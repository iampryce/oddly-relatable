"""Import of local generations (images made outside the studio, e.g. with the Codex CLI's image route), with provenance.

The owner uploads the image file and its manifest (prompt, references with their sha256, generator and route, session
id, original path, dimensions, the file's sha256, when it was made, the pose dimension, kind, expression, optional
parent). The studio:

- refuses the upload (422) unless the file's sha256 and pixel size are exactly the manifest's;
- stores the ORIGINAL bytes unchanged (no cut-out, no re-encode) under a key named by the file's sha256; an imported
  original is immutable: never re-uploaded over, never edited in place (anything derived is a new file or asset);
- creates a CANDIDATE, never an approved asset: a character asset in status "review", a set record in status
  "candidate". Approval stays the owner's, through the existing flows (POST /character-assets/{id}/decision for a
  character asset; POST /sets/{id}/decide in Settings > Sets for a set);
- keeps the manifest as the asset's provenance, plus who imported it and when. The manifest keeps four distinct
  states: generated (required: when, by which route, how, the prompt and references), reviewed, approved, rejected.
  A decision recorded there is information only ("noted in manifest"); the import is still a candidate.

Nothing here generates anything or calls any network service.

Character kinds: pose, mask (a figure-only alpha cut-out of its parent pose: a linked asset with its own manifest, whose
mask block records the method, the script and its sha256, the source image's sha256 and the polygon spec),
expression-sheet, back-view. A mask must name its parent (an asset id, or the parent's file sha256 when the parent is
imported later: it is linked as soon as that file arrives). A set import may name reverse_of (another set's id, or
that plate's file sha256), linking the wide and reverse plates of one room.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import DIMENSION_VALUES, Asset, Character, CharacterAsset, Event, is_standard, now
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

CHARACTER_KINDS = ("pose", "mask", "expression-sheet", "back-view")
IMPORTED_KINDS = CHARACTER_KINDS            # what the one-by-one decision accepts besides studio poses
SHA = r"^[0-9a-f]{64}$"
MAX_B64 = 40_000_000                        # about 30 MB of image


class ReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(default="", max_length=200)          # what the reference controlled (identity, chair, line weight)
    file: str = Field(default="", max_length=500)          # its file name as attached
    source: str = Field(default="", max_length=500)        # where the copy came from
    sha256: str = Field(pattern=SHA)


class Generated(BaseModel):
    """How and when the image was made (required): the route, the exact prompt and the references it was given."""
    model_config = ConfigDict(extra="forbid")
    at: str = Field(min_length=1, max_length=40)             # ISO date or date-time
    by: str = Field(min_length=1, max_length=300)            # the generator and route, e.g. "codex-cli 0.165.0, ChatGPT sign-in"
    how: str = Field(default="", max_length=600)             # the method (one call per image, scratch folder, ...)
    session_id: str = Field(default="", max_length=200)
    original_path: str = Field(default="", max_length=1000)
    prompt: str = Field(default="", max_length=60_000)
    prompt_file: str = Field(default="", max_length=500)
    references: list[ReferenceIn] = Field(default_factory=list, max_length=20)


class Reviewed(BaseModel):
    """A review recorded outside the studio (who looked at it, when, what they noted). Information only."""
    model_config = ConfigDict(extra="forbid")
    by: str = Field(min_length=1, max_length=120)
    at: str = Field(min_length=1, max_length=40)
    notes: list[str] = Field(default_factory=list, max_length=20)


class Decision(BaseModel):
    """An approval or a rejection recorded outside the studio. Information only: the import is still a candidate and
    the owner's decision in the studio is the one that counts."""
    model_config = ConfigDict(extra="forbid")
    by: str = Field(min_length=1, max_length=120)
    at: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=600)


class MaskSpec(BaseModel):
    """How a mask was made: the method, the script (and its sha256) that rendered it, the source image's sha256 and the
    polygon spec it was rendered from."""
    model_config = ConfigDict(extra="forbid")
    method: str = Field(min_length=1, max_length=600)
    script: str = Field(min_length=1, max_length=500)
    script_sha256: str = Field(pattern=SHA)
    source_sha256: str = Field(pattern=SHA)
    spec: dict


class ManifestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["oddstudio-import-1"] = "oddstudio-import-1"
    kind: str = Field(max_length=20)
    file_name: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=SHA)
    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)
    # four distinct states, never one status string: generated (required), reviewed, approved, rejected
    generated: Generated
    reviewed: Reviewed | None = None
    approved: Decision | None = None
    rejected: Decision | None = None
    expression: str = Field(default="", max_length=40)
    expressions: list[str] = Field(default_factory=list, max_length=16)   # an expression sheet's panels
    posture: Literal["standing", "seated"] | None = None
    body_turn: Literal["front", "left", "right"] | None = None
    view: Literal["front", "back"] | None = None
    framing: Literal["full", "chest_up", "bust"] | None = None
    parent_asset_id: int | None = None
    parent_sha256: str | None = Field(default=None, pattern=SHA)
    mask: MaskSpec | None = None
    notes: list[str] = Field(default_factory=list, max_length=20)
    source_manifest: str = Field(default="", max_length=500)
    # sets only
    label: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=1200)
    plate_view: str = Field(default="", max_length=20)        # wide | reverse
    reverse_of: str | None = Field(default=None, max_length=80)
    set_id: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _consistent(self):
        if self.approved is not None and self.rejected is not None:
            raise ValueError("approved and rejected are both recorded: a manifest records at most one decision")
        if self.kind == "mask" and self.mask is None:
            raise ValueError("a mask's manifest needs its mask block (method, script, script_sha256, source_sha256, spec)")
        if self.kind != "mask" and self.mask is not None:
            raise ValueError("only a mask has a mask block")
        if self.mask is not None and self.parent_sha256 and self.mask.source_sha256 != self.parent_sha256:
            raise ValueError("mask.source_sha256 is not parent_sha256: the mask must be made from its parent")
        return self


class ImportIn(BaseModel):
    file_base64: str = Field(min_length=8, max_length=MAX_B64)
    manifest: ManifestIn


def _verified_image(body: ImportIn) -> tuple[bytes, Image.Image]:
    """The uploaded bytes, verified against the manifest: the sha256 and the pixel size must match exactly."""
    try:
        raw = base64.b64decode(body.file_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "the file is not valid base64")
    got = hashlib.sha256(raw).hexdigest()
    if got != body.manifest.sha256:
        raise HTTPException(422, f"the file's sha256 ({got[:16]}...) is not the manifest's ({body.manifest.sha256[:16]}...): "
                                 "refused, nothing stored")
    try:
        Image.open(io.BytesIO(raw)).verify()
        img = Image.open(io.BytesIO(raw))
    except Exception:  # noqa: BLE001 -- any decoder error means "not a readable image"
        raise HTTPException(422, "the file is not a readable image")
    if img.format not in ("PNG", "JPEG"):
        raise HTTPException(422, "the file must be a PNG or JPEG image")
    if (img.width, img.height) != (body.manifest.width, body.manifest.height):
        raise HTTPException(422, f"the image is {img.width}x{img.height}, the manifest says "
                                 f"{body.manifest.width}x{body.manifest.height}: refused")
    return raw, img


def _provenance(m: ManifestIn, user: str, raw: bytes, key: str) -> dict:
    p = m.model_dump(exclude={"posture", "body_turn", "view", "framing", "parent_asset_id"})
    p.update({"imported_by": user, "imported_at": now().isoformat(), "bytes": len(raw), "storage_key": key,
              "sha256_verified": True})
    return p


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "-", Path(name).name.lower()).strip("-")[:80] or "image.png"


