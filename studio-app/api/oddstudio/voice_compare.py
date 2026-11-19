"""Kokoro vs Piper: identical dialogue, each character voiced by both engines on the worker's CPU, with timings and
resource use. Clips are stored as assets so the owner can listen side by side (Settings > Voice generation).
Nothing here changes the production voice settings or any character's assigned voice.
"""
from __future__ import annotations

import time

try:
    import resource   # Linux (the server worker); not available on Windows
except ImportError:
    resource = None

from .tasks import Ctx, by_key, store_asset, task

LINES = [
    ("character-01", "Okay. Nobody panic. The party is in the other room, and he does not suspect a thing."),
    ("leo", "Who took my charger? It was right here a minute ago!"),
    ("ben", "Uh... I swear it wasn't me. Probably. Maybe."),
    ("maya", "Oh, this charger? I've been using it all morning. You're welcome."),
]
# Proposed Kokoro voices per character (matching the character's voice style; owner can change them later)
KOKORO_VOICES = {"character-01": "am_michael", "leo": "bm_george", "ben": "am_puck", "maya": "af_heart"}


def _usage():
    if resource is None:
        return time.process_time(), 0.0, 0.0
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime, c.ru_utime + c.ru_stime, s.ru_maxrss / 1024   # cpu self, cpu children, MB peak


@task
def voice_compare(ctx: Ctx) -> dict:
    from . import kokoro, providers
    from .settings_store import get_section
    db, job = ctx.db, ctx.job
    chars = by_key(db)
    folder = ctx.folder("voice-compare", job.id)
    cfg = get_section(db, "voice")
    t0 = time.time()
    kokoro.engine()                                   # model load (and first-run download) measured separately
    load_s = round(time.time() - t0, 2)
    rows = []
    for key, text in LINES:
        c = chars.get(key)
        if c is None:
            continue
        row = {"character": key, "name": c.name, "text": text}
        for engine_name, voice in (("piper", c.voice or cfg.get("default_voice") or ""),
                                   ("kokoro", KOKORO_VOICES.get(key, kokoro.DEFAULT_VOICE))):
            cs0, cc0, _ = _usage()
            w0 = time.time()
            f = providers.speak({"provider": engine_name, "default_voice": ""}, text, voice, folder / f"{key}-{engine_name}")
            wall = time.time() - w0
            cs1, cc1, peak = _usage()
            secs = providers.audio_seconds(f)
            a = store_asset(db, ep_id=None, src=f, key=f"voice-compare/job{job.id}/{f.name}", kind="voice-compare",
                            label=f"{c.name} ({engine_name})", content_type="audio/wav", job_id=job.id)
            row[engine_name] = {"voice": voice.split("/")[-1].split("\\")[-1], "asset_id": a.id, "audio_seconds": round(secs, 2),
                                "generation_seconds": round(wall, 2), "cpu_seconds": round((cs1 - cs0) + (cc1 - cc0), 2),
                                "real_time_factor": round(wall / secs, 2) if secs else None, "peak_worker_mb": round(peak)}
        rows.append(row)
        ctx.log(f"{c.name}: piper {row['piper']['generation_seconds']} s, kokoro {row['kokoro']['generation_seconds']} s")
    db.commit()
    return {"rows": rows, "kokoro_load_seconds": load_s,
            "note": "CPU seconds include the Piper subprocess; peak memory is the worker process (Kokoro runs in-process)."}
