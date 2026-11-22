"""Set notes from the reference video (owner request 2026-11-22): what each distinct room looks like, in WORDS ONLY.

A few frames per room (taken from the frames the video notes already sample; one room per setting after the notes'
smoothing, so a short flip to another angle is not a new room) are shown once to the studio's API vision provider, in
the same job as the video notes. It answers from fixed lists only: room size, the main piece of furniture and where it
sits, how many seats and how they are arranged, each piece of furniture as item / shape / material / colour / place,
the walls, floor, ceiling and light as plain colour words, and the mood. Anything outside the lists is removed and
counted, so names, brands, logos, on-screen text, artwork and people can never be stored. The frames and the video are
deleted after the job; no frame ever goes to an image generator.

Each room's notes become one sentence assembled only from those list words (`room_text`). The owner can edit it in
the episode page; "Propose from the video notes" uses it verbatim, one proposal per room.

Pure functions on plain data, so the rules are tested directly.
"""
from __future__ import annotations

import math
import re

from . import video_notes as VN

MAX_ROOMS = 4
FRAMES_PER_ROOM = 3
MAX_ITEMS = 10
OUT_PER_ROOM = 320            # output tokens per room (estimate)

SIZES = ("small", "medium", "large")
ARRANGEMENTS = ("around a table", "side by side", "facing each other", "in a row facing the camera", "behind a desk",
                "scattered", "none")
ITEMS = ("desk", "long table", "round table", "meeting table", "dining table", "coffee table", "side table", "chair",
         "office chair", "armchair", "sofa", "stool", "bench", "bookshelf", "shelf", "cabinet", "filing cabinet",
         "counter", "bar counter", "kitchen counter", "bed", "wardrobe", "dresser", "lamp", "floor lamp", "ceiling light",
         "pendant light", "plant", "window", "door", "rug", "whiteboard", "screen", "picture frame", "curtains", "blinds",
         "fridge", "sink", "stove", "mirror", "clock", "radiator", "coat stand", "water cooler", "printer")
# items whose real content could be text or artwork: always drawn blank
BLANK = {"whiteboard": "a blank whiteboard", "screen": "a blank dark screen", "picture frame": "a plain empty frame",
         "clock": "a plain clock face"}
SHAPES = ("rectangular", "square", "round", "oval", "L-shaped", "long", "low", "tall", "narrow", "wide", "curved")
MATERIALS = ("wood", "light wood", "dark wood", "metal", "glass", "fabric", "leather", "plastic", "stone", "laminate",
             "wicker", "marble", "tiles", "concrete")
COLOURS = ("white", "off-white", "cream", "beige", "light grey", "grey", "dark grey", "charcoal", "black", "navy", "blue",
           "light blue", "sky blue", "teal", "turquoise", "mint", "green", "sage green", "olive", "dark green", "yellow",
           "pale yellow", "mustard", "orange", "peach", "terracotta", "red", "burgundy", "pink", "dusty pink", "purple",
           "lilac", "brown", "tan", "light brown", "dark brown", "chrome", "gold")
PLACES = ("left wall", "right wall", "back wall", "centre", "front left", "front right", "back left corner",
          "back right corner", "ceiling", "floor")
FLOORS = ("carpet", "wood planks", "parquet", "tiles", "concrete", "vinyl", "linoleum", "stone", "rug on wood")
LIGHTS = ("bright daylight", "soft daylight", "overcast daylight", "cool fluorescent light", "warm lamp light",
          "dim light", "evening light", "night with city light", "neon light", "spotlights")
MOODS = ("tidy", "cluttered", "corporate", "homely", "shabby", "sterile", "busy", "quiet", "tense", "cheerful", "gloomy",
         "modern", "old-fashioned", "luxurious", "cramped", "spacious")
