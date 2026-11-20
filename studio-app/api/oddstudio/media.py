"""Audio-first Stage 1b: media helpers around FFmpeg / FFprobe (owner decision 2026-11-20).

The owner may upload any audio OR video file. A video is only ever a carrier for its audio track: the audio is extracted
and the picture is never reused (no frame of it reaches an episode). Optionally, a handful of small frames are sampled
for casting and setting hints (people count, setting, mood only) and deleted as soon as the hints are made.

Everything here is a plain function on local files, so the API and the worker share it and the tests drive it directly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .config import get_settings

MIN_FREE_BYTES = 1024 ** 3          # always leave 1 GB free on the work disk after an upload and its extraction
FRAME_COUNT = 6                     # frames sampled for the hints (small JPEGs, deleted after use)
FRAME_WIDTH = 512


class MediaError(ValueError):
    """The file cannot be used (unreadable, no audio track, ...): the message is shown to the owner."""


class MediaToolMissing(RuntimeError):
    """FFmpeg / FFprobe are not configured (FFMPEG / FFPROBE)."""


def _ffmpeg() -> str:
    s = get_settings()
    if not s.ffmpeg:
        raise MediaToolMissing("FFmpeg is not configured on this server (FFMPEG), so video files cannot be read")
    return s.ffmpeg


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def free_bytes(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(folder).free


def check_free_space(folder: Path, incoming: int) -> None:
    """Refuse an upload unless the disk can hold it twice (the file plus its extracted audio) and still keep
    MIN_FREE_BYTES free. `incoming` is the declared size, or the cap when the client did not declare one."""
    need = 2 * incoming + MIN_FREE_BYTES
    free = free_bytes(folder)
    if free < need:
        raise OSError(f"not enough free disk space for this upload ({free / 1024 ** 3:.1f} GB free, "
                      f"{need / 1024 ** 3:.1f} GB needed); free some space or upload a smaller file")


def probe(path: Path) -> dict:
    """{"duration": seconds | None, "audio": bool, "video": bool} via FFprobe. Without FFprobe (tests without FFmpeg)
    the duration is unknown and the streams are not checked."""
    s = get_settings()
    if not s.ffprobe:
        return {"duration": None, "audio": True, "video": None}
    r = _run([s.ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)], 120)
    try:
        info = json.loads(r.stdout or "{}")
    except ValueError:
        info = {}
    streams = {st.get("codec_type") for st in info.get("streams") or []}
    try:
        duration = float((info.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    if r.returncode != 0 or (not streams and duration is None):
        raise MediaError("not a readable audio or video file")
    # an image (a cover picture) inside an audio file is a "video" stream of one frame: only real durations count
    return {"duration": duration, "audio": "audio" in streams, "video": "video" in streams}


def extract_audio(src: Path, dst: Path) -> Path:
    """The first audio track of a video as AAC (.m4a). The picture is dropped (-vn): it is never stored."""
    dst = dst.with_suffix(".m4a")
    r = _run([_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-vn", "-sn", "-dn",
              "-c:a", "aac", "-b:a", "192k", str(dst)])
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        dst.unlink(missing_ok=True)
        raise MediaError("the audio track could not be read from this video" + (f": {r.stderr.strip()[-200:]}" if r.stderr else ""))
    return dst


def cut_audio(src: Path, dst: Path, start: float, end: float) -> Path:
    """The window [start, end) of an audio file as 48 kHz 16-bit WAV (decoded once, no second lossy encode)."""
    dst = dst.with_suffix(".wav")
    r = _run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
              "-vn", "-ar", "48000", "-c:a", "pcm_s16le", str(dst)])
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        dst.unlink(missing_ok=True)
        raise MediaError("the audio could not be trimmed" + (f": {r.stderr.strip()[-200:]}" if r.stderr else ""))
    return dst


def sample_frames(src: Path, folder: Path, duration: float | None, count: int = FRAME_COUNT) -> list[Path]:
    """`count` small JPEG frames spread over the video (for the hints only; the caller deletes the folder)."""
    folder.mkdir(parents=True, exist_ok=True)
    d = duration or 1.0
    out = []
    for k in range(count):
        t = d * (k + 0.5) / count
        f = folder / f"frame-{k + 1}.jpg"
        r = _run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                  "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "5", str(f)], 120)
        if r.returncode == 0 and f.exists() and f.stat().st_size:
            out.append(f)
    return out
