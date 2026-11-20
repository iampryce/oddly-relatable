"""Background job handlers, run by the worker (worker.py). Each handler does real work or raises; the worker records
the failure on the job (and the episode stage) so the owner can fix the cause and retry just that job.

Production pipeline for one episode:
  start_production -> one `scene_prepare` per scene (engine build + stills, validates the scene) and one `scene_voice`
  per scene (voice clips when a voice provider is configured) -> when every scene job has succeeded, `render_episode`
  (engine `produce`: audio bed, MP4, QA, manifest) -> episode moves to video_review.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

from sqlalchemy.orm import Session

from . import engine, house_style, writer
from .config import REPO_ROOT, get_settings
from .models import Asset, Character, CharacterAsset, Episode, Event, Idea, Job, PublishRecord, ScriptVersion, StoryboardScene, now
from .casting import register_new_characters, writer_characters
from .providers import ProviderNotConfigured, audio_seconds, image_generate, speak, text_provider
from .queue import enqueue
from .script_schema import validate_script
from .settings_store import get_section
from .storage import sha256_file, storage
from .workflow import set_stage

TASKS = {}
SCENE_JOBS = ("scene_prepare", "scene_voice")


def task(fn):
    TASKS[fn.__name__] = fn
    return fn


class Ctx:
    """What a handler gets: the session, the job, and a log function that appends to the job's log."""

    def __init__(self, db: Session, job: Job):
        self.db, self.job = db, job

    def log(self, text: str) -> None:
        self.job.log = (self.job.log + ("\n" if self.job.log else "") + text.strip())[-60000:]
        self.db.commit()

    def folder(self, *parts) -> Path:
        p = get_settings().work_dir.joinpath(*map(str, parts))
        p.mkdir(parents=True, exist_ok=True)
        return p


def event(db: Session, episode_id, kind: str, message: str) -> None:
    db.add(Event(episode_id=episode_id, kind=kind, message=message))


def characters(db: Session) -> list[Character]:
    return db.query(Character).order_by(Character.id).all()


def by_key(db: Session) -> dict[str, Character]:
    return {c.key: c for c in characters(db)}


def scene_hash(sc) -> str:
    """Production-relevant content of a storyboard scene (long-form selective regeneration compares it)."""
    import hashlib
    return hashlib.sha256(json.dumps({"location": sc.location, "characters": sc.characters, "lines": sc.lines}, sort_keys=True).encode()).hexdigest()


def current_script(db: Session, ep: Episode) -> dict:
    sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one()
    return sv.content


def save_script(db: Session, ep: Episode, content: dict, source: str, note: str = "") -> ScriptVersion:
    version = (db.query(ScriptVersion).filter_by(episode_id=ep.id).count()) + 1
    sv = ScriptVersion(episode_id=ep.id, version=version, content=content, source=source, note=note)
    db.add(sv)
    ep.script_version = version
    ep.title = content["title"]
    return sv


def store_asset(db: Session, *, ep_id, src: Path, key: str, kind: str, label: str, content_type: str, scene_id=None, job_id=None, revision=1) -> Asset:
    storage().put_file(key, src, content_type)
    a = Asset(episode_id=ep_id, scene_id=scene_id, job_id=job_id, revision=revision, kind=kind, label=label, storage_key=key,
              content_type=content_type, size=src.stat().st_size, sha256=sha256_file(src))
    db.add(a)
    db.flush()
    return a


