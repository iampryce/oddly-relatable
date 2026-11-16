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

from . import engine, routes_characters, routes_episodes, serialize as S
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
    return {"sections": all_sections(db), "integrations": integrations_status(), "environments": engine.environments()}


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
    st = storage()
    if not isinstance(st, LocalStorage):
        raise HTTPException(404, "not found")
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
