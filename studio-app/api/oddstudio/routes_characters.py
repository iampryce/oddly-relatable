"""Characters: reusable cast, per-episode characters, reference images and generated expression poses.

A generated pose is only used in production after the owner approves it here; the character becomes usable once at
least one pose is approved (its default expression must be among them)."""
from __future__ import annotations

import base64
import binascii
import io
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, CharacterAsset, Event
from .queue import enqueue
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
KEY = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
EXPRESSION = re.compile(r"^[a-z][a-z -]{1,38}$")


def get_char(db: Session, cid: int) -> Character:
    c = db.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    return c


def out(db: Session, c: Character) -> dict:
    from . import rig_check
    return S.character(c, db.query(CharacterAsset).filter_by(character_id=c.id).order_by(CharacterAsset.id.desc()).all(),
                       rig_check.records(db))


class CharacterIn(BaseModel):
    key: str = Field(min_length=2, max_length=41)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    visual_description: str = Field(default="", max_length=4000)
    bubble_style: Literal["him", "her", "neutral"] = "neutral"
    scope: Literal["recurring", "episode"] = "recurring"
    episode_id: int | None = None
    default_expression: str = Field(default="neutral", max_length=40)
    voice: str = Field(default="", max_length=120)
    voice_style: str = Field(default="", max_length=600)
    voice_speed: float | None = Field(default=None, ge=0.5, le=2.0)   # optional; Fish Audio prosody speed
    skin_tone: str = Field(default="", max_length=40)                    # house style v2: optional flat skin tone (white if empty)


@router.get("/characters")
def list_characters(db: Session = Depends(get_db)):
    from .bin import hidden_ids
    gone = hidden_ids(db, "character")
    return [out(db, c) for c in db.query(Character).order_by(Character.id) if c.id not in gone]


@router.post("/characters/rig-check-all")
def rig_check_all(db: Session = Depends(get_db), user: str = Depends(current_user)):
    """One-time (repeatable) check of every character's approved poses, for poses approved before the check existed.
    Informational only: it records results for the pose cards and never changes an approval."""
    from .models import Job
    busy = {j.character_id for j in db.query(Job).filter(Job.kind == "rig_check", Job.status.in_(("queued", "running")))}
    chars = [c for c in db.query(Character).order_by(Character.id) if not c.locked and c.art_status == "approved"]
    queued = [c.name for c in chars if c.id not in busy]
    for c in chars:
        if c.id not in busy:
            enqueue(db, "rig_check", episode_id=c.episode_id, character_id=c.id)
    db.add(Event(episode_id=None, kind="character", message=f"Rig check queued for {len(queued)} character(s) by {user}"))
    db.commit()
    return {"queued": queued, "already_running": len(chars) - len(queued),
            "skipped_locked": [c.name for c in db.query(Character).filter_by(locked=True)]}


@router.post("/characters", status_code=201)
def create_character(body: CharacterIn, db: Session = Depends(get_db)):
    if not KEY.match(body.key):
        raise HTTPException(422, "key: lowercase letters, digits and dashes, starting with a letter")
    if db.query(Character).filter_by(key=body.key).first():
        raise HTTPException(409, f"a character with key {body.key!r} already exists")
    c = Character(**body.model_dump(), engine_character=f"studio-{body.key}", art_status="none")
    db.add(c)
    db.add(Event(kind="character", message=f"Character created: {body.name}"))
    db.commit()
    return out(db, c)


@router.put("/characters/{cid}")
def update_character(cid: int, body: CharacterIn, db: Session = Depends(get_db)):
    c = get_char(db, cid)
    if c.locked:
        # Approved repository artwork and its description stay locked; only the voice may be assigned.
        c.voice, c.voice_style, c.voice_speed, c.skin_tone = body.voice, body.voice_style, body.voice_speed, body.skin_tone
        db.commit()
        return out(db, c)
    if body.key != c.key:
        raise HTTPException(409, "a character's key cannot change (scripts refer to it)")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return out(db, c)


class SuggestVoiceIn(BaseModel):
    use_ai: bool = True


@router.post("/characters/{cid}/suggest-voice")
def suggest_voice(cid: int, body: SuggestVoiceIn, db: Session = Depends(get_db)):
    """Suggest a voice from the library for this character. Nothing is saved: the page puts it in the form and the owner saves."""
    from .voice_library import suggest
    return suggest(db, get_char(db, cid), use_ai=body.use_ai)


class ReferenceIn(BaseModel):
    png_base64: str = Field(max_length=12_000_000)


