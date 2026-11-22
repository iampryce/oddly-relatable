"""The Reference plan (owner decision 2026-11-21): where an audio episode has video reference notes, they drive the
episode (set proposal, seating and blocking, shots, reactors), and the owner sees and accepts that BEFORE the scenes
are built.

Per notes range the plan lists four items, each with its current (possibly edited) value, the unedited value the
vision model gave, a "used / ignored" toggle, and a note on anything the renderer cannot do yet:
  set       setting, furniture and time of day (used for the set proposal and, in per-scene sets, the scene's set)
  seating   who is seated or standing and whom they face (each scene starts in that arrangement; speaker first)
  shot      shot size and camera movement (a strong suggestion to the scene writer; dialogue and timing stay locked)
  reactors  who reacts and how (silent reaction cutaways)
The roles in the notes are anonymous. With the per-person notes and the owner's "who is who" (People), each role is
read back to its person and so to the confirmed character; a person nobody confirmed is LEFT OUT (never shown or
staged as another character). Without them: "speaker" is whoever says the range's first line and "reactor N" the N-th
other character (silent characters first, then the other speakers), and roles beyond the cast are left out (they never
wrap around to a character already on screen). Only the notes' fixed-list values are ever used.

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
FIELDS = ("set", "view", "seating", "shot", "reactors", "movement")
SET_KEYS = ("setting", "furniture", "time")
SHOT_KEYS = ("shot", "camera")
CAMERA_OK = ("static",)
POSE_OK = ("seated", "standing", "leaning", "walking")
TYPICAL_HEAD = 0.42     # the cast's head width / height (the renderer uses each rig's own figure)


def ranges_of(tr: dict) -> list[dict]:
    return ((tr.get("video_notes") or {}).get("ranges")) or []


def stored(tr: dict) -> dict:
    return tr.get("reference_plan") or {}


def notes_hash(tr: dict) -> str:
    body = {"ranges": [{k: v for k, v in r.items() if k != "line_ids"} for r in ranges_of(tr)],
            "ignored": sorted(stored(tr).get("ignored", [])),
            "beats": (tr.get("video_notes") or {}).get("beats") or [], "people": tr.get("person_map") or {}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def accepted(tr: dict) -> bool:
    p = stored(tr)
    return bool(p.get("accepted")) and p.get("hash") == notes_hash(tr)


def needs_acceptance(tr: dict) -> bool:
    return bool(ranges_of(tr)) and not accepted(tr)


def persons_of(frames: list[dict], r: dict) -> dict[str, int] | None:
    """{role: person number} for one range: the person number each role carries (notes made from now on), else read
    from the per-person frames (notes v2): the first frame inside the range whose people match the range's roles one
    to one in person order, with the same poses and positions. None when nothing matches."""
    roles = r.get("roles", [])
    if roles and all(isinstance(ro.get("person"), int) for ro in roles):
        return {ro["role"]: ro["person"] for ro in roles}      # the person number the notes recorded for each role
    for fr in frames:
        if not r["start"] <= fr.get("t", -1) < r["end"]:
            continue
        people = fr.get("people", [])
        if len(people) != len(roles):
            continue
        # notes made before roles carried their person number: unedited ranges list the roles in the frames' person
        # order (by construction), checked against the poses and positions
        if all(ro.get("pose") in (None, p.get("pose")) and ro.get("position") in (None, p.get("position"))
               for ro, p in zip(roles, people)):
            return {ro["role"]: p["person"] for ro, p in zip(roles, people)}
    return None


def with_people(tr: dict, ranges: list[dict]) -> list[dict]:
    """The ranges with each role's confirmed character as "who" (None: a person nobody confirmed, left out), when the
    episode has per-person notes and a "who is who" map; otherwise unchanged."""
    pm = tr.get("person_map") or {}
    vn = tr.get("video_notes") or {}
    frames = vn.get("people_frames") or []
    if not pm or not frames or vn.get("edited"):
        return ranges          # edited notes no longer follow the frames: the plain mapping is used
    inv = {int(n): k for k, n in pm.items() if isinstance(n, int) or str(n).isdigit()}
    out = []
    for r in ranges:
        persons = persons_of(frames, r)
        if persons is None:
            out.append(r)
            continue
        out.append({**r, "roles": [{**ro, "who": inv.get(persons.get(ro.get("role")))} for ro in r.get("roles", [])]})
    return out


def effective(tr: dict) -> list[dict]:
    """The notes as the builders use them: ignored items removed, each role with its confirmed character when known
    (never stored this way)."""
    ign = set(stored(tr).get("ignored", []))
    out = []
    all_ranges = ranges_of(tr)
    for i, r in enumerate(with_people(tr, all_ranges)):
        r = {k: v for k, v in r.items() if k != "line_ids"}
        if f"{i}:set" in ign:
            r = {k: v for k, v in r.items() if k not in SET_KEYS}
        if f"{i}:view" in ign:
            r.pop("view", None)
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


def range_index(ranges: list[dict], t: float) -> int | None:
    """The one range a moment belongs to: the latest range that has started by `t` and not ended. Neighbouring
    ranges overlap by a hundredth of a second at a cut, so a beat at the cut belongs to the range starting there."""
    best = None
    for k, r in enumerate(ranges):
        if r["start"] <= t < r["end"] and (best is None or r["start"] >= ranges[best]["start"]):
            best = k
    return best


def effective_beats(tr: dict) -> list[dict]:
    """The beats the builders act: supported types only, without those in ranges whose Movement item is ignored."""
    from .beats import SUPPORTED
    ign = set(stored(tr).get("ignored", []))
    ranges = ranges_of(tr)
    out = []
    for b in (tr.get("video_notes") or {}).get("beats") or []:
        i = range_index(ranges, b["t"])
        if b["type"] in SUPPORTED and not (i is not None and f"{i}:movement" in ign):
            out.append(b)
    return out


def role_map(range_lines: list[dict], cast: list[str], silent: list[str], r: dict | None = None) -> dict[str, str]:
    """Anonymous role -> character key for one range. With the confirmed people ("who" on the roles): each role's own
    character, speaker = the line's speaker; a role nobody confirmed is left out, and no character appears twice.
    Otherwise: speaker = the first line's speaker; the k-th reactor present in the range = the k-th other character
    (whatever its number), and reactors beyond the cast are left out (never wrapped around to a character already on
    screen)."""
    if not range_lines:
        return {}
    speaker = range_lines[0]["speaker"]
    roles = (r or {}).get("roles", [])
    if any("who" in ro for ro in roles):
        # each role is its own confirmed person, the speaker role included (the person talking in the video); a role
        # nobody confirmed is left out, and no character appears twice
        out, used = {}, set()
        for ro in sorted(roles, key=lambda x: 0 if x.get("role") == "speaker" else 1):
            who = ro.get("who")
            if who and who not in used:
                out[ro["role"]] = who
                used.add(who)
        return out
    out = {"speaker": speaker}
    others = [k for k in list(dict.fromkeys(silent + cast)) if k != speaker]
    present = [ro["role"] for ro in roles if ro.get("role", "").startswith("reactor")]
    labels = present or [f"reactor {n}" for n in range(1, 10)]
    for label, k in zip(labels, others):      # the k-th reactor present is the k-th other character; extras left out
        out[label] = k
    return out


def staging_for(range_lines: list[dict], r: dict | None, cast: list[str], silent: list[str]) -> dict[str, str]:
    """{character: seated | standing} in the note's arrangement, speaker first (insertion order is the seat order)."""
    if not r:
        return {}
    roles = role_map(range_lines, cast, silent, r)
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
        if ro.get("role") not in roles:
            continue                      # unconfirmed or extra people are left out
        who = names.get(roles.get(ro.get("role", "")), ro.get("role", ""))
        if ro.get("pose"):
            bits.append(f"{who} {ro['pose']}" + (f", facing {names.get(roles.get(ro['facing']), ro['facing'])}" if ro.get("facing") else ""))
    return "; ".join(bits) or "-"


