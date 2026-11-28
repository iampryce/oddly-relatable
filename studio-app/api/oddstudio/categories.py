"""Video categories: which engines, voices and rules each kind of video uses (owner, 2026-11-27).

The first step of the "New short" wizard is choosing a category. A category only names capability providers that
already exist in `capabilities.CAPABILITIES` (or are listed there as planned); it never replaces them.
`easy_path` marks what to build and test first (free: code kit + Gemini TTS).
"""
from __future__ import annotations

CATEGORIES: dict[str, dict] = {
    "stickman_short": {
        "label": "Narrated stick-man shorts", "characters": "cast library (approved stick men)",
        "motion": ["procedural-rig", "code-kit", "fal"], "voice": ["gemini-tts", "kokoro", "piper", "openai"],
        "formats": ["9:16", "16:9"], "length_s": (30, 600), "synthetic_tick": False, "source_text_check": False,
        "easy_path": True,
    },
    "cinematic": {
        "label": "Real cinematic movies", "characters": "invented realistic actors",
        "motion": ["omni-flash", "fal"], "voice": ["gemini-tts", "openai", "elevenlabs"],
        "formats": ["16:9", "9:16"], "length_s": (30, 600), "synthetic_tick": True, "source_text_check": False,
        "easy_path": False,
    },
    "cartoon_kit": {
        "label": "Cartoon sketches (cartoon-short-kit)", "characters": "kit characters",
        "motion": ["code-kit"], "voice": ["gemini-tts", "kokoro", "piper"],
        "formats": ["16:9", "9:16"], "length_s": (30, 600), "synthetic_tick": False, "source_text_check": False,
        "easy_path": True,
    },
    "bible": {
        "label": "Bible stories", "characters": "invented realistic actors",
        "motion": ["omni-flash", "fal"], "voice": ["gemini-tts", "openai", "elevenlabs"],
        "formats": ["16:9", "9:16"], "length_s": (60, 600), "synthetic_tick": True, "source_text_check": True,
        "easy_path": False,
    },
}


def get(category: str) -> dict:
    if category not in CATEGORIES:
        raise KeyError(f"unknown category {category!r}; choose one of {', '.join(CATEGORIES)}")
    return CATEGORIES[category]


def easy_path() -> list[str]:
    return [k for k, v in CATEGORIES.items() if v["easy_path"]]
