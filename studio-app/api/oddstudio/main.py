"""Oddly Relatable Studio API (FastAPI). Run: uvicorn oddstudio.main:app

All /api routes except health, sign-in and signed media require the owner's session. The database schema is managed
by Alembic (`alembic upgrade head`); tests create it directly."""
from __future__ import annotations

import json
import logging
import mimetypes
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import audio_first, engine, routes_characters, routes_episodes, serialize as S
from .auth import COOKIE, check_rate, current_user, make_token, record_failure, verify_password
from .config import REPO_ROOT, get_settings
from .db import get_db, new_session
from .models import Asset, Character, CharacterAsset, Episode, Event, Idea, Job, now
from .queue import redis_client
from .settings_store import DEFAULTS, all_sections, integrations_status, put_section
from .storage import LocalStorage, sha256_file, storage, verify_local

log = logging.getLogger("oddstudio")

# Character 01 uses the approved repository artwork (production/characters/character-01.json); expression names map to
# its six approved poses. It is locked: the studio never edits or regenerates approved artwork.
CHARACTER_01_EXPRESSIONS = {
    "neutral": "01", "calm": "01", "worried": "02", "nervous": "02", "on phone": "02", "shocked": "03", "frozen": "03",
    "surprised": "03", "laughing": "04", "happy": "04", "excited": "04", "pleading": "05", "begging": "05", "sorry": "05",
    "deadpan": "06", "annoyed": "06", "unimpressed": "06", "smug": "06",
}


def seed(db: Session) -> None:
    if db.query(Character).filter_by(key="character-01").first():
        return
    reg = json.loads((REPO_ROOT / "production" / "characters" / "character-01.json").read_text(encoding="utf-8"))
    c = Character(key="character-01", name="Character 01", locked=True, art_status="approved", bubble_style="him",
                  description="The channel's lead: an ordinary, easily rattled guy whose everyday panics are the joke.",
                  visual_description="Locked canonical artwork (bald cream head, rust turtleneck). Not regenerated.",
                  engine_character="character-01", registry_path="production/characters/character-01.json",
                  expressions=CHARACTER_01_EXPRESSIONS, default_expression="neutral")
    db.add(c)
    db.flush()
    for pid, p in reg["poses"].items():   # copies for display in the dashboard; the engine reads the repository files
        src = REPO_ROOT / p["file"]
        key = f"characters/character-01/poses/{pid}-{p['name']}.png"
        storage().put_file(key, src, "image/png")
        db.add(CharacterAsset(character_id=c.id, kind="pose", expression=p["name"], storage_key=key, sha256=sha256_file(src),
                              feet=p["feet"], figure_height=p["figureHeight"], status="approved"))
    db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if s.env == "production":
        problems = s.check()
        if problems:
            raise RuntimeError("Configuration incomplete: " + "; ".join(problems))
    with new_session() as db:
        seed(db)
    yield


app = FastAPI(title="Oddly Relatable Studio", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(routes_episodes.router)
app.include_router(routes_characters.router)
app.include_router(audio_first.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"detail": "Internal error; see the API logs"}, status_code=500)


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=500)


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    s = get_settings()
    client = request.client.host if request.client else "unknown"
    check_rate(client)
    if not s.owner_email or not s.owner_password_hash:
        raise HTTPException(503, "The owner account is not configured on the server")
    if body.email.strip().lower() != s.owner_email or not verify_password(body.password, s.owner_password_hash):
        record_failure(client)
        raise HTTPException(401, "Wrong email or password")
    response.set_cookie(COOKIE, make_token(s.owner_email), httponly=True, secure=s.cookie_secure, samesite="strict",
                        max_age=int(timedelta(hours=s.session_hours).total_seconds()), path="/")
    return {"email": s.owner_email}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: str = Depends(current_user)):
    return {"email": user}


