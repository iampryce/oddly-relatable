"""Acting analysis of the episode's reference video (guided flow, step 2).

The owner's private reference video (guided.py keeps it under private/) is uploaded once to the Gemini Files API
(resumable upload), then read in up to three batches of shots: each request carries video_metadata {fps 5,
start_offset, end_offset} for that batch's time range, so only that part of the video is billed. The answer is JSON:
per character traits, posture, expressions, gestures and reactions; per shot timed acting beats and 1-3 key frame
times; per character the talking style. The uploaded file is deleted from Google afterwards, also when a batch fails.

Cost: about 300 input tokens per second of video at fps 5 plus the prompt, at the model's input price, and at most
maxOutputTokens of answer per batch at the output price. The estimate is shown first and the request must carry it
(confirm_usd, HTTP 409 otherwise). Paid calls are never retried. The free tier is only used when the owner ticks it for
this run (free-tier uploads may be used by Google to improve its models); its models are tried only after the paid model
answers 429 or 503.

Key frames: after the analysis, ffmpeg takes each shot's key frame times from the reference video into private
storage. They are for the owner to look at only: they are never sent to an image or video generator.

The key comes only from secrets_store.secret("gemini_api_key"): it is sent in a header, never logged or returned.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, Job, Setting, StoryboardScene
from .providers import ProviderError
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

BASE = "https://generativelanguage.googleapis.com"
TOKENS_PER_SECOND = 300        # video at fps 5 (Gemini's own figure for the default resolution)
CHARS_PER_TOKEN = 3.5
MAX_OUTPUT_TOKENS = 30000
BATCHES = 3
PAD = 1.0                      # seconds of video before and after each batch
FALLBACK_SHOT_SECONDS = 4.0    # shot length when the episode has no shot plan yet
MAX_KEY_FRAMES = 3
JOB = "acting_analysis"
POLL_SECONDS = 5.0
POLL_LIMIT = 120

_transport = None              # tests only: an httpx transport (httpx.MockTransport) instead of the network


def set_test_transport(t) -> None:
    global _transport, POLL_SECONDS
    _transport = t
    POLL_SECONDS = 0.0 if t is not None else 5.0


def key(eid: int) -> str:
    return f"acting:{eid}"


# ------------------------------------------------------------------ shots and batches (pure)
def fallback_shots(seconds: float) -> list[dict]:
    n = max(1, math.ceil(seconds / FALLBACK_SHOT_SECONDS))
    return [{"shot": i + 1, "start": round(i * FALLBACK_SHOT_SECONDS, 2),
             "end": round(min(seconds, (i + 1) * FALLBACK_SHOT_SECONDS), 2), "people": []} for i in range(n)]


def make_batches(shots: list[dict], n: int = BATCHES) -> list[dict]:
    """Contiguous groups of shots, as even as possible: [{a, b, lo, hi, shots}] with a and b the first and last shot
    number and [lo, hi] the video range sent (the shots plus PAD on each side)."""
    shots = sorted(shots, key=lambda s: s["shot"])
    if not shots:
        return []
    n = max(1, min(n, len(shots)))
    size, extra = divmod(len(shots), n)
    out, i = [], 0
    for k in range(n):
        part = shots[i:i + size + (1 if k < extra else 0)]
        i += len(part)
        out.append({"a": part[0]["shot"], "b": part[-1]["shot"], "lo": round(max(0.0, part[0]["start"] - PAD), 2),
                    "hi": round(part[-1]["end"] + PAD, 2), "shots": part})
    return out


def normalise(part) -> dict:
    """One batch's answer as {characters, shots, talking_style}. Seen in practice: a bare list of shots, or a list
    wrapping one or more {characters, shots, talking_style} objects."""
    out = {"characters": {}, "shots": [], "talking_style": {}}
    items = part if isinstance(part, list) else [part]
    for it in items:
        if not isinstance(it, dict):
            continue
        if "shot" in it and "shots" not in it:      # an element of a bare list of shots
            out["shots"].append(it)
            continue
        for k in ("characters", "talking_style"):
            if isinstance(it.get(k), dict):
                out[k].update(it[k])
        out["shots"] += [s for s in (it.get("shots") or []) if isinstance(s, dict)]
    return out


def merge(result: dict, part: dict) -> dict:
    for k in ("characters", "talking_style"):
        result[k].update(part[k])
    have = {s.get("shot") for s in result["shots"]}
    result["shots"] += [s for s in part["shots"] if s.get("shot") not in have]
    result["shots"].sort(key=lambda s: (s.get("shot") is None, s.get("shot") or 0))
    return result


def key_frame_times(shot: dict) -> list[float]:
    out = []
    for t in shot.get("key_frame_times") or []:
        try:
            out.append(round(float(t), 1))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))[:MAX_KEY_FRAMES]


# ------------------------------------------------------------------ prompt (pure)
PROMPT = """You are an animation director. Watch this reference video. We are remaking it as a 2D stick-figure cartoon
with the SAME audio and timing, and we need the ACTING, not the look.

