"""Audio-first episodes, stage 1: the owner uploads an audio file and the studio builds the episode AROUND it.

The uploaded audio is the voice track: no voice provider is used for these lines. Stage 1 covers:

  1. create   POST /api/audio-episodes             the rights confirmation and its source label are REQUIRED
                                                     (append-only Review record "audio_rights")
  2. upload   PUT  /api/episodes/{id}/audio         raw request body (audio/* or video/*), owner upload only: nothing
                                                     here downloads media from other sites. Stage 1b: a video is only a
                                                     carrier: job `audio_media_prepare`
                                                     extracts its audio track and deletes the original (the picture is
                                                     never reused); with ?hints=1 a few frames of the part the episode
                                                     uses become TEXT-ONLY staging notes (job `audio_video_notes`,
                                                     video_notes.py) and are deleted right after.
     trim     POST /api/episodes/{id}/audio/trim    Shorts only: the 60 s window of a longer recording
  3. transcribe (worker job `audio_transcribe`)    the selected transcription provider (word timestamps), split into
                                                     timed lines (pauses, sentence ends, maximum length)
  4. label    PUT  /api/episodes/{id}/audio/lines   a speaker per line; edit, split or merge lines (validated here)
  5. cast     POST /api/episodes/{id}/audio/suggest-cast   the AI writer proposes the cast and voice styles (job
                                                     `audio_cast_suggest`), stored as a suggestion only
              POST /api/episodes/{id}/audio/cast    map each speaker to an existing character or create a new
                                                     episode character; the lines then carry character keys

Stages: audio_upload -> (audio_preparing: video only) -> audio_transcribing -> audio_labelling. Building scenes around the timed lines and playing the
uploaded clips in production are later stages (separate changes, owner-approved).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .config import get_settings
from .db import get_db
from .models import Asset, Character, Episode, Event, Review
from .queue import enqueue
from .workflow import GateError, require, set_stage
from . import line_normaliser as LN
from . import media

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

RIGHTS_SOURCES = ("own_recording", "licensed", "voice_actor", "other")
RIGHTS_LABEL = {"own_recording": "own recording", "licensed": "licensed", "voice_actor": "voice actor", "other": "other"}
MAX_BYTES = 60 * 1024 * 1024                        # an audio file
MAX_VIDEO_BYTES = 250 * 1024 * 1024                 # a video file (owner decision 2026-11-20)
MAX_SECONDS = {"short": 60, "long": 450}            # the formats' caps (a Short runs at most 60 s; long at most 7½ min)
MAX_SOURCE_SECONDS = 1800                           # a Short's recording may be longer (the owner picks a 60 s window)
VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/x-matroska": ".mkv",
               "video/x-m4v": ".m4v"}
# Upload facts that survive a (re)transcription: where the audio came from, the video hints, the chosen Short window.
# the Reference plan is kept too: its acceptance is checked against the notes, so a change still asks again
KEEP_KEYS = ("source_media", "media_hints", "trim", "video_notes", "reference_plan", "person_map")
RIGHTS_TEXT = "I have the right to use this recording: its audio and any video it came with."
AUDIO_TYPES = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
               "audio/vnd.wave": ".wav", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a", "audio/aac": ".aac",
               "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/flac": ".flac", "audio/x-flac": ".flac"}
KEY = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
PAUSE, MAX_LINE_SECONDS, MAX_LINE_WORDS = 0.6, 8.0, 24
MAX_LINES = 500


def gate(ep: Episode, action: str) -> None:
    try:
        require(ep, action)
    except GateError as e:
        raise HTTPException(409, str(e))


def audio_episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    if ep.source != "audio":
        raise HTTPException(409, "this episode was not created from audio")
    if not ep.audio_rights_confirmed:
        raise HTTPException(409, "the right to use this audio has not been confirmed")
    return ep


# ------------------------------------------------------------------ line splitting
def _join(words: list[str]) -> str:
    text = " ".join(w.strip() for w in words if w.strip())
    return re.sub(r"\s+([,.!?;:…])", r"\1", text).strip()


def split_lines(tr: dict, pause: float = PAUSE, max_seconds: float = MAX_LINE_SECONDS, max_words: int = MAX_LINE_WORDS) -> list[dict]:
    """Timed lines from a transcription. With word timestamps a line ends at a pause, at the end of a sentence, or when
    it would run longer than `max_seconds` / `max_words`. Without words, each transcription segment is one line.
    Speakers are not known yet (transcription providers do not identify them): every line starts unlabelled."""
    words = [w for w in (tr.get("words") or []) if str(w.get("word", "")).strip()]
    groups: list[list[dict]] = []
    if words:
        cur: list[dict] = []
        for w in words:
            if cur:
                gap = float(w["start"]) - float(cur[-1]["end"])
                ends_sentence = re.search(r"[.!?…][\"')\]]*$", str(cur[-1]["word"]).strip())
                too_long = float(w["end"]) - float(cur[0]["start"]) > max_seconds or len(cur) >= max_words
                if gap >= pause or ends_sentence or too_long:
                    groups.append(cur)
                    cur = []
            cur.append(w)
        if cur:
            groups.append(cur)
        lines = [{"start": float(g[0]["start"]), "end": float(g[-1]["end"]), "text": _join([str(x["word"]) for x in g]),
                  "words": [{"start": round(float(x["start"]), 3), "end": round(float(x["end"]), 3), "word": str(x["word"]).strip()} for x in g]}
                 for g in groups]
    else:
        lines = [{"start": float(s["start"]), "end": float(s["end"]), "text": str(s.get("text", "")).strip(), "words": []}
                 for s in (tr.get("segments") or []) if str(s.get("text", "")).strip()]
    out = []
    for i, ln in enumerate(lines):
        start = round(ln["start"], 3)
        end = round(max(ln["end"], ln["start"] + 0.05), 3)
        out.append({"id": f"l{i + 1}", "start": start, "end": end, "text": ln["text"], "speaker": "", "words": ln["words"]})
    return out


def speakers_of(lines: list[dict]) -> list[str]:
    return list(dict.fromkeys(ln["speaker"] for ln in lines if ln.get("speaker")))


def audio_seconds_of(path: Path) -> float | None:
    """Duration via FFprobe (None when FFprobe is not configured, e.g. in tests). Raises ValueError if unreadable."""
    s = get_settings()
    if not s.ffprobe:
        return None
    r = subprocess.run([s.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise ValueError("not a readable audio file") from None


# ------------------------------------------------------------------ state
def state(db: Session, ep: Episode) -> dict:
    tr = ep.audio_transcript or {}
    lines = tr.get("lines", [])
    keys = {c.key: c for c in db.query(Character).all()}
    sp = speakers_of(lines)
    return {**S.episode_summary(ep), "last_error": ep.last_error or "",
            "audio": S.asset(db.get(Asset, ep.audio_asset_id)) if ep.audio_asset_id else None,
            "rights": {"confirmed": bool(ep.audio_rights_confirmed), "source": ep.audio_rights_source,
                       "label": RIGHTS_LABEL.get(ep.audio_rights_source, "")},
            "transcript": ({k: v for k, v in tr.items() if k not in ("lines", "cast_suggestion", *KEEP_KEYS)}
                           if tr.get("lines") is not None else None),
            # Stage 1b: the uploaded media (an extracted video's audio), the Short's 60 s window, the video hints
            "source_media": tr.get("source_media"), "trim": tr.get("trim"), "media_hints": tr.get("media_hints"),
            # "reference, not copy": text-only staging notes from the video, aligned to the recorded lines
            "video_notes": _notes_view(tr),
            "needs_trim": bool((tr.get("source_media") or {}).get("needs_trim")),
            "window_seconds": MAX_SECONDS["short"] if ep.format == "short" else None,
            "full_audio": _full_audio(db, ep),
            "limits": {"audio_mb": MAX_BYTES // 1048576, "video_mb": MAX_VIDEO_BYTES // 1048576,
                       "max_seconds": MAX_SECONDS[ep.format], "max_source_seconds": MAX_SOURCE_SECONDS if ep.format == "short" else MAX_SECONDS["long"]},
            "lines": lines, "speakers": sp,
            "unlabelled_lines": sum(1 for ln in lines if not ln.get("speaker")),
            "speakers_without_character": [s for s in sp if s not in keys],
            "cast_suggestion": tr.get("cast_suggestion"),
            # Casting hints (A): pitch/pace/energy measured from the audio per speaker (owner-editable suggestions; gender
            # and age are never inferred), and silent characters (named in the transcript, never speaking)
            "voice_traits": tr.get("voice_traits"), "silent_cast": tr.get("silent_cast", []),
            # Stage 1c: line quality (cue phrases, one-level Undo, a cut-off last line)
            "cues": tr.get("cues", LN.DEFAULT_CUES),
            "can_undo": bool(tr.get("lines_previous")),
            "end_at": tr.get("end_at"),
            "fragment": fragment_of(tr),
            "characters": [{"key": c.key, "name": c.name, "scope": c.scope, "voice_style": c.voice_style}
                           for c in sorted(keys.values(), key=lambda c: c.id)
                           if (c.scope == "recurring" or c.art_status == "approved" or c.episode_id == ep.id)
                           and c.id not in _binned_characters(db)]}


def _binned_characters(db: Session) -> set[int]:
    from .bin import hidden_ids
    return hidden_ids(db, "character")


def _notes_view(tr: dict) -> dict | None:
    from . import video_notes as VN
    notes = tr.get("video_notes")
    if not notes:
        return None
    # the per-person frames stay on the server (for the cast mapping); the view has the ranges and the quality readout
    return {**{k: v for k, v in notes.items() if k not in ("ranges", "people_frames")}, "ranges": VN.align(notes.get("ranges", []), tr.get("lines", []))}


def _full_audio(db: Session, ep: Episode) -> dict | None:
    """The whole recording (a Short's source before its 60 s window is chosen), for the trim player."""
    fid = ((ep.audio_transcript or {}).get("source_media") or {}).get("full_asset_id")
    a = db.get(Asset, fid) if fid else None
    return S.asset(a) if a else None


def fragment_of(tr: dict) -> dict | None:
    """The last line, if it looks cut off and the owner has not decided about it yet."""
    lines = tr.get("lines", [])
    if not lines or tr.get("end_at") is not None:
        return None
    frag = LN.trailing_fragment(lines, tr.get("text", ""), tr.get("duration"))
    ack = tr.get("fragment_ack") or {}
    if frag and ack.get("text") == frag["text"] and ack.get("end") == frag["end"]:
        return None   # the owner chose to keep this exact line
    return frag


def remember(tr: dict) -> None:
    """Keep the current lines (and audio end) so one click can undo the next change."""
    tr["lines_previous"] = {"lines": tr.get("lines", []), "end_at": tr.get("end_at")}


# ------------------------------------------------------------------ create + upload
class AudioEpisodeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    format: Literal["short", "long"] = "short"
    rights_confirmed: bool = False
    rights_source: Literal["own_recording", "licensed", "voice_actor", "other"] | None = None


@router.post("/audio-episodes", status_code=201)
def create_audio_episode(body: AudioEpisodeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    if not body.rights_confirmed:
        raise HTTPException(422, "Confirm that you have the right to use this audio before creating the episode")
    if not body.rights_source:
        raise HTTPException(422, "Choose where the audio comes from (own recording, licensed, voice actor or other)")
    # Stage 2 (owner): audio episodes start with no dialogue on screen (the recording carries it); changeable per episode
    ep = Episode(title=body.title, format=body.format, stage="audio_upload", source="audio", dialogue_display="none",
                 audio_rights_confirmed=True, audio_rights_source=body.rights_source)
    db.add(ep)
    db.flush()
    # append-only record of who confirmed the rights, and the stated source
    db.add(Review(episode_id=ep.id, gate="audio_rights", decision="confirmed", revision=ep.revision, target={},
                  comment=f"{RIGHTS_TEXT} Source: {RIGHTS_LABEL[body.rights_source]}", actor=user))
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio-first episode created (audio source: {RIGHTS_LABEL[body.rights_source]})"))
    db.commit()
    return state(db, ep)


def uploads_dir() -> Path:
    d = get_settings().work_dir / "uploads"     # temporary files only: never backed up, swept by maintenance after 24 h
    d.mkdir(parents=True, exist_ok=True)
    return d


def _in_uploads(name: str) -> Path:
    p = (uploads_dir() / Path(str(name)).name).resolve()
    if p.parent != uploads_dir().resolve():
        raise ValueError("not an upload file")
    return p


def accept_audio(db: Session, ep: Episode, path: Path, ctype: str, ext: str, seconds: float | None, source: dict) -> str:
    """Store a usable audio file for the episode (an upload, or the track extracted from a video) and move on:
    transcription, or (a Short longer than 60 s) waiting for the owner's 60 s window. Returns the event text.
    Raises HTTPException(422) when the recording is too long for the format."""
    from .storage import sha256_file
    from .tasks import store_asset
    window = MAX_SECONDS[ep.format]
    limit = MAX_SOURCE_SECONDS if ep.format == "short" else window
    if seconds is not None and seconds > limit + 0.5:
        raise HTTPException(422, f"the recording runs {seconds:.0f} s; a {ep.format} episode allows at most {limit} s"
                                 + (" (you then choose its 60 s window)" if ep.format == "short" else ""))
    needs_trim = ep.format == "short" and seconds is not None and seconds > window + 0.5
    key = f"episodes/{ep.id}/source-{'full-' if needs_trim else ''}audio-{sha256_file(path)[:12]}{ext}"
    a = store_asset(db, ep_id=ep.id, src=path, key=key, kind="source-audio-full" if needs_trim else "source-audio",
                    content_type=ctype, revision=ep.revision,
                    label=("Uploaded recording, before its 60 s window" if needs_trim else "Uploaded audio")
                          + (" (extracted from a video)" if source.get("type") == "video" else "")
                          + f" ({RIGHTS_LABEL.get(ep.audio_rights_source, '')})")
    sm = {**source, "full_asset_id": a.id, "duration": round(seconds, 3) if seconds else None, "needs_trim": needs_trim}
    ep.audio_transcript = {"source_media": sm}
    ep.last_error = ""
    what = "the audio of a video (the video file was deleted)" if source.get("type") == "video" else "audio"
    if needs_trim:
        ep.audio_asset_id = None
        set_stage(ep, "audio_upload")
        return f"Recording received: {what}, {seconds:.1f} s; choose its 60 s window for the Short"
    ep.audio_asset_id = a.id
    set_stage(ep, "audio_transcribing")
    return f"Recording received: {what}" + (f", {seconds:.1f} s" if seconds else "")


@router.put("/episodes/{eid}/audio")
async def upload_audio(eid: int, request: Request, hints: bool = False, start: float | None = None, end: float | None = None,
                       db: Session = Depends(get_db)):
    """The audio or video file is the raw request body (Content-Type audio/* or video/*), streamed to disk with a size
    cap after a free-space check. Audio is stored right away. A video is checked here (it must have an audio track) and
    handed to the worker (`audio_media_prepare`), which extracts the audio and deletes the video.
    `hints` (video only): text-only staging notes from frames of the part the episode uses (video_notes.py); a Short
    longer than 60 s then needs its window (`start`, `end`) with the upload, so only that part is analysed. The frames
    are deleted as soon as the notes are made."""
    ep = audio_episode(db, eid)
    gate(ep, "upload_audio")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    is_video = ctype in VIDEO_TYPES
    if ctype not in AUDIO_TYPES and not is_video:
        exts = sorted(set(AUDIO_TYPES.values()) | set(VIDEO_TYPES.values()))
        raise HTTPException(415, f"upload an audio or video file ({', '.join(exts)})")
    cap = MAX_VIDEO_BYTES if is_video else MAX_BYTES
    kind = "video" if is_video else "audio"
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > cap:
        raise HTTPException(413, f"the {kind} file is larger than {cap // 1048576} MB")
    try:
        media.check_free_space(uploads_dir(), declared or cap)
    except OSError as e:
        raise HTTPException(507, str(e))
    ext = (VIDEO_TYPES if is_video else AUDIO_TYPES)[ctype]
    tmp = uploads_dir() / f"{kind}-{ep.id}-{uuid.uuid4().hex[:8]}{ext}"
    size, keep_for_worker = 0, False
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > cap:
                    raise HTTPException(413, f"the {kind} file is larger than {cap // 1048576} MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, "the uploaded file is empty")
        try:
            info = media.probe(tmp)
        except media.MediaError as e:
            raise HTTPException(422, str(e))
        if not info["audio"]:
            raise HTTPException(422, f"this {kind} file has no audio track")
        if is_video:
            if not (get_settings().ffmpeg and get_settings().ffprobe):
                raise HTTPException(503, "FFmpeg and FFprobe are not configured on this server (FFMPEG, FFPROBE), so video files cannot be read")
            if hints:
                try:
                    hints_vision_config(db)
                except ValueError as e:
                    raise HTTPException(409, str(e))
            seconds = info["duration"]
            limit = MAX_SOURCE_SECONDS if ep.format == "short" else MAX_SECONDS[ep.format]
            if seconds is not None and seconds > limit + 0.5:
                raise HTTPException(422, f"the video runs {seconds:.0f} s; a {ep.format} episode allows at most {limit} s")
            window = None
            if start is not None or end is not None:
                if ep.format != "short":
                    raise HTTPException(422, "a window is for Shorts only (a long episode uses the whole recording)")
                if start is None or end is None:
                    raise HTTPException(422, "give the window's start and end")
                check_window(start, end, seconds)
                window = {"start": round(start, 3), "end": round(end, 3)}
            elif hints and ep.format == "short" and seconds is not None and seconds > MAX_SECONDS["short"] + 0.5:
                raise HTTPException(422, f"the video runs {seconds:.0f} s: choose the Short's 60 s window with the upload, "
                                         "so only that part of the video is analysed for the notes")
            if hints:
                # the notes' estimated cost must fit under the cap (Settings > Video and visual analysis)
                est = notes_estimate(db, (window["end"] - window["start"]) if window else float(seconds or 0), ep.format)
                if est.get("configured") and not est["within_cap"]:
                    raise HTTPException(409, f"the video notes would cost about ${est['usd']:.2f} ({est['frames']} frames), "
                                             f"over the ${est['cap_usd']:.2f} cap: use a shorter part of the video or raise "
                                             "the cap in Settings > Video and visual analysis")
            ep.audio_asset_id, ep.last_error = None, ""
            ep.audio_transcript = {"source_media": {"type": "video", "preparing": True, "hints_requested": bool(hints)}}
            set_stage(ep, "audio_preparing")
            db.add(Event(episode_id=ep.id, kind="episode", message=f"Video uploaded ({size / 1048576:.1f} MB): extracting its audio"
                                                                  + (" and sampling frames for the video notes" if hints else "")))
            db.commit()
            keep_for_worker = True
            enqueue(db, "audio_media_prepare", episode_id=ep.id, revision=ep.revision,
                    payload={"upload": tmp.name, "hints": bool(hints), "seconds": seconds, "window": window})
            return state(db, ep)
        if start is not None or end is not None:
            raise HTTPException(422, "for an audio file, choose the window after the upload (Audio tab)")
        msg = accept_audio(db, ep, tmp, ctype, ext, info["duration"], {"type": "audio"})
    finally:
        if not keep_for_worker:
            tmp.unlink(missing_ok=True)
    db.add(Event(episode_id=ep.id, kind="episode", message=f"{msg} ({size / 1048576:.1f} MB)"))
    db.commit()
    if ep.audio_asset_id:
        enqueue(db, "audio_transcribe", episode_id=ep.id, revision=ep.revision, payload={"asset_id": ep.audio_asset_id})
    return state(db, ep)


class TrimIn(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)


def check_window(start: float, end: float, duration: float | None) -> None:
    """A Short's window: at most 60 s, inside the recording (HTTPException 422 otherwise)."""
    window = MAX_SECONDS["short"]
    if end <= start:
        raise HTTPException(422, "the window must end after it starts")
    if end - start > window + 0.05:
        raise HTTPException(422, f"a Short's window is at most {window} s (this one is {end - start:.1f} s)")
    if duration and end > float(duration) + 0.05:
        raise HTTPException(422, f"the window ends after the recording ({float(duration):.1f} s)")


def apply_window(db: Session, ep: Episode, start: float, end: float) -> None:
    """Cut the window [start, end) from the whole recording as the episode's audio and transcribe it. Video notes move
    with the window (their times are the audio's); notes outside the new window are dropped."""
    from . import video_notes as VN
    tr = dict(ep.audio_transcript or {})
    sm = dict(tr.get("source_media") or {})
    full = db.get(Asset, sm.get("full_asset_id")) if sm.get("full_asset_id") else None
    if full is None:
        raise HTTPException(409, "upload the recording first")
    duration = sm.get("duration")
    check_window(start, end, duration)
    try:
        media.check_free_space(uploads_dir(), int(full.size or 0))
    except OSError as e:
        raise HTTPException(507, str(e))
    from .storage import sha256_file, storage
    from .tasks import store_asset
    src = uploads_dir() / f"trim-src-{ep.id}-{uuid.uuid4().hex[:8]}{Path(full.storage_key).suffix}"
    out = uploads_dir() / f"trim-{ep.id}-{uuid.uuid4().hex[:8]}.wav"
    try:
        storage().get_to_file(full.storage_key, src)
        try:
            out = media.cut_audio(src, out, start, min(end, float(duration) if duration else end))
        except media.MediaToolMissing as e:
            raise HTTPException(503, str(e))
        except media.MediaError as e:
            raise HTTPException(422, str(e))
        a = store_asset(db, ep_id=ep.id, src=out, key=f"episodes/{ep.id}/source-audio-{sha256_file(out)[:12]}.wav",
                        kind="source-audio", content_type="audio/wav", revision=ep.revision,
                        label=f"Short window {start:.1f}-{end:.1f} s ({RIGHTS_LABEL.get(ep.audio_rights_source, '')})")
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    sm["needs_trim"] = False
    notes = tr.get("video_notes")
    if notes:
        delta = float(notes.get("base", 0.0)) - start
        notes = {**notes, "ranges": VN.shift(notes.get("ranges", []), delta, end - start),
                 "base": round(start, 3), "length": round(end - start, 3)}
        if notes.get("original"):
            notes["original"] = VN.shift(notes["original"], delta, end - start)
        if notes.get("people_frames"):
            notes["people_frames"] = [{**f, "t": round(f["t"] + delta, 2)} for f in notes["people_frames"]
                                      if 0 <= f["t"] + delta <= end - start]
    ep.audio_transcript = {k: v for k, v in {**tr, "source_media": sm, "video_notes": notes,
                                             "trim": {"start": round(start, 3), "end": round(end, 3)}}.items()
                           if k in KEEP_KEYS and v is not None}
    ep.audio_asset_id, ep.last_error = a.id, ""
    set_stage(ep, "audio_transcribing")
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Short window chosen: {start:.1f}-{end:.1f} s; transcribing it"))
    db.commit()
    enqueue(db, "audio_transcribe", episode_id=ep.id, revision=ep.revision, payload={"asset_id": a.id})


@router.post("/episodes/{eid}/audio/trim")
def trim_audio(eid: int, body: TrimIn, db: Session = Depends(get_db)):
    """Shorts only: the episode uses the window [start, end) of the uploaded recording (at most 60 s). The whole
    recording is kept, so the window can be moved later; a new window is transcribed again (labels start over)."""
    ep = audio_episode(db, eid)
    gate(ep, "trim_audio")
    if ep.format != "short":
        raise HTTPException(422, "trimming is for Shorts only (a long episode uses the whole recording)")
    apply_window(db, ep, body.start, body.end)
    return state(db, ep)


class NotesIn(BaseModel):
    ranges: list[dict] = Field(default_factory=list, max_length=40)


@router.put("/episodes/{eid}/audio/video-notes")
def edit_video_notes(eid: int, body: NotesIn, db: Session = Depends(get_db)):
    """The owner's edit of the video notes (same schema as the model's; anything outside it is refused, not kept)."""
    from . import video_notes as VN
    ep = audio_episode(db, eid)
    gate(ep, "edit_video_notes")
    tr = dict(ep.audio_transcript or {})
    notes = tr.get("video_notes")
    if not notes:
        raise HTTPException(409, "this episode has no video notes")
    strip = [{k: v for k, v in r.items() if k != "line_ids"} for r in body.ranges]   # the view adds line ids
    ranges, redacted = VN.clean_notes({"ranges": strip}, float(notes.get("length") or 0) or 1e9)
    if redacted or len(ranges) != len(body.ranges):
        raise HTTPException(422, "the notes can only hold the listed values (shot, camera, setting, roles with position, "
                                 "pose, facing and emotion) and ranges inside the clip")
    # the unedited notes are kept (once) so the Reference plan can show what the vision model said and what you changed
    tr["video_notes"] = {**notes, "ranges": ranges, "edited": True, "original": notes.get("original") or notes.get("ranges", [])}
    tr["media_hints"] = {**(tr.get("media_hints") or {}), **VN.summary(ranges)}
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Video notes edited ({len(ranges)} range(s))"))
    db.commit()
    return state(db, ep)


@router.delete("/episodes/{eid}/audio/video-notes")
def clear_video_notes(eid: int, db: Session = Depends(get_db)):
    """Remove the video notes (and the hints derived from them); the scenes are then built without them."""
    ep = audio_episode(db, eid)
    gate(ep, "edit_video_notes")
    tr = dict(ep.audio_transcript or {})
    tr.pop("video_notes", None)
    if (tr.get("media_hints") or {}).get("from") == "video notes":
        tr.pop("media_hints", None)
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message="Video notes cleared"))
    db.commit()
    return state(db, ep)


def notes_estimate(db: Session, seconds: float, fmt: str) -> dict:
    """Frames, calls and estimated cost of the v2 notes for `seconds` of video, with the cap and whether it fits."""
    from . import notes_v2 as NV
    from .settings_store import get_section
    cap = NV.clamp_cap(get_section(db, "vision").get("notes_cap_usd"))
    seconds = max(0.0, min(seconds, MAX_SECONDS["long"]))
    try:
        cfg = hints_vision_config(db)
    except ValueError as e:
        return {"configured": False, "frames": len(NV.frame_times(0.0, seconds, fmt)), "cap_usd": cap, "message": str(e)}
    return NV.estimate(seconds, fmt, cfg["provider"], cfg.get("model", ""), cap)


@router.get("/audio/video-notes/estimate")
def video_notes_estimate(seconds: float, format: str = "short", db: Session = Depends(get_db)):
    """Before an upload: how many frames the notes would use for `seconds` of video, the calls, the estimated cost
    with the configured vision provider (list prices) and the episode cap."""
    return notes_estimate(db, seconds, "long" if format == "long" else "short")


@router.post("/episodes/{eid}/audio/transcribe")
def transcribe_again(eid: int, db: Session = Depends(get_db)):
    ep = audio_episode(db, eid)
    gate(ep, "transcribe_audio")
    if not ep.audio_asset_id:
        needs = ((ep.audio_transcript or {}).get("source_media") or {}).get("needs_trim")
        raise HTTPException(409, "choose the Short's 60 s window first" if needs else "upload the audio first")
    set_stage(ep, "audio_transcribing")
    ep.last_error = ""
    db.commit()
    enqueue(db, "audio_transcribe", episode_id=ep.id, revision=ep.revision, payload={"asset_id": ep.audio_asset_id})
    return state(db, ep)


@router.get("/episodes/{eid}/audio")
def audio_state(eid: int, db: Session = Depends(get_db)):
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    if ep.source != "audio":
        raise HTTPException(409, "this episode was not created from audio")
    return state(db, ep)


# ------------------------------------------------------------------ labelling
class WordIn(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    word: str = Field(max_length=100)


class LineIn(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=400)
    speaker: str = Field(default="", max_length=40)
    words: list[WordIn] = Field(default_factory=list, max_length=200)


class LinesIn(BaseModel):
    lines: list[LineIn] = Field(min_length=1, max_length=MAX_LINES)
    keep_previous: bool = False   # an applied proposal (normaliser): the lines before it can be restored with Undo


@router.put("/episodes/{eid}/audio/lines")
def save_lines(eid: int, body: LinesIn, db: Session = Depends(get_db)):
    """The owner's labelled lines (speakers; text fixes; split or merged lines). Timing must stay inside the audio, in
    order and without overlaps: the lines are later placed against the uploaded audio itself."""
    ep = audio_episode(db, eid)
    gate(ep, "label_audio")
    tr = dict(ep.audio_transcript or {})
    duration = tr.get("duration")
    lines, prev_end = [], 0.0
    for i, ln in enumerate(body.lines):
        if ln.end <= ln.start:
            raise HTTPException(422, f"line {i + 1}: it must end after it starts")
        if ln.start < prev_end - 0.01:
            raise HTTPException(422, f"line {i + 1}: it overlaps the line before it (lines must be in time order)")
        if duration and ln.end > float(duration) + 0.25:
            raise HTTPException(422, f"line {i + 1}: it ends after the audio ({float(duration):.2f} s)")
        if any(w.start < ln.start - 0.01 or w.end > ln.end + 0.01 for w in ln.words):
            raise HTTPException(422, f"line {i + 1}: a word lies outside the line's time")
        speaker = ln.speaker.strip()
        lines.append({"id": f"l{i + 1}", "start": round(ln.start, 3), "end": round(ln.end, 3), "text": ln.text.strip(),
                      "speaker": speaker, "words": [w.model_dump() for w in ln.words]})
        prev_end = ln.end
    if body.keep_previous:
        remember(tr)
    else:
        tr.pop("lines_previous", None)   # Undo restores the lines before the last applied proposal only while nothing
                                        # was edited since; an ordinary save makes the current lines the reference
    tr["lines"], tr["edited"] = lines, True
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio lines saved ({len(lines)} lines, "
                                                            f"{sum(1 for x in lines if not x['speaker'])} without a speaker)"))
    db.commit()
    return state(db, ep)


# ------------------------------------------------------------------ line quality (Stage 1c)
class NormaliseIn(BaseModel):
    cues: list[str] | None = Field(default=None, max_length=20)


@router.post("/episodes/{eid}/audio/normalise")
def normalise(eid: int, body: NormaliseIn, db: Session = Depends(get_db)):
    """A proposal only (nothing is saved but the cue phrases): the current lines re-split at natural beats, for the
    owner to review side by side, edit and apply (PUT /audio/lines with keep_previous) or discard."""
    ep = audio_episode(db, eid)
    gate(ep, "label_audio")
    tr = dict(ep.audio_transcript or {})
    if body.cues is not None:
        cues = list(dict.fromkeys(c.strip()[:40] for c in body.cues if c and c.strip()))
        if tr.get("cues") != cues:
            tr["cues"] = cues
            ep.audio_transcript = tr
            db.commit()
    cues = tr.get("cues", LN.DEFAULT_CUES)
    current = tr.get("lines", [])
    proposal = LN.propose_lines(current, tr.get("text", ""), cues)
    return {"cues": cues, "current": current, "proposal": proposal,
            "fragment": LN.trailing_fragment(proposal, tr.get("text", ""), tr.get("duration")),
            "changed": [ln["text"] for ln in proposal] != [ln["text"] for ln in current]}


@router.post("/episodes/{eid}/audio/lines/undo")
def undo_lines(eid: int, db: Session = Depends(get_db)):
    """One-click Undo of the last applied proposal or fragment decision."""
    ep = audio_episode(db, eid)
    gate(ep, "label_audio")
    tr = dict(ep.audio_transcript or {})
    prev = tr.pop("lines_previous", None)
    if not prev:
        raise HTTPException(409, "there is nothing to undo")
    tr["lines"], tr["end_at"] = prev["lines"], prev.get("end_at")
    tr.pop("fragment_ack", None)
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio lines restored ({len(prev['lines'])} lines)"))
    db.commit()
    return state(db, ep)


class FragmentIn(BaseModel):
    action: Literal["end_before", "keep"]


@router.post("/episodes/{eid}/audio/fragment")
def decide_fragment(eid: int, body: FragmentIn, db: Session = Depends(get_db)):
    """A cut-off last line: end the episode before it (the line is removed and the audio will end at its start), or
    keep it as it is."""
    ep = audio_episode(db, eid)
    gate(ep, "label_audio")
    tr = dict(ep.audio_transcript or {})
    frag = fragment_of(tr)
    if not frag:
        raise HTTPException(409, "the last line does not look cut off")
    if body.action == "keep":
        tr["fragment_ack"] = {"text": frag["text"], "end": frag["end"]}
        msg = f"Kept the last line as it is: {frag['text']!r}"
    else:
        if len(tr.get("lines", [])) < 2:
            raise HTTPException(409, "the only line cannot be removed")
        remember(tr)
        tr["lines"] = [ln for ln in tr["lines"] if ln["id"] != frag["line_id"]]
        tr["end_at"] = frag["start"]
        msg = f"The episode ends before the cut-off line at {frag['start']:.2f} s: {frag['text']!r}"
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=msg))
    db.commit()
    return state(db, ep)


