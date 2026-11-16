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
    return S.character(c, db.query(CharacterAsset).filter_by(character_id=c.id).order_by(CharacterAsset.id.desc()).all())


class CharacterIn(BaseModel):
    key: str = Field(min_length=2, max_length=41)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    visual_description: str = Field(default="", max_length=4000)
    bubble_style: Literal["him", "her", "neutral"] = "neutral"
    scope: Literal["recurring", "episode"] = "recurring"
    episode_id: int | None = None
    default_expression: str = Field(default="neutral", max_length=40)


@router.get("/characters")
def list_characters(db: Session = Depends(get_db)):
    return [out(db, c) for c in db.query(Character).order_by(Character.id)]


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
        raise HTTPException(409, "this character uses approved repository artwork and is locked")
    if body.key != c.key:
        raise HTTPException(409, "a character's key cannot change (scripts refer to it)")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return out(db, c)


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


@router.post("/character-assets/{aid}/decision")
def decide_pose(aid: int, body: DecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    a = db.get(CharacterAsset, aid)
    if a is None or a.kind != "pose":
        raise HTTPException(404, "pose not found")
    c = get_char(db, a.character_id)
    if c.locked:
        raise HTTPException(409, "locked character")
    if body.decision == "approve":
        # One approved pose per expression: approving a new one retires the previous one.
        for other in db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", expression=a.expression, status="approved"):
            other.status = "rejected"
        a.status = "approved"
    else:
        a.status = "rejected"
    db.flush()
    approved = [x for x in db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="approved")]
    c.expressions = {x.expression: f"p{x.id}" for x in approved}
    if approved:
        if c.default_expression not in c.expressions:
            c.default_expression = approved[0].expression
        c.art_status = "approved"
        c.registry_path = c.registry_path or "generated"
    else:
        c.art_status, c.registry_path = "review", None
    db.add(Event(kind="character", message=f"{c.name}: pose '{a.expression}' {a.status} by {user}"))
    db.commit()
    return out(db, c)
