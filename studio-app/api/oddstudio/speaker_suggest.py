"""Suggested speaker labels for "Lines and speakers" (2026-11-27, owner request after "25 line(s) have no speaker yet").

Two ways, both paid, both a SUGGESTION only: nothing is written to the episode's lines until the owner accepts rows in
the review table (all, or line by line, after editing any label).

  from the video  Gemini watches the episode's PRIVATE reference video (guided.py, step 1, or kept when the episode was
                  made from a video) WITH its audio, and gets the transcript lines (id, time, text). It answers, per
                  line, the most likely speaker as a short role label ("Doctor", "Patient", "Jim") and a confidence.
                  Only words come back. The video is uploaded to the Files API and deleted afterwards (also on failure),
                  exactly like the acting analysis; its pictures never go to an image or video generator.
  from the text   no reference video: the configured text model (prompt_writer's provider and model, Settings > Guided
                  generation) guesses from the words alone. Its confidence is capped at TEXT_CAP and the table says so.

Tier rules (as the acting analysis and the quality check): the paid model (Settings > Guided generation) when the owner
ticks "my key is on a paid tier" (the default); the free-tier models only when "use the free tier" is ticked for this
run (Google may use free-tier uploads to improve its models), after the paid model answers 429 or 503, or alone when the
paid tier is not ticked. Every call shows its "at most" price first and the request must carry it (confirm_usd, HTTP 409
otherwise). Never retried. Keys only from secrets_store.secret().

Labels are mapped to the episode's characters when a name or key matches; Cast from video uses the labels as its
character list (cast_labels()).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, Job, Setting
from .providers import ProviderError
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

JOB = "speaker_suggest"
FPS = 1                      # who speaks: the voices carry most of it; one frame a second shows who is on screen
CHARS_PER_TOKEN = 3.5
TOKENS_PER_LINE_OUT = 40     # {"line_id": "l12", "speaker": "Doctor", "confidence": 0.8} and some slack
TEXT_CAP = 0.5               # text only: never more sure than this
LEVELS = ((0.75, "high"), (0.45, "medium"), (0.0, "low"))
WORD_CONFIDENCE = {"high": 0.9, "very high": 0.95, "medium": 0.6, "moderate": 0.6, "low": 0.3, "very low": 0.15}


def key(eid: int) -> str:
    return f"speakers:{eid}"


# ================================================================== pure parts
def lines_payload(lines: list[dict], offset: float = 0.0) -> list[dict]:
    """What is sent: each line's id, its time (on the VIDEO's timeline: + offset when the episode uses a window of it)
    and its text. Never the speakers already typed (the answer must not just echo them)."""
    return [{"id": ln["id"], "start": round(float(ln["start"]) + offset, 2), "end": round(float(ln["end"]) + offset, 2),
             "text": ln.get("text", "")} for ln in lines]


def signature(lines: list[dict]) -> str:
    """The lines the suggestion was made for (ids and words): a later edit makes the suggestion stale."""
    return hashlib.sha256(json.dumps([[ln["id"], ln.get("text", "")] for ln in lines]).encode()).hexdigest()[:16]


PROMPT = """You are a dialogue editor. {source}

Below is the transcript, one line at a time, with each line's id and its time in seconds{timeline}.
For EACH line, say who speaks it.

Names we already use: {names}. Use one of these when it is the same person. Otherwise give a short role label from what
is said and done (for example "Doctor", "Patient", "Nurse"), or the first name when someone is called by it. Use the
SAME label for the same person every time. Never describe anyone's face or looks.

Lines: {lines}

