"""The Reference plan (owner decision 2026-11-21): where an audio episode has video reference notes, they drive the
episode (set proposal, seating and blocking, shots, reactors), and the owner sees and accepts that BEFORE the scenes
are built.

Per notes range the plan lists four items, each with its current (possibly edited) value, the unedited value the
vision model gave, a "used / ignored" toggle, and a note on anything the renderer cannot do yet:
  set       setting, furniture and time of day (used for the set proposal and, in per-scene sets, the scene's set)
  seating   who is seated or standing and whom they face (each scene starts in that arrangement; speaker first)
  shot      shot size and camera movement (a strong suggestion to the scene writer; dialogue and timing stay locked)
  reactors  who reacts and how (silent reaction cutaways)
The roles in the notes are anonymous: "speaker" is whoever says the range's first line; "reactor N" is the N-th other
character (silent characters first, then the other speakers). Only the notes' fixed-list values are ever used.

Nothing is built until the owner accepts the plan; editing the notes or a toggle withdraws the acceptance.
"""
from __future__ import annotations

import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
FIELDS = ("set", "seating", "shot", "reactors")
SET_KEYS = ("setting", "furniture", "time")
SHOT_KEYS = ("shot", "camera")
CAMERA_OK = ("static",)
POSE_OK = ("seated", "standing", "leaning", "walking")


def ranges_of(tr: dict) -> list[dict]:
    return ((tr.get("video_notes") or {}).get("ranges")) or []


def stored(tr: dict) -> dict:
    return tr.get("reference_plan") or {}


def notes_hash(tr: dict) -> str:
    body = {"ranges": [{k: v for k, v in r.items() if k != "line_ids"} for r in ranges_of(tr)],
            "ignored": sorted(stored(tr).get("ignored", []))}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def accepted(tr: dict) -> bool:
    p = stored(tr)
    return bool(p.get("accepted")) and p.get("hash") == notes_hash(tr)


def needs_acceptance(tr: dict) -> bool:
    return bool(ranges_of(tr)) and not accepted(tr)


def effective(tr: dict) -> list[dict]:
    """The notes as the builders use them: ignored items removed (never stored this way)."""
    ign = set(stored(tr).get("ignored", []))
    out = []
    for i, r in enumerate(ranges_of(tr)):
        r = {k: v for k, v in r.items() if k != "line_ids"}
        if f"{i}:set" in ign:
            r = {k: v for k, v in r.items() if k not in SET_KEYS}
        if f"{i}:shot" in ign:
            r = {k: v for k, v in r.items() if k not in SHOT_KEYS}
        roles = [dict(ro) for ro in r.get("roles", [])]
        if f"{i}:reactors" in ign:
            for ro in roles:
                if ro.get("role", "").startswith("reactor"):
                    ro["react"] = False
        if f"{i}:seating" in ign:
            roles = [{k: v for k, v in ro.items() if k not in ("pose", "facing", "position")} for ro in roles]
        r["roles"] = roles
        out.append(r)
    return out


def role_map(range_lines: list[dict], cast: list[str], silent: list[str]) -> dict[str, str]:
    """Anonymous role -> character key for one range: speaker = the first line's speaker; reactor N = the N-th other."""
    if not range_lines:
        return {}
    speaker = range_lines[0]["speaker"]
    others = [k for k in list(dict.fromkeys(silent + cast)) if k != speaker]
    out = {"speaker": speaker}
    for n in range(1, 10):
        if others:
            out[f"reactor {n}"] = others[(n - 1) % len(others)]
    return out


def staging_for(range_lines: list[dict], r: dict | None, cast: list[str], silent: list[str]) -> dict[str, str]:
    """{character: seated | standing} in the note's arrangement, speaker first (insertion order is the seat order)."""
    if not r:
        return {}
    roles = role_map(range_lines, cast, silent)
    out = {}
    for ro in sorted(r.get("roles", []), key=lambda ro: 0 if ro.get("role") == "speaker" else 1):
        k = roles.get(ro.get("role", ""))
        if k and k not in out and ro.get("pose"):
            out[k] = "seated" if ro["pose"] == "seated" else "standing"
    return out


def _original_for(tr: dict, r: dict) -> dict | None:
    orig = (tr.get("video_notes") or {}).get("original")
    if not orig:
        return None
    best = min(orig, key=lambda o: abs(o["start"] - r["start"]) + abs(o["end"] - r["end"]), default=None)
    return best if best and best["start"] < r["end"] and best["end"] > r["start"] else None


def _set_text(r: dict) -> str:
    return ", ".join(r[k] for k in SET_KEYS if r.get(k)) or "-"


def _seat_text(r: dict, names: dict, roles: dict) -> str:
    bits = []
    for ro in r.get("roles", []):
        who = names.get(roles.get(ro.get("role", "")), ro.get("role", ""))
        if ro.get("pose"):
            bits.append(f"{who} {ro['pose']}" + (f", facing {names.get(roles.get(ro['facing']), ro['facing'])}" if ro.get("facing") else ""))
    return "; ".join(bits) or "-"


