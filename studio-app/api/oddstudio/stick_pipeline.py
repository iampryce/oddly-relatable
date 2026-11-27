"""The stick pipeline (owner decision 2026-11-25): characters, shot stills and animation from hosted image and video
models, with the approved master of each character as the only source of its look.

1. Character master: the studio style prompt (Settings > Studio style) + the character's own lines (name, how they
   look: one accessory, expression) + the owner's style reference image -> N candidates (one paid image each). The owner
   approves ONE; it becomes the character's master. Approving a new master supersedes the old one (kept in history).
2. Expressions / turnaround: one sheet image each, made with the approved master as the ONLY reference (never drawn
   from scratch again), so the character cannot change.
3. Shot stills and 4. animation live in stick_shots.py (they build on the storyboard's shot plan).

Providers (a seam: a self-hosted GPU can be added as another entry, see VIDEO_PROVIDERS):
  image  WaveSpeed google/nano-banana-2.1/edit, priced PER IMAGE.
  video  WaveSpeed wavespeed-ai/wan-2.2/i2v-720p, priced PER SECOND of video (WaveSpeed's model list gives a video
         model's base_price per second: 0.06/s -> $0.30 for 5 s).

Rules kept here: the cost is computed before anything starts and the request must carry the cost the owner saw
(confirm_usd), so nothing paid starts without the owner's click on that exact price; a paid submit is never retried
(wavespeed.run; ProviderError is not transient, so the worker does not retry the job either); candidates and sheets go
to review and only the owner's click approves them. The WaveSpeed key stays in the credential store.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Character, CharacterAsset, Event, Job
from .queue import enqueue
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

# ------------------------------------------------------------------ providers and prices
IMAGE_PROVIDERS: dict[str, dict] = {
    # t2i_model: the same model without reference images, used by the cast styles that have no style example yet
    # (cast_from_video.py); same price per image.
    "wavespeed-nano-banana-2.1": {"label": "WaveSpeed: nano-banana-2.1 (edit)", "model": "google/nano-banana-2.1/edit",
                                  "t2i_model": "google/nano-banana-2.1/text-to-image",
                                  "usd_per_image": 0.04, "implemented": True},
}
VIDEO_PROVIDERS: dict[str, dict] = {
    "wavespeed-wan-2.2-i2v-720p": {"label": "WaveSpeed: wan-2.2 i2v 720p", "model": "wavespeed-ai/wan-2.2/i2v-720p",
                                   "usd_per_second": 0.06, "durations": [5, 8], "implemented": True},
    # TODO(gpu): the self-hosted GPU (gpu.py / runpod.py) as a second video provider; same body, own price per second.
    "gpu-self-hosted": {"label": "Own GPU (not connected yet)", "model": "", "usd_per_second": 0.0, "durations": [5, 8],
                        "implemented": False},
}
# TODO(talking): talking shots via wavespeed-ai/infinitetalk-fast (audio + still) are out of scope here; shot_compare.py
# already runs that model for the comparison and is the seam to reuse.
MASTER_KIND, SHEET_KIND = "master", "master-sheet"
SHEETS = ("expressions", "turnaround")
JOBS = ("stick_master", "stick_sheet")


def image_provider(db: Session) -> dict:
    pid = get_section(db, "stick").get("image_provider")
    p = IMAGE_PROVIDERS.get(pid)
    if not p:
        raise HTTPException(409, "choose the stick pipeline's image provider in Settings > Studio style")
    return {"id": pid, **p}


def video_provider(db: Session) -> dict:
    pid = get_section(db, "stick").get("video_provider")
    p = VIDEO_PROVIDERS.get(pid)
    if not p or not p["implemented"]:
        raise HTTPException(409, "choose a connected video provider in Settings > Studio style")
    return {"id": pid, **p}


def image_cost(count: int, usd_per_image: float) -> dict:
    """Images are priced per image: count x price."""
    usd = round(count * usd_per_image, 4)
    return {"count": count, "usd_per_image": usd_per_image, "usd": usd,
            "label": f"{count} image{'s' if count != 1 else ''} x ${usd_per_image:.2f} = ${usd:.2f}"}


def video_cost(seconds: int, usd_per_second: float, clips: int = 1) -> dict:
    """Video is priced PER SECOND of video: seconds x price (x clips)."""
    usd = round(clips * seconds * usd_per_second, 4)
    each = round(seconds * usd_per_second, 4)
    label = f"{seconds} s x ${usd_per_second:.2f}/s = ${each:.2f}"
    if clips != 1:
        label = f"{clips} clips x {label} = ${usd:.2f}"
    return {"clips": clips, "seconds": seconds, "usd_per_second": usd_per_second, "usd_each": each, "usd": usd, "label": label}


def price_from_model_list(entry: dict, kind: Literal["image", "video"]) -> dict:
    """WaveSpeed's model list gives `base_price`; for a VIDEO model it is per second, for an image model per image.
    (For refreshing the table above from WaveSpeed without mixing the two units.)"""
    price = float(entry.get("base_price") or 0)
    return {"usd_per_second": price} if kind == "video" else {"usd_per_image": price}


def require_confirmed(cost: float, confirm: float | None) -> None:
    """The owner's click carries the price they saw; a different (or missing) price is refused, nothing starts."""
    if confirm is None or abs(float(confirm) - cost) > 0.0005:
        raise HTTPException(409, f"the cost is ${cost:.2f}: confirm that amount to start (nothing was started)")


