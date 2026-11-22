"""Read the room from a video, and the owner's own reference image for a set (feat/episode-workspace, owner request
2026-11-22).

"Read the room from a video": the owner uploads a video only to describe the ROOM. A few frames are sampled evenly,
sent once to the studio's API vision provider with the set-notes schema (set_notes.scan_prompt: fixed lists, words
only, the roles layout as positions only), and the answer becomes the episode's set notes (set_proposal.set_notes),
one per room, editable and used verbatim by "Propose". It never touches the recording, the lines, the speakers or the
cast (the episode's audio_transcript is not written), and the video and its frames are deleted when the job ends,
whatever happens. The cost is shown before the upload and the job refuses to run over the episode cap
(Settings > Video and visual analysis).

The owner's own reference image: an upload the owner confirms is their own picture. Only such an image is ever sent to
the image generator with a set prompt (images/edits); without one every set is text only.
"""
from __future__ import annotations

import math
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import media
from .auth import current_user
from .db import get_db
from .models import Asset, Episode, Event
from .queue import enqueue
from . import serialize as S

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

LOCKED = ("producing", "publishing")
MIN_FRAMES, MAX_FRAMES, SECONDS_PER_FRAME = 4, 8, 8.0
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def frame_count(seconds: float | None) -> int:
    if not seconds or not math.isfinite(seconds) or seconds <= 0:
        return MIN_FRAMES
    return max(MIN_FRAMES, min(MAX_FRAMES, math.ceil(seconds / SECONDS_PER_FRAME)))


def frame_times(seconds: float | None) -> list[float]:
    """Evenly spread over the video (the middle of each slice), so every room in it is likely seen."""
    n = frame_count(seconds)
    length = seconds if seconds and seconds > 0 else n * 1.0
    return [round(length * (i + 0.5) / n, 2) for i in range(n)]


def estimate(db: Session, seconds: float | None) -> dict:
    """Frames, tokens and USD of the one call, with the cap and whether it fits; or why it cannot run."""
    from . import set_notes as SN
    from .audio_first import hints_vision_config
    from .notes_v2 import clamp_cap
    from .settings_store import get_section
    cap = clamp_cap(get_section(db, "vision").get("notes_cap_usd"))
    n = frame_count(seconds)
    try:
        cfg = hints_vision_config(db)
    except ValueError as e:
        return {"configured": False, "frames": n, "cap_usd": cap, "message": str(e)}
    est = SN.estimate(cfg["provider"], rooms_n=2, frames=n)
    est["output_tokens"] = est.get("output_tokens", 0) + 2 * SN.OUT_PER_ROOM      # up to 4 rooms
    from .notes_v2 import CALIBRATION
    from . import video_notes as VN
    p = VN.PRICES.get(cfg["provider"])
    if p:
        est["usd"] = round((est["input_tokens"] * p["in"] + est["output_tokens"] * p["out"]) / 1e6
                           * CALIBRATION.get(cfg["provider"], 1.0), 4)
    return {**est, "provider": cfg["provider"], "cap_usd": cap, "within_cap": est.get("usd", 0) <= cap,
            "note": "words only: the frames and the video are deleted after the call; the recording, lines, speakers "
                    "and cast are not touched"}


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    if ep.stage in LOCKED:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    return ep


async def _receive(request: Request, folder: Path, prefix: str, types: dict, cap: int) -> tuple[Path, str]:
    """Stream the raw request body to a temporary file (size cap and free-space check first)."""
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in types:
        raise HTTPException(415, f"upload one of: {', '.join(sorted(set(types.values())))}")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > cap:
        raise HTTPException(413, f"the file is larger than {cap // 1048576} MB")
    try:
        media.check_free_space(folder, declared or cap)
    except OSError as e:
        raise HTTPException(507, str(e))
    tmp = folder / f"{prefix}-{uuid.uuid4().hex[:8]}{types[ctype]}"
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > cap:
                    raise HTTPException(413, f"the file is larger than {cap // 1048576} MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, "the uploaded file is empty")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, ctype


@router.get("/episodes/{eid}/set-notes/read-video/estimate")
def read_estimate(eid: int, seconds: float = 0.0, db: Session = Depends(get_db)):
    """Before the upload: the cost of reading the room from a video of `seconds` (frames, tokens, USD, the cap)."""
    if db.get(Episode, eid) is None:
        raise HTTPException(404, "episode not found")
    return estimate(db, seconds or None)


@router.put("/episodes/{eid}/set-notes/read-video")
async def read_video(eid: int, request: Request, db: Session = Depends(get_db)):
    """The owner's video, for the room only: stored as a temporary upload and handed to `set_notes_read_video`, which
    samples the frames, asks once and deletes the video and the frames. Refused over the cap."""
    from .audio_first import MAX_VIDEO_BYTES, VIDEO_TYPES, uploads_dir
    from .config import get_settings
    ep = _episode(db, eid)
    if not (get_settings().ffmpeg and get_settings().ffprobe):
        raise HTTPException(503, "FFmpeg and FFprobe are not configured on this server, so video files cannot be read")
    tmp, _ = await _receive(request, uploads_dir(), f"room-{ep.id}", VIDEO_TYPES, MAX_VIDEO_BYTES)
    try:
        try:
            info = media.probe(tmp)
        except media.MediaError as e:
            raise HTTPException(422, str(e))
        if info.get("video") is False:
            raise HTTPException(422, "this file has no picture to read the room from")
        est = estimate(db, info.get("duration"))
        if not est.get("configured"):
            raise HTTPException(409, est.get("message") or "no API vision provider")
        if not est["within_cap"]:
            raise HTTPException(409, f"reading the room would cost about ${est['usd']:.3f}, over the ${est['cap_usd']:.2f} cap")
        job = enqueue(db, "set_notes_read_video", episode_id=ep.id, revision=ep.revision,
                      payload={"upload": tmp.name, "seconds": info.get("duration"), "estimated_usd": est["usd"]})
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Reading the room from a video (about ${est['usd']:.3f}; "
                                                              "the video is deleted after use)"))
        db.commit()
        return {"job": S.job(job), "estimate": est}
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ the owner's own reference image
@router.put("/episodes/{eid}/set-proposal/reference")
async def attach_reference(eid: int, request: Request, own: bool = False, db: Session = Depends(get_db)):
    """Attach the owner's OWN reference picture for this episode's sets (they confirm it is theirs: no video frame,
    no third-party image). Every set generated afterwards for this episode follows its layout (images/edits) until it
    is removed. Nothing is generated here."""
    from .audio_first import uploads_dir
    from .tasks import store_asset
    ep = _episode(db, eid)
    if not own:
        raise HTTPException(422, "confirm the picture is your own (not a video frame or someone else's image)")
    tmp, ctype = await _receive(request, uploads_dir(), f"setref-{ep.id}", IMAGE_TYPES, MAX_IMAGE_BYTES)
    try:
        from PIL import Image
        try:
            with Image.open(tmp) as im:
                im.verify()
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "the file is not a readable image")
        a = store_asset(db, ep_id=ep.id, src=tmp, key=f"set-references/ep{ep.id}/{tmp.name}", kind="set-own-reference",
                        label="Your own set reference", content_type=ctype)
        p = dict(ep.set_proposal or {})
        p["reference"] = {"asset_id": a.id, "label": f"your own picture (asset {a.id})", "at": time.time()}
        ep.set_proposal = p
        db.add(Event(episode_id=ep.id, kind="episode", message="Own set reference attached (used for the next set "
                                                              "candidates of this episode until removed)"))
        db.commit()
    finally:
        tmp.unlink(missing_ok=True)
    from .set_proposals import view
    return view(db, ep)