# ------------------------------------------------------------------ cast
class NewCharacterIn(BaseModel):
    key: str = Field(min_length=2, max_length=41)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    visual_description: str = Field(default="", max_length=4000)
    voice_style: str = Field(default="", max_length=600)
    bubble_style: Literal["him", "her", "neutral"] = "neutral"
    # Casting hints (A): the measured traits as the owner left them, and an age range the OWNER sets (never inferred)
    voice_traits: "VoiceTraitsIn | None" = None
    age_range: str = Field(default="", max_length=30)


class VoiceTraitsIn(BaseModel):
    pitch: Literal["low", "medium", "high"] = "medium"
    pace: Literal["slow", "medium", "fast"] = "medium"
    energy: Literal["soft", "medium", "loud"] = "medium"


NewCharacterIn.model_rebuild()


def voice_style_of(n: "NewCharacterIn") -> str:
    """The new character's voice style: the owner's traits and age range, then their own words."""
    from .voice_traits import describe
    parts = []
    if n.voice_traits:
        parts.append(describe(n.voice_traits.model_dump()))
    if n.age_range.strip():
        parts.append(f"age range {n.age_range.strip()} (set by the owner)")
    if n.voice_style.strip():
        parts.append(n.voice_style.strip())
    return "; ".join(parts)[:600]


class SpeakerCastIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    character_key: str | None = None
    new: NewCharacterIn | None = None


class CastIn(BaseModel):
    speakers: list[SpeakerCastIn] = Field(min_length=1, max_length=12)


@router.post("/episodes/{eid}/audio/cast")
def set_cast(eid: int, body: CastIn, db: Session = Depends(get_db)):
    """Give each speaker label a character: an existing one, or a new character for this episode (no art yet; its pose
    sheet is generated and approved in the usual way). The lines then carry the character keys."""
    ep = audio_episode(db, eid)
    gate(ep, "audio_cast")
    tr = dict(ep.audio_transcript or {})
    lines = [dict(x) for x in tr.get("lines", [])]
    labels = set(speakers_of(lines))
    mapping: dict[str, str] = {}
    created = []
    for sp in body.speakers:
        if sp.label not in labels:
            raise HTTPException(422, f"no line is labelled {sp.label!r}")
        if (sp.character_key is None) == (sp.new is None):
            raise HTTPException(422, f"{sp.label}: choose an existing character or describe a new one (not both)")
        if sp.character_key is not None:
            if not db.query(Character).filter_by(key=sp.character_key).first():
                raise HTTPException(422, f"{sp.label}: there is no character {sp.character_key!r}")
            mapping[sp.label] = sp.character_key
            continue
        n = sp.new
        if not KEY.match(n.key):
            raise HTTPException(422, f"{sp.label}: key must be lowercase letters, digits and dashes, starting with a letter")
        if db.query(Character).filter_by(key=n.key).first() or n.key in created:
            raise HTTPException(409, f"{sp.label}: a character with key {n.key!r} already exists")
        from .character_looks import look_from_notes, notes_ranges
        db.add(Character(key=n.key, name=n.name, description=n.description,
                         visual_description=n.visual_description.strip() or look_from_notes(notes_ranges(ep), True),
                         voice_style=voice_style_of(n), bubble_style=n.bubble_style, scope="episode", episode_id=ep.id,
                         engine_character=f"studio-{n.key}", art_status="none", default_expression="neutral", voice=""))
        created.append(n.key)
        mapping[sp.label] = n.key
    for ln in lines:
        if ln.get("speaker") in mapping:
            ln["speaker"] = mapping[ln["speaker"]]
    tr["lines"], tr["cast"] = lines, {**tr.get("cast", {}), **mapping}
    ep.audio_transcript = tr
    for key in created:
        db.add(Event(episode_id=ep.id, kind="character", message=f"New character for the audio: {key}"))
    db.add(Event(episode_id=ep.id, kind="episode", message="Audio cast set: " + ", ".join(f"{k} → {v}" for k, v in mapping.items())))
    db.commit()
    return state(db, ep)


