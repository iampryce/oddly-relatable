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
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
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
    row = db.get(Setting, key(eid))
    return dict(row.value) if row else {}


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


# ------------------------------------------------------------------ routes
class PlanIn(BaseModel):
    sides: dict[str, list[str]] = Field(..., min_length=1, max_length=6)       # set id -> characters, in seat order
    standing: list[str] = Field(default_factory=list, max_length=12)           # characters who stand (not seated)
    listeners_side: str | None = None                                          # the side for ties (default: the last)


@router.post("/episodes/{eid}/shot-frames")
def make_frames(eid: int, body: PlanIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Plan the shots from the accepted notes and render one frame per shot (CPU, free)."""
    from . import scene_sets
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    allowed = set(scene_sets.episode_sets(db, ep))
    bad = [s for s in body.sides if s not in allowed]
    if bad:
        raise HTTPException(422, f"not one of this episode's approved sets: {', '.join(bad)}")
    if db.query(Job).filter(Job.kind == "shot_frames", Job.episode_id == eid, Job.status.in_(("queued", "running"))).first():
        raise HTTPException(409, "the shot frames are already being made")
    listeners = body.listeners_side or list(body.sides)[-1]
    job = enqueue(db, "shot_frames", episode_id=eid,
                  payload={"sides": body.sides, "standing": body.standing, "listeners_side": listeners, "by": user})
    return S.job(job)


@router.get("/episodes/{eid}/shot-frames")
def get_frames(eid: int, db: Session = Depends(get_db)):
    from .storage import storage
    v = stored(db, eid)
    ids = [s.get("asset_id") for s in v.get("shots", []) if s.get("asset_id")] + ([v["sheet_asset_id"]] if v.get("sheet_asset_id") else [])
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}
    shots = [{**s, "url": storage().url(assets[s["asset_id"]].storage_key) if s.get("asset_id") in assets else None}
             for s in v.get("shots", [])]
    sheet = assets.get(v.get("sheet_asset_id"))
    return {**{k: x for k, x in v.items() if k != "shots"}, "shots": shots,
            "sheet_url": storage().url(sheet.storage_key) if sheet else None}


# ------------------------------------------------------------------ the job
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
    seat_of = {}
    for sid, members in sides.items():
        n = 0
        for k in members:
            if k not in standing:
                seat_of[k], n = n, n + 1
    made = []
    for shot in shots:
        if not shot["people"]:
            shot["note"] = "nobody the notes name is on screen: the room only"
        if shot["people"]:
            f = _render_one(ctx, ep, shot, specs[shot["side"]], chars, seat_of, standing, folder)
        else:
            f = folder / f"shot-{shot['index']:03d}-room.png"
            Image.open(specs[shot["side"]]["plate"]).convert("RGB").save(f)
        a = store_asset(db, ep_id=ep.id, src=f, key=f"episodes/{ep.id}/shot-frames/job{job.id}/shot-{shot['index']:03d}.png",
                        kind="shot-frame", label=f"Shot {shot['index']} ({shot['t0']:.1f}-{shot['t1']:.1f} s)",
                        content_type="image/png", job_id=job.id)
        made.append({**shot, "asset_id": a.id, "file": str(f)})
        job.progress = {"done": len(made), "total": len(shots)}
        db.commit()
        ctx.log(f"shot {shot['index']}: {shot['t0']:.1f}-{shot['t1']:.1f} s, {shot['shot']}, {', '.join(shot['people']) or 'room'} on {shot['side']}")
    # contact sheet, in order, labelled with the time and the people
    tw = 384
    th = round(tw * 9 / 16)
    cols = 5
    rows = (len(made) + cols - 1) // cols
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
    save(db, ep.id, {"job_id": job.id, "made": time.time(), "sides": sides, "standing": sorted(standing),
                     "sheet_asset_id": sa.id, "shots": [{k: v for k, v in m.items() if k != "file"} for m in made]})
    db.add(Event(episode_id=ep.id, kind="storyboard", message=f"Shot frames: {len(made)} frames (one per shot), for the video step"))
    db.commit()
    return {"shots": len(made), "sheet_asset_id": sa.id}
