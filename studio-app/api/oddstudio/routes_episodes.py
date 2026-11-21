"""Ideas, episodes, scripts, storyboards, production, review and publishing routes.

Every state change goes through workflow.require() first; gates are enforced here, not in the dashboard."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import secrets

from . import engine, longform, serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Character, Episode, Event, Idea, Job, OutlineVersion, PublishRecord, Review, ScriptVersion, Segment, StoryboardScene, now
from .queue import announce, enqueue
from .script_schema import ScriptError, estimated_seconds, validate_script
from .settings_store import get_section
from .casting import cast_status, register_new_characters
from .tasks import by_key, save_script
from .workflow import GateError, REVISION_TARGETS, require, set_stage
from .youtube import configured as youtube_configured

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def gate(ep: Episode, action: str) -> None:
    try:
        require(ep, action)
    except GateError as e:
        raise HTTPException(409, str(e))


def get_episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def log_event(db: Session, ep_id, kind: str, msg: str) -> None:
    db.add(Event(episode_id=ep_id, kind=kind, message=msg))


def record(db: Session, ep: Episode, gate_name: str, decision: str, user: str, comment: str = "", target: dict | None = None) -> None:
    db.add(Review(episode_id=ep.id, gate=gate_name, decision=decision, revision=ep.revision, target=target or {}, comment=comment, actor=user))


# ------------------------------------------------------------------ ideas
class IdeaIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    premise: str = Field(min_length=1, max_length=4000)
    notes: str = Field(default="", max_length=4000)
    characters: list[str] = Field(default_factory=list, max_length=4)
    target_seconds: int = Field(default=45, ge=10, le=450)
    interactive: Literal["none", "viewer-choice", "poll"] = "none"
    status: Literal["draft", "submitted"] = "draft"
    format: Literal["short", "long"] = "short"            # long: 3 acts, 5–7 minutes (D-L3)
    continues_episode_id: int | None = None               # D-L5: a long episode may continue a successful Short


def check_idea(db: Session, body: "IdeaIn") -> None:
    if body.format == "short" and body.target_seconds > 60:
        raise HTTPException(422, "a Short runs at most 60 s; choose a long episode for more")
    if body.continues_episode_id is not None:
        if body.format != "long":
            raise HTTPException(422, "only a long episode can continue a Short")
        src = db.get(Episode, body.continues_episode_id)
        if src is None or src.format != "short" or not src.script_version:
            raise HTTPException(422, "the episode to continue must be a Short with a script")


@router.get("/ideas")
def list_ideas(db: Session = Depends(get_db)):
    return [S.idea(i) for i in db.query(Idea).order_by(Idea.updated_at.desc())]


@router.post("/ideas", status_code=201)
def create_idea(body: IdeaIn, db: Session = Depends(get_db)):
    known = set(by_key(db))
    unknown = [k for k in body.characters if k not in known]
    if unknown:
        raise HTTPException(422, f"unknown characters: {', '.join(unknown)}")
    check_idea(db, body)
    i = Idea(**body.model_dump())
    db.add(i)
    db.flush()
    log_event(db, None, "idea", f"Idea saved: {i.title} ({i.status})")
    db.commit()
    return S.idea(i)


@router.put("/ideas/{iid}")
def update_idea(iid: int, body: IdeaIn, db: Session = Depends(get_db)):
    i = db.get(Idea, iid)
    if i is None:
        raise HTTPException(404, "idea not found")
    if i.status in ("in_production", "archived"):
        raise HTTPException(409, f"an idea that is {i.status.replace('_', ' ')} cannot be edited")
    check_idea(db, body)
    for k, v in body.model_dump().items():
        setattr(i, k, v)
    db.commit()
    return S.idea(i)


@router.post("/ideas/{iid}/archive")
def archive_idea(iid: int, db: Session = Depends(get_db)):
    i = db.get(Idea, iid)
    if i is None:
        raise HTTPException(404, "idea not found")
    if i.status == "in_production":
        raise HTTPException(409, "this idea already has an episode")
    i.status = "archived"
    db.commit()
    return S.idea(i)


class StartIn(BaseModel):
    generate_script: bool = True


@router.post("/ideas/{iid}/start", status_code=201)
def start_from_idea(iid: int, body: StartIn, db: Session = Depends(get_db)):
    i = db.get(Idea, iid)
    if i is None:
        raise HTTPException(404, "idea not found")
    if i.status in ("in_production", "archived"):
        raise HTTPException(409, f"this idea is already {i.status.replace('_', ' ')}")
    ep = Episode(idea_id=i.id, title=i.title, stage="script_pending", format=i.format, continues_episode_id=i.continues_episode_id,
                 dialogue_display=get_section(db, "production").get("dialogue_display", "none"))
    db.add(ep)
    db.flush()
    i.status, i.episode_id = "in_production", ep.id
    log_event(db, ep.id, "episode", f"Episode created from idea “{i.title}”")
    db.commit()
    if body.generate_script:
        # Long episodes start with the three-act outline (two-pass writing); Shorts with the script, as before.
        long = ep.format == "long"
        set_stage(ep, "outline_generating" if long else "script_generating")
        db.commit()
        enqueue(db, "generate_outline" if long else "generate_script", episode_id=ep.id, revision=ep.revision)
    return S.episode_summary(ep)


# ------------------------------------------------------------------ episodes
@router.get("/episodes")
def list_episodes(stage: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Episode)
    if stage:
        q = q.filter(Episode.stage.in_(stage.split(",")))
    return [S.episode_summary(e) for e in q.order_by(Episode.updated_at.desc())]


@router.get("/episodes/{eid}")
def episode_detail(eid: int, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    script = None
    if ep.script_version:
        sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one()
        script = {"version": sv.version, "content": sv.content, "source": sv.source, "note": sv.note,
                  "estimated_seconds": estimated_seconds(sv.content), "created_at": S.ts(sv.created_at)}
    versions = [{"version": v.version, "source": v.source, "note": v.note, "created_at": S.ts(v.created_at)}
                for v in db.query(ScriptVersion).filter_by(episode_id=ep.id).order_by(ScriptVersion.version.desc())]
    assets = db.query(Asset).filter_by(episode_id=ep.id).order_by(Asset.id.desc()).all()
    amap = {a.id: a for a in assets}
    jobs = db.query(Job).filter_by(episode_id=ep.id).order_by(Job.id.desc()).limit(200).all()
    idea = db.get(Idea, ep.idea_id) if ep.idea_id else None
    outline = None
    if ep.outline_version:
        ov = db.query(OutlineVersion).filter_by(episode_id=ep.id, version=ep.outline_version).one()
        outline = {"version": ov.version, "content": ov.content, "source": ov.source, "note": ov.note, "created_at": S.ts(ov.created_at),
                   "approved": ep.approved_outline_version == ov.version, "warnings": longform.outline_warnings(ov.content)}
    if script and ep.format == "long":
        script["warnings"] = longform.repeated_lines(script["content"]) + (
            [f"Runs about {script['estimated_seconds']:.0f} s, over the 7½-minute cap ({longform.HARD_CAP} s)."] if script["estimated_seconds"] > longform.HARD_CAP else [])
    segs = db.query(Segment).filter_by(episode_id=ep.id, revision=ep.revision).order_by(Segment.position).all()
    segments = [{"id": g.id, "position": g.position, "parts": g.parts, "seconds": g.seconds, "status": g.status, "reused_from": g.reused_from,
                 "render_seconds": g.render_seconds, "error": g.error, "job_id": g.job_id, "fingerprint": g.fingerprint[:12],
                 "video": S.asset(amap.get(g.video_asset_id) or (db.get(Asset, g.video_asset_id) if g.video_asset_id else None))} for g in segs]
    return {**S.episode_summary(ep), "idea": S.idea(idea) if idea else None, "outline": outline, "segments": segments,
            "script": script, "script_versions": versions,
            "scenes": [S.scene(s, amap.get(s.reference_asset_id) if s.reference_asset_id else None) for s in ep.scenes],
            "jobs": [S.job(j) for j in jobs], "assets": [S.asset(a) for a in assets],
            "video": S.asset(amap.get(ep.video_asset_id)) if ep.video_asset_id else None,
            "reviews": [S.review(r) for r in db.query(Review).filter_by(episode_id=ep.id).order_by(Review.id.desc())],
            "publish": S.publish(db.query(PublishRecord).filter_by(episode_id=ep.id).one_or_none()),
            "events": [{"kind": e.kind, "message": e.message, "created_at": S.ts(e.created_at)}
                       for e in db.query(Event).filter_by(episode_id=ep.id).order_by(Event.id.desc()).limit(50)]}


class DialogueDisplayIn(BaseModel):
    value: Literal["bubbles", "none", "captions"]


@router.get("/episodes/{eid}/set-options")
def set_options(eid: int, db: Session = Depends(get_db)):
    """The sets this episode may use (approved only), each with a thumbnail and the other episodes that already use it,
    the current choice, the video notes' setting word as a suggestion (never applied by itself), and set candidates
    still waiting for approval in Settings > Sets."""
    from . import sets as studio_sets
    ep = get_episode(db, eid)
    used = studio_sets.usage(db, exclude_episode=ep.id)
    options = [{**s, "thumbnail": studio_sets.thumbnail_url(db, k), "used_in": used.get(k, [])}
               for k, s in studio_sets.usable(db).items()]
    tr = ep.audio_transcript or {}
    word = ((tr.get("media_hints") or {}).get("setting") or "").strip() if ep.source == "audio" else ""
    pending = [{"id": k, "label": r.get("label", k)} for k, r in studio_sets.records(db).items() if r.get("status") == "candidate"]
    return {"current": ep.set_id, "options": options, "candidates": pending,
            "suggestion": {"word": word, "set_id": studio_sets.suggest(db, word)} if word else None}


class SetChoiceIn(BaseModel):
    set_id: str = Field(min_length=1, max_length=80)


@router.put("/episodes/{eid}/set")
def choose_set(eid: int, body: SetChoiceIn, db: Session = Depends(get_db)):
    """The owner's deliberate choice of this episode's set: approved sets only. Not while a render is running."""
    from . import sets as studio_sets
    ep = get_episode(db, eid)
    if ep.stage in ("producing", "publishing"):
        raise HTTPException(409, f"not while the episode is {ep.stage}: change the set before or after the render")
    usable = studio_sets.usable(db)
    if body.set_id not in usable:
        raise HTTPException(422, "choose an approved set (candidates must be approved in Settings > Sets first)")
    if ep.set_id != body.set_id:
        n = len(studio_sets.usage(db, exclude_episode=ep.id).get(body.set_id, []))
        log_event(db, ep.id, "episode", f"Set chosen: {usable[body.set_id]['label']} ({body.set_id})"
                                        + (f"; reused, already in {n} other episode(s)" if n else "; new to this episode"))
        ep.set_id = body.set_id
        db.commit()
    return S.episode_summary(ep)


@router.put("/episodes/{eid}/dialogue-display")
def set_dialogue_display(eid: int, body: DialogueDisplayIn, db: Session = Depends(get_db)):
    """What the viewer sees of the dialogue in this episode's next render: speech bubbles, nothing (the audio carries
    it) or captions. Not while a render is running (it would apply to part of the video only)."""
    ep = get_episode(db, eid)
    if ep.stage in ("producing", "publishing"):
        raise HTTPException(409, f"not while the episode is {ep.stage}: change it before or after the render")
    if ep.dialogue_display != body.value:
        log_event(db, ep.id, "episode", f"Dialogue on screen: {ep.dialogue_display or 'bubbles'} -> {body.value} (applies to the next render)")
        ep.dialogue_display = body.value
        db.commit()
    return S.episode_summary(ep)


# ------------------------------------------------------------------ script
class InstructionIn(BaseModel):
    instruction: str = Field(default="", max_length=2000)


@router.post("/episodes/{eid}/script/generate")
def generate_script(eid: int, body: InstructionIn, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "generate_script")
    if ep.source == "audio":
        raise HTTPException(409, "the dialogue of an audio episode comes from the recording: build or rebuild its scenes "
                                 "in the Audio tab instead")
    if ep.format == "long":
        if not ep.approved_outline_version:
            raise HTTPException(409, "a long episode is written from its approved outline: approve the outline first")
        set_stage(ep, "script_generating")
        db.commit()
        return S.job(enqueue(db, "generate_act", episode_id=ep.id, revision=ep.revision,
                             payload={"act": 1, "chain": secrets.randbelow(2**31), "instruction": body.instruction}))
    if ep.stage == "outline_approved":
        raise HTTPException(409, "outlines apply to long episodes only")
    set_stage(ep, "script_generating")
    db.commit()
    job = enqueue(db, "generate_script", episode_id=ep.id, revision=ep.revision, payload={"instruction": body.instruction})
    return S.job(job)


@router.get("/episodes/{eid}/script/versions/{version}")
def script_version(eid: int, version: int, db: Session = Depends(get_db)):
    sv = db.query(ScriptVersion).filter_by(episode_id=eid, version=version).one_or_none()
    if sv is None:
        raise HTTPException(404, "no such script version")
    return {"version": sv.version, "content": sv.content, "source": sv.source, "note": sv.note, "created_at": S.ts(sv.created_at)}


class ScriptIn(BaseModel):
    content: dict
    note: str = Field(default="", max_length=500)


@router.put("/episodes/{eid}/script")
def edit_script(eid: int, body: ScriptIn, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "edit_script")
    try:
        content = validate_script(body.content, set(by_key(db)), fmt=ep.format)
        if ep.source == "audio":   # Stage 2: the recorded dialogue cannot be edited, only its staging
            from .audio_scenes import guard_dialogue, transcript_dialogue
            guard_dialogue(transcript_dialogue(ep), content)
    except ScriptError as e:
        raise HTTPException(422, str(e))
    if ep.format == "long" and not ep.approved_outline_version:
        raise HTTPException(409, "approve the outline before writing the long episode's scenes")
    register_new_characters(db, ep.id, content)
    sv = save_script(db, ep, content, "edited", body.note)
    set_stage(ep, "script_review")
    log_event(db, ep.id, "script", f"Script v{sv.version} saved (edited)")
    db.commit()
    return {"version": sv.version}


class SectionIn(BaseModel):
    section: str = Field(min_length=1, max_length=60)
    instruction: str = Field(default="", max_length=2000)


@router.post("/episodes/{eid}/script/regenerate-section")
def regenerate_section(eid: int, body: SectionIn, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "regenerate_section")
    if ep.source == "audio":
        raise HTTPException(409, "the dialogue of an audio episode comes from the recording: build or rebuild its scenes "
                                 "in the Audio tab instead")
    return S.job(enqueue(db, "regenerate_section", episode_id=ep.id, revision=ep.revision, payload=body.model_dump()))


class CommentIn(BaseModel):
    comment: str = Field(default="", max_length=4000)


@router.post("/episodes/{eid}/script/approve")
def approve_script(eid: int, body: CommentIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "approve_script")
    if not ep.script_version:
        raise HTTPException(409, "there is no script to approve")
    if ep.format == "long":
        est = estimated_seconds(db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one().content)
        if est > longform.HARD_CAP:
            raise HTTPException(409, f"the script runs about {est:.0f} s, over the 7½-minute cap ({longform.HARD_CAP} s): tighten it first")
    ep.approved_script_version = ep.script_version
    set_stage(ep, "script_approved")
    record(db, ep, "script", "approved", user, body.comment, {"script_version": ep.script_version})
    log_event(db, ep.id, "approval", f"Script v{ep.script_version} approved")
    db.commit()
    return S.episode_summary(ep)


@router.post("/episodes/{eid}/script/reject")
def reject_script(eid: int, body: CommentIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "reject_script")
    record(db, ep, "script", "rejected", user, body.comment, {"script_version": ep.script_version})
    log_event(db, ep.id, "review", f"Script v{ep.script_version} rejected: {body.comment[:200]}")
    db.commit()
    return S.episode_summary(ep)


# ------------------------------------------------------------------ storyboard
@router.post("/episodes/{eid}/storyboard/generate")
def generate_storyboard(eid: int, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "generate_storyboard")
    if not ep.approved_script_version:
        raise HTTPException(409, "approve the script first")
    set_stage(ep, "storyboard_generating")
    db.commit()
    return S.job(enqueue(db, "generate_storyboard", episode_id=ep.id, revision=ep.revision))


def get_scene(db: Session, ep: Episode, sid: int) -> StoryboardScene:
    sc = db.get(StoryboardScene, sid)
    if sc is None or sc.episode_id != ep.id:
        raise HTTPException(404, "scene not found")
    return sc


class SceneIn(BaseModel):
    heading: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)
    action: str = Field(default="", max_length=2000)
    camera: str = Field(default="", max_length=400)
    lines: list[dict]


@router.put("/episodes/{eid}/scenes/{sid}")
def edit_scene(eid: int, sid: int, body: SceneIn, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "edit_scene")
    sc = get_scene(db, ep, sid)
    known = set(by_key(db))
    trial = {"title": "t", "characters": [{"key": k} for k in known], "scenes": [{"id": sc.scene_key, **body.model_dump()}]}
    try:
        checked = validate_script(trial, known)["scenes"][0]
        if ep.source == "audio":
            from .audio_scenes import guard_dialogue
            guard_dialogue(list(sc.lines), checked["lines"], f"scene {sc.position}")
    except ScriptError as e:
        raise HTTPException(422, str(e).replace("script.scenes[0]", f"scene {sc.position}"))
    for k in ("heading", "location", "description", "action", "camera", "lines"):
        setattr(sc, k, checked[k])
    from .acting import referenced
    sc.characters = list(dict.fromkeys(k for ln in checked["lines"] for k in referenced(ln)))
    sc.status, sc.revision_note = "draft", ""
    log_event(db, ep.id, "storyboard", f"Scene {sc.position} edited")
    db.commit()
    return S.scene(sc, None)


@router.post("/episodes/{eid}/scenes/{sid}/regenerate")
def regenerate_scene(eid: int, sid: int, body: InstructionIn, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "regenerate_scene")
    if ep.source == "audio":
        raise HTTPException(409, "the dialogue of an audio episode comes from the recording: build or rebuild its scenes "
                                 "in the Audio tab instead")
    sc = get_scene(db, ep, sid)
    return S.job(enqueue(db, "regenerate_scene", episode_id=ep.id, scene_id=sc.id, revision=ep.revision, payload=body.model_dump()))


@router.post("/episodes/{eid}/scenes/{sid}/reference")
def scene_reference(eid: int, sid: int, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "scene_reference")
    sc = get_scene(db, ep, sid)
    return S.job(enqueue(db, "scene_reference", episode_id=ep.id, scene_id=sc.id, revision=ep.revision))


@router.post("/episodes/{eid}/storyboard/approve")
def approve_storyboard(eid: int, body: CommentIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "approve_storyboard")
    if not ep.scenes:
        raise HTTPException(409, "the storyboard has no scenes")
    pending = [s.position for s in ep.scenes if s.status == "needs_revision"]
    if pending:
        raise HTTPException(409, f"scenes {pending} are marked for revision; edit or regenerate them first")
    for s in ep.scenes:
        s.status = "ready"
    ep.approved_storyboard_version = ep.storyboard_version
    set_stage(ep, "storyboard_approved")
    record(db, ep, "storyboard", "approved", user, body.comment, {"storyboard_version": ep.storyboard_version})
    log_event(db, ep.id, "approval", f"Storyboard v{ep.storyboard_version} approved")
    db.commit()
    return S.episode_summary(ep)


class SceneRejectIn(BaseModel):
    comment: str = Field(min_length=1, max_length=4000)
    scene_ids: list[int] = Field(default_factory=list)


@router.post("/episodes/{eid}/storyboard/reject")
def reject_storyboard(eid: int, body: SceneRejectIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "reject_storyboard")
    for sid in body.scene_ids:
        sc = get_scene(db, ep, sid)
        sc.status, sc.revision_note = "needs_revision", body.comment
    record(db, ep, "storyboard", "rejected", user, body.comment, {"scene_ids": body.scene_ids})
    db.commit()
    return S.episode_summary(ep)


# ------------------------------------------------------------------ production
def enqueue_scene_jobs(db: Session, ep: Episode, scenes: list[StoryboardScene]) -> list[Job]:
    jobs = []
    for sc in scenes:
        sc.production_status = "pending"
    db.commit()
    from .tasks import scene_jobs
    for sc in scenes:
        for kind in scene_jobs(ep):
            jobs.append(enqueue(db, kind, episode_id=ep.id, scene_id=sc.id, revision=ep.revision))
    return jobs


def preflight(db: Session, ep: Episode) -> None:
    """Refuse to start production that cannot succeed (no fake runs): no chosen set, characters without art, too long."""
    from . import sets as studio_sets
    if not ep.set_id:
        raise HTTPException(409, "choose this episode's set first (Storyboard tab, Set): there is no default set")
    if ep.set_id not in studio_sets.usable(db):
        raise HTTPException(409, f"the episode's set {ep.set_id!r} is not an approved set any more: choose another one")
    chars = by_key(db)
    keys = {k for s in ep.scenes for k in s.characters}
    try:
        engine.check_cast_ready([chars[k] for k in keys if k in chars])
    except engine.EngineInputError as e:
        raise HTTPException(409, str(e))
    from . import acting, rig_check
    if acting.enabled(db):
        bad = rig_check.blocking_problems(db, [chars[k] for k in sorted(keys) if k in chars])
        if bad:
            raise HTTPException(409, " ".join(bad) + " Approve a new pose for them under Characters.")
    if ep.source == "audio":
        # the recording sets the length (its format cap was checked at upload); it is performed by the rig animator
        from . import acting
        if not acting.enabled(db):
            raise HTTPException(409, "an audio episode is performed by the studio rig animator: set Settings > Motion to it first")
        if not ep.audio_asset_id:
            raise HTTPException(409, "the episode has no audio")
        return
    sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.approved_script_version).one()
    est = estimated_seconds(sv.content)
    limit = longform.HARD_CAP if ep.format == "long" else get_section(db, "production")["max_seconds"]
    if est > limit:
        raise HTTPException(409, f"the script runs about {est} s; production renders up to {limit} s (shorten the script)")


@router.post("/episodes/{eid}/production/start")
def start_production(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "start_production")
    if ep.approved_storyboard_version != ep.storyboard_version:
        raise HTTPException(409, "the storyboard changed after approval; approve it again")
    preflight(db, ep)
    set_stage(ep, "producing")
    log_event(db, ep.id, "production", f"Production started (revision {ep.revision}) by {user}")
    db.commit()
    if ep.format == "long" and ep.source != "audio":
        # Selective regeneration: unchanged scenes keep their preparation and voices (their segments are then reused).
        from .tasks_long import start_long_scene_jobs
        need = start_long_scene_jobs(db, ep, list(ep.scenes))
        if not need:
            return [S.job(enqueue(db, "plan_segments", episode_id=ep.id, revision=ep.revision))]
        return [S.job(j) for j in enqueue_scene_jobs(db, ep, need)]
    return [S.job(j) for j in enqueue_scene_jobs(db, ep, list(ep.scenes))]


@router.post("/jobs/{jid}/retry")
def retry_job(jid: int, db: Session = Depends(get_db)):
    job = db.get(Job, jid)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status != "failed":
        raise HTTPException(409, f"only failed jobs can be retried (this one is {job.status})")
    if job.episode_id and job.kind not in ("character_sheet", "character_pose", "voice_preview"):   # character jobs are not tied to a revision
        ep = get_episode(db, job.episode_id)
        if job.revision != ep.revision:
            raise HTTPException(409, "this job belongs to an earlier revision")
        if job.kind in ("scene_prepare", "scene_voice", "audio_slice", "render_episode", "plan_segments", "render_segment", "join_segments"):
            gate(ep, "retry_job")
            set_stage(ep, "producing")
            if job.kind == "render_segment":
                seg = db.get(Segment, job.payload.get("segment_id"))
                if seg:
                    seg.status, seg.error = "pending", ""
        elif job.kind == "generate_outline":
            gate(ep, "generate_outline")
            set_stage(ep, "outline_generating")
        elif job.kind == "generate_act":
            if ep.stage != "outline_approved":
                raise HTTPException(409, "acts are retried from the approved outline")
            set_stage(ep, "script_generating")
        elif job.kind == "generate_script":
            gate(ep, "generate_script")
            set_stage(ep, "script_generating")
        elif job.kind == "generate_storyboard":
            gate(ep, "generate_storyboard")
            set_stage(ep, "storyboard_generating")
        elif job.kind == "publish_youtube":
            gate(ep, "publish")
            rec = db.query(PublishRecord).filter_by(episode_id=ep.id).one()
            if rec.status != "failed" or rec.approved_revision != ep.revision:
                raise HTTPException(409, "publication is not approved for this revision")
            rec.status = "approved"
            set_stage(ep, "publishing")
    job.status, job.error, job.finished_at = "queued", "", None
    db.add(Event(episode_id=job.episode_id, kind="job", message=f"Retrying {job.kind} (job {job.id})"))
    db.commit()
    announce(job.id)
    return S.job(job)


@router.post("/episodes/{eid}/scenes/{sid}/rerun")
def rerun_scene(eid: int, sid: int, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "rerun_scene")
    sc = get_scene(db, ep, sid)
    if ep.stage == "video_review":
        raise HTTPException(409, "to change a finished video, request a revision for the scenes instead")
    set_stage(ep, "producing")
    db.commit()
    return [S.job(j) for j in enqueue_scene_jobs(db, ep, [sc])]


# ------------------------------------------------------------------ video review
@router.post("/episodes/{eid}/video/approve")
def approve_video(eid: int, body: CommentIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "approve_video")
    if not ep.video_asset_id:
        raise HTTPException(409, "there is no video to approve")
    set_stage(ep, "final_approved")
    record(db, ep, "video", "approved", user, body.comment, {"video_asset_id": ep.video_asset_id})
    rec = db.query(PublishRecord).filter_by(episode_id=ep.id).one_or_none()
    yt = get_section(db, "youtube")
    script = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one().content
    if rec is None:
        rec = PublishRecord(episode_id=ep.id, title=ep.title[:100], description=script.get("logline", ""),
                            tags=list(yt.get("default_tags", [])), category_id=yt.get("category_id", "23"), privacy=yt.get("default_privacy", "private"))
        db.add(rec)
    else:   # a new revision was approved: any earlier publication approval no longer applies
        rec.status, rec.approved_revision, rec.approved_video_asset_id, rec.approved_at = "draft", None, None, None
    log_event(db, ep.id, "approval", f"Final video (revision {ep.revision}) approved")
    db.commit()
    return S.episode_summary(ep)


class RevisionIn(BaseModel):
    target: str
    comment: str = Field(min_length=1, max_length=4000)
    scene_ids: list[int] = Field(default_factory=list)
    segment_positions: list[int] = Field(default_factory=list)


@router.post("/episodes/{eid}/video/request-revision")
def request_revision(eid: int, body: RevisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "request_revision")
    if body.target not in REVISION_TARGETS:
        raise HTTPException(422, f"target must be one of {', '.join(sorted(REVISION_TARGETS))}")
    if body.target in ("storyboard", "scenes"):
        for sid in body.scene_ids:
            get_scene(db, ep, sid)
    if body.target == "scenes" and not body.scene_ids:
        raise HTTPException(422, "choose the scenes to re-produce")
    if body.target == "segments":
        if ep.format != "long":
            raise HTTPException(422, "segments apply to long episodes")
        positions = {s.position for s in db.query(Segment).filter_by(episode_id=ep.id, revision=ep.revision)}
        if not body.segment_positions or not set(body.segment_positions) <= positions:
            raise HTTPException(422, f"choose segments to re-render from {sorted(positions)}")
    record(db, ep, "video", "revision_requested", user, body.comment, {"target": body.target, "scene_ids": body.scene_ids, "segment_positions": body.segment_positions})
    ep.revision += 1
    ep.video_asset_id = None
    if body.target == "script":
        ep.approved_script_version = None
        ep.approved_storyboard_version = None
        set_stage(ep, "script_review")
    elif body.target == "storyboard":
        ep.approved_storyboard_version = None
        for s in ep.scenes:
            s.production_status = "pending"
            if s.id in body.scene_ids:
                s.status, s.revision_note = "needs_revision", body.comment
        set_stage(ep, "storyboard_review")
    elif body.target == "segments":
        set_stage(ep, "producing")
        db.commit()
        enqueue(db, "plan_segments", episode_id=ep.id, revision=ep.revision, payload={"force_positions": body.segment_positions})
    else:
        targets = [s for s in ep.scenes if s.id in body.scene_ids]
        for s in targets:
            s.revision_note = body.comment
        set_stage(ep, "producing")
        db.commit()
        enqueue_scene_jobs(db, ep, targets)
    log_event(db, ep.id, "revision", f"Revision {ep.revision} requested ({body.target}): {body.comment[:200]}")
    db.commit()
    return S.episode_summary(ep)


# ------------------------------------------------------------------ publishing
class PublishIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    category_id: str = Field(default="23", max_length=10)
    privacy: Literal["private", "unlisted", "public"] = "private"
    made_for_kids: bool = False
    thumbnail_asset_id: int | None = None


def publish_record(db: Session, ep: Episode) -> PublishRecord:
    rec = db.query(PublishRecord).filter_by(episode_id=ep.id).one_or_none()
    if rec is None:
        raise HTTPException(409, "approve the final video first")
    return rec


@router.put("/episodes/{eid}/publish")
def edit_publish(eid: int, body: PublishIn, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "edit_publish")
    rec = publish_record(db, ep)
    if body.thumbnail_asset_id is not None:
        a = db.get(Asset, body.thumbnail_asset_id)
        if a is None or a.episode_id != ep.id or not a.content_type.startswith("image/"):
            raise HTTPException(422, "thumbnail must be an image asset of this episode")
    for k, v in body.model_dump().items():
        setattr(rec, k, v)
    # Any change after approval withdraws the approval: the owner approves exactly what will be published.
    rec.status, rec.approved_at, rec.approved_revision, rec.approved_video_asset_id, rec.approved_by = "draft", None, None, None, ""
    db.commit()
    return S.publish(rec)


class PublishApproveIn(BaseModel):
    confirm: str


@router.post("/episodes/{eid}/publish/approve")
def approve_publish(eid: int, body: PublishApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = get_episode(db, eid)
    gate(ep, "approve_publish")
    if body.confirm != "PUBLISH":
        raise HTTPException(422, 'type PUBLISH to confirm')
    rec = publish_record(db, ep)
    if not rec.title.strip():
        raise HTTPException(422, "a title is required")
    rec.status, rec.approved_by, rec.approved_at = "approved", user, now()
    rec.approved_revision, rec.approved_video_asset_id = ep.revision, ep.video_asset_id
    record(db, ep, "publish", "approved", user, f"privacy={rec.privacy}", {"video_asset_id": ep.video_asset_id, "title": rec.title})
    log_event(db, ep.id, "approval", f"Publication approved ({rec.privacy})")
    db.commit()
    return S.publish(rec)


@router.post("/episodes/{eid}/publish/start")
def start_publish(eid: int, db: Session = Depends(get_db)):
    ep = get_episode(db, eid)
    gate(ep, "publish")
    rec = publish_record(db, ep)
    if rec.status not in ("approved", "failed") or rec.approved_revision != ep.revision or rec.approved_video_asset_id != ep.video_asset_id:
        raise HTTPException(409, "publication has not been approved for the current video")
    if not youtube_configured():
        raise HTTPException(409, "YouTube is not connected on the server (see Settings > YouTube)")
    rec.status = "approved"
    set_stage(ep, "publishing")
    db.commit()
    return S.job(enqueue(db, "publish_youtube", episode_id=ep.id, revision=ep.revision))


# ------------------------------------------------------------------ cast (story-driven characters)
def episode_script(db: Session, ep: Episode) -> dict:
    if not ep.script_version:
        raise HTTPException(409, "the episode has no script yet")
    return db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one().content


@router.get("/episodes/{eid}/cast")
def episode_cast(eid: int, db: Session = Depends(get_db)):
    """Who the script needs, whether their art is approved, and which expressions are still missing."""
    ep = get_episode(db, eid)
    return cast_status(db, episode_script(db, ep))


@router.post("/episodes/{eid}/cast/generate")
def generate_cast(eid: int, db: Session = Depends(get_db)):
    """Owner-started: generate expression sheets for every character the script needs that lacks approved poses."""
    from .routes_characters import enqueue_sheet, require_image_generation
    ep = get_episode(db, eid)
    jobs = []
    for row in cast_status(db, episode_script(db, ep)):
        if row.get("missing") or row["locked"] or not row["missing_expressions"]:
            continue
        busy = db.query(Job).filter(Job.character_id == row["id"], Job.kind == "character_sheet", Job.status.in_(["queued", "running"])).count()
        if busy:
            continue
        c = db.get(Character, row["id"])
        require_image_generation(db, c)
        jobs.append(S.job(enqueue_sheet(db, c, row["missing_expressions"])))
    if not jobs:
        raise HTTPException(409, "every character in the script already has its poses (or a sheet is already being generated)")
    return jobs


# ------------------------------------------------------------------ long-form outline (two-pass writing, D-L1 to D-L5)
def long_episode(db: Session, eid: int) -> Episode:
    ep = get_episode(db, eid)
    if ep.format != "long":
        raise HTTPException(409, "outlines apply to long episodes only")
    return ep


@router.post("/episodes/{eid}/outline/generate")
def generate_outline(eid: int, body: InstructionIn, db: Session = Depends(get_db)):
    ep = long_episode(db, eid)
    gate(ep, "generate_outline")
    set_stage(ep, "outline_generating")
    db.commit()
    return S.job(enqueue(db, "generate_outline", episode_id=ep.id, revision=ep.revision, payload={"instruction": body.instruction}))


class OutlineIn(BaseModel):
    content: dict
    note: str = Field(default="", max_length=500)


@router.put("/episodes/{eid}/outline")
def edit_outline(eid: int, body: OutlineIn, db: Session = Depends(get_db)):
    from .tasks_long import save_outline
    ep = long_episode(db, eid)
    gate(ep, "edit_outline")
    try:
        content = longform.validate_outline(body.content, set(by_key(db)))
    except ScriptError as e:
        raise HTTPException(422, str(e))
    register_new_characters(db, ep.id, content)
    ov = save_outline(db, ep, content, "edited", body.note)
    set_stage(ep, "outline_review")
    log_event(db, ep.id, "outline", f"Outline v{ov.version} saved (edited)")
    db.commit()
    return {"version": ov.version, "warnings": longform.outline_warnings(content)}


@router.post("/episodes/{eid}/outline/approve")
def approve_outline(eid: int, body: CommentIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = long_episode(db, eid)
    gate(ep, "approve_outline")
    ep.approved_outline_version = ep.outline_version
    set_stage(ep, "outline_approved")
    record(db, ep, "outline", "approved", user, body.comment, {"outline_version": ep.outline_version})
    log_event(db, ep.id, "approval", f"Outline v{ep.outline_version} approved")
    db.commit()
    return S.episode_summary(ep)


@router.post("/episodes/{eid}/outline/reject")
def reject_outline(eid: int, body: CommentIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = long_episode(db, eid)
    gate(ep, "reject_outline")
    record(db, ep, "outline", "rejected", user, body.comment, {"outline_version": ep.outline_version})
    log_event(db, ep.id, "review", f"Outline v{ep.outline_version} sent back: {body.comment[:200]}")
    db.commit()
    return S.episode_summary(ep)


@router.get("/episodes/{eid}/outline/versions/{version}")
def outline_version(eid: int, version: int, db: Session = Depends(get_db)):
    ov = db.query(OutlineVersion).filter_by(episode_id=eid, version=version).one_or_none()
    if ov is None:
        raise HTTPException(404, "no such outline version")
    return {"version": ov.version, "content": ov.content, "source": ov.source, "note": ov.note, "created_at": S.ts(ov.created_at)}
