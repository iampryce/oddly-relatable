"""The guided generation page (/episodes/{id}/guide): one list of steps from the uploads to the final review, each with
its status and its live cost. The help text lives in the web page; this module reports facts only.

It also keeps the episode's reference video for the acting analysis. The video is the owner's own upload, stored under
private/ (never in the episode's asset list, so nothing else can pick it up as an image or video reference) and only
ever sent to the acting analysis. The owner can remove it at any time.

Step statuses: not_started | running | needs_approval | done. Steps 10-11 are not in the dashboard yet ("available":
false) and never offer a button.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, CharacterAsset, Episode, Event, Job, Setting
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

MAX_VIDEO_BYTES = 250 * 1024 * 1024
VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
PLACEHOLDERS = ("quality", "assembly")
ORDER = ("upload", "acting", "prompts", "masters", "sets", "closeups", "faces", "movement", "talking", "quality", "assembly")


def key(eid: int) -> str:
    return f"guide:{eid}"


def _stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return dict(row.value) if row else {}


def _save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = v
    else:
        db.add(Setting(key=key(eid), value=v))


def reference_video(db: Session, eid: int) -> dict | None:
    """{key, content_type, seconds, size, uploaded} or None. The storage key stays on the server."""
    return _stored(db, eid).get("reference_video")


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


# ------------------------------------------------------------------ reference video
@router.put("/episodes/{eid}/guide/reference-video")
async def upload_reference(eid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The reference video is the raw request body (MP4, MOV or WebM, at most 250 MB). It replaces the earlier one."""
    from . import media
    from .audio_first import uploads_dir
    ep = _episode(db, eid)
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in VIDEO_TYPES:
        raise HTTPException(415, "upload an MP4, MOV or WebM video")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_VIDEO_BYTES:
        raise HTTPException(413, "the video is larger than 250 MB")
    try:
        media.check_free_space(uploads_dir(), declared or MAX_VIDEO_BYTES)
    except OSError as e:
        raise HTTPException(507, str(e))
    ext = VIDEO_TYPES[ctype]
    tmp = uploads_dir() / f"reference-{ep.id}-{uuid.uuid4().hex[:8]}{ext}"
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(413, "the video is larger than 250 MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, "the uploaded file is empty")
        try:
            info = media.probe(tmp)
        except media.MediaError as e:
            raise HTTPException(422, str(e))
        if info.get("video") is False:
            raise HTTPException(422, "this file has no picture")
        k = f"private/episodes/{ep.id}/reference-video-{uuid.uuid4().hex[:8]}{ext}"
        storage().put_file(k, tmp, ctype)
    finally:
        tmp.unlink(missing_ok=True)
    v = _stored(db, ep.id)
    old = (v.get("reference_video") or {}).get("key")
    v["reference_video"] = {"key": k, "content_type": ctype, "size": size, "uploaded": time.time(),
                            "seconds": round(info["duration"], 2) if info.get("duration") else None}
    _save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Reference video uploaded by {user} ({size / 1048576:.1f} MB, private)"))
    db.commit()
    if old and old != k:
        storage().delete(old)
    return guide(db, ep)


@router.delete("/episodes/{eid}/guide/reference-video")
def remove_reference(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = _stored(db, ep.id)
    ref = v.pop("reference_video", None)
    if ref:
        storage().delete(ref["key"])
        _save(db, ep.id, v)
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Reference video removed by {user}"))
        db.commit()
    return guide(db, ep)


# ------------------------------------------------------------------ the steps
def _jobs_busy(db: Session, eid: int, kinds: tuple[str, ...]) -> bool:
    return db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(("queued", "running"))).first() is not None


def _ref_out(ref: dict | None) -> dict | None:
    if not ref:
        return None
    return {"content_type": ref["content_type"], "size": ref["size"], "seconds": ref.get("seconds"),
            "uploaded": ref.get("uploaded"), "url": storage().url(ref["key"])}


def guide(db: Session, ep: Episode) -> dict:
    from . import acting_analysis as AA
    from . import prompt_writer as PW
    from . import shot_frames as SF
    from .stick_pipeline import IMAGE_PROVIDERS, image_cost
    steps: dict[str, dict] = {}

    # 1. uploads
    has_script = ep.script_version is not None or bool((ep.audio_transcript or {}).get("lines"))
    has_voice = ep.audio_asset_id is not None
    ref = reference_video(db, ep.id)
    have = [has_script, has_voice, ref is not None]
    steps["upload"] = {"status": "done" if all(have) else "not_started", "cost": None,
                       "detail": f"{sum(have)} of 3 uploaded",
                       "items": {"script": has_script, "voice": has_voice, "reference_video": _ref_out(ref)}}

    # 2. acting analysis
    av = AA.stored(db, ep.id)
    ap = AA.plan(db, ep)
    a_busy = _jobs_busy(db, ep.id, (AA.JOB,))
    steps["acting"] = {"status": "running" if a_busy else "done" if av.get("accepted") else
                       "needs_approval" if av.get("result") else "not_started",
                       "cost": ap["estimate"], "detail": (f"{len(av['result']['shots'])} shots described" if av.get("result") else "")}

    # 3. prompts
    pv = PW.stored(db, ep.id)
    drafts = [p for p in pv.get("prompts") or [] if p.get("status") == "draft"]
    approved = [p for p in pv.get("prompts") or [] if p.get("status") == "approved"]
    steps["prompts"] = {"status": "needs_approval" if drafts else "done" if approved else "not_started",
                        "cost": PW.typical_estimate(db),
                        "detail": f"{len(approved)} ready, {len(drafts)} to check" if (drafts or approved) else ""}

    # 4. character masters (the episode's cast)
    cast_keys: list[str] = []
    for sc in ep.scenes:
        cast_keys += [k for k in sc.characters or [] if k not in cast_keys]
    chars = [c for c in db.query(Character).filter(Character.key.in_(cast_keys))] if cast_keys else []
    chars += [c for c in db.query(Character).filter_by(scope="episode", episode_id=ep.id) if c.key not in cast_keys]
    ids = [c.id for c in chars]
    masters = {a.character_id for a in db.query(CharacterAsset).filter(CharacterAsset.character_id.in_(ids),
               CharacterAsset.kind == "master", CharacterAsset.status == "approved")} if ids else set()
    review = {a.character_id for a in db.query(CharacterAsset).filter(CharacterAsset.character_id.in_(ids),
              CharacterAsset.kind == "master", CharacterAsset.status == "review")} if ids else set()
    m_busy = db.query(Job).filter(Job.kind == "stick_master", Job.character_id.in_(ids),
                                  Job.status.in_(("queued", "running"))).first() is not None if ids else False
    st = get_section(db, "stick")
    ip = IMAGE_PROVIDERS.get(st.get("image_provider"))
    steps["masters"] = {"status": "running" if m_busy else "done" if chars and len(masters) == len(chars) else
                        "needs_approval" if review else "not_started",
                        "cost": image_cost(int(st.get("master_candidates") or 2), ip["usd_per_image"]) if ip else None,
                        "detail": f"{len(masters)} of {len(chars)} characters have an approved master" if chars else "no cast yet",
                        "characters": [{"id": c.id, "name": c.name, "master": c.id in masters, "to_review": c.id in review}
                                       for c in chars]}

    # 5. sets and seating (the shot stills on the storyboard)
    shots = SF.migrated(SF.stored(db, ep.id)).get("shots") or []
    stills = [s for s in shots if any(x.get("source") == "still" for x in s.get("versions") or [])]
    ok = [s for s in stills if s.get("approved")]
    s_busy = _jobs_busy(db, ep.id, ("stick_shot_still",))
    steps["sets"] = {"status": "running" if s_busy else "done" if shots and len(ok) == len(shots) else
                     "needs_approval" if len(stills) > len(ok) else "not_started",
                     "cost": image_cost(1, ip["usd_per_image"]) if ip else None,
                     "detail": f"{len(ok)} of {len(shots)} shots have an approved still" if shots else "no storyboard yet"}

    for k in PLACEHOLDERS:
        steps[k] = {"status": "not_started", "cost": None, "detail": "", "available": False}

    # 6-8. close-up crops, face poses and movement of the reaction shots (reactions.py)
    from . import reactions
    steps.update(reactions.summary(db, ep))

    # 9. talking shots (talking_s2v.py)
    from . import talking_s2v
    steps["talking"] = talking_s2v.summary(db, ep)
    steps = {k: steps[k] for k in ORDER if k in steps}
    for k in steps:
        steps[k].setdefault("available", True)
    return {"episode": {"id": ep.id, "title": ep.title, "source": ep.source}, "steps": steps,
            "keys": {"gemini": bool(_secret("gemini_api_key", db)), "openai": bool(_secret("openai_api_key", db))}}


def _secret(name: str, db: Session) -> str:
    from .secrets_store import secret
    return secret(name, db)


@router.get("/episodes/{eid}/guide")
def get_guide(eid: int, db: Session = Depends(get_db)):
    return guide(db, _episode(db, eid))
