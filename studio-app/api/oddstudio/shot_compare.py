"""Shot comparison (owner request 2026-11-21, Production > Motion Model Comparison): AI video models against the rig
animator on single lines of a real episode.

Inputs are ONLY the studio's own approved art: the speaking character's approved neutral pose on the episode's (or the
scene's) approved set plate, composed locally into one first frame; and the line's own recorded audio, cut from the
episode's recording. Frames or stills from the uploaded reference video never exist after analysis and are never used.
The action description is written from the video notes' fixed-list words (staging and beats) and is editable.

Flow: plan (free, a local job: first frame, audio cut, rig render of the same line) -> the page shows, per model, the
exact request (prompt, the image and audio sent), the estimated cost and the experimental budget's running total ->
nothing is sent until the owner clicks Run for that model -> results side by side with the rig render, with the actual
cost per clip and per second. Our audio is never replaced by a model's: every output gets the original line audio,
and its length is checked to be the line's length within one frame.

Models (fal.ai, checked 2026-11-21; both pages say "Commercial use permitted (Partner)"):
- Kling 2.6 Pro image-to-video, audio off: $0.07 per second, 5 or 10 s clips (cut to the line afterwards).
- Kling AI Avatar v2 Standard: image + OUR line audio -> a talking clip as long as the audio; $0.0562 per second.
"""
from __future__ import annotations

import json
import math
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, CharacterAsset, Episode, Event, Setting, StoryboardScene

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
ROW = "_shot_compare"
FPS = 30
W, H = 720, 1280

MODELS = {
    "kling-2.6-pro-i2v": {
        "endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video", "kind": "i2v", "rate": 0.07,
        "label": "Kling 2.6 Pro image-to-video (audio off)",
        "why": "a strong current image-to-video model; with audio off it is the cheapest Kling Pro tier",
        "price": "$0.07 per second with audio off; 5 or 10 s clips", "licence": "Commercial use permitted (fal Partner model)",
        "framing": "wide"},
    "kling-avatar-v2-standard": {
        "endpoint": "fal-ai/kling-video/ai-avatar/v2/standard", "kind": "avatar", "rate": 0.0562,
        "label": "Kling AI Avatar v2 Standard (our line audio)",
        "why": "takes an image AND our recorded line, so the mouth follows our audio; the output is as long as the audio; "
               "the page lists cartoons and stylized characters",
        "price": "$0.0562 per second of audio", "licence": "Commercial use permitted (fal Partner model)",
        "framing": "medium"},   # a talking-avatar model: head and upper body fill the frame (owner decision 2026-11-21)
}
FRAMINGS = ("wide", "medium")
NEGATIVE = "realistic, photo, 3d render, extra characters, text, logo, watermark, deformed, blur"


# ------------------------------------------------------------------ records
def records(db: Session) -> dict:
    row = db.get(Setting, ROW)
    return dict(row.value) if row else {}


def save(db: Session, recs: dict) -> None:
    row = db.get(Setting, ROW)
    if row:
        row.value = recs
    else:
        db.add(Setting(key=ROW, value=recs))


def estimate(model: str, seconds: float) -> dict:
    m = MODELS[model]
    if m["kind"] == "i2v":
        billed = 5 if seconds <= 5 else 10
        note = "" if seconds <= 10 else f"the line runs {seconds:.1f} s: the 10 s clip's last frame is held to the end"
    else:
        billed, note = math.ceil(seconds), ""
    return {"billed_seconds": billed, "usd": round(m["rate"] * billed, 4), "note": note}


def prompt_for(model: str, action: str) -> str:
    if MODELS[model]["kind"] == "i2v":
        return ("2D flat cartoon animation, static camera. The character in the image " + action.strip().rstrip(".") +
                ". Keep the character's design, colours and proportions and the background exactly as in the image; "
                "no new characters, no text, no camera move.")
    return (action.strip().rstrip(".") + ". Keep the character's flat 2D design and the background exactly as in the "
            "image; the mouth follows the audio.")


