"""Shot stills and their animation in the stick pipeline (owner decision 2026-11-25), on the storyboard's shot plan
(shot_frames.py: one entry per shot, its takes, the chosen one and the owner's approval).

Make still   one paid image (nano-banana edit) with the references [the shot's set, the approved master of every
             character in the shot]; the prompt says who is in the shot, seated or standing, what they do and feel. The
             still is added to the shot's takes (source "still"), chosen, NOT approved: the owner approves it with the
             storyboard's own Approve. Make still again = a new take; the older takes are kept.
Animate      an APPROVED shot's chosen frame -> image-to-video (wan-2.2 i2v 720p), priced per second of video. The clip
             is kept in the shot's clips (all versions), chosen, not approved; the owner approves a clip with a click.
Animate all  one job per approved shot that has no clip yet; the total (clips x seconds x price per second) is shown
             and confirmed first.

Every paid request carries the price the owner saw (confirm_usd); a submit is never retried (wavespeed.run).
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from . import shot_frames as SF
from .auth import current_user
from .db import get_db
from .models import Asset, Character, Episode, Event, Job, StoryboardScene
from .queue import enqueue
from .settings_store import get_section
from .stick_pipeline import (IMAGE_PROVIDERS, VIDEO_PROVIDERS, approved_master, image_cost, image_provider,
                             require_confirmed, video_cost, video_provider)
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
JOBS = ("stick_shot_still", "stick_shot_animate")
NEGATIVE = ("changing the characters' design, new or extra characters, morphing faces, extra limbs, realistic humans, "
            "text, captions, speech bubbles, watermark, flicker, camera shake")


# ------------------------------------------------------------------ prompts (pure)
def aspect_ratio(ep) -> str:
    from .acting import frame_size
    w, h = frame_size(ep)
    return "16:9" if w > h else "9:16"


def spoken_in(shot: dict, lines: list[dict]) -> list[dict]:
    """The recorded lines that overlap the shot (most of the shot's time first)."""
    t0, t1 = float(shot["t0"]), float(shot["t1"])
    out = [ln for ln in lines if float(ln.get("end", 0)) > t0 + 0.05 and float(ln.get("start", 0)) < t1 - 0.05]
    return sorted(out, key=lambda ln: -(min(t1, float(ln["end"])) - max(t0, float(ln["start"]))))


def still_prompt(shot: dict, names: dict[str, str], standing: set, speaker: str | None, said: str, action: str,
                 aspect: str) -> str:
    """The shot plan in words: the set is image 1, each character's master the next images, in order."""
    people = shot.get("people") or []
    parts = [f"Image 1 is the set: keep its room, furniture, camera angle, lighting and colours unchanged.",
             "The other images are the approved character masters. Draw each character EXACTLY as in their image (same "
             "head, eyes, line style, accessory and colours); never redesign them and add nobody else."]
    size = {"close": "close-up of one character (head and shoulders)", "medium": "medium shot (waist up)",
            "wide": "wide shot (full bodies, the room visible)"}.get(shot.get("shot") or "wide", "wide shot")
    parts.append(f"Shot: {size}, {aspect} frame.")
    if not people:
        parts.append("Nobody is in this shot: the empty room only.")
    for i, k in enumerate(people):
        pose = "standing" if k in standing else "seated"
        emo = (shot.get("emotions") or {}).get(k) or "neutral"
        line = f"- {names.get(k, k)} (image {i + 2}): {pose}, looking {emo}"
        if k == speaker and said:
            line += f", speaking (mouth open mid-word), saying: \"{said[:160]}\""
        elif speaker and speaker in people:
            line += f", listening to {names.get(speaker, speaker)}"
        parts.append(line + ".")
    if action:
        parts.append(f"What happens: {action[:300]}")
    parts.append("Clean polished 2D cartoon, bold black outlines. No text, no captions, no speech bubbles, no watermark.")
    return "\n".join(parts)


def motion_prompt(shot: dict, names: dict[str, str], speaker: str | None, action: str) -> str:
    people = [names.get(k, k) for k in shot.get("people") or []]
    who = ", ".join(people) or "the empty room"
    bits = [f"2D cartoon animation of this exact frame: {who}."]
    if speaker and speaker in (shot.get("people") or []):
        bits.append(f"{names.get(speaker, speaker)} talks with small natural head and hand gestures; the others react subtly.")
    else:
        bits.append("Small natural movements: breathing, blinking, slight head turns.")
    if action:
        bits.append(action[:200])
    bits.append("Static camera. The characters keep exactly their look from the image.")
    return " ".join(bits)


def i2v_body(image_url: str, prompt: str, seconds: int, seed: int, last_image_url: str | None = None) -> dict:
    """The wan-2.2 i2v request. last_image (an end frame) is optional: start + end frame when given."""
    body = {"image": image_url, "prompt": prompt, "negative_prompt": NEGATIVE, "duration": seconds, "seed": seed}
    if last_image_url:
        body["last_image"] = last_image_url
    return body


def clips_of(s: dict) -> list[dict]:
    return [dict(c) for c in s.get("clips") or [] if c.get("asset_id")]


def needs_clip(s: dict) -> bool:
    """Animate all: an approved shot with a frame and no clip yet."""
    return bool(s.get("approved") and s.get("chosen") and not clips_of(s))


# ------------------------------------------------------------------ context
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _characters(db: Session) -> dict[str, Character]:
    return {c.key: c for c in db.query(Character)}


def shot_context(db: Session, ep: Episode, v: dict, s: dict) -> dict:
    """Who speaks, what they say and the scene's action for one shot (from the recording and the storyboard)."""
    tr = ep.audio_transcript or {}
    lines = spoken_in(s, tr.get("lines") or [])
    pm = tr.get("person_map") or {}
    first = lines[0] if lines else {}
    speaker = pm.get(first.get("speaker")) or first.get("character") or first.get("speaker")
    action = ""
    if first.get("id"):
        for sc in db.query(StoryboardScene).filter_by(episode_id=ep.id).order_by(StoryboardScene.position):
            if any(ln.get("line_id") == first["id"] for ln in sc.lines or []):
                action = (sc.action or sc.description or "").strip()
                break
    chars = _characters(db)
    names = {k: c.name for k, c in chars.items()}
    standing = set(v.get("standing") or [])
    return {"speaker": speaker, "said": (first.get("text") or "").strip(), "action": action, "names": names,
            "standing": standing, "chars": chars}


def missing_masters(db: Session, s: dict, chars: dict[str, Character]) -> list[str]:
    return [k for k in s.get("people") or [] if k not in chars or approved_master(db, chars[k].id) is None]


def _active(db: Session, eid: int):
    return db.query(Job).filter(Job.kind.in_(JOBS), Job.episode_id == eid, Job.status.in_(("queued", "running")))


def _busy_on(db: Session, eid: int, index: int) -> bool:
    return any((j.payload or {}).get("index") == index for j in _active(db, eid))


# ------------------------------------------------------------------ routes
@router.get("/episodes/{eid}/stick-shots")
def get_stick_shots(eid: int, db: Session = Depends(get_db)):
    """Per shot: the still's cost and prompt, characters without an approved master, the clips; and Animate all's
    total. Read-only."""
    ep = _episode(db, eid)
    st = get_section(db, "stick")
    ip, vp = IMAGE_PROVIDERS.get(st.get("image_provider")), VIDEO_PROVIDERS.get(st.get("video_provider"))
    seconds = int(st.get("video_seconds") or 5)
    v = SF.migrated(SF.stored(db, eid))
    shots = v.get("shots") or []
    ids = {c["asset_id"] for s in shots for c in clips_of(s)}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}
    out = []
    for s in shots:
        cx = shot_context(db, ep, v, s)
        clips = [{**c, "url": storage().url(assets[c["asset_id"]].storage_key) if c["asset_id"] in assets else None}
                 for c in clips_of(s)]
        out.append({"index": s["index"], "missing_masters": missing_masters(db, s, cx["chars"]),
                    "prompt": still_prompt(s, cx["names"], cx["standing"], cx["speaker"], cx["said"], cx["action"], aspect_ratio(ep)),
                    "motion_prompt": motion_prompt(s, cx["names"], cx["speaker"], cx["action"]),
                    "clips": clips, "clip_chosen": s.get("clip_chosen"), "clip_approved": bool(s.get("clip_approved")),
                    "busy": _busy_on(db, eid, s["index"])})
    todo = [s["index"] for s in shots if needs_clip(s)]
    jobs = db.query(Job).filter(Job.kind.in_(JOBS), Job.episode_id == eid).order_by(Job.id.desc()).limit(30).all()
    return {"image": {"provider": st.get("image_provider"), "label": ip["label"] if ip else "off",
                      "cost": image_cost(1, ip["usd_per_image"]) if ip else None},
            "video": {"provider": st.get("video_provider"), "label": vp["label"] if vp else "off", "seconds": seconds,
                      "durations": vp["durations"] if vp else [5, 8],
                      "usd_per_second": vp["usd_per_second"] if vp else None,
                      "cost": video_cost(seconds, vp["usd_per_second"]) if vp and vp["implemented"] else None},
            "animate_all": {"shots": todo, "cost": video_cost(seconds, vp["usd_per_second"], len(todo))
                            if vp and vp["implemented"] else None},
            "shots": out, "jobs": [S.job(j) for j in jobs]}


class StillIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=100)
    # the owner's own prompt (e.g. applied from the chat under the shot); empty = the shot plan in words
    prompt: str | None = Field(default=None, max_length=4000)


@router.post("/episodes/{eid}/shot-frames/{index}/still")
def make_still(eid: int, index: int, body: StillIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """One paid still for a shot (cost shown and confirmed first). Refs: the shot's set, then each character's master."""
    ep = _episode(db, eid)
    v = SF._plan_or_404(db, eid)
    s = SF._shot_or_404(v, index)
    prov = image_provider(db)
    cx = shot_context(db, ep, v, s)
    miss = missing_masters(db, s, cx["chars"])
    if miss:
        raise HTTPException(409, "approve a master for " + ", ".join(cx["names"].get(k, k) for k in miss) + " first")
    if SF._active(db, eid, ("shot_frames",)).first():
        raise HTTPException(409, "the shot frames are being made again")
    if _busy_on(db, eid, index):
        raise HTTPException(409, f"shot {index} is already being made")
    cost = image_cost(1, prov["usd_per_image"])
    require_confirmed(cost["usd"], body.confirm_usd)
    prompt = (body.prompt or "").strip() or still_prompt(s, cx["names"], cx["standing"], cx["speaker"], cx["said"],
                                                          cx["action"], aspect_ratio(ep))
    job = enqueue(db, "stick_shot_still", episode_id=eid,
                  payload={"index": index, "plan_job_id": v.get("job_id"), "side": s["side"], "people": list(s["people"]),
                           "prompt": prompt, "aspect_ratio": aspect_ratio(ep), "provider": prov["id"],
                           "usd": cost["usd"], "by": user})
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Shot {index}: still asked by {user} ({cost['label']})"))
    db.commit()
    return S.job(job)


class AnimateIn(BaseModel):
    seconds: int = Field(default=5)
    confirm_usd: float | None = Field(default=None, ge=0, le=100)
    prompt: str | None = Field(default=None, max_length=1500)


def _check_seconds(prov: dict, seconds: int) -> None:
    if seconds not in prov["durations"]:
        raise HTTPException(422, f"duration must be one of {', '.join(map(str, prov['durations']))} seconds")


def _enqueue_animate(db: Session, ep: Episode, v: dict, s: dict, prov: dict, seconds: int, prompt: str | None, user: str) -> Job:
    cx = shot_context(db, ep, v, s)
    cost = video_cost(seconds, prov["usd_per_second"])
    return enqueue(db, "stick_shot_animate", episode_id=ep.id,
                   payload={"index": s["index"], "plan_job_id": v.get("job_id"), "frame_asset_id": s["chosen"],
                            "seconds": seconds, "prompt": prompt or motion_prompt(s, cx["names"], cx["speaker"], cx["action"]),
                            "provider": prov["id"], "usd": cost["usd"], "seed": random.randint(1, 2**31 - 1), "by": user})


@router.post("/episodes/{eid}/shot-frames/{index}/animate")
def animate(eid: int, index: int, body: AnimateIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Animate one approved shot (paid per second of video, confirmed first). Again = a new clip; older ones kept."""
    ep = _episode(db, eid)
    v = SF._plan_or_404(db, eid)
    s = SF._shot_or_404(v, index)
    prov = video_provider(db)
    _check_seconds(prov, body.seconds)
    if not (s.get("approved") and s.get("chosen")):
        raise HTTPException(409, f"approve shot {index}'s still first: only approved stills are animated")
    if _busy_on(db, eid, index):
        raise HTTPException(409, f"shot {index} is already being made")
    cost = video_cost(body.seconds, prov["usd_per_second"])
    require_confirmed(cost["usd"], body.confirm_usd)
    job = _enqueue_animate(db, ep, v, s, prov, body.seconds, body.prompt, user)
    db.add(Event(episode_id=eid, kind="storyboard", message=f"Shot {index}: animation asked by {user} ({cost['label']})"))
    db.commit()
    return S.job(job)


class AnimateAllIn(BaseModel):
    seconds: int = Field(default=5)
    confirm_usd: float | None = Field(default=None, ge=0, le=1000)


@router.post("/episodes/{eid}/shot-frames/animate-all")
def animate_all(eid: int, body: AnimateAllIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Every approved shot without a clip, one job (one paid call) each; the total is confirmed first."""
    ep = _episode(db, eid)
    v = SF._plan_or_404(db, eid)
    prov = video_provider(db)
    _check_seconds(prov, body.seconds)
    todo = [s for s in v["shots"] if needs_clip(s) and not _busy_on(db, eid, s["index"])]
    if not todo:
        raise HTTPException(409, "no approved shot is waiting for a clip")
    cost = video_cost(body.seconds, prov["usd_per_second"], len(todo))
    require_confirmed(cost["usd"], body.confirm_usd)
    jobs = [_enqueue_animate(db, ep, v, s, prov, body.seconds, None, user) for s in todo]
    db.add(Event(episode_id=eid, kind="storyboard",
                 message=f"Animate all: {len(todo)} shot(s) asked by {user} ({cost['label']})"))
    db.commit()
    return {"jobs": [S.job(j) for j in jobs], "cost": cost}


class ClipIn(BaseModel):
    asset_id: int


def _clip_change(db: Session, eid: int, index: int, asset_id: int, approve: bool | None, user: str) -> dict:
    _episode(db, eid)
    v = SF._plan_or_404(db, eid)
    s = SF._shot_or_404(v, index)
    if asset_id not in [c["asset_id"] for c in clips_of(s)]:
        raise HTTPException(422, f"not a clip of shot {index}")
    if approve is None:          # choose another clip: it needs approving again
        s.update(clip_chosen=asset_id, clip_approved=False)
        msg = f"Shot {index}: clip {asset_id} chosen by {user} (not approved yet)"
    else:
        s.update(clip_chosen=asset_id, clip_approved=approve)
        msg = f"Shot {index}: clip {asset_id} {'approved' if approve else 'approval withdrawn'} by {user}"
    SF.save(db, eid, v)
    db.add(Event(episode_id=eid, kind="storyboard", message=msg))
    db.commit()
    return get_stick_shots(eid, db)


@router.post("/episodes/{eid}/shot-frames/{index}/clip/approve")
def approve_clip(eid: int, index: int, body: ClipIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner approves a clip (only this click)."""
    return _clip_change(db, eid, index, body.asset_id, True, user)


@router.post("/episodes/{eid}/shot-frames/{index}/clip/unapprove")
def unapprove_clip(eid: int, index: int, body: ClipIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _clip_change(db, eid, index, body.asset_id, False, user)


@router.post("/episodes/{eid}/shot-frames/{index}/clip/choose")
def choose_clip(eid: int, index: int, body: ClipIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _clip_change(db, eid, index, body.asset_id, None, user)


# ------------------------------------------------------------------ the jobs
from .tasks import Ctx, store_asset, task  # noqa: E402


def set_image(db: Session, set_id: str, folder: Path) -> Path:
    """The shot's set as a local image (an approved studio set or a repository plate)."""
    from . import sets as studio_sets
    spec = studio_sets.spec_for(db, set_id, folder / f"set-{set_id}")
    if not spec or not Path(spec["plate"]).exists():
        raise ValueError(f"the set {set_id} has no usable image")
    return Path(spec["plate"])


def _fresh_plan(db: Session, eid: int, p: dict) -> dict:
    db.expire_all()
    v = SF.migrated(SF.stored(db, eid))
    if v.get("job_id") != p.get("plan_job_id") or not 1 <= int(p["index"]) <= len(v.get("shots") or []):
        raise ValueError("the shot frames were made again since this was asked: ask again")
    return v


@task
def stick_shot_still(ctx: Ctx) -> dict:
    """One shot's still (paid, one image); a new take of the shot, chosen, not approved."""
    from .stick_pipeline import run_images
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    ep = db.get(Episode, job.episode_id)
    index = int(p["index"])
    _fresh_plan(db, ep.id, p)
    folder = ctx.folder("episodes", ep.id, "stick-shots", f"still-job{job.id}")
    chars = _characters(db)
    refs = [set_image(db, p["side"], folder)]
    for k in p["people"]:
        m = approved_master(db, chars[k].id) if k in chars else None
        if m is None:
            raise ValueError(f"{k} has no approved master any more: approve one and ask again")
        refs.append(storage().get_to_file(m.storage_key, folder / f"master-{k}.png"))
    asset = None
    for _i, f in run_images(ctx, p["provider"], p["prompt"], refs, 1, float(p["usd"]), p["aspect_ratio"], folder,
                            f"episode {ep.id} shot {index} still"):
        asset = store_asset(db, ep_id=ep.id, src=f, key=f"episodes/{ep.id}/stick-shots/still-job{job.id}/shot-{index:03d}.png",
                            kind="shot-frame", label=f"Shot {index} still", content_type="image/png", job_id=job.id)
        db.commit()
    v = _fresh_plan(db, ep.id, p)
    s = v["shots"][index - 1]
    s["versions"].append({"asset_id": asset.id, "at": time.time(), "source": "still", "note": "still (image model)",
                          "side": s["side"], "people": list(s["people"]), "shot": s["shot"], "emotions": dict(s.get("emotions") or {})})
    s.update(chosen=asset.id, asset_id=asset.id, approved=False)
    SF.save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="storyboard", message=f"Shot {index}: still made (take {len(s['versions'])}), waiting for approval"))
    db.commit()
    return {"index": index, "asset_id": asset.id, "takes": len(s["versions"])}


@task
def stick_shot_animate(ctx: Ctx) -> dict:
    """One approved shot animated (paid per second); the clip is added to the shot's clips, chosen, not approved."""
    from . import wavespeed
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    ep = db.get(Episode, job.episode_id)
    index = int(p["index"])
    v = _fresh_plan(db, ep.id, p)
    s = v["shots"][index - 1]
    if not s.get("approved") or s.get("chosen") != p["frame_asset_id"]:
        raise ValueError(f"shot {index}'s approved still changed since the animation was asked: ask again")
    prov = VIDEO_PROVIDERS[p["provider"]]
    folder = ctx.folder("episodes", ep.id, "stick-shots", f"clip-job{job.id}")
    frame = db.get(Asset, p["frame_asset_id"])
    local = storage().get_to_file(frame.storage_key, folder / f"frame{Path(frame.storage_key).suffix or '.png'}")
    url = wavespeed.upload(local)
    out = folder / "clip.mp4"
    body = i2v_body(url, p["prompt"], int(p["seconds"]), int(p["seed"]))
    _data, tm = wavespeed.run(db, prov["model"], body, float(p["usd"]), f"episode {ep.id} shot {index} clip", out, ctx.log)
    a = store_asset(db, ep_id=ep.id, src=out, key=f"episodes/{ep.id}/stick-shots/clip-job{job.id}/shot-{index:03d}.mp4",
                    kind="shot-clip", label=f"Shot {index} clip ({p['seconds']} s)", content_type="video/mp4", job_id=job.id)
    db.commit()
    v = _fresh_plan(db, ep.id, p)
    s = v["shots"][index - 1]
    s["clips"] = clips_of(s) + [{"asset_id": a.id, "at": time.time(), "seconds": int(p["seconds"]), "usd": float(p["usd"]),
                                 "frame_asset_id": p["frame_asset_id"], "seed": int(p["seed"]), "job_id": job.id,
                                 "request_id": tm.get("request_id")}]
    s.update(clip_chosen=a.id, clip_approved=False)
    SF.save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="storyboard", message=f"Shot {index}: clip made ({p['seconds']} s), waiting for approval"))
    db.commit()
    return {"index": index, "asset_id": a.id, "clips": len(s["clips"])}
