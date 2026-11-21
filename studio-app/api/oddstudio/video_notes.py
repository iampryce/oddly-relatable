"""Video reference notes for audio episodes ("reference, not copy", owner decision 2026-11-21).

When the owner uploads a video and asks for notes, a few frames from the part of the video the episode uses (the
Short's window, or the whole clip for a long episode) are shown ONCE to the studio's API vision provider. It returns
staging notes as structured JSON per time range: shot type, anonymous roles (speaker, reactor 1..n), approximate
blocking, emotions as plain words, setting type and camera movement. Every field is an enumeration: a value outside it
is dropped and counted, so names of people or characters, faces, appearance, clothing, brands, logos, on-screen text
and dialogue can never be stored. Only these text notes are kept (the frames and the video are deleted); the scene
writer reads them as soft suggestions and never changes the recorded dialogue.

Pure functions on plain data (no database, no files), so the rules are tested directly.
"""
from __future__ import annotations

import math
import re

FRAME_EVERY = 4.5          # s between sampled frames
FRAME_CAP = 24             # never more frames than this per clip
FRAME_WIDTH = 512          # px, frames are downscaled before they are sent
MAX_RANGES = 40
MAX_ROLES = 6

SHOTS = ("wide", "medium", "close")
CAMERA = ("static", "pan", "tilt", "zoom in", "zoom out", "handheld", "tracking")
POSITIONS = ("left", "center", "right", "background")
POSES = ("standing", "seated", "walking", "leaning", "lying")
FACING_FIXED = ("camera", "away", "left", "right")
EMOTIONS = ("neutral", "calm", "happy", "amused", "laughing", "excited", "proud", "smug", "surprised", "shocked",
            "confused", "curious", "worried", "nervous", "anxious", "scared", "sad", "disappointed", "embarrassed",
            "awkward", "annoyed", "irritated", "frustrated", "angry", "bored", "tired", "skeptical", "pleading",
            "relieved", "determined", "serious", "deadpan")
SETTINGS = ("office", "meeting room", "kitchen", "living room", "bedroom", "bathroom", "hallway", "dining room",
            "restaurant", "cafe", "bar", "shop", "supermarket", "street", "car", "bus", "train", "park", "garden",
            "beach", "school", "classroom", "hospital", "gym", "stage", "studio", "lobby", "elevator", "outdoors",
            "indoors", "other")
FURNITURE = ("long table", "round table", "desk", "sofa", "counter", "bed", "bench", "none")
TIME_OF_DAY = ("daytime", "evening", "night")
ROLE = re.compile(r"^(speaker|reactor ([1-9]))$")
TOP_KEYS = {"ranges"}
RANGE_KEYS = {"start", "end", "shot", "camera", "setting", "furniture", "time", "roles"}
ROLE_KEYS = {"role", "position", "pose", "facing", "emotion"}

# Emotion words -> the rig's expressions (used by the deterministic scene split for reactions)
EMOTION_EXPRESSION = {"happy": "happy", "amused": "happy", "excited": "happy", "proud": "smug", "smug": "smug",
                      "laughing": "laughing", "relieved": "happy", "surprised": "shocked", "shocked": "shocked",
                      "scared": "shocked", "confused": "confused", "curious": "confused", "skeptical": "deadpan",
                      "worried": "worried", "nervous": "worried", "anxious": "worried", "sad": "sad",
                      "disappointed": "sad", "tired": "deadpan", "bored": "deadpan", "deadpan": "deadpan",
                      "embarrassed": "embarrassed", "awkward": "embarrassed", "annoyed": "annoyed",
                      "irritated": "annoyed", "frustrated": "annoyed", "angry": "angry", "pleading": "pleading",
                      "serious": "neutral", "determined": "neutral", "calm": "neutral", "neutral": "neutral"}


# ------------------------------------------------------------------ sampling and cost
def frame_times(start: float, end: float, every: float = FRAME_EVERY, cap: int = FRAME_CAP) -> list[float]:
    """Frame times (absolute, in the video) inside [start, end): one every `every` seconds, centred in its slot; more
    widely spaced when that would exceed `cap`."""
    length = max(0.0, end - start)
    if length <= 0:
        return []
    n = min(cap, max(1, math.ceil(length / every)))
    step = length / n
    return [round(start + step * (k + 0.5), 2) for k in range(n)]


# Estimate only (list prices known to the studio, per million tokens; image tokens per downscaled frame)
PRICES = {"openai": {"model": "gpt-4.1-mini", "in": 0.40, "out": 1.60, "per_frame": 260},
          "anthropic": {"model": "claude-sonnet-5-5", "in": 2.00, "out": 10.00, "per_frame": 200}}
PROMPT_TOKENS, OUT_PER_FRAME, OUT_BASE = 900, 60, 150