def request_for(model: str, action: str, image_url: str, audio_url: str, seconds: float) -> dict:
    """The exact JSON body sent to fal (shown to the owner before Run)."""
    if MODELS[model]["kind"] == "i2v":
        return {"prompt": prompt_for(model, action), "start_image_url": image_url,
                "duration": str(estimate(model, seconds)["billed_seconds"]), "generate_audio": False, "negative_prompt": NEGATIVE}
    return {"image_url": image_url, "audio_url": audio_url, "prompt": prompt_for(model, action)}


# ------------------------------------------------------------------ the line and its words-only action
def _episode_line(db: Session, eid: int, scene_id: int, line: int):
    ep = db.get(Episode, eid)
    sc = db.get(StoryboardScene, scene_id)
    if ep is None or sc is None or sc.episode_id != ep.id or not 0 <= line < len(sc.lines or []):
        raise HTTPException(404, "no such line")
    return ep, sc, sc.lines[line]


def action_from_notes(db: Session, ep: Episode, ln: dict) -> str:
    """A short action description from the video notes' fixed-list words for the line's time (editable)."""
    from . import beats as BT
    from . import video_notes as VN
    from .reference_plan import effective
    tr = ep.audio_transcript or {}
    if "start" not in ln or not (tr.get("video_notes") or {}).get("ranges"):
        return f"talks ({ln.get('expression') or 'neutral'}), with small natural head and hand movements"
    r = VN.for_line(effective(tr), ln) or {}
    sp = next((ro for ro in r.get("roles", []) if ro.get("role") == "speaker"), {})
    bits = [sp.get("pose"), sp.get("emotion") and f"looking {sp['emotion']}"]
    names = BT.names_of(db, tr)
    who = {v: k for k, v in (tr.get("person_map") or {}).items()}
    own = [b for b in (tr.get("video_notes") or {}).get("beats") or []
           if ln["start"] <= b["t"] < ln["end"] and who.get(b["person"]) == ln.get("speaker") and b["type"] in BT.SUPPORTED]
    acts = [BT.describe(b, names).split(" ", 1)[1].rsplit(" (", 1)[0] for b in own]
    words = ", ".join(x for x in bits if x) or "talking"
    return f"is {words} and talks" + (f"; {', '.join(acts)}" if acts else "") + ", with small natural head and hand movements"


@router.get("/motion/shot/options")
def options(episode_id: int, db: Session = Depends(get_db)):
    from . import fal
    ep = db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(404, "episode not found")
    chars = {c.key: c for c in db.query(Character).all()}
    lines = []
    for sc in sorted(ep.scenes, key=lambda s: s.position):
        for i, ln in enumerate(sc.lines or []):
            c = chars.get(ln.get("speaker"))
            ok = bool(c and (c.expressions or {}).get("neutral"))
            lines.append({"scene_id": sc.id, "scene": sc.position, "line": i, "speaker": ln.get("speaker"), "text": ln.get("text"),
                          "seconds": round(float(ln.get("end", 0)) - float(ln.get("start", 0)), 2) if "start" in ln else None,
                          "ready": ok and "start" in ln, "why_not": None if ok else "the speaker has no approved neutral pose",
                          "action": action_from_notes(db, ep, ln)})
    led = fal.spent(db)
    return {"episode": {"id": ep.id, "title": ep.title, "set_id": ep.set_id}, "lines": lines,
            "models": [{"id": k, **{x: m[x] for x in ("label", "why", "price", "licence")}} for k, m in MODELS.items()],
            "spent_usd": round(led["total"], 2), "budget_usd": fal.budget(db)}


class PlanIn(BaseModel):
    episode_id: int
    scene_id: int
    line: int = Field(ge=0)
    action: str = Field(min_length=3, max_length=400)


