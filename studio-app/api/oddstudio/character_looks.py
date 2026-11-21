"""New characters that can be rigged (owner decision 2026-11-21, after render job 267).

- Look: a new character from an audio episode gets a starting Look (free, no AI) from the video notes' fixed lists
  only (people count, speaking or silent, usual pose, mood) plus the words-only style cues below; "Write the look (AI
  writer)" asks the text provider for one sentence from the character's own lines and the same fixed lists. Never an
  image, never a name (names are removed). The owner edits the Look like any other field.
- The server appends house_style.RIG_RULES to every pose prompt, whatever the Look says.
- Sheet plan: the first sheet defaults to the expressions the episode's script needs from this character (neutral
  only for a silent one), with the image cost shown before anything is generated.
- Body candidates: N neutral poses (default 3, capped by a cost limit), each rig-checked; only the ones that pass are
  shown for review, and approving one replaces the approved neutral (the previous one is retired, never deleted).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, CharacterAsset, Episode, Event, ScriptVersion, StoryboardScene
from .queue import enqueue

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

IMAGE_USD = (0.05, 0.20)            # estimated cost of one pose image (the image provider's range)
MAX_CANDIDATES = 6
# Words-only character cues from the owner's style brief (style-cues-from-references.md, "Characters"), limited to the
# ones that fit the current house style: an individual silhouette and adult details, never another creator's design.
STYLE_CUES = ("hair as ONE flat colour shape with a clear silhouette (a bun, a styled quiff) or a single curl line on a "
              "bald head; one plain torso garment with one adult detail (a tie, a collar); adult body language")
POSE_WORD = {"seated": "usually seated", "standing": "usually standing", "leaning": "often leaning", "walking": "often on the move",
             "lying": "often lying down"}


def _most(values):
    values = [v for v in values if v]
    return max(dict.fromkeys(values), key=lambda v: (values.count(v), -values.index(v))) if values else ""


def notes_ranges(ep: Episode | None) -> list[dict]:
    return (((ep.audio_transcript or {}).get("video_notes") or {}).get("ranges") or []) if ep is not None else []


def look_from_notes(ranges: list[dict], speaking: bool) -> str:
    """The free starting Look: only fixed-list values from the notes (and fixed words), never free text."""
    roles = [ro for r in ranges for ro in r.get("roles", [])]
    mine = [ro for ro in roles if (ro.get("role") == "speaker") == speaking]
    count = max((len(r.get("roles", [])) for r in ranges), default=0)
    pose = POSE_WORD.get(_most(ro.get("pose") for ro in mine) or _most(ro.get("pose") for ro in roles), "")
    mood = _most(ro.get("emotion") for ro in mine) or _most(ro.get("emotion") for ro in roles)
    parts = ["An adult " + ("who does the talking" if speaking else "who listens and reacts without speaking")]
    if pose:
        parts.append(pose)
    if mood:
        parts.append(f"usual mood {mood}")
    if count > 1:
        parts.append(f"one of {count} people in the scene")
    return "; ".join(parts) + f". Design: {STYLE_CUES}."


def strip_names(text: str, names: list[str]) -> str:
    t = re.sub(r"[\"“”‘’`]", "", str(text or ""))
    for n in sorted({n for n in names if n and len(n) > 1}, key=len, reverse=True):
        t = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", "the character", t, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip()[:600]


def _char(db: Session, cid: int) -> Character:
    c = db.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    return c


def _lines_of(ep: Episode, key: str) -> list[str]:
    return [ln.get("text", "") for ln in (ep.audio_transcript or {}).get("lines", []) if ln.get("speaker") == key]


# ------------------------------------------------------------------ the Look
@router.post("/characters/{cid}/look/from-notes")
def look_notes(cid: int, db: Session = Depends(get_db)):
    """Free: the starting Look from the episode's video notes (fixed lists only). Shown for editing; saved as the Look."""
    c = _char(db, cid)
    if c.locked:
        raise HTTPException(409, "approved repository artwork: the look is fixed")
    ep = db.get(Episode, c.episode_id) if c.episode_id else None
    c.visual_description = look_from_notes(notes_ranges(ep), bool(ep and _lines_of(ep, c.key)))
    db.add(Event(episode_id=c.episode_id, kind="character", message=f"{c.name}: look written from the video notes (edit it freely)"))
    db.commit()
    return {"visual_description": c.visual_description}


