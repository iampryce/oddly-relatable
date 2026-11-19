"""Long-form job handlers (D-L1 to D-L5). Shorts never reach this module.

  generate_outline     three-act outline from the idea (and the Short it continues, if any); owner approves it
  generate_act         acts written one at a time from the APPROVED outline, each consistent with the acts before it
  plan_segments        exact engine timings -> segments of at most 58 s, cut at scene or line boundaries; a segment whose
                       inputs are unchanged reuses its earlier render (fingerprint), the rest are queued
  render_segment       one segment through the unchanged engine `produce` (voices placed at the engine's line timings)
  join_segments        video copied, audio concatenated exactly; joined file checked (frames, duration, audio at joins)
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from . import engine, longform, writer
from .casting import register_new_characters, writer_characters
from .config import REPO_ROOT, get_settings
from .models import Asset, Episode, Event, Idea, Job, OutlineVersion, ScriptVersion, Segment, StoryboardScene
from .providers import text_provider
from .queue import enqueue
from .script_schema import estimated_seconds, validate_script
from .settings_store import get_section
from .storage import sha256_file, storage
from .tasks import Ctx, characters, current_script, event, prepare_characters, save_script, scene_hash, store_asset, task
from .workflow import set_stage


# ------------------------------------------------------------------ outline and acts
def approved_outline(db, ep: Episode) -> dict:
    return db.query(OutlineVersion).filter_by(episode_id=ep.id, version=ep.approved_outline_version).one().content


def save_outline(db, ep: Episode, content: dict, source: str, note: str = "") -> OutlineVersion:
    version = db.query(OutlineVersion).filter_by(episode_id=ep.id).count() + 1
    ov = OutlineVersion(episode_id=ep.id, version=version, content=content, source=source, note=note)
    db.add(ov)
    ep.outline_version = version
    ep.title = content["title"]
    return ov


def continued_short(db, ep: Episode) -> dict | None:
    if not ep.continues_episode_id:
        return None
    src = db.get(Episode, ep.continues_episode_id)
    if not src or not src.script_version:
        return None
    sv = db.query(ScriptVersion).filter_by(episode_id=src.id, version=src.script_version).one()
    return {"title": src.title, **{k: sv.content.get(k) for k in ("logline", "twist", "interactive", "characters")},
            "scenes": [{"heading": s["heading"], "lines": [f"{ln['speaker']}: {ln['text']}" for ln in s["lines"]]} for s in sv.content["scenes"]]}


@task
def generate_outline(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    idea = db.get(Idea, ep.idea_id)
    chars = writer_characters(db, ep.id)
    provider = text_provider(get_section(db, "text"))
    ctx.log(f"Writing the three-act outline with provider {provider.name}")
    from . import sets
    prompt = writer.outline_prompt(idea, chars, sets.writer_environments(db), continued_short(db, ep))
    if job.payload.get("instruction"):
        prompt += f"\n\nOWNER INSTRUCTION FOR THIS VERSION: {job.payload['instruction']}"
    answer = provider.complete_json(writer.system_prompt(get_section(db, "creative")), prompt)
    outline = longform.validate_outline(answer, {c.key for c in characters(db)})
    made = register_new_characters(db, ep.id, outline)
    ov = save_outline(db, ep, outline, "generated", job.payload.get("instruction", ""))
    set_stage(ep, "outline_review")
    warnings = longform.outline_warnings(outline)
    event(db, ep.id, "outline", f"Outline v{ov.version}: 3 acts, {sum(len(a['scenes']) for a in outline['acts'])} scenes, about "
                                f"{outline['runtime_estimate_seconds']:.0f} s" + (f"; new characters: {', '.join(made)}" if made else ""))
    db.commit()
    return {"outline_version": ov.version, "warnings": warnings}


def _act_scenes(db, ep: Episode, chain: int) -> dict[int, list]:
    """Scenes already written in this act chain: {act: scenes} from the latest successful job per act."""
    out = {}
    for j in db.query(Job).filter_by(episode_id=ep.id, kind="generate_act", status="succeeded").order_by(Job.id):
        if j.payload.get("chain") == chain:
            out[j.payload["act"]] = j.result["scenes"]
    return out


@task
def generate_act(ctx: Ctx) -> dict:
    """Write one act's scenes from the approved outline; the third act assembles and saves the full script."""
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    act, chain = job.payload["act"], job.payload["chain"]
    outline = approved_outline(db, ep)
    chars = writer_characters(db, ep.id)
    known = {c.key for c in characters(db)}
    written = _act_scenes(db, ep, chain)
    prior = [{"act": a, "scenes": written[a]} for a in sorted(written) if a < act]
    provider = text_provider(get_section(db, "text"))
    ctx.log(f"Writing act {act} with provider {provider.name}")
    answer = provider.complete_json(writer.system_prompt(get_section(db, "creative")), writer.act_prompt(outline, act, prior, chars))
    planned = [s["id"] for s in outline["acts"][act - 1]["scenes"]]
    scenes = answer.get("scenes") if isinstance(answer, dict) else None
    if not isinstance(scenes, list) or [str(s.get("id", "")).lower() for s in scenes] != planned:
        raise ValueError(f"act {act}: the writer must return exactly the outline's scenes {planned} in order")
    for s in scenes:
        s["id"], s["act"] = s["id"].lower(), act
    # Validate this act on its own (same rules as the full script) before moving on.
    validate_script({"title": outline["title"], "characters": outline["characters"], "scenes": scenes}, known, fmt="long")
    job.result = {"act": act, "scenes": scenes}
    db.commit()
    if act < 3:
        enqueue(db, "generate_act", episode_id=ep.id, revision=ep.revision, payload={"act": act + 1, "chain": chain})
        return {"act": act, "scenes": scenes}
    written[3] = scenes
    script = validate_script({"title": outline["title"], "logline": outline["logline"], "twist": outline.get("twist", ""),
                              "hook": "", "interactive": {"type": "none"}, "characters": outline["characters"],
                              "scenes": [s for a in (1, 2, 3) for s in written[a]]}, known, fmt="long")
    sv = save_script(db, ep, script, "acts-generated", f"from outline v{ep.approved_outline_version}")
    set_stage(ep, "script_review")
    est = estimated_seconds(script)
    event(db, ep.id, "script", f"Script v{sv.version}: three acts, {len(script['scenes'])} scenes, about {est:.0f} s")
    db.commit()
    return {"act": act, "scenes": scenes, "script_version": sv.version, "estimated_seconds": est}


