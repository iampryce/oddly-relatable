"""Oddly Relatable Studio API (FastAPI). Run: uvicorn oddstudio.main:app

All /api routes except health, sign-in and signed media require the owner's session. The database schema is managed
by Alembic (`alembic upgrade head`); tests create it directly."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import head_angles
from . import set_views
from . import audio_first, audio_scenes, beats, bin as studio_bin, gpu, shot_compare, character_admin, character_looks, reference_plan, room_read, scene_sets, shot_frames, storyboard_frames, workspace, set_proposals, engine, routes_characters, routes_episodes, serialize as S
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
app.include_router(character_admin.router)
app.include_router(character_looks.router)
app.include_router(routes_characters.router)
app.include_router(audio_first.router)
app.include_router(audio_scenes.router)
app.include_router(set_proposals.router)
app.include_router(set_views.router)
app.include_router(head_angles.router)
app.include_router(room_read.router)
app.include_router(storyboard_frames.router)
app.include_router(shot_frames.router)
app.include_router(workspace.router)
app.include_router(reference_plan.router)
app.include_router(scene_sets.router)
app.include_router(beats.router)
app.include_router(shot_compare.router)
from . import draft as episode_draft  # noqa: E402
app.include_router(episode_draft.router)
app.include_router(studio_bin.router)
app.include_router(gpu.router)
from . import system_disk  # noqa: E402
app.include_router(system_disk.router)
from . import chat, stick_pipeline, stick_shots  # noqa: E402
app.include_router(stick_pipeline.router)
app.include_router(stick_shots.router)
app.include_router(chat.router)


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
    email: str = Field(max_length=200)     # the owner's username (OWNER_EMAIL may be any name, e.g. "admin")
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
        raise HTTPException(401, "Wrong username or password")
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
    from .bin import job_keep_reason
    q = db.query(Job).filter(Job.cleared_at.is_(None))      # failed jobs the owner cleared are not listed
    if status:
        q = q.filter(Job.status.in_(status.split(",")))
    if episode_id:
        q = q.filter_by(episode_id=episode_id)
    return [{**S.job(j), **({"keep_reason": job_keep_reason(db, j)} if j.status == "failed" else {})}
            for j in q.order_by(Job.id.desc()).limit(min(limit, 500))]


@app.get("/api/jobs/{jid}", dependencies=[Depends(current_user)])
def job_detail(jid: int, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    return S.job(j, with_log=True)


# ------------------------------------------------------------------ library
@app.get("/api/library", dependencies=[Depends(current_user)])
def library(db: Session = Depends(get_db)):
    from .bin import hidden_ids
    out = []
    gone_eps, gone_clips = hidden_ids(db, "episode"), hidden_ids(db, "clip")
    for ep in db.query(Episode).order_by(Episode.updated_at.desc()):
        if ep.id in gone_eps:
            continue
        videos = [v for v in db.query(Asset).filter_by(episode_id=ep.id, kind="video").order_by(Asset.id.desc()).all()
                  if v.id not in gone_clips]
        if videos:
            out.append({**S.episode_summary(ep), "videos": [{**S.asset(v), "comparison_clip": studio_bin.is_comparison_clip(v),
                                                             "draft": "/draft/" in (v.storage_key or "")} for v in videos]})
    return out


# ------------------------------------------------------------------ settings
@app.get("/api/settings", dependencies=[Depends(current_user)])
def get_all_settings(db: Session = Depends(get_db)):
    from .capabilities import status
    from .secrets_store import presence
    tests = provider_tests(db)
    return {"sections": all_sections(db), "integrations": integrations_status(), "environments": engine.environments(),
            "credentials": presence(db), "tests": tests, "capabilities": status(db, tests)}


@app.get("/api/settings/codex", dependencies=[Depends(current_user)])
def codex_status():
    """Codex CLI sign-in state on the server (never the login file itself)."""
    from . import codex_login
    return codex_login.status()


@app.post("/api/settings/codex/login", dependencies=[Depends(current_user)])
def codex_login_start():
    """Start a ChatGPT device-code sign-in for the server's Codex; returns the link and one-time code to enter."""
    from . import codex_login
    from .providers import ProviderNotConfigured
    try:
        return codex_login.start()
    except (ProviderNotConfigured, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/settings/codex/cancel", dependencies=[Depends(current_user)])
def codex_login_cancel():
    from . import codex_login
    codex_login.cancel()
    return codex_login.status()


@app.post("/api/settings/codex/logout", dependencies=[Depends(current_user)])
def codex_logout():
    from . import codex_login
    from .providers import ProviderNotConfigured
    try:
        return codex_login.logout()
    except ProviderNotConfigured as e:
        raise HTTPException(409, str(e)) from e


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
    orientation: Literal["portrait", "landscape"] = "portrait"   # landscape: for 16:9 (YouTube long) episodes
    style: Literal["flat", "painted"] = "flat"                   # painted: a hand-painted animation background
    seats: int | None = Field(default=None, ge=1, le=12)          # the people who sit (a set is drawn for everyone in it)
    standing: int = Field(default=0, ge=0, le=12)                 # the people who stand


class SetDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    blocking: dict | None = None


@app.get("/api/sets", dependencies=[Depends(current_user)])
def list_sets(db: Session = Depends(get_db)):
    from . import sets
    out = []
    for sid, r in sorted(((k, v) for k, v in sets.records(db).items() if v.get("status") != "binned"),
                         key=lambda kv: -kv[1].get("created", 0)):
        a, pv = db.get(Asset, r.get("asset_id")), db.get(Asset, r.get("preview_asset_id"))
        out.append({"id": sid, **{k: v for k, v in r.items() if k not in ("asset_id", "preview_asset_id")},
                    "url": storage().url(a.storage_key) if a else None, "preview_url": storage().url(pv.storage_key) if pv else None,
                    "spacing": sets.spacing_of(r.get("blocking"))})
    jobs = db.query(Job).filter_by(kind="set_candidate").order_by(Job.id.desc()).limit(10).all()
    from .acting import min_head_px
    return {"sets": out, "jobs": [S.job(j) for j in jobs], "min_head_px": min_head_px()}


@app.post("/api/sets/generate", dependencies=[Depends(current_user)])
def generate_set(body: SetIn, db: Session = Depends(get_db)):
    """Generate a set CANDIDATE with the image provider (uses the OpenAI key; about $0.05-0.20 per image)."""
    from . import sets
    from .queue import enqueue
    sid = sets.slug(body.label)
    rec = sets.records(db).get(sid)
    if rec and rec.get("status") == "approved":
        raise HTTPException(409, f"an approved set named {sid!r} already exists")
    return S.job(enqueue(db, "set_candidate", payload={"set_id": sid, "label": body.label, "description": body.description,
                                                       "orientation": body.orientation, "style": body.style,
                                                       **({"seats": body.seats} if body.seats else {}), "standing": body.standing}))


@app.post("/api/sets/{sid}/decide", dependencies=[Depends(current_user)])
def decide_set(sid: str, body: SetDecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import sets
    recs = sets.records(db)
    if sid not in recs:
        raise HTTPException(404, "no such set")
    r = recs[sid]
    if body.blocking:
        apply_blocking(r, body.blocking)
    r["status"] = "approved" if body.decision == "approve" else "rejected"
    r["decided_by"], r["decided_at"] = user, time_now()
    sets.save(db, recs)
    spacing = sets.spacing_of(r.get("blocking")) if r["status"] == "approved" else []
    if spacing and r.get("episode_id"):
        db.add(Event(episode_id=r["episode_id"], kind="episode", message=f"Set {r.get('label', sid)} approved by {user} with "
                                                                         f"close seats: " + "; ".join(w["text"] for w in spacing)))
        db.commit()
    return {"id": sid, **r, "spacing": spacing}


SEAT_FACINGS = ("speaker", "camera", "away")


def apply_blocking(r: dict, blocking: dict, strict: bool = False) -> None:
    """Validate and apply a set's staging (floor line, standing area, seats, table front) to its record. Refused
    values raise 422; nothing else in the record changes. strict (staging edits): the standing area is also checked
    to run left to right inside the picture (the approval keeps its earlier checks)."""
    try:
        b = {k: int(blocking[k]) for k in ("floor_y", "stand_min_x", "stand_max_x") if k in blocking}
    except (TypeError, ValueError):
        raise HTTPException(422, "the floor line and the standing area are whole numbers of pixels")
    blk = dict(r["blocking"])
    if not (0 < b.get("floor_y", blk["floor_y"]) <= r["height"]):
        raise HTTPException(422, "floor_y must be inside the image")
    lo, hi = b.get("stand_min_x", blk.get("stand_min_x", 0)), b.get("stand_max_x", blk.get("stand_max_x", r["width"]))
    if strict and not (0 <= lo < hi <= r["width"]):
        raise HTTPException(422, "the standing area must be inside the image, from left to right")
    blk.update(b)
    try:
        if isinstance(blocking.get("seat"), dict):
            blk["seat"] = {k: int(blocking["seat"][k]) for k in ("x", "hip_y", "feet_y")}
        if isinstance(blocking.get("seats"), list):
            # several seats (feat/seating): each inside the image, the hips above the feet
            seats = []
            n_seats = min(8, len(blocking["seats"]))
            for i, s in enumerate(blocking["seats"][:8]):
                v = {k: int(s[k]) for k in ("x", "hip_y", "feet_y")}
                if not (0 <= v["x"] <= r["width"] and 0 <= v["hip_y"] < v["feet_y"] <= r["height"]):
                    raise HTTPException(422, "each seat must be inside the image, with the hips above the feet")
                # where a seated character faces (feat/3d-rig PR 3); empty = the default (the first seat faces the
                # camera, the others face the first seat)
                f = s.get("facing") if isinstance(s, dict) else None
                if f:
                    f = str(f)
                    m = re.fullmatch(r"seat:(\d)", f)
                    if f not in SEAT_FACINGS and not (m and int(m.group(1)) < n_seats and int(m.group(1)) != i):
                        raise HTTPException(422, f"seat {i + 1}: facing must be one of {', '.join(SEAT_FACINGS)} or "
                                                 "seat:N (another seat)")
                    v["facing"] = f
                seats.append(v)
            blk["seats"] = seats
            blk.pop("seat", None)
        if "table_front" in blocking:
            tf = blocking["table_front"]
            if tf:
                v = {k: int(tf[k]) for k in ("x0", "y0", "x1", "y1")}
                if not (0 <= v["x0"] < v["x1"] <= r["width"] and 0 <= v["y0"] < v["y1"] <= r["height"]):
                    raise HTTPException(422, "the table front must be a box inside the image")
                blk["table_front"] = v
            else:
                blk.pop("table_front", None)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "a seat needs x, hip_y and feet_y; the table front needs x0, y0, x1 and y1 (whole pixels)")
    r["blocking"] = blk


class StagingIn(BaseModel):
    blocking: dict


@app.put("/api/sets/{sid}/staging", dependencies=[Depends(current_user)])
def edit_set_staging(sid: str, body: StagingIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Edit the staging of a set, approved or not (seats, table front, floor line, standing area). It never changes
    the set's picture or its approval. The staging preview is redrawn, and every episode using the set is re-checked:
    its seats against the most people the video notes seat at once, with an event on the episode."""
    from . import sets
    recs = sets.records(db)
    r = recs.get(sid)
    if r is None or r.get("status") not in ("candidate", "approved"):
        raise HTTPException(404, "no such set (only candidates and approved sets have staging to edit)")
    before = len(sets.seats_of(r["blocking"]))
    status, asset_id = r.get("status"), r.get("asset_id")
    apply_blocking(r, body.blocking, strict=True)
    r["staging_edited_by"], r["staging_edited_at"] = user, time_now()
    # the preview with the staging drawn on it (the picture itself is not touched)
    a = db.get(Asset, asset_id) if asset_id else None
    if a is not None:
        import tempfile
        from pathlib import Path
        from .tasks import store_asset
        folder = Path(tempfile.mkdtemp(prefix="set-staging-"))
        src = storage().get_to_file(a.storage_key, folder / Path(a.storage_key).name)
        pv = sets.preview(src, r["blocking"], folder / f"{sid}-staging-{int(time_now())}.png")
        pa = store_asset(db, ep_id=None, src=pv, key=f"sets/{sid}/{pv.name}", kind="set-candidate-preview",
                         label=f"Set staging: {r.get('label', sid)}", content_type="image/png")
        r["preview_asset_id"] = pa.id
    if r.get("status") != status or r.get("asset_id") != asset_id:   # never the approval, never the art
        raise HTTPException(500, "the staging edit would have changed the set's approval or picture")
    recs[sid] = r
    sets.save(db, recs)
    checks = recheck_set_users(db, sid, r)
    after = len(sets.seats_of(r["blocking"]))
    for c in checks:
        db.add(Event(episode_id=c["id"], kind="episode", message=f"Set {r.get('label', sid)}: staging edited by {user} "
                                                                   f"({before} -> {after} seat(s)); {c['note']}"))
    db.commit()
    return {"id": sid, **{k: v for k, v in r.items() if k not in ("asset_id", "preview_asset_id")},
            "preview_url": storage().url(db.get(Asset, r["preview_asset_id"]).storage_key) if r.get("preview_asset_id") else None,
            "episodes": checks, "spacing": sets.spacing_of(r["blocking"])}


def recheck_set_users(db: Session, sid: str, r: dict) -> list[dict]:
    """Every episode using the set (as its set or for scene changes): its seats against the most people its video
    notes seat at once."""
    from . import sets
    from .models import Episode
    seats = len(sets.seats_of(r["blocking"]))
    out = []
    for ep in db.query(Episode).order_by(Episode.id):
        if ep.set_id != sid and sid not in (ep.scene_set_ids or []):
            continue
        ranges = ((ep.audio_transcript or {}).get("video_notes") or {}).get("ranges") or []
        seated = max((sum(1 for ro in x.get("roles", []) if ro.get("pose") == "seated") for x in ranges), default=0)
        if seated > seats:
            note = f"the notes seat up to {seated} at once: {seated - seats} will stand"
        elif seated:
            note = f"enough seats for the {seated} seated at once"
        else:
            note = "the notes seat nobody"
        out.append({"id": ep.id, "title": ep.title, "seats": seats, "seated_at_once": seated, "ok": seated <= seats,
                    "note": note + ("; render again to use the new staging" if ep.stage in ("ready", "publishing", "published") else "")})
    return out


class KeepIn(BaseModel):
    keep: bool


@app.post("/api/sets/{sid}/keep", dependencies=[Depends(current_user)])
def keep_set(sid: str, body: KeepIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Keep this set for future episodes (reuse is an explicit choice; owner rule 2026-11-22), or stop offering it to
    other episodes. Episodes that already use the set keep it either way."""
    from . import sets
    recs = sets.records(db)
    if sid not in recs or recs[sid].get("status") in ("binned", "rejected"):
        raise HTTPException(404, "no such set")
    recs[sid]["kept"] = body.keep
    sets.save(db, recs)
    db.add(Event(episode_id=recs[sid].get("episode_id"), kind="episode",
                 message=f"Set {recs[sid].get('label', sid)}: {'kept for future episodes' if body.keep else 'no longer offered to other episodes'} by {user}"))
    db.commit()
    return {"id": sid, "kept": body.keep}


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