def _shot_text(r: dict) -> str:
    return ", ".join(f"{k} {r[k]}" for k in SHOT_KEYS if r.get(k)) or "-"


def _react_text(r: dict, names: dict, roles: dict) -> str:
    bits = [f"{names.get(roles.get(ro['role']), ro['role'])} ({ro.get('emotion') or 'neutral'})"
            for ro in r.get("roles", []) if ro.get("role", "").startswith("reactor")]
    return ", ".join(bits) or "-"


def view(db: Session, ep: Episode) -> dict:
    from . import sets
    tr = ep.audio_transcript or {}
    lines = tr.get("lines", [])
    cast = list(dict.fromkeys(ln.get("speaker") for ln in lines if ln.get("speaker")))
    silent = [m["character_key"] for m in tr.get("silent_cast", []) if m.get("character_key") not in cast]
    names = {c.key: c.name for c in db.query(Character).all()}
    ign = set(stored(tr).get("ignored", []))
    spec = sets.blocking_of(db, ep.set_id) if ep.set_id else None
    seats = len(sets.seats_of(spec)) if spec else 0
    out = []
    for i, r in enumerate(ranges_of(tr)):
        rl = [ln for ln in lines if ln["start"] < r["end"] and ln["end"] > r["start"]]
        roles = role_map(rl, cast, silent)
        o = _original_for(tr, r)
        seated = sum(1 for ro in r.get("roles", []) if ro.get("pose") == "seated")
        seat_note = []
        if seated and spec is not None and seated > seats:
            seat_note.append(f"the episode's set has {seats} seat(s): {seated - seats} seated person(s) will stand")
        if seated and spec is None:
            seat_note.append("choose the episode's set to see how many seats it has")
        if any(ro.get("pose") not in (None, *POSE_OK) for ro in r.get("roles", [])):
            seat_note.append("lying down is not supported: they stand")
        if any(ro.get("role", "").startswith("reactor") and ro["role"] not in roles for ro in r.get("roles", [])):
            seat_note.append("more people than characters: the extra roles are left out")
        items = {
            "set": {"value": _set_text(r), "original": _set_text(o) if o else None,
                    "note": "used for the set proposal (and, with per-scene sets, this scene's set)"},
            "seating": {"value": _seat_text(r, names, roles), "original": _seat_text(o, names, roles) if o else None,
                        "note": "; ".join(seat_note) or "each scene starts in this arrangement (speaker first)"},
            "shot": {"value": _shot_text(r), "original": _shot_text(o) if o else None,
                     "note": ("the camera does not pan, tilt, zoom or track yet: only cuts between wide, medium and close"
                              if r.get("camera") and r["camera"] not in CAMERA_OK else "a strong suggestion to the scene writer")},
            "reactors": {"value": _react_text(r, names, roles), "original": _react_text(o, names, roles) if o else None,
                         "note": "silent reaction cutaways" if silent else "no silent character: reactions only from other speakers"},
        }
        for f, it in items.items():
            it["used"] = f"{i}:{f}" not in ign
            it["edited"] = it["original"] is not None and it["original"] != it["value"]
        out.append({"index": i, "start": r["start"], "end": r["end"], "line_ids": [ln["id"] for ln in rl], "items": items})
    p = stored(tr)
    return {"ranges": out, "accepted": accepted(tr), "needs_acceptance": needs_acceptance(tr),
            "accepted_at": p.get("accepted_at") if accepted(tr) else None, "edited": bool((tr.get("video_notes") or {}).get("edited"))}


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None or ep.source != "audio":
        raise HTTPException(404, "audio episode not found")
    return ep


@router.get("/episodes/{eid}/reference-plan")
def get_plan(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class IgnoredIn(BaseModel):
    ignored: list[str] = Field(default_factory=list, max_length=200)


@router.put("/episodes/{eid}/reference-plan")
def set_ignored(eid: int, body: IgnoredIn, db: Session = Depends(get_db)):
    ep = _episode(db, eid)
    tr = dict(ep.audio_transcript or {})
    n = len(ranges_of(tr))
    bad = [x for x in body.ignored if x.split(":")[-1] not in FIELDS or not x.split(":")[0].isdigit() or int(x.split(":")[0]) >= n]
    if bad:
        raise HTTPException(422, f"unknown plan items: {', '.join(bad[:5])}")
    tr["reference_plan"] = {"ignored": sorted(set(body.ignored)), "accepted": False}
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Reference plan changed ({len(body.ignored)} item(s) ignored); accept it again"))
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/reference-plan/accept")
def accept(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    tr = dict(ep.audio_transcript or {})
    if not ranges_of(tr):
        raise HTTPException(409, "this episode has no video notes")
    p = {**stored(tr), "accepted": True, "accepted_at": time.time(), "accepted_by": user}
    tr["reference_plan"] = p
    p["hash"] = notes_hash(tr)
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Reference plan accepted by {user}"))
    db.commit()
    return view(db, ep)