# ------------------------------------------------------------------ settings
def check_stick_settings(db: Session, v: dict) -> None:
    """Settings > Studio style: refused values never reach a provider."""
    if "style_prompt" in v and not (isinstance(v["style_prompt"], str) and 20 <= len(v["style_prompt"].strip()) <= 8000):
        raise ValueError("stick.style_prompt must be 20 to 8000 characters")
    if "image_provider" in v and v["image_provider"] not in ("none", *IMAGE_PROVIDERS):
        raise ValueError(f"stick.image_provider must be one of none, {', '.join(IMAGE_PROVIDERS)}")
    if "video_provider" in v:
        if v["video_provider"] not in ("none", *VIDEO_PROVIDERS):
            raise ValueError(f"stick.video_provider must be one of none, {', '.join(VIDEO_PROVIDERS)}")
        if v["video_provider"] != "none" and not VIDEO_PROVIDERS[v["video_provider"]]["implemented"]:
            raise ValueError(f"{VIDEO_PROVIDERS[v['video_provider']]['label']} is not integrated yet and cannot be selected")
    n = v.get("master_candidates", 2)
    if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 4):
        raise ValueError("stick.master_candidates must be 1 to 4")
    if v.get("video_seconds", 5) not in (5, 8):
        raise ValueError("stick.video_seconds must be 5 or 8")
    ref = v.get("style_reference")
    if ref is not None and reference_image(db, ref) is None:
        raise ValueError("stick.style_reference must be an approved image (a character's approved art or an uploaded style example)")


def reference_image(db: Session, ref: dict | None):
    """The owner's style reference: an approved character image, or a style example the owner uploaded. None when it
    is not (or no longer) one of those."""
    if not isinstance(ref, dict) or not isinstance(ref.get("id"), int) or isinstance(ref.get("id"), bool):
        return None
    if ref.get("kind") == "character_asset":
        a = db.get(CharacterAsset, ref["id"])
        return a if a is not None and a.status == "approved" and a.kind in ("master", "pose", "reference") else None
    if ref.get("kind") == "asset":
        a = db.get(Asset, ref["id"])
        return a if a is not None and a.kind == "style-reference" else None
    return None