@router.post("/episodes/{eid}/audio/voice-traits")
def measure_voice_traits(eid: int, db: Session = Depends(get_db)):
    """Pitch, pace and energy per labelled speaker, measured from the audio (job `audio_voice_traits`, no AI model,
    no cost). Suggestions only: the owner edits them in the cast; gender and age are never inferred."""
    ep = audio_episode(db, eid)
    gate(ep, "audio_cast")
    if not speakers_of((ep.audio_transcript or {}).get("lines", [])) or not ep.audio_asset_id:
        raise HTTPException(409, "label the lines with speakers first")
    from .models import Job
    if db.query(Job).filter(Job.episode_id == ep.id, Job.kind == "audio_voice_traits", Job.status.in_(["queued", "running"])).count():
        raise HTTPException(409, "the voices are already being measured")
    return S.job(enqueue(db, "audio_voice_traits", episode_id=ep.id, revision=ep.revision, payload={"asset_id": ep.audio_asset_id}))


class SilentMemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    character_key: str | None = None
    new: NewCharacterIn | None = None


class SilentCastIn(BaseModel):
    members: list[SilentMemberIn] = Field(default_factory=list, max_length=8)


@router.put("/episodes/{eid}/audio/silent-cast")
def set_silent_cast(eid: int, body: SilentCastIn, db: Session = Depends(get_db)):
    """Characters who are named or present but never speak (reactions only): each is an existing character or a new
    character for this episode. The list replaces the previous one (an empty list removes them all)."""
    ep = audio_episode(db, eid)
    gate(ep, "audio_cast")
    tr = dict(ep.audio_transcript or {})
    speaking = set(speakers_of(tr.get("lines", [])))
    members, created = [], []
    for m in body.members:
        if (m.character_key is None) == (m.new is None):
            raise HTTPException(422, f"{m.name}: choose an existing character or describe a new one (not both)")
        if m.character_key is not None:
            if not db.query(Character).filter_by(key=m.character_key).first():
                raise HTTPException(422, f"{m.name}: there is no character {m.character_key!r}")
            key = m.character_key
        else:
            n = m.new
            if not KEY.match(n.key):
                raise HTTPException(422, f"{m.name}: key must be lowercase letters, digits and dashes, starting with a letter")
            if db.query(Character).filter_by(key=n.key).first() or n.key in created:
                raise HTTPException(409, f"{m.name}: a character with key {n.key!r} already exists")
            from .character_looks import look_from_notes, notes_ranges
            db.add(Character(key=n.key, name=n.name, description=n.description,
                             visual_description=n.visual_description.strip() or look_from_notes(notes_ranges(ep), False),
                             voice_style="", bubble_style=n.bubble_style, scope="episode", episode_id=ep.id,
                             engine_character=f"studio-{n.key}", art_status="none", default_expression="neutral", voice=""))
            created.append(n.key)
            key = n.key
        if key in speaking or key in [x["character_key"] for x in members]:
            raise HTTPException(422, f"{m.name}: {key} already speaks in this episode or is listed twice")
        members.append({"name": m.name.strip(), "character_key": key})
    tr["silent_cast"] = members
    ep.audio_transcript = tr
    for key in created:
        db.add(Event(episode_id=ep.id, kind="character", message=f"New silent character for the audio: {key}"))
    db.add(Event(episode_id=ep.id, kind="episode", message="Silent characters: " + (", ".join(f"{m['name']} → {m['character_key']}" for m in members) or "none")))
    db.commit()
    return state(db, ep)