@router.post("/characters/{cid}/look/write")
def look_write(cid: int, db: Session = Depends(get_db)):
    """The AI writer proposes the Look from the character's lines and the notes' fixed lists (a small text call)."""
    c = _char(db, cid)
    if c.locked:
        raise HTTPException(409, "approved repository artwork: the look is fixed")
    return {"job": S.job(enqueue(db, "character_look", episode_id=c.episode_id, character_id=c.id))}


# ------------------------------------------------------------------ the first sheet
def needed_expressions(db: Session, c: Character) -> tuple[list[str], bool]:
    """The expressions the character's episodes ask of it (script or storyboard lines and reactions); (list, speaks)."""
    from .acting import referenced
    from .character_admin import usage
    eps = [db.get(Episode, e["id"]) for e in usage(db).get(c.key, []) if e["live"]]
    if c.episode_id and all(e is None or e.id != c.episode_id for e in eps):
        eps.append(db.get(Episode, c.episode_id))
    exps, speaks = [], False

    def take(ln):
        nonlocal speaks
        if ln.get("speaker") == c.key:
            speaks = True
            exps.append((ln.get("expression") or "").strip().lower())
        for r in ln.get("reactions") or []:
            if r.get("character") == c.key:
                exps.append((r.get("expression") or "").strip().lower())

    for ep in [e for e in eps if e is not None]:
        lines = [ln for s in db.query(StoryboardScene).filter_by(episode_id=ep.id) for ln in (s.lines or [])]
        if not lines:
            v = ep.approved_script_version or ep.script_version
            sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=v).one_or_none() if v else None
            lines = [ln for sc in ((sv.content or {}).get("scenes", []) if sv else []) for ln in sc.get("lines", [])]
        if not lines and ep.source == "audio":
            lines = (ep.audio_transcript or {}).get("lines", [])
        for ln in lines:
            if c.key in referenced(ln) or ln.get("speaker") == c.key:
                take(ln)
    if not speaks:
        return ["neutral"], False
    ok = re.compile(r"^[a-z][a-z -]{1,38}$")
    return list(dict.fromkeys(["neutral"] + [e for e in exps if ok.match(e)]))[:8], True


def cost(images: int) -> dict:
    return {"images": images, "usd_low": round(images * IMAGE_USD[0], 2), "usd_high": round(images * IMAGE_USD[1], 2),
            "text": f"{images} image(s), about ${images * IMAGE_USD[0]:.2f}-${images * IMAGE_USD[1]:.2f}"}


@router.get("/characters/{cid}/sheet-plan")
def sheet_plan(cid: int, db: Session = Depends(get_db)):
    c = _char(db, cid)
    exps, speaks = needed_expressions(db, c)
    return {"expressions": exps, "speaks": speaks, "cost": cost(len(exps)),
            "reason": "the expressions this character's script lines ask for" if speaks else
            "a silent character: only the neutral pose (its reactions fall back to neutral)"}


# ------------------------------------------------------------------ body pose candidates
class CandidatesIn(BaseModel):
    n: int = Field(default=3, ge=1, le=MAX_CANDIDATES)
    max_usd: float = Field(default=1.0, gt=0, le=10)


@router.post("/characters/{cid}/body-candidates")
def request_body_candidates(cid: int, body: CandidatesIn, db: Session = Depends(get_db)):
    from .routes_characters import require_image_generation
    c = _char(db, cid)
    require_image_generation(db, c)
    est = cost(body.n)
    if est["usd_high"] > body.max_usd:
        raise HTTPException(422, f"{est['text']} could exceed the ${body.max_usd:.2f} cap: lower the number or raise the cap")
    job = enqueue(db, "body_candidates", episode_id=c.episode_id, character_id=c.id, payload={"n": body.n})
    db.add(Event(episode_id=c.episode_id, kind="character", message=f"{c.name}: {body.n} body pose candidate(s) requested ({est['text']})"))
    db.commit()
    return {"job": S.job(job), "cost": est}