def _store(raw: bytes, key: str, img: Image.Image) -> None:
    """The original bytes, unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "import"
        f.write_bytes(raw)
        storage().put_file(key, f, "image/png" if img.format == "PNG" else "image/jpeg")


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def summary(a: CharacterAsset) -> dict | None:
    """The short provenance shown on the card (the full record, prompt included, is read on demand)."""
    p = a.provenance
    if not p:
        return None
    g = p.get("generated") or {}
    return {"file_name": p.get("file_name"), "sha256": p.get("sha256"), "imported_at": p.get("imported_at"),
            "imported_by": p.get("imported_by"), "generated": {k: g.get(k) for k in ("at", "by", "session_id", "original_path")},
            # decisions recorded in the manifest: information only ("noted in manifest"), never the studio's status
            "reviewed": p.get("reviewed"), "approved": p.get("approved"), "rejected": p.get("rejected")}


# ------------------------------------------------------------------ characters
@router.post("/characters/{cid}/import", status_code=201)
def import_character_asset(cid: int, body: ImportIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from .routes_characters import out
    c = db.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    if c.locked:
        raise HTTPException(409, "this character uses locked repository artwork; nothing is imported onto it")
    m = body.manifest
    if m.kind not in CHARACTER_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(CHARACTER_KINDS)}")
    expression = m.expression.strip().lower()
    if expression and not re.match(r"^[a-z][a-z _-]{0,38}$", expression):
        raise HTTPException(422, f"invalid expression name {m.expression!r}")
    if m.kind == "pose" and not expression:
        raise HTTPException(422, "a pose needs its expression (e.g. neutral)")
    raw, img = _verified_image(body)
    dup = (db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id, CharacterAsset.sha256 == m.sha256,
                                           CharacterAsset.kind == m.kind, CharacterAsset.status != "binned").first())
    if dup is not None:
        raise HTTPException(409, f"this file is already imported for {c.name} (asset {dup.id}, {dup.status})")
    parent = None
    if m.parent_asset_id is not None:
        parent = db.get(CharacterAsset, m.parent_asset_id)
        if parent is None or parent.character_id != c.id or parent.status == "binned":
            raise HTTPException(422, f"parent asset {m.parent_asset_id} is not one of {c.name}'s assets")
    elif m.parent_sha256:
        parent = (db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id, CharacterAsset.sha256 == m.parent_sha256,
                                                  CharacterAsset.status != "binned").order_by(CharacterAsset.id.desc()).first())
    if m.kind == "mask":
        if parent is None and not m.parent_sha256:
            raise HTTPException(422, "a mask belongs to a pose: name its parent (parent_asset_id or parent_sha256)")
        if parent is not None and parent.sha256 != m.mask.source_sha256:
            raise HTTPException(422, f"mask.source_sha256 is not the sha256 of parent asset {parent.id}: the mask must be "
                                     "made from its parent")
        if not _has_alpha(img):
            raise HTTPException(422, "a mask must be a PNG with an alpha channel (the figure-only cut-out)")
    dims = {k: getattr(m, k) for k in DIMENSION_VALUES}
    if m.kind == "back-view" and dims["view"] is None:
        dims["view"] = "back"
    feet = figure_height = None
    if m.kind == "pose" and is_standard(SimpleNamespace(**dims)):
        # a standing front pose is used like any studio pose once approved: it must be a cut-out the engine can anchor
        feet, figure_height = _anchor(raw, img)
    # immutable: the key is the file's own sha256, and a key that was ever stored (even binned) is never written again
    key = f"characters/{c.key}/imported/{m.sha256}-{_safe_name(m.file_name)}"
    if db.query(CharacterAsset).filter(CharacterAsset.storage_key == key).first() is not None:
        raise HTTPException(409, "this file was imported before (it may be binned): an imported original is never replaced")
    _store(raw, key, img)
    a = CharacterAsset(character_id=c.id, kind=m.kind, expression=expression, storage_key=key, sha256=m.sha256,
                       width=img.width, height=img.height, feet=feet, figure_height=figure_height, status="review",
                       style_version="v1", provenance=_provenance(m, user, raw, key),
                       parent_asset_id=parent.id if parent is not None else None, **dims)
    db.add(a)
    db.flush()
    # an earlier import that named this file as its parent (by sha256) is linked now
    for child in db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id, CharacterAsset.parent_asset_id.is_(None),
                                                 CharacterAsset.id != a.id):
        if (child.provenance or {}).get("parent_sha256") == m.sha256:
            child.parent_asset_id = a.id
    db.add(Event(episode_id=c.episode_id, kind="character",
                 message=f"{c.name}: imported {m.kind} '{expression or m.file_name}' as a candidate by {user} "
                         f"({m.generated.by}; sha256 {m.sha256[:12]}); awaiting the owner's decision"
                         + ("; the manifest notes an earlier approval (information only)" if m.approved else "")))
    db.commit()
    return {"asset_id": a.id, "character": out(db, c)}


def _anchor(raw: bytes, img: Image.Image) -> tuple[dict, int]:
    from . import engine
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "pose.png"
        f.write_bytes(raw)
        try:
            info = engine.analyse_pose(f)
        except Exception as e:  # noqa: BLE001 -- EngineInputError and decoder errors read the same to the owner
            raise HTTPException(422, f"a standing front pose must be a cut-out on a transparent background ({e}); "
                                     "import it with its pose dimension (e.g. seated) or cut it out first")
    return info["feet"], info["figure_height"]


@router.get("/character-assets/{aid}/provenance")
def get_provenance(aid: int, db: Session = Depends(get_db)):
    a = db.get(CharacterAsset, aid)
    if a is None or a.status == "binned":
        raise HTTPException(404, "asset not found")
    return {"id": a.id, "kind": a.kind, "imported": a.provenance is not None, "provenance": a.provenance,
            "parent_asset_id": a.parent_asset_id}


class DimensionIn(BaseModel):
    posture: Literal["standing", "seated"] | None = None
    body_turn: Literal["front", "left", "right"] | None = None
    view: Literal["front", "back"] | None = None
    framing: Literal["full", "chest_up", "bust"] | None = None


@router.put("/character-assets/{aid}/dimension")
def set_dimension(aid: int, body: DimensionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Correct a candidate's pose dimension before the decision (an approved or rejected asset keeps its own)."""
    from .routes_characters import out
    a = db.get(CharacterAsset, aid)
    if a is None or a.status == "binned":
        raise HTTPException(404, "asset not found")
    c = db.get(Character, a.character_id)
    if c.locked:
        raise HTTPException(409, "locked character")
    if a.status != "review":
        raise HTTPException(409, "only a candidate awaiting review can change its pose dimension")
    before = {k: getattr(a, k) for k in DIMENSION_VALUES}
    for k in DIMENSION_VALUES:
        setattr(a, k, getattr(body, k))
    if a.kind == "pose" and is_standard(a) and a.feet is None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(storage().get_to_file(a.storage_key, Path(tmp) / "pose.png")).read_bytes()
        try:
            a.feet, a.figure_height = _anchor(raw, Image.open(io.BytesIO(raw)))
        except HTTPException:
            for k, v in before.items():
                setattr(a, k, v)
            raise
    db.add(Event(episode_id=c.episode_id, kind="character",
                 message=f"{c.name}: asset {a.id} pose dimension set by {user}: " + dimension_text(a)))
    db.commit()
    return out(db, c)