def reference_options(db: Session) -> list[dict]:
    """Every image the owner may choose as the style reference: uploaded style examples and approved character art."""
    out = [{"kind": "asset", "id": a.id, "label": a.label or "Style example", "url": storage().url(a.storage_key)}
           for a in db.query(Asset).filter_by(kind="style-reference").order_by(Asset.id.desc())]
    names = {c.id: c.name for c in db.query(Character)}
    for a in (db.query(CharacterAsset).filter(CharacterAsset.status == "approved",
                                              CharacterAsset.kind.in_(("master", "pose", "reference")))
              .order_by(CharacterAsset.id.desc()).limit(200)):
        what = "master" if a.kind == "master" else a.expression or a.kind
        out.append({"kind": "character_asset", "id": a.id, "label": f"{names.get(a.character_id, '?')}: {what}",
                    "url": storage().url(a.storage_key)})
    return out


# ------------------------------------------------------------------ prompts (pure)
def character_lines(c) -> str:
    look = (c.visual_description or "").strip()
    return f"Character name: {c.name}." + (f" {look}" if look else "")


def master_prompt(style: str, c) -> str:
    """The studio style block unchanged, then this character's own lines (the owner's rule: add only those)."""
    return (f"{style.strip()}\n\n{character_lines(c)}\n"
            "Use the reference image only for the drawing style (line weight, head and eye shapes, colouring); "
            "do not copy its character, accessories or pose. One character only, full body, plain white background.")


SHEET_PROMPTS = {
    "expressions": ("An expression sheet of EXACTLY the character in the reference image: the same head, eyes, line "
                    "style, accessory and colours, never redesigned. A neat grid of six head-and-shoulders views: "
                    "neutral, happy, laughing, shocked, angry, worried. Plain white background. No text, no labels, "
                    "no watermark."),
    "turnaround": ("A character turnaround of EXACTLY the character in the reference image: the same head, eyes, line "
                   "style, accessory and colours, never redesigned. Full body, standing, in a row: front, three-quarter "
                   "front, side, three-quarter back, back. Same size and ground line in every view. Plain white "
                   "background. No text, no labels, no watermark."),
}


def sheet_prompt(sheet: str, c) -> str:
    return f"{SHEET_PROMPTS[sheet]}\nThe character: {c.name}."


def edit_body(prompt: str, image_urls: list[str], aspect_ratio: str) -> dict:
    """The nano-banana edit request (references are URLs, in order)."""
    return {"prompt": prompt, "images": list(image_urls), "aspect_ratio": aspect_ratio, "resolution": "1k",
            "output_format": "png"}


# ------------------------------------------------------------------ character state
def _char(db: Session, cid: int) -> Character:
    c = db.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    return c


def approved_master(db: Session, cid: int) -> CharacterAsset | None:
    return (db.query(CharacterAsset).filter_by(character_id=cid, kind=MASTER_KIND, status="approved")
            .order_by(CharacterAsset.id.desc()).first())


def _active(db: Session, cid: int):
    return db.query(Job).filter(Job.kind.in_(JOBS), Job.character_id == cid, Job.status.in_(("queued", "running")))


def _asset_out(a: CharacterAsset) -> dict:
    return {"id": a.id, "kind": a.kind, "sheet": a.expression if a.kind == SHEET_KIND else None, "status": a.status,
            "url": storage().url(a.storage_key), "width": a.width, "height": a.height, "created_at": S.ts(a.created_at)}


def state(db: Session, c: Character) -> dict:
    st = get_section(db, "stick")
    rows = (db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id,
                                            CharacterAsset.kind.in_((MASTER_KIND, SHEET_KIND)))
            .order_by(CharacterAsset.id.desc()).all())
    prov = IMAGE_PROVIDERS.get(st.get("image_provider"))
    each = prov["usd_per_image"] if prov else 0.0
    master = approved_master(db, c.id)
    ref = reference_image(db, st.get("style_reference"))
    jobs = (db.query(Job).filter(Job.kind.in_(JOBS), Job.character_id == c.id).order_by(Job.id.desc()).limit(10).all())
    return {"character_id": c.id, "provider": {"id": st.get("image_provider"), "label": prov["label"] if prov else "off"},
            "master": _asset_out(master) if master else None,
            "candidates": [_asset_out(a) for a in rows if a.kind == MASTER_KIND and a.status == "review"],
            "sheets": [_asset_out(a) for a in rows if a.kind == SHEET_KIND and a.status in ("review", "approved")],
            "history": [_asset_out(a) for a in rows if a.status in ("rejected", "superseded")][:20],
            "style_reference": {"set": ref is not None, "url": storage().url(ref.storage_key) if ref is not None else None},
            "costs": {"master": image_cost(int(st.get("master_candidates") or 2), each),
                      "expressions": image_cost(1, each), "turnaround": image_cost(1, each)},
            "prompt": master_prompt(st.get("style_prompt") or "", c),
            "busy": _active(db, c.id).first() is not None, "jobs": [S.job(j) for j in jobs]}


