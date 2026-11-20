"""Audio-first episodes, stage 1: the owner uploads an audio file and the studio builds the episode AROUND it.

The uploaded audio is the voice track: no voice provider is used for these lines. Stage 1 covers:

  1. create   POST /api/audio-episodes             the rights confirmation and its source label are REQUIRED
                                                     (append-only Review record "audio_rights")
  2. upload   PUT  /api/episodes/{id}/audio         raw request body (audio/*), owner upload only: nothing here
                                                     downloads audio from other sites
  3. transcribe (worker job `audio_transcribe`)    the selected transcription provider (word timestamps), split into
                                                     timed lines (pauses, sentence ends, maximum length)
  4. label    PUT  /api/episodes/{id}/audio/lines   a speaker per line; edit, split or merge lines (validated here)
  5. cast     POST /api/episodes/{id}/audio/suggest-cast   the AI writer proposes the cast and voice styles (job
                                                     `audio_cast_suggest`), stored as a suggestion only
              POST /api/episodes/{id}/audio/cast    map each speaker to an existing character or create a new
                                                     episode character; the lines then carry character keys

Stages: audio_upload -> audio_transcribing -> audio_labelling. Building scenes around the timed lines and playing the
uploaded clips in production are later stages (separate changes, owner-approved).
"""
from __future__ import annotations

import re
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

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

RIGHTS_SOURCES = ("own_recording", "licensed", "voice_actor", "other")
RIGHTS_LABEL = {"own_recording": "own recording", "licensed": "licensed", "voice_actor": "voice actor", "other": "other"}
MAX_BYTES = 60 * 1024 * 1024
MAX_SECONDS = {"short": 60, "long": 450}            # the formats' caps (a Short runs at most 60 s; long at most 7½ min)
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
            "transcript": {k: v for k, v in tr.items() if k not in ("lines", "cast_suggestion")} if tr else None,
            "lines": lines, "speakers": sp,
            "unlabelled_lines": sum(1 for ln in lines if not ln.get("speaker")),
            "speakers_without_character": [s for s in sp if s not in keys],
            "cast_suggestion": tr.get("cast_suggestion"),
            # Stage 1c: line quality (cue phrases, one-level Undo, a cut-off last line)
            "cues": tr.get("cues", LN.DEFAULT_CUES),
            "can_undo": bool(tr.get("lines_previous")),
            "end_at": tr.get("end_at"),
            "fragment": fragment_of(tr),
            "characters": [{"key": c.key, "name": c.name, "scope": c.scope, "voice_style": c.voice_style}
                           for c in sorted(keys.values(), key=lambda c: c.id)
                           if c.scope == "recurring" or c.art_status == "approved" or c.episode_id == ep.id]}


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
    ep = Episode(title=body.title, format=body.format, stage="audio_upload", source="audio",
                 audio_rights_confirmed=True, audio_rights_source=body.rights_source)
    db.add(ep)
    db.flush()
    # append-only record of who confirmed the rights, and the stated source
    db.add(Review(episode_id=ep.id, gate="audio_rights", decision="confirmed", revision=ep.revision, target={},
                  comment=f"I have the right to use this audio. Source: {RIGHTS_LABEL[body.rights_source]}", actor=user))
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio-first episode created (audio source: {RIGHTS_LABEL[body.rights_source]})"))
    db.commit()
    return state(db, ep)


@router.put("/episodes/{eid}/audio")
async def upload_audio(eid: int, request: Request, db: Session = Depends(get_db)):
    """The audio file is the raw request body (Content-Type audio/*), streamed to disk with a size cap."""
    ep = audio_episode(db, eid)
    gate(ep, "upload_audio")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in AUDIO_TYPES:
        raise HTTPException(415, f"upload an audio file ({', '.join(sorted(set(AUDIO_TYPES.values())))})")
    folder = get_settings().work_dir / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"audio-{ep.id}-{uuid.uuid4().hex[:8]}{AUDIO_TYPES[ctype]}"
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, f"the audio file is larger than {MAX_BYTES // (1024 * 1024)} MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, "the uploaded file is empty")
        try:
            seconds = audio_seconds_of(tmp)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if seconds is not None and seconds > MAX_SECONDS[ep.format] + 0.5:
            raise HTTPException(422, f"the audio runs {seconds:.0f} s; a {ep.format} episode allows at most {MAX_SECONDS[ep.format]} s")
        from .storage import sha256_file
        from .tasks import store_asset
        key = f"episodes/{ep.id}/source-audio-{sha256_file(tmp)[:12]}{AUDIO_TYPES[ctype]}"
        a = store_asset(db, ep_id=ep.id, src=tmp, key=key, kind="source-audio", content_type=ctype, revision=ep.revision,
                        label=f"Uploaded audio ({RIGHTS_LABEL.get(ep.audio_rights_source, '')})")
    finally:
        tmp.unlink(missing_ok=True)
    ep.audio_asset_id, ep.audio_transcript, ep.last_error = a.id, None, ""
    set_stage(ep, "audio_transcribing")
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio uploaded ({size / 1048576:.1f} MB" + (f", {seconds:.1f} s)" if seconds else ")")))
    db.commit()
    enqueue(db, "audio_transcribe", episode_id=ep.id, revision=ep.revision, payload={"asset_id": a.id})
    return state(db, ep)