def _shot_text(r: dict) -> str:
    return ", ".join(f"{k} {r[k]}" for k in SHOT_KEYS if r.get(k)) or "-"


def _react_text(r: dict, names: dict, roles: dict) -> str:
    bits = [f"{names.get(roles.get(ro['role']), ro['role'])} ({ro.get('emotion') or 'neutral'})"
            for ro in r.get("roles", []) if ro.get("role", "").startswith("reactor") and ro["role"] in roles]
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
    all_ranges = ranges_of(tr)
    for i, r in enumerate(with_people(tr, all_ranges)):
        rl = [ln for ln in lines if ln["start"] < r["end"] and ln["end"] > r["start"]]
        roles = role_map(rl, cast, silent, r)
        o = _original_for(tr, r)
        seated = sum(1 for ro in r.get("roles", []) if ro.get("pose") == "seated")
        seat_note = []
        if seated and spec is not None and seated > seats:
            seat_note.append(f"the episode's set has {seats} seat(s): {seated - seats} seated person(s) will stand")
        if seated and spec is None:
            seat_note.append("choose the episode's set to see how many seats it has")
        if seated and spec is not None:
            from .acting import HEIGHT, cast_height
            h = cast_height(sets.seats_of(spec), TYPICAL_HEAD)
            if h < HEIGHT:
                seat_note.append(f"the set's seats are close together: the characters are drawn about {h} px tall instead of "
                                 f"{HEIGHT} (a set with seats further apart keeps them full size)")
        if any(ro.get("pose") not in (None, *POSE_OK) for ro in r.get("roles", [])):
            seat_note.append("lying down or kneeling will be skipped: they stand")
        left = [ro for ro in r.get("roles", []) if ro.get("role") != "speaker" and ro.get("role") not in roles]
        if left:
            unconfirmed = sum(1 for ro in left if "who" in ro and not ro["who"])
            seat_note.append(f"{len(left)} person(s) left out" + (f" ({unconfirmed} not confirmed under People)" if unconfirmed else
                                                                 " (more people than characters)"))
        from . import beats as BT
        in_range = [b for b in (tr.get("video_notes") or {}).get("beats") or [] if range_index(all_ranges, b["t"]) == i]
        pnames = BT.names_of(db, tr)
        skip = [b for b in in_range if b["type"] in BT.UNSUPPORTED]
        move_note = []
        if skip:
            move_note.append("lying down and kneeling will be skipped (they stand)")
        if in_range and not tr.get("person_map"):
            move_note.append("confirm who is who (People) so the beats can be acted")
        two = BT.two_views(ranges_of(tr))
        items = {
            "set": {"value": _set_text(r), "original": _set_text(o) if o else None,
                    "note": "one setting per room (short flips smoothed); used for the set proposal and per-scene sets"},
            "view": {"value": r.get("view") or "-", "original": (o.get("view") or "-") if o else None,
                     "note": ("one room seen from two sides: a cut to the other side switches to that side's set "
                              "(when both view sets are the episode's) and flips who stands where") if two
                     else "one view of the room"},
            "movement": {"value": "; ".join(BT.describe(b, pnames) for b in in_range) or "-", "original": None,
                         "note": "; ".join(move_note) or "acted on the timeline (dialogue and timing stay as recorded)"},
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