# ------------------------------------------------------------------ routes
@router.get("/stick/config")
def config(db: Session = Depends(get_db)):
    st = get_section(db, "stick")
    ref = reference_image(db, st.get("style_reference"))
    return {"image_providers": IMAGE_PROVIDERS, "video_providers": VIDEO_PROVIDERS, "settings": st,
            "style_reference": ({"kind": st["style_reference"]["kind"], "id": st["style_reference"]["id"],
                                 "url": storage().url(ref.storage_key)} if ref is not None else None),
            "options": reference_options(db)}


@router.get("/stick/balance")
def get_balance():
    """The prepaid WaveSpeed balance (a free GET; the key never leaves the server)."""
    from . import wavespeed
    from .providers import ProviderError, ProviderNotConfigured
    try:
        return {"usd": round(wavespeed.balance(), 4)}
    except (ProviderError, ProviderNotConfigured) as e:
        raise HTTPException(502, str(e))


@router.put("/stick/style-reference/upload", status_code=201)
async def upload_style_reference(request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's own style example (PNG or JPEG, the request body). Uploading it is the owner's choice, so it becomes
    the style reference at once; the earlier one stays in the list."""
    import io
    from PIL import Image
    from .settings_store import put_section
    from .tasks import store_asset
    raw = await request.body()
    if not raw or len(raw) > 15_000_000:
        raise HTTPException(422, "the style example must be a PNG or JPEG up to 15 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        fmt = img.format
    except Exception:
        raise HTTPException(422, "the style example must be a PNG or JPEG image")
    if fmt not in ("PNG", "JPEG"):
        raise HTTPException(422, "the style example must be a PNG or JPEG image")
    ext = "png" if fmt == "PNG" else "jpg"
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"style.{ext}"
        f.write_bytes(raw)
        n = db.query(Asset).filter_by(kind="style-reference").count() + 1
        a = store_asset(db, ep_id=None, src=f, key=f"stick/style-reference-{n}.{ext}", kind="style-reference",
                        label=f"Style example {n}", content_type="image/png" if ext == "png" else "image/jpeg")
    db.commit()
    put_section(db, "stick", {"style_reference": {"kind": "asset", "id": a.id}})
    db.add(Event(kind="character", message=f"Studio style example {n} uploaded and chosen by {user}"))
    db.commit()
    return config(db)


@router.get("/characters/{cid}/stick")
def get_state(cid: int, db: Session = Depends(get_db)):
    return state(db, _char(db, cid))


class PaidIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=100)


def _check_can_draw(db: Session, c: Character) -> None:
    if c.locked:
        raise HTTPException(409, "this character uses approved repository artwork; it is not redrawn here")
    if _active(db, c.id).first():
        raise HTTPException(409, f"{c.name}: a stick pipeline image is already being made")


@router.post("/characters/{cid}/stick/master")
def generate_master(cid: int, body: PaidIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Master candidates (paid: shown first, started only by this click). They go to review."""
    c = _char(db, cid)
    _check_can_draw(db, c)
    st = get_section(db, "stick")
    prov = image_provider(db)
    if not (c.visual_description or "").strip():
        raise HTTPException(422, f"write {c.name}'s look first (name, one accessory, expression)")
    ref = reference_image(db, st.get("style_reference"))
    if ref is None:
        raise HTTPException(409, "choose the style reference image in Settings > Studio style first")
    n = int(st.get("master_candidates") or 2)
    cost = image_cost(n, prov["usd_per_image"])
    require_confirmed(cost["usd"], body.confirm_usd)
    ref_ref = {"kind": "character_asset" if isinstance(ref, CharacterAsset) else "asset", "id": ref.id}
    job = enqueue(db, "stick_master", episode_id=c.episode_id, character_id=c.id,
                  payload={"count": n, "prompt": master_prompt(st["style_prompt"], c), "refs": [ref_ref],
                           "provider": prov["id"], "usd_each": prov["usd_per_image"], "usd": cost["usd"], "by": user})
    db.add(Event(episode_id=c.episode_id, kind="character",
                 message=f"{c.name}: {n} master candidate(s) asked by {user} ({cost['label']})"))
    db.commit()
    return S.job(job)


@router.post("/characters/{cid}/stick/{sheet}")
def generate_sheet(cid: int, sheet: Literal["expressions", "turnaround"], body: PaidIn, db: Session = Depends(get_db),
                   user: str = Depends(current_user)):
    """An expressions or turnaround sheet made from the APPROVED master only (paid: one image, shown first)."""
    c = _char(db, cid)
    _check_can_draw(db, c)
    prov = image_provider(db)
    master = approved_master(db, c.id)
    if master is None:
        raise HTTPException(409, f"approve {c.name}'s master first: every other image is made from it")
    cost = image_cost(1, prov["usd_per_image"])
    require_confirmed(cost["usd"], body.confirm_usd)
    job = enqueue(db, "stick_sheet", episode_id=c.episode_id, character_id=c.id,
                  payload={"sheet": sheet, "prompt": sheet_prompt(sheet, c), "master_id": master.id,
                           "provider": prov["id"], "usd_each": prov["usd_per_image"], "usd": cost["usd"], "by": user})
    db.add(Event(episode_id=c.episode_id, kind="character",
                 message=f"{c.name}: {sheet} sheet from the approved master asked by {user} ({cost['label']})"))
    db.commit()
    return S.job(job)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]


