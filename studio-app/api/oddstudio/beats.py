"""Action beats and the video's people (owner decisions 2026-11-21, video-first; PR 8 feat/action-beats).

From the v2 notes' per-person frames (words only, fixed lists) the server derives:
- Beats per numbered person on the timeline: enters, exits, sits down, stands up, walks (to left/center/right), leans
  in, leans back, turns to person N, turns away, nods, shakes the head, phone to ear, and held gestures. A change is
  dated halfway between the two frames that show it. Lying down and kneeling are listed but marked "will be skipped"
  (the rig cannot do them yet), like hugs, running and camera moves.
- The person map: which character each numbered person is. A SUGGESTION from timing (the person most often the only
  one talking during each labelled speaker's lines) that the owner confirms; never applied automatically.
- The v1 ranges again, now with (a) the speaker taken from the audio timing (the labelled speaker's line at that
  moment, through the confirmed person map) in preference to the vision "talking" flag, which is used only when it is
  informative; (b) one setting per room: short setting flips (one room seen from two angles) are smoothed to the most
  common setting, and the unsmoothed value is kept as the "was" value; (c) the view (which side of the room the
  camera looks at) per range, so one room seen from two angles is one setting with two views.
Everything stays editable; the owner's range edits are never overwritten without asking.
"""
from __future__ import annotations

from . import notes_v2 as NV
from . import video_notes as VN

SMOOTH_SECONDS = 20.0             # a setting shown for less than this (in a row) is smoothed into the room's setting
GESTURE_MIN_SECONDS = 1.0         # a gesture must be held at least this long to become a beat
INFORMATIVE_TALKING = 0.5         # the vision talking flag is used only if it singles out one person in >= half the frames
SUPPORTED = ("enter", "exit", "sit_down", "stand_up", "walk", "lean_in", "lean_back", "turn_to", "turn_away", "nod",
             "head_shake", "phone_to_ear", "gesture")
UNSUPPORTED = ("lie_down", "kneel")
TYPES = SUPPORTED + UNSUPPORTED
GESTURE_TYPES = {"nod": "nod", "head_shake": "head_shake", "phone_to_ear": "phone_to_ear"}
TWO_VIEWS = ("main side", "reverse side")


# ------------------------------------------------------------------ beats
def derive(frames: list[dict], step: float) -> list[dict]:
    """Beats from consecutive frames, per person, sorted by time."""
    out = []
    people = sorted({p["person"] for fr in frames for p in fr.get("people", [])})
    for n in people:
        prev, prev_t, run_g, run_t0, prev_view = None, None, None, None, None
        for fr in frames:
            cur = next((p for p in fr.get("people", []) if p["person"] == n), None)
            t = fr["t"]
            at = round((prev_t + t) / 2, 2) if prev_t is not None else round(t, 2)
            if prev is None and cur is not None and prev_t is not None:
                out.append({"person": n, "t": at, "type": "enter"})
            elif prev is not None and cur is None:
                out.append({"person": n, "t": at, "type": "exit"})
            elif prev is not None and cur is not None:
                a, b = prev.get("pose"), cur.get("pose")
                if a and b and a != b:
                    kind = {"seated": "sit_down", "lying": "lie_down", "kneeling": "kneel"}.get(b)
                    if kind:
                        out.append({"person": n, "t": at, "type": kind})
                    elif a in ("seated", "lying", "kneeling"):
                        out.append({"person": n, "t": at, "type": "stand_up"})
                    elif b == "leaning":
                        out.append({"person": n, "t": at, "type": "lean_in"})
                    elif a == "leaning":
                        out.append({"person": n, "t": at, "type": "lean_back"})
                pa, pb = prev.get("position"), cur.get("position")
                same_view = fr.get("view") == prev_view   # a cut to the other side flips positions: not a walk
                if pa and pb and pa != pb and same_view and b not in ("seated", "lying", "kneeling") and a not in ("seated",):
                    out.append({"person": n, "t": at, "type": "walk", "target": pb})
                fa, fb = prev.get("facing"), cur.get("facing")
                if fb and fb != fa and fb.startswith("person "):
                    out.append({"person": n, "t": at, "type": "turn_to", "target": fb})
                elif fb == "away" and fa != "away":
                    out.append({"person": n, "t": at, "type": "turn_away"})
            # held gestures: a run of the same gesture (not none) lasting long enough
            g = (cur or {}).get("gesture")
            g = None if g in (None, "none") else g
            if g != run_g:
                if run_g and prev_t is not None and (prev_t - run_t0 + step) >= GESTURE_MIN_SECONDS - 1e-6:
                    out.append(_gesture_beat(n, run_t0, run_g))
                run_g, run_t0 = g, t
            prev, prev_t, prev_view = cur, t, fr.get("view")
        if run_g and prev_t is not None and (prev_t - run_t0 + step) >= GESTURE_MIN_SECONDS - 1e-6:
            out.append(_gesture_beat(n, run_t0, run_g))
    out.sort(key=lambda b: (b["t"], b["person"], b["type"]))
    for i, b in enumerate(out, 1):
        b["id"] = f"b{i}"
    return out


