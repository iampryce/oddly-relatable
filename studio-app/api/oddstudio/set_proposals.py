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
MIN_TEXT, MAX_TEXT = 10, 1000      # richer set notes (layout, windows, doors) run longer than one sentence
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
    """The set notes, one per distinct room (words only; owner-editable): those read from a video for the room alone
    ("Read the room from a video", kept on the proposal), else those made with the video notes."""
    own = (ep.set_proposal or {}).get("set_notes")
    if own:
        return list(own)
    return list((((ep.audio_transcript or {}).get("video_notes") or {}).get("set_notes")) or [])


def set_notes_from(ep: Episode) -> str:
    """Where the set notes come from, in words."""
    if (ep.set_proposal or {}).get("set_notes"):
        return ((ep.set_proposal or {}).get("set_notes_source") or {}).get("from") or "a video read for the room"
    return "the video notes" if set_notes_of(ep) else ""


def reference_of(ep: Episode) -> dict | None:
    """The owner's own reference picture for this episode's sets (None: text only)."""
    return (ep.set_proposal or {}).get("reference") or None


def cast_size(ep: Episode) -> int | None:
    """How many people the set must seat at least: the most people the video notes show at once, else the number of
    speakers in the recording or the script."""
    tr = ep.audio_transcript or {}
    ranges = ((tr.get("video_notes") or {}).get("ranges")) or []
    if ranges:
        from .reference_plan import effective
        ranges = effective(tr)

    def on_screen(r: dict) -> list:
        # with "who is who" confirmed, a person nobody confirmed is left out of the scenes: they need no seat
        roles = r.get("roles", [])
        return [ro for ro in roles if ro.get("who")] if any("who" in ro for ro in roles) else roles
    n = max((len(on_screen(r)) for r in ranges), default=0)
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
    ref = reference_of(ep)
    parts = sets.prompt_parts(db, r["text"], seats, variety, reference=bool(ref))
    prompt = sets.prompt_for(db, r["text"], seats, variety, reference=bool(ref))
    req = sets.request_view(db, prompt, ref["label"] if ref else None)
    return {**r, "seats": seats, "variety_source": vsrc, "parts": parts, "prompt": prompt, "request": req,
            "request_text": sets.request_text(req),
            "view_prompts": {v: sets.prompt_for(db, r["text"], seats, variety, line, bool(ref)) for v, line in VIEW_LINES.items()} if two else {}}


def view(db: Session, ep: Episode) -> dict:
    from . import sets
    p = ep.set_proposal or {}
    two = two_views_for(ep)
    rooms = [room_view(db, ep, r, two) for r in rooms_of(ep)]
    first = rooms[0] if rooms else None
    variety, vsrc = variety_of(db, ep, first["text"] if first else "")
    return {"text": first["text"] if first else "", "source": first.get("source") if first else None, "updated": p.get("updated"),
            "prompt": first["prompt"] if first else "", "parts": first["parts"] if first else [], "rooms": rooms,
            "image_cost": IMAGE_COST, "two_views": two, "two_cost": TWO_COST, "seat_cost": _seat_cost(db),
            "view_prompts": first["view_prompts"] if first else {},
            "variety": variety, "variety_source": vsrc, "recent_sets": sets.recent_signatures(db, ep.id),
            "set_notes": set_notes_of(ep), "set_notes_note": ((ep.audio_transcript or {}).get("video_notes") or {}).get("set_notes_note", ""),
            "set_notes_from": set_notes_from(ep), "set_notes_source": (p.get("set_notes_source") if p.get("set_notes") else None),
            "reference": {**reference_of(ep), "url": _asset_url(db, reference_of(ep)["asset_id"])} if reference_of(ep) else None,
            "propose_with": "set notes" if set_notes_of(ep) else ("video notes" if ep.source == "audio" else "writer"),
            "can_propose": bool(set_notes_of(ep)) or (bool(((ep.audio_transcript or {}).get("video_notes") or {}).get("ranges"))
                                                     if ep.source == "audio" else bool(ep.script_version))}


