"""Set views (feat/set-views, owner request 2026-11-23): one set, up to four views of the same room, like the cuts in a
real video.

  wide      the set's own picture (everyone)
  speaker   the speaker seen from the audience's side
  audience  the row of listeners seen from the speaker's side
  two-shot  the speaker and the nearest listener, side-on

A view is created from words: the set's own description plus the view's camera words (read from the reference video
by "Read the room from a video", camera_angles.py; editable), with the set's own approved wide picture as the
reference image so the room stays consistent. No third-party picture or video frame is ever sent; the exact request
names the reference ("our own generated set picture"). The cost is shown before generating; nothing is generated or
approved by itself. Each view has its own staging (seats, facing, floor line, desk front, standing area), edited on its
picture; a view seats only who it shows (speaker: the speaker; audience: the listeners; two-shot: the speaker and the
person addressed).

The camera picks the view per line (view_for): a wide shot uses wide; a close shot of the speaker uses speaker; a
medium shot of a speaker addressing someone uses two-shot (else speaker); a long line with reactions ends on a short
cutaway to the audience view. A missing view falls back to wide, so missing views never block anything. The storyboard
stills and the renderer use the same rule (the cuts become scene changes in the render spec; the renderer is
unchanged).

Records: on the set's record in the "_sets" settings row: views: {view: {status, asset_id, width, height, blocking,
prompt, request, camera_words, created, job_id}}.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .camera_angles import VIEW_LABEL, stored as stored_angles
from .db import get_db
from .models import Asset, Episode, Event, Job
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

EXTRA = ("speaker", "audience", "two-shot")          # the views made from the wide picture
CUTAWAY_MIN, CUTAWAY_LEN = 5.0, 2.0                  # a line this long with reactions ends on a cutaway this long (s)
REFERENCE_LABEL = "our own generated set picture ({sid}, the wide view)"
VIEW_REFERENCE = ("The attached image is THIS SAME ROOM from the wide camera angle (our own generated set picture): keep "
                  "the room, its furniture, colours, light and drawing style identical; only the camera angle changes.")


# ------------------------------------------------------------------ choosing the view (pure)
def view_for(line: dict, available: set[str]) -> str:
    """The view a line's shot uses; a missing view falls back to wide."""
    shot = (line.get("shot") or "wide").lower()
    want = "wide"
    if shot == "close":
        want = "speaker"
    elif shot == "medium":
        want = "two-shot" if line.get("look_at") and "two-shot" in available else "speaker"
    return want if want in available else "wide"


def view_starts(view: str, line: dict, listeners: list[str], seats: int) -> dict[str, str]:
    """Who sits where in a view (only those it shows; everyone else off this picture)."""
    sp = line["speaker"]
    if view == "speaker":
        order = [sp]
    elif view == "two-shot":
        other = line.get("look_at") if line.get("look_at") in listeners else (listeners[0] if listeners else None)
        order = [sp] + ([other] if other else [])
    elif view == "audience":
        order = [k for k in listeners if k != sp]
    else:
        return {}
    return {k: f"seat:{i}" for i, k in enumerate(order[:max(0, seats)])}


def cut(lines: list[dict], base: list[dict], views_by_set: dict[str, dict]) -> list[dict] | None:
    """The render's scene changes with the view cuts merged in, or None when no line uses a view (then the spec stays
    exactly as before). base: [{t0, set_id, set, starts, flip?}] (the first entry is the render's start)."""
    def base_at(t):
        b = base[0]
        for x in base:
            if x["t0"] <= t:
                b = x
        return b

    segs = []                                       # (t0, t1, base entry, view, line)
    for ln in lines:
        b = base_at(ln["start"])
        views = views_by_set.get(b["set_id"]) or {}
        v = view_for(ln, set(views))
        reactions = [r["character"] for r in ln.get("reactions") or [] if r.get("character")]
        if v == "wide" and "audience" in views and reactions and ln["end"] - ln["start"] >= CUTAWAY_MIN:
            split = round(ln["end"] - CUTAWAY_LEN, 3)
            segs += [(ln["start"], split, b, "wide", ln), (split, ln["end"], b, "audience", ln)]
        else:
            segs.append((ln["start"], ln["end"], b, v, ln))
    if all(s[3] == "wide" for s in segs):
        return None
    out, prev = [], (base[0]["set_id"], "wide", base[0]["t0"])
    for i, (t0, t1, b, v, ln) in enumerate(segs):
        key = (b["set_id"], v, b["t0"] if v == "wide" else ln["start"])
        if key == prev:
            continue
        at = t0 if i == 0 or segs[i - 1][1] >= t0 else round((segs[i - 1][1] + t0) / 2, 3)
        if v == "wide":
            out.append({"t0": at, "set": b["set"], "starts": dict(b["starts"]), **({"flip": True} if b.get("flip") else {}),
                        "view": "wide"})
        else:
            listeners = [k for k, s in sorted(b["starts"].items(), key=lambda kv: kv[1]) if str(s).startswith("seat:")]
            vs = views_by_set[b["set_id"]][v]
            out.append({"t0": at, "set": vs, "starts": view_starts(v, ln, listeners, len(vs.get("seats") or [])), "view": v})
        prev = key
    # keep the base's own scene changes that fall inside wide stretches
    return out


