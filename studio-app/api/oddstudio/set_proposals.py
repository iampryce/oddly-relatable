"""A set for every episode (owner decision 2026-11-21): the studio proposes an ORIGINAL set description, the owner
edits it, and only the owner's click generates a candidate from exactly that text.

- Audio episodes: the description is assembled by a fixed sentence from the video notes' list values only
  (video_notes.proposal_text): setting type, furniture, time of day, seated/standing counts, facing, mood. Free; no AI
  wording.
- Script-first episodes: the AI writer proposes one sentence from the story text (title, logline, scene headings and
  descriptions); names of the cast are removed and the owner edits it.
- "Generate this set" shows the estimated image cost first and sends the prompt the episode displays (house style +
  the text in the box) through the existing set-candidate job; the candidate is linked to the episode and appears in
  Settings > Sets for approval. Nothing is generated or approved without the owner's click.
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, ScriptVersion
from .queue import enqueue

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

IMAGE_COST = "about $0.05-0.20 per image"
TWO_COST = "2 images, about $0.10-0.40"
# shot / reverse shot: one room, two linked sets with the same description and a view line (owner decision 2026-11-21)
VIEW_LINES = {"main side": "View: the main side of the room (the first camera angle).",
              "reverse side": "View: the reverse side of the same room, seen from the opposite direction (the reverse "
                              "shot), with the same furniture, light and style."}


def two_views_for(ep: Episode) -> bool:
    if ep.source != "audio":
        return False
    from .beats import two_views
    from .reference_plan import effective
    return two_views(effective(ep.audio_transcript or {}))
MIN_TEXT, MAX_TEXT = 10, 400
MAX_VARIETY = 1500
LOCKED_STAGES = ("producing", "publishing")


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _story_text(db: Session, ep: Episode) -> str:
    sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one_or_none() if ep.script_version else None
    if sv is None:
        return ""
    c = sv.content
    parts = [c.get("title", ""), c.get("logline", "")]
    for s in c.get("scenes", []):
        parts += [s.get("heading", ""), s.get("description", ""), s.get("action", "")]
    return "\n".join(p for p in parts if p)


def clean_text(text: str, names: list[str]) -> str:
    """One plain sentence: no quotes, no cast names (replaced by "someone"), collapsed spaces, at most MAX_TEXT chars."""
    t = re.sub(r"[\"“”‘’`]", "", str(text or ""))
    for n in sorted({n for n in names if n and len(n) > 1}, key=len, reverse=True):
        t = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", "someone", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip()[:MAX_TEXT]


def set_notes_of(ep: Episode) -> list[dict]:
    """The video's set notes, one per distinct room (words only; owner-editable)."""
    return list((((ep.audio_transcript or {}).get("video_notes") or {}).get("set_notes")) or [])


def cast_size(ep: Episode) -> int | None:
    """How many people the set must seat at least: the most people the video notes show at once, else the number of
    speakers in the recording or the script."""
    tr = ep.audio_transcript or {}
    ranges = ((tr.get("video_notes") or {}).get("ranges")) or []
    n = max((len(r.get("roles", [])) for r in ranges), default=0)
    if not n:
        n = len({ln.get("speaker") for ln in tr.get("lines", []) if ln.get("speaker")})
    return n or None


def rooms_of(ep: Episode) -> list[dict]:
    """The proposals, one per room: [{room, text, source, seats, signature}]. Older proposals (one text) are one room."""
    p = ep.set_proposal or {}
    if p.get("rooms"):
        return [dict(r) for r in p["rooms"]]
    return [{"room": None, "text": p["text"], "source": p.get("source"), "seats": None}] if p.get("text") else []


def variety_of(db: Session, ep: Episode, description: str) -> tuple[str, str]:
    """(text, source): the owner's edited variety guard, else the automatic one from the recent sets."""
    from . import sets
    v = (ep.set_proposal or {}).get("variety")
    if v is not None:
        return v, "your edit"
    return sets.variety_text(db, ep.id, description), "recent sets"


def room_view(db: Session, ep: Episode, r: dict, two: bool) -> dict:
    from . import sets
    seats = r.get("seats") or cast_size(ep)
    variety, vsrc = variety_of(db, ep, r["text"])
    parts = sets.prompt_parts(db, r["text"], seats, variety)
    return {**r, "seats": seats, "variety_source": vsrc, "parts": parts,
            "prompt": sets.prompt_for(db, r["text"], seats, variety),
            "view_prompts": {v: sets.prompt_for(db, r["text"], seats, variety, line) for v, line in VIEW_LINES.items()} if two else {}}


