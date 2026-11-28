"""Assembly and the owner's review (guided flow, step 11): the whole episode put together on the studio server from
APPROVED results only, over the episode's ORIGINAL recording. FFmpeg only, so it is free.

Sources, per storyboard shot (shot_frames.py), in this order:
  * a talking shot (talking_s2v.py) with an approved result: the result's first `trim_start_frames` (2) frames are
    dropped (they settle from the still), then the clip is slowed a little when it is short (at most 1.4x) and its
    last frame is held to the shot's length; a longer clip is cut at the end;
  * a reaction shot (reactions.py) with an approved result: the same (no frames to drop);
  * otherwise the shot's approved still, held for the whole shot and listed as "still, not animated".
A shot with none of these blocks the assembly (nothing unapproved is ever used).

Frame-exact timing (the owner's proven assemble_ep15.py): each shot lasts from its own start to the NEXT shot's start
(the first from 0, the last to the end of the recording), and its frame count is round(next_start * 25) -
round(start * 25). Frames are counted from absolute positions, so half-frame roundings never add up into drift (a
one-shot drift made the mouths go out of sync on Episode 15). 25 fps; 1280x720 for a 16:9 episode, 720x1280 for a 9:16
one (each picture fitted inside, black around it when its shape differs).

On top: the episode's POV banner (acting.episode_hook: "" when it is off) and its dialogue display (bubbles | none |
captions) from the transcript's lines, drawn once as transparent pictures by production/animation/overlay.mjs (the
same fonts and banner layout as the episode renderer) and laid over the video by FFmpeg at each line's time. Without
Node the cut is made without them, with a warning.

Nothing is approved by itself: the cut waits for the owner's "Approve the final cut" click.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Episode, Event, Job, Setting
from .queue import enqueue
from .storage import sha256_file, storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

JOB = "episode_assembly"
FPS = 25
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280)}
MAX_STRETCH = 1.4
TALK_FPS = 16                # talking_s2v.FPS (the Speech-to-Video output)
STILL_LABEL = "still, not animated"


def key(eid: int) -> str:
    return f"assembly:{eid}"


# ================================================================== pure parts
def segment_frames(starts: list[float], end: float, fps: int = FPS) -> list[tuple[int, int]]:
    """[(first frame, frame count)] for shots starting at `starts` (sorted, seconds): shot i runs from its start (the
    first from 0) to the next shot's start, the last to `end`. Counts come from ABSOLUTE frame positions
    (round(next * fps) - round(start * fps)), so roundings never accumulate. Every shot gets at least one frame."""
    out: list[tuple[int, int]] = []
    pos = 0
    for i in range(len(starts)):
        stop = starts[i + 1] if i + 1 < len(starts) else max(end, starts[i])
        b = max(round(stop * fps), pos + 1)
        out.append((pos, b - pos))
        pos = b
    return out


def fit_clip(src_frames: int, src_fps: float, trim: int, slot_frames: int, fps: int = FPS) -> dict:
    """How a clip fills its slot: {stretch, used_s, held_s, cut_s, warnings}. The first `trim` frames are dropped;
    a short clip is slowed (at most MAX_STRETCH) and its last frame held; a long one is cut at the end."""
    slot = slot_frames / fps
    have = max(0, src_frames - trim) / src_fps if src_fps else 0.0
    out = {"stretch": 1.0, "used_s": round(have, 3), "held_s": 0.0, "cut_s": 0.0, "warnings": []}
    if have <= 0:
        out["held_s"] = round(slot, 3)
        out["warnings"].append("the clip has no frames after the trim: its first frame is held")
        return out
    if have < slot - 1e-6:
        st = min(MAX_STRETCH, slot / have)
        out["stretch"] = round(st, 4)
        held = slot - have * st
        if held > 1.0 / fps:
            out["held_s"] = round(held, 3)
            out["warnings"].append(f"the clip is {slot - have:.2f} s shorter than the shot: slowed to {st * 100:.0f}% and "
                                   f"its last frame held for {held:.2f} s")
        elif st > 1.0001:
            out["warnings"].append(f"the clip is {slot - have:.2f} s shorter than the shot: slowed to {st * 100:.0f}%")
    elif have > slot + 1.0 / fps:
        out["cut_s"] = round(have - slot, 3)
        out["warnings"].append(f"the clip is {have - slot:.2f} s longer than the shot: the end is cut")
    return out


def picture_filter(w: int, h: int) -> str:
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,format=yuv420p")


def clip_filter(trim: int, stretch: float, slot_frames: int, w: int, h: int, fps: int = FPS) -> str:
    """trim the settle frames at the source rate, slow down, resample to 25 fps, fit, then hold the last frame."""
    parts = []
    if trim > 0:
        parts.append(f"trim=start_frame={trim}")
    parts.append("setpts=PTS-STARTPTS")
    if abs(stretch - 1.0) > 1e-4:
        parts.append(f"setpts={stretch:.4f}*PTS")
    parts += [f"fps={fps}", picture_filter(w, h), f"tpad=stop_mode=clone:stop_duration={slot_frames / fps + 1:.3f}"]
    return ",".join(parts)


def segment_command(ff: str, row: dict, src: Path, out: Path, w: int, h: int) -> list[str]:
    n = int(row["frames"])
    enc = ["-frames:v", str(n), "-r", str(FPS), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", str(out)]
    if row["source"] == "still":
        return [ff, "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(src), "-vf", picture_filter(w, h)] + enc
    vf = clip_filter(int(row.get("trim_start_frames") or 0), float(row.get("stretch") or 1.0), n, w, h)
    return [ff, "-v", "error", "-y", "-i", str(src), "-vf", vf] + enc


def overlay_graph(n_lines_windows: list[tuple[float, float]], has_banner: bool) -> tuple[str, str]:
    """(filter_complex, output label) laying the banner (input 2) and each line picture (inputs 3...) over the video
    (input 0), each line only between its start and end."""
    parts, cur, k = [], "0:v", 2
    if has_banner:
        parts.append(f"[{cur}][{k}:v]overlay=0:0[b0]")
        cur, k = "b0", k + 1
    for i, (a, b) in enumerate(n_lines_windows):
        nxt = f"l{i}"
        parts.append(f"[{cur}][{k}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[{nxt}]")
        cur, k = nxt, k + 1
    return ";".join(parts), cur


def sources_hash(rows: list[dict]) -> str:
    keep = [[r["index"], r["source"], r.get("asset_id"), r["frames"]] for r in rows]
    return hashlib.sha256(json.dumps(keep).encode()).hexdigest()[:12]


# ================================================================== episode data
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


def frame_size(ep: Episode) -> tuple[int, int]:
    from .stick_shots import aspect_ratio
    return SIZES[aspect_ratio(ep)]


def recording_end(db: Session, ep: Episode, shots: list[dict]) -> float:
    """The end of the last shot: the recording's length (measured by the assembly job and kept), else the last shot's
    end (only the last shot's length can differ until the first cut is made)."""
    last = max((float(s.get("t1") or 0) for s in shots), default=0.0)
    rec = stored(db, ep.id).get("recording") or {}
    if rec.get("asset_id") == ep.audio_asset_id and rec.get("seconds"):
        return float(rec["seconds"])
    return last


def _talk_record(tv: dict, idx: int) -> tuple[dict | None, bool]:
    st = (tv.get("shots") or {}).get(str(idx)) or {}
    rid = st.get("approved")
    rec = next((r for r in st.get("renders") or [] if r.get("id") == rid), None) if rid else None
    return rec, bool(st.get("renders"))


def _react_record(rv: dict, idx: int) -> tuple[dict | None, bool]:
    st = (rv.get("shots") or {}).get(str(idx)) or {}
    cid = st.get("approved")
    rec = next((c for c in st.get("clips") or [] if c.get("id") == cid), None) if cid else None
    return rec, bool(st.get("clips"))


def plan_rows(db: Session, ep: Episode) -> dict:
    """The shot-by-shot list: {rows, size, fps, end, frames, missing}. Each row: index, start, seconds, frames,
    start_frame, source (talking | reaction | still | missing), label, asset_id, trim_start_frames, src_fps,
    src_frames, stretch, warnings. Only approved results are used."""
    from . import reactions as R
    from . import shot_frames as SF
    from . import talking_s2v as T
    shots = sorted(SF.migrated(SF.stored(db, ep.id)).get("shots") or [], key=lambda s: float(s["t0"]))
    w, h = frame_size(ep)
    if not shots:
        return {"rows": [], "size": [w, h], "fps": FPS, "end": 0.0, "frames": 0, "missing": [], "hash": ""}
    end = recording_end(db, ep, shots)
    segs = segment_frames([float(s["t0"]) for s in shots], end)
    talking = {r["index"] for r in T.talking_rows(db, ep)}
    reacting = {r["index"] for r in R.reaction_rows(db, ep)}
    tv, rv = T.stored(db, ep.id), R.stored(db, ep.id)
    rows, missing = [], []
    for s, (f0, n) in zip(shots, segs):
        idx = int(s["index"])
        row = {"index": idx, "start": round(f0 / FPS, 3), "seconds": round(n / FPS, 3), "frames": n, "start_frame": f0,
               "t0": float(s["t0"]), "t1": float(s.get("t1") or s["t0"]), "source": "missing", "label": "",
               "asset_id": None, "trim_start_frames": 0, "src_fps": None, "src_frames": None, "stretch": 1.0, "warnings": []}
        rec, waiting = (None, False)
        if idx in talking:
            rec, waiting = _talk_record(tv, idx)
            if rec:
                frames = sum(rec.get("pieces") or []) or int(rec.get("frames") or 0)
                row.update(source="talking", label="talking shot (approved)", asset_id=rec.get("asset_id"),
                           trim_start_frames=int(rec.get("trim_start_frames") or 0), src_fps=TALK_FPS, src_frames=frames,
                           clip_id=rec.get("id"))
        elif idx in reacting:
            rec, waiting = _react_record(rv, idx)
            if rec:
                row.update(source="reaction", label="reaction shot (approved)", asset_id=rec.get("asset_id"),
                           trim_start_frames=0, src_fps=int(rec.get("fps") or FPS), src_frames=int(rec.get("frames") or 0),
                           clip_id=rec.get("id"))
        if row["source"] == "missing" and s.get("approved") and s.get("chosen"):
            row.update(source="still", label=STILL_LABEL, asset_id=s["chosen"])
            if waiting:
                row["warnings"].append("a clip is waiting for your approval: the still is used until you approve it")
        if row["source"] in ("talking", "reaction") and row["src_frames"]:
            fit = fit_clip(row["src_frames"], row["src_fps"], row["trim_start_frames"], n)
            row["stretch"] = fit["stretch"]
            row["warnings"] += fit["warnings"]
        if row["source"] == "missing":
            row["label"] = "no approved still or clip"
            row["warnings"].append("approve this shot's still or clip first")
            missing.append(idx)
        rows.append(row)
    total = sum(r["frames"] for r in rows)
    return {"rows": rows, "size": [w, h], "fps": FPS, "end": round(end, 3), "frames": total,
            "seconds": round(total / FPS, 3), "missing": missing, "hash": sources_hash(rows)}


def dialogue_lines(ep: Episode) -> list[dict]:
    """The recording's lines as the viewer sees them: [{start, end, text}] (performance tags and emoji removed)."""
    from .engine import viewer_text
    out = []
    for ln in (ep.audio_transcript or {}).get("lines") or []:
        try:
            a, b = float(ln.get("start")), float(ln.get("end"))
        except (TypeError, ValueError):
            continue
        text = viewer_text(str(ln.get("text") or "")).strip()
        if text and b > a:
            out.append({"start": round(a, 3), "end": round(b, 3), "text": text})
    return out


def presentation(db: Session, ep: Episode) -> dict:
    """{mode: bubbles | none | captions, hook: banner text or "", band: bool} from the episode's settings."""
    from .acting import episode_hook
    from .engine import hook_text
    mode = ep.dialogue_display or "bubbles"
    try:
        hook = hook_text(episode_hook(db, ep) or "")
    except Exception:   # noqa: BLE001 -- no script: no banner text from it
        hook = ""
    return {"mode": mode if mode in ("bubbles", "captions") else "none", "hook": hook,
            "band": (getattr(ep, "layout", None) or "full") == "band"}


# ================================================================== view
def view(db: Session, ep: Episode) -> dict:
    from .config import get_settings
    p = plan_rows(db, ep)
    v = stored(db, ep.id)
    ids = [r["asset_id"] for r in p["rows"] if r["asset_id"]] + [c.get("asset_id") for c in v.get("cuts") or []]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_([i for i in ids if i]))} if ids else {}
    for r in p["rows"]:
        a = assets.get(r["asset_id"])
        r["url"] = storage().url(a.storage_key) if a else None
    cuts = []
    for c in v.get("cuts") or []:
        a = assets.get(c.get("asset_id"))
        cuts.append({**c, "url": storage().url(a.storage_key) if a else None,
                     "approved": v.get("approved") == c["id"], "current": c.get("hash") == p["hash"]})
    job = db.query(Job).filter_by(kind=JOB, episode_id=ep.id).order_by(Job.id.desc()).first()
    busy = db.query(Job).filter(Job.kind == JOB, Job.episode_id == ep.id, Job.status.in_(("queued", "running"))).first() is not None
    s = get_settings()
    return {**p, "presentation": presentation(db, ep), "cuts": cuts, "approved": v.get("approved"),
            "approved_by": v.get("approved_by"), "busy": busy, "job": S.job(job) if job else None,
            "ffmpeg": bool(s.ffmpeg), "node": bool(s.node_bin and shutil.which(s.node_bin)),
            "cost": {"label": "Free (made on the studio server with FFmpeg)"}}