# ------------------------------------------------------------------ records
def views_of(rec: dict) -> dict:
    return dict((rec or {}).get("views") or {})


def approved_views(db, set_id: str) -> dict:
    from . import sets
    rec = sets.records(db).get(set_id) or {}
    return {v: x for v, x in views_of(rec).items() if x.get("status") == "approved"}


def view_spec(db, set_id: str, view: str, folder: Path) -> dict | None:
    """An approved view as a set spec for the renderer (its plate and its own staging)."""
    x = approved_views(db, set_id).get(view)
    if not x:
        return None
    a = db.get(Asset, x["asset_id"])
    if a is None:
        return None
    local = storage().get_to_file(a.storage_key, folder / Path(a.storage_key).name)
    return {"plate": str(local), "width": x["width"], "height": x["height"], **x["blocking"]}


def specs_for(db, set_ids: list[str], folder: Path) -> dict[str, dict]:
    out = {}
    for sid in dict.fromkeys(set_ids):
        vs = {}
        for v in approved_views(db, sid):
            spec = view_spec(db, sid, v, folder / f"view-{sid}-{v}")
            if spec:
                vs[v] = spec
        if vs:
            out[sid] = vs
    return out


def seats_needed(view: str, people: int) -> int:
    return {"speaker": 1, "two-shot": 2}.get(view, max(1, people - 1))


def prompt_for(db, rec: dict, view: str, words: str, people: int) -> str:
    from .sets import LAYOUT_LEAD, SET_STYLE_SHORT, rules_text
    return "\n".join([LAYOUT_LEAD + (rec.get("description") or ""),
                      f"This picture is another camera angle of the same room: the {VIEW_LABEL[view]} view. Camera: {words}",
                      SET_STYLE_SHORT, rules_text(seats_needed(view, people)), VIEW_REFERENCE])


def _set(db, sid: str) -> dict:
    from . import sets
    rec = sets.records(db).get(sid)
    if not rec or rec.get("status") == "binned":
        raise HTTPException(404, "no such set")
    return rec


def _view_name(view: str) -> str:
    if view not in EXTRA:
        raise HTTPException(404, f"unknown view (the views made from the wide picture: {', '.join(EXTRA)})")
    return view


def episode_words(ep: Episode | None) -> dict[str, str]:
    """The episode's camera words per view (from "Read the room from a video", as edited)."""
    return {a["view"]: a["text"] for a in stored_angles((ep.set_proposal if ep else None) or {})}


# ------------------------------------------------------------------ routes
@router.get("/sets/{sid}/views")
def list_views(sid: str, episode: int | None = None, db: Session = Depends(get_db)):
    from . import sets
    from .set_proposals import IMAGE_COST, cast_size
    rec = _set(db, sid)
    ep = db.get(Episode, episode) if episode else None
    words = episode_words(ep)
    people = (cast_size(ep) if ep else None) or 4
    out = []
    for v in EXTRA:
        x = views_of(rec).get(v)
        a = db.get(Asset, x["asset_id"]) if x and x.get("asset_id") else None
        out.append({"view": v, "label": VIEW_LABEL[v], "status": (x or {}).get("status", "missing"),
                    "url": storage().url(a.storage_key) if a else None, "width": (x or {}).get("width"), "height": (x or {}).get("height"),
                    "blocking": (x or {}).get("blocking") or {}, "seats": len(sets.seats_of((x or {}).get("blocking") or {})),
                    "seats_needed": seats_needed(v, people), "spacing": sets.spacing_of((x or {}).get("blocking")),
                    "request_text": sets.request_text(x["request"]) if x and x.get("request") else None,
                    "camera_words": words.get(v, (x or {}).get("camera_words") or ""),
                    "words_from": "the reference video" if v in words else ("this view's request" if x else "")})
    w = db.get(Asset, rec.get("asset_id"))
    return {"set_id": sid, "label": rec.get("label", sid), "wide": {"status": rec.get("status"), "url": storage().url(w.storage_key) if w else None},
            "views": out, "cost": IMAGE_COST, "can_generate": rec.get("status") == "approved",
            "reason": "" if rec.get("status") == "approved" else "approve the wide picture first: it is the reference for every view"}