def estimate(seconds: float, provider: str, model: str = "") -> dict:
    """What one notes call is expected to cost for a clip (or window) of `seconds`: frames, tokens and USD (an upper
    estimate from list prices; the actual token usage is recorded with the notes)."""
    frames = len(frame_times(0.0, seconds))
    p = PRICES.get(provider)
    if not p:
        return {"frames": frames, "configured": False}
    tin = PROMPT_TOKENS + frames * p["per_frame"]
    tout = OUT_BASE + frames * OUT_PER_FRAME
    usd = (tin * p["in"] + tout * p["out"]) / 1e6
    priced = model or p["model"]
    return {"frames": frames, "configured": True, "provider": provider, "model": priced, "input_tokens": tin,
            "output_tokens": tout, "usd": round(usd, 4),
            "note": "" if priced == p["model"] else f"priced as {p['model']}; {priced} may cost differently"}


# ------------------------------------------------------------------ the prompt
def prompt(times: list[float]) -> str:
    when = "; ".join(f"frame {i + 1} at {t:.1f} s" for i, t in enumerate(times))
    return (
        "You are helping stage an ORIGINAL 2D animated comedy scene. The frames below come from a reference video; we "
        "will never copy it. Describe only how the scene is staged, as anonymous roles.\n"
        f"Frames ({when}; times in seconds from the start of the part being used).\n"
        "Return JSON only: {\"ranges\": [{\"start\": s, \"end\": s, \"shot\": ..., \"camera\": ..., \"setting\": ..., \"furniture\": ..., \"time\": ..., "
        "\"roles\": [{\"role\": ..., \"position\": ..., \"pose\": ..., \"facing\": ..., \"emotion\": ...}]}]}\n"
        "Group consecutive frames with the same staging into one range. Allowed values ONLY:\n"
        f"- shot: {', '.join(SHOTS)}\n- camera: {', '.join(CAMERA)}\n- setting: {', '.join(SETTINGS)}\n"
        f"- furniture (the main piece in view): {', '.join(FURNITURE)}\n- time: {', '.join(TIME_OF_DAY)}\n"
        "- role: \"speaker\" (whoever seems to be talking) or \"reactor 1\" .. \"reactor 9\" for the others\n"
        f"- position: {', '.join(POSITIONS)}\n- pose: {', '.join(POSES)}\n"
        f"- facing: {', '.join(FACING_FIXED)}, or another role (e.g. \"speaker\", \"reactor 2\")\n"
        f"- emotion: one of {', '.join(EMOTIONS)}\n"
        "Never output names of real people, actors or characters, never describe faces, appearance, bodies, clothing, "
        "age, gender or ethnicity, never mention brands or logos, never transcribe on-screen text or dialogue. "
        "If unsure of a value, leave the field out.")


# ------------------------------------------------------------------ validation (redaction)
def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _role_label(v) -> str | None:
    s = re.sub(r"\s+", " ", str(v or "").strip().lower())
    return s if ROLE.match(s) else None


def clean_notes(raw, duration: float) -> tuple[list[dict], int]:
    """Keep only the schema: returns (ranges, redacted) where `redacted` counts every key or value that was dropped
    (unknown keys, values outside the enumerations, free text). Ranges are clamped to [0, duration] and sorted."""
    redacted = 0
    if not isinstance(raw, dict):
        return [], 1
    redacted += len(set(raw) - TOP_KEYS)
    out = []
    for r in (raw.get("ranges") if isinstance(raw.get("ranges"), list) else [])[: MAX_RANGES * 2]:
        if not isinstance(r, dict):
            redacted += 1
            continue
        redacted += len(set(r) - RANGE_KEYS)
        start, end = _num(r.get("start")), _num(r.get("end"))
        if start is None or end is None:
            redacted += 1
            continue
        start, end = max(0.0, min(start, duration)), max(0.0, min(end, duration))
        if end <= start:
            redacted += 1
            continue
        rng = {"start": round(start, 2), "end": round(end, 2)}
        for key, allowed in (("shot", SHOTS), ("camera", CAMERA), ("setting", SETTINGS), ("furniture", FURNITURE),
                             ("time", TIME_OF_DAY)):
            if key in r:
                v = str(r[key] or "").strip().lower()
                if v in allowed:
                    rng[key] = v
                else:
                    redacted += 1
        roles = []
        for ro in (r.get("roles") if isinstance(r.get("roles"), list) else [])[: MAX_ROLES * 2]:
            if not isinstance(ro, dict):
                redacted += 1
                continue
            redacted += len(set(ro) - ROLE_KEYS)
            label = _role_label(ro.get("role"))
            if not label or any(x["role"] == label for x in roles):
                redacted += 1
                continue
            entry = {"role": label}
            for key, allowed in (("position", POSITIONS), ("pose", POSES), ("emotion", EMOTIONS)):
                if key in ro:
                    v = str(ro[key] or "").strip().lower()
                    if v in allowed:
                        entry[key] = v
                    else:
                        redacted += 1
            if "facing" in ro:
                v = str(ro["facing"] or "").strip().lower()
                if v in FACING_FIXED or (_role_label(v) and v != label):
                    entry["facing"] = v
                else:
                    redacted += 1
            roles.append(entry)
            if len(roles) >= MAX_ROLES:
                break
        if roles:
            rng["roles"] = roles
        out.append(rng)
    out.sort(key=lambda x: (x["start"], x["end"]))
    return out[:MAX_RANGES], redacted


