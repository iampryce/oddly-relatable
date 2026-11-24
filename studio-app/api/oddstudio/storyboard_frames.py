"""Storyboard frames: painted frames for an episode's shot list, made from the dashboard with the image provider in
Settings (Codex on the ChatGPT plan at $0 per frame, or the OpenAI Images API at a shown price).

The frame plan (frames, their prompts, which reference images each uses and which shots each serves) is uploaded by
the owner with its reference images. References must be the studio's own approved art (set plates, character
masters): never a frame of the reference video or anyone else's picture. Several shots can reuse one frame.

Making frames: the owner picks frames and clicks Make; one job makes them ONE AT A TIME, stops on the first failure
and is never retried automatically (no plan allowance or money spent that the owner did not start). A paid provider
needs the owner to confirm the shown worst-case total, which the job never exceeds.

Frames are drafts ("Draft: not for publishing"). Only the owner approves a frame, with their own click. A remade frame
keeps the earlier file (each attempt is its own asset). Stored in the settings table under "sbframes:<episode id>"
(no migration): {"frames": [...], "refs": {name: asset_id}, "made": {frame: [{asset_id, ...}, ...]},
"approved": {frame: asset_id}}.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Episode, Event, Job, Setting
from .queue import enqueue

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.png$")
FRAME_ID = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
MAX_REF_BYTES = 20 * 1024 * 1024
MAX_FRAMES = 200
MAX_REFS_PER_FRAME = 16
SIZES = ("1536x1024", "1024x1536", "1024x1024", "1536x864", "864x1536")
# OpenAI gpt-image-2 worst case per frame (standard rates; the real cost comes from the token counts): output at
# high quality plus about $0.02 per reference image and the prompt. Codex on the ChatGPT plan: $0.
OPENAI_BASE, OPENAI_PER_REF = 0.15, 0.02
DRAFT = "Draft: not for publishing"


def key(eid: int) -> str:
    return f"sbframes:{eid}"


def load(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return dict(row.value) if row else {"frames": [], "refs": {}, "made": {}, "approved": {}}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))
    db.flush()


def episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if not ep:
        raise HTTPException(404, "episode not found")
    return ep


def provider_cfg(db: Session) -> dict:
    from .settings_store import get_section
    return get_section(db, "image")


def frame_cost(provider: str, refs: int) -> float:
    return 0.0 if provider == "codex-cli" else round(OPENAI_BASE + OPENAI_PER_REF * refs, 4)


def estimate(db: Session, eid: int, frames: list[str]) -> dict:
    plan = load(db, eid)
    by_id = {f["frame"]: f for f in plan["frames"]}
    unknown = [f for f in frames if f not in by_id]
    if unknown:
        raise HTTPException(422, f"not in the frame plan: {', '.join(unknown)}")
    p = provider_cfg(db).get("provider", "none")
    if p not in ("codex-cli", "openai"):
        raise HTTPException(409, "Choose Codex (ChatGPT plan) or OpenAI as the image provider in Settings first")
    each = {f: frame_cost(p, len(by_id[f]["references"])) for f in frames}
    return {"provider": p, "frames": len(frames), "per_frame": each, "total": round(sum(each.values()), 4),
            "label": "$0 (ChatGPT plan allowance)" if p == "codex-cli" else f"up to ${sum(each.values()):.2f} (OpenAI, worst case)"}


def view(db: Session, eid: int) -> dict:
    plan = load(db, eid)
    ids = {a for v in plan["made"].values() for a in (m["asset_id"] for m in v)} | set(plan["refs"].values())
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}
    busy = db.query(Job).filter(Job.kind == "storyboard_frames", Job.episode_id == eid).order_by(Job.id.desc()).first()
    frames = []
    for f in plan["frames"]:
        made = [{**m, "asset": S.asset(assets.get(m["asset_id"]))} for m in plan["made"].get(f["frame"], [])]
        frames.append({**f, "made": made, "latest": made[-1] if made else None,
                       "approved_asset_id": plan["approved"].get(f["frame"]),
                       "missing_refs": [r for r in f["references"] if r not in plan["refs"]]})
    return {"frames": frames, "refs": {n: S.asset(assets.get(a)) for n, a in plan["refs"].items()},
            "provider": provider_cfg(db).get("provider", "none"), "job": S.job(busy) if busy else None, "status": DRAFT}


# ---------------------------------------------------------------- routes
class Shot(BaseModel):
    n: int
    start: float | None = None
    end: float | None = None
    text: str = Field("", max_length=600)


class Frame(BaseModel):
    frame: str
    prompt: str = Field(..., min_length=10, max_length=12000)
    references: list[str] = Field(default_factory=list, max_length=MAX_REFS_PER_FRAME)
    shots: list[Shot] = Field(default_factory=list)
    size: str = "1536x1024"
    title: str = Field("", max_length=200)


class Plan(BaseModel):
    frames: list[Frame] = Field(..., min_length=1, max_length=MAX_FRAMES)


@router.get("/episodes/{eid}/storyboard-frames")
def get_frames(eid: int, db: Session = Depends(get_db)):
    episode(db, eid)
    return view(db, eid)


@router.put("/episodes/{eid}/storyboard-frames/plan")
def put_plan(eid: int, body: Plan, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Replace the frame plan. Frames already made and approvals stay with their frame id."""
    episode(db, eid)
    seen = set()
    for f in body.frames:
        if not FRAME_ID.match(f.frame) or f.frame in seen:
            raise HTTPException(422, f"frame id {f.frame!r} is not valid or repeated")
        seen.add(f.frame)
        if f.size not in SIZES:
            raise HTTPException(422, f"{f.frame}: size must be one of {', '.join(SIZES)}")
        bad = [r for r in f.references if not NAME.match(r)]
        if bad:
            raise HTTPException(422, f"{f.frame}: reference names must be plain .png file names: {bad}")
    plan = load(db, eid)
    plan["frames"] = [f.model_dump() for f in body.frames]
    save(db, eid, plan)
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Storyboard frame plan set by {user}: {len(body.frames)} frames"))
    db.commit()
    return view(db, eid)