@router.post("/episodes/{eid}/audio/suggest-cast")
def suggest_cast(eid: int, db: Session = Depends(get_db)):
    ep = audio_episode(db, eid)
    gate(ep, "audio_cast")
    if not (ep.audio_transcript or {}).get("lines"):
        raise HTTPException(409, "transcribe the audio first")
    from .models import Job
    if db.query(Job).filter(Job.episode_id == ep.id, Job.kind == "audio_cast_suggest", Job.status.in_(["queued", "running"])).count():
        raise HTTPException(409, "a cast suggestion is already being written")
    return S.job(enqueue(db, "audio_cast_suggest", episode_id=ep.id, revision=ep.revision))


# ------------------------------------------------------------------ worker jobs
from .tasks import Ctx, task  # noqa: E402  (tasks imports this module last; the handlers register with @task)


@task
def audio_transcribe(ctx: Ctx) -> dict:
    from .analysis import transcribe
    from .settings_store import get_section
    from .storage import storage
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    if (job.payload or {}).get("asset_id") != ep.audio_asset_id:
        ctx.log("A newer upload replaced this audio; nothing to do.")
        return {"skipped": "replaced by a newer upload"}
    a = db.get(Asset, ep.audio_asset_id)
    local = storage().get_to_file(a.storage_key, ctx.folder("episodes", ep.id, "audio") / Path(a.storage_key).name)
    cfg = get_section(db, "transcription")
    ctx.log(f"Transcribing with {cfg.get('provider')} (word timestamps)")
    tr = transcribe(cfg, local)
    lines = split_lines(tr)
    if not lines:
        raise ValueError("the transcription found no speech in this audio")
    duration = tr.get("duration") or audio_seconds_of(local) or lines[-1]["end"]
    kept = {k: v for k, v in (ep.audio_transcript or {}).items() if k in KEEP_KEYS}   # upload facts, video hints, window
    ep.audio_transcript = {**kept, "provider": tr.get("provider", cfg.get("provider")), "model": tr.get("model", ""),
                           "language": tr.get("language", ""), "duration": round(float(duration), 3), "text": tr.get("text", ""),
                           "words_available": bool(tr.get("words")), "asset_id": a.id, "lines": lines, "edited": False}
    ep.last_error = ""
    set_stage(ep, "audio_labelling")
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio transcribed: {len(lines)} timed lines; label the speakers"))
    db.commit()
    return {"lines": len(lines), "duration": round(float(duration), 3), "words": len(tr.get("words") or [])}