def _gesture_beat(n: int, t: float, g: str) -> dict:
    kind = GESTURE_TYPES.get(g)
    return {"person": n, "t": round(t, 2), "type": kind} if kind else {"person": n, "t": round(t, 2), "type": "gesture", "gesture": g}


def clean_beats(raw, length: float, people: set[int]) -> list[dict]:
    """The owner's edit of the beats: only known types, people, targets and times inside the clip."""
    out = []
    for i, b in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(b, dict) or b.get("type") not in TYPES:
            raise ValueError(f"beat {i + 1}: unknown type")
        try:
            n, t = int(b.get("person")), float(b.get("t"))
        except (TypeError, ValueError):
            raise ValueError(f"beat {i + 1}: person and time are needed")
        if n not in people or not 0 <= t <= length:
            raise ValueError(f"beat {i + 1}: unknown person or a time outside the clip")
        e = {"id": str(b.get("id") or f"e{i + 1}")[:12], "person": n, "t": round(t, 2), "type": b["type"]}
        tg = b.get("target")
        if b["type"] == "walk":
            if tg not in VN.POSITIONS:
                raise ValueError(f"beat {i + 1}: walk needs a position ({', '.join(VN.POSITIONS)})")
            e["target"] = tg
        elif b["type"] == "turn_to":
            if not (isinstance(tg, str) and tg.startswith("person ") and tg[7:].isdigit() and int(tg[7:]) in people and int(tg[7:]) != n):
                raise ValueError(f"beat {i + 1}: turn_to needs another person")
            e["target"] = tg
        elif b["type"] == "gesture":
            if b.get("gesture") not in NV.GESTURES or b.get("gesture") == "none":
                raise ValueError(f"beat {i + 1}: unknown gesture")
            e["gesture"] = b["gesture"]
        out.append(e)
    return sorted(out, key=lambda x: (x["t"], x["person"]))


def describe(b: dict, names: dict) -> str:
    who = names.get(b["person"]) or f"person {b['person']}"
    what = {"enter": "enters", "exit": "exits", "sit_down": "sits down", "stand_up": "stands up", "lean_in": "leans in",
            "lean_back": "leans back", "turn_away": "turns away", "nod": "nods", "head_shake": "shakes the head",
            "phone_to_ear": "puts a phone to the ear", "lie_down": "lies down", "kneel": "kneels"}.get(b["type"])
    if b["type"] == "walk":
        what = f"walks {b.get('target')}"
    elif b["type"] == "turn_to":
        n = int(b["target"].split()[1])
        what = f"turns to {names.get(n) or b['target']}"
    elif b["type"] == "gesture":
        what = b.get("gesture", "").replace("_", " ")
    return f"{who} {what} ({b['t']:.1f} s)" + (" [will be skipped]" if b["type"] in UNSUPPORTED else "")


# ------------------------------------------------------------------ the person map (suggestion only)
def talking_informative(frames: list[dict]) -> bool:
    if not frames:
        return False
    single = sum(1 for fr in frames if sum(1 for p in fr.get("people", []) if p.get("talking")) == 1)
    return single / len(frames) >= INFORMATIVE_TALKING


def suggest_map(frames: list[dict], lines: list[dict]) -> dict[str, int | None]:
    """{character key: person number or None}: the person most often the ONLY one talking during that character's
    lines, when the talking flag is informative and that person wins at least half of those frames. A suggestion."""
    out: dict[str, int | None] = {}
    informative = talking_informative(frames)
    for key in dict.fromkeys(ln.get("speaker") for ln in lines if ln.get("speaker")):
        counts, total = {}, 0
        for fr in frames:
            if not any(ln.get("speaker") == key and ln["start"] <= fr["t"] < ln["end"] for ln in lines):
                continue
            talkers = [p["person"] for p in fr.get("people", []) if p.get("talking")]
            total += 1
            if len(talkers) == 1:
                counts[talkers[0]] = counts.get(talkers[0], 0) + 1
        best = max(counts.items(), key=lambda kv: kv[1]) if counts else None
        out[key] = best[0] if informative and best and total and best[1] / total >= 0.5 else None
    return out


