"""Audio-first Stage 3 (owner decision 2026-11-20): producing an audio episode against its ORIGINAL recording.

  * `audio_slice` (replaces `scene_voice` for audio episodes): each recorded line's span [start, end) is cut from the
    episode's audio as a WAV, only to drive lip sync (Rhubarb, guided by the line's text). No voice is generated.
  * absolute timeline (acting.render): every line plays at its recorded start and end; no beats, gaps, tail or end
    card are added, so the video lasts exactly as long as the audio.
  * the original audio passes through unchanged: it is muxed into the MP4 as it is (stream copy when it is already
    AAC; otherwise encoded once, with no filter, gain or mix).
  * QA (the render fails when a check fails): the video's length equals the audio's (within one frame), and the first
    mouth movement starts within +/-80 ms of the first recorded word.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import get_settings
from .models import Asset, Episode, StoryboardScene

CUE_TOLERANCE = 0.08        # s: first mouth cue vs first recorded word
SLICE_RATE = 16000          # Hz: lip-sync slices (Rhubarb works on speech bands; the final audio is the original)


# ------------------------------------------------------------------ pure
def line_window(ln: dict) -> tuple[float, float]:
    """A recorded line's place on the absolute timeline."""
    return round(float(ln["start"]), 3), round(float(ln["end"]), 3)


def first_mouth_cue(lines: list[dict]) -> float | None:
    """Absolute time of the first mouth shape that is not rest (X), over spec lines {start, cues: [{start, value}]}."""
    best = None
    for ln in lines:
        for c in ln.get("cues") or []:
            if c.get("value") != "X":
                t = round(float(ln["start"]) + float(c["start"]), 3)
                best = t if best is None or t < best else best
                break
    return best


def qa(video_seconds: float, audio_seconds: float, fps: int, first_cue: float | None, first_word: float | None,
       tolerance: float = CUE_TOLERANCE) -> dict:
    """The audio episode's render checks. Video length must match the audio within one frame; the first mouth cue
    must fall within `tolerance` of the first recorded word."""
    frame = 1.0 / fps
    length_ok = abs(video_seconds - audio_seconds) <= frame + 1e-6
    checks = [{"check": "video length equals audio length", "video_seconds": round(video_seconds, 3),
               "audio_seconds": round(audio_seconds, 3), "tolerance": round(frame, 4), "pass": length_ok}]
    if first_cue is None or first_word is None:
        checks.append({"check": "first mouth cue within 80 ms of the first word", "pass": False,
                       "detail": "no mouth cue" if first_cue is None else "no word timing"})
    else:
        off = round(first_cue - first_word, 3)
        checks.append({"check": "first mouth cue within 80 ms of the first word", "first_cue": first_cue,
                       "first_word": first_word, "offset": off, "tolerance": tolerance, "pass": abs(off) <= tolerance + 1e-9})
    return {"pass": all(c["pass"] for c in checks), "checks": checks}


def qa_message(report: dict) -> str:
    bad = [c for c in report["checks"] if not c["pass"]]
    return "; ".join(f"{c['check']}: " + (f"video {c['video_seconds']} s vs audio {c['audio_seconds']} s" if "video_seconds" in c
                                          else c.get("detail") or f"offset {c['offset'] * 1000:.0f} ms") for c in bad)


# ------------------------------------------------------------------ media
def _ff() -> str:
    s = get_settings()
    if not s.ffmpeg:
        raise RuntimeError("FFmpeg is not configured (FFMPEG): audio episodes cannot be produced")
    return s.ffmpeg


def probe(path: Path, stream: str | None = None) -> dict:
    """{"duration": s, "codec": name} of the file (or of its first audio/video stream)."""
    s = get_settings()
    if not s.ffprobe:
        raise RuntimeError("FFprobe is not configured (FFPROBE)")
    sel = ["-select_streams", f"{stream}:0", "-show_entries", "stream=codec_name,duration"] if stream else ["-show_entries", "format=duration"]
    r = subprocess.run([s.ffprobe, "-v", "error", *sel, "-of", "json", str(path)], capture_output=True, text=True, timeout=120)
    info = json.loads(r.stdout or "{}")
    src = (info.get("streams") or [{}])[0] if stream else info.get("format") or {}
    try:
        dur = float(src.get("duration"))
    except (TypeError, ValueError):
        dur = None
    return {"duration": dur, "codec": src.get("codec_name")}