@router.delete("/episodes/{eid}/set-proposal/reference")
def remove_reference(eid: int, db: Session = Depends(get_db)):
    ep = _episode(db, eid)
    p = dict(ep.set_proposal or {})
    if p.pop("reference", None) is not None:
        ep.set_proposal = p
        db.add(Event(episode_id=ep.id, kind="episode", message="Own set reference removed: new sets are text only"))
        db.commit()
    from .set_proposals import view
    return view(db, ep)


# ------------------------------------------------------------------ the job
from .tasks import Ctx, task  # noqa: E402


@task
def set_notes_read_video(ctx: Ctx) -> dict:
    """Frames -> one vision call -> set notes (words only) on set_proposal. The video and the frames are deleted when
    the job ends, whatever happens; the episode's recording, lines, speakers and cast are never written."""
    from . import analysis
    from . import set_notes as SN
    from .audio_first import _in_uploads, hints_vision_config, uploads_dir
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    src = _in_uploads(p.get("upload", ""))
    frames_dir = uploads_dir() / f"room-frames-{job.id}-{uuid.uuid4().hex[:6]}"
    try:
        ep = db.get(Episode, job.episode_id)
        if not src.exists():
            return {"skipped": "the video is gone (already used or swept)"}
        est = estimate(db, p.get("seconds"))
        if not est.get("configured"):
            raise ValueError(est.get("message") or "no API vision provider")
        if not est["within_cap"]:
            raise ValueError(f"about ${est['usd']:.3f}, over the ${est['cap_usd']:.2f} cap")
        try:
            frames = media.sample_frames_at(src, frames_dir, frame_times(p.get("seconds")))
        finally:
            src.unlink(missing_ok=True)
        ctx.log(f"{len(frames)} frame(s) sampled; video deleted")
        if not frames:
            raise ValueError("no frames could be read from the video")
        cfg = hints_vision_config(db)
        analysis.last_vision_usage.clear()
        ans = analysis.analyse_images(cfg, [f for f, _ in frames], SN.scan_prompt(len(frames)))
        usage = dict(analysis.last_vision_usage)
        rooms, stripped = SN.clean_scan(ans)
        if not rooms:
            raise ValueError("the answer described no room in the allowed words: nothing saved")
        notes = []
        for e in rooms:
            seated = sum(g["count"] for g in e.get("layout", []) if g["pose"] == "seated")
            people = sum(g["count"] for g in e.get("layout", []))
            notes.append({"room": e["room"], "fields": e, "text": SN.room_text(e), "signature": SN.signature(e),
                          "edited": False, "seats": max(e.get("seats") or 0, seated) or None, "people": people or None})
        db.refresh(ep)
        sp = dict(ep.set_proposal or {})
        sp["set_notes"] = notes
        sp["set_notes_source"] = {"from": "a video read for the room (deleted)", "job_id": job.id, "frames": len(frames),
                                  "stripped": stripped, "usage": usage, "estimated_usd": est.get("usd"), "at": time.time()}
        ep.set_proposal = sp
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Room read from a video: {len(notes)} room(s), "
                                                              f"{stripped} value(s) outside the lists removed; video and "
                                                              "frames deleted"))
        db.commit()
        if usage:
            ctx.log(f"vision call: {usage.get('provider')} {usage.get('model')}, {usage.get('input_tokens')} in / "
                    f"{usage.get('output_tokens')} out tokens")
        return {"rooms": len(notes), "frames": len(frames), "stripped": stripped, "usage": usage}
    finally:
        src.unlink(missing_ok=True)
        shutil.rmtree(frames_dir, ignore_errors=True)