@router.put("/episodes/{eid}/storyboard-frames/references/{name}")
async def put_reference(eid: int, name: str, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """One reference image (raw PNG body). Only the studio's own approved art: never a reference-video frame."""
    episode(db, eid)
    if not NAME.match(name):
        raise HTTPException(422, "the name must be a plain .png file name")
    data = await request.body()
    if len(data) > MAX_REF_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "send one PNG image of at most 20 MB")
    a = _store(db, eid, data, f"episodes/{eid}/storyboard-frames/references/{name}", "storyboard-reference", name)
    plan = load(db, eid)
    plan["refs"][name] = a.id
    save(db, eid, plan)
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Storyboard reference {name} uploaded by {user}"))
    db.commit()
    return {"name": name, "asset": S.asset(a)}


@router.put("/episodes/{eid}/storyboard-frames/frames/{frame}/import")
async def import_frame(eid: int, frame: str, request: Request, source: str = "", db: Session = Depends(get_db),
                       user: str = Depends(current_user)):
    """Add a frame made outside the studio (raw PNG body), as a draft. Importing never approves it."""
    episode(db, eid)
    plan = load(db, eid)
    if frame not in {f["frame"] for f in plan["frames"]}:
        raise HTTPException(404, "not in the frame plan")
    data = await request.body()
    if len(data) > MAX_REF_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "send one PNG image of at most 20 MB")
    n = len(plan["made"].get(frame, [])) + 1
    a = _store(db, eid, data, f"episodes/{eid}/storyboard-frames/{frame}-import{n}-{int(time.time())}.png",
               "storyboard-frame", f"{frame} (imported; {DRAFT})")
    plan["made"].setdefault(frame, []).append({"asset_id": a.id, "provider": "imported", "source": source[:200],
                                               "at": time.time()})
    save(db, eid, plan)
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Storyboard frame {frame} imported by {user} (draft)"))
    db.commit()
    return view(db, eid)


class MakeBody(BaseModel):
    frames: list[str] = Field(..., min_length=1, max_length=MAX_FRAMES)
    confirm_total: float = 0.0    # the total the owner saw; required (and a ceiling) for a paid provider


@router.post("/episodes/{eid}/storyboard-frames/estimate")
def post_estimate(eid: int, body: MakeBody, db: Session = Depends(get_db)):
    episode(db, eid)
    return estimate(db, eid, body.frames)


@router.post("/episodes/{eid}/storyboard-frames/make")
def make(eid: int, body: MakeBody, db: Session = Depends(get_db), user: str = Depends(current_user)):
    episode(db, eid)
    est = estimate(db, eid, body.frames)
    if est["provider"] != "codex-cli" and body.confirm_total + 1e-9 < est["total"]:
        raise HTTPException(409, f"Confirm the cost first: {est['label']}")
    plan = load(db, eid)
    by_id = {f["frame"]: f for f in plan["frames"]}
    missing = sorted({r for f in body.frames for r in by_id[f]["references"] if r not in plan["refs"]})
    if missing:
        raise HTTPException(409, f"upload these reference images first: {', '.join(missing)}")
    if db.query(Job).filter(Job.kind == "storyboard_frames", Job.episode_id == eid,
                            Job.status.in_(("queued", "running"))).first():
        raise HTTPException(409, "frames are already being made for this episode")
    job = enqueue(db, "storyboard_frames", episode_id=eid,
                  payload={"frames": body.frames, "provider": est["provider"], "ceiling": est["total"], "by": user})
    return {"job": S.job(job), "estimate": est}