def summary(db: Session, ep: Episode) -> dict:
    vw = view(db, ep)
    rows = vw["rows"]
    stills = sum(1 for r in rows if r["source"] == "still")
    status = ("running" if vw["busy"] else "done" if vw["approved"] and any(c["approved"] and c["current"] for c in vw["cuts"])
              else "needs_approval" if vw["cuts"] else "not_started")
    detail = (f"{len(rows) - len(vw['missing'])} of {len(rows)} shots ready" + (f" ({stills} as stills, not animated)" if stills else "")
              if rows else "no storyboard yet")
    if vw["cuts"] and not vw["approved"]:
        detail += "; the final cut waits for your approval"
    return {"status": status, "cost": vw["cost"], "detail": detail}


# ================================================================== routes
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


@router.get("/episodes/{eid}/assembly")
def get_assembly(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


def start(db: Session, ep: Episode, user: str) -> dict:
    """Free: queue the assembly. Refused while a shot has no approved still or clip, without FFmpeg, or while one runs."""
    from .config import get_settings
    if not get_settings().ffmpeg:
        raise HTTPException(409, "FFmpeg is not configured on the studio server (FFMPEG), so the episode cannot be put together")
    p = plan_rows(db, ep)
    if not p["rows"]:
        raise HTTPException(409, "make the storyboard first: there are no shots to put together")
    if p["missing"]:
        raise HTTPException(409, "approve a still or a clip for shot(s) " + ", ".join(map(str, p["missing"])) + " first")
    if not ep.audio_asset_id:
        raise HTTPException(409, "the episode has no voice recording to put the shots on")
    if db.query(Job).filter(Job.kind == JOB, Job.episode_id == ep.id, Job.status.in_(("queued", "running"))).first():
        raise HTTPException(409, "the episode is already being put together")
    job = enqueue(db, JOB, episode_id=ep.id, payload={"by": user, "hash": p["hash"]})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Assembly asked by {user} ({len(p['rows'])} shots, free)"))
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/assembly")
def assemble(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return start(db, _episode(db, eid), user)


class ApproveIn(BaseModel):
    cut_id: str | None = Field(default=None, max_length=20)


@router.post("/episodes/{eid}/assembly/approve")
def approve(eid: int, body: ApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: this cut is the episode (null withdraws the approval)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.cut_id is not None and not any(c["id"] == body.cut_id for c in v.get("cuts") or []):
        raise HTTPException(404, "no such cut")
    v["approved"], v["approved_by"] = body.cut_id, (user if body.cut_id else None)
    save(db, eid, v)
    db.add(Event(episode_id=eid, kind="approval", message=(f"Final cut approved by {user}" if body.cut_id
                                                           else f"Final cut: approval withdrawn by {user}")))
    db.commit()
    return view(db, ep)


# ================================================================== the job
from .tasks import Ctx, task  # noqa: E402

OVERLAY_SCRIPT = "production/animation/overlay.mjs"


def probe_frames(ffprobe: str, path: Path) -> int | None:
    """The number of video frames in a file (counted packets), or None."""
    if not ffprobe:
        return None
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets,r_frame_rate", "-of", "json", str(path)], capture_output=True, text=True,
                       timeout=120, stdin=subprocess.DEVNULL)
    try:
        st = json.loads(r.stdout)["streams"][0]
        return int(st["nb_read_packets"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def render_overlays(db: Session, ep: Episode, size: tuple[int, int], folder: Path, log, lines: list[dict] | None = None,
                    mode: str | None = None, hook: str | None = None) -> dict:
    """{banner: Path | None, lines: [(start, end, Path)], warning: str}: the banner and line pictures from overlay.mjs.
    `lines` ([{start, end, text}]), `mode` and `hook` replace the episode's own (the cinematic captions)."""
    from . import acting
    from .config import REPO_ROOT, get_settings
    from . import engine
    if lines is not None:
        pr = {"mode": mode or "captions", "hook": hook or "", "band": False}
    else:
        pr = presentation(db, ep)
        lines = dialogue_lines(ep) if pr["mode"] != "none" else []
    if not pr["hook"] and not lines:
        return {"banner": None, "lines": [], "warning": ""}
    s = get_settings()
    node = shutil.which(s.node_bin) if s.node_bin else None
    if not node:
        return {"banner": None, "lines": [], "warning": "Node is not available on the server: the banner and the dialogue are left out"}
    w, h = size
    spec = {"width": w, "height": h, "hook": pr["hook"], "band": pr["band"], "mode": pr["mode"],
            "banner_font": str(acting.FONTS / "Anton-Regular.ttf"), "emoji_font": str(acting.FONTS / "NotoColorEmoji-Regular.ttf"),
            "font": str(REPO_ROOT / "skills/directing-stickman-videos/assets/fonts/NotoSans.ttf"),
            "lines": [{"text": ln["text"]} for ln in lines], "out": str(folder / "overlays")}
    f = folder / "overlay.json"
    f.write_text(json.dumps(spec))
    r = subprocess.run([node, str(REPO_ROOT / OVERLAY_SCRIPT), str(f)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(REPO_ROOT), env=engine.env_for_node(), timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        log("overlay pictures failed: " + (r.stderr or r.stdout)[-300:])
        return {"banner": None, "lines": [], "warning": "the banner and dialogue pictures could not be drawn: they are left out"}
    rep = json.loads(r.stdout.strip().splitlines()[-1])
    pics = rep.get("lines") or []
    return {"banner": Path(rep["banner"]) if rep.get("banner") else None,
            "lines": [(ln["start"], ln["end"] + 0.25, Path(p)) for ln, p in zip(lines, pics) if p], "warning": ""}


def _run(cmd: list[str], what: str, timeout: int = 1800) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg could not {what}: {(r.stderr or r.stdout or '')[-400:]}")


@task
def episode_assembly(ctx: Ctx) -> dict:
    from .config import get_settings
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    s = get_settings()
    ff = s.ffmpeg
    if not ff:
        raise RuntimeError("FFmpeg is not configured on this server (FFMPEG)")
    folder = ctx.folder("episodes", ep.id, f"assembly-job{job.id}")
    rec = db.get(Asset, ep.audio_asset_id) if ep.audio_asset_id else None
    if rec is None:
        raise ValueError("the episode has no voice recording")
    audio = storage().get_to_file(rec.storage_key, folder / ("recording" + (Path(rec.storage_key).suffix or ".m4a")))
    from . import media
    try:
        secs = media.probe(audio).get("duration")
    except media.MediaError:
        secs = None
    if secs:
        v = stored(db, ep.id)
        v["recording"] = {"asset_id": ep.audio_asset_id, "seconds": round(float(secs), 3)}
        save(db, ep.id, v)
        db.commit()
    p = plan_rows(db, ep)
    if p["missing"]:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError("shot(s) " + ", ".join(map(str, p["missing"])) + " have no approved still or clip any more")
    w, h = p["size"]
    try:
        listing = []
        for r in p["rows"]:
            a = db.get(Asset, r["asset_id"])
            if a is None:
                raise ValueError(f"shot {r['index']}: its approved picture or clip is missing from storage")
            src = storage().get_to_file(a.storage_key, folder / f"src{r['index']:03d}{Path(a.storage_key).suffix or '.bin'}")
            if r["source"] != "still":
                real = probe_frames(s.ffprobe, src)
                if real and real != r["src_frames"]:            # the file decides, not the record
                    r["src_frames"] = real
                    fit = fit_clip(real, r["src_fps"], r["trim_start_frames"], r["frames"])
                    r["stretch"] = fit["stretch"]
                    r["warnings"] = [x for x in r["warnings"] if not x.startswith("the clip")] + fit["warnings"]
            seg = folder / f"seg{r['index']:03d}.mp4"
            ctx.log(f"shot {r['index']}: {r['label']}, {r['frames']} frames")
            _run(segment_command(ff, r, src, seg, w, h), f"make shot {r['index']}")
            listing.append(f"file '{seg.resolve().as_posix()}'")
        (folder / "list.txt").write_text("\n".join(listing) + "\n")
        ov = render_overlays(db, ep, (w, h), folder, ctx.log)
        total = p["frames"] / FPS
        cmd = [ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(folder / "list.txt"), "-i", str(audio)]
        pics = ([ov["banner"]] if ov["banner"] else []) + [x[2] for x in ov["lines"]]
        for pic in pics:
            cmd += ["-i", str(pic)]
        if pics:
            graph, last = overlay_graph([(a_, b_) for a_, b_, _ in ov["lines"]], bool(ov["banner"]))
            cmd += ["-filter_complex", graph, "-map", f"[{last}]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-r", str(FPS)]
        else:
            cmd += ["-map", "0:v", "-c:v", "copy"]
        out = folder / "final.mp4"
        cmd += ["-map", "1:a", "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        ctx.log(f"joining {len(p['rows'])} shots ({p['frames']} frames, {total:.2f} s) over the recording")
        _run(cmd, "join the shots")
        cid = uuid.uuid4().hex[:8]
        vk = f"episodes/{ep.id}/assembly/final-{cid}.mp4"
        storage().put_file(vk, out, "video/mp4")
        asset = Asset(episode_id=ep.id, job_id=job.id, kind="video", label="Final cut (waiting for your approval)",
                      storage_key=vk, content_type="video/mp4", size=out.stat().st_size, sha256=sha256_file(out))
        db.add(asset)
        db.flush()
        warnings = ([ov["warning"]] if ov["warning"] else [])
        cut = {"id": cid, "asset_id": asset.id, "at": time.time(), "by": (job.payload or {}).get("by"), "job_id": job.id,
               "frames": p["frames"], "seconds": round(total, 3), "size": [w, h], "hash": p["hash"],
               "stills": sum(1 for r in p["rows"] if r["source"] == "still"), "warnings": warnings,
               "rows": [{k: r[k] for k in ("index", "start", "seconds", "frames", "source", "label", "stretch", "warnings")}
                        for r in p["rows"]],
               "presentation": presentation(db, ep)}
        db.commit()
        db.expire_all()
        v = stored(db, ep.id)
        v["cuts"] = ([cut] + (v.get("cuts") or []))[:10]
        save(db, ep.id, v)
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Final cut made: {len(p['rows'])} shots, {total:.1f} s (not approved)"))
        db.commit()
        return {"cut": cid, "frames": p["frames"], "seconds": round(total, 3), "usd": 0.0}
    finally:
        shutil.rmtree(folder, ignore_errors=True)