ROOM_KEYS = {"room", "size", "seats", "arrangement", "main", "furniture", "walls", "floor", "ceiling", "light", "mood"}
ITEM_KEYS = {"item", "shape", "material", "colour", "place"}
WORDS = (set(SIZES) | set(ARRANGEMENTS) | set(ITEMS) | set(SHAPES) | set(MATERIALS) | set(COLOURS) | set(PLACES)
         | set(FLOORS) | set(LIGHTS) | set(MOODS) | set(VN.SETTINGS) | set(BLANK.values()))


# ------------------------------------------------------------------ rooms and frames
def rooms(ranges: list[dict]) -> list[dict]:
    """The distinct rooms of the (smoothed) notes, in order of first appearance: [{room, start, end, seconds, people}].
    A setting word is one room (the notes' smoothing already folds short flips into the room they belong to)."""
    out: dict[str, dict] = {}
    for r in ranges:
        s = r.get("setting") or "room"
        if s in ("indoors", "outdoors", "other"):
            s = "room"
        e = out.setdefault(s, {"room": s, "spans": [], "seconds": 0.0, "people": 0, "seated": 0})
        e["spans"].append((r["start"], r["end"]))
        e["seconds"] += r["end"] - r["start"]
        e["people"] = max(e["people"], len(r.get("roles", [])))
        e["seated"] = max(e["seated"], sum(1 for ro in r.get("roles", []) if ro.get("pose") == "seated"))
    rs = sorted(out.values(), key=lambda x: -x["seconds"])[:MAX_ROOMS]     # the longest rooms when there are many
    return sorted(rs, key=lambda x: x["spans"][0][0])


def pick_frames(room: dict, frames: list[dict], k: int = FRAMES_PER_ROOM) -> list[float]:
    """Up to k frame times inside the room's spans, spread over its time; wide shots preferred."""
    inside = [f for f in frames if any(a <= f["t"] < b for a, b in room["spans"])]
    if not inside:
        return []
    wide = [f for f in inside if f.get("shot") == "wide"]
    pool = wide if len(wide) >= k else inside
    if len(pool) <= k:
        return [f["t"] for f in pool]
    step = len(pool) / k
    return [pool[int(step * (i + 0.5))]["t"] for i in range(k)]


# ------------------------------------------------------------------ cost
def estimate(provider: str, rooms_n: int = 2) -> dict:
    """The extra vision call for the set notes: frames, tokens and USD (list prices, upper estimate). Before an upload
    the number of rooms is unknown: two rooms are assumed."""
    from .notes_v2 import CALIBRATION
    frames = rooms_n * FRAMES_PER_ROOM
    p = VN.PRICES.get(provider)
    if not p:
        return {"frames": frames, "configured": False}
    tin = VN.PROMPT_TOKENS + 300 + frames * p["per_frame"]
    tout = VN.OUT_BASE + rooms_n * OUT_PER_ROOM
    usd = round((tin * p["in"] + tout * p["out"]) / 1e6 * CALIBRATION.get(provider, 1.0), 4)
    return {"frames": frames, "rooms_assumed": rooms_n, "configured": True, "input_tokens": tin, "output_tokens": tout, "usd": usd}


