"""Unified provider registry: production capabilities -> providers.

One place that says, for every capability the studio needs, which providers exist, what each needs (credentials,
installed tools), whether its adapter is implemented in this code base, and how it is tested. The Settings page,
the provider test jobs and the workers all read this registry.

Status shown to the owner is never assumed:
  implemented  the adapter exists in this code base (False = evaluated/planned only)
  configured   its credentials / tools are present on the server
  verified     the most recent real worker test for it SUCCEEDED (see tasks_providers.provider_test)
A provider whose adapter only checks a connection says so ("test": "connection only").

Selection per capability lives in the settings section named by "section": provider (primary), fallback, model,
enabled, plus provider-specific fields. Existing sections (text, image, voice, storage, youtube, comfyui) keep their
keys, so nothing that already works changes.
"""
from __future__ import annotations

import shutil

from .config import get_settings
from .secrets_store import secret

# need: credential names (secrets_store) or "tool:<name>" (a binary on the worker)
CAPABILITIES: dict[str, dict] = {
    "script": {"label": "Script and story generation", "section": "text", "providers": {
        "openai": {"label": "OpenAI", "needs": ["openai_api_key"], "implemented": True, "default_model": "gpt-4.1-mini"},
        "anthropic": {"label": "Anthropic Claude", "needs": ["anthropic_api_key"], "implemented": True, "default_model": "claude-sonnet-5-5"},
        "codex-cli": {"label": "Codex CLI (ChatGPT subscription)", "needs": ["tool:codex"], "implemented": True},
    }},
    "transcription": {"label": "Audio transcription and speech analysis", "section": "transcription", "providers": {
        "openai": {"label": "OpenAI transcription (word timestamps)", "needs": ["openai_api_key"], "implemented": True, "default_model": "whisper-1"},
        "local-whisper": {"label": "Local Whisper (free, CPU on the worker)", "needs": ["tool:faster-whisper"], "implemented": True, "default_model": "base.en"},
    }},
    "vision": {"label": "Video and visual reference analysis", "section": "vision", "providers": {
        "openai": {"label": "OpenAI vision", "needs": ["openai_api_key"], "implemented": True, "default_model": "gpt-4.1-mini"},
        "anthropic": {"label": "Anthropic Claude vision", "needs": ["anthropic_api_key"], "implemented": True, "default_model": "claude-sonnet-5-5"},
    }},
    "image": {"label": "Character and image generation", "section": "image", "providers": {
        "openai": {"label": "OpenAI Images API", "needs": ["openai_api_key"], "implemented": True, "default_model": "gpt-image-2"},
        "codex-cli": {"label": "Codex CLI image generation (workstation only)", "needs": ["tool:codex"], "implemented": True},
        "comfyui": {"label": "ComfyUI workflow (GPU server)", "needs": ["setting:comfyui.url"], "implemented": False,
                    "note": "connection test only; no image workflow adapter yet"},
    }},
    "voice": {"label": "Voice generation", "section": "voice", "providers": {
        "piper": {"label": "Piper (free, local)", "needs": ["tool:piper"], "implemented": True},
        "kokoro": {"label": "Kokoro-82M (free, local CPU; Apache-2.0)", "needs": ["tool:kokoro"], "implemented": True},
        "openai": {"label": "OpenAI TTS", "needs": ["openai_api_key"], "implemented": True, "default_model": "gpt-4o-mini-tts"},
        "elevenlabs": {"label": "ElevenLabs", "needs": ["elevenlabs_api_key"], "implemented": True, "default_model": "eleven_multilingual_v2"},
    }},
    "motion": {"label": "Motion and character animation", "section": "motion", "providers": {
        "procedural-rig": {"label": "Studio 2D rig animator (procedural, CPU, free)", "needs": ["tool:rhubarb"], "implemented": True,
                           "note": "performs the script's acting (gestures, walking, sitting, reactions) with Rhubarb lip sync"},
        "fal": {"label": "fal.ai hosted open models (Wan 2.2, LTX-2)", "needs": ["fal_key"], "implemented": True,
                "note": "paid per clip; estimated cost shown before each run; capped by the experimental budget"},
        "comfyui": {"label": "ComfyUI image-to-video workflow (GPU)", "needs": ["setting:comfyui.url"], "implemented": False,
                    "note": "connection test only"},
        "runway": {"label": "Runway", "needs": ["runway_api_key"], "implemented": False, "note": "evaluated, not integrated"},
        "luma": {"label": "Luma", "needs": ["luma_api_key"], "implemented": False, "note": "evaluated, not integrated"},
        "kling": {"label": "Kling", "needs": ["kling_api_key"], "implemented": False, "note": "evaluated, not integrated"},
    }},
    "lipsync": {"label": "Lip sync (audio-driven mouth shapes)", "section": "lipsync", "providers": {
        "rhubarb": {"label": "Rhubarb Lip Sync (free, local)", "needs": ["tool:rhubarb"], "implemented": True},
    }},
    "sound": {"label": "Music and sound effects", "section": "sound", "providers": {
        "elevenlabs": {"label": "ElevenLabs sound effects", "needs": ["elevenlabs_api_key"], "implemented": True},
    }},
    "storage": {"label": "Media storage", "section": "storage", "providers": {
        "local": {"label": "Server volume", "needs": [], "implemented": True},
        "s3": {"label": "AWS S3", "needs": ["setting:storage.bucket"], "implemented": True},
    }},
    "publishing": {"label": "Publishing", "section": "youtube", "providers": {
        "youtube": {"label": "YouTube Data API", "needs": ["youtube_client_id", "youtube_client_secret", "youtube_refresh_token"],
                    "implemented": True},
    }},
}

