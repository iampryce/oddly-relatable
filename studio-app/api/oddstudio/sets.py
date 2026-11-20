"""Studio sets (background environments) beyond the repository's approved plates.

New sets are generated as CANDIDATES with the verified image provider, using the approved living-room plate as a style
reference, and saved as image assets with proposed blocking (floor line, standing area, optional seat). Only after the
owner approves one in Settings > Sets does it become available: the AI writer may choose it as a location and the acting
renderer can stage scenes in it. The repository's environment registry is never modified, and the pose engine keeps
using its own approved plates (it falls back to the default set for any location it does not know).

Records live in the "_sets" settings row: {set_id: {label, description, status: candidate|approved|rejected,
asset_id, width, height, blocking: {floor_y, stand_min_x, stand_max_x, seat?}, created}}.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from PIL import Image

from .config import REPO_ROOT, get_settings

ROW = "_sets"
STYLE_REFERENCE = REPO_ROOT / "bible/concepts/lookdev-richenv/lookdev-room-empty-03.png"
from .house_style import SET_STYLE as STYLE  # noqa: E402  (the locked house style)
from .house_style import set_style  # noqa: E402


def style_reference_for(db, version: str, folder: Path) -> Path | None:
    """v1: the approved cozy living-room plate. v2: the first approved v2 set (none yet: text only, so the v1 look
    cannot leak into v2 through the reference)."""
    if version != "v2":
        return STYLE_REFERENCE
    v2 = sorted(((k, r) for k, r in approved(db).items() if r.get("style_version") == "v2"), key=lambda kv: kv[1].get("created", 0))
    if not v2:
        return None
    spec = plate_for(db, v2[0][0], folder)
    return Path(spec["plate"]) if spec else None


def records(db) -> dict:
    from .models import Setting
    row = db.get(Setting, ROW)
    return dict(row.value) if row else {}


def save(db, recs: dict) -> None:
    from .models import Setting
    row = db.get(Setting, ROW)
    if row:
        row.value = recs
    else:
        db.add(Setting(key=ROW, value=recs))
    db.commit()


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "set"


def approved(db) -> dict:
    return {k: v for k, v in records(db).items() if v.get("status") == "approved"}


def writer_environments(db) -> list[str]:
    """Locations offered to the AI writer: the repository plates, plus approved studio sets when the acting renderer
    (the only renderer that can stage them) is selected."""
    from . import acting, engine
    envs = engine.environments()
    if acting.enabled(db):
        # only sets the acting renderer can stage: repository plates with blocking, plus approved studio sets
        envs = [e for e in envs if (acting.ANIM / "sets" / f"{e}.json").exists()] + sorted(approved(db))
    return envs


def proposed_blocking(width: int, height: int) -> dict:
    """Default staging for a generated plate: feet on the open lower floor, a wide standing area. The owner sees it
    marked on the candidate and can adjust before approving."""
    return {"floor_y": round(height * 0.86), "stand_min_x": round(width * 0.08), "stand_max_x": round(width * 0.92)}


def plate_for(db, set_id: str, folder: Path) -> dict | None:
    """Acting-renderer set spec (blocking + local plate path) for an approved studio set."""
    from .models import Asset
    from .storage import storage
    rec = approved(db).get(set_id)
    if not rec:
        return None
    a = db.get(Asset, rec["asset_id"])
    local = storage().get_to_file(a.storage_key, folder / Path(a.storage_key).name)
    return {"plate": str(local), "width": rec["width"], "height": rec["height"], **rec["blocking"]}


def preview(src: Path, blocking: dict, out: Path) -> Path:
    """The candidate with its proposed staging drawn on it (floor line, standing area, seat)."""
    from PIL import ImageDraw
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    y = blocking["floor_y"]
    d.line((0, y, im.width, y), fill=(255, 40, 40), width=4)
    d.rectangle((blocking["stand_min_x"], y - 8, blocking["stand_max_x"], y + 8), outline=(40, 200, 255), width=3)
    if blocking.get("seat"):
        s = blocking["seat"]
        d.ellipse((s["x"] - 14, s["hip_y"] - 14, s["x"] + 14, s["hip_y"] + 14), outline=(255, 220, 0), width=4)
    im.save(out)
    return out


# ---------------------------------------------------------------- job
from .tasks import Ctx, store_asset, task  # noqa: E402


@task
def set_candidate(ctx: Ctx) -> dict:
    from . import providers
    from .settings_store import get_section
    db, job = ctx.db, ctx.job
    p = job.payload
    cfg = {**get_section(db, "image"), "provider": "openai", "fallback": "none", "size": "1024x1536", "use_reference": True}
    if get_section(db, "image").get("provider") != "openai":
        cfg["model"] = ""
    folder = ctx.folder("sets", p["set_id"])
    out = folder / f"{p['set_id']}-job{job.id}.png"
    from .tasks import style_version
    version = style_version(db)
    if version == "v2":
        cfg["background"] = None   # a set plate is its own scenery: no flat background instruction
    prompt = f"{set_style(version)}\nSetting: {p['description']}"
    providers.image_generate(cfg, prompt, out, reference=style_reference_for(db, version, folder))
    im = Image.open(out)
    w, h = im.size
    a = store_asset(db, ep_id=None, src=out, key=f"sets/{p['set_id']}/{out.name}", kind="set-candidate",
                    label=f"Set candidate: {p['label']}", content_type="image/png", job_id=job.id)
    blk = proposed_blocking(w, h)
    pv = preview(out, blk, folder / f"{p['set_id']}-job{job.id}-blocking.png")
    pa = store_asset(db, ep_id=None, src=pv, key=f"sets/{p['set_id']}/{pv.name}", kind="set-candidate-preview",
                     label=f"Set candidate staging: {p['label']}", content_type="image/png", job_id=job.id)
    recs = records(db)
    recs[p["set_id"]] = {"label": p["label"], "description": p["description"], "status": "candidate", "asset_id": a.id,
                         "preview_asset_id": pa.id, "width": w, "height": h, "blocking": blk, "created": time.time(), "job_id": job.id,
                         "style_version": version}
    save(db, recs)
    ctx.log(f"set candidate {p['set_id']}: {w}x{h}, awaiting owner approval")
    return {"set_id": p["set_id"], "asset_id": a.id, "width": w, "height": h}