@router.post("/characters/{cid}/reference", status_code=201)
def upload_reference(cid: int, body: ReferenceIn, db: Session = Depends(get_db)):
    """A visual reference supplied by the owner (used to keep generated poses consistent)."""
    c = get_char(db, cid)
    try:
        raw = base64.b64decode(body.png_base64, validate=True)
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
    except (binascii.Error, ValueError, OSError):
        raise HTTPException(422, "the reference must be a PNG or JPEG image")
    if img.format not in ("PNG", "JPEG"):
        raise HTTPException(422, "the reference must be a PNG or JPEG image")
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"ref.{img.format.lower()}"
        f.write_bytes(raw)
        n = db.query(CharacterAsset).filter_by(character_id=c.id, kind="reference").count() + 1
        key = f"characters/{c.key}/reference-{n}.{img.format.lower()}"
        storage().put_file(key, f, "image/png" if img.format == "PNG" else "image/jpeg")
    a = CharacterAsset(character_id=c.id, kind="reference", storage_key=key, width=img.width, height=img.height, status="approved")
    db.add(a)
    db.commit()
    return out(db, c)


class PosesIn(BaseModel):
    expressions: list[str] = Field(min_length=1, max_length=12)


@router.post("/characters/{cid}/poses/generate")
def generate_poses(cid: int, body: PosesIn, db: Session = Depends(get_db)):
    c = get_char(db, cid)
    if c.locked:
        raise HTTPException(409, "this character uses approved repository artwork; new poses need the owner's separate artwork approval")
    if not c.visual_description.strip():
        raise HTTPException(422, "describe how the character looks first (visual description)")
    if get_section(db, "image").get("provider", "none") == "none":
        raise HTTPException(409, "image generation is off; choose an image provider in Settings > AI providers")
    exps = []
    for e in body.expressions:
        e = e.strip().lower()
        if not EXPRESSION.match(e):
            raise HTTPException(422, f"invalid expression name {e!r}")
        exps.append(e)
    c.art_status = "generating"
    db.commit()
    return [S.job(enqueue(db, "character_pose", character_id=c.id, payload={"expression": e})) for e in exps]


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]


def refresh_art(db: Session, c: Character) -> None:
    """A character's usable expressions are exactly its approved poses; art is approved once any pose is."""
    approved = db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="approved").all()
    c.expressions = {x.expression: f"p{x.id}" for x in approved}
    if approved:
        if c.default_expression not in c.expressions:
            c.default_expression = "neutral" if "neutral" in c.expressions else approved[0].expression
        c.art_status = "approved"
        c.registry_path = c.registry_path or "generated"
    else:
        reviewing = db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="review").count()
        c.art_status, c.registry_path = ("review" if reviewing else "none"), None


def decide(db: Session, c: Character, a: CharacterAsset, approve: bool) -> None:
    if approve:
        # One approved pose per expression: approving a new one retires the previous one.
        for other in db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", expression=a.expression, status="approved"):
            if other.id != a.id:
                other.status = "rejected"
        a.status = "approved"
    else:
        a.status = "rejected"