Our cast names: {cast}.
Map the people in the video to these names from what is said and done.

Our shot list (seconds, same timeline as the video): {shots}

THIS REQUEST: you are given only the part of the video from {lo} s to {hi} s. Describe ONLY shots {a} to {b}. {extra}

Return JSON only:
{{
 "characters": {{"<name>": {{"traits": "...", "posture": "...", "typical_expressions": "...", "tics_and_gestures": "...",
                 "how_they_react": "..."}}}},
 "shots": [{{"shot": <n>, "what_the_reference_shows": "who is on screen and framing in the reference at this time",
            "beats": [{{"t_start": <sec>, "t_end": <sec>, "character": "<name>", "on_word": "<word in the audio or null>",
                       "expression": "...", "eyes_and_gaze": "...", "head_and_body": "...", "hands": "...",
                       "hold_or_move": "hold|move", "intensity": "subtle|clear|big"}}],
            "key_frame_times": [<sec>, ...]}}],
 "talking_style": {{"<name>": "how they deliver lines: pace, pauses, where they look up, emphasis"}}
}}
Rules: times are absolute seconds in the video, to 0.1 s. Every shot in our list gets an entry; if the reference shows a
different person than our shot, still describe what OUR shot's characters should be doing at that moment, based on what
the reference shows of them nearby. Describe acting precisely enough for an animator (e.g. "eyes snap wide on 'no',
head jerks back 10 degrees, jaw drops and holds 0.6 s"). key_frame_times: 1-3 moments per shot that best show the acting.
BEAT DENSITY: give a new beat every time ANY on-screen character changes expression, gaze, head or hands, and at least
one beat every 1.5 s. Reaction shots of 2 s need 2-4 beats (e.g. still -> snap -> hold -> settle)."""


def prompt_for(cast: list[str], shots: list[dict], batch: dict, first: bool) -> str:
    extra = ("Also fill characters and talking_style for every cast member." if first
             else "Return empty objects for characters and talking_style.")
    return PROMPT.format(cast=", ".join(cast) or "(not named yet: call them Person 1, Person 2, ...)",
                         shots=json.dumps(shots), lo=batch["lo"], hi=batch["hi"], a=batch["a"], b=batch["b"], extra=extra)


def request_body(file_uri: str, mime: str, batch: dict, prompt: str) -> dict:
    return {"contents": [{"parts": [{"file_data": {"mime_type": mime, "file_uri": file_uri},
                                     "video_metadata": {"fps": 5, "start_offset": f"{batch['lo']}s",
                                                        "end_offset": f"{batch['hi']}s"}},
                                    {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4,
                                 "maxOutputTokens": MAX_OUTPUT_TOKENS, "thinkingConfig": {"thinkingLevel": "low"}}}


# ------------------------------------------------------------------ cost (pure)
def estimate(shots: list[dict], cast: list[str], cfg: dict) -> dict:
    """Input: video seconds of every batch x 300 tokens + the prompt; output: at most MAX_OUTPUT_TOKENS per batch.
    usd_max is what the owner confirms."""
    batches = make_batches(shots)
    seconds = sum(b["hi"] - b["lo"] for b in batches)
    prompt_tokens = sum(math.ceil(len(prompt_for(cast, shots, b, i == 0)) / CHARS_PER_TOKEN) for i, b in enumerate(batches))
    tin = int(seconds * TOKENS_PER_SECOND) + prompt_tokens
    tout_max = MAX_OUTPUT_TOKENS * len(batches)
    tout_typ = min(tout_max, 8000 * len(batches))
    p_in, p_out = float(cfg["acting_usd_in"]), float(cfg["acting_usd_out"])
    usd = lambda o: round(tin * p_in / 1e6 + o * p_out / 1e6, 4)
    return {"model": cfg["acting_model"], "batches": len(batches), "video_seconds": round(seconds, 1),
            "input_tokens": tin, "max_output_tokens": tout_max, "usd_typical": usd(tout_typ), "usd_max": usd(tout_max),
            "usd_per_mtok": {"input": p_in, "output": p_out},
            "label": f"{len(batches)} request(s), {seconds:.0f} s of video: about ${usd(tout_typ):.2f}, at most ${usd(tout_max):.2f}"}


def cost_usd(tin: int, tout: int, cfg: dict) -> float:
    return round(tin * float(cfg["acting_usd_in"]) / 1e6 + tout * float(cfg["acting_usd_out"]) / 1e6, 6)


# ------------------------------------------------------------------ Gemini over HTTP
def plain_error(status: int, where: str) -> str:
    text = {400: "Gemini refused the request (the video or the settings were not accepted)",
            401: "Gemini did not accept the API key saved in Settings > Credentials",
            403: "Gemini did not accept the API key saved in Settings > Credentials",
            404: "this Gemini model is not available to your key: check the model name in Settings > Guided generation",
            429: "Gemini is busy or your quota is used up: try again later, or add billing to the Google project",
            503: "Gemini is overloaded right now: try again in a few minutes"}.get(status, "Gemini returned an error")
    return f"{where}: {text} (HTTP {status}); not retried"


def client() -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=900) if _transport is not None else httpx.Client(timeout=900)


def upload(c: httpx.Client, api_key: str, path: Path, mime: str, name: str) -> dict:
    """Resumable upload to the Files API; waits until the file is ACTIVE. Returns the file resource."""
    h = {"x-goog-api-key": api_key}
    size = path.stat().st_size
    r = c.post(f"{BASE}/upload/v1beta/files", json={"file": {"display_name": name}},
               headers={**h, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                        "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": mime})
    if r.status_code >= 400:
        raise ProviderError(plain_error(r.status_code, "Upload"))
    url = r.headers.get("x-goog-upload-url")
    if not url:
        raise ProviderError("Upload: Gemini did not return an upload address; not retried")
    with open(path, "rb") as f:
        r = c.post(url, content=f.read(), headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"})
    if r.status_code >= 400:
        raise ProviderError(plain_error(r.status_code, "Upload"))
    f = r.json()["file"]
    for _ in range(POLL_LIMIT):
        if f.get("state") == "ACTIVE":
            return f
        if f.get("state") == "FAILED":
            delete(c, api_key, f["name"])
            raise ProviderError("Gemini could not process the reference video; not retried")
        time.sleep(POLL_SECONDS)
        r = c.get(f"{BASE}/v1beta/{f['name']}", headers=h)
        if r.status_code >= 400:
            raise ProviderError(plain_error(r.status_code, "Upload"))
        f = r.json()
    delete(c, api_key, f["name"])
    raise ProviderError("Gemini took too long to process the reference video; not retried")


def delete(c: httpx.Client, api_key: str, name: str) -> bool:
    try:
        r = c.delete(f"{BASE}/v1beta/{name}", headers={"x-goog-api-key": api_key})
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def generate(c: httpx.Client, api_key: str, models: list[str], body: dict, log) -> tuple[str, dict]:
    """One request, tried on the next model only when the previous one answered 429 or 503 (the free-tier list).
    Returns (model used, response JSON)."""
    r = None
    for m in models:
        r = c.post(f"{BASE}/v1beta/models/{m}:generateContent", json=body, headers={"x-goog-api-key": api_key})
        log(f"{m}: HTTP {r.status_code}")
        if r.status_code not in (429, 503):
            break
    if r.status_code >= 400:
        raise ProviderError(plain_error(r.status_code, f"Analysis ({m})"))
    return m, r.json()


def answer_text(d: dict) -> str:
    parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


# ------------------------------------------------------------------ episode data
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = v
    else:
        db.add(Setting(key=key(eid), value=v))


def cast_names(db: Session, ep: Episode) -> tuple[list[str], dict[str, str]]:
    names = {c.key: c.name for c in db.query(Character)}
    keys: list[str] = []
    for sc in db.query(StoryboardScene).filter_by(episode_id=ep.id).order_by(StoryboardScene.position):
        keys += [k for k in sc.characters or [] if k not in keys]
    keys += [c.key for c in db.query(Character).filter_by(scope="episode", episode_id=ep.id) if c.key not in keys]
    return [names.get(k, k) for k in keys], names


def shot_list(db: Session, ep: Episode, seconds: float | None) -> tuple[list[dict], str]:
    """The storyboard's shot plan when there is one, else even slices of the video."""
    from . import shot_frames as SF
    _cast, names = cast_names(db, ep)
    plan = SF.stored(db, ep.id).get("shots") or []
    if plan:
        return [{"shot": int(s["index"]), "start": round(float(s["t0"]), 2), "end": round(float(s["t1"]), 2),
                 "people": [names.get(k, k) for k in s.get("people") or []]} for s in plan], "storyboard"
    if seconds:
        return fallback_shots(float(seconds)), "even slices"
    return [], ""


def config(db: Session) -> dict:
    return get_section(db, "guide")


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _active(db: Session, eid: int):
    return db.query(Job).filter(Job.kind == JOB, Job.episode_id == eid, Job.status.in_(("queued", "running")))


def frames_out(v: dict) -> dict:
    """Signed links to the private key frames, per shot number."""
    return {str(n): [{"t": f["t"], "url": storage().url(f["key"])} for f in fs] for n, fs in (v.get("frames") or {}).items()}


def plan(db: Session, ep: Episode) -> dict:
    from . import guided
    ref = guided.reference_video(db, ep.id)
    cast, _names = cast_names(db, ep)
    shots, source = shot_list(db, ep, ref["seconds"] if ref else None)
    cfg = config(db)
    return {"reference_video": ref, "cast": cast, "shots": shots, "shots_from": source,
            "estimate": estimate(shots, cast, cfg) if shots else None,
            "free_models": list(cfg.get("acting_free_models") or [])}


def view(db: Session, ep: Episode) -> dict:
    v = stored(db, ep.id)
    job = db.query(Job).filter_by(kind=JOB, episode_id=ep.id).order_by(Job.id.desc()).first()
    p = plan(db, ep)
    return {**p, "key_set": bool(secret("gemini_api_key", db)), "result": v.get("result"), "made": v.get("made"),
            "model_used": v.get("model_used"), "usage": v.get("usage"), "usd": v.get("usd"), "partial": v.get("partial"),
            "accepted": bool(v.get("accepted")), "frames": frames_out(v), "busy": _active(db, ep.id).first() is not None,
            "job": S.job(job) if job else None}


# ------------------------------------------------------------------ routes
class StartIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=50)
    use_free_tier: bool = False


