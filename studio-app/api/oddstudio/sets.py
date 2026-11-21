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


REPO_SETS = REPO_ROOT / "production" / "animation" / "sets"
_thumbs: dict[str, str] = {}      # set id -> storage key of its thumbnail (made once per process)


def usable(db) -> dict[str, dict]:
    """Every set an episode may use: approved studio sets and the repository plates that have blocking (both are
    approved sets the acting renderer can stage). Candidates and rejected sets are not usable."""
    out = {}
    for p in sorted(REPO_SETS.glob("*.json")):
        spec = json.loads(p.read_text())
        out[p.stem] = {"id": p.stem, "label": p.stem.replace("-", " ").capitalize(), "source": "repository",
                       "description": spec.get("note", ""), "style_version": "v1", "width": spec.get("width"),
                       "height": spec.get("height"), "seat": bool(spec.get("seat"))}
    for k, r in approved(db).items():
        out[k] = {"id": k, "label": r.get("label", k), "source": "studio", "description": r.get("description", ""),
                  "style_version": r.get("style_version") or "v1", "width": r.get("width"), "height": r.get("height"),
                  "seat": bool((r.get("blocking") or {}).get("seat"))}
    return out


def spec_for(db, set_id: str, folder: Path) -> dict | None:
    """The acting renderer's set spec (plate path + blocking) for a usable set, or None."""
    if set_id in approved(db):
        return plate_for(db, set_id, folder)
    p = REPO_SETS / f"{set_id}.json"
    if p.exists():
        spec = json.loads(p.read_text())
        spec["plate"] = str(REPO_ROOT / spec["plate"])
        return spec
    return None


def thumbnail_url(db, set_id: str) -> str | None:
    """A small picture of the set for the picker (studio sets: their approved image; repository plates: a copy
    stored once)."""
    from .models import Asset
    from .storage import sha256_file, storage
    rec = approved(db).get(set_id)
    if rec:
        a = db.get(Asset, rec["asset_id"])
        return storage().url(a.storage_key) if a else None
    if set_id not in _thumbs:
        p = REPO_SETS / f"{set_id}.json"
        if not p.exists():
            return None
        plate = REPO_ROOT / json.loads(p.read_text())["plate"]
        if not plate.exists():
            return None
        folder = get_settings().work_dir / "set-thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        thumb = folder / f"{set_id}.jpg"
        im = Image.open(plate).convert("RGB")
        im.thumbnail((360, 640))
        im.save(thumb, quality=85)
        key = f"sets/thumbs/{set_id}-{sha256_file(thumb)[:12]}.jpg"
        storage().put_file(key, thumb, "image/jpeg")
        _thumbs[set_id] = key
    return storage().url(_thumbs[set_id])


def usage(db, exclude_episode: int | None = None) -> dict[str, list[dict]]:
    """Which episodes use each set (so repeats are visible in the picker)."""
    from .models import Episode
    out: dict[str, list[dict]] = {}
    for e in db.query(Episode).filter(Episode.set_id.isnot(None)).order_by(Episode.id):
        if e.id != exclude_episode:
            out.setdefault(e.set_id, []).append({"id": e.id, "title": e.title})
    return out


def suggest(db, word: str | None) -> str | None:
    """A usable set whose id, label or description mentions the video notes' setting word (shown, never applied)."""
    w = (word or "").strip().lower()
    if not w or w in ("other", "indoors", "outdoors"):
        return None
    for k, s in usable(db).items():
        if w in f"{k} {s['label']} {s['description']}".lower().replace("-", " "):
            return k
    return None


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
    prompt = prompt_for(db, p["description"])
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
                         "style_version": version, "episode_id": p.get("episode_id")}
    save(db, recs)
    ctx.log(f"set candidate {p['set_id']}: {w}x{h}, awaiting owner approval")
    return {"set_id": p["set_id"], "asset_id": a.id, "width": w, "height": h}