@router.post("/episodes/{eid}/audio/transcribe")
def transcribe_again(eid: int, db: Session = Depends(get_db)):
    ep = audio_episode(db, eid)
    gate(ep, "transcribe_audio")
    if not ep.audio_asset_id:
        raise HTTPException(409, "upload the audio first")
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
        db.add(Character(key=n.key, name=n.name, description=n.description, visual_description=n.visual_description,
                         voice_style=n.voice_style, bubble_style=n.bubble_style, scope="episode", episode_id=ep.id,
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
    ep.audio_transcript = {"provider": tr.get("provider", cfg.get("provider")), "model": tr.get("model", ""),
                           "language": tr.get("language", ""), "duration": round(float(duration), 3), "text": tr.get("text", ""),
                           "words_available": bool(tr.get("words")), "asset_id": a.id, "lines": lines, "edited": False}
    ep.last_error = ""
    set_stage(ep, "audio_labelling")
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Audio transcribed: {len(lines)} timed lines; label the speakers"))
    db.commit()
    return {"lines": len(lines), "duration": round(float(duration), 3), "words": len(tr.get("words") or [])}


CAST_SYSTEM = ("You are the casting director of an adult 2D animated comedy (grown-up characters and situations). You read "
               "a transcript of real recorded dialogue and propose the cast that will perform it on screen. You never name or "
               "imitate real people; characters are original. Reply with one JSON object only.")


def _clip(v, n: int) -> str:
    return str(v or "").strip()[:n]


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
    prompt = (f"Transcript (one timed line each; '?' = speaker not labelled yet):\n{listing}\n\n"
              f"Existing characters that may be reused when they clearly fit:\n{cast}\n\n"
              "Propose who speaks each line and the cast. Group lines into distinct speakers by content and turn-taking. "
              "Use the owner's labels where given. For each speaker give a short label (reuse the owner's label if any), "
              "an existing character key to reuse OR a new original adult character: name, a lowercase key (letters, digits, "
              "dashes), one-sentence personality/comic role, a short visual description (hair or cap shape and colour, one "
              "garment colour), a voice style describing how they sound in the recording (age range, pace, tone), and "
              "bubble_style him|her|neutral.\n"
              'JSON: {"speakers": [{"label": "", "reuse_key": null, "name": "", "key": "", "description": "", '
              '"visual_description": "", "voice_style": "", "bubble_style": "neutral"}], "line_speakers": {"l1": "label"}}')
    ans = text_provider(get_section(db, "text")).complete_json(CAST_SYSTEM, prompt)
    keys = {c.key for c in db.query(Character).all()}
    ids = {ln["id"] for ln in lines}
    speakers = []
    for s in (ans.get("speakers") or [])[:12]:
        if not isinstance(s, dict) or not _clip(s.get("label"), 40):
            continue
        reuse = s.get("reuse_key") if s.get("reuse_key") in keys else None
        key = re.sub(r"[^a-z0-9-]+", "-", _clip(s.get("key"), 41).lower()).strip("-")
        speakers.append({"label": _clip(s.get("label"), 40), "reuse_key": reuse,
                         "name": _clip(s.get("name"), 120), "key": key if KEY.match(key or "") else "",
                         "description": _clip(s.get("description"), 600), "visual_description": _clip(s.get("visual_description"), 600),
                         "voice_style": _clip(s.get("voice_style"), 300),
                         "bubble_style": s.get("bubble_style") if s.get("bubble_style") in ("him", "her", "neutral") else "neutral"})
    labels = {s["label"] for s in speakers}
    raw_ls = ans.get("line_speakers") if isinstance(ans.get("line_speakers"), dict) else {}
    line_speakers = {k: v for k, v in raw_ls.items() if k in ids and v in labels}
    tr["cast_suggestion"] = {"speakers": speakers, "line_speakers": line_speakers, "job_id": job.id}
    ep.audio_transcript = tr
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Cast suggestion ready: {len(speakers)} speaker(s)"))
    db.commit()
    return {"speakers": len(speakers), "lines_labelled": len(line_speakers)}