# ------------------------------------------------------------------ scripts
@task
def generate_script(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    idea = db.get(Idea, ep.idea_id)
    chars = writer_characters(db, ep.id)
    provider = text_provider(get_section(db, "text"))
    ctx.log(f"Writing the script with provider {provider.name}")
    answer = provider.complete_json(writer.system_prompt(get_section(db, "creative")), writer.script_prompt(idea, chars, sets.writer_environments(db), job.payload.get("instruction", "")))
    script = validate_script(answer, {c.key for c in characters(db)})
    made = register_new_characters(db, ep.id, script)
    if made:
        ctx.log(f"The script introduces new characters: {', '.join(made)} (pose sheets needed before production)")
    sv = save_script(db, ep, script, "generated", job.payload.get("instruction", ""))
    set_stage(ep, "script_review")
    event(db, ep.id, "script", f"Script v{sv.version} generated")
    db.commit()
    return {"script_version": sv.version}


@task
def regenerate_section(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    chars = writer_characters(db, ep.id)
    script = current_script(db, ep)
    section, instruction = job.payload["section"], job.payload.get("instruction", "")
    provider = text_provider(get_section(db, "text"))
    if section.startswith("act:") and ep.format == "long":
        from .tasks_long import regenerate_act
        new = regenerate_act(ctx, ep, script, int(section.split(":", 1)[1]), instruction)
    else:
        answer = provider.complete_json(writer.system_prompt(get_section(db, "creative")),
                                        writer.section_prompt(script, section, instruction, chars))
        new = writer.apply_section(script, section, answer, {c.key for c in characters(db)}, fmt=ep.format)
    register_new_characters(db, ep.id, new)
    sv = save_script(db, ep, new, "section-regenerated", f"{section}: {instruction}")
    event(db, ep.id, "script", f"Script v{sv.version}: regenerated {section}")
    db.commit()
    return {"script_version": sv.version, "section": section}


# ------------------------------------------------------------------ storyboard
@task
def generate_storyboard(ctx: Ctx) -> dict:
    """Scene breakdown from the APPROVED script version (deterministic: each script scene becomes a storyboard scene),
    then one visual-reference job per scene."""
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.approved_script_version).one()
    for old in list(ep.scenes):
        db.delete(old)
    db.flush()
    for i, s in enumerate(sv.content["scenes"], 1):
        cast = []
        for ln in s["lines"]:
            if ln["speaker"] not in cast:
                cast.append(ln["speaker"])
        db.add(StoryboardScene(episode_id=ep.id, position=i, scene_key=s["id"], heading=s["heading"], location=s.get("location", ""),
                               description=s.get("description", ""), action=s.get("action", ""), camera=s.get("camera", ""),
                               characters=cast, lines=s["lines"], status="draft"))
    ep.storyboard_version += 1
    set_stage(ep, "storyboard_review")
    event(db, ep.id, "storyboard", f"Storyboard v{ep.storyboard_version} created from script v{sv.version}")
    db.commit()
    db.refresh(ep)   # the scenes relationship was loaded before the new rows were added
    for sc in ep.scenes:
        enqueue(db, "scene_reference", episode_id=ep.id, scene_id=sc.id, revision=ep.revision)
    return {"scenes": len(ep.scenes), "storyboard_version": ep.storyboard_version}


@task
def regenerate_scene(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    sc = db.get(StoryboardScene, job.scene_id)
    chars = characters(db)
    known = {c.key for c in chars}
    script = current_script(db, ep)
    scene = {k: getattr(sc, k) for k in ("heading", "location", "description", "action", "camera", "lines")}
    provider = text_provider(get_section(db, "text"))
    answer = provider.complete_json(writer.system_prompt(get_section(db, "creative")),
                                    writer.scene_prompt(script, scene, job.payload.get("instruction", ""), chars))
    # Validate the new scene inside a copy of the script (same rules as script edits).
    trial = json.loads(json.dumps(script))
    trial["characters"] = [{"key": k, "role": ""} for k in known]
    trial["scenes"] = [{"id": sc.scene_key, **{k: answer.get(k, scene[k]) for k in scene}}]
    checked = validate_script(trial, known)["scenes"][0]
    for k in ("heading", "location", "description", "action", "camera", "lines"):
        setattr(sc, k, checked[k])
    sc.characters = list(dict.fromkeys(ln["speaker"] for ln in checked["lines"]))
    sc.status, sc.revision_note = "draft", ""
    event(db, ep.id, "storyboard", f"Scene {sc.position} regenerated")
    db.commit()
    enqueue(db, "scene_reference", episode_id=ep.id, scene_id=sc.id, revision=ep.revision)
    return {"scene": sc.position}


def _scene_preview(ctx: Ctx, ep: Episode, sc: StoryboardScene, kind: str) -> Asset:
    db = ctx.db
    script = current_script(db, ep)
    story = engine.build_story(episode_id=ep.id, revision=ep.revision, title=ep.title, script={**script, "hook": "", "interactive": {"type": "none"}},
                               scenes=list(ep.scenes), chars_by_key=prepare_characters(ctx), production=get_section(db, "production"),
                               only_scene_ids={sc.id}, end_card=False)
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", f"scene-{sc.position}", kind)
    sheet = engine.preview(story, folder, ctx.log)
    key = f"episodes/{ep.id}/r{ep.revision}/scenes/{sc.position}/{kind}-job{ctx.job.id}.png"
    return store_asset(db, ep_id=ep.id, src=sheet, key=key, kind=kind, label=f"Scene {sc.position} stills",
                       content_type="image/png", scene_id=sc.id, job_id=ctx.job.id, revision=ep.revision)


@task
def scene_reference(ctx: Ctx) -> dict:
    """Visual reference for one storyboard scene: renderer-exact stills of the scene with the real character art."""
    db, job = ctx.db, ctx.job
    ep, sc = db.get(Episode, job.episode_id), db.get(StoryboardScene, job.scene_id)
    asset = _scene_preview(ctx, ep, sc, "scene-reference")
    sc.reference_asset_id = asset.id
    db.commit()
    return {"asset_id": asset.id}


# ------------------------------------------------------------------ characters
def prepare_characters(ctx: Ctx) -> dict[str, Character]:
    """Make every generated character's approved poses available locally with an engine registry."""
    db = ctx.db
    out = {}
    for c in characters(db):
        if c.locked or c.art_status != "approved":
            out[c.key] = c
            continue
        poses = db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="approved").all()
        folder = ctx.folder("characters", c.key)
        entries = []
        for p in poses:
            src = folder / f"pose-{p.id}.png"
            if not src.exists() or sha256_file(src) != p.sha256:
                storage().get_to_file(p.storage_key, src)
            # The engine sizes and frames a pose by its whole image, so the generator's wide transparent margins would
            # count as body width (members cut at frame edges, medium shots that "do not fit"). The engine works from a
            # copy trimmed to the figure (plus a small border), with the feet anchor moved to match; the approved
            # original is never changed.
            trimmed, feet = engine.trim_pose(src, folder / f"pose-{p.id}-trim.png", p.feet)
            entries.append({"pose_id": f"p{p.id}", "file": trimmed.resolve(), "sha256": sha256_file(trimmed), "feet": feet,
                            "figure_height": p.figure_height, "expression": p.expression})
        reg = engine.write_registry(c, entries, folder)
        c.registry_path = str(reg.resolve())
        c.expressions = {e["expression"]: e["pose_id"] for e in entries}
        out[c.key] = c
    db.commit()
    return out


def style_version(db: Session) -> str:
    """The house style new character and set images are drawn in (Settings > creative.style_version)."""
    v = get_section(db, "creative").get("style_version", "v1")
    return v if v in house_style.STYLE_VERSIONS else "v1"


def pose_prompt_v2(c: Character, expression: str, with_identity: bool, with_style: bool, simplify: bool = False) -> str:
    """House style v2 (owner decision 2026-11-20): adult minimal stick-figure style. A flat mid-grey background, because
    white heads and torsos would merge with a white one and break the cut-out. Expressions keep the neutral body: the
    acting rig uses only the heads, and the face carries the acting with restraint."""
    refs = []
    if with_identity and simplify:
        refs.append("IMAGE 1 is THIS character's previous design in an OLDER style: keep only who they are (hair or cap shape and "
                    "colour, garment colour) and redraw them completely in house style v2 above: no ears, no nose, solid black "
                    "oval eyes without whites, tall lanky adult proportions, black blob hands and feet, no shoes.")
    elif with_identity:
        refs.append("IMAGE 1 is THIS character: keep them identical (head shape and size, hair or cap shape and colour, torso or "
                    "garment, line weight, proportions and stance); only the face changes.")
    if with_style:
        refs.append(f"The {'LAST' if with_identity else 'attached'} image is the show's HOUSE STYLE v2 reference (a different "
                    "character): match its drawing style exactly (line weight, eye, brow and mouth style, head-to-body "
                    "proportions, flat colours) but do NOT copy that character's cap, hair, garment or colours.")
    return (f"Full-body 2D character for an animated comedy for grown-ups: an ADULT, standing upright and facing the viewer "
            f"in a relaxed neutral stance with the arms hanging at the sides, whole body visible with space around it, on a "
            f"plain flat mid-grey (#808080) background; no scenery, no floor, no shadow, no text. "
            f"{house_style.character_rules('v2', c.skin_tone or '')} Character: {c.name}. Appearance: {c.visual_description}. "
            f"Expression: {expression}, shown with restraint through the brows, the eyes and a small mouth change; the body "
            f"and stance stay exactly as in the neutral pose. " + " ".join(refs))


def pose_prompt(c: Character, expression: str, with_identity: bool, with_style: bool, simplify: bool = False, version: str = "v1") -> str:
    if version == "v2":
        return pose_prompt_v2(c, expression, with_identity, with_style, simplify)
    """Image prompt for one pose. References are attached in this order: the character's own approved/neutral pose
    (identity), then the house-style reference (the show's locked lead character)."""
    refs = []
    if with_identity and simplify:
        refs.append("IMAGE 1 is THIS character's previous, more detailed design: keep who they are (hair or hat shape, skin "
                    "tone, clothing type and colours) but redraw them simpler in the house style described above: remove "
                    "textures, stubble, jewellery and fine detail.")
    elif with_identity:
        refs.append("IMAGE 1 is THIS character: keep them identical (same face, hairstyle, accessories, outfit, colours, "
                    "head and body proportions); only the expression and pose change.")
    if with_style:
        refs.append(f"The {'LAST' if with_identity else 'attached'} image is the show's HOUSE STYLE reference (a different "
                    "character): match its drawing style exactly (line weight, bold clean black outlines, head-to-body "
                    "proportions of an adult, flat colours with the same simple shading, eye and brow style), but do NOT copy "
                    "that character's face, head, hair, clothes or colours.")
    return (f"Full-body 2D cartoon character for an animated comedy show about adults: an ADULT (not a child), standing, "
            f"facing the viewer, whole body visible with space around it, plain transparent (or flat white) background, no "
            f"scenery, no text. {house_style.CHARACTER_RULES} Clothing covers the torso only (no trousers, sleeves or "
            f"skin-coloured limbs). Character: {c.name}. "
            f"Appearance: {c.visual_description}. Expression and body language: {expression}, exaggerated and readable. "
            + " ".join(refs))


def style_reference(ctx: Ctx, version: str = "v1") -> Path | None:
    """The house style: the locked lead character's approved neutral pose (read only; never modified). In v2, the first
    approved v2 neutral pose (the lead's when it has one); none yet means text-only generation, so the v1 look cannot
    leak into v2 through the reference image."""
    db = ctx.db
    if version == "v2":
        q = (db.query(CharacterAsset).join(Character, Character.id == CharacterAsset.character_id)
             .filter(CharacterAsset.kind == "pose", CharacterAsset.status == "approved", CharacterAsset.style_version == "v2",
                     CharacterAsset.expression == "neutral")
             .order_by(Character.locked.desc(), CharacterAsset.id))
        a = q.first()
        return storage().get_to_file(a.storage_key, ctx.folder("characters", "_style-v2") / Path(a.storage_key).name) if a else None
    lead = db.query(Character).filter_by(locked=True).order_by(Character.id).first()
    if lead is None:
        return None
    a = (db.query(CharacterAsset).filter_by(character_id=lead.id, kind="pose", status="approved", expression="neutral").first()
         or db.query(CharacterAsset).filter_by(character_id=lead.id, kind="pose", status="approved").first())
    if a is None:
        return None
    return storage().get_to_file(a.storage_key, ctx.folder("characters", "_style") / Path(a.storage_key).name)


def _generate_pose(ctx: Ctx, c: Character, expression: str, ref: Path | None, cfg: dict, simplify: bool = False,
                   version: str = "v1") -> tuple[CharacterAsset, Path]:
    folder = ctx.folder("characters", c.key, "generated")
    # The attempt number keeps every generation as its own file: a retried sheet never overwrites earlier evidence.
    out = folder / f"{re.sub(r'[^a-z0-9]+', '-', expression)}-job{ctx.job.id}-a{ctx.job.attempts}.png"
    style = style_reference(ctx, version)
    refs = [r for r in (ref, style) if r is not None]
    ctx.log(f"Generating '{expression}' in house style {version} with image provider {cfg.get('provider')} ({len(refs)} reference image(s))")
    if version == "v2":
        cfg = {**cfg, "background": "mid-grey (#808080)"}
    image_generate(cfg, pose_prompt(c, expression, ref is not None, style is not None, simplify, version), out, refs or None)
    if engine.make_cutout(out):
        ctx.log(f"'{expression}': background or halo removed")
    info = engine.analyse_pose(out)
    key = f"characters/{c.key}/poses/{'v2/' if version == 'v2' else ''}{out.name}"
    storage().put_file(key, out, "image/png")
    a = CharacterAsset(character_id=c.id, kind="pose", expression=expression, storage_key=key, sha256=sha256_file(out),
                       width=info["width"], height=info["height"], feet=info["feet"], figure_height=info["figure_height"], status="review",
                       style_version=version)
    ctx.db.add(a)
    ctx.db.commit()
    return a, out


def _reference_for(ctx: Ctx, c: Character, version: str | None = None) -> Path | None:
    """Consistency anchor: an approved neutral pose, else any approved pose, else the owner's reference image. With a
    style version, only poses drawn in that style anchor (a v1 pose must not pull a v2 drawing back to the old look)."""
    db = ctx.db
    poses = db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose")
    if version:
        poses = poses.filter(CharacterAsset.style_version == version)
    a = (poses.filter_by(status="approved", expression="neutral").first()
         or poses.filter_by(status="approved").first()
         # A sheet still in review: its neutral pose anchors a re-drawn expression, so the sheet stays one identity.
         or poses.filter_by(status="review", expression="neutral").order_by(CharacterAsset.id.desc()).first()
         or db.query(CharacterAsset).filter_by(character_id=c.id, kind="reference").order_by(CharacterAsset.id.desc()).first())
    if not a:
        return None
    return storage().get_to_file(a.storage_key, ctx.folder("characters", c.key, "ref") / Path(a.storage_key).name)


@task
def character_pose(ctx: Ctx) -> dict:
    """One extra expression pose for a character (owner-started)."""
    c = ctx.db.get(Character, ctx.job.character_id)
    a, _ = _generate_pose(ctx, c, ctx.job.payload["expression"], _reference_for(ctx, c, style_version(ctx.db)), get_section(ctx.db, "image"),
                          version=style_version(ctx.db))
    if c.art_status != "approved":
        c.art_status = "review"
    ctx.db.commit()
    return {"asset_id": a.id}


@task
def character_sheet(ctx: Ctx) -> dict:
    """A character's pose and expression sheet (owner-started): the neutral pose first, then every other expression
    drawn from it as the reference, then one labelled sheet image for review. Expressions that already have a pose in
    review or approved are skipped, so a retry continues where a failure stopped."""
    db, job = ctx.db, ctx.job
    c = db.get(Character, job.character_id)
    cfg = get_section(db, "image")
    version = job.payload.get("style_version") or style_version(db)
    restyle = bool(job.payload.get("restyle"))
    if job.payload.get("provider"):
        cfg = {**cfg, "provider": job.payload["provider"], "model": "", "fallback": "none"}
    if cfg.get("provider") == "openai":
        cfg = {**cfg, "use_reference": True}      # attach the house-style reference (and the new neutral) to each image
    wanted = list(dict.fromkeys(["neutral"] + [e.lower() for e in job.payload.get("expressions", [])]))
    # A restyle draws the new neutral from the current design simplified into the house style ("simplify"), or from
    # the house style alone; the rest of the sheet is anchored on the new neutral.
    simplify_from = _reference_for(ctx, c) if restyle and job.payload.get("from_current") else None
    ref = None if restyle else _reference_for(ctx, c, version)
    entries = []
    for i, exp in enumerate(wanted):
        statuses = ["review"] if restyle else ["review", "approved"]   # a restyle redraws approved expressions too
        existing = db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id, CharacterAsset.kind == "pose",
                                                   CharacterAsset.expression == exp, CharacterAsset.status.in_(statuses),
                                                   CharacterAsset.style_version == version).first()
        if existing:
            f = storage().get_to_file(existing.storage_key, ctx.folder("characters", c.key, "sheet") / Path(existing.storage_key).name)
        else:
            if ref is None and simplify_from is not None:
                _, f = _generate_pose(ctx, c, exp, simplify_from, cfg, simplify=True, version=version)
            else:
                _, f = _generate_pose(ctx, c, exp, ref, cfg, version=version)
        if ref is None:
            ref = f   # the first pose anchors the rest of the sheet
        entries.append((exp, f))
        job.progress = {"done": i + 1, "total": len(wanted), "current": exp}
        db.commit()
    sheet = engine.compose_sheet(entries, ctx.folder("characters", c.key) / f"sheet-job{job.id}.png", f"{c.name}: expression sheet")
    key = f"characters/{c.key}/sheet-job{job.id}.png"
    storage().put_file(key, sheet, "image/png")
    db.add(CharacterAsset(character_id=c.id, kind="sheet", storage_key=key, sha256=sha256_file(sheet), status="review"))
    if c.art_status != "approved":
        c.art_status = "review"
    event(db, c.episode_id, "character", f"{c.name}: expression sheet ready for review ({len(entries)} poses)")
    db.commit()
    return {"poses": len(entries)}