Return JSON only: {{"speakers": [{{"line_id": "<id>", "speaker": "<short label>", "confidence": <0 to 1>}}]}}
One entry per line id, in order. confidence: how sure you are that this person says this line."""

VIDEO_SOURCE = ("Watch AND listen to this video: the voices, whose lips move and who is on screen tell you who speaks.")
TEXT_SOURCE = ("You only have the words, not the audio or the picture: guess from what is said (questions and answers, "
               "names, who talks about what). Be honest when you are unsure: use a low confidence.")
TEXT_SYSTEM = "You label who says each line of a short comedy sketch transcript. Reply with JSON only."


def prompt_for(lines: list[dict], names: list[str], video: bool, offset: float = 0.0) -> str:
    return PROMPT.format(source=VIDEO_SOURCE if video else TEXT_SOURCE,
                         timeline=" (the same timeline as the video)" if video else "",
                         names=", ".join(names) or "(none yet)",
                         lines=json.dumps(lines_payload(lines, offset if video else 0.0), ensure_ascii=False))


def max_tokens_for(n: int) -> int:
    return min(16000, 400 + TOKENS_PER_LINE_OUT * n)


def confidence_of(x) -> float:
    """0..1 from a number (a percentage too) or a word ("high", "medium", "low"); 0 when unreadable."""
    if isinstance(x, str):
        w = x.strip().lower()
        if w in WORD_CONFIDENCE:
            return WORD_CONFIDENCE[w]
        try:
            x = float(w.rstrip("%"))
        except ValueError:
            return 0.0
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v > 1.0:
        v = v / 100.0
    return round(max(0.0, min(1.0, v)), 2)


def level(c: float) -> str:
    return next(name for floor, name in LEVELS if c >= floor)


def clean_label(s) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip().strip("\"'")
    return s[:40]


def map_label(label: str, characters: list[dict]) -> dict | None:
    """The episode's character for a label: the same key or name (any case), else the same first word when only one
    character has it ("Jim" -> "Jim Hacker"). characters: [{key, name}]."""
    n = label.strip().lower()
    if not n:
        return None
    for c in characters:
        if c["key"].lower() == n or c["name"].strip().lower() == n:
            return c
    first = n.split(" ")[0]
    hits = [c for c in characters if c["name"].strip().lower().split(" ")[0] == first]
    return hits[0] if len(hits) == 1 else None


def normalise(raw, lines: list[dict], characters: list[dict], cap: float = 1.0) -> list[dict]:
    """The answer as one row per CURRENT line (in order): {line_id, start, end, text, current, label, confidence, level,
    character_key, character_name}. Seen in practice: {"speakers": [...]}, a bare list, or {"<line id>": "<label>"}.
    A line the answer skipped gets an empty label and confidence 0."""
    items = raw.get("speakers", raw.get("lines", raw)) if isinstance(raw, dict) else raw
    by_id: dict[str, dict] = {}
    if isinstance(items, dict):
        items = [{"line_id": k, **(v if isinstance(v, dict) else {"speaker": v})} for k, v in items.items()]
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        lid = str(it.get("line_id", it.get("id", "")))
        if lid and lid not in by_id:
            by_id[lid] = it
    rows = []
    for ln in lines:
        it = by_id.get(ln["id"]) or {}
        label = clean_label(it.get("speaker", it.get("label", "")))
        c = min(cap, confidence_of(it.get("confidence"))) if label else 0.0
        m = map_label(label, characters) if label else None
        rows.append({"line_id": ln["id"], "start": ln["start"], "end": ln["end"], "text": ln.get("text", ""),
                     "current": ln.get("speaker", ""), "label": label, "confidence": c, "level": level(c),
                     "character_key": m["key"] if m else None, "character_name": m["name"] if m else None})
    return rows


def labels_of(rows: list[dict]) -> list[str]:
    return list(dict.fromkeys((r.get("character_name") or r["label"]) for r in rows if r.get("label")))


# ================================================================== episode data
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = v
    else:
        db.add(Setting(key=key(eid), value=v))


def characters_for(db: Session, ep: Episode) -> list[dict]:
    """The characters a label may map to: the ones the audio cast step offers (audio_first.state)."""
    from .audio_first import state
    return [{"key": c["key"], "name": c["name"]} for c in state(db, ep)["characters"]]


def known_names(db: Session, ep: Episode, lines: list[dict]) -> list[str]:
    """Names already in use: the episode's cast, and the speaker labels the owner typed (character keys as names)."""
    from . import acting_analysis as AA
    names, _ = AA.cast_names(db, ep)
    by_key = {c.key: c.name for c in db.query(Character)}
    for ln in lines:
        s = (ln.get("speaker") or "").strip()
        if s:
            s = by_key.get(s, s)
            if s.lower() not in {n.lower() for n in names}:
                names.append(s)
    return names


def cast_labels(db: Session, ep: Episode) -> list[str]:
    """The speaker labels as a character list for Cast from video: the labels saved on the lines (a character key as
    its name); when none is saved yet, the labels of the pending suggestion."""
    from .audio_first import speakers_of
    lines = (ep.audio_transcript or {}).get("lines") or []
    by_key = {c.key: c.name for c in db.query(Character)}
    saved = [by_key.get(s, s) for s in speakers_of(lines)]
    if saved:
        return list(dict.fromkeys(saved))
    sug = stored(db, ep.id).get("suggestion") or {}
    return labels_of(sug.get("rows") or []) if not sug.get("accepted") else []


