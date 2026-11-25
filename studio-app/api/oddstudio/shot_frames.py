"""Shot frames: the storyboard as ONE still per shot of the reference video, for the video generator to animate.

The owner's plan (2026-11-25): upload the video, the engine reads it (video notes: every shot's camera, who is on
screen, their pose and emotion), the studio makes a storyboard frame per shot, and a video generator turns each frame
into the shot. The studio does not animate; it only draws each shot's FIRST FRAME exactly, from the approved character
drawings placed in the approved sets, so the characters never drift.

Per shot (a range of the accepted video notes, people confirmed with "who is who"):
  side    the episode set whose people are in the shot (owner's mapping: set id -> the characters who belong on
          that side, in seat order); shot / reverse shot comes from the notes, never from the renderer's walking.
  people  only the characters the notes show in that shot, each on their own fixed seat (the same seat in every shot),
          standing characters on the set's standing area.
  camera  the notes' shot size (close / medium / wide), framed on the first person.
  face    the notes' emotion, as the nearest approved expression.
After the notes end (the rest of the recording), one shot per recorded line from the storyboard scene that holds it.

One job renders all frames (CPU, free) and stores them with a contact sheet; the plan (times, side, people, shot,
asset) is kept for the video step. Nothing is approved here.

The storyboard in the dashboard (2026-11-25) builds on the same plan:
  automatic sides  POST without a mapping derives it from the storyboard scenes' staging (plan-defaults shows it).
  versions         every shot keeps all its takes: versions [{asset_id, at, source: first|retake, note}], the chosen
                   one (asset_id mirrors it, for the video step) and approved (the owner's click, never automatic).
  retake           one shot drawn again with the owner's changes (shot size, people, side, expressions): a new
                   version, chosen, not approved; the older ones are kept.
  animatic         the chosen frames on the recording's timeline as a draft MP4 (FFmpeg, free).
Everything here is CPU work on the server: no paid call anywhere.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Episode, Event, Job, Setting, StoryboardScene
from .queue import enqueue

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def key(eid: int) -> str:
    return f"shotframes:{eid}"


def stored(db: Session, eid: int) -> dict:
    # a deep copy: the shots are edited in place and saved back, and SQLAlchemy only writes a JSON value it sees change
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


# ------------------------------------------------------------------ planning (pure)
def side_of(people: list[str], sides: dict[str, list[str]], fallback: str) -> str:
    """The set most of the shot's people belong to (ties: the fallback, the listeners' side)."""
    best, n = fallback, -1
    for sid, members in sides.items():
        k = sum(1 for p in people if p in members)
        if k > n or (k == n and sid == fallback):
            best, n = sid, k
    return best


def plan_shots(ranges: list[dict], lines: list[dict], scenes: list[dict], sides: dict[str, list[str]],
               listeners_side: str) -> list[dict]:
    """[{index, t0, t1, side, people, shot, emotions, source}] from the notes' ranges (people confirmed), then one
    shot per recorded line after the notes end, from the scene that holds it (its side's people who are not off)."""
    out = []
    notes_end = 0.0
    for r in ranges:
        people = list(dict.fromkeys(ro.get("who") for ro in r.get("roles", []) if ro.get("who")))
        emo = {ro["who"]: ro.get("emotion") or "neutral" for ro in r.get("roles", []) if ro.get("who")}
        side = side_of(people, sides, listeners_side)
        people = [p for p in people if p in sides.get(side, [])]
        shot = (r.get("shot") or "wide").lower()
        if shot not in ("close", "medium", "wide"):
            shot = "wide"
        out.append({"t0": float(r["start"]), "t1": float(r["end"]), "side": side, "people": people, "shot": shot,
                    "emotions": emo, "source": "video notes"})
        notes_end = max(notes_end, float(r["end"]))
    for ln in lines:
        if float(ln.get("start", 0)) < notes_end - 0.01:
            continue
        sc = next((s for s in scenes if ln.get("id") in s["line_ids"]), None)
        if sc is None:
            continue
        side = sc["set"] if sc["set"] in sides else listeners_side
        staging = sc.get("staging") or {}
        people = [k for k in sides.get(side, []) if staging.get(k, "seated") != "off"]
        shot = (sc["shots"].get(ln["id"]) or "medium").lower()
        if len(people) > 1 and shot == "close":
            shot = "medium"
        out.append({"t0": float(ln["start"]), "t1": float(ln["end"]), "side": side, "people": people, "shot": shot,
                    "emotions": {}, "source": f"script ({ln['id']})"})
    out.sort(key=lambda s: s["t0"])
    for i, s in enumerate(out):
        s["index"] = i + 1
    return out




def derive_sides(scenes: list[dict], allowed: list[str]) -> dict:
    """The owner's mapping, worked out from the storyboard scenes ({set, staging, characters}): every set the scenes use
    (approved ones only, in first-use order) with the characters staged on it (not "off"), in staging (seat) order.
    A character staged on several sets belongs to the set they are staged on most (ties: the first), so each one has
    one fixed seat. A scene without staging counts its characters as seated. Standing: staged "standing" in more scenes
    than seated. The listeners' side (ties in plan_shots): the set with the most characters (ties: the first)."""
    order, set_order = [], []
    count: dict[str, dict[str, int]] = {}
    pose: dict[str, int] = {}                     # > 0: standing more often than seated
    for sc in scenes:
        sid = sc.get("set")
        if sid not in allowed:
            continue
        staging = sc.get("staging") or {}
        if staging:
            on = [(k, v) for k, v in staging.items() if v != "off"]
        else:
            on = [((c.get("key") if isinstance(c, dict) else c), "seated") for c in sc.get("characters") or []]
        for k, v in on:
            if not k:
                continue
            if k not in count:
                count[k] = {}
                order.append(k)
            count[k][sid] = count[k].get(sid, 0) + 1
            pose[k] = pose.get(k, 0) + (1 if v == "standing" else -1)
            if sid not in set_order:
                set_order.append(sid)
    sides: dict[str, list[str]] = {sid: [] for sid in set_order}
    for k in order:
        n = count[k]
        best = max(n.values())
        home = next(sid for sid in set_order if n.get(sid) == best)
        sides[home].append(k)
    sides = {sid: m for sid, m in sides.items() if m}
    listeners = None
    for sid, m in sides.items():
        if listeners is None or len(m) > len(sides[listeners]):
            listeners = sid
    return {"sides": sides, "standing": [k for k in order if pose.get(k, 0) > 0], "listeners_side": listeners}


def seats(sides: dict[str, list[str]], standing: set) -> dict[str, int]:
    """Each seated character's fixed seat on their own side: 0, 1, ... in the mapping's order (standing ones: none)."""
    out = {}
    for members in sides.values():
        n = 0
        for k in members:
            if k not in standing:
                out[k], n = n, n + 1
    return out


def norm_shot(s: dict, made: float = 0.0) -> dict:
    """A stored shot with its takes. Older plans (one asset_id per shot) become one "first" version; chosen falls back
    to the first take; approved is only ever true when the owner set it (and only on a chosen take)."""
    s = dict(s)
    vs = [dict(v) for v in s.get("versions") or [] if v.get("asset_id")]
    if not vs and s.get("asset_id"):
        vs = [{"asset_id": s["asset_id"], "at": made, "source": "first", "note": ""}]
    ids = [v["asset_id"] for v in vs]
    chosen = s.get("chosen") if s.get("chosen") in ids else (ids[0] if ids else None)
    s.update(versions=vs, chosen=chosen, asset_id=chosen, approved=bool(s.get("approved")) and chosen is not None)
    return s


def migrated(v: dict) -> dict:
    v = dict(v)
    v["shots"] = [norm_shot(s, v.get("made") or 0.0) for s in v.get("shots") or []]
    return v


def retake_note(shot: str, people: list[str], side: str, emotions: dict[str, str], before: dict) -> str:
    """What a retake changed, in words (shown with the take)."""
    parts = []
    if shot != before.get("shot"):
        parts.append(f"{shot} shot")
    if side != before.get("side"):
        parts.append(f"on {side}")
    if people != before.get("people"):
        parts.append("people: " + (", ".join(people) or "nobody (the room)"))
    faces = {k: e for k, e in emotions.items() if e and e != (before.get("emotions") or {}).get(k)}
    if faces:
        parts.append("faces: " + ", ".join(f"{k} {e}" for k, e in faces.items()))
    return "; ".join(parts) or "drawn again"


def animatic_timeline(shots: list[dict], end: float | None) -> list[tuple[int, float, float]]:
    """[(index, start, seconds)]: each shot from its t0 to the next shot's t0 (the first from 0, the last to the end
    of the recording, or its own end when the recording is unknown or shorter). Every shot lasts at least one frame."""
    out = []
    ordered = sorted(shots, key=lambda s: float(s["t0"]))
    for i, s in enumerate(ordered):
        start = 0.0 if i == 0 else float(s["t0"])
        if i + 1 < len(ordered):
            stop = float(ordered[i + 1]["t0"])
        else:
            stop = end if end and end > start else float(s.get("t1") or start)
        out.append((int(s["index"]), round(start, 3), round(max(stop - start, 0.04), 3)))
    return out


# ------------------------------------------------------------------ routes
class PlanIn(BaseModel):
    # set id -> characters, in seat order; empty (or no body at all): worked out from the storyboard scenes
    sides: dict[str, list[str]] = Field(default_factory=dict, max_length=6)
    standing: list[str] = Field(default_factory=list, max_length=12)           # characters who stand (not seated)
    listeners_side: str | None = None                                          # the side for ties (default: the last)


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def plan_defaults(db: Session, ep: Episode) -> dict:
    from . import scene_sets
    allowed = scene_sets.episode_sets(db, ep)
    rows = db.query(StoryboardScene).filter_by(episode_id=ep.id).order_by(StoryboardScene.position)
    scenes = [{"set": sc.set_id or ep.set_id, "staging": sc.staging or {}, "characters": sc.characters or []} for sc in rows]
    return derive_sides(scenes, allowed)


def _active(db: Session, eid: int, kinds: tuple[str, ...]):
    return db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(("queued", "running")))