def voice_direction(c: Character, line: dict) -> str:
    """Acting direction for the voice model: the character's voice style, the line's expression and delivery."""
    parts = [c.voice_style or f"{c.name}: expressive comedic delivery", f"Emotion: {line.get('expression', 'neutral')}"]
    if line.get("delivery"):
        parts.append(f"Delivery: {line['delivery']}")
    parts.append("Short animated comedy sketch; exaggerated, clear and well-timed.")
    return ". ".join(parts)


@task
def voice_preview(ctx: Ctx) -> dict:
    """A short sample of a character's assigned voice, so the owner can approve it before production."""
    db, job = ctx.db, ctx.job
    c = db.get(Character, job.character_id)
    cfg = get_section(db, "voice")
    text = job.payload.get("text") or f"Hi, I am {c.name}. Something is definitely wrong here."
    f = speak(cfg, text, c.voice, ctx.folder("characters", c.key, "voice") / f"sample-job{job.id}", voice_direction(c, {"expression": "neutral"}),
              speed=c.voice_speed)
    key = f"characters/{c.key}/voice-sample-job{job.id}{f.suffix}"
    storage().put_file(key, f, "audio/mpeg" if f.suffix == ".mp3" else "audio/wav")
    a = CharacterAsset(character_id=c.id, kind="voice-sample",
                       # the voice's short name (a Piper voice is a model path; the column holds 40 characters)
                       expression=(Path(c.voice.replace("\\", "/")).stem if c.voice else "default")[:40], storage_key=key, sha256=sha256_file(f), status="review")
    db.add(a)
    db.commit()
    return {"asset_id": a.id, "seconds": round(audio_seconds(f), 2)}