def _offset(ref: dict | None) -> float:
    return float(((ref or {}).get("window") or {}).get("start") or 0.0)


def _models(gcfg: dict, paid_tier: bool, use_free_tier: bool) -> list[str]:
    return ([gcfg["acting_model"]] if paid_tier else []) + (list(gcfg.get("acting_free_models") or []) if use_free_tier else [])


def video_estimate(db: Session, ep: Episode, lines: list[dict]) -> dict | None:
    """The "at most" price at the paid model's prices (the free tier costs nothing). None without a reference video
    whose length is known (or a transcript duration to stand in for it)."""
    from . import acting_analysis as AA
    from . import guided
    ref = guided.reference_video(db, ep.id)
    if not ref or not lines:
        return None
    secs = float(ref.get("seconds") or 0) or float((ep.audio_transcript or {}).get("duration") or 0) + _offset(ref)
    if not secs:
        return None
    gcfg = get_section(db, "guide")
    names = known_names(db, ep, lines)
    tin = int(secs * AA.TOKENS_PER_SECOND) + math.ceil(len(prompt_for(lines, names, True, _offset(ref))) / CHARS_PER_TOKEN)
    mt = max_tokens_for(len(lines))
    p_in, p_out = float(gcfg["acting_usd_in"]), float(gcfg["acting_usd_out"])
    usd = lambda o: round(tin * p_in / 1e6 + o * p_out / 1e6, 4)
    typ = min(mt, 30 * len(lines) + 200)
    return {"model": gcfg["acting_model"], "video_seconds": round(secs, 1), "input_tokens": tin, "max_output_tokens": mt,
            "usd_typical": usd(typ), "usd_max": usd(mt), "free_models": list(gcfg.get("acting_free_models") or []),
            "label": f"1 request, {secs:.0f} s of video with its sound, {len(lines)} lines: about ${usd(typ):.2f}, at most ${usd(mt):.2f}"}


def text_estimate(db: Session, ep: Episode, lines: list[dict]) -> dict | None:
    from . import prompt_writer as PW
    if not lines:
        return None
    cfg = PW.config(db)
    msg = prompt_for(lines, known_names(db, ep, lines), False)
    tin = PW.estimate_tokens(TEXT_SYSTEM) + PW.estimate_tokens(msg) + 8
    mt = max_tokens_for(len(lines))
    return {"model": cfg["prompt_model"], "input_tokens": tin, "max_output_tokens": mt,
            "usd_typical": round(PW.cost_usd(tin, min(mt, 30 * len(lines) + 200), cfg), 4),
            "usd_max": round(PW.cost_usd(tin, mt, cfg), 4)}


def _active(db: Session, eid: int) -> bool:
    return db.query(Job).filter(Job.kind == JOB, Job.episode_id == eid, Job.status.in_(("queued", "running"))).first() is not None


def view(db: Session, ep: Episode) -> dict:
    from . import guided
    lines = (ep.audio_transcript or {}).get("lines") or []
    v = stored(db, ep.id)
    sug = v.get("suggestion")
    if sug:
        sug = {**sug, "stale": sug.get("signature") != signature(lines)}
    job = db.query(Job).filter_by(kind=JOB, episode_id=ep.id).order_by(Job.id.desc()).first()
    return {"reference_video": guided.reference_video(db, ep.id) is not None, "lines": len(lines),
            "video_estimate": video_estimate(db, ep, lines), "text_estimate": text_estimate(db, ep, lines),
            "keys": {"gemini": bool(secret("gemini_api_key", db)), "openai": bool(secret("openai_api_key", db))},
            "text_cap": TEXT_CAP, "suggestion": sug, "busy": _active(db, ep.id), "job": S.job(job) if job else None}


def _episode(db: Session, eid: int) -> tuple[Episode, list[dict]]:
    from .audio_first import audio_episode
    ep = audio_episode(db, eid)
    lines = (ep.audio_transcript or {}).get("lines") or []
    if not lines:
        raise HTTPException(409, "there are no transcribed lines yet")
    return ep, lines


def _confirm(need: float, got: float | None, what: str) -> None:
    if got is None or got + 1e-9 < need:
        raise HTTPException(409, f"{what} can cost up to ${need:.4f}: confirm that amount to start (nothing was sent)")


def _store(db: Session, ep: Episode, rows: list[dict], lines: list[dict], source: str, model: str, usd: float,
           extra: dict | None = None) -> dict:
    v = stored(db, ep.id)
    v["suggestion"] = {"rows": rows, "source": source, "model": model, "usd": round(usd, 6), "made": time.time(),
                       "signature": signature(lines), "labels": labels_of(rows), "accepted": False, **(extra or {})}
    save(db, ep.id, v)
    return v["suggestion"]