# ------------------------------------------------------------------ the prompt
def prompt(groups: list[tuple[str, int]]) -> str:
    """groups: (room word, number of frames) in the order the frames are attached."""
    n, parts = 0, []
    for i, (word, k) in enumerate(groups):
        parts.append(f"room {i + 1} ({word}): frames {n + 1}-{n + k}" if k > 1 else f"room {i + 1} ({word}): frame {n + 1}")
        n += k
    L = lambda xs: ", ".join(xs)
    return (
        "You are helping design an ORIGINAL, EMPTY 2D cartoon set inspired by the kind of room in a reference video that "
        "we will never copy. Describe only the room itself, in words from the lists below. Ignore all people.\n"
        f"The frames show these rooms: {'; '.join(parts)}.\n"
        'Return JSON only: {"rooms": [{"room": 1, "size": ..., "seats": 0, "arrangement": ..., "main": {"item": ..., '
        '"place": ...}, "furniture": [{"item": ..., "shape": ..., "material": ..., "colour": ..., "place": ...}], '
        '"walls": ..., "floor": {"colour": ..., "material": ...}, "ceiling": ..., "light": ..., "mood": [...]}]}\n'
        f"One entry per room, at most {MAX_ITEMS} furniture items each (windows, doors, shelves, plants and lamps count as "
        "furniture with their place). Allowed values ONLY:\n"
        f"- size: {L(SIZES)}\n- seats: a whole number (chairs, stools and sofa places)\n- arrangement: {L(ARRANGEMENTS)}\n"
        f"- item: {L(ITEMS)}\n- shape: {L(SHAPES)}\n- material: {L(MATERIALS)}\n- colour (also walls, ceiling, floor "
        f"colour): {L(COLOURS)}\n- place: {L(PLACES)}\n- floor material: {L(FLOORS)}\n- light: {L(LIGHTS)}\n"
        f"- mood (at most 2): {L(MOODS)}\n"
        "Never output names, brands, logos, any written text or signs, artwork or pictures on walls, screens' content, "
        "or anything about the people. If unsure of a value, leave the field out.")


# ------------------------------------------------------------------ validation (redaction)
def _pick(v, allowed) -> str | None:
    s = re.sub(r"\s+", " ", str(v or "").strip().lower())
    return s if s in allowed else None


def clean(raw, words: list[str]) -> tuple[list[dict], int]:
    """Keep only the schema: one entry per known room (room words in `words`), every value from the lists. Returns
    (rooms, stripped) where stripped counts every key or value removed."""
    stripped = 0
    if not isinstance(raw, dict):
        return [], 1
    stripped += len(set(raw) - {"rooms"})
    out, seen = [], set()
    for r in (raw.get("rooms") if isinstance(raw.get("rooms"), list) else [])[: len(words) * 2]:
        if not isinstance(r, dict):
            stripped += 1
            continue
        stripped += len(set(r) - ROOM_KEYS)
        k = r.get("room")
        k = int(k) if isinstance(k, (int, float)) and not isinstance(k, bool) and float(k).is_integer() else None
        if k is None or not 1 <= k <= len(words) or k in seen:
            stripped += 1
            continue
        seen.add(k)
        e: dict = {"room": words[k - 1]}
        for key, allowed in (("size", SIZES), ("arrangement", ARRANGEMENTS), ("walls", COLOURS), ("ceiling", COLOURS),
                             ("light", LIGHTS)):
            if key in r:
                v = _pick(r[key], allowed)
                if v:
                    e[key] = v
                else:
                    stripped += 1
        if "seats" in r:
            s = r["seats"]
            if isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) and 0 <= s <= 20:
                e["seats"] = int(s)
            else:
                stripped += 1
        if "main" in r:
            m = r["main"] if isinstance(r["main"], dict) else {}
            stripped += len(set(m) - {"item", "place"}) + (0 if isinstance(r["main"], dict) else 1)
            item, place = _pick(m.get("item"), ITEMS), _pick(m.get("place"), PLACES)
            stripped += (m.get("item") is not None and not item) + (m.get("place") is not None and not place)
            if item:
                e["main"] = {"item": item, **({"place": place} if place else {})}
        if "floor" in r:
            f = r["floor"] if isinstance(r["floor"], dict) else {}
            stripped += len(set(f) - {"colour", "material"}) + (0 if isinstance(r["floor"], dict) else 1)
            fl = {k2: v for k2, v in (("colour", _pick(f.get("colour"), COLOURS)), ("material", _pick(f.get("material"), FLOORS))) if v}
            stripped += sum(1 for k2 in ("colour", "material") if f.get(k2) is not None and k2 not in fl)
            if fl:
                e["floor"] = fl
        items = []
        for it in (r.get("furniture") if isinstance(r.get("furniture"), list) else [])[: MAX_ITEMS * 2]:
            if not isinstance(it, dict):
                stripped += 1
                continue
            stripped += len(set(it) - ITEM_KEYS)
            name = _pick(it.get("item"), ITEMS)
            if not name:
                stripped += 1
                continue
            x = {"item": name}
            for key, allowed in (("shape", SHAPES), ("material", MATERIALS), ("colour", COLOURS), ("place", PLACES)):
                if key in it:
                    v = _pick(it[key], allowed)
                    if v:
                        x[key] = v
                    else:
                        stripped += 1
            items.append(x)
            if len(items) >= MAX_ITEMS:
                break
        if items:
            e["furniture"] = items
        if "mood" in r:
            ms = r["mood"] if isinstance(r["mood"], list) else [r["mood"]]
            keep = [m for m in (_pick(x, MOODS) for x in ms) if m][:2]
            stripped += len(ms) - len(keep)
            if keep:
                e["mood"] = keep
        out.append(e)
    return out, stripped