@router.post("/characters/{cid}/stick/assets/{aid}/decision")
def decide(cid: int, aid: int, body: DecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's decision on a master candidate or a sheet (only this click approves). Approving a master supersedes
    the earlier approved master (kept in history); sheets made from the earlier master stay as they are."""
    c = _char(db, cid)
    a = db.get(CharacterAsset, aid)
    if a is None or a.character_id != c.id or a.kind not in (MASTER_KIND, SHEET_KIND):
        raise HTTPException(404, "not one of this character's masters or sheets")
    if a.status != "review":
        raise HTTPException(409, f"this image is {a.status}, not waiting for a decision")
    if body.decision == "approve":
        same = db.query(CharacterAsset).filter_by(character_id=c.id, kind=a.kind, status="approved")
        if a.kind == SHEET_KIND:
            same = same.filter_by(expression=a.expression)
        for old in same:
            old.status = "superseded"
        a.status = "approved"
    else:
        a.status = "rejected"
    what = "master" if a.kind == MASTER_KIND else f"{a.expression} sheet"
    db.add(Event(episode_id=c.episode_id, kind="approval" if a.status == "approved" else "character",
                 message=f"{c.name}: {what} {a.status} by {user}"))
    db.commit()
    return state(db, c)


# ------------------------------------------------------------------ the jobs
from .tasks import Ctx, task  # noqa: E402


def local_reference(db: Session, ref: dict, folder: Path) -> Path:
    a = reference_image(db, ref)
    if a is None:
        raise ValueError("the style reference image is no longer approved: choose it again in Settings > Studio style")
    return storage().get_to_file(a.storage_key, folder / f"ref-{ref['kind']}-{a.id}{Path(a.storage_key).suffix or '.png'}")


def _save_character_image(db: Session, c: Character, src: Path, kind: str, sheet: str, job_id: int, i: int) -> CharacterAsset:
    from PIL import Image
    from .storage import sha256_file
    with Image.open(src) as im:
        w, h = im.size
    key = f"characters/{c.key}/stick/{kind}{'-' + sheet if sheet else ''}-job{job_id}-{i}.png"
    storage().put_file(key, src, "image/png")
    a = CharacterAsset(character_id=c.id, kind=kind, expression=sheet, storage_key=key, sha256=sha256_file(src),
                       width=w, height=h, status="review", style_version="v2")
    db.add(a)
    db.flush()
    return a


def run_images(ctx: Ctx, prov_id: str, prompt: str, ref_files: list[Path], count: int, usd_each: float,
               aspect_ratio: str, folder: Path, note: str):
    """Upload the references once, then one paid image per call (never retried). Yields each finished file; a failure
    stops the rest and is raised after the finished ones were kept."""
    from . import wavespeed
    prov = IMAGE_PROVIDERS[prov_id]
    urls = [wavespeed.upload(f) for f in ref_files]
    ctx.log(f"{len(urls)} reference image(s) uploaded")
    body = edit_body(prompt, urls, aspect_ratio)
    for i in range(1, count + 1):
        out = folder / f"image-{i}.png"
        wavespeed.run(ctx.db, prov["model"], body, usd_each, f"{note} {i}/{count}", out, ctx.log)
        yield i, out


@task
def stick_master(ctx: Ctx) -> dict:
    """Master candidates for one character (paid, one image each); every candidate goes to review."""
    from .providers import ProviderError
    db, job = ctx.db, ctx.job
    c = db.get(Character, job.character_id)
    p = job.payload or {}
    folder = ctx.folder("characters", c.key, "stick", f"master-job{job.id}")
    refs = [local_reference(db, r, folder) for r in p.get("refs") or []]
    made = []
    try:
        for i, f in run_images(ctx, p["provider"], p["prompt"], refs, int(p["count"]), float(p["usd_each"]), "3:4",
                               folder, f"{c.key} master"):
            a = _save_character_image(db, c, f, MASTER_KIND, "", job.id, i)
            made.append(a.id)
            db.commit()
            ctx.log(f"candidate {i}: saved for review (image {a.id})")
    except ProviderError as e:
        if made:
            db.add(Event(episode_id=c.episode_id, kind="character",
                         message=f"{c.name}: {len(made)} master candidate(s) waiting for review; the next one failed"))
            db.commit()
            raise ProviderError(f"{len(made)} of {p['count']} candidates made (kept for review); then: {e}", transient=False)
        raise
    db.add(Event(episode_id=c.episode_id, kind="character", message=f"{c.name}: {len(made)} master candidate(s) waiting for review"))
    db.commit()
    return {"made": made}


@task
def stick_sheet(ctx: Ctx) -> dict:
    """One expressions or turnaround sheet from the approved master (the only reference); it goes to review."""
    db, job = ctx.db, ctx.job
    c = db.get(Character, job.character_id)
    p = job.payload or {}
    master = db.get(CharacterAsset, p["master_id"])
    if master is None or master.status != "approved":
        raise ValueError(f"{c.name}'s master changed since this sheet was asked: ask again")
    folder = ctx.folder("characters", c.key, "stick", f"{p['sheet']}-job{job.id}")
    ref = storage().get_to_file(master.storage_key, folder / "master.png")
    made = None
    for i, f in run_images(ctx, p["provider"], p["prompt"], [ref], 1, float(p["usd_each"]),
                           "16:9" if p["sheet"] == "turnaround" else "4:3", folder, f"{c.key} {p['sheet']}"):
        made = _save_character_image(db, c, f, SHEET_KIND, p["sheet"], job.id, i).id
    db.add(Event(episode_id=c.episode_id, kind="character", message=f"{c.name}: {p['sheet']} sheet waiting for review"))
    db.commit()
    return {"made": made, "master": master.id}