def view(db: Session, ep: Episode) -> dict:
    from . import sets
    p = ep.set_proposal or {}
    two = two_views_for(ep)
    rooms = [room_view(db, ep, r, two) for r in rooms_of(ep)]
    first = rooms[0] if rooms else None
    variety, vsrc = variety_of(db, ep, first["text"] if first else "")
    return {"text": first["text"] if first else "", "source": first.get("source") if first else None, "updated": p.get("updated"),
            "prompt": first["prompt"] if first else "", "parts": first["parts"] if first else [], "rooms": rooms,
            "image_cost": IMAGE_COST, "two_views": two, "two_cost": TWO_COST,
            "view_prompts": first["view_prompts"] if first else {},
            "variety": variety, "variety_source": vsrc, "recent_sets": sets.recent_signatures(db, ep.id),
            "set_notes": set_notes_of(ep), "set_notes_note": ((ep.audio_transcript or {}).get("video_notes") or {}).get("set_notes_note", ""),
            "propose_with": "video notes" if ep.source == "audio" else "writer",
            "can_propose": bool(((ep.audio_transcript or {}).get("video_notes") or {}).get("ranges"))
            if ep.source == "audio" else bool(ep.script_version)}


def normalized(text: str) -> str:
    """Collapsed spaces; refused when the result is shorter than MIN_TEXT (the schema only sees the raw input)."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) < MIN_TEXT:
        raise HTTPException(422, f"the description needs at least {MIN_TEXT} characters")
    return t


def _save(db: Session, ep: Episode, text: str, source: str, room: int = 0) -> None:
    """Save one room's text (the first room by default); the other rooms and the variety guard are kept."""
    p = dict(ep.set_proposal or {})
    rooms = rooms_of(ep) or [{"room": None, "text": text, "source": source, "seats": None}]
    if not 0 <= room < len(rooms):
        raise HTTPException(404, "no such room in the proposal")
    rooms[room] = {**rooms[room], "text": text, "source": source}
    p.update({"rooms": rooms, "text": rooms[0]["text"], "source": rooms[0]["source"], "updated": time.time()})
    ep.set_proposal = p