def source_audio(db, ep: Episode, folder: Path) -> tuple[Path, float]:
    """The episode's recording on local disk and how long the episode runs: the whole recording, or up to the
    owner's chosen end (a cut-off last line removed in Stage 1c)."""
    from .storage import storage
    a = db.get(Asset, ep.audio_asset_id) if ep.audio_asset_id else None
    if a is None:
        raise RuntimeError("the episode has no audio")
    local = storage().get_to_file(a.storage_key, folder / Path(a.storage_key).name)
    dur = probe(local)["duration"]
    if dur is None:
        raise RuntimeError("the length of the recording could not be read")
    end_at = (ep.audio_transcript or {}).get("end_at")
    return local, round(min(dur, float(end_at)) if end_at else dur, 3)


def cut(src: Path, dst: Path, start: float, end: float) -> Path:
    r = subprocess.run([_ff(), "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src), "-vn",
                        "-ac", "1", "-ar", str(SLICE_RATE), "-c:a", "pcm_s16le", str(dst)],
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"could not cut {start:.2f}-{end:.2f} s from the recording: {r.stderr[-300:]}")
    return dst


def mux_original(video: Path, audio: Path, seconds: float, out: Path) -> Path:
    """The silent render + the ORIGINAL recording: copied as it is when it is AAC, else encoded once (no filters)."""
    codec = probe(audio, "a")["codec"]
    a_args = ["-c:a", "copy"] if codec == "aac" else ["-c:a", "aac", "-b:a", "256k"]
    r = subprocess.run([_ff(), "-v", "error", "-y", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", *a_args, "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(out)],
                       capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"could not add the recording to the video: {r.stderr[-300:]}")
    return out


def as_wav(audio: Path, seconds: float, out: Path) -> Path:
    """The recording as WAV (for the "Final audio" asset), decoded once, nothing else changed."""
    subprocess.run([_ff(), "-v", "error", "-y", "-i", str(audio), "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(out)],
                   check=True, capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    return out


# ------------------------------------------------------------------ the job
from .tasks import Ctx, scene_hash, store_asset, task  # noqa: E402


@task
def audio_slice(ctx: Ctx) -> dict:
    """Per recorded line of the scene, its span of the original recording (for lip sync only)."""
    db, job = ctx.db, ctx.job
    ep, sc = db.get(Episode, job.episode_id), db.get(StoryboardScene, job.scene_id)
    folder = ctx.folder("episodes", ep.id, f"r{ep.revision}", f"scene-{sc.position}", "slices")
    src, total = source_audio(db, ep, folder)
    clips = []
    for i, ln in enumerate(sc.lines):
        if not ln.get("line_id"):
            raise RuntimeError(f"scene {sc.position} line {i + 1} is not a recorded line")
        start, end = line_window(ln)
        end = min(end, total)
        if end <= start:
            raise RuntimeError(f"scene {sc.position} line {i + 1} lies after the end of the episode's audio")
        f = cut(src, folder / f"line-{i + 1}.wav", start, end)
        key = f"episodes/{ep.id}/r{ep.revision}/scenes/{sc.position}/recorded/{ln['line_id']}-job{job.id}.wav"
        a = store_asset(db, ep_id=ep.id, src=f, key=key, kind="voice", label=f"Scene {sc.position} {ln['line_id']} (recording)",
                        content_type="audio/wav", scene_id=sc.id, job_id=job.id, revision=ep.revision)
        clips.append({"line": i, "asset_id": a.id, "seconds": round(end - start, 3), "text": ln["text"], "speaker": ln["speaker"],
                      "line_id": ln["line_id"], "start": start, "end": end, "recorded": True})
        ctx.log(f"{ln['line_id']}: {start:.2f}-{end:.2f} s from the recording")
    db.commit()
    return {"clips": clips, "scene_hash": scene_hash(sc), "source": "recording"}
