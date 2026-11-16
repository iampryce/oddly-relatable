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