@task
def audio_media_prepare(ctx: Ctx) -> dict:
    """A video upload: extract its audio track, optionally sample frames for the video notes (only inside the chosen
    window, or the whole clip; job `audio_video_notes`), delete the original video (always, even on failure), then store
    the audio like an audio upload and apply the window."""
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    src = _in_uploads(p.get("upload", ""))
    frames_dir: Path | None = None
    out = uploads_dir() / f"extracted-{ep.id}-{uuid.uuid4().hex[:8]}.m4a"
    try:
        sm = (ep.audio_transcript or {}).get("source_media") or {}
        if ep.stage != "audio_preparing" or not sm.get("preparing") or not src.exists():
            ctx.log("A newer upload replaced this video; nothing to do.")
            return {"skipped": "replaced by a newer upload"}
        try:
            out = media.extract_audio(src, out)
            ctx.log("Audio track extracted from the video")
            frames = []
            win = p.get("window") or {"start": 0.0, "end": float(p.get("seconds") or media.probe(out)["duration"] or 0)}
            if p.get("hints"):
                from . import video_notes as VN
                frames_dir = uploads_dir() / f"notes-{ep.id}-{uuid.uuid4().hex[:8]}"
                from . import notes_v2 as NV
                frames = media.sample_frames_at(src, frames_dir, NV.frame_times(win["start"], win["end"], ep.format))
                ctx.log(f"{len(frames)} frame(s) sampled in {win['start']:.1f}-{win['end']:.1f} s for the video notes "
                        "(deleted after use)")
        finally:
            src.unlink(missing_ok=True)       # the original video is never kept: only its audio is used
        ctx.log("Original video deleted")
        seconds = media.probe(out)["duration"]
        if seconds is None:
            raise media.MediaError("the length of the extracted audio could not be read")
        try:
            msg = accept_audio(db, ep, out, "audio/mp4", ".m4a", seconds,
                               {"type": "video", "original_deleted": True, "hints_requested": bool(p.get("hints"))})
        except HTTPException as e:
            raise media.MediaError(str(e.detail)) from None
        db.add(Event(episode_id=ep.id, kind="episode", message=msg))
        db.commit()
        full_id = ep.audio_transcript["source_media"]["full_asset_id"]
        if p.get("window"):
            try:
                apply_window(db, ep, p["window"]["start"], p["window"]["end"])   # transcribes the window
            except HTTPException as e:
                raise media.MediaError(str(e.detail)) from None
        elif ep.audio_asset_id:
            enqueue(db, "audio_transcribe", episode_id=ep.id, revision=ep.revision, payload={"asset_id": ep.audio_asset_id})
        if frames:
            enqueue(db, "audio_video_notes", episode_id=ep.id, revision=ep.revision,
                    payload={"frames": frames_dir.name, "full_asset_id": full_id, "base": win["start"],
                             "length": round(win["end"] - win["start"], 3),
                             "times": {f.name: round(t - win["start"], 2) for f, t in frames}})
            frames_dir = None                 # handed to the notes job, which deletes it
        elif p.get("hints"):
            db.add(Event(episode_id=ep.id, kind="episode", message="No frames could be read from the video: no notes"))
            db.commit()
        return {"audio_asset_id": ep.audio_asset_id, "needs_trim": ep.audio_asset_id is None, "frames": len(frames)}
    except (media.MediaError, media.MediaToolMissing) as e:
        ep.audio_transcript, ep.audio_asset_id, ep.last_error = None, None, str(e)[:2000]
        set_stage(ep, "audio_upload")
        db.add(Event(episode_id=ep.id, kind="episode", message=f"The video could not be used: {e}"))
        db.commit()
        return {"refused": str(e)}
    finally:
        src.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        if frames_dir is not None:
            shutil.rmtree(frames_dir, ignore_errors=True)