@router.get("/episodes/{eid}/acting-analysis")
def get_analysis(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


@router.post("/episodes/{eid}/acting-analysis")
def start(eid: int, body: StartIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: starts only when the request carries the most it can cost, as shown to the owner."""
    ep = _episode(db, eid)
    p = plan(db, ep)
    if not p["reference_video"]:
        raise HTTPException(409, "upload the reference video first (step 1)")
    if not p["shots"]:
        raise HTTPException(409, "the length of the reference video is unknown and there is no storyboard yet: make the storyboard first")
    if not secret("gemini_api_key", db):
        raise HTTPException(409, "save the Gemini API key under Settings > Credentials first")
    if _active(db, ep.id).first():
        raise HTTPException(409, "the acting analysis is already running")
    est = p["estimate"]
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"the analysis can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    cfg = config(db)
    models = [cfg["acting_model"]] + (list(cfg.get("acting_free_models") or []) if body.use_free_tier else [])
    job = enqueue(db, JOB, episode_id=ep.id, payload={"models": models, "estimate": est, "by": user,
                                                      "free_tier": body.use_free_tier})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Acting analysis asked by {user} (up to ${est['usd_max']:.2f}"
                 + (", free tier allowed" if body.use_free_tier else "") + ")"))
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/acting-analysis/accept")
def accept(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: the analysis reads right and the next steps may use it."""
    ep = _episode(db, eid)
    v = stored(db, ep.id)
    if not v.get("result"):
        raise HTTPException(409, "there is no acting analysis to accept yet")
    v["accepted"] = True
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="approval", message=f"Acting analysis accepted by {user}"))
    db.commit()
    return view(db, ep)