# ------------------------------------------------------------------ jobs
from .tasks import Ctx, task  # noqa: E402

LOOK_SYSTEM = "You describe how ONE original adult cartoon character looks. Reply with one JSON object only."
LOOK_PROMPT = ("The character {role}.{lines}\nStaging notes (fixed words): {notes}.\nStyle cues (words only): {cues}.\n\n"
               "Write ONE sentence of at most 45 words describing this character's look: the hair shape and colour, one "
               "plain sleeveless torso garment and its colour, one adult detail, and their usual body language. Never name "
               "anyone, never describe a real person, actor, character from another show, brand or logo, and no text. "
               'JSON: {{"look": ""}}')


@task
def character_look(ctx: Ctx) -> dict:
    from .providers import text_provider
    from .settings_store import get_section
    db = ctx.db
    c = db.get(Character, ctx.job.character_id)
    ep = db.get(Episode, c.episode_id) if c.episode_id else None
    mine = _lines_of(ep, c.key) if ep else []
    ranges = notes_ranges(ep)
    notes = look_from_notes(ranges, bool(mine)).split(". Design:")[0] if ranges else "none"
    lines = ("\nTheir lines:\n" + "\n".join(f"- {t}" for t in mine)[:1500]) if mine else ""
    ans = text_provider(get_section(db, "text")).complete_json(
        LOOK_SYSTEM, LOOK_PROMPT.format(role="speaks in the scene" if mine else "is silent and only reacts", lines=lines,
                                        notes=notes, cues=STYLE_CUES))
    names = [x for ch in db.query(Character).all() for x in (ch.name, ch.key)]
    names += [ln.get("speaker", "") for ln in (ep.audio_transcript or {}).get("lines", [])] if ep else []
    look = strip_names((ans or {}).get("look", "") if isinstance(ans, dict) else "", names)
    if len(look) < 10:
        raise ValueError("the writer did not propose a usable look: write it yourself")
    c.visual_description = look
    db.add(Event(episode_id=c.episode_id, kind="character", message=f"{c.name}: look written by the AI writer (edit it freely)"))
    db.commit()
    return {"look": look}


@task
def body_candidates(ctx: Ctx) -> dict:  # noqa: F811 (the job kind; the route above is registered on the router)
    from . import engine, rig_check
    from .settings_store import get_section
    from .tasks import _generate_pose, _reference_for, style_version
    db, job = ctx.db, ctx.job
    c = db.get(Character, job.character_id)
    version = style_version(db)
    cfg = get_section(db, "image")
    if cfg.get("provider") == "openai":
        cfg = {**cfg, "use_reference": True}
    ref = _reference_for(ctx, c, version)
    folder = ctx.folder("rig-checks", c.key)
    passed, failed = [], []
    for i in range(int(job.payload.get("n", 3))):
        # the current design is the identity reference, but the body is redrawn with both hands visible (a candidate
        # exists to replace a neutral that cannot be rigged, so it must not copy that pose)
        a, f = _generate_pose(ctx, c, "neutral", ref, cfg, version=version, tag=f"-c{i + 1}", body_fix=True)
        trimmed, _ = engine.trim_pose(f, folder / f"cand-{a.id}-trim.png", a.feet or {"x": 0, "y": 0})
        res = rig_check.check(c, [(a.id, "neutral", trimmed)], a.id, folder)[str(a.id)]
        recs = rig_check.records(db)
        recs[str(a.id)] = res
        rig_check.save(db, recs)
        if res["ok"]:
            passed.append(a.id)
        else:
            a.status = "rig_failed"      # kept for the record, hidden unless "show all poses"
            failed.append(a.id)
            ctx.log(res["message"])
        job.progress = {"done": i + 1, "total": job.payload.get("n", 3)}
        db.commit()
    if passed and c.art_status not in ("approved",):
        c.art_status = "review"
    db.add(Event(episode_id=c.episode_id, kind="character",
                 message=f"{c.name}: {len(passed)} body pose candidate(s) passed the rig check, {len(failed)} did not"))
    db.commit()
    return {"passed": passed, "failed": failed}