API_VISION = ("openai", "anthropic")    # the video notes use the studio's API vision provider only, never a Codex login


def hints_vision_config(db: Session) -> dict:
    """Settings > Video and visual analysis, if it is an API provider (OpenAI / Anthropic with the studio's key);
    otherwise ValueError. A fallback that is not an API provider is dropped."""
    from .settings_store import get_section
    cfg = dict(get_section(db, "vision"))
    if cfg.get("provider") not in API_VISION:
        raise ValueError("video notes need an API vision provider: set Settings > Video and visual analysis to "
                         "OpenAI or Anthropic (the Codex login is never used for them)")
    if cfg.get("fallback") not in API_VISION:
        cfg["fallback"] = "none"
    return cfg


@task
def audio_video_notes(ctx: Ctx) -> dict:
    """Text-only staging notes from the sampled frames, asked once of the studio's API vision provider (token usage
    recorded). Only the schema survives (video_notes.clean_notes); the frames are deleted when this job ends,
    whatever happens."""
    from . import analysis
    from . import video_notes as VN
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    folder = _in_uploads(p.get("frames", ""))
    try:
        sm = (ep.audio_transcript or {}).get("source_media") or {}
        frames = sorted(folder.glob("frame-*.jpg")) if folder.is_dir() else []
        if sm.get("full_asset_id") != p.get("full_asset_id") or not frames:
            ctx.log("No frames for the current upload; nothing to do.")
            return {"skipped": True}
        try:
            cfg = hints_vision_config(db)
        except ValueError as e:
            db.add(Event(episode_id=ep.id, kind="episode", message=f"No video notes: {e}"))
            db.commit()
            return {"skipped": str(e)}
        from . import notes_v2 as NV
        times = [float((p.get("times") or {}).get(f.name, 0.0)) for f in frames]
        length = float(p.get("length") or 0) or (max(times) + NV.EVERY.get(ep.format, 1.0))
        est = notes_estimate(db, length, ep.format)
        if est.get("configured") and not est["within_cap"]:
            msg = f"video notes skipped: about ${est['usd']:.2f}, over the ${est['cap_usd']:.2f} cap"
            db.add(Event(episode_id=ep.id, kind="episode", message=msg))
            db.commit()
            return {"skipped": msg}
        step = (length / len(frames)) if frames else 1.0
        kept, stripped, usages, mappings, sent = [], 0, [], [], 0
        for idx in NV.batches(len(frames)):
            carried = kept[-1]["people"] if kept else None   # the overlap frame, described in words
            analysis.last_vision_usage.clear()
            ans = analysis.analyse_images(cfg, [frames[i] for i in idx], NV.prompt([times[i] for i in idx], carried))
            usages.append(dict(analysis.last_vision_usage))
            sent += len(idx)
            got, s = NV.clean_frames(ans, [times[i] for i in idx])
            stripped += s
            if kept:
                got, m = NV.renumber(kept[-1], got)
                mappings.append(NV.summarize_mapping(m))
            kept += got
        from . import beats as BT
        ranges, redacted = NV.to_ranges(kept, length, step)
        usage = {"provider": (usages[0] if usages else {}).get("provider"), "model": (usages[0] if usages else {}).get("model"),
                 "input_tokens": sum(u.get("input_tokens") or 0 for u in usages),
                 "output_tokens": sum(u.get("output_tokens") or 0 for u in usages), "calls": len(usages)}
        quality = NV.quality(kept, sent, stripped + redacted, usages, est.get("usd"), mappings)
        db.refresh(ep)
        tr = dict(ep.audio_transcript or {})
        notes = {"version": NV.VERSION, "ranges": ranges, "people_frames": kept, "quality": quality,
                 "base": float(p.get("base") or 0.0), "length": round(length, 3), "frames": len(frames),
                 "redacted": stripped + redacted, "usage": usage, "job_id": job.id, "edited": False,
                 "source": "video frames (deleted)"}
        # one setting per room (smoothed; the unsmoothed values stay as "was"), views, and the action beats
        tr["video_notes"] = BT.rebuild(notes, tr.get("lines", []), tr.get("person_map") or {})
        ranges = tr["video_notes"]["ranges"]
        tr["media_hints"] = {**VN.summary(ranges), "frames": len(frames), "job_id": job.id, "usage": usage,
                             "from": "video notes"}
        ep.audio_transcript = tr
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Video notes: {quality['people']} people, {len(ranges)} "
                                                              f"range(s) from {len(frames)} frame(s) in {len(usages)} call(s); "
                                                              f"{stripped + redacted} value(s) outside the notes' schema "
                                                              "removed; frames deleted"))
        db.commit()
        if usage:
            ctx.log(f"Vision call: {usage.get('provider')} {usage.get('model')}, {usage.get('input_tokens')} input / "
                    f"{usage.get('output_tokens')} output tokens")
        return {"ranges": len(ranges), "frames": len(frames), "redacted": stripped + redacted, "usage": usage, "quality": quality}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