@router.post("/episodes/{eid}/storyboard-frames/frames/{frame}/approve")
def approve(eid: int, frame: str, asset_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner approves one made frame (their own click). Never done by a job."""
    episode(db, eid)
    plan = load(db, eid)
    if asset_id not in [m["asset_id"] for m in plan["made"].get(frame, [])]:
        raise HTTPException(404, "that image is not a made version of this frame")
    plan["approved"][frame] = asset_id
    save(db, eid, plan)
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Storyboard frame {frame} approved by {user} (asset {asset_id})"))
    db.commit()
    return view(db, eid)


@router.post("/episodes/{eid}/storyboard-frames/frames/{frame}/unapprove")
def unapprove(eid: int, frame: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    episode(db, eid)
    plan = load(db, eid)
    plan["approved"].pop(frame, None)
    save(db, eid, plan)
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Storyboard frame {frame} approval withdrawn by {user}"))
    db.commit()
    return view(db, eid)


def _store(db: Session, eid: int, data: bytes, key_: str, kind: str, label: str) -> Asset:
    from .config import get_settings
    from .tasks import store_asset
    tmp = get_settings().work_dir / "sbframes-upload" / hashlib.sha256(data).hexdigest()
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    try:
        return store_asset(db, ep_id=eid, src=tmp, key=key_, kind=kind, label=label, content_type="image/png")
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- the job
def run(ctx) -> dict:
    """Make the chosen frames one at a time; stop at the first failure (never retried automatically)."""
    from . import providers
    from .providers import ProviderError
    from .storage import storage
    from .tasks import store_asset
    db, job = ctx.db, ctx.job
    eid = job.episode_id
    pay = job.payload or {}
    cfg = {**provider_cfg(db), "fallback": "none", "background": None, "use_reference": True}
    if cfg.get("provider") != pay.get("provider"):
        raise ProviderError(f"the image provider changed since the cost was shown ({pay.get('provider')} -> "
                            f"{cfg.get('provider')}); start again to see the new cost")
    spent, done = 0.0, []
    work = ctx.folder("storyboard-frames", eid, f"job{job.id}")
    for fid in pay["frames"]:
        plan = load(db, eid)
        f = next((x for x in plan["frames"] if x["frame"] == fid), None)
        if f is None:
            raise ProviderError(f"{fid} is no longer in the frame plan (made so far: {done})")
        cost = frame_cost(cfg["provider"], len(f["references"]))
        if spent + cost > float(pay.get("ceiling", 0)) + 1e-9:
            raise ProviderError(f"stopped before {fid}: it would pass the confirmed total ${pay.get('ceiling')}")
        refs = []
        for r in f["references"]:
            a = db.get(Asset, plan["refs"].get(r, -1))
            if a is None:
                raise ProviderError(f"{fid}: reference {r} is missing (made so far: {done})")
            p = work / "refs" / r
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                storage().get_to_file(a.storage_key, p)
            refs.append(p)
        ctx.log(f"{fid}: making with {cfg['provider']} ({len(refs)} references)")
        t0 = time.time()
        out = work / f"{fid}.png"
        try:
            providers.image_generate({**cfg, "size": f.get("size") or "1536x1024"}, f["prompt"], out, refs)
        except Exception as e:
            # recorded on the job; never transient, so the worker does not retry it by itself
            raise ProviderError(f"{fid} failed (made before it: {', '.join(done) or 'none'}): {str(e)[:500]}",
                                transient=False) from e
        n = len(plan["made"].get(fid, [])) + 1
        a = store_asset(db, ep_id=eid, src=out, key=f"episodes/{eid}/storyboard-frames/{fid}-job{job.id}-v{n}.png",
                        kind="storyboard-frame", label=f"{fid} ({DRAFT})", content_type="image/png", job_id=job.id)
        plan = load(db, eid)
        plan["made"].setdefault(fid, []).append({"asset_id": a.id, "provider": cfg["provider"], "job_id": job.id,
                                                 "seconds": round(time.time() - t0, 1), "at": time.time()})
        save(db, eid, plan)
        db.commit()
        spent += cost
        done.append(fid)
        ctx.log(f"{fid}: done in {time.time() - t0:.0f} s")
    return {"made": done, "provider": cfg["provider"], "worst_case_spent": round(spent, 4)}