def dimension_text(a) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {getattr(a, k) or 'default'}" for k in DIMENSION_VALUES)


# ------------------------------------------------------------------ sets
@router.post("/sets/import", status_code=201)
def import_set(body: ImportIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """A set plate made outside the studio, as a CANDIDATE in Settings > Sets (kept for reuse, like a library set made
    there). Its staging starts from the same proposed default as a generated candidate; the owner adjusts and approves
    it with the existing flow."""
    from . import sets
    from .tasks import store_asset
    m = body.manifest
    if m.kind not in ("set", "set-plate"):
        raise HTTPException(422, "a set import has kind set-plate")
    if len(m.label.strip()) < 2:
        raise HTTPException(422, "name the set (label)")
    raw, img = _verified_image(body)
    sid = sets.slug(m.set_id or m.label)
    recs = sets.records(db)
    if sid in recs and recs[sid].get("status") != "binned":
        raise HTTPException(409, f"a set named {sid!r} already exists ({recs[sid].get('status')})")
    for k, r in recs.items():
        if r.get("status") != "binned" and (r.get("provenance") or {}).get("sha256") == m.sha256:
            raise HTTPException(409, f"this plate is already imported as {k!r}")
    reverse_of = None
    if m.reverse_of:
        reverse_of = m.reverse_of if m.reverse_of in recs and recs[m.reverse_of].get("status") != "binned" else next(
            (k for k, r in recs.items() if r.get("status") != "binned" and (r.get("provenance") or {}).get("sha256") == m.reverse_of), None)
        if reverse_of is None:
            raise HTTPException(422, f"reverse_of: no set {m.reverse_of!r} (import the wide plate first)")
    # immutable: keyed by the file's own sha256; a key that was ever stored is never written again
    key = f"sets/{sid}/imported-{m.sha256}-{_safe_name(m.file_name)}"
    if db.query(Asset).filter(Asset.storage_key == key).first() is not None:
        raise HTTPException(409, "this plate was imported before (it may be binned): an imported original is never replaced")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / _safe_name(m.file_name)
        f.write_bytes(raw)          # the original bytes, unchanged
        a = store_asset(db, ep_id=None, src=f, key=key, kind="set-candidate", label=f"Imported set candidate: {m.label}",
                        content_type="image/png" if img.format == "PNG" else "image/jpeg")
        blk = sets.proposed_blocking(img.width, img.height)
        pv = sets.preview(f, blk, Path(tmp) / f"{sid}-imported-{m.sha256[:16]}-blocking.png")   # a new derived file
        pa = store_asset(db, ep_id=None, src=pv, key=f"sets/{sid}/{pv.name}", kind="set-candidate-preview",
                         label=f"Set candidate staging: {m.label}", content_type="image/png")
    rec = {"label": m.label.strip(), "description": m.description.strip(), "status": "candidate", "asset_id": a.id,
           "preview_asset_id": pa.id, "width": img.width, "height": img.height, "blocking": blk, "created": time.time(),
           "style_version": "v1", "episode_id": None, "kept": True, "imported": True,
           "provenance": _provenance(m, user, raw, key)}
    if reverse_of:
        rec["reverse_of"] = reverse_of
    recs[sid] = rec
    sets.save(db, recs)
    db.add(Event(kind="episode", message=f"Set {m.label}: imported as a candidate by {user} ({m.generated.by}; sha256 "
                                         f"{m.sha256[:12]}){f'; reverse of {reverse_of}' if reverse_of else ''}; awaiting "
                                         "the owner's decision in Settings > Sets"))
    db.commit()
    return {"id": sid, **{k: v for k, v in rec.items() if k not in ("asset_id", "preview_asset_id")},
            "url": storage().url(a.storage_key), "preview_url": storage().url(pa.storage_key)}
