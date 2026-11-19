"""The script document: what the AI writer must return and what the owner edits.

A script is plain data (never hard-coded storylines). It is validated on every save, so an invalid edit is refused
with a precise message instead of failing later in production.

{
  "title": "...", "logline": "...", "hook": "on-screen hook text (optional)", "twist": "what the unexpected turn is",
  "interactive": {"type": "none" | "viewer-choice" | "poll", "question": "...", "options": ["A", "B"]},
  "characters": [{"key": "<character key>", "role": "..."}],
  "new_characters": [{"key": "dad", "name": "Dad", "description": "who they are", "visual_description": "how they look",
                      "bubble_style": "him|her|neutral", "voice_style": "how they sound"}],     (optional: cast this story introduces)
  "scenes": [{
      "id": "s1", "heading": "...", "location": "<environment id or free text>", "description": "...",
      "action": "...", "camera": "...",
      "lines": [{"speaker": "<character key>", "text": "...", "expression": "neutral", "shot": "wide|medium|close",
                 "duration": 2.0, "delivery": "optional voice direction, e.g. whispered, panicked",
                 "gesture": "optional acting gesture", "move": {"type": "enter|exit|walk_to|sit|stand|jump", "to": "seat|<key>"},
                 "look_at": "<character key>", "reactions": [{"character": "<key>", "gesture": "...", "expression": "..."}]}]
  }]
}
"""
from __future__ import annotations

import re

SHOTS = ("wide", "medium", "close")
INTERACTIVE = ("none", "viewer-choice", "poll")
MAX_LINE_CHARS = 140
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
KEY = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class ScriptError(ValueError):
    pass


def _str(obj: dict, key: str, where: str, required: bool = True, max_len: int = 2000) -> str:
    v = obj.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ScriptError(f"{where}.{key} must be text")
    v = v.strip()
    if required and not v:
        raise ScriptError(f"{where}.{key} is required")
    if len(v) > max_len:
        raise ScriptError(f"{where}.{key} is too long (max {max_len} characters)")
    return v


# Limits per format. Shorts keep their original limits; long episodes (D-L3: 3 acts, 5–7 minutes) allow more scenes and a
# larger cast (still at most 4 on screen per scene, checked when the scene is built).
LIMITS = {"short": {"scenes": 12, "characters": 4}, "long": {"scenes": 60, "characters": 8}}


# Acting instructions (optional per line; the studio rig animator performs them). Unknown values are dropped, not
# rejected, so a writer's creative wording never fails a whole script.
GESTURES = ("none", "open_palms", "point", "shrug", "arms_up", "head_scratch", "hands_on_hips", "hand_on_chest",
            "facepalm", "thumbs_up", "wave", "beat", "cross_arms", "hands_on_head")
MOVES = ("enter", "exit", "walk_to", "sit", "stand", "jump")