# ------------------------------------------------------------------ ranges: speaker from audio, smoothing, views
def speakers_by_frame(frames: list[dict], lines: list[dict], person_map: dict) -> dict[float, int | None]:
    """The speaking person per frame time: the confirmed person of the character whose recorded line covers it
    (audio timing first); else the vision talking flag when it is informative and singles out one person."""
    by_char = {k: int(v) for k, v in (person_map or {}).items() if v}
    informative = talking_informative(frames)
    out = {}
    for fr in frames:
        ln = next((x for x in lines if x["start"] <= fr["t"] < x["end"]), None)
        n = by_char.get(ln.get("speaker")) if ln else None
        if n is None and informative:
            talkers = [p["person"] for p in fr.get("people", []) if p.get("talking")]
            n = talkers[0] if len(talkers) == 1 else None
        out[fr["t"]] = n
    return out


def smooth(ranges: list[dict]) -> list[dict]:
    """One setting per room: a setting shown for less than SMOOTH_SECONDS in a row becomes the room's setting (the most
    common setting among the long runs, else overall, by time); the furniture follows the setting."""
    if not ranges:
        return ranges
    runs = []
    for r in ranges:
        s = r.get("setting")
        if runs and runs[-1]["setting"] == s:
            runs[-1]["end"], runs[-1]["items"] = r["end"], runs[-1]["items"] + [r]
        else:
            runs.append({"setting": s, "start": r["start"], "end": r["end"], "items": [r]})
    def most(rs):
        tot = {}
        for x in rs:
            if x["setting"]:
                tot[x["setting"]] = tot.get(x["setting"], 0) + x["end"] - x["start"]
        return max(tot.items(), key=lambda kv: kv[1])[0] if tot else None
    long_runs = [x for x in runs if x["end"] - x["start"] >= SMOOTH_SECONDS]
    room = most(long_runs) or most(runs)
    furn = {}
    for r in ranges:
        if r.get("setting") and r.get("furniture"):
            furn.setdefault(r["setting"], {}).setdefault(r["furniture"], 0)
            furn[r["setting"]][r["furniture"]] += r["end"] - r["start"]
    out = []
    for x in runs:
        short = x["end"] - x["start"] < SMOOTH_SECONDS
        for r in x["items"]:
            r = dict(r)
            if short and room and r.get("setting") != room:
                r["setting"] = room
                f = furn.get(room)
                if f:
                    r["furniture"] = max(f.items(), key=lambda kv: kv[1])[0]
                else:
                    r.pop("furniture", None)
            out.append(r)
    return out


def two_views(ranges: list[dict]) -> bool:
    return set(TWO_VIEWS) <= {r.get("view") for r in ranges}


def rebuild(notes: dict, lines: list[dict], person_map: dict) -> dict:
    """Ranges (speaker from audio timing, smoothed, with views) and beats again from the per-person frames. The
    unsmoothed ranges become the "was" values. Returns the new notes (edits are replaced: the caller asks first)."""
    frames = notes.get("people_frames") or []
    if not frames:
        return notes
    step = (notes.get("length") or 0) / max(1, notes.get("frames") or len(frames)) or 1.0
    spk = speakers_by_frame(frames, lines, person_map)
    marked = [{**fr, "people": [{**p, "talking": p["person"] == spk.get(fr["t"])} for p in fr.get("people", [])]}
              for fr in frames]
    raw, _ = NV.to_ranges(marked, float(notes.get("length") or 0), step)
    return {**notes, "ranges": smooth(raw), "original": raw, "beats": derive(frames, step), "beats_original": None,
            "edited": False, "smoothed": True}


# ------------------------------------------------------------------ routes
from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from .auth import current_user  # noqa: E402
from .db import get_db  # noqa: E402
from .models import Character, Episode, Event  # noqa: E402

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _episode(db: Session, eid: int) -> tuple[Episode, dict, dict]:
    from .audio_first import audio_episode, gate
    ep = audio_episode(db, eid)
    gate(ep, "edit_video_notes")
    tr = dict(ep.audio_transcript or {})
    notes = tr.get("video_notes") or {}
    if not notes.get("people_frames"):
        raise HTTPException(409, "this episode has no v2 video notes (numbered people): upload the video again with notes")
    return ep, tr, notes