# ------------------------------------------------------------------ health, overview, activity
@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    r = redis_client()
    # queue: "redis" (connected), "redis-down", "database-polling" (development worker without Redis) or "none".
    if r is not None:
        try:
            mode = "redis" if r.ping() else "redis-down"
        except Exception:
            mode = "redis-down"
    else:
        mode = "none" if get_settings().env == "production" else "database-polling"
    return {"ok": True, "database": True, "queue": mode}


@app.get("/api/overview", dependencies=[Depends(current_user)])
def overview(db: Session = Depends(get_db)):
    stages = dict(db.query(Episode.stage, func.count()).group_by(Episode.stage).all())
    count = lambda *names: sum(stages.get(n, 0) for n in names)  # noqa: E731
    return {
        "videos_created": db.query(Asset).filter_by(kind="video").count(),
        "episodes": sum(stages.values()),
        "ideas_awaiting": db.query(Idea).filter(Idea.status.in_(["draft", "submitted"])).count(),
        "scripts_awaiting_approval": count("script_review"),
        "storyboards_awaiting_approval": count("storyboard_review"),
        "processing": count("script_generating", "storyboard_generating", "producing", "publishing"),
        "videos_awaiting_review": count("video_review"),
        "completed": count("final_approved", "published"),
        "published": count("published"),
        "failed_jobs": db.query(Job).filter_by(status="failed").count(),
        "active_jobs": db.query(Job).filter(Job.status.in_(["queued", "running"])).count(),
        "stages": stages,
        "activity": [{"episode_id": e.episode_id, "kind": e.kind, "message": e.message, "created_at": S.ts(e.created_at)}
                     for e in db.query(Event).order_by(Event.id.desc()).limit(25)],
    }


# ------------------------------------------------------------------ jobs
@app.get("/api/jobs", dependencies=[Depends(current_user)])
def list_jobs(status: str | None = None, episode_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status.in_(status.split(",")))
    if episode_id:
        q = q.filter_by(episode_id=episode_id)
    return [S.job(j) for j in q.order_by(Job.id.desc()).limit(min(limit, 500))]