@router.get("/episodes/{eid}/set-proposal")
def get_proposal(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class ProposalIn(BaseModel):
    text: str = Field(min_length=MIN_TEXT, max_length=MAX_TEXT)
    room: int = Field(default=0, ge=0, le=7)


@router.put("/episodes/{eid}/set-proposal")
def edit_proposal(eid: int, body: ProposalIn, db: Session = Depends(get_db)):
    """The owner's own words: what is shown is what will be sent."""
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    _save(db, ep, normalized(body.text), "edited", body.room)
    db.add(Event(episode_id=ep.id, kind="episode", message="Proposed set edited"))
    db.commit()
    return view(db, ep)


class VarietyIn(BaseModel):
    text: str | None = Field(default=None, max_length=MAX_VARIETY)


@router.put("/episodes/{eid}/set-proposal/variety")
def edit_variety(eid: int, body: VarietyIn, db: Session = Depends(get_db)):
    """The owner's variety guard (sent as shown); empty or null goes back to the automatic one from the recent sets."""
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    p = dict(ep.set_proposal or {})
    t = re.sub(r"[ \t]+", " ", body.text or "").strip()
    if t:
        p["variety"] = t
    else:
        p.pop("variety", None)
    ep.set_proposal = p
    db.add(Event(episode_id=ep.id, kind="episode", message="Set variety guard " + ("edited" if t else "reset to the recent sets")))
    db.commit()
    return view(db, ep)


class SetNotesIn(BaseModel):
    room: int = Field(ge=0, le=7)
    text: str = Field(min_length=MIN_TEXT, max_length=MAX_TEXT)


@router.put("/episodes/{eid}/set-notes")
def edit_set_notes(eid: int, body: SetNotesIn, db: Session = Depends(get_db)):
    """The owner's edit of one room's set notes (your words; "Propose from the video notes" then uses them verbatim)."""
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    tr = dict(ep.audio_transcript or {})
    notes = dict(tr.get("video_notes") or {})
    sn = [dict(x) for x in notes.get("set_notes") or []]
    if not 0 <= body.room < len(sn):
        raise HTTPException(404, "no such room in the set notes")
    sn[body.room].update(text=normalized(body.text), edited=True)
    notes["set_notes"] = sn
    tr["video_notes"] = notes
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Set notes edited ({sn[body.room]['room']})"))
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/set-proposal/propose")
def propose(eid: int, db: Session = Depends(get_db)):
    """Audio: the set notes verbatim, one proposal per room (or, for older notes without set notes, the fixed sentence
    from the staging notes); free and immediate. Script-first: the AI writer proposes one sentence from the story."""
    from . import video_notes as VN
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    if ep.source == "audio":
        from .reference_plan import effective
        sn = set_notes_of(ep)
        if sn:
            p = dict(ep.set_proposal or {})
            rooms = [{"room": x["room"], "text": x["text"], "source": "set notes", "seats": x.get("seats"),
                      "signature": x.get("signature", "")} for x in sn]
            p.update({"rooms": rooms, "text": rooms[0]["text"], "source": "set notes", "updated": time.time()})
            ep.set_proposal = p
            db.add(Event(episode_id=ep.id, kind="episode", message=f"Proposed set(s) from the set notes: {len(rooms)} room(s)"))
            db.commit()
            return view(db, ep)
        ranges = effective(ep.audio_transcript or {})   # your edits, without the items you ignored in the plan
        if not ranges:
            raise HTTPException(409, "this episode has no video notes to propose a set from: write the description yourself")
        p = dict(ep.set_proposal or {})
        p.pop("rooms", None)
        ep.set_proposal = p
        _save(db, ep, VN.proposal_text(ranges), "video notes")
        db.add(Event(episode_id=ep.id, kind="episode", message="Proposed set written from the video notes"))
        db.commit()
        return view(db, ep)
    if not ep.script_version:
        raise HTTPException(409, "write the script first: the set is proposed from the story")
    return {"job": S.job(enqueue(db, "set_proposal", episode_id=ep.id, revision=ep.revision))}


class GenerateIn(BaseModel):
    text: str = Field(min_length=MIN_TEXT, max_length=MAX_TEXT)
    views: bool = False      # both sides of the room (only when the notes show two views of one room)
    room: int = Field(default=0, ge=0, le=7)


@router.post("/episodes/{eid}/set-proposal/generate")
def generate(eid: int, body: GenerateIn, db: Session = Depends(get_db)):
    """The owner's click: one set candidate for one room, from exactly the prompt the page shows (the studio style,
    this text, the studio rules and the variety guard), stored in the job and sent as is."""
    from . import sets
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    text = normalized(body.text)
    rooms = rooms_of(ep)
    if body.room >= max(1, len(rooms)):
        raise HTTPException(404, "no such room in the proposal")
    if not rooms or rooms[body.room].get("text") != text:
        _save(db, ep, text, "edited", body.room)
        rooms = rooms_of(ep)
    r = rooms[body.room]
    seats = r.get("seats") or cast_size(ep)
    variety, _ = variety_of(db, ep, text)
    # the job's own id makes the set id unique, even for two requests at the same moment
    # (the job is created, given its set id and committed in one transaction, so a worker never sees it without one)
    from .models import Job
    room_word = f", {r['room']}" if r.get("room") and len(rooms) > 1 else ""
    label = f"{ep.title[:44]} (episode {ep.id}{room_word})"
    if body.views and not two_views_for(ep):
        raise HTTPException(409, "the video notes do not show two views of one room: generate one set")
    want = list(VIEW_LINES.items()) if body.views else [(None, None)]
    made, linked = [], None
    sig = r.get("signature") if r.get("source") == "set notes" else ""
    for view_name, line in want:
        prompt = sets.prompt_for(db, text, seats, variety, line or "")
        job = Job(kind="set_candidate", episode_id=None, revision=1, status="queued",
                  payload={"label": label + (f", {view_name}" if view_name else ""), "description": text, "episode_id": ep.id,
                           "prompt": prompt, "seats": seats, **({"signature": sig} if sig else {})})
        db.add(job)
        db.flush()
        set_id = f"{sets.slug(ep.title)[:30]}-ep{ep.id}-{job.id}"
        linked = linked or set_id
        job.payload = {**job.payload, "set_id": set_id, **({"view": view_name, "room": linked} if view_name else {})}
        db.add(Event(episode_id=ep.id, kind="job", message=f"Queued set_candidate (job {job.id})"))
        made.append({"set_id": set_id, "view": view_name, "job": S.job(job), "prompt": prompt})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Set candidate(s) requested ({', '.join(m['set_id'] for m in made)}, "
                                                          f"{TWO_COST if body.views else IMAGE_COST}); approve in Settings > Sets"))
    db.commit()
    # the jobs are built here (not with enqueue) so each set id carries its job id; like enqueue, announce each one to
    # the worker queue only after the commit (job 327, 2026-11-22: without this the job stayed queued until a restart)
    from .queue import announce
    for m in made:
        announce(m["job"]["id"])
    first = made[0]
    return {"set_id": first["set_id"], "job": first["job"], "prompt": first["prompt"], "sets": made}


# ------------------------------------------------------------------ the writer's proposal (script-first)
from .tasks import Ctx, task  # noqa: E402

SYSTEM = ("You design ONE original set (a single place) for an adult 2D animated comedy. Reply with one JSON object only.")
PROMPT = ("Story:\n{story}\n\nDescribe the main place of this story as an original set, in ONE sentence of at most 40 "
          "words: the kind of place, the key furniture, the time of day, and how many people are seated or standing. "
          "Never name people or characters, real places, shows, films, brands or logos, and no written text or signs. "
          'JSON: {{"description": ""}}')


@task
def set_proposal(ctx: Ctx) -> dict:
    from .providers import text_provider
    from .settings_store import get_section
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    story = _story_text(db, ep)
    if not story:
        raise ValueError("the episode has no script to propose a set from")
    ans = text_provider(get_section(db, "text")).complete_json(SYSTEM, PROMPT.format(story=story[:6000]))
    names = [x for c in db.query(Character).all() for x in (c.name, c.key)]
    text = clean_text((ans or {}).get("description", "") if isinstance(ans, dict) else "", names)
    if len(text) < MIN_TEXT:
        raise ValueError("the writer did not propose a usable set description: write it yourself")
    _save(db, ep, text, "writer")
    db.add(Event(episode_id=ep.id, kind="episode", message="Proposed set written by the AI writer from the story"))
    db.commit()
    return {"text": text}