def _asset_url(db: Session, aid) -> str | None:
    from .models import Asset
    from .storage import storage
    a = db.get(Asset, aid) if aid else None
    return storage().url(a.storage_key) if a else None


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
    """The owner's edit of one room's set notes (your words; "Propose" then uses them verbatim). The notes are edited
    where they live: on the proposal (read from a video for the room) or in the video notes."""
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    if (ep.set_proposal or {}).get("set_notes"):
        sp = dict(ep.set_proposal)
        sn = [dict(x) for x in sp["set_notes"]]
        if not 0 <= body.room < len(sn):
            raise HTTPException(404, "no such room in the set notes")
        sn[body.room].update(text=normalized(body.text), edited=True)
        sp["set_notes"] = sn
        ep.set_proposal = sp
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Set notes edited ({sn[body.room]['room']})"))
        db.commit()
        return view(db, ep)
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
    """The set notes verbatim when there are any (from the video notes, or read from a video for the room), one
    proposal per room; else audio: the fixed sentence from the staging notes (older notes); free and immediate.
    Script-first without set notes: the AI writer proposes one sentence from the story."""
    from . import video_notes as VN
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    sn = set_notes_of(ep)
    if ep.source == "audio" or sn:
        from .reference_plan import effective
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
    text: str = Field(default="", max_length=MAX_TEXT)
    views: bool = False      # both sides of the room (only when the notes show two views of one room)
    room: int = Field(default=0, ge=0, le=7)
    again_of: str | None = Field(default=None, max_length=80)   # "Generate another": the same request as this candidate


@router.post("/episodes/{eid}/set-proposal/generate")
def generate(eid: int, body: GenerateIn, db: Session = Depends(get_db)):
    """The owner's click: one set candidate for one room, from exactly the prompt the page shows (the studio style,
    this text, the studio rules and the variety guard), stored in the job and sent as is."""
    from . import sets
    ep = _episode(db, eid)
    if ep.stage in LOCKED_STAGES:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    if body.again_of:
        return _again(db, ep, body.again_of)
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
    ref = reference_of(ep)
    for view_name, line in want:
        prompt = sets.prompt_for(db, text, seats, variety, line or "", bool(ref))
        job = Job(kind="set_candidate", episode_id=None, revision=1, status="queued",
                  payload={"label": label + (f", {view_name}" if view_name else ""), "description": text, "episode_id": ep.id,
                           "prompt": prompt, "seats": seats, "room_index": body.room, **({"signature": sig} if sig else {}),
                           **({"reference_asset_id": ref["asset_id"], "reference_label": ref["label"]} if ref else {})})
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


def _again(db: Session, ep: Episode, sid: str) -> dict:
    """"Generate another": one more candidate from exactly the request an earlier candidate of this episode was made
    from (its stored prompt, seats and reference), whatever the boxes say now."""
    from . import sets
    from .models import Job
    from .queue import announce
    rec = sets.records(db).get(sid)
    if not rec or rec.get("episode_id") != ep.id or not rec.get("prompt"):
        raise HTTPException(404, "no set candidate of this episode with a stored request")
    ref_id = rec.get("reference_asset_id")
    job = Job(kind="set_candidate", episode_id=None, revision=1, status="queued",
              payload={"label": rec.get("label", sid), "description": rec.get("description", ""), "episode_id": ep.id,
                       "prompt": rec["prompt"], "seats": rec.get("seats_wanted"), "room_index": rec.get("room_index", 0),
                       "again_of": sid, **({"signature": rec["signature"]} if rec.get("signature") else {}),
                       **({"reference_asset_id": ref_id, "reference_label": (rec.get("request") or {}).get("reference_image")}
                          if ref_id else {})})
    db.add(job)
    db.flush()
    set_id = f"{sets.slug(ep.title)[:30]}-ep{ep.id}-{job.id}"
    job.payload = {**job.payload, "set_id": set_id}
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Another set candidate requested ({set_id}, same request as "
                                                          f"{sid}, {IMAGE_COST})"))
    db.commit()
    announce(job.id)
    return {"set_id": set_id, "job": S.job(job), "prompt": rec["prompt"], "sets": [{"set_id": set_id, "job": S.job(job)}]}


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


# ------------------------------------------------------------------ the set panel on the episode page
PANEL_JOBS = ("set_candidate", "set_seat_suggest", "set_notes_read_video", "set_proposal")