@app.get("/api/jobs/{jid}", dependencies=[Depends(current_user)])
def job_detail(jid: int, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    return S.job(j, with_log=True)


# ------------------------------------------------------------------ library
@app.get("/api/library", dependencies=[Depends(current_user)])
def library(db: Session = Depends(get_db)):
    out = []
    for ep in db.query(Episode).order_by(Episode.updated_at.desc()):
        videos = db.query(Asset).filter_by(episode_id=ep.id, kind="video").order_by(Asset.id.desc()).all()
        if videos:
            out.append({**S.episode_summary(ep), "videos": [S.asset(v) for v in videos]})
    return out


# ------------------------------------------------------------------ settings
@app.get("/api/settings", dependencies=[Depends(current_user)])
def get_all_settings(db: Session = Depends(get_db)):
    from .capabilities import status
    from .secrets_store import presence
    tests = provider_tests(db)
    return {"sections": all_sections(db), "integrations": integrations_status(), "environments": engine.environments(),
            "credentials": presence(db), "tests": tests, "capabilities": status(db, tests)}


def provider_tests(db: Session) -> dict:
    """Latest test job per target, with a playable/viewable link for voice and image tests."""
    out = {}
    for j in db.query(Job).filter_by(kind="provider_test").order_by(Job.id.desc()).limit(200):
        t = (j.payload or {}).get("target")
        if not t or t in out:
            continue
        row = {"job_id": j.id, "status": j.status, "error": j.error, "result": j.result or {},
               "attempts": j.attempts, "finished_at": S.ts(j.finished_at)}
        aid = (j.result or {}).get("asset_id")
        if aid and (a := db.get(Asset, aid)):
            row["url"], row["content_type"] = storage().url(a.storage_key), a.content_type
        out[t] = row
    return out


class CredentialsIn(BaseModel):
    values: dict[str, str | None]


@app.put("/api/settings/credentials", dependencies=[Depends(current_user)])
def put_credentials(body: CredentialsIn, db: Session = Depends(get_db)):
    """Write-only: values are encrypted at rest and never returned (only whether each one is set)."""
    from .secrets_store import put_secrets
    try:
        return put_secrets(db, body.values)
    except ValueError as e:
        raise HTTPException(422, str(e))


class ProviderTestIn(BaseModel):
    target: str = Field(max_length=60)


@app.post("/api/settings/test", dependencies=[Depends(current_user)])
def test_provider(body: ProviderTestIn, db: Session = Depends(get_db)):
    """Queue a real test job that the worker runs with this provider (see tasks_providers)."""
    from .queue import enqueue
    from .tasks_providers import TARGETS
    stage, _, name = body.target.partition(":")
    if name not in TARGETS.get(stage, ()):
        raise HTTPException(422, f"unknown provider test {body.target!r}")
    return S.job(enqueue(db, "provider_test", payload={"target": body.target}))


# ------------------------------------------------------------------ hosted model comparison (fal.ai)
class CompareIn(BaseModel):
    models: list[str] = Field(default_factory=lambda: ["wan-2.2-a14b", "ltx-2-19b", "wan-2.2-5b"])
    attempts: int = Field(default=2, ge=1, le=3)
    scenario: str = "talk"
    confirm: bool = False


@app.post("/api/motion/compare", dependencies=[Depends(current_user)])
def motion_compare(body: CompareIn, db: Session = Depends(get_db)):
    """Without confirm: the plan with the estimated cost (nothing is spent). With confirm: queue the comparison."""
    from . import fal
    from .comparison import plan
    from .queue import enqueue
    from .secrets_store import secret
    from .comparison import SCENARIOS
    bad = [m for m in body.models if m not in fal.MODELS]
    if bad:
        raise HTTPException(422, f"unknown models: {bad}")
    if body.scenario not in SCENARIOS:
        raise HTTPException(422, f"unknown scenario {body.scenario!r}")
    p = plan(db, body.models, body.attempts, body.scenario)
    p["key_configured"] = bool(secret("fal_key", db))
    p["models_available"] = {k: {"label": v["label"], "price": v["price"], "licence": v["licence"]} for k, v in fal.MODELS.items()}
    if not body.confirm:
        return p
    if db.query(Job).filter(Job.kind.in_(["motion_compare", "motion_generate"]), Job.status.in_(["queued", "running"])).count():
        raise HTTPException(409, "A comparison is already running")
    if not p["key_configured"]:
        raise HTTPException(409, "Save the fal.ai API key under Settings > Credentials first")
    if not p["fits_budget"]:
        raise HTTPException(409, f"Estimated ${p['estimated_total_usd']:.2f} exceeds the remaining experimental budget")
    j = enqueue(db, "motion_compare", payload={"models": body.models, "attempts": body.attempts, "scenario": body.scenario})
    return {**p, "job": S.job(j)}


@app.get("/api/motion/comparison", dependencies=[Depends(current_user)])
def motion_comparison(db: Session = Depends(get_db)):
    """Everything the Production page's Motion Model Comparison section shows. Never includes the API key."""
    from . import fal
    from .comparison import SCENARIOS, TITLE, plan
    from .secrets_store import secret
    ep = db.query(Episode).filter_by(title=TITLE).first()
    jobs = db.query(Job).filter(Job.kind.in_(["motion_compare", "motion_generate"])).order_by(Job.id.desc()).limit(40).all()
    assets = {a.job_id: a for a in db.query(Asset).filter_by(episode_id=ep.id)} if ep else {}
    clips = []
    for j in jobs:
        if j.kind != "motion_generate":
            continue
        pl, res = j.payload or {}, j.result or {}
        a = assets.get(j.id)
        clips.append({"job_id": j.id, "status": j.status, "model": pl.get("model"), "attempt": pl.get("attempt"),
                      "scenario": pl.get("scenario", "talk"),
                      "progress": j.progress or {}, "error": j.error, "tries": j.attempts,
                      "estimated_usd": fal.estimate(pl["model"], {}) if pl.get("model") in fal.MODELS else None,
                      "actual_usd": res.get("actual_usd"), "seconds": res.get("seconds"), "width": res.get("width"),
                      "height": res.get("height"), "url": storage().url(a.storage_key) if a else None})
    setup = next((j for j in jobs if j.kind == "motion_compare"), None)
    running = any(j.status in ("queued", "running") for j in jobs)
    frame = (db.query(Asset).filter_by(episode_id=ep.id, kind="scene-reference").order_by(Asset.id.desc()).first() if ep else None)
    return {"episode_id": ep.id if ep else None, "clips": clips, "running": running, "plan": plan(db, list(fal.MODELS), 2),
            "plans": {k: plan(db, list(fal.MODELS), 2, k) for k in SCENARIOS},
            "scenarios": {k: {"label": v["label"], "prompt": v["prompt"]} for k, v in SCENARIOS.items()},
            "setup": {"job_id": setup.id, "status": setup.status, "error": setup.error} if setup else None,
            "models": {k: {"label": v["label"], "price": v["price"], "licence": v["licence"], "estimated_usd": fal.estimate(k, {})}
                       for k, v in fal.MODELS.items()},
            "key_configured": bool(secret("fal_key", db)), "spent_usd": round(fal.spent(db)["total"], 2), "budget_usd": fal.budget(db),
            "first_frame_url": storage().url(frame.storage_key) if frame else None}


# ------------------------------------------------------------------ studio sets (candidates -> owner approval)
class SetIn(BaseModel):
    label: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=10, max_length=1200)


class SetDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    blocking: dict | None = None


@app.get("/api/sets", dependencies=[Depends(current_user)])
def list_sets(db: Session = Depends(get_db)):
    from . import sets
    out = []
    for sid, r in sorted(sets.records(db).items(), key=lambda kv: -kv[1].get("created", 0)):
        a, pv = db.get(Asset, r.get("asset_id")), db.get(Asset, r.get("preview_asset_id"))
        out.append({"id": sid, **{k: v for k, v in r.items() if k not in ("asset_id", "preview_asset_id")},
                    "url": storage().url(a.storage_key) if a else None, "preview_url": storage().url(pv.storage_key) if pv else None})
    jobs = db.query(Job).filter_by(kind="set_candidate").order_by(Job.id.desc()).limit(10).all()
    return {"sets": out, "jobs": [S.job(j) for j in jobs]}


@app.post("/api/sets/generate", dependencies=[Depends(current_user)])
def generate_set(body: SetIn, db: Session = Depends(get_db)):
    """Generate a set CANDIDATE with the image provider (uses the OpenAI key; about $0.05-0.20 per image)."""
    from . import sets
    from .queue import enqueue
    sid = sets.slug(body.label)
    rec = sets.records(db).get(sid)
    if rec and rec.get("status") == "approved":
        raise HTTPException(409, f"an approved set named {sid!r} already exists")
    return S.job(enqueue(db, "set_candidate", payload={"set_id": sid, "label": body.label, "description": body.description}))


