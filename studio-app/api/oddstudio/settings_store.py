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
              "fish_default_voice": "",
              # Approved Fish voices for auto-casting, one per line: voice id | label | him/her/neutral | description
              "library": ""},
    # Media storage. "local": the server volume. "s3": new media goes to the bucket (credentials under Credentials);
    # media saved before the switch keeps being served from the server volume.
    "storage": {"backend": "", "bucket": "", "region": "", "prefix": "oddly-relatable/"},
    # AI video generation on a ComfyUI server (GPU). Empty URL: not connected.
    "comfyui": {"url": ""},
    # Self-hosted GPU worker (docs/GPU-INFRASTRUCTURE.md §11; gpu.py). mode: off | own (worker_url, a machine we own) |
    # rented (a RunPod Secure Cloud pod per session, terminated when idle). The monthly cap applies to rented sessions
    # (separate from fal.ai's budget); the owner's accepted defaults: $50, warn at 80%, 5 min idle, 120 min lifetime.
    "gpu": {"mode": "off", "worker_url": "", "provider": "runpod", "gpu_type": "NVIDIA H100 PCIe", "image": "",
            "disk_gb": 150, "monthly_cap_usd": 50.0, "warn_at": 0.8, "idle_minutes": 5, "max_lifetime_minutes": 120},
    # Reference analysis (Create from Reference): speech-to-text with word timestamps, and frame analysis.
    "transcription": {"provider": "none", "model": "", "fallback": "none", "language": ""},
    # notes_cap_usd: the most one episode's video notes may cost (checked before the upload; owner default $0.50)
    "vision": {"provider": "none", "model": "", "fallback": "none", "notes_cap_usd": 0.5},
    # Character animation. Only the procedural rig is planned for production use; generative motion is evaluated
    # per provider before it is enabled (see capabilities.py).
    "motion": {"provider": "none", "model": "", "fallback": "none", "budget_usd": 25.0,
               # talking shots in the shot comparison: which hosted provider, and the hard cap per plan (all its runs)
               "talking_provider": "wavespeed-infinitetalk-fast", "talking_plan_cap_usd": 0.50},
    "lipsync": {"provider": "rhubarb", "fallback": "none"},
    "sound": {"provider": "none", "model": "", "fallback": "none"},
    # dialogue_display: what new episodes show of the dialogue (bubbles | none | captions); each episode can change it
    "production": {"environment": "living-room-empty-03", "max_seconds": 60, "fps": 30, "dialogue_display": "none",
                   "end_card": "Oddly Relatable"},
    "youtube": {"default_privacy": "private", "category_id": "23", "default_tags": ["stickman", "funny", "relatable", "comedy"]},
    "creative": {"house_style": (
        "Original, relatable everyday comedy with expressive stickman characters. Short scenes, fast setups, "
        "exaggerated reactions, a clear escalation and an unexpected twist near the end. Comedic timing: setup, "
        "pause, reaction, payoff. Dialogue is short (bubbles hold one short sentence). Silent reaction beats use "
        "short sounds like \"...\", \"!!\" or \"Hm.\". Adult-oriented, relatable humor for grown-ups; no explicit "
        "sexual content. Never copy existing creators' characters, catchphrases or specific sketches; take inspiration "
        "only from the general genre."),
        # House style of all new character and set images: v1 (the original look, kept as rollback) | v2 (adult minimal
        # stick-figure style, owner decision 2026-11-20). Existing approved art is never changed by switching.
        "style_version": "v1"},
}

TEXT_PROVIDERS = ("none", "codex-cli", "openai", "anthropic")
IMAGE_PROVIDERS = ("none", "codex-cli", "openai")
DIALOGUE_DISPLAYS = ("bubbles", "none", "captions")
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
    if key == "creative" and "style_version" in value:
        from .house_style import STYLE_VERSIONS
        if value["style_version"] not in STYLE_VERSIONS:
            raise ValueError(f"creative.style_version must be one of {', '.join(STYLE_VERSIONS)}")
    if key == "production" and value.get("dialogue_display", "none") not in DIALOGUE_DISPLAYS:
        raise ValueError(f"production.dialogue_display must be one of {', '.join(DIALOGUE_DISPLAYS)}")
    if key == "gpu":
        check_gpu(value)
    if key == "motion":
        from .shot_compare import TALKING
        if "talking_provider" in value and value["talking_provider"] not in TALKING:
            raise ValueError(f"motion.talking_provider must be one of {', '.join(TALKING)}")
        cap = value.get("talking_plan_cap_usd", 0.5)
        if not (isinstance(cap, (int, float)) and 0 < cap <= 10):
            raise ValueError("motion.talking_plan_cap_usd must be more than 0 and at most 10")
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


def check_gpu(v: dict) -> None:
    """Settings > GPU worker: refused values never reach the worker or the provider."""
    from urllib.parse import urlparse
    if v.get("mode", "off") not in ("off", "own", "rented"):
        raise ValueError("gpu.mode must be off, own or rented")
    if v.get("provider", "runpod") != "runpod":
        raise ValueError("gpu.provider: only runpod has an adapter")
    url = v.get("worker_url", "")
    if url:
        u = urlparse(url)
        local = u.hostname in ("localhost", "127.0.0.1")
        if not u.hostname or u.scheme not in ("https", "http") or (u.scheme == "http" and not local) or u.username or u.password:
            raise ValueError("gpu.worker_url must be an https:// address (http only for localhost)")
    img = v.get("image", "")
    if img and ("@sha256:" not in img or any(ch.isspace() for ch in img)):
        raise ValueError("gpu.image must be pinned by digest (name@sha256:…)")
    rng = {"monthly_cap_usd": (0, 1000), "warn_at": (0.1, 1), "idle_minutes": (1, 60), "max_lifetime_minutes": (15, 480),
           "disk_gb": (20, 500)}
    for k, (lo, hi) in rng.items():
        if k in v and not (isinstance(v[k], (int, float)) and not isinstance(v[k], bool) and lo <= v[k] <= hi):
            raise ValueError(f"gpu.{k} must be between {lo} and {hi}")
    gt = v.get("gpu_type", "")
    if gt and (len(gt) > 60 or not all(ch.isalnum() or ch in " -_." for ch in gt)):
        raise ValueError("gpu.gpu_type is not a GPU type name")


def _codex_login() -> str:
    from .providers import codex_login_state
    return codex_login_state()


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
        "codex_login": _codex_login(),
        "youtube": bool(secret("youtube_client_id") and secret("youtube_client_secret") and secret("youtube_refresh_token")),
        "storage": storage_config()["backend"],
        "s3_bucket_set": bool(storage_config()["bucket"]),
        "ffmpeg": bool(s.ffmpeg and s.ffprobe),
        "redis": bool(s.redis_url),
    }