# ------------------------------------------------------------------ the job
from .tasks import Ctx, task  # noqa: E402


def extract_key_frames(ctx: Ctx, eid: int, video: Path, result: dict, folder: Path) -> dict:
    """{shot number: [{t, key}]} in private storage. Skipped (empty) when ffmpeg is not configured."""
    from .config import get_settings
    from .media import sample_frames_at
    if not get_settings().ffmpeg:
        ctx.log("ffmpeg is not configured: key frames skipped")
        return {}
    out = {}
    for s in result["shots"]:
        times = key_frame_times(s)
        if not times or s.get("shot") is None:
            continue
        got = sample_frames_at(video, folder / f"shot{s['shot']}", times)
        for f, t in got:
            k = f"private/episodes/{eid}/acting/shot{s['shot']}-{t:.1f}s.jpg"
            storage().put_file(k, f, "image/jpeg")
            out.setdefault(str(s["shot"]), []).append({"t": t, "key": k})
    return out


@task
def acting_analysis(ctx: Ctx) -> dict:
    from . import guided
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    ref = guided.reference_video(db, ep.id)
    if not ref:
        raise ValueError("the reference video was removed: upload it again")
    cfg = config(db)
    cast, _names = cast_names(db, ep)
    shots, _src = shot_list(db, ep, ref["seconds"])
    batches = make_batches(shots)
    free = set(cfg.get("acting_free_models") or [])
    folder = ctx.folder("episodes", ep.id, f"acting-job{job.id}")
    video = storage().get_to_file(ref["key"], folder / f"reference{Path(ref['key']).suffix or '.mp4'}")
    api_key = secret("gemini_api_key", db)
    if not api_key:
        raise ValueError("save the Gemini API key under Settings > Credentials first")
    result = {"characters": {}, "shots": [], "talking_style": {}}
    tin = tout = 0
    usd = 0.0
    used, error = [], ""
    try:
        with client() as c:
            f = None
            try:
                f = upload(c, api_key, video, ref["content_type"], f"episode-{ep.id}-reference")
                ctx.log(f"reference video uploaded to Gemini ({ref['seconds'] or '?'} s)")
                for i, b in enumerate(batches):
                    body = request_body(f["uri"], ref["content_type"], b, prompt_for(cast, shots, b, i == 0))
                    try:
                        model, d = generate(c, api_key, list(p.get("models") or [cfg["acting_model"]]), body, ctx.log)
                    except ProviderError as e:
                        error = str(e)
                        break
                    u = d.get("usageMetadata") or {}
                    bi, bo = int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
                    tin, tout = tin + bi, tout + bo
                    usd += 0.0 if model in free else cost_usd(bi, bo, cfg)
                    used.append(model)
                    try:
                        part = normalise(json.loads(answer_text(d)))
                    except ValueError:
                        ctx.log(f"shots {b['a']}-{b['b']}: the answer was not valid JSON (kept out)")
                        continue
                    merge(result, part)
                    ctx.log(f"shots {b['a']}-{b['b']}: {len(part['shots'])} shot(s) described by {model}")
            finally:
                if f is not None:
                    ctx.log("uploaded video deleted from Gemini" if delete(c, api_key, f["name"])
                            else "could not confirm the uploaded video was deleted from Gemini (it expires after 48 h)")
    except httpx.HTTPError as e:
        raise ProviderError(f"Gemini could not be reached ({type(e).__name__}); not retried")
    frames = extract_key_frames(ctx, ep.id, video, result, folder) if result["shots"] else {}
    import shutil
    shutil.rmtree(folder, ignore_errors=True)
    if not result["shots"]:
        raise ProviderError(error or "Gemini returned no usable acting notes; not retried")
    v = {"result": result, "made": time.time(), "model_used": sorted(set(used)), "accepted": False, "frames": frames,
         "usage": {"input_tokens": tin, "output_tokens": tout}, "usd": round(usd, 4), "partial": error or None,
         "estimate": p.get("estimate")}
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="episode",
                 message=f"Acting analysis ready: {len(result['shots'])} shot(s), ${usd:.4f}" + (f" (stopped early: {error})" if error else "")))
    db.commit()
    return {"shots": len(result["shots"]), "usd": round(usd, 4), "partial": bool(error)}