def regenerate_act(ctx: Ctx, ep: Episode, script: dict, act: int, instruction: str) -> dict:
    """Rewrite one act of a long script (the others stay as they are)."""
    db = ctx.db
    outline = approved_outline(db, ep)
    others = [{"act": a, "scenes": [s for s in script["scenes"] if s["act"] == a]} for a in (1, 2, 3) if a != act]
    provider = text_provider(get_section(db, "text"))
    prompt = writer.act_prompt(outline, act, others, writer_characters(db, ep.id))
    if instruction:
        prompt += f"\n\nOWNER INSTRUCTION: {instruction}"
    answer = provider.complete_json(writer.system_prompt(get_section(db, "creative")), prompt)
    planned = [s["id"] for s in outline["acts"][act - 1]["scenes"]]
    scenes = answer.get("scenes") or []
    if [str(s.get("id", "")).lower() for s in scenes] != planned:
        raise ValueError(f"act {act}: the writer must return exactly the outline's scenes {planned} in order")
    for s in scenes:
        s["id"], s["act"] = s["id"].lower(), act
    new = dict(script)
    new["scenes"] = [s for a in (1, 2, 3) for s in (scenes if a == act else [x for x in script["scenes"] if x["act"] == a])]
    return validate_script(new, {c.key for c in characters(db)}, fmt="long")


# ------------------------------------------------------------------ voices and timings
def clip_map(db, ep: Episode) -> dict[int, dict[int, dict]]:
    """Voice clips per scene and line index (latest successful voice job per scene), checked against the current text."""
    jobs = {j.scene_id: j for j in db.query(Job).filter_by(episode_id=ep.id, kind="scene_voice", status="succeeded").order_by(Job.id)}
    out = {}
    for sc in ep.scenes:
        j = jobs.get(sc.id)
        if not j or not j.result.get("clips"):
            continue
        clips = {}
        for clip in j.result["clips"]:
            if clip["line"] >= len(sc.lines) or sc.lines[clip["line"]]["text"] != clip.get("text", sc.lines[clip["line"]]["text"]):
                raise engine.EngineInputError(f"scene {sc.position}: dialogue changed after its voice was recorded; re-run the scene")
            a = db.get(Asset, clip["asset_id"])
            clips[clip["line"]] = {**clip, "sha256": a.sha256, "key": a.storage_key}
        out[sc.id] = clips
    return out