@app.post("/api/sets/{sid}/decide", dependencies=[Depends(current_user)])
def decide_set(sid: str, body: SetDecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import sets
    recs = sets.records(db)
    if sid not in recs:
        raise HTTPException(404, "no such set")
    r = recs[sid]
    if body.blocking:
        b = {k: int(body.blocking[k]) for k in ("floor_y", "stand_min_x", "stand_max_x") if k in body.blocking}
        if not (0 < b.get("floor_y", r["blocking"]["floor_y"]) <= r["height"]):
            raise HTTPException(422, "floor_y must be inside the image")
        r["blocking"].update(b)
        if isinstance(body.blocking.get("seat"), dict):
            r["blocking"]["seat"] = {k: int(body.blocking["seat"][k]) for k in ("x", "hip_y", "feet_y")}
    r["status"] = "approved" if body.decision == "approve" else "rejected"
    r["decided_by"], r["decided_at"] = user, time_now()
    sets.save(db, recs)
    return {"id": sid, **r}


def time_now() -> float:
    import time as _t
    return _t.time()


# ------------------------------------------------------------------ Kokoro vs Piper voice comparison (CPU, free)
@app.post("/api/voice/compare", dependencies=[Depends(current_user)])
def voice_compare_start(db: Session = Depends(get_db)):
    from .queue import enqueue
    if db.query(Job).filter(Job.kind == "voice_compare", Job.status.in_(["queued", "running"])).count():
        raise HTTPException(409, "A voice comparison is already running")
    return S.job(enqueue(db, "voice_compare"))


@app.get("/api/voice/compare", dependencies=[Depends(current_user)])
def voice_compare_result(db: Session = Depends(get_db)):
    j = db.query(Job).filter_by(kind="voice_compare").order_by(Job.id.desc()).first()
    if not j:
        return {"job": None}
    res = json.loads(json.dumps(j.result or {}))
    for row in res.get("rows", []):
        for eng in ("piper", "kokoro"):
            a = db.get(Asset, (row.get(eng) or {}).get("asset_id"))
            if a:
                row[eng]["url"] = storage().url(a.storage_key)
    return {"job": S.job(j), "result": res}


# ------------------------------------------------------------------ YouTube connection (OAuth, owner's channel)
def _public_url(request: Request) -> str:
    import os
    return (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")


@app.get("/api/youtube/connect", dependencies=[Depends(current_user)])
def youtube_connect(request: Request):
    """Send the owner to Google to grant this studio upload access to their channel (OAuth consent)."""
    import hashlib, hmac, time as _t, urllib.parse
    from fastapi.responses import RedirectResponse
    from .secrets_store import secret
    cid = secret("youtube_client_id")
    if not cid or not secret("youtube_client_secret"):
        raise HTTPException(409, "Save the YouTube OAuth client ID and secret under Credentials first")
    ts = str(int(_t.time()))
    state = ts + "." + hmac.new((get_settings().session_secret or "dev").encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    q = {"client_id": cid, "redirect_uri": _public_url(request) + "/api/youtube/callback", "response_type": "code",
         "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(q))


@app.get("/api/youtube/callback", dependencies=[Depends(current_user)])
def youtube_callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    import hashlib, hmac, time as _t
    import httpx
    from fastapi.responses import RedirectResponse
    from .secrets_store import put_secrets, secret
    ts, _, sig = state.partition(".")
    good = hmac.new((get_settings().session_secret or "dev").encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    if error or not code or not ts.isdigit() or not hmac.compare_digest(good, sig) or _t.time() - int(ts) > 1800:
        return RedirectResponse("/settings?youtube=failed")
    r = httpx.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "code": code, "client_id": secret("youtube_client_id"), "client_secret": secret("youtube_client_secret"),
        "redirect_uri": _public_url(request) + "/api/youtube/callback", "grant_type": "authorization_code"})
    if r.status_code >= 400 or not r.json().get("refresh_token"):
        log.warning("YouTube token exchange failed: HTTP %s", r.status_code)   # body not logged (may hold tokens)
        return RedirectResponse("/settings?youtube=failed")
    put_secrets(db, {"youtube_refresh_token": r.json()["refresh_token"]})
    return RedirectResponse("/settings?youtube=connected")


@app.put("/api/settings/{section}", dependencies=[Depends(current_user)])
def put_settings(section: str, body: dict, db: Session = Depends(get_db)):
    if section not in DEFAULTS:
        raise HTTPException(404, "unknown settings section")
    try:
        return put_section(db, section, body)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ------------------------------------------------------------------ media (local storage only; S3 uses presigned URLs)
@app.get("/api/media/{key:path}")
def media(key: str, exp: int, sig: str):
    st = LocalStorage()   # files on the server volume (also media kept locally after a switch to S3)
    try:
        if not verify_local(key, exp, sig):
            raise HTTPException(403, "link expired or invalid")
        path = st.local_path(key)
    except ValueError:
        raise HTTPException(404, "not found")
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=mimetypes.guess_type(str(path))[0] or "application/octet-stream",
                        headers={"Cache-Control": "private, max-age=300"})