@router.post("/motion/shot/plan")
def make_plan(body: PlanIn, db: Session = Depends(get_db)):
    """Free: queue the local preparation (first frame from approved art, the line's audio, the rig render)."""
    from .queue import enqueue
    ep, sc, ln = _episode_line(db, body.episode_id, body.scene_id, body.line)
    if "start" not in ln or ep.source != "audio":
        raise HTTPException(409, "the comparison uses a recorded line (an audio-first episode)")
    pid = uuid.uuid4().hex[:10]
    recs = records(db)
    recs[pid] = {"id": pid, "episode_id": ep.id, "scene_id": sc.id, "line": body.line, "speaker": ln.get("speaker"),
                 "text": ln.get("text"), "start": float(ln["start"]), "end": float(ln["end"]),
                 "seconds": round(float(ln["end"]) - float(ln["start"]), 3), "action": body.action.strip(),
                 "status": "preparing", "created": time.time(), "results": {}}
    save(db, recs)
    job = enqueue(db, "shot_prepare", episode_id=ep.id, payload={"pid": pid})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Shot comparison planned for scene {sc.position}, line {body.line + 1} (free preparation)"))
    db.commit()
    return {"plan": view(db, recs[pid]), "job_id": job.id}


def framing_of(p: dict, model: str) -> str:
    """The first frame a model gets: the owner's choice for this plan, else the model's default."""
    return (p.get("framing") or {}).get(model) or MODELS[model]["framing"]


def view(db: Session, p: dict) -> dict:
    from . import fal
    from .comparison import public_url
    from .models import Asset
    from .storage import storage
    url = lambda aid: storage().url(db.get(Asset, aid).storage_key) if aid and db.get(Asset, aid) else None
    out = {**p, "frame_url": url(p.get("frame_asset_id")), "audio_url": url(p.get("audio_asset_id")),
           "rig_url": url(p.get("rig_asset_id"))}
    frames = p.get("frame_assets") or {"wide": p.get("frame_asset_id")}
    out["frame_urls"] = {f: url(a) for f, a in frames.items()}
    if p.get("status") == "ready":
        sent_img = public_url(storage().url(db.get(Asset, p["frame_asset_id"]).storage_key, 7200)) if p.get("frame_asset_id") else ""
        sent_aud = public_url(storage().url(db.get(Asset, p["audio_asset_id"]).storage_key, 7200)) if p.get("audio_asset_id") else ""
        out["requests"] = [{"model": k, "label": m["label"], "endpoint": m["endpoint"], "price": m["price"],
                            "estimate": estimate(k, p["seconds"]), "framing": framing_of(p, k),
                            "frame_url": out["frame_urls"].get(framing_of(p, k)),
                            "body": request_for(k, p["action"], f"<the {framing_of(p, k)} first frame shown>", "<the line audio shown above>", p["seconds"]),
                            "sends": [f"the {framing_of(p, k)} first frame (approved set + approved neutral pose)"]
                                     + (["the line's own recorded audio"] if m["kind"] == "avatar" else []),
                            "result": p["results"].get(k)} for k, m in MODELS.items()]
        out["urls_ok"] = bool(sent_img.startswith("http") and sent_aud.startswith("http"))
    for k, r in (p.get("results") or {}).items():
        if r.get("asset_id"):
            r["url"] = url(r["asset_id"])
    led = fal.spent(db)
    out["spent_usd"], out["budget_usd"] = round(led["total"], 2), fal.budget(db)
    return out


@router.get("/motion/shot")
def list_plans(db: Session = Depends(get_db)):
    return {"plans": [view(db, p) for p in sorted(records(db).values(), key=lambda p: -p.get("created", 0))[:10]]}


class FramingIn(BaseModel):
    model: str
    framing: str


@router.put("/motion/shot/{pid}/framing")
def set_framing(pid: str, body: FramingIn, db: Session = Depends(get_db)):
    """Free: which first frame a model gets (wide: the whole set; medium: head and upper body filling the frame)."""
    recs = records(db)
    p = recs.get(pid)
    if not p:
        raise HTTPException(404, "no such plan")
    if body.model not in MODELS or body.framing not in FRAMINGS:
        raise HTTPException(422, f"framing must be one of {', '.join(FRAMINGS)}")
    if (p["results"].get(body.model) or {}).get("status") in ("queued", "running"):
        raise HTTPException(409, "not while that model is running")
    p["framing"] = {**(p.get("framing") or {}), body.model: body.framing}
    save(db, recs)
    db.commit()
    return view(db, p)


