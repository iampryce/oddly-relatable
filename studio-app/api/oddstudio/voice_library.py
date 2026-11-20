"""Voice library and auto-casting. The owner keeps a shortlist of approved Fish Audio voices in Settings (one per line:
`voice id | label | him/her/neutral | description`). New characters are given the best match for their voice style
automatically; the Characters page can also ask the AI writer to pick one. Nothing here overwrites a voice the owner
set, and every pick can be changed on the character."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Character

HEX_ID = re.compile(r"[0-9a-f]{32}")
GENDERS = {"him": "him", "he": "him", "male": "him", "man": "him", "m": "him",
           "her": "her", "she": "her", "female": "her", "woman": "her", "f": "her",
           "neutral": "neutral", "any": "neutral", "": "neutral"}
STOP = {"the", "and", "with", "for", "who", "that", "his", "her", "him", "she", "very", "a", "an", "of", "to", "in", "is", "it"}


@dataclass
class LibVoice:
    id: str
    label: str
    gender: str
    description: str


def _extract_id(text: str) -> str:
    """A voice id, or a fish.audio page URL that contains one (modelId=<id> or /m/<id>)."""
    m = HEX_ID.search(text.strip().lower())
    return m.group(0) if m else ""


def parse_library(text: str) -> list[LibVoice]:
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        vid = _extract_id(parts[0])
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(LibVoice(vid, parts[1] if len(parts) > 1 and parts[1] else vid[:8],
                            GENDERS.get(parts[2].lower() if len(parts) > 2 else "", "neutral"),
                            parts[3] if len(parts) > 3 else ""))
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in STOP}


def _fish_id(voice: str) -> str:
    return voice[5:] if (voice or "").startswith("fish:") else ""


def used_ids(db: Session) -> set[str]:
    return {_fish_id(v) for (v,) in db.query(Character.voice).filter(Character.voice.like("fish:%")).all()}


def _score(c_style: str, bubble: str, v: LibVoice, taken: set[str]) -> float:
    score = 0.0
    if bubble in ("him", "her"):
        score += 3 if v.gender == bubble else (1 if v.gender == "neutral" else -3)
    score += len(_words(c_style) & _words(f"{v.label} {v.description}"))
    if v.id in taken:
        score -= 2     # prefer a voice no other character uses
    return score


def heuristic_pick(lib: list[LibVoice], voice_style: str, bubble_style: str, taken: set[str]) -> LibVoice | None:
    if not lib:
        return None
    return max(lib, key=lambda v: (_score(voice_style, bubble_style, v, taken), -lib.index(v)))


def ai_pick(provider, lib: list[LibVoice], name: str, description: str, voice_style: str, bubble_style: str,
            taken: set[str]) -> tuple[LibVoice | None, str]:
    """Ask the text model to choose from the library. Returns (voice, reason); (None, '') on any failure."""
    catalogue = "\n".join(f"- {v.id} | {v.label} | {v.gender} | {v.description}" + (" | already used by another character" if v.id in taken else "")
                          for v in lib)
    system = "You cast voices for short comedy videos. Reply with JSON only."
    prompt = (f"Character: {name}\nDescription: {description}\nHow they sound: {voice_style}\nBubble style (him/her/neutral): {bubble_style}\n\n"
              f"Voice library (id | label | gender | description):\n{catalogue}\n\n"
              'Choose the single best voice id from the library. Prefer a voice no other character uses. '
              'Return JSON: {"id": "<voice id from the library>", "reason": "<one short sentence>"}')
    try:
        answer = provider.complete_json(system, prompt)
        vid = _extract_id(str(answer.get("id", "")))
        match = next((v for v in lib if v.id == vid), None)
        return (match, str(answer.get("reason", ""))[:300]) if match else (None, "")
    except Exception:    # noqa: BLE001 - any provider problem falls back to the built-in match
        return None, ""


def suggest(db: Session, c: Character, use_ai: bool = True) -> dict:
    """A suggested `fish:<id>` voice for a character (not saved)."""
    from .providers import text_provider
    from .settings_store import get_section
    lib = parse_library(get_section(db, "voice").get("library", ""))
    if not lib:
        return {"voice": "", "reason": "The voice library is empty. Add voices under Settings > Voice generation."}
    taken = used_ids(db) - {_fish_id(c.voice)}
    pick, reason, ai = None, "", False
    if use_ai:
        pick, reason = ai_pick(text_provider(get_section(db, "text")), lib, c.name, c.description, c.voice_style, c.bubble_style, taken)
        ai = pick is not None
    if pick is None:
        pick = heuristic_pick(lib, c.voice_style, c.bubble_style, taken)
        reason = "best match on gender and how they sound"
    return {"voice": f"fish:{pick.id}", "label": pick.label, "reason": reason, "ai": ai}


def assign_new(db: Session, c: Character, taken: set[str]) -> str | None:
    """Give a newly introduced character a library voice (built-in match: instant, free, no model call). An existing voice
    is never overwritten. Returns the label assigned, or None."""
    from .settings_store import get_section
    if c.voice:
        return None
    lib = parse_library(get_section(db, "voice").get("library", ""))
    pick = heuristic_pick(lib, c.voice_style, c.bubble_style, taken)
    if pick is None:
        return None
    c.voice = f"fish:{pick.id}"
    taken.add(pick.id)
    return pick.label