def names_of(db: Session, tr: dict) -> dict[int, str]:
    chars = {c.key: c.name for c in db.query(Character).all()}
    return {int(v): chars.get(k, k) for k, v in (tr.get("person_map") or {}).items() if v}


def people_view(db: Session, tr: dict) -> dict:
    notes = tr.get("video_notes") or {}
    frames = notes.get("people_frames") or []
    lines = tr.get("lines", [])
    counts = {}
    for fr in frames:
        for p in fr.get("people", []):
            counts[p["person"]] = counts.get(p["person"], 0) + 1
    names = names_of(db, tr)
    beats = notes.get("beats") or []
    return {"people": [{"person": n, "appearances": c, "character": next((k for k, v in (tr.get("person_map") or {}).items() if v == n), None)}
                       for n, c in sorted(counts.items())],
            "frames": len(frames), "suggestion": suggest_map(frames, lines), "map": tr.get("person_map") or {},
            "talking_informative": talking_informative(frames), "two_views": two_views(notes.get("ranges") or []),
            "beats": [{**b, "text": describe(b, names), "supported": b["type"] in SUPPORTED} for b in beats],
            "beats_edited": notes.get("beats_original") is not None, "notes_edited": bool(notes.get("edited"))}


@router.get("/episodes/{eid}/people")
def get_people(eid: int, db: Session = Depends(get_db)):
    from .audio_first import audio_episode
    return people_view(db, dict(audio_episode(db, eid).audio_transcript or {}))


class MapIn(BaseModel):
    map: dict[str, int | None] = Field(default_factory=dict)


@router.put("/episodes/{eid}/people")
def put_people(eid: int, body: MapIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner confirms which character each numbered person is (the suggestion is never applied by itself). The
    ranges and beats are rebuilt from the frames when you have not edited the ranges; otherwise use Rebuild."""
    ep, tr, notes = _episode(db, eid)
    people = {p["person"] for fr in notes["people_frames"] for p in fr.get("people", [])}
    keys = {c.key for c in db.query(Character).all()}
    bad = [k for k, v in body.map.items() if k not in keys or (v is not None and v not in people)]
    if bad:
        raise HTTPException(422, f"unknown character or person: {', '.join(bad)}")
    taken = [v for v in body.map.values() if v is not None]
    if len(taken) != len(set(taken)):
        raise HTTPException(422, "one person can be only one character")
    tr["person_map"] = {k: v for k, v in body.map.items() if v is not None}
    if not notes.get("edited"):
        tr["video_notes"] = rebuild(notes, tr.get("lines", []), tr["person_map"])
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"People confirmed by {user}: "
                 + (", ".join(f"person {v} = {k}" for k, v in tr["person_map"].items()) or "none")))
    db.commit()
    return {**people_view(db, tr), "rebuilt": not notes.get("edited")}


@router.post("/episodes/{eid}/notes/rebuild")
def rebuild_notes(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Ranges and beats again from the video frames, with the confirmed people (replaces your range and beat edits)."""
    ep, tr, notes = _episode(db, eid)
    tr["video_notes"] = rebuild(notes, tr.get("lines", []), tr.get("person_map") or {})
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Video notes rebuilt from the frames by {user}"))
    db.commit()
    return people_view(db, tr)


class BeatsIn(BaseModel):
    beats: list[dict] = Field(default_factory=list, max_length=400)


@router.put("/episodes/{eid}/beats")
def put_beats(eid: int, body: BeatsIn, db: Session = Depends(get_db)):
    """The owner's edit of the beats (fixed types only). The derived beats are kept as the "was" values."""
    ep, tr, notes = _episode(db, eid)
    people = {p["person"] for fr in notes["people_frames"] for p in fr.get("people", [])}
    try:
        beats = clean_beats(body.beats, float(notes.get("length") or 0), people)
    except ValueError as e:
        raise HTTPException(422, str(e))
    tr["video_notes"] = {**notes, "beats": beats, "beats_original": notes.get("beats_original") or notes.get("beats") or []}
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Action beats edited ({len(beats)})"))
    db.commit()
    return people_view(db, tr)