def _plan_or_404(db: Session, eid: int) -> dict:
    v = migrated(stored(db, eid))
    if not v.get("shots"):
        raise HTTPException(404, "no shot frames yet: make the storyboard first")
    return v


def _shot_or_404(v: dict, index: int) -> dict:
    if not 1 <= index <= len(v["shots"]):
        raise HTTPException(404, f"no shot {index} (the storyboard has {len(v['shots'])} shots)")
    return v["shots"][index - 1]


@router.post("/episodes/{eid}/shot-frames")
def make_frames(eid: int, body: PlanIn | None = Body(None), db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Plan the shots from the accepted notes and render one frame per shot (CPU, free). Without a mapping, the sides
    are worked out from the storyboard scenes (see plan-defaults)."""
    from . import scene_sets
    ep = _episode(db, eid)
    body = body or PlanIn()
    sides, standing, listeners = body.sides, body.standing, body.listeners_side
    auto = not sides
    if auto:
        d = plan_defaults(db, ep)
        sides, standing, listeners = d["sides"], d["standing"], d["listeners_side"]
        if not sides:
            raise HTTPException(422, "the storyboard scenes put nobody on an approved set yet: build the scenes and choose the sets first")
    allowed = set(scene_sets.episode_sets(db, ep))
    bad = [s for s in sides if s not in allowed]
    if bad:
        raise HTTPException(422, f"not one of this episode's approved sets: {', '.join(bad)}")
    if _active(db, eid, ("shot_frames", "shot_frame_retake")).first():
        raise HTTPException(409, "the shot frames are already being made")
    listeners = listeners or list(sides)[-1]
    job = enqueue(db, "shot_frames", episode_id=eid,
                  payload={"sides": sides, "standing": standing, "listeners_side": listeners, "by": user, "auto": auto})
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Shot frames asked by {user} (free)"
                 + (": sides from the storyboard scenes" if auto else "")))
    db.commit()
    return S.job(job)


@router.get("/episodes/{eid}/shot-frames/plan-defaults")
def get_plan_defaults(eid: int, db: Session = Depends(get_db)):
    """The mapping a POST without a body would use (read-only)."""
    return plan_defaults(db, _episode(db, eid))


@router.get("/episodes/{eid}/shot-frames")
def get_frames(eid: int, db: Session = Depends(get_db)):
    from .storage import storage
    v = migrated(stored(db, eid))
    ids = {x["asset_id"] for s in v["shots"] for x in s["versions"]}
    ids |= {v[k] for k in ("sheet_asset_id", "animatic_asset_id") if v.get(k)}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}

    def url(aid):
        return storage().url(assets[aid].storage_key) if aid in assets else None
    shots = [{**s, "url": url(s["chosen"]), "versions": [{**x, "url": url(x["asset_id"])} for x in s["versions"]]}
             for s in v["shots"]]
    jobs = (db.query(Job).filter(Job.episode_id == eid, Job.kind.in_(("shot_frames", "shot_frame_retake", "shot_animatic")))
            .order_by(Job.id.desc()).limit(20).all())
    return {**{k: x for k, x in v.items() if k != "shots"}, "shots": shots,
            "sheet_url": url(v.get("sheet_asset_id")), "animatic_url": url(v.get("animatic_asset_id")),
            "approved": sum(1 for s in shots if s["approved"]), "jobs": [S.job(j) for j in jobs]}


class RetakeIn(BaseModel):
    shot: str | None = Field(None, pattern="^(close|medium|wide)$")
    people: list[str] | None = Field(None, max_length=12)
    side: str | None = Field(None, max_length=80)
    emotions: dict[str, str] = Field(default_factory=dict, max_length=12)


@router.post("/episodes/{eid}/shot-frames/{index}/retake")
def retake(eid: int, index: int, body: RetakeIn | None = Body(None), db: Session = Depends(get_db),
           user: str = Depends(current_user)):
    """Draw one shot again with the owner's changes (CPU, free). The new take is added to the shot's versions and
    chosen; the older takes are kept; the shot is no longer approved."""
    _episode(db, eid)
    body = body or RetakeIn()
    v = _plan_or_404(db, eid)
    s = _shot_or_404(v, index)
    sides = v.get("sides") or {}
    side = body.side or s["side"]
    if side not in sides:
        raise HTTPException(422, f"not one of this storyboard's sides: {side}")
    if body.people is not None:
        people = list(dict.fromkeys(body.people))
    elif side == s["side"]:
        people = list(s["people"])
    else:
        people = list(sides[side])
    stray = [p for p in people if p not in sides[side]]
    if stray:
        raise HTTPException(422, f"not on the {side} side: {', '.join(stray)}")
    for k, e in body.emotions.items():
        if k not in people:
            raise HTTPException(422, f"an expression for someone not in the shot: {k}")
        if len(e) > 40:
            raise HTTPException(422, "an expression is one word or two")
    shot = body.shot or s["shot"]
    if shot == "close" and len(people) > 1:
        raise HTTPException(422, "a close shot shows one person: choose medium or wide, or one person")
    if _active(db, eid, ("shot_frames",)).first():
        raise HTTPException(409, "the shot frames are being made again")
    if any((j.payload or {}).get("index") == index for j in _active(db, eid, ("shot_frame_retake",))):
        raise HTTPException(409, f"shot {index} is already being drawn again")
    emotions = {**{k: e for k, e in (s.get("emotions") or {}).items() if k in people},
                **{k: e for k, e in body.emotions.items() if e}}
    job = enqueue(db, "shot_frame_retake", episode_id=eid,
                  payload={"index": index, "plan_job_id": v.get("job_id"), "shot": shot, "people": people, "side": side,
                           "emotions": emotions, "note": retake_note(shot, people, side, emotions, s), "by": user})
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Shot {index}: retake asked by {user} (free)"))
    db.commit()
    return S.job(job)


class ChooseIn(BaseModel):
    asset_id: int


def _owner_change(db: Session, eid: int, v: dict, message: str) -> dict:
    save(db, eid, v)
    db.add(Event(episode_id=eid, kind="storyboard", message=message))
    db.commit()
    return get_frames(eid, db)


@router.post("/episodes/{eid}/shot-frames/{index}/choose")
def choose(eid: int, index: int, body: ChooseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Use another take of a shot (the owner's click). The shot then needs approving again."""
    _episode(db, eid)
    v = _plan_or_404(db, eid)
    s = _shot_or_404(v, index)
    take = next((x for x in s["versions"] if x["asset_id"] == body.asset_id), None)
    if take is None:
        raise HTTPException(422, f"not a take of shot {index}")
    s.update(chosen=take["asset_id"], asset_id=take["asset_id"], approved=False)
    s.update({k: take[k] for k in ("side", "people", "shot", "emotions") if k in take})   # the take's own staging
    n = s["versions"].index(take) + 1
    return _owner_change(db, eid, v, f"Shot {index}: take {n} chosen by {user} (not approved yet)")


def _set_approval(db: Session, eid: int, index: int, value: bool, user: str) -> dict:
    _episode(db, eid)
    v = _plan_or_404(db, eid)
    s = _shot_or_404(v, index)
    if value and not s["chosen"]:
        raise HTTPException(409, f"shot {index} has no frame to approve")
    s["approved"] = value
    return _owner_change(db, eid, v, f"Shot {index}: {'approved' if value else 'approval withdrawn'} by {user}")


@router.post("/episodes/{eid}/shot-frames/{index}/approve")
def approve(eid: int, index: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner approves a shot's chosen take (only ever this click; nothing approves by itself)."""
    return _set_approval(db, eid, index, True, user)


@router.post("/episodes/{eid}/shot-frames/{index}/unapprove")
def unapprove(eid: int, index: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _set_approval(db, eid, index, False, user)


@router.post("/episodes/{eid}/shot-frames/approve-all")
def approve_all(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner approves every shot's chosen take at once (their click)."""
    _episode(db, eid)
    v = _plan_or_404(db, eid)
    n = 0
    for s in v["shots"]:
        if s["chosen"] and not s["approved"]:
            s["approved"], n = True, n + 1
    return _owner_change(db, eid, v, f"Shot frames: all {len(v['shots'])} approved by {user} ({n} newly)")


@router.post("/episodes/{eid}/shot-frames/animatic")
def make_animatic(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The chosen frames on the recording's timeline, as a draft MP4 (FFmpeg on the server, free)."""
    from .config import get_settings
    _episode(db, eid)
    _plan_or_404(db, eid)
    if not get_settings().ffmpeg:
        raise HTTPException(409, "FFmpeg is not configured on this server (FFMPEG), so the animatic cannot be made")
    if _active(db, eid, ("shot_frames", "shot_animatic")).first():
        raise HTTPException(409, "the shot frames or the animatic are being made")
    job = enqueue(db, "shot_animatic", episode_id=eid, payload={"by": user})
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Animatic asked by {user} (free)"))
    db.commit()
    return S.job(job)


# ------------------------------------------------------------------ the jobs
from .tasks import Ctx, store_asset, task  # noqa: E402


def _render_one(ctx, ep, shot: dict, set_spec: dict, chars: dict, seat_of: dict, standing: set, folder: Path) -> Path:
    from . import acting
    from . import sets as studio_sets
    from .config import REPO_ROOT, get_settings
    from . import engine
    cast, faces, ratios = {}, {}, []
    for k in shot["people"]:
        c = chars[k]
        rd = acting.rig_for(ctx, c)
        rig = json.loads((rd / "rig.json").read_text())
        ratios.append(acting.head_ratio(rig))
        faces[k] = set(rig["faces"])
        lips = sum(rig["faces"]["neutral"]["mouth"].get("color", [0, 0, 0])) > 150
        start = "on" if k in standing or seat_of.get(k) is None else f"seat:{seat_of[k]}"
        cast[k] = {"rig": str(rd), "height": acting.HEIGHT, "lips": lips, "start": start}
    base_h, min_h = acting.scaled_height(set_spec.get("height"))
    h = acting.cast_height(studio_sets.seats_of(set_spec), max(ratios or [0.0]), base_h, min_h)
    for v in cast.values():
        v["height"] = h
    focus = shot["people"][0]
    face = lambda k: acting.face_for(faces[k], chars[k], shot["emotions"].get(k, "neutral"))
    line = {"speaker": focus, "text": "", "start": 0.2, "end": 1.4, "shot": shot["shot"], "expression": face(focus), "cues": [],
            "reactions": [{"character": k, "expression": face(k)} for k in shot["people"][1:]]}
    fw, fh = acting.frame_size(ep)
    spec = {"width": fw, "height": fh, "fps": 30, "duration": 1.6, "bubbles": False, "captions": False, "hook": "",
            "banner_font": str(acting.FONTS / "Anton-Regular.ttf"), "emoji_font": str(acting.FONTS / "NotoColorEmoji-Regular.ttf"),
            "font": str(REPO_ROOT / "skills/directing-stickman-videos/assets/fonts/NotoSans.ttf"),
            "set": set_spec, "cast": cast, "lines": [line], "end_card": None, "timeline": "absolute", "stills": [0.8]}
    spec_file = folder / f"shot-{shot['index']:03d}.json"
    spec_file.write_text(json.dumps(spec, indent=1))
    out = folder / f"shot-{shot['index']:03d}"
    s = get_settings()
    env = engine.env_for_node()
    r = subprocess.run(acting.node_command(s.node_bin, [str(acting.ANIM / "render-acting.mjs"), str(spec_file), str(out)], False),
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=env, timeout=600,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise engine.EngineRunError(f"shot {shot['index']}: the renderer failed: " + (r.stderr or r.stdout)[-600:])
    report = json.loads(r.stdout.strip().splitlines()[-1])
    files = [x["file"] for x in report.get("stills") or [] if x]
    if not files:
        raise engine.EngineRunError(f"shot {shot['index']}: no frame")
    return Path(files[0])


def _draw(ctx, ep, shot: dict, spec: dict, chars: dict, seat_of: dict, standing: set, folder: Path) -> Path:
    """One shot's frame: the acting renderer with its people, or the empty room when nobody is on screen."""
    from PIL import Image
    if shot["people"]:
        return _render_one(ctx, ep, shot, spec, chars, seat_of, standing, folder)
    f = folder / f"shot-{shot['index']:03d}-room.png"
    Image.open(spec["plate"]).convert("RGB").save(f)
    return f


@task
def shot_frames(ctx: Ctx) -> dict:
    from PIL import Image, ImageDraw
    from . import sets as studio_sets
    from .reference_plan import effective
    from .tasks import prepare_characters
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    sides, standing = p["sides"], set(p.get("standing") or [])
    tr = ep.audio_transcript or {}
    scenes = [{"line_ids": [ln.get("line_id") for ln in sc.lines], "set": sc.set_id or ep.set_id, "staging": sc.staging or {},
               "shots": {ln.get("line_id"): ln.get("shot") for ln in sc.lines}}
              for sc in db.query(StoryboardScene).filter_by(episode_id=ep.id).order_by(StoryboardScene.position)]
    shots = plan_shots(effective(tr), tr.get("lines", []), scenes, sides, p["listeners_side"])
    chars = prepare_characters(ctx)
    folder = ctx.folder("episodes", ep.id, "shot-frames", f"job{job.id}")
    specs = {sid: studio_sets.spec_for(db, sid, folder / f"set-{sid}") for sid in sides}
    seat_of = seats(sides, standing)
    made = []
    made_at = time.time()
    for shot in shots:
        if not shot["people"]:
            shot["note"] = "nobody the notes name is on screen: the room only"
        f = _draw(ctx, ep, shot, specs[shot["side"]], chars, seat_of, standing, folder)
        a = store_asset(db, ep_id=ep.id, src=f, key=f"episodes/{ep.id}/shot-frames/job{job.id}/shot-{shot['index']:03d}.png",
                        kind="shot-frame", label=f"Shot {shot['index']} ({shot['t0']:.1f}-{shot['t1']:.1f} s)",
                        content_type="image/png", job_id=job.id)
        first = {"asset_id": a.id, "at": made_at, "source": "first", "note": "",
                 **{k: shot[k] for k in ("side", "people", "shot", "emotions")}}
        made.append({**shot, "asset_id": a.id, "versions": [first], "chosen": a.id, "approved": False, "file": str(f)})
        job.progress = {"done": len(made), "total": len(shots)}
        db.commit()
        ctx.log(f"shot {shot['index']}: {shot['t0']:.1f}-{shot['t1']:.1f} s, {shot['shot']}, {', '.join(shot['people']) or 'room'} on {shot['side']}")
    # contact sheet, in order, labelled with the time and the people
    tw = 384
    th = round(tw * 9 / 16)
    cols = 5
    rows = max(1, (len(made) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 34) + 10), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    for i, m in enumerate(made):
        with Image.open(m["file"]) as im:
            t = im.convert("RGB")
            t.thumbnail((tw, th))
        x, y = 10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 34)
        sheet.paste(t, (x, y))
        d.text((x, y + th + 4), f"{m['index']}  {m['t0']:.1f}s  {m['shot']}  {', '.join(m['people'])[:44]}", fill=(230, 230, 230))
    sp = folder / "contact-sheet.png"
    sheet.save(sp)
    sa = store_asset(db, ep_id=ep.id, src=sp, key=f"episodes/{ep.id}/shot-frames/job{job.id}/contact-sheet.png",
                     kind="shot-frames-sheet", label="Shot frames (contact sheet)", content_type="image/png", job_id=job.id)
    save(db, ep.id, {"job_id": job.id, "made": made_at, "sides": sides, "standing": sorted(standing),
                     "listeners_side": p["listeners_side"], "sheet_asset_id": sa.id,
                     "shots": [{k: v for k, v in m.items() if k != "file"} for m in made]})
    db.add(Event(episode_id=ep.id, kind="storyboard", message=f"Shot frames: {len(made)} frames (one per shot), for the video step"))
    db.commit()
    return {"shots": len(made), "sheet_asset_id": sa.id}


@task
def shot_frame_retake(ctx: Ctx) -> dict:
    """One shot drawn again with the owner's changes; the new take is appended (never replacing one) and chosen."""
    from . import sets as studio_sets
    from .tasks import prepare_characters
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    index = int(p["index"])
    v = migrated(stored(db, ep.id))
    if v.get("job_id") != p.get("plan_job_id") or not 1 <= index <= len(v.get("shots") or []):
        raise ValueError("the shot frames were made again since this retake was asked: ask for it again")
    sides, standing = v["sides"], set(v.get("standing") or [])
    change = {"side": p["side"], "people": list(p["people"]), "shot": p["shot"], "emotions": dict(p.get("emotions") or {})}
    shot = {**v["shots"][index - 1], **change}
    folder = ctx.folder("episodes", ep.id, "shot-frames", f"retake-job{job.id}")
    chars = prepare_characters(ctx)
    spec = studio_sets.spec_for(db, change["side"], folder / f"set-{change['side']}")
    f = _draw(ctx, ep, shot, spec, chars, seats(sides, standing), standing, folder)
    a = store_asset(db, ep_id=ep.id, src=f, key=f"episodes/{ep.id}/shot-frames/retake-job{job.id}/shot-{index:03d}.png",
                    kind="shot-frame", label=f"Shot {index} retake ({shot['t0']:.1f}-{shot['t1']:.1f} s)",
                    content_type="image/png", job_id=job.id)
    db.commit()
    # read the plan again: the owner may have chosen or approved other shots while this one was drawn
    db.expire_all()
    v = migrated(stored(db, ep.id))
    if v.get("job_id") != p.get("plan_job_id"):
        raise ValueError("the shot frames were made again while this retake was drawn: ask for it again")
    s = v["shots"][index - 1]
    s["versions"].append({"asset_id": a.id, "at": time.time(), "source": "retake", "note": p.get("note") or "", **change})
    s.update(chosen=a.id, asset_id=a.id, approved=False, **change)
    save(db, ep.id, v)
    n = len(s["versions"])
    db.add(Event(episode_id=ep.id, kind="storyboard",
                 message=f"Shot {index}: take {n} drawn ({p.get('note') or 'drawn again'}), chosen, not approved yet"))
    db.commit()
    ctx.log(f"shot {index}: take {n}, {shot['shot']}, {', '.join(shot['people']) or 'room'} on {shot['side']}")
    return {"index": index, "asset_id": a.id, "takes": n}


ANIMATIC_LABEL = "Animatic: storyboard on the recording · Draft: not for publishing"


def _ffmpeg_animatic(ff: str, concat: Path, audio: Path | None, size: tuple[int, int], seconds: float, out: Path) -> None:
    w, h = size
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"fps=30,format=yuv420p")
    base = [ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat)]
    if audio:
        base += ["-i", str(audio)]
    tail = (["-vf", vf, "-map", "0:v"] + (["-map", "1:a", "-c:a", "aac", "-b:a", "128k"] if audio else [])
            + ["-t", f"{seconds:.3f}", "-movflags", "+faststart", str(out)])
    # H.264 plays in every browser; an FFmpeg built without it falls back to MPEG-4 Part 2
    err = ""
    for codec in (["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "28"], ["-c:v", "mpeg4", "-q:v", "6"]):
        r = subprocess.run(base + codec + tail, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and out.exists() and out.stat().st_size:
            return
        err = r.stderr or r.stdout or ""
    raise RuntimeError("FFmpeg could not make the animatic: " + err[-600:])


@task
def shot_animatic(ctx: Ctx) -> dict:
    """The chosen frames, each from its shot's start to the next one's, over the episode recording (a draft MP4)."""
    from . import acting, media
    from .config import get_settings
    from .storage import storage
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    ff = get_settings().ffmpeg
    if not ff:
        raise RuntimeError("FFmpeg is not configured on this server (FFMPEG)")
    v = migrated(stored(db, ep.id))
    shots = [s for s in v.get("shots") or [] if s.get("chosen")]
    if not shots:
        raise ValueError("no shot frames to put on the recording")
    folder = ctx.folder("episodes", ep.id, "shot-frames", f"animatic-job{job.id}")
    audio = None
    rec = db.get(Asset, ep.audio_asset_id) if ep.audio_asset_id else None
    if rec is not None:
        audio = storage().get_to_file(rec.storage_key, folder / ("recording" + (Path(rec.storage_key).suffix or ".m4a")))
    else:
        ctx.log("no recording on this episode: the animatic is silent")
    end = None
    if audio is not None:
        try:
            end = media.probe(audio).get("duration")
        except media.MediaError:
            end = None
    end = end or max(float(s.get("t1") or 0) for s in shots)
    frames = {}
    for s in shots:
        a = db.get(Asset, s["chosen"])
        frames[int(s["index"])] = storage().get_to_file(a.storage_key, folder / f"shot-{int(s['index']):03d}.png")
    timeline = animatic_timeline(shots, end)
    total = timeline[-1][1] + timeline[-1][2]
    lines = ["ffconcat version 1.0"]
    for idx, _start, secs in timeline:
        lines += [f"file '{Path(frames[idx]).resolve().as_posix()}'", f"duration {secs:.3f}"]
    lines.append(f"file '{Path(frames[timeline[-1][0]]).resolve().as_posix()}'")   # the concat demuxer needs the last one twice
    concat = folder / "frames.ffconcat"
    concat.write_text("\n".join(lines) + "\n")
    out = folder / "animatic.mp4"
    ctx.log(f"animatic: {len(timeline)} shots over {total:.1f} s" + (" with the recording" if audio else ""))
    _ffmpeg_animatic(ff, concat, audio, acting.frame_size(ep), total, out)
    a = store_asset(db, ep_id=ep.id, src=out, key=f"episodes/{ep.id}/shot-frames/animatic-job{job.id}.mp4", kind="animatic",
                    label=ANIMATIC_LABEL, content_type="video/mp4", job_id=job.id)
    db.commit()
    db.expire_all()
    v = stored(db, ep.id)
    v["animatic_asset_id"] = a.id
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="storyboard", message=f"Animatic: {len(timeline)} shots on the recording ({total:.1f} s), a draft"))
    db.commit()
    return {"asset_id": a.id, "seconds": round(total, 2), "shots": len(timeline)}
