"""Camera angles read from the reference video, in WORDS ONLY (feat/set-views, owner request 2026-11-23).

"Read the room from a video" asks the vision model, in the same single call as the set notes, for the camera angles
the video uses: for each distinct angle, the camera position, the shot size, what is in frame, who is seated or
standing where and which way each person faces (positions only), and where the room's furniture, windows and
bookcases sit from that angle. The instruction says only the set and the camera angles are wanted: never a person's
face, appearance, clothing or name. Every value comes from fixed lists; anything else is removed and counted. Only the
words are stored (on the episode's set proposal), shown and editable before a view is generated from them.

Each angle is one of the set's views (up to four):
  wide      everyone, the whole room
  speaker   the speaker, from the audience's side
  audience  the row of listeners, from the speaker's side
  two-shot  the speaker and the nearest listener, side-on
"""
from __future__ import annotations

import math
import re

VIEWS = ("wide", "speaker", "audience", "two-shot")
VIEW_LABEL = {"wide": "wide (everyone)", "speaker": "speaker (from the audience's side)",
              "audience": "audience (the listeners, from the speaker's side)", "two-shot": "two-shot (the speaker and the nearest listener, side-on)"}
CAMERA = ("in front, eye level", "in front, slightly high", "in front, low", "behind the audience", "behind the speaker",
          "from the left side", "from the right side", "high corner, looking down")
SHOTS = ("wide", "medium", "close", "over the shoulder")
WHO = ("the main speaker", "one other person", "the others")
POSES = ("seated", "standing")
WHERE = ("left of frame", "centre of frame", "right of frame", "foreground", "background")
FACING = ("towards the camera", "left", "right", "away from the camera", "towards the main speaker", "towards the others")
THINGS = ("desk", "long table", "round table", "chairs", "a row of chairs", "sofa", "bookcase", "window", "door", "curtains",
          "lamp", "plant", "cabinet", "fireplace", "rug", "wall", "floor", "ceiling", "picture frame")
MAX_ITEMS = 8


def prompt_addition() -> str:
    L = lambda xs: ", ".join(xs)     # noqa: E731
    return (
        "\nAlso list the CAMERA ANGLES the video uses (at most 4 distinct angles). Only the set and the camera angles "
        "are wanted: never describe any person's face, appearance, clothing or name.\n"
        'Add to the JSON: "angles": [{"view": ..., "camera": ..., "shot": ..., "in_frame": [...], "people": [{"who": ..., '
        '"count": 1, "pose": ..., "where": ..., "facing": ...}], "furniture": [{"item": ..., "where": ...}]}]\n'
        f"- view: {L(VIEWS)} (wide = everyone; speaker = the speaker seen from the audience's side; audience = the "
        "listeners seen from the speaker's side; two-shot = the speaker and the nearest listener, side-on)\n"
        f"- camera: {L(CAMERA)}\n- shot: {L(SHOTS)}\n- in_frame and furniture item: {L(THINGS)}\n"
        f"- who: {L(WHO)}; pose: {L(POSES)}; where (also for furniture): {L(WHERE)}; facing: {L(FACING)}\n"
        "One entry per distinct angle; leave out anything you are unsure of.")


def _pick(v, allowed):
    s = re.sub(r"\s+", " ", str(v or "").strip().lower())
    return s if s in allowed else None


def clean(raw) -> tuple[list[dict], int]:
    """The angles, every value from the lists; one per view (the first wins). Returns (angles, values removed)."""
    if not isinstance(raw, list):
        return [], 0 if raw is None else 1
    out, stripped, seen = [], 0, set()
    for a in raw[:8]:
        if not isinstance(a, dict):
            stripped += 1
            continue
        stripped += len(set(a) - {"view", "camera", "shot", "in_frame", "people", "furniture"})
        view = _pick(a.get("view"), VIEWS)
        if not view or view in seen:
            stripped += 1
            continue
        seen.add(view)
        e: dict = {"view": view}
        for key, allowed in (("camera", CAMERA), ("shot", SHOTS)):
            if key in a:
                v = _pick(a[key], allowed)
                if v:
                    e[key] = v
                else:
                    stripped += 1
        things = []
        for it in (a.get("in_frame") if isinstance(a.get("in_frame"), list) else [])[: MAX_ITEMS * 2]:
            v = _pick(it, THINGS)
            if v and v not in things:
                things.append(v)
            elif not v:
                stripped += 1
        if things:
            e["in_frame"] = things[:MAX_ITEMS]
        people = []
        for p in (a.get("people") if isinstance(a.get("people"), list) else [])[:8]:
            if not isinstance(p, dict):
                stripped += 1
                continue
            stripped += len(set(p) - {"who", "count", "pose", "where", "facing"})
            who, pose, where, facing = (_pick(p.get("who"), WHO), _pick(p.get("pose"), POSES), _pick(p.get("where"), WHERE),
                                        _pick(p.get("facing"), FACING))
            c = p.get("count", 1)
            if not who or not (isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and 1 <= c <= 12):
                stripped += 1
                continue
            q = {"who": who, "count": 1 if who != "the others" else int(c)}
            for k, v, raw_v in (("pose", pose, p.get("pose")), ("where", where, p.get("where")), ("facing", facing, p.get("facing"))):
                if v:
                    q[k] = v
                elif raw_v is not None:
                    stripped += 1
            people.append(q)
        if people:
            e["people"] = people[:4]
        furn = []
        for f in (a.get("furniture") if isinstance(a.get("furniture"), list) else [])[: MAX_ITEMS * 2]:
            if not isinstance(f, dict):
                stripped += 1
                continue
            item, where = _pick(f.get("item"), THINGS), _pick(f.get("where"), WHERE)
            if not item:
                stripped += 1
                continue
            furn.append({"item": item, **({"where": where} if where else {})})
        if furn:
            e["furniture"] = furn[:MAX_ITEMS]
        out.append(e)
        if len(out) >= len(VIEWS):
            break
    return out, stripped


def angle_text(e: dict) -> str:
    """The angle in words, e.g. "Camera behind the audience, medium shot. In frame: desk, bookcase, window. The main
    speaker seated, centre of frame, facing towards the camera. Furniture: desk centre of frame; bookcase background." """
    parts = []
    cam = f"Camera {e['camera']}" if e.get("camera") else "Camera"
    parts.append(cam + (f", {e['shot']} shot" if e.get("shot") else "") + ".")
    if e.get("in_frame"):
        parts.append("In frame: " + ", ".join(e["in_frame"]) + ".")
    for p in e.get("people", []):
        who = p["who"] if p["who"] != "the others" else (f"{p['count']} others" if p["count"] > 1 else "one other")
        bits = [who, p.get("pose"), p.get("where"), f"facing {p['facing']}" if p.get("facing") else None]
        s = " ".join(b for b in bits[:2] if b) + "".join(f", {b}" for b in bits[2:] if b) + "."
        parts.append(s[:1].upper() + s[1:])
    if e.get("furniture"):
        parts.append("Furniture: " + "; ".join(f"{f['item']} {f['where']}" if f.get("where") else f["item"] for f in e["furniture"]) + ".")
    return " ".join(parts)


def stored(sp: dict) -> list[dict]:
    """The episode's camera angles (on its set proposal): [{view, fields, text, edited}]."""
    return list((sp or {}).get("camera_angles") or [])