# ================================================================== routes
@router.get("/episodes/{eid}/audio/speaker-suggestions")
def get_suggestions(eid: int, db: Session = Depends(get_db)):
    from .audio_first import audio_episode
    return view(db, audio_episode(db, eid))


class VideoIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=50)
    paid_tier: bool = True          # "my Gemini key is on a paid tier": the paid model, at its price
    use_free_tier: bool = False     # the free-tier models (Google may use the video to improve its models)


@router.post("/episodes/{eid}/audio/speaker-suggestions/video")
def suggest_from_video(eid: int, body: VideoIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (free when only the free tier is ticked): Gemini watches and listens to the private reference video and
    suggests a speaker per line. Queued as a job; the answer waits for the owner's review."""
    ep, lines = _episode(db, eid)
    est = video_estimate(db, ep, lines)
    if est is None:
        raise HTTPException(409, "there is no reference video for this episode: add it in guided step 1, or suggest from the text only")
    if not secret("gemini_api_key", db):
        raise HTTPException(409, "save the Gemini API key under Settings > Credentials first")
    models = _models(get_section(db, "guide"), body.paid_tier, body.use_free_tier)
    if not models:
        raise HTTPException(409, "tick \"my key is on a paid tier\" or \"use the free tier\" first (nothing was sent)")
    if _active(db, ep.id):
        raise HTTPException(409, "the speakers are already being suggested")
    _confirm(est["usd_max"] if body.paid_tier else 0.0, body.confirm_usd, "suggesting the speakers")
    job = enqueue(db, JOB, episode_id=ep.id, payload={"models": models, "estimate": est, "by": user, "signature": signature(lines),
                                                      "free_tier": body.use_free_tier, "paid_tier": body.paid_tier})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Speakers from the video asked by {user}"
                 + (f" (up to ${est['usd_max']:.2f})" if body.paid_tier else " (free tier only)")
                 + (", free tier allowed" if body.use_free_tier and body.paid_tier else "")))
    db.commit()
    return S.job(job)


class TextIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


@router.post("/episodes/{eid}/audio/speaker-suggestions/text")
def suggest_from_text(eid: int, body: TextIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: the configured text model guesses the speakers from the words only (lower confidence, at most TEXT_CAP).
    One call, never retried; the answer waits for the owner's review."""
    from . import prompt_writer as PW
    ep, lines = _episode(db, eid)
    est = text_estimate(db, ep, lines)
    _confirm(est["usd_max"], body.confirm_usd, "suggesting the speakers from the text")
    api_key = secret("openai_api_key", db)
    if not api_key:
        raise HTTPException(409, "save the OpenAI API key under Settings > Credentials first")
    cfg = PW.config(db)
    out = PW.call_openai(api_key, cfg["prompt_model"], TEXT_SYSTEM, prompt_for(lines, known_names(db, ep, lines), False),
                         est["max_output_tokens"])
    usd = PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg)
    try:
        raw = json.loads(_json_part(out["text"]))
    except ValueError:
        raise HTTPException(502, "the text model's answer was not valid JSON; not retried")
    rows = normalise(raw, lines, characters_for(db, ep), cap=TEXT_CAP)
    if not any(r["label"] for r in rows):
        raise HTTPException(502, "the text model suggested no speakers; not retried")
    _store(db, ep, rows, lines, "text", cfg["prompt_model"], usd,
           {"usage": {"input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"]}})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Speakers suggested from the text only by {cfg['prompt_model']} "
                                                            f"for {user} (${usd:.4f}); waiting for review"))
    db.commit()
    return view(db, ep)