# ------------------------------------------------------------------ the sentence
def _a(phrase: str) -> str:
    return ("an " if phrase[:1] in "aeiou" else "a ") + phrase


def _item(it: dict) -> str:
    if it["item"] in BLANK:
        base = BLANK[it["item"]]
    else:
        desc = " ".join(x for x in (it.get("colour"), it.get("material"), it.get("shape"), it["item"]) if x)
        base = _a(desc)
    if it.get("place") in ("ceiling", "floor"):
        return f"{base} on the {it['place']}"
    return f"{base} by the {it['place']}" if it.get("place") and "wall" in it["place"] else \
        (f"{base} in the {it['place']}" if it.get("place") else base)


def room_text(e: dict) -> str:
    """One sentence from the list words only, e.g. "A medium office: light grey walls, a blue carpet floor, a white
    ceiling, cool fluorescent light. A long desk in the centre, 3 seats behind a desk. Furniture: ...; mood: tidy." """
    room = e.get("room", "room")
    head = f"{e['size'].capitalize()} {room}" if e.get("size") else room.capitalize()
    surf = []
    if e.get("walls"):
        surf.append(f"{e['walls']} walls")
    fl = e.get("floor") or {}
    if fl:
        surf.append(_a(" ".join(x for x in (fl.get("colour"), fl.get("material")) if x)) + " floor")
    if e.get("ceiling"):
        surf.append(f"{_a(e['ceiling'])} ceiling")
    if e.get("light"):
        surf.append(e["light"])
    s = (f"An original {head.lower()}" if not e.get("size") else f"An original {e['size']} {room}") + \
        (": " + ", ".join(surf) if surf else "") + "."
    m = e.get("main")
    if m:
        s += f" {_a(m['item']).capitalize()}" + (f" at the {m['place']}" if m.get("place") else "")
        if e.get("seats"):
            s += f", {e['seats']} {'seat' if e['seats'] == 1 else 'seats'}" + \
                 (f" {e['arrangement']}" if e.get("arrangement") and e["arrangement"] != "none" else "")
        s += "."
    elif e.get("seats"):
        s += f" {e['seats']} {'seat' if e['seats'] == 1 else 'seats'}" + \
             (f" {e['arrangement']}" if e.get("arrangement") and e["arrangement"] != "none" else "") + "."
    items = [it for it in e.get("furniture", []) if not (m and it["item"] == m["item"] and not it.get("colour"))]
    if items:
        s += " Furniture: " + "; ".join(_item(it) for it in items) + "."
    if e.get("mood"):
        s += f" Mood: {', '.join(e['mood'])}."
    return s


def signature(e: dict) -> str:
    """A short signature of a room's look (for the variety guard of later sets)."""
    fl = e.get("floor") or {}
    bits = [e.get("room"), f"{e['walls']} walls" if e.get("walls") else "",
            " ".join(x for x in (fl.get("colour"), fl.get("material")) if x) + " floor" if fl else "",
            e.get("light") or "", (f"{e['main']['item']} {e.get('arrangement', '')}".strip() if e.get("main") else "")]
    return "; ".join(b for b in bits if b)
