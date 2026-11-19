"""Test harness: a fresh SQLite database and work folder per test case, the owner signed in, and a way to run queued
jobs in-process (no Redis needed). The fake text provider is only available because ODD_ENV=test."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oddstudio.auth import hash_password  # noqa: E402

PASSWORD = "correct horse battery staple"


def sample_script(title="Group Chat Emergency", speaker="character-01"):
    return {
        "title": title, "logline": "A man misreads one text and spirals.", "hook": "One text. Total panic.",
        "twist": "It was his own reminder.", "interactive": {"type": "viewer-choice", "question": "Would you have panicked?",
                                                              "options": ["Yes, instantly", "No, I'm calm"]},
        "characters": [{"key": speaker, "role": "the panicking guy"}],
        "scenes": [
            {"id": "s1", "heading": "The text", "location": "living-room-empty-03", "description": "He reads a message.",
             "action": "Freezes mid-step.", "camera": "Wide, then push to his face",
             "lines": [{"speaker": speaker, "text": "We need to talk...?", "expression": "worried", "shot": "wide", "duration": 2.0},
                       {"speaker": speaker, "text": "WHAT DID I DO", "expression": "shocked", "shot": "close", "duration": 1.6}]},
            {"id": "s2", "heading": "The twist", "location": "living-room-empty-03", "description": "He checks the sender.",
             "action": "Slowly lowers the phone.", "camera": "Medium",
             "lines": [{"speaker": speaker, "text": "...it's from me.", "expression": "deadpan", "shot": "medium", "duration": 2.0}]},
        ],
    }


def fake_pose_image(prompt, out_file, reference):
    """Test stand-in for an image model: a bold-outlined figure on a FLAT WHITE background (not transparent), so the
    studio's cut-out step is exercised exactly as with real model output. The face colour varies with the prompt."""
    from PIL import Image, ImageDraw
    import hashlib
    tint = hashlib.sha256(prompt.encode()).digest()
    img = Image.new("RGB", (512, 768), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([176, 60, 336, 220], fill=(240, 200 - tint[0] % 60, 160), outline=(0, 0, 0), width=8)    # head
    d.rectangle([206, 220, 306, 470], fill=(40 + tint[1] % 150, 90, 180), outline=(0, 0, 0), width=8)   # body
    d.line([216, 470, 196, 700], fill=(0, 0, 0), width=10)                                                 # legs
    d.line([296, 470, 316, 700], fill=(0, 0, 0), width=10)
    d.line([176, 700, 216, 700], fill=(0, 0, 0), width=10)                                                 # feet
    d.line([296, 700, 336, 700], fill=(0, 0, 0), width=10)
    img.save(out_file)
    return out_file


def fake_voice(text, voice, instructions, out_file):
    """Test stand-in for a voice model: a tone whose length follows the text (about 14 characters per second)."""
    import math, struct, wave
    seconds = max(0.6, len(text) / 14)
    rate = 24000
    freq = 180 + sum(map(ord, voice or "")) % 120   # each voice sounds different (so a re-voiced line changes)
    f = out_file.with_suffix(".wav")
    with wave.open(str(f), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(int(seconds * rate))))
    return f


class Env:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oddstudio-test-"))
        os.environ.update({
            "ODD_ENV": "test", "DATABASE_URL": f"sqlite:///{(self.tmp / 'test.db').as_posix()}", "REDIS_URL": "",
            "ODD_WORK_DIR": str(self.tmp / "work"), "OWNER_EMAIL": "owner@example.com", "COOKIE_SECURE": "false",
            "OWNER_PASSWORD_HASH": hash_password(PASSWORD, iterations=1000), "SESSION_SECRET": "t" * 40, "STORAGE_BACKEND": "local",
        })
        from oddstudio import config, db, queue, storage
        config.reset_settings(); db.reset_engine(); storage.reset_storage(); queue.reset_queue()
        from oddstudio.db import Base, engine
        import oddstudio.models  # noqa: F401
        Base.metadata.create_all(engine())
        from fastapi.testclient import TestClient
        from oddstudio.main import app
        self.client = TestClient(app)
        self.client.__enter__()   # runs startup (seeds Character 01)

    def login(self):
        r = self.client.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        assert r.status_code == 200, r.text
        return self

    def run_jobs(self, kinds=None, max_rounds=20):
        """Run queued jobs (optionally only some kinds), including jobs they queue, like a worker would."""
        from oddstudio.db import new_session
        from oddstudio.models import Job
        from oddstudio.tasks import run_job
        ran = []
        for _ in range(max_rounds):
            with new_session() as s:
                q = s.query(Job).filter_by(status="queued")
                if kinds:
                    q = q.filter(Job.kind.in_(kinds))
                ids = [j.id for j in q.order_by(Job.id)]
            if not ids:
                break
            for jid in ids:
                with new_session() as s:
                    j = run_job(s, jid)
                    if j is not None:
                        ran.append((j.kind, j.status, j.error))
        return ran

    def close(self):
        self.client.__exit__(None, None, None)
        from oddstudio import db
        db.reset_engine()
        shutil.rmtree(self.tmp, ignore_errors=True)