CAST_SYSTEM = ("You are the casting director of an adult 2D animated comedy (grown-up characters and situations). You read "
               "the TEXT of a transcript of real recorded dialogue (you cannot hear the audio) and propose the cast that will "
               "perform it on screen. You never name or imitate real people; characters are original. You never guess "
               "anyone's gender or age, and never describe how anyone sounds: the owner sets those. Reply with one JSON "
               "object only.")
CAST_SOURCE = "text"   # the suggestion works from the transcript text only (shown to the owner)


def _clip(v, n: int) -> str:
    return str(v or "").strip()[:n]


def mentioned_names(raw, lines: list[dict], speaking: set[str]) -> list[dict]:
    """Silent-character suggestions: only names that really appear in the transcript (word match, any case), that are
    not already speakers, each with the lines that mention it."""
    out, seen = [], set()
    for m in (raw if isinstance(raw, list) else [])[:8]:
        name = _clip((m or {}).get("name") if isinstance(m, dict) else m, 60)
        if not name or name.lower() in seen or name.lower() in {s.lower() for s in speaking if s}:
            continue
        pat = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])", re.IGNORECASE)
        where = [ln["id"] for ln in lines if pat.search(ln.get("text", ""))]
        if where:
            out.append({"name": name, "line_ids": where})
            seen.add(name.lower())
    return out


@task
def audio_voice_traits(ctx: Ctx) -> dict:
    """Measure pitch, pace and energy per labelled speaker from the episode's audio (no AI model)."""
    from . import voice_traits as VT
    from .storage import storage
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    if (job.payload or {}).get("asset_id") != ep.audio_asset_id:
        return {"skipped": "the audio changed"}
    a = db.get(Asset, ep.audio_asset_id)
    local = storage().get_to_file(a.storage_key, ctx.folder("episodes", ep.id, "audio") / Path(a.storage_key).name)
    samples = VT.decode(local)
    if samples is None:
        raise media.MediaToolMissing("FFmpeg is not configured (FFMPEG): the voices cannot be measured")
    tr = dict(ep.audio_transcript or {})
    traits = VT.measure(samples, tr.get("lines", []))
    tr["voice_traits"] = {"speakers": traits, "source": "measured from the audio", "job_id": job.id}
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message="Voices measured: " + ", ".join(
        f"{sp}: pitch {t['pitch']}, pace {t['pace']}, energy {t['energy']}" for sp, t in traits.items())))
    db.commit()
    return {"speakers": len(traits)}


@task
def audio_cast_suggest(ctx: Ctx) -> dict:
    from .providers import text_provider
    from .settings_store import get_section
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    tr = dict(ep.audio_transcript or {})
    lines = tr.get("lines", [])
    existing = [c for c in db.query(Character).order_by(Character.id) if c.scope == "recurring" or c.art_status == "approved"]
    listing = "\n".join(f"[{ln['id']} | speaker: {ln.get('speaker') or '?'} | {ln['start']:.1f}-{ln['end']:.1f} s] {ln['text']}" for ln in lines)
    cast = "\n".join(f"- {c.key}: {c.name}. {c.description[:200]} Voice: {c.voice_style[:120]}" for c in existing) or "(none)"
    hints = tr.get("media_hints") or {}
    hint_text = (f"\nThe owner's video suggests about {hints.get('people_count')} people, setting: {hints.get('setting') or '?'}, "
                 f"mood: {hints.get('mood') or '?'}.\n" if hints else "")
    prompt = (f"Transcript (one timed line each; '?' = speaker not labelled yet):\n{listing}\n{hint_text}\n"
              f"Existing characters that may be reused when they clearly fit:\n{cast}\n\n"
              "Propose who speaks each line and the cast. Group lines into distinct speakers by content and turn-taking. "
              "Use the owner's labels where given. For each speaker give a short label (reuse the owner's label if any), "
              "an existing character key to reuse OR a new original adult character: name, a lowercase key (letters, digits, "
              "dashes), one-sentence personality/comic role, and a short visual description (hair or cap shape and colour, "
              "one garment colour). Do not state or imply gender or age anywhere, and do not describe voices.\n"
              "Also list people who are NAMED in the dialogue but never speak (e.g. someone addressed or talked about who "
              "could react silently on screen): their name exactly as written in the transcript, and the ids of the lines "
              "that mention them.\n"
              'JSON: {"speakers": [{"label": "", "reuse_key": null, "name": "", "key": "", "description": "", '
              '"visual_description": ""}], "line_speakers": {"l1": "label"}, '
              '"mentioned": [{"name": "", "line_ids": ["l1"]}]}')
    ans = text_provider(get_section(db, "text")).complete_json(CAST_SYSTEM, prompt)
    keys = {c.key for c in db.query(Character).all()}
    ids = {ln["id"] for ln in lines}
    speakers = []
    for s in (ans.get("speakers") or [])[:12]:
        if not isinstance(s, dict) or not _clip(s.get("label"), 40):
            continue
        reuse = s.get("reuse_key") if s.get("reuse_key") in keys else None
        key = re.sub(r"[^a-z0-9-]+", "-", _clip(s.get("key"), 41).lower()).strip("-")
        # no voice style and no him/her from the model: it reads text only, and the owner sets gender and age
        speakers.append({"label": _clip(s.get("label"), 40), "reuse_key": reuse,
                         "name": _clip(s.get("name"), 120), "key": key if KEY.match(key or "") else "",
                         "description": _clip(s.get("description"), 600), "visual_description": _clip(s.get("visual_description"), 600),
                         "bubble_style": "neutral"})
    labels = {s["label"] for s in speakers}
    raw_ls = ans.get("line_speakers") if isinstance(ans.get("line_speakers"), dict) else {}
    line_speakers = {k: v for k, v in raw_ls.items() if k in ids and v in labels}
    mentioned = mentioned_names(ans.get("mentioned"), lines, labels | {s["name"] for s in speakers})
    tr["cast_suggestion"] = {"speakers": speakers, "line_speakers": line_speakers, "mentioned": mentioned,
                             "source": CAST_SOURCE, "job_id": job.id}
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Cast suggestion ready: {len(speakers)} speaker(s)"))
    db.commit()
    return {"speakers": len(speakers), "lines_labelled": len(line_speakers)}