# capability -> provider_test stage name (tasks_providers.TARGETS keys)
TEST_STAGE = {"script": "text", "transcription": "transcription", "vision": "vision", "image": "image", "voice": "voice",
              "lipsync": "lipsync", "sound": "sound", "storage": "storage", "publishing": "youtube", "motion": "motion"}


def tool_present(name: str) -> bool:
    s = get_settings()
    if name == "codex":
        return bool(shutil.which(s.codex_bin))
    if name == "piper":
        return bool(shutil.which(s.piper_bin))
    if name == "kokoro":
        from .kokoro import installed
        return installed()
    if name == "rhubarb":
        from .analysis import rhubarb_bin
        return bool(rhubarb_bin())
    if name == "faster-whisper":
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False
    return bool(shutil.which(name))


def status(db, tests: dict) -> dict:
    """Registry with live status for the Settings page. Never includes credential values."""
    from .settings_store import get_section
    out = {}
    for cap, spec in CAPABILITIES.items():
        sec = get_section(db, spec["section"]) if spec["section"] else {}
        provs = {}
        for pid, p in spec["providers"].items():
            missing = []
            for need in p["needs"]:
                if need.startswith("tool:"):
                    if not tool_present(need[5:]):
                        missing.append(need)
                elif need.startswith("setting:"):
                    s_name, field = need[8:].split(".")
                    if not get_section(db, s_name).get(field):
                        missing.append(need)
                elif need not in _known_secrets() or not secret(need, db):
                    # an unknown credential name belongs to a provider that is not integrated yet
                    missing.append(need)
            target = "comfyui:comfyui" if pid == "comfyui" else f"{TEST_STAGE.get(cap, cap)}:{pid}"
            t = tests.get(target)
            provs[pid] = {**{k: v for k, v in p.items() if k != "needs"}, "needs": p["needs"], "missing": missing,
                          "configured": not missing, "test_target": target,
                          "verified": bool(t and t.get("status") == "succeeded" and p["implemented"]),
                          "last_test": t}
        out[cap] = {"label": spec["label"], "section": spec["section"], "selected": sec.get("provider"),
                    "fallback": sec.get("fallback"), "enabled": sec.get("enabled", True), "providers": provs}
    return out


def _known_secrets() -> set[str]:
    from .secrets_store import SECRETS
    return set(SECRETS)


def provider_ids(cap: str) -> tuple[str, ...]:
    return ("none",) + tuple(CAPABILITIES[cap]["providers"])