def _json_part(text: str) -> str:
    """The JSON in an answer that may be wrapped in a code fence."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    return m.group(1) if m else t


class AcceptRow(BaseModel):
    line_id: str = Field(min_length=1, max_length=20)
    speaker: str = Field(min_length=1, max_length=40)


class AcceptIn(BaseModel):
    rows: list[AcceptRow] = Field(min_length=1, max_length=500)


@router.post("/episodes/{eid}/audio/speaker-suggestions/accept")
def accept(eid: int, body: AcceptIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: the rows they accepted (as they edited them) become the lines' speakers. Only those lines
    change; a suggestion made for other lines (edited since) is refused."""
    from .audio_first import gate, state
    ep, lines = _episode(db, eid)
    gate(ep, "label_audio")
    v = stored(db, ep.id)
    sug = v.get("suggestion")
    if not sug:
        raise HTTPException(409, "there is no suggestion to accept")
    if sug.get("signature") != signature(lines):
        raise HTTPException(409, "the lines changed since the suggestion was made: ask for a new suggestion")
    ids = {ln["id"] for ln in lines}
    want = {r.line_id: r.speaker.strip() for r in body.rows}
    unknown = [i for i in want if i not in ids]
    if unknown:
        raise HTTPException(422, f"no such line: {', '.join(unknown[:5])}")
    tr = dict(ep.audio_transcript)
    tr["lines"] = [{**ln, "speaker": want[ln["id"]]} if ln["id"] in want else ln for ln in lines]
    ep.audio_transcript = tr
    sug["accepted_lines"] = sorted(set(sug.get("accepted_lines") or []) | set(want), key=lambda x: int(re.sub(r"\D", "", x) or 0))
    sug["accepted"] = True
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Suggested speakers accepted by {user} for {len(want)} line(s)"))
    db.commit()
    return state(db, ep)


@router.delete("/episodes/{eid}/audio/speaker-suggestions")
def discard(eid: int, db: Session = Depends(get_db)):
    from .audio_first import audio_episode
    ep = audio_episode(db, eid)
    v = stored(db, ep.id)
    if v.pop("suggestion", None) is not None:
        save(db, ep.id, v)
        db.commit()
    return view(db, ep)


# ================================================================== the job
from .tasks import Ctx, task  # noqa: E402


@task
def speaker_suggest(ctx: Ctx) -> dict:
    """Gemini watches and listens to the reference video once and suggests a speaker per line (words only). The
    uploaded file is deleted from Google afterwards, also when the request fails."""
    from . import acting_analysis as AA
    from . import guided
    import shutil
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    ref = guided.reference_video(db, ep.id)
    if not ref:
        raise ValueError("the reference video was removed: add it again in guided step 1")
    lines = (ep.audio_transcript or {}).get("lines") or []
    if not lines:
        raise ValueError("there are no transcribed lines")
    api_key = secret("gemini_api_key", db)
    if not api_key:
        raise ValueError("save the Gemini API key under Settings > Credentials first")
    gcfg = get_section(db, "guide")
    free = set(gcfg.get("acting_free_models") or [])
    prompt = prompt_for(lines, known_names(db, ep, lines), True, _offset(ref))
    body = {"contents": [{"parts": [{"file_data": {"mime_type": ref["content_type"], "file_uri": None},
                                     "video_metadata": {"fps": FPS}}, {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                                 "maxOutputTokens": max_tokens_for(len(lines)), "thinkingConfig": {"thinkingLevel": "low"}}}
    folder = ctx.folder("episodes", ep.id, f"speakers-job{job.id}")
    video = storage().get_to_file(ref["key"], folder / f"reference{Path(ref['key']).suffix or '.mp4'}")
    try:
        with AA.client() as c:
            f = None
            try:
                f = AA.upload(c, api_key, video, ref["content_type"], f"episode-{ep.id}-speakers")
                ctx.log("reference video uploaded to Gemini (with its sound)")
                body["contents"][0]["parts"][0]["file_data"]["file_uri"] = f["uri"]
                model, d = AA.generate(c, api_key, list(p.get("models") or [gcfg["acting_model"]]), body, ctx.log)
            finally:
                if f is not None:
                    ctx.log("uploaded video deleted from Gemini" if AA.delete(c, api_key, f["name"])
                            else "could not confirm the uploaded video was deleted from Gemini (it expires after 48 h)")
    except httpx.HTTPError as e:
        raise ProviderError(f"Gemini could not be reached ({type(e).__name__}); not retried")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    u = d.get("usageMetadata") or {}
    tin, tout = int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
    usd = 0.0 if model in free else AA.cost_usd(tin, tout, gcfg)
    try:
        raw = json.loads(AA.answer_text(d))
    except ValueError:
        raise ProviderError("Gemini's answer was not valid JSON; not retried")
    rows = normalise(raw, lines, characters_for(db, ep))
    if not any(r["label"] for r in rows):
        raise ProviderError("Gemini suggested no speakers; not retried")
    _store(db, ep, rows, lines, "video", model, usd,
           {"usage": {"input_tokens": tin, "output_tokens": tout}, "free_tier": model in free})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Speakers suggested from the video by {model} (${usd:.4f}); "
                                                            "waiting for review"))
    db.commit()
    return {"lines": len(rows), "labelled": sum(1 for r in rows if r["label"]), "usd": round(usd, 6)}