def apply_durations(story: dict, refs: list[list[tuple[int, int]]], clips: dict) -> None:
    """Each voiced line stays on screen until its clip ends plus a 0.4 s beat (rounded up: a clip is never cut)."""
    for es, rs in zip(story["scenes"], refs):
        for line, (sid, li) in zip(es["lines"], rs):
            clip = clips.get(sid, {}).get(li)
            if clip:
                line["duration"] = max(line.get("duration", 0), math.ceil((clip["seconds"] + 0.4) * 100) / 100)


def engine_timings(story: dict, folder: Path) -> list[dict]:
    story_file = engine.write_story(story, folder)
    tmp = folder / "timings"
    shutil.rmtree(tmp, ignore_errors=True)
    s = get_settings()
    r = subprocess.run([s.node_bin, str(Path(__file__).parent / "node" / "line-timings.mjs"), str(story_file), str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=engine.env_for_node(), timeout=900,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise engine.EngineRunError("could not time the episode: " + engine.last_error(r.stdout + r.stderr))
    return json.loads(r.stdout)


def place_voices(story: dict, refs: list[list[tuple[int, int]]], clips: dict, timings: list[dict], folder: Path, gain: float) -> None:
    voice = []
    for es, rs, t in zip(story["scenes"], refs, timings):
        for k, (sid, li) in enumerate(rs):
            clip = clips.get(sid, {}).get(li)
            if not clip:
                continue
            local = storage().get_to_file(clip["key"], folder / "voice" / Path(clip["key"]).name)
            voice.append({"source": str(Path(local).resolve()), "sha256": clip["sha256"],
                          "licence": "Generated for this episode by the configured voice provider", "start": t["lines"][k]["start"], "gain": gain})
    if voice:
        story["audio"] = {"voice": voice}


# ------------------------------------------------------------------ segments
@task
def plan_segments(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    script = current_script(db, ep)
    prod = get_section(db, "production")
    chars = prepare_characters(ctx)
    clips = clip_map(db, ep)
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", "plan")
    full = engine.build_story(episode_id=ep.id, revision=ep.revision, title=ep.title, script=script, scenes=list(ep.scenes),
                              chars_by_key=chars, production=prod, end_card=False)
    refs = [[(sc.id, li) for li in range(len(sc.lines))] for sc in ep.scenes]
    apply_durations(full, refs, clips)
    timings = engine_timings(full, folder)
    scene_timings = [{"scene": sc.scene_key, "duration": t["duration"],
                      "lines": [{"start": round(ln["start"] - t["start"], 4), "duration": ln["duration"]} for ln in t["lines"]]}
                     for sc, t in zip(ep.scenes, timings)]
    total = sum(t["duration"] for t in scene_timings)
    if total > longform.HARD_CAP:
        raise ValueError(f"the episode runs {total:.0f} s, over the 7½-minute cap ({longform.HARD_CAP} s); tighten the script")
    plan = longform.plan_segments(scene_timings)
    by_key = {sc.scene_key: sc for sc in ep.scenes}
    registries = [Path(REPO_ROOT / c.registry_path) if not Path(c.registry_path).is_absolute() else Path(c.registry_path)
                  for c in chars.values() if c.registry_path and c.art_status == "approved"]
    force = set(job.payload.get("force_positions", []))
    db.query(Segment).filter_by(episode_id=ep.id, revision=ep.revision).delete()
    queued, reused = [], []
    for i, parts in enumerate(plan):
        story = engine.build_story(episode_id=ep.id, revision=ep.revision, title=ep.title, script=script, scenes=list(ep.scenes),
                                   chars_by_key=chars, production=prod, parts=parts, segment=(i, len(plan)))
        seg_refs = [[(by_key[p["scene"]].id, li) for li in range(p["lines"][0], p["lines"][1])] for p in parts]
        apply_durations(story, seg_refs, clips)
        clip_hashes = [clips.get(sid, {}).get(li, {}).get("sha256", "") for rs in seg_refs for sid, li in rs]
        # The story id names the revision ("ep12-r3-seg2"); it is not an input to the render, so it is left out of
        # the fingerprint (otherwise every segment would look changed in every revision).
        fp = longform.segment_fingerprint({k: v for k, v in story.items() if k != "id"}, clip_hashes, registries)
        seg = Segment(episode_id=ep.id, revision=ep.revision, position=i + 1, parts=parts, seconds=round(sum(p["duration"] for p in parts), 3),
                      fingerprint=fp, status="pending", error="")
        prev = None if (i + 1) in force else (db.query(Segment).filter(Segment.episode_id == ep.id, Segment.fingerprint == fp,
                                                                       Segment.status == "done").order_by(Segment.id.desc()).first())
        if prev:
            seg.status, seg.reused_from = "done", prev.reused_from or prev.id
            seg.video_asset_id, seg.audio_asset_id, seg.render_seconds = prev.video_asset_id, prev.audio_asset_id, 0.0
        db.add(seg)
        db.flush()
        (reused if prev else queued).append((seg, story, seg_refs))
    db.commit()
    for seg, story, seg_refs in queued:
        j = enqueue(db, "render_segment", episode_id=ep.id, revision=ep.revision,
                    payload={"segment_id": seg.id, "story": story, "refs": seg_refs})
        seg.job_id = j.id
    db.commit()
    event(db, ep.id, "production", f"Revision {ep.revision}: {len(plan)} segments ({total:.0f} s); {len(queued)} to render, {len(reused)} reused unchanged")
    db.commit()
    if not queued:
        enqueue(db, "join_segments", episode_id=ep.id, revision=ep.revision)
    return {"segments": len(plan), "render": [s.position for s, _, _ in queued], "reused": [s.position for s, _, _ in reused], "seconds": round(total, 2)}


@task
def render_segment(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    seg = db.get(Segment, job.payload["segment_id"])
    seg.status, seg.error, seg.job_id = "rendering", "", job.id
    db.commit()
    story = json.loads(json.dumps(job.payload["story"]))
    refs = [[tuple(x) for x in rs] for rs in job.payload["refs"]]
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", f"segment-{seg.position}")
    clips = clip_map(db, ep)
    if clips:
        place_voices(story, refs, clips, engine_timings(story, folder), folder, float(get_section(db, "voice").get("gain", 1.0)))

    def progress(run: dict) -> None:
        job.progress = {"status": run.get("status"), "stages": run.get("stages", []), "segment": seg.position}
        db.commit()

    t0 = time.time()
    from . import acting
    if acting.enabled(db):
        # Settings > Motion = studio rig animator: the same segment, performed by the procedural acting renderer
        mp4, wav, rep = acting.render(ctx, ep, refs, clips, prepare_characters(ctx), folder / "acting")
        result = {"run": {"status": "pass", "renderer": "acting", **rep}}
    else:
        result = engine.produce(story, folder, ctx.log, progress)
        out: Path = result["folder"]
        mp4 = next((out / "render").glob("*.mp4"), None)
        wav = next((out / "audio").glob("*.wav"), None)
    if not mp4 or not wav:
        raise engine.EngineRunError("the engine finished without the segment's video or audio")
    base = f"episodes/{ep.id}/r{ep.revision}/segments/{seg.position}-job{job.id}"
    v = store_asset(db, ep_id=ep.id, src=mp4, key=f"{base}.mp4", kind="segment-video", label=f"Segment {seg.position}",
                    content_type="video/mp4", job_id=job.id, revision=ep.revision)
    a = store_asset(db, ep_id=ep.id, src=wav, key=f"{base}.wav", kind="segment-audio", label=f"Segment {seg.position} audio",
                    content_type="audio/wav", job_id=job.id, revision=ep.revision)
    seg.video_asset_id, seg.audio_asset_id, seg.status = v.id, a.id, "done"
    seg.render_seconds = round(time.time() - t0, 1)
    db.commit()
    return {"segment": seg.position, "seconds": seg.seconds, "render_seconds": seg.render_seconds, "qa": result["run"].get("status")}


@task
def join_segments(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    segs = db.query(Segment).filter_by(episode_id=ep.id, revision=ep.revision).order_by(Segment.position).all()
    if not segs or any(s.status != "done" for s in segs):
        raise ValueError("not every segment of this revision is rendered")
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", "join")
    videos, wavs = [], []
    for s in segs:
        v, a = db.get(Asset, s.video_asset_id), db.get(Asset, s.audio_asset_id)
        videos.append(storage().get_to_file(v.storage_key, folder / f"seg-{s.position}.mp4"))
        wavs.append(storage().get_to_file(a.storage_key, folder / f"seg-{s.position}.wav"))
    out = folder / f"episode-{ep.id}-r{ep.revision}.mp4"
    checks = longform.join_segments(videos, wavs, out, folder / "lists")
    report = folder / "join-report.json"
    report.write_text(json.dumps(checks, indent=1), encoding="utf-8")
    base = f"episodes/{ep.id}/r{ep.revision}"
    store_asset(db, ep_id=ep.id, src=report, key=f"{base}/join-report-job{job.id}.json", kind="report", label="Join report",
                content_type="application/json", job_id=job.id, revision=ep.revision)
    if not checks["ok"]:
        db.commit()
        raise ValueError("the joined episode failed its checks: " + "; ".join(checks["problems"]))
    video = store_asset(db, ep_id=ep.id, src=out, key=f"{base}/video-job{job.id}.mp4", kind="video",
                        label=f"{ep.title} (revision {ep.revision}, {len(segs)} segments)", content_type="video/mp4", job_id=job.id, revision=ep.revision)
    ep.video_asset_id = video.id
    for sc in ep.scenes:
        sc.production_status = "done"
    set_stage(ep, "video_review")
    event(db, ep.id, "production", f"Revision {ep.revision} joined from {len(segs)} segments ({checks['duration']:.1f} s); ready for video review")
    db.commit()
    return {"video_asset_id": video.id, "duration": checks["duration"], "segments": len(segs)}


def after_long_job(db, job: Job, ep: Episode) -> bool:
    """Advance a long episode after a long-form job. Returns True when the job was a long-form kind."""
    if job.kind == "generate_outline":
        if job.status == "failed":
            set_stage(ep, "outline_review" if ep.outline_version else "script_pending")
            db.commit()
        return True
    if job.kind == "generate_act":
        if job.status == "failed":
            set_stage(ep, "outline_approved")
            db.commit()
        return True
    if job.kind == "plan_segments":
        if job.status == "failed":
            set_stage(ep, "production_failed")
            db.commit()
        return True
    if job.kind == "render_segment":
        seg = db.get(Segment, job.payload.get("segment_id"))
        if job.status == "failed":
            if seg:
                seg.status, seg.error = "failed", job.error
            set_stage(ep, "production_failed")
            db.commit()
            return True
        segs = db.query(Segment).filter_by(episode_id=ep.id, revision=ep.revision).all()
        joining = db.query(Job).filter(Job.episode_id == ep.id, Job.revision == ep.revision, Job.kind == "join_segments",
                                       Job.status.in_(["queued", "running", "succeeded"])).count()
        if segs and all(s.status == "done" for s in segs) and not joining:
            set_stage(ep, "producing")
            db.commit()
            enqueue(db, "join_segments", episode_id=ep.id, revision=ep.revision)
        return True
    if job.kind == "join_segments":
        if job.status == "failed":
            set_stage(ep, "production_failed")
            db.commit()
        return True
    return False


def start_long_scene_jobs(db, ep: Episode, scenes: list[StoryboardScene]) -> list[StoryboardScene]:
    """Selective regeneration: a scene whose content is unchanged since its last successful preparation and voice keeps
    them (no re-voicing, so its segments keep their fingerprints). Returns the scenes that need new jobs."""
    need = []
    last = {}
    for j in db.query(Job).filter(Job.episode_id == ep.id, Job.kind.in_(["scene_prepare", "scene_voice"]), Job.status == "succeeded").order_by(Job.id):
        last[(j.kind, j.scene_id)] = j
    for sc in scenes:
        h = scene_hash(sc)
        ok = all(last.get((k, sc.id)) and last[(k, sc.id)].result.get("scene_hash") == h for k in ("scene_prepare", "scene_voice"))
        if ok:
            sc.production_status = "done"
        else:
            need.append(sc)
    db.commit()
    return need