class RunIn(BaseModel):
    model: str


@router.post("/motion/shot/{pid}/run")
def run_model(pid: str, body: RunIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's approval of ONE paid request, after seeing its prompt, images and estimate."""
    from . import fal
    from .providers import ProviderError
    from .queue import enqueue
    p = records(db).get(pid)
    if not p:
        raise HTTPException(404, "no such plan")
    if body.model not in MODELS:
        raise HTTPException(422, "unknown model")
    if p.get("status") != "ready":
        raise HTTPException(409, "the plan is not ready yet (its free preparation is still running or failed)")
    if (p["results"].get(body.model) or {}).get("status") in ("queued", "running"):
        raise HTTPException(409, "already running")
    if not view(db, p).get("urls_ok"):
        raise HTTPException(409, "fal.ai fetches the first frame and the line audio from the studio: set PUBLIC_URL on the server first")
    est = estimate(body.model, p["seconds"])
    # approved runs that have not been charged yet count too, so two quick approvals cannot pass the cap together
    pending = sum(r.get("estimated_usd") or 0 for q in records(db).values() for r in (q.get("results") or {}).values()
                  if r.get("status") in ("queued", "running"))
    try:
        fal.check_budget(db, est["usd"] + pending)
    except ProviderError as e:
        raise HTTPException(409, str(e) + (f" (including ${pending:.2f} already approved and not yet run)" if pending else ""))
    recs = records(db)
    recs[pid]["results"][body.model] = {"status": "queued", "estimated_usd": est["usd"], "approved_by": user}
    save(db, recs)
    job = enqueue(db, "shot_generate", episode_id=p["episode_id"], payload={"pid": pid, "model": body.model})
    db.add(Event(episode_id=p["episode_id"], kind="episode", message=f"Shot comparison: {MODELS[body.model]['label']} approved by {user} (estimated ${est['usd']:.2f})"))
    db.commit()
    return {"job_id": job.id, "estimate": est}


# ------------------------------------------------------------------ media helpers
def _ff(args: list[str]) -> None:
    from .config import get_settings
    r = subprocess.run([get_settings().ffmpeg, "-v", "error", "-y", *args], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr.strip()[-300:]}")


def stream_seconds(path: Path) -> dict:
    """Duration of the video and the audio streams (FFprobe)."""
    from .config import get_settings
    r = subprocess.run([get_settings().ffprobe, "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=120)
    out = {}
    for s in json.loads(r.stdout or "{}").get("streams", []):
        try:
            out[s["codec_type"]] = float(s["duration"])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def finish(video: Path, wav: Path, seconds: float, out: Path) -> dict:
    """The model's (or the rig's) picture with OUR line audio: the picture is cut, or its last frame held, to exactly
    the line's length at 30 fps; any audio the model made is dropped. Returns the length check."""
    vs = stream_seconds(video).get("video") or 0.0
    pad = max(0.0, seconds - vs) + 0.5
    _ff(["-i", str(video), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
         "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
         "-t", f"{seconds:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)])
    got = stream_seconds(out)
    v, a = got.get("video") or 0.0, got.get("audio") or 0.0
    return {"model_seconds": round(vs, 3), "video_seconds": round(v, 3), "audio_seconds": round(a, 3),
            "line_seconds": round(seconds, 3), "held_last_frame": vs + 1e-3 < seconds,
            "length_ok": abs(v - seconds) <= 1.0 / FPS + 1e-3 and abs(a - seconds) <= 1.0 / FPS + 1e-3}


def compose(plate: Path, pose: Path, blocking: dict, plate_w: int, plate_h: int, out: Path, framing: str = "wide") -> Path:
    """The first frame: the approved set plate (cover-fit to 720x1280) and the approved neutral pose, centred. Our own
    art only. wide: the whole figure standing on the floor line. medium: closer on the same plate, the head and upper
    body filling most of the frame (the figure runs off the bottom edge, the plate is enlarged to match)."""
    from PIL import Image
    bg = Image.open(plate).convert("RGB")
    k = max(W / bg.width, H / bg.height)
    if framing == "medium":
        fig = Image.open(pose).convert("RGBA")
        box = fig.getchannel("A").getbbox() or (0, 0, fig.width, fig.height)
        fig = fig.crop(box)
        fh = round(H * 1.55)                          # the head and upper body fill the frame, legs below the edge
        fig = fig.resize((max(1, round(fig.width * fh / fig.height)), fh))
        k2 = k * 1.55 / 0.46                          # the plate enlarged as much as the figure (same apparent scale)
        bg = bg.resize((round(bg.width * k2), round(bg.height * k2)))
        head_top = round(H * 0.06)
        floor = round(blocking.get("floor_y", plate_h * 0.86) * k2)
        top = max(0, min(bg.height - H, floor - (head_top + fh)))
        left = (bg.width - W) // 2
        bg = bg.crop((left, top, left + W, top + H))
        bg.paste(fig, ((W - fig.width) // 2, head_top), fig)
        bg.save(out)
        return out
    bg = bg.resize((round(bg.width * k), round(bg.height * k)))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H))
    fig = Image.open(pose).convert("RGBA")
    box = fig.getchannel("A").getbbox() or (0, 0, fig.width, fig.height)
    fig = fig.crop(box)
    fh = round(H * 0.46)
    fig = fig.resize((max(1, round(fig.width * fh / fig.height)), fh))
    floor = round(blocking.get("floor_y", plate_h * 0.86) * k) - top
    bg.paste(fig, ((W - fig.width) // 2, min(H, floor) - fig.height), fig)
    bg.save(out)
    return out


# ------------------------------------------------------------------ jobs
from .tasks import Ctx, store_asset, task  # noqa: E402


@task
def shot_prepare(ctx: Ctx) -> dict:
    """Free and local: the first frame, the line's audio and the rig render of the same line."""
    from . import media, scene_sets
    from . import sets as studio_sets
    from .audio_production import source_audio
    from .storage import storage
    db, job = ctx.db, ctx.job
    pid = job.payload["pid"]
    p = records(db)[pid]
    ep = db.get(Episode, p["episode_id"])
    sc = db.get(StoryboardScene, p["scene_id"])
    folder = ctx.folder("shot-compare", pid)
    try:
        c = db.query(Character).filter_by(key=p["speaker"]).one()
        pid_pose = (c.expressions or {}).get("neutral")
        a = db.get(CharacterAsset, int(pid_pose[1:])) if pid_pose and pid_pose.startswith("p") else None
        if a is None or a.status != "approved":
            raise RuntimeError(f"{c.name} has no approved neutral pose")
        pose = storage().get_to_file(a.storage_key, folder / "pose.png")
        set_id = scene_sets.scene_set(ep, sc)
        spec = studio_sets.spec_for(db, set_id, folder / "set") if set_id else None
        if not spec:
            raise RuntimeError("the scene has no approved set")
        frame_assets = {}
        for f in FRAMINGS:
            frame = compose(Path(spec["plate"]), pose, spec, spec["width"], spec["height"], folder / f"first-frame-{f}.png", f)
            frame_assets[f] = store_asset(db, ep_id=ep.id, src=frame, key=f"episodes/{ep.id}/shot-compare/{pid}/first-frame-{f}.png",
                                          kind="scene-reference", label=f"Shot comparison first frame, {f} (approved set + approved neutral pose)",
                                          content_type="image/png", job_id=job.id).id
        src, _ = source_audio(db, ep, folder / "source")
        wav = media.cut_audio(src, folder / "line.wav", p["start"], p["end"])
        aa = store_asset(db, ep_id=ep.id, src=wav, key=f"episodes/{ep.id}/shot-compare/{pid}/line.wav", kind="audio",
                         label="Shot comparison: the line's recorded audio", content_type="audio/wav", job_id=job.id)
        recs = records(db)
        recs[pid].update({"frame_asset_id": frame_assets["wide"], "frame_assets": frame_assets, "audio_asset_id": aa.id, "set_id": set_id, "status": "ready",
                          "audio_seconds": round(media.probe(wav)["duration"] or p["seconds"], 3)})
        save(db, recs)
        db.commit()
        # the rig render of the same line (free; a failure here does not block the AI comparison)
        try:
            from . import acting
            from .tasks import prepare_characters
            from .tasks_long import clip_map
            mp4, _, _ = acting.render(ctx, ep, [[(sc.id, p["line"])]], clip_map(db, ep), prepare_characters(ctx), folder / "rig")
            cut = folder / "rig-line.mp4"
            _ff(["-ss", f"{p['start']:.3f}", "-i", str(mp4), "-t", f"{p['seconds'] + 0.5:.3f}", "-an", "-c:v", "libx264", str(cut)])
            out = folder / "rig-final.mp4"
            check = finish(cut, wav, p["seconds"], out)
            ra = store_asset(db, ep_id=ep.id, src=out, key=f"episodes/{ep.id}/shot-compare/{pid}/rig.mp4", kind="video",
                             label="Shot comparison: the rig animator", content_type="video/mp4", job_id=job.id)
            recs = records(db)
            recs[pid].update({"rig_asset_id": ra.id, "rig_check": check})
        except Exception as e:   # noqa: BLE001
            recs = records(db)
            recs[pid]["rig_error"] = f"the rig render of this line is not available: {str(e)[:200]}"
            ctx.log(recs[pid]["rig_error"])
        save(db, recs)
        db.commit()
    except Exception as e:
        recs = records(db)
        recs[pid].update({"status": "failed", "error": str(e)[:300]})
        save(db, recs)
        db.commit()
        raise
    return {"pid": pid}


@task
def shot_generate(ctx: Ctx) -> dict:
    """ONE paid request the owner approved: send the shown request, then put our line audio under the result."""
    from . import fal
    from .comparison import public_url
    from .models import Asset
    from .storage import storage
    db, job = ctx.db, ctx.job
    pid, model = job.payload["pid"], job.payload["model"]
    p = records(db)[pid]
    m = MODELS[model]
    folder = ctx.folder("shot-compare", pid)
    framing = framing_of(p, model)
    img = public_url(storage().url(db.get(Asset, (p.get("frame_assets") or {}).get(framing) or p["frame_asset_id"]).storage_key, 7200))
    aud = public_url(storage().url(db.get(Asset, p["audio_asset_id"]).storage_key, 7200))
    body = request_for(model, p["action"], img, aud, p["seconds"])
    est = estimate(model, p["seconds"])

    def mark(**kw):
        recs = records(db)
        recs[pid]["results"][model] = {**recs[pid]["results"].get(model, {}), **kw}
        save(db, recs)
        db.commit()

    mark(status="running")
    try:
        raw = folder / f"{model}-raw.mp4"
        data, tm = fal.run(db, m["endpoint"], m["label"], body, est["usd"], f"shot {pid}: {p['text'][:60]}", raw, ctx.log,
                           lambda info: mark(progress=info))
        if m["kind"] == "avatar":
            # billed per second of OUR audio (the output follows it): the reported duration, else the audio's length
            billed = float(data.get("duration") or p.get("audio_seconds") or p["seconds"])
            actual = round(m["rate"] * billed, 4)
        else:
            actual = est["usd"]
        if abs(actual - est["usd"]) > 0.0001:
            fal.correct_spend(db, est["usd"], actual)
        wav = storage().get_to_file(db.get(Asset, p["audio_asset_id"]).storage_key, folder / "line.wav")
        out = folder / f"{model}.mp4"
        check = finish(raw, wav, p["seconds"], out)
        va = store_asset(db, ep_id=p["episode_id"], src=out, key=f"episodes/{p['episode_id']}/shot-compare/{pid}/{model}.mp4",
                         kind="video", label=f"Shot comparison: {m['label']}", content_type="video/mp4", job_id=job.id)
        mark(status="done", asset_id=va.id, actual_usd=actual, framing=framing, per_second_usd=round(actual / max(0.001, p["seconds"]), 4),
             check=check, seconds=tm["seconds"], request_id=tm["request_id"])
        return {"pid": pid, "model": model, "actual_usd": actual, "check": check}
    except Exception as e:
        mark(status="failed", error=str(e)[:300])
        raise
