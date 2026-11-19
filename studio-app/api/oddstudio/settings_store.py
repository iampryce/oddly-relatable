"""Owner-editable, non-secret settings, stored in the `settings` table. Secrets are never stored here."""
from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from .config import get_settings
from .secrets_store import secret
from .models import Setting

DEFAULTS: dict[str, dict] = {
    # Text generation (scripts, section and scene regeneration).
    "text": {"provider": "none", "model": "", "temperature": 0.9, "fallback": "none", "fallback_model": ""},
    # Image generation (character poses, scene reference images). Off until the owner turns it on.
    "image": {"provider": "none", "model": "", "size": "1024x1536", "fallback": "none"},
    # Voiceover. "none": the video carries the engine's built-in SFX only. Each character's voice is set on the character.
    "voice": {"provider": "none", "model": "", "voices": {}, "default_voice": "", "gain": 1.0, "fallback": "none",
              # Fish Audio voice id used when Fish is the fallback (or for its test when no character has a Fish voice)
              "fish_default_voice": ""},
    # Media storage. "local": the server volume. "s3": new media goes to the bucket (credentials under Credentials);
    # media saved before the switch keeps being served from the server volume.
    "storage": {"backend": "", "bucket": "", "region": "", "prefix": "oddly-relatable/"},
    # AI video generation on a ComfyUI server (GPU). Empty URL: not connected.
    "comfyui": {"url": ""},
    # Reference analysis (Create from Reference): speech-to-text with word timestamps, and frame analysis.
    "transcription": {"provider": "none", "model": "", "fallback": "none", "language": ""},
    "vision": {"provider": "none", "model": "", "fallback": "none"},
    # Character animation. Only the procedural rig is planned for production use; generative motion is evaluated
    # per provider before it is enabled (see capabilities.py).
    "motion": {"provider": "none", "model": "", "fallback": "none", "budget_usd": 25.0},
    "lipsync": {"provider": "rhubarb", "fallback": "none"},
    "sound": {"provider": "none", "model": "", "fallback": "none"},
    "production": {"environment": "living-room-empty-03", "max_seconds": 60, "fps": 30,
                   "end_card": "Oddly Relatable"},
    "youtube": {"default_privacy": "private", "category_id": "23", "default_tags": ["stickman", "funny", "relatable", "comedy"]},
    "creative": {"house_style": (
        "Original, relatable everyday comedy with expressive stickman characters. Short scenes, fast setups, "
        "exaggerated reactions, a clear escalation and an unexpected twist near the end. Comedic timing: setup, "
        "pause, reaction, payoff. Dialogue is short (bubbles hold one short sentence). Silent reaction beats use "
        "short sounds like \"...\", \"!!\" or \"Hm.\". Family-friendly for a general audience. Never copy existing "
        "creators' characters, catchphrases or specific sketches; take inspiration only from the general genre.")},
}

TEXT_PROVIDERS = ("none", "codex-cli", "openai", "anthropic")
IMAGE_PROVIDERS = ("none", "codex-cli", "openai")
VOICE_PROVIDERS = ("none", "openai", "elevenlabs", "piper", "kokoro", "fish")


def get_section(db: Session, key: str) -> dict:
    value = copy.deepcopy(DEFAULTS[key])
    row = db.get(Setting, key)
    if row:
        value.update(row.value)
    return value


def all_sections(db: Session) -> dict:
    return {k: get_section(db, k) for k in DEFAULTS}


def put_section(db: Session, key: str, value: dict) -> dict:
    if key not in DEFAULTS:
        raise KeyError(key)
    allowed = set(DEFAULTS[key])
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown {key} settings: {', '.join(sorted(unknown))}")
    from .capabilities import provider_ids
    choices = {"text": TEXT_PROVIDERS, "image": IMAGE_PROVIDERS, "voice": VOICE_PROVIDERS,
               "transcription": provider_ids("transcription"), "vision": provider_ids("vision"),
               "motion": provider_ids("motion"), "lipsync": provider_ids("lipsync"), "sound": provider_ids("sound")}.get(key)
    if choices and "provider" in value and value["provider"] not in choices:
        raise ValueError(f"{key}.provider must be one of {', '.join(choices)}")
    if choices and "fallback" in value and value["fallback"] not in choices:
        raise ValueError(f"{key}.fallback must be one of {', '.join(choices)}")
    from .capabilities import CAPABILITIES
    cap = next((c for c, spec in CAPABILITIES.items() if spec["section"] == key), None)
    for field in ("provider", "fallback"):
        pid = value.get(field)
        if cap and pid and pid != "none" and pid in CAPABILITIES[cap]["providers"] and not CAPABILITIES[cap]["providers"][pid]["implemented"]:
            raise ValueError(f"{CAPABILITIES[cap]['providers'][pid]['label']} is not integrated yet and cannot be selected")
    if key == "storage" and value.get("backend", "") not in ("", "local", "s3"):
        raise ValueError("storage.backend must be local or s3")
    if key == "voice" and "gain" in value and not (isinstance(value["gain"], (int, float)) and 0.2 <= value["gain"] <= 2):
        raise ValueError("voice.gain must be between 0.2 and 2")
    if key == "youtube" and value.get("default_privacy", "private") not in ("private", "unlisted", "public"):
        raise ValueError("youtube.default_privacy must be private, unlisted or public")
    merged = get_section(db, key)
    merged.update(value)
    row = db.get(Setting, key)
    if row:
        row.value = merged
    else:
        db.add(Setting(key=key, value=merged))
    db.commit()
    return merged


def integrations_status() -> dict:
    """Which credentials and tools are present. Values are never returned."""
    import shutil
    from .storage import storage_config
    s = get_settings()
    return {
        "openai_api_key": bool(secret("openai_api_key")),
        "anthropic_api_key": bool(secret("anthropic_api_key")),
        "elevenlabs_api_key": bool(secret("elevenlabs_api_key")),
        "fish_api_key": bool(secret("fish_api_key")),
        "piper": bool(shutil.which(s.piper_bin)),
        "codex_cli": bool(shutil.which(s.codex_bin)),
        "youtube": bool(secret("youtube_client_id") and secret("youtube_client_secret") and secret("youtube_refresh_token")),
        "storage": storage_config()["backend"],
        "s3_bucket_set": bool(storage_config()["bucket"]),
        "ffmpeg": bool(s.ffmpeg and s.ffprobe),
        "redis": bool(s.redis_url),
    }