# ------------------------------------------------------------------ production
@task
def scene_prepare(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep, sc = db.get(Episode, job.episode_id), db.get(StoryboardScene, job.scene_id)
    sc.production_status = "running"
    db.commit()
    asset = _scene_preview(ctx, ep, sc, "scene-frames")
    return {"asset_id": asset.id, "scene_hash": scene_hash(sc)}


@task
def scene_voice(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep, sc = db.get(Episode, job.episode_id), db.get(StoryboardScene, job.scene_id)
    cfg = get_section(db, "voice")
    if cfg.get("provider", "none") == "none":
        ctx.log("No voice provider configured: this scene has no voice clips (the video carries the engine's SFX only).")
        return {"skipped": "no voice provider configured", "clips": [], "scene_hash": scene_hash(sc)}
    chars = by_key(db)
    clips = []
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", f"scene-{sc.position}", "voice")
    for i, ln in enumerate(sc.lines):
        c = chars[ln["speaker"]]
        if not re.search(r"\w", ln["text"]):
            # A silent reaction beat ("...", "?!"): nothing to speak, so no clip; the line keeps its storyboard timing.
            ctx.log(f"line {i + 1}: silent reaction beat ({ln['text']!r}), no voice")
            continue
        # Voice per character (set under Characters); the old settings map and the default voice are fallbacks.
        voice = c.voice or (cfg.get("voices") or {}).get(ln["speaker"]) or cfg.get("default_voice", "")
        f = speak(cfg, ln["text"], voice, folder / f"line-{i + 1}", voice_direction(c, ln), speed=c.voice_speed)
        seconds = audio_seconds(f)
        key = f"episodes/{ep.id}/r{ep.revision}/scenes/{sc.position}/voice/line-{i + 1}-job{job.id}{f.suffix}"
        a = store_asset(db, ep_id=ep.id, src=f, key=key, kind="voice", label=f"Scene {sc.position} line {i + 1} ({c.name})",
                        content_type="audio/mpeg" if f.suffix == ".mp3" else "audio/wav", scene_id=sc.id, job_id=job.id, revision=ep.revision)
        clips.append({"line": i, "asset_id": a.id, "seconds": round(seconds, 3), "text": ln["text"], "speaker": ln["speaker"]})
        ctx.log(f"line {i + 1}: {seconds:.2f} s ({c.name}, voice {voice or 'default'})")
    db.commit()
    return {"clips": clips, "scene_hash": scene_hash(sc)}


def _voice_audio(ctx: Ctx, ep: Episode, story: dict, folder: Path) -> None:
    """Give lines with voice clips enough time, then place each clip at its line's start (engine timing)."""
    db = ctx.db
    # Latest successful voice job per scene (scenes not re-produced in this revision keep their earlier clips).
    jobs = {j.scene_id: j for j in db.query(Job).filter_by(episode_id=ep.id, kind="scene_voice", status="succeeded").order_by(Job.id)}
    by_scene = {}
    for sc in ep.scenes:
        j = jobs.get(sc.id)
        if j and j.result.get("clips"):
            by_scene[sc.position] = j.result["clips"]
    if not by_scene:
        return
    for sc, es in zip(ep.scenes, story["scenes"]):
        for clip in by_scene.get(sc.position, []):
            # A clip is used only for the exact line it was recorded for: edited dialogue needs its voice re-run.
            if clip["line"] >= len(sc.lines) or sc.lines[clip["line"]]["text"] != clip.get("text", sc.lines[clip["line"]]["text"]):
                raise engine.EngineInputError(f"scene {sc.position}: dialogue changed after its voice was recorded; re-run the scene")
            line = es["lines"][clip["line"]]
            # The line stays on screen until its clip has finished, plus a short comedic beat.
            line["duration"] = max(line.get("duration", 0), math.ceil((clip["seconds"] + 0.4) * 100) / 100)   # rounded UP: the clip always fits
    story_file = engine.write_story(story, folder)
    tmp = folder / "timings"
    shutil.rmtree(tmp, ignore_errors=True)
    s = get_settings()
    r = subprocess.run([s.node_bin, str(Path(__file__).parent / "node" / "line-timings.mjs"), str(story_file), str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=engine.env_for_node(), timeout=600,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise engine.EngineRunError("could not time the voice clips: " + engine.last_error(r.stdout + r.stderr))
    timings = json.loads(r.stdout)
    voice = []
    for sc, t in zip(ep.scenes, timings):
        for clip in by_scene.get(sc.position, []):
            a = db.get(Asset, clip["asset_id"])
            local = storage().get_to_file(a.storage_key, folder / "voice" / Path(a.storage_key).name)
            rel = Path(local).resolve()
            voice.append({"source": str(rel), "sha256": a.sha256, "licence": f"Generated for this episode by the configured voice provider",
                          "start": t["lines"][clip["line"]]["start"], "gain": float(get_section(db, "voice").get("gain", 1.0))})
    story["audio"] = {"voice": voice}


@task
def render_episode(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    prod = get_section(db, "production")
    script = current_script(db, ep)
    story = engine.build_story(episode_id=ep.id, revision=ep.revision, title=ep.title, script=script, scenes=list(ep.scenes),
                               chars_by_key=prepare_characters(ctx), production=prod)
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", "render")
    _voice_audio(ctx, ep, story, folder)

    def progress(run: dict) -> None:
        job.progress = {"status": run.get("status"), "stages": run.get("stages", [])}
        db.commit()

    from . import acting
    base = f"episodes/{ep.id}/r{ep.revision}"
    if acting.enabled(db):
        # Settings > Motion = studio rig animator: every line performed by the procedural acting renderer
        from .tasks_long import clip_map
        refs = [[(sc.id, li) for li in range(len(sc.lines))] for sc in ep.scenes]
        mp4, wav, rep = acting.render(ctx, ep, refs, clip_map(db, ep), prepare_characters(ctx), folder / "acting",
                                      end_card=prod.get("end_card") or "Oddly Relatable")
        out = folder / "acting"
        result = {"run": {"status": "pass", "renderer": "acting", **rep}, "folder": out}
        store_asset(db, ep_id=ep.id, src=wav, key=f"{base}/audio-job{job.id}.wav", kind="audio", label="Final mixed audio",
                    content_type="audio/wav", job_id=job.id, revision=ep.revision)
    else:
        result = engine.produce(story, folder, ctx.log, progress)
        out: Path = result["folder"]
        mp4 = next((out / "render").glob("*.mp4"), None)
    if not mp4:
        raise engine.EngineRunError("the engine finished without an MP4")
    video = store_asset(db, ep_id=ep.id, src=mp4, key=f"{base}/video-job{job.id}.mp4", kind="video", label=f"{ep.title} (revision {ep.revision})",
                        content_type="video/mp4", job_id=job.id, revision=ep.revision)
    extras = [("storyboard/storyboard-sheet.png", "storyboard-sheet", "image/png", "Storyboard sheet"),
              ("reports/qa-report.json", "report", "application/json", "QA report"),
              ("reports/layout-report.json", "report", "application/json", "Layout report"),
              ("production-manifest.json", "manifest", "application/json", "Production manifest")]
    for rel, kind, ct, label in extras:
        f = out / rel
        if f.exists():
            store_asset(db, ep_id=ep.id, src=f, key=f"{base}/{Path(rel).name.replace('.', f'-job{job.id}.', 1)}", kind=kind, label=label,
                        content_type=ct, job_id=job.id, revision=ep.revision)
    for f in (out / "audio").glob("*.wav"):
        store_asset(db, ep_id=ep.id, src=f, key=f"{base}/audio-job{job.id}.wav", kind="audio", label="Final mixed audio",
                    content_type="audio/wav", job_id=job.id, revision=ep.revision)
    ep.video_asset_id = video.id
    for sc in ep.scenes:
        sc.production_status = "done"
    set_stage(ep, "video_review")
    event(db, ep.id, "production", f"Revision {ep.revision} rendered; ready for video review")
    db.commit()
    return {"video_asset_id": video.id, "qa": result["run"].get("status")}


def after_job(db: Session, job: Job) -> None:
    """Advance the episode after a job finishes (success or failure)."""
    if job.kind in ("character_sheet", "character_pose") and job.status == "failed" and job.character_id:
        # Do not leave the character stuck in "generating": its status follows the poses it really has.
        c = db.get(Character, job.character_id)
        if c is not None and not c.locked:
            poses = {a.status for a in db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose")}
            c.art_status = "approved" if "approved" in poses else "review" if "review" in poses else "none"
            db.commit()
    if not job.episode_id:
        return
    ep = db.get(Episode, job.episode_id)
    if ep is None or job.revision != ep.revision:
        return
    if ep.format == "long":
        from .tasks_long import after_long_job
        if after_long_job(db, job, ep):
            return
    if job.kind in SCENE_JOBS:
        sc = db.get(StoryboardScene, job.scene_id)
        if job.status == "failed":
            sc.production_status = "failed"
            if ep.stage == "producing":
                set_stage(ep, "production_failed")
        elif job.kind == "scene_prepare":
            sc.production_status = "ready"
        db.commit()
        latest = {}
        for j in db.query(Job).filter(Job.episode_id == ep.id, Job.revision == ep.revision, Job.kind.in_(SCENE_JOBS)).order_by(Job.id):
            latest[(j.kind, j.scene_id)] = j
        # Scenes already produced for this episode ("done") are reused as they are; only the others must finish.
        expected = {(k, s.id) for k in SCENE_JOBS for s in ep.scenes if s.production_status != "done"}
        done = all(latest.get(x) is not None and latest[x].status == "succeeded" for x in expected)
        rendering = db.query(Job).filter(Job.episode_id == ep.id, Job.revision == ep.revision, Job.kind == "render_episode",
                                         Job.status.in_(["queued", "running", "succeeded"])).count()
        if ep.format == "long":   # long-form: plan segments (the Shorts single render is never used)
            rendering = db.query(Job).filter(Job.episode_id == ep.id, Job.revision == ep.revision, Job.kind == "plan_segments",
                                             Job.status.in_(["queued", "running"])).count()
        if done and not rendering and ep.stage in ("producing", "production_failed"):
            set_stage(ep, "producing")
            db.commit()
            enqueue(db, "plan_segments" if ep.format == "long" else "render_episode", episode_id=ep.id, revision=ep.revision)
    elif job.kind == "render_episode" and job.status == "failed":
        set_stage(ep, "production_failed")
        db.commit()
    elif job.kind in ("generate_script",) and job.status == "failed":
        set_stage(ep, "script_review" if ep.script_version else "script_pending")
        db.commit()
    elif job.kind == "generate_storyboard" and job.status == "failed":
        set_stage(ep, "script_approved")
        db.commit()
    elif job.kind == "publish_youtube" and job.status == "failed":
        rec = db.query(PublishRecord).filter_by(episode_id=ep.id).one_or_none()
        if rec:
            rec.status, rec.error = "failed", job.error
        set_stage(ep, "publish_failed")
        db.commit()


@task
def publish_youtube(ctx: Ctx) -> dict:
    from .youtube import upload_video
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    rec = db.query(PublishRecord).filter_by(episode_id=ep.id).one()
    # Re-check the gate at execution time: the approval must cover exactly this revision and this video.
    if rec.status not in ("approved", "uploading") or rec.approved_revision != ep.revision or rec.approved_video_asset_id != ep.video_asset_id:
        raise PermissionError("publication is not approved for the current video; approve it again in Publishing")
    rec.status = "uploading"
    db.commit()
    video = db.get(Asset, ep.video_asset_id)
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", "publish")
    local = storage().get_to_file(video.storage_key, folder / "video.mp4")
    thumb = None
    if rec.thumbnail_asset_id:
        t = db.get(Asset, rec.thumbnail_asset_id)
        thumb = storage().get_to_file(t.storage_key, folder / Path(t.storage_key).name)
    vid = upload_video(local, title=rec.title, description=rec.description, tags=rec.tags, category_id=rec.category_id,
                       privacy=rec.privacy, made_for_kids=rec.made_for_kids, thumbnail=thumb, log=ctx.log)
    rec.youtube_video_id, rec.youtube_url, rec.status, rec.error = vid, f"https://www.youtube.com/watch?v={vid}", "published", ""
    set_stage(ep, "published")
    event(db, ep.id, "publish", f"Published to YouTube ({rec.privacy}): {rec.youtube_url}")
    db.commit()
    return {"video_id": vid, "url": rec.youtube_url}


def is_transient(e: Exception) -> bool:
    """Failures worth an automatic retry: rate limits, provider server errors, timeouts and network errors."""
    import httpx
    if getattr(e, "transient", False):
        return True
    if isinstance(e, (httpx.TimeoutException, httpx.TransportError, subprocess.TimeoutExpired, ConnectionError, TimeoutError)):
        return True
    try:
        from botocore.exceptions import ConnectionError as BotoConnectionError, EndpointConnectionError
        return isinstance(e, (BotoConnectionError, EndpointConnectionError))
    except ImportError:
        return False


def run_job(db: Session, job_id: int) -> Job | None:
    """Claim and run one job (the worker calls this for each ID it receives)."""
    from .queue import claim
    job = claim(db, job_id)
    if job is None:
        return None
    ctx = Ctx(db, job)
    from .providers import set_fallback_logger
    set_fallback_logger(ctx.log)
    retry_in = 0
    try:
        fn = TASKS.get(job.kind)
        if fn is None:
            raise ValueError(f"unknown job kind {job.kind}")
        job.result = fn(ctx) or {}
        job.status = "succeeded"
    except ProviderNotConfigured as e:
        db.rollback()
        job = db.get(Job, job_id)
        job.status, job.error = "failed", f"Not configured: {e}"
    except Exception as e:  # recorded on the job; the owner sees it in Production and can retry
        db.rollback()
        job = db.get(Job, job_id)
        job.status, job.error = "failed", f"{type(e).__name__}: {e}"
        if is_transient(e) and job.attempts < get_settings().max_job_attempts:
            retry_in = min(60, 5 * 2 ** job.attempts)   # 10 s, 20 s, ... capped at a minute
    finally:
        set_fallback_logger(None)
    if retry_in:
        # Automatic retry of a transient failure: back to the queue; the dashboard shows the attempt and the reason.
        job.status, job.error = "queued", f"Retrying automatically (attempt {job.attempts + 1} of {get_settings().max_job_attempts}) after: {job.error}"
        job.log = (job.log or "") + "\n" + job.error
        db.add(Event(episode_id=job.episode_id, kind="job", message=f"{job.kind} (job {job.id}) will retry in {retry_in} s: {job.error[:200]}"))
        db.commit()
        if get_settings().env != "test":
            time.sleep(retry_in)
        from .queue import announce
        announce(job.id)
        return job
    job.finished_at = now()
    if job.status == "failed":
        db.add(Event(episode_id=job.episode_id, kind="error", message=f"{job.kind} (job {job.id}) failed: {job.error[:300]}"))
    db.commit()
    after_job(db, job)
    return job


# Long-form handlers register themselves with @task (imported last: they build on the helpers above).
from . import tasks_long  # noqa: E402,F401
from . import tasks_providers  # noqa: E402,F401
from . import comparison  # noqa: E402,F401
from . import voice_compare  # noqa: E402,F401
from . import sets  # noqa: E402,F401
