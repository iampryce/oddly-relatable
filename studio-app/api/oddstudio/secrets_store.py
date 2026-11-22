"""Provider credentials entered in Settings.

Stored encrypted (Fernet, key derived from SESSION_SECRET) in the `settings` table under the reserved key "_secrets".
The API only ever reports whether a secret is set, never its value. Server environment variables still work and are
used when no value was entered in Settings, so existing deployments keep working.

Workers read secrets through `secret(name)`, which caches for a few seconds so a key saved in Settings reaches the
running worker without a restart.
"""
from __future__ import annotations

import base64
import hashlib
import os
import time

from .config import get_settings

ROW = "_secrets"
# name -> environment variable used when nothing is saved in Settings
SECRETS = {
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "fish_api_key": "FISH_API_KEY",
    "aws_access_key_id": "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
    "youtube_client_id": "YOUTUBE_CLIENT_ID",
    "youtube_client_secret": "YOUTUBE_CLIENT_SECRET",
    "youtube_refresh_token": "YOUTUBE_REFRESH_TOKEN",
    "comfyui_token": "COMFYUI_TOKEN",
    "runpod_api_key": "RUNPOD_API_KEY",          # rented GPU sessions (gpu.py); used only by the studio, never sent to a pod
    "gpu_worker_token": "GPU_WORKER_TOKEN",      # our own GPU machine's worker token (mode "own")
    "fal_key": "FAL_KEY",
}
_cache: tuple[float, dict] | None = None
TTL = 5.0


def _fernet():
    from cryptography.fernet import Fernet
    s = get_settings().session_secret or "dev-only-secret-not-for-production"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("oddstudio-secrets:" + s).encode()).digest()))


def _load(db=None) -> dict:
    """Decrypted secrets saved in Settings (empty when none or when SESSION_SECRET changed)."""
    from .db import new_session
    from .models import Setting
    own = db is None
    db = db or new_session()
    try:
        row = db.get(Setting, ROW)
        enc = dict(row.value) if row else {}
    finally:
        if own:
            db.close()
    f, out = _fernet(), {}
    for k, v in enc.items():
        try:
            out[k] = f.decrypt(v.encode()).decode()
        except Exception:  # unreadable (secret key rotated): treat as not set
            pass
    return out


def secret(name: str, db=None) -> str:
    global _cache
    if name not in SECRETS:
        raise KeyError(name)
    if db is not None or _cache is None or time.time() - _cache[0] > TTL:
        try:
            _cache = (time.time(), _load(db))
        except Exception:  # database not ready (first start, tests without tables): environment only
            _cache = (time.time(), {})
    return _cache[1].get(name) or os.environ.get(SECRETS[name], "")


def put_secrets(db, values: dict[str, str | None]) -> dict:
    """Set (non-empty string) or clear (None or "") secrets. Returns presence flags."""
    global _cache
    from .models import Setting
    unknown = set(values) - set(SECRETS)
    if unknown:
        raise ValueError(f"unknown credentials: {', '.join(sorted(unknown))}")
    row = db.get(Setting, ROW)
    enc = dict(row.value) if row else {}
    f = _fernet()
    for k, v in values.items():
        if v:
            enc[k] = f.encrypt(v.strip().encode()).decode()
        else:
            enc.pop(k, None)
    if row:
        row.value = enc
    else:
        db.add(Setting(key=ROW, value=enc))
    db.commit()
    _cache = None
    return presence(db)


def presence(db=None) -> dict:
    """{name: {"set": bool, "source": "settings" | "environment" | ""}} -- never values."""
    saved = _load(db)
    out = {}
    for k, env in SECRETS.items():
        src = "settings" if saved.get(k) else ("environment" if os.environ.get(env) else "")
        out[k] = {"set": bool(src), "source": src}
    return out