@router.post("/character-assets/{aid}/decision")
def decide_pose(aid: int, body: DecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    a = db.get(CharacterAsset, aid)
    if a is None or a.kind != "pose":
        raise HTTPException(404, "pose not found")
    c = get_char(db, a.character_id)
    if c.locked:
        raise HTTPException(409, "locked character")
    decide(db, c, a, body.decision == "approve")
    db.flush()
    refresh_art(db, c)
    db.add(Event(episode_id=c.episode_id, kind="character", message=f"{c.name}: pose '{a.expression}' {a.status} by {user}"))
    db.commit()
    if a.status == "approved":
        queue_rig_check(db, c)
    return out(db, c)


def queue_rig_check(db: Session, c: Character) -> None:
    """Check at approval that the acting rig can be built from the approved poses (so a pose with hidden hands is
    flagged now, not an hour into a render). The result shows on the pose cards; it never changes an approval."""
    if not c.locked and c.art_status == "approved":
        enqueue(db, "rig_check", episode_id=c.episode_id, character_id=c.id)


class SheetIn(BaseModel):
    expressions: list[str] = Field(default_factory=list, max_length=16)


def clean_expressions(values: list[str]) -> list[str]:
    exps = []
    for e in values:
        e = e.strip().lower()
        if not EXPRESSION.match(e):
            raise HTTPException(422, f"invalid expression name {e!r}")
        if e not in exps:
            exps.append(e)
    return exps


def require_image_generation(db: Session, c: Character) -> None:
    if c.locked:
        raise HTTPException(409, "this character uses approved repository artwork; new art needs the owner's separate artwork approval")
    if not c.visual_description.strip():
        raise HTTPException(422, f"describe how {c.name} looks first (visual description)")
    if get_section(db, "image").get("provider", "none") == "none":
        raise HTTPException(409, "image generation is off; choose an image provider in Settings > AI providers")


def enqueue_sheet(db: Session, c: Character, expressions: list[str]):
    c.art_status = "generating" if c.art_status != "approved" else c.art_status
    db.commit()
    # Linked to the character's episode (if any) so it shows in that episode's job list.
    return enqueue(db, "character_sheet", episode_id=c.episode_id, character_id=c.id, payload={"expressions": expressions})


@router.post("/characters/{cid}/sheet")
def generate_sheet(cid: int, body: SheetIn, db: Session = Depends(get_db)):
    """Generate the pose and expression sheet (neutral first; the rest drawn from it)."""
    c = get_char(db, cid)
    require_image_generation(db, c)
    exps = clean_expressions(body.expressions or ["neutral", "happy", "shocked", "angry", "worried", "laughing"])
    return S.job(enqueue_sheet(db, c, exps))


class RestyleIn(BaseModel):
    visual_description: str | None = None
    from_current: bool = True   # simplify the current design (keeps hair/hat, skin tone, colours) into the house style


@router.post("/characters/{cid}/restyle")
def restyle(cid: int, body: RestyleIn, db: Session = Depends(get_db)):
    """Redraw a provisional character in the locked house style (Character 01's stickman style), keeping their traits.
    The new sheet goes to review; the current approved poses stay in use until the owner approves it, and are then
    superseded (kept in history)."""
    from . import house_style
    from .models import Setting
    from .secrets_store import secret
    c = get_char(db, cid)
    if c.locked:
        raise HTTPException(409, "locked character")
    if not secret("openai_api_key", db):
        raise HTTPException(409, "the restyle uses the verified OpenAI image provider: save the OpenAI key first")
    desc = body.visual_description or house_style.restyle_description(get_section(db, "creative").get("style_version", "v1"), c.key)
    if not desc:
        raise HTTPException(422, "give the simplified visual description for this character")
    c.visual_description = desc
    exps = sorted({a.expression for a in db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="approved")} | {"neutral"})
    j = enqueue(db, "character_sheet", episode_id=c.episode_id, character_id=c.id,
                payload={"expressions": exps, "restyle": True, "provider": "openai", "from_current": body.from_current})
    row = db.get(Setting, "_restyle")
    pending = dict(row.value) if row else {}
    pending[str(c.id)] = j.id
    if row:
        row.value = pending
    else:
        db.add(Setting(key="_restyle", value=pending))
    db.commit()
    return S.job(j)


@router.post("/characters/{cid}/sheet/decision")
def decide_sheet(cid: int, body: DecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Approve (or reject) every pose of the sheet that is awaiting review, in one decision."""
    c = get_char(db, cid)
    if c.locked:
        raise HTTPException(409, "locked character")
    pending = db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="review").all()
    if not pending:
        raise HTTPException(409, "no poses are awaiting review")
    from .models import Setting
    row = db.get(Setting, "_restyle")
    restyles = dict(row.value) if row else {}
    if str(c.id) in restyles:
        if body.decision == "approve":
            # the restyled sheet replaces the old design: old poses stay in history, never mixed into production
            for old in db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="approved"):
                old.status = "superseded"
        restyles.pop(str(c.id))
        row.value = restyles
    for a in pending:
        decide(db, c, a, body.decision == "approve")
        db.flush()
    for sheet in db.query(CharacterAsset).filter_by(character_id=c.id, kind="sheet", status="review"):
        sheet.status = "approved" if body.decision == "approve" else "rejected"
    refresh_art(db, c)
    db.add(Event(episode_id=c.episode_id, kind="approval" if body.decision == "approve" else "character",
                 message=f"{c.name}: expression sheet {body.decision}d by {user} ({len(pending)} poses)"))
    db.commit()
    if body.decision == "approve":
        queue_rig_check(db, c)
    return out(db, c)


@router.post("/characters/{cid}/promote")
def promote(cid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Save a story's character to the recurring cast so any later story can reuse it."""
    c = get_char(db, cid)
    if c.art_status != "approved":
        raise HTTPException(409, "approve the character's expression sheet before adding it to the recurring cast")
    c.scope, c.episode_id = "recurring", None
    db.add(Event(kind="character", message=f"{c.name} added to the recurring cast by {user}"))
    db.commit()
    return out(db, c)


class VoicePreviewIn(BaseModel):
    text: str = Field(default="", max_length=300)


@router.post("/characters/{cid}/voice/preview")
def voice_preview(cid: int, body: VoicePreviewIn, db: Session = Depends(get_db)):
    c = get_char(db, cid)
    if get_section(db, "voice").get("provider", "none") == "none":
        raise HTTPException(409, "no voice provider is configured (Settings > Voice and audio)")
    return S.job(enqueue(db, "voice_preview", character_id=c.id, payload=body.model_dump()))