def panel_jobs(db: Session, ep: Episode, set_ids: set[str]) -> list[dict]:
    """The latest set jobs of this episode (set candidates carry the episode in their payload, not on the job)."""
    from .models import Job
    out = []
    for j in db.query(Job).filter(Job.kind.in_(PANEL_JOBS)).order_by(Job.id.desc()).limit(300):
        p = j.payload or {}
        if j.episode_id == ep.id or p.get("episode_id") == ep.id or p.get("set_id") in set_ids:
            out.append({"id": j.id, "kind": j.kind, "status": j.status, "error": j.error, "set_id": p.get("set_id"),
                        "created_at": S.ts(j.created_at), "finished_at": S.ts(j.finished_at)})
        if len(out) >= 12:
            break
    return out


@router.get("/episodes/{eid}/set-panel")
def set_panel(eid: int, db: Session = Depends(get_db)):
    """Every set made for this episode (and the sets it uses), each with its picture, status, staging, the suggested
    seats, the exact request it was made from and its cost; the set jobs with their errors; the seat-suggestion cost."""
    from . import seat_suggest, sets
    from .models import Asset
    from .storage import storage
    ep = _episode(db, eid)
    people = cast_size(ep) or 0
    items = []
    for sid, r in sorted(sets.records(db).items(), key=lambda kv: -kv[1].get("created", 0)):
        if r.get("status") == "binned" or not (r.get("episode_id") == ep.id or sid == ep.set_id or sid in (ep.scene_set_ids or [])):
            continue
        a, pv = db.get(Asset, r.get("asset_id")), db.get(Asset, r.get("preview_asset_id"))
        want = int(r.get("seats_wanted") or people or 0)
        sug = r.get("suggested") or None
        items.append({"id": sid, "label": r.get("label", sid), "status": r.get("status"), "chosen": sid == ep.set_id,
                      "for_this_episode": r.get("episode_id") == ep.id, "kept": bool(r.get("kept")),
                      "url": storage().url(a.storage_key) if a else None, "preview_url": storage().url(pv.storage_key) if pv else None,
                      "width": r.get("width"), "height": r.get("height"), "blocking": r.get("blocking") or {},
                      "seats": len(sets.seats_of(r.get("blocking") or {})), "people": want,
                      "suggested": {k: sug[k] for k in ("blocking", "info", "summary", "usage", "estimated_usd", "at") if k in sug} if sug else None,
                      "suggest_error": r.get("suggest_error"), "staging_edited": bool(r.get("staging_edited_at")),
                      "request": r.get("request") or ({"prompt": r["prompt"]} if r.get("prompt") else None),
                      "request_text": sets.request_text(r["request"]) if r.get("request") else r.get("prompt"),
                      "estimated_usd": r.get("estimated_usd"), "cost": IMAGE_COST, "room": r.get("room"), "view": r.get("view"),
                      "room_index": r.get("room_index", 0), "created": r.get("created"), "description": r.get("description")})
    return {"sets": items, "people": people, "jobs": panel_jobs(db, ep, {x["id"] for x in items}),
            "suggest_cost": seat_suggest.cost_view(db), "image_cost": IMAGE_COST, "chosen": ep.set_id}


@router.post("/sets/{sid}/suggest-seats")
def suggest_seats(sid: str, db: Session = Depends(get_db)):
    """"Suggest seats again": one vision call on the set's own picture (cost shown first; refused over the cap). The
    suggestion is stored and, on a candidate nobody has edited, used as its staging; nothing is approved."""
    from . import seat_suggest, sets
    r = sets.records(db).get(sid)
    if not r or r.get("status") not in ("candidate", "approved"):
        raise HTTPException(404, "no such set")
    cost = seat_suggest.cost_view(db)
    if not cost.get("configured"):
        raise HTTPException(409, cost.get("message") or "no API vision provider")
    if not cost["within_cap"]:
        raise HTTPException(409, f"about ${cost['usd']:.3f}, over the ${cost['cap_usd']:.2f} cap")
    job = enqueue(db, "set_seat_suggest", payload={"set_id": sid, "episode_id": r.get("episode_id")})
    if r.get("episode_id"):
        db.add(Event(episode_id=r["episode_id"], kind="job", message=f"Seat suggestion requested for {r.get('label', sid)} "
                                                                     f"(about ${cost['usd']:.3f})"))
        db.commit()
    return {"job": S.job(job), "cost": cost}


def _seat_cost(db: Session) -> dict:
    from . import seat_suggest
    return seat_suggest.cost_view(db)