class GenerateIn(BaseModel):
    text: str = Field(default="", max_length=1000)        # the camera words (empty: the episode's words for the view)
    episode_id: int | None = None


@router.post("/sets/{sid}/views/{view}/generate")
def generate_view(sid: str, view: str, body: GenerateIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: one candidate of this view, from the set's text plus the view's camera words, with the set's
    own approved wide picture as the reference image (cost shown on the page before)."""
    from . import sets
    from .queue import enqueue
    from .set_proposals import IMAGE_COST, cast_size
    view = _view_name(view)
    rec = _set(db, sid)
    if rec.get("status") != "approved":
        raise HTTPException(409, "approve the wide picture first: it is the reference for every view")
    ep = db.get(Episode, body.episode_id) if body.episode_id else None
    words = " ".join(body.text.split()) or episode_words(ep).get(view, "")
    if len(words) < 10:
        raise HTTPException(422, "write the view's camera words first (or read the room from a video)")
    prompt = prompt_for(db, rec, view, words, (cast_size(ep) if ep else None) or 4)
    req = sets.request_view(db, prompt, REFERENCE_LABEL.format(sid=sid))
    busy = [j for j in db.query(Job).filter(Job.kind == "set_view_candidate", Job.status.in_(("queued", "running")))
            if (j.payload or {}).get("set_id") == sid and (j.payload or {}).get("view") == view]
    if busy:
        raise HTTPException(409, "this view is already being drawn")
    job = enqueue(db, "set_view_candidate", payload={"set_id": sid, "view": view, "prompt": prompt, "request": req,
                                                     "camera_words": words, "episode_id": ep.id if ep else None})
    if ep:
        db.add(Event(episode_id=ep.id, kind="episode", message=f"Set view requested by {user}: {rec.get('label', sid)}, {view} ({IMAGE_COST})"))
        db.commit()
    return {"job": S.job(job), "request_text": sets.request_text(req), "cost": IMAGE_COST}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    blocking: dict | None = None


@router.post("/sets/{sid}/views/{view}/decide")
def decide_view(sid: str, view: str, body: DecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import sets
    from .main import apply_blocking
    view = _view_name(view)
    recs = sets.records(db)
    rec = recs.get(sid)
    x = views_of(rec).get(view) if rec else None
    if not x or x.get("status") not in ("candidate", "approved"):
        raise HTTPException(404, "no such view candidate")
    if body.blocking and body.decision == "approve":
        apply_blocking(x, body.blocking, strict=True)
    x["status"] = "approved" if body.decision == "approve" else "rejected"
    x["decided_by"], x["decided_at"] = user, time.time()
    rec["views"] = {**views_of(rec), view: x}
    sets.save(db, recs)
    db.commit()
    return {"view": view, "status": x["status"], "spacing": sets.spacing_of(x.get("blocking"))}


class StagingIn(BaseModel):
    blocking: dict


@router.put("/sets/{sid}/views/{view}/staging")
def view_staging(sid: str, view: str, body: StagingIn, db: Session = Depends(get_db)):
    """The view's own staging, edited on its picture (the picture and its approval never change)."""
    from . import sets
    from .main import apply_blocking
    view = _view_name(view)
    recs = sets.records(db)
    rec = recs.get(sid)
    x = views_of(rec).get(view) if rec else None
    if not x or x.get("status") not in ("candidate", "approved"):
        raise HTTPException(404, "no such view")
    apply_blocking(x, body.blocking, strict=True)
    rec["views"] = {**views_of(rec), view: x}
    sets.save(db, recs)
    db.commit()
    return {"view": view, "blocking": x["blocking"], "spacing": sets.spacing_of(x["blocking"])}


class WordsIn(BaseModel):
    view: str
    text: str = Field(min_length=10, max_length=1000)


@router.put("/episodes/{eid}/camera-angles")
def edit_words(eid: int, body: WordsIn, db: Session = Depends(get_db)):
    """The owner's edit of one view's camera words (used verbatim when that view is generated)."""
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    if body.view not in VIEW_LABEL:
        raise HTTPException(422, f"unknown view ({', '.join(VIEW_LABEL)})")
    sp = dict(ep.set_proposal or {})
    angles = [dict(a) for a in stored_angles(sp)]
    text = " ".join(body.text.split())
    for a in angles:
        if a["view"] == body.view:
            a.update(text=text, edited=True)
            break
    else:
        angles.append({"view": body.view, "fields": {}, "text": text, "edited": True})
    sp["camera_angles"] = angles
    ep.set_proposal = sp
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Camera words edited ({body.view})"))
    db.commit()
    return {"camera_angles": angles}


@router.get("/episodes/{eid}/view-plan")
def view_plan(eid: int, db: Session = Depends(get_db)):
    """Which view each shot uses (the same rule as the storyboard and the renderer)."""
    from . import scene_sets
    from .models import StoryboardScene
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    rows = []
    for sc in db.query(StoryboardScene).filter_by(episode_id=ep.id).order_by(StoryboardScene.position):
        sid = scene_sets.scene_set(ep, sc) or ep.set_id
        avail = set(approved_views(db, sid)) if sid else set()
        for i, ln in enumerate(sc.lines or []):
            v = view_for(ln, avail)
            want = view_for(ln, set(EXTRA))
            cut = "audience" in avail and ln.get("reactions") and v == "wide" and \
                float(ln.get("end", 0) or 0) - float(ln.get("start", 0) or 0) >= CUTAWAY_MIN
            rows.append({"scene": sc.position, "line": ln.get("line_id") or i + 1, "speaker": ln.get("speaker"),
                         "shot": ln.get("shot") or "wide", "view": v + (" then audience" if cut else ""),
                         "note": "" if v == want else f"{want} view missing: wide is used"})
    return {"set_id": ep.set_id, "rows": rows, "camera_angles": stored_angles(ep.set_proposal or {})}


# ------------------------------------------------------------------ the job
from .tasks import Ctx, task  # noqa: E402


@task
def set_view_candidate(ctx: Ctx) -> dict:
    """One view of a set: the prompt the page showed, with the set's own approved wide picture as the reference."""
    from PIL import Image
    from . import providers, sets
    from .settings_store import get_section
    from .tasks import store_asset
    db, p = ctx.db, ctx.job.payload or {}
    sid, view = p["set_id"], p["view"]
    rec = sets.records(db).get(sid)
    if not rec or rec.get("status") != "approved":
        raise ValueError("the set's wide picture is not approved any more")
    wide = db.get(Asset, rec.get("asset_id")) if rec.get("asset_id") else None
    if wide is None:
        raise ValueError(f"the set {sid}'s wide picture is missing: regenerate or re-approve the set before drawing its views")
    folder = ctx.folder("sets", sid, "views")
    ref = storage().get_to_file(wide.storage_key, folder / Path(wide.storage_key).name)
    cfg = {**get_section(db, "image"), "provider": "openai", "fallback": "none", "size": sets.SET_SIZE, "use_reference": True,
           "background": None}
    if get_section(db, "image").get("provider") != "openai":
        cfg["model"] = ""
    out = folder / f"{sid}-{view}-job{ctx.job.id}.png"
    ctx.log("request: " + sets.request_text(p["request"]).replace("\n", " | ")[:600])
    providers.image_generate(cfg, p["prompt"], out, reference=ref)
    w, h = Image.open(out).size
    a = store_asset(db, ep_id=None, src=out, key=f"sets/{sid}/views/{out.name}", kind="set-view",
                    label=f"Set view: {rec.get('label', sid)}, {view}", content_type="image/png", job_id=ctx.job.id)
    recs = sets.records(db)
    r = recs[sid]
    r["views"] = {**views_of(r), view: {"status": "candidate", "asset_id": a.id, "width": w, "height": h,
                                        "blocking": sets.proposed_blocking(w, h), "prompt": p["prompt"], "request": p["request"],
                                        "camera_words": p["camera_words"], "created": time.time(), "job_id": ctx.job.id}}
    sets.save(db, recs)
    ctx.log(f"view {view} of {sid}: {w}x{h}, awaiting the owner's approval")
    return {"set_id": sid, "view": view, "asset_id": a.id}