# ------------------------------------------------------------------ alignment and use
def shift(ranges: list[dict], delta: float, length: float) -> list[dict]:
    """Ranges moved by `delta` seconds (a Short's window moved) and clipped to [0, length]; ranges outside are dropped."""
    out = []
    for r in ranges:
        s, e = max(0.0, r["start"] + delta), min(length, r["end"] + delta)
        if e > s:
            out.append({**r, "start": round(s, 2), "end": round(e, 2)})
    return out


def align(ranges: list[dict], lines: list[dict]) -> list[dict]:
    """Each range with the ids of the recorded lines it overlaps (the notes' timestamps are the audio's)."""
    return [{**r, "line_ids": [ln["id"] for ln in lines if ln["start"] < r["end"] and ln["end"] > r["start"]]}
            for r in ranges]


def for_line(ranges: list[dict], line: dict) -> dict | None:
    """The range that covers most of a recorded line (None when no range touches it)."""
    best, cover = None, 0.0
    for r in ranges:
        c = min(r["end"], line["end"]) - max(r["start"], line["start"])
        if c > cover:
            best, cover = r, c
    return best


def describe(r: dict) -> str:
    """One readable line for the writer's prompt (text only; every value is from the enumerations)."""
    parts = [f"shot {r['shot']}" if r.get("shot") else "", f"camera {r['camera']}" if r.get("camera") else "",
             f"setting {r['setting']}" if r.get("setting") else "",
             f"furniture {r['furniture']}" if r.get("furniture") and r["furniture"] != "none" else "",
             r.get("time", "")]
    for ro in r.get("roles", []):
        bits = [ro.get(k) for k in ("position", "pose") if ro.get(k)]
        if ro.get("facing"):
            bits.append(f"facing {ro['facing']}")
        if ro.get("emotion"):
            bits.append(ro["emotion"])
        parts.append(f"{ro['role']}: {', '.join(bits)}" if bits else ro["role"])
    return "; ".join(p for p in parts if p)


# The proposed set, assembled by a fixed sentence from the notes' list values only (owner decision 2026-11-21: no AI
# wording for audio episodes; the owner edits the text before anything is generated)
SENTENCE_WORDS = {"an", "original", "room", "with", "a", "people", "person", "seated", "standing", "facing", "each", "other",
                  "the", "mood", "is"}


def _most(values):
    values = [v for v in values if v]
    return max(dict.fromkeys(values), key=lambda v: (values.count(v), -values.index(v))) if values else ""


def proposal_text(ranges: list[dict]) -> str:
    """e.g. "An original dining room with a long table, daytime, 4 people seated facing each other; the mood is tense."
    Every word is either a fixed word of this sentence or a value from the notes' lists (never free text)."""
    setting = _most(r.get("setting") for r in ranges if r.get("setting") not in ("other", "indoors", "outdoors"))
    furniture = _most(r.get("furniture") for r in ranges if r.get("furniture") != "none")
    time = _most(r.get("time") for r in ranges)
    seated = max((sum(1 for ro in r.get("roles", []) if ro.get("pose") == "seated") for r in ranges), default=0)
    standing = max((sum(1 for ro in r.get("roles", []) if ro.get("pose") in ("standing", "leaning")) for r in ranges), default=0)
    facing = any(ro.get("facing", "").startswith(("speaker", "reactor")) for r in ranges for ro in r.get("roles", []))
    mood = _most(ro.get("emotion") for r in ranges for ro in r.get("roles", []))
    text = f"An original {setting or 'room'}" + (f" with a {furniture}" if furniture else "") + (f", {time}" if time else "")
    if seated:
        text += f", {seated} {'person' if seated == 1 else 'people'} seated" + (" facing each other" if facing and seated > 1 else "")
    if standing:
        text += f", {standing} {'person' if standing == 1 else 'people'} standing"
    if mood:
        text += f"; the mood is {mood}"
    return text + "."


def summary(ranges: list[dict]) -> dict:
    """The older hints (people count, setting, mood) derived from the notes, for the cast suggestion."""
    people = max((len(r.get("roles", [])) for r in ranges), default=0)
    def most(values):   # the most frequent value; on a tie, the one that comes first in time
        values = [v for v in values if v]
        return max(dict.fromkeys(values), key=lambda v: (values.count(v), -values.index(v))) if values else ""
    return {"people_count": people or None, "setting": most(r.get("setting") for r in ranges),
            "mood": most(ro.get("emotion") for r in ranges for ro in r.get("roles", []))}