def acting(ln: dict, keys: list[str], where: str) -> dict:
    out = {}
    g = str(ln.get("gesture") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if g in GESTURES and g != "none":
        out["gesture"] = g
    mv = ln.get("move")
    if isinstance(mv, str):
        mv = {"type": mv}
    if isinstance(mv, dict) and str(mv.get("type", "")).lower() in MOVES:
        m = {"type": str(mv["type"]).lower()}
        to = str(mv.get("to") or "").strip().lower()
        if to and (to in keys or to in ("seat", "left", "right", "center")):
            m["to"] = to
        out["move"] = m
    look = str(ln.get("look_at") or "").strip()
    if look in keys:
        out["look_at"] = look
    reacts = []
    for r in ln.get("reactions") or []:
        if isinstance(r, dict) and r.get("character") in keys:
            rr = {"character": r["character"]}
            rg = str(r.get("gesture") or "").strip().lower().replace(" ", "_")
            if rg in GESTURES and rg != "none":
                rr["gesture"] = rg
            if r.get("expression"):
                rr["expression"] = str(r["expression"])[:40].lower()
            if len(rr) > 1:
                reacts.append(rr)
    if reacts:
        out["reactions"] = reacts[:3]
    return out


def validate_script(doc: dict, known_characters: set[str] | None = None, fmt: str = "short") -> dict:
    """Return a normalised copy of the script or raise ScriptError naming the first problem."""
    if not isinstance(doc, dict):
        raise ScriptError("script must be an object")
    out = {
        "title": _str(doc, "title", "script", max_len=100),
        "logline": _str(doc, "logline", "script", required=False, max_len=400),
        "hook": _str(doc, "hook", "script", required=False, max_len=60),
        "twist": _str(doc, "twist", "script", required=False, max_len=400),
    }
    inter = doc.get("interactive") or {"type": "none"}
    if not isinstance(inter, dict) or inter.get("type", "none") not in INTERACTIVE:
        raise ScriptError(f"script.interactive.type must be one of {', '.join(INTERACTIVE)}")
    out["interactive"] = {"type": inter.get("type", "none")}
    if out["interactive"]["type"] != "none":
        out["interactive"]["question"] = _str(inter, "question", "script.interactive", max_len=120)
        opts = inter.get("options") or []
        if not isinstance(opts, list) or not 2 <= len(opts) <= 4 or not all(isinstance(o, str) and o.strip() for o in opts):
            raise ScriptError("script.interactive.options must be 2 to 4 short texts")
        out["interactive"]["options"] = [o.strip()[:60] for o in opts]

    new_chars = doc.get("new_characters") or []
    if not isinstance(new_chars, list) or len(new_chars) > 4:
        raise ScriptError("script.new_characters must be a list of at most 4 characters")
    out["new_characters"] = []
    for i, c in enumerate(new_chars):
        where = f"script.new_characters[{i}]"
        if not isinstance(c, dict):
            raise ScriptError(f"{where} must be an object")
        key = _str(c, "key", where, max_len=40).lower()
        if not KEY.match(key):
            raise ScriptError(f"{where}.key must be lowercase letters, digits and dashes, starting with a letter")
        style = (c.get("bubble_style") or "neutral").strip().lower()
        if style not in ("him", "her", "neutral"):
            style = "neutral"
        entry = {"key": key, "name": _str(c, "name", where, max_len=120),
                 "description": _str(c, "description", where, required=False),
                 "visual_description": _str(c, "visual_description", where),
                 "bubble_style": style, "voice_style": _str(c, "voice_style", where, required=False, max_len=600)}
        if known_characters is not None and key in known_characters:
            continue   # already in the studio: the story simply reuses that character
        out["new_characters"].append(entry)
    if known_characters is not None:
        known_characters = set(known_characters) | {c["key"] for c in out["new_characters"]}

    chars = doc.get("characters")
    if not isinstance(chars, list) or not chars:
        raise ScriptError("script.characters must list at least one character")
    keys = []
    out["characters"] = []
    for i, c in enumerate(chars):
        where = f"script.characters[{i}]"
        if not isinstance(c, dict):
            raise ScriptError(f"{where} must be an object")
        key = _str(c, "key", where, max_len=60)
        if key in keys:
            raise ScriptError(f"{where}.key {key!r} is listed twice")
        if known_characters is not None and key not in known_characters:
            raise ScriptError(f"{where}.key {key!r} is not a character in the studio (create it under Characters first)")
        keys.append(key)
        out["characters"].append({"key": key, "role": _str(c, "role", where, required=False, max_len=200)})
    lim = LIMITS[fmt]
    if len(keys) > lim["characters"]:
        raise ScriptError(f"script.characters: at most {lim['characters']} characters per episode")

    scenes = doc.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ScriptError("script.scenes must contain at least one scene")
    if len(scenes) > lim["scenes"]:
        raise ScriptError(f"script.scenes: at most {lim['scenes']} scenes")
    out["scenes"] = []
    seen = set()
    for si, s in enumerate(scenes):
        where = f"script.scenes[{si}]"
        if not isinstance(s, dict):
            raise ScriptError(f"{where} must be an object")
        sid = _str(s, "id", where, required=False, max_len=40) or f"s{si + 1}"
        sid = sid.lower()
        if not ID.match(sid) or sid in seen:
            raise ScriptError(f"{where}.id must be unique, lowercase letters, digits and dashes")
        seen.add(sid)
        scene = {"id": sid, "heading": _str(s, "heading", where, max_len=200),
                 "location": _str(s, "location", where, required=False, max_len=80),
                 "description": _str(s, "description", where, required=False),
                 "action": _str(s, "action", where, required=False),
                 "camera": _str(s, "camera", where, required=False, max_len=400), "lines": []}
        lines = s.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ScriptError(f"{where}.lines must contain at least one line")
        if len(lines) > 24:
            raise ScriptError(f"{where}.lines: at most 24 lines per scene")
        for li, ln in enumerate(lines):
            lw = f"{where}.lines[{li}]"
            if not isinstance(ln, dict):
                raise ScriptError(f"{lw} must be an object")
            spk = _str(ln, "speaker", lw, max_len=60)
            if spk not in keys:
                raise ScriptError(f"{lw}.speaker {spk!r} is not in script.characters")
            text = _str(ln, "text", lw, max_len=MAX_LINE_CHARS)
            shot = (ln.get("shot") or "wide").strip().lower()
            if shot not in SHOTS:
                raise ScriptError(f"{lw}.shot must be one of {', '.join(SHOTS)}")
            line = {"speaker": spk, "text": text, "expression": _str(ln, "expression", lw, required=False, max_len=40).lower() or "neutral",
                    "shot": shot}
            delivery = _str(ln, "delivery", lw, required=False, max_len=120)
            if delivery:
                line["delivery"] = delivery
            line.update(acting(ln, keys, lw))
            if ln.get("duration") is not None:
                d = ln["duration"]
                if not isinstance(d, (int, float)) or not 0.8 <= d <= 8:
                    raise ScriptError(f"{lw}.duration must be between 0.8 and 8 seconds")
                line["duration"] = round(float(d), 2)
            scene["lines"].append(line)
        if s.get("act") is not None:
            if s["act"] not in (1, 2, 3):
                raise ScriptError(f"{where}.act must be 1, 2 or 3")
            scene["act"] = s["act"]
        elif fmt == "long":
            raise ScriptError(f"{where}.act is required in a long episode (1, 2 or 3)")
        out["scenes"].append(scene)
    if fmt == "long":
        acts = [sc["act"] for sc in out["scenes"]]
        if acts != sorted(acts):
            raise ScriptError("script.scenes must run act 1, then act 2, then act 3")
    return out


def estimated_seconds(script: dict) -> float:
    """Rough runtime: explicit durations, else reading time (the engine's own timing decides the exact value)."""
    total = 0.0
    for s in script["scenes"]:
        for ln in s["lines"]:
            total += ln.get("duration") or max(1.5, min(5.0, 0.9 + len(ln["text"]) / 14))
    return round(total, 1)
