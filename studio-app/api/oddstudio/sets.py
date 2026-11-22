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
from .house_style import SET_STYLE_FLAT  # noqa: E402


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


def writer_environments(db, ep=None) -> list[str]:
    """Locations offered to the AI writer: the repository plates, plus the approved studio sets this episode may use
    (its own sets and the sets kept for reuse) when the acting renderer (the only renderer that can stage them) is
    selected. Another episode's set is never offered unless it was kept for future episodes."""
    from . import acting, engine
    envs = engine.environments()
    if acting.enabled(db):
        # only sets the acting renderer can stage: repository plates with blocking, plus approved studio sets
        ok = [k for k, r in approved(db).items() if r.get("kept") or (ep is not None and r.get("episode_id") == ep.id)
              or (ep is not None and k in {ep.set_id, *(ep.scene_set_ids or [])})]
        envs = [e for e in envs if (acting.ANIM / "sets" / f"{e}.json").exists()] + sorted(ok)
    return envs


def for_episode(db, ep) -> dict[str, dict]:
    """The sets an episode may choose (owner rule 2026-11-22: every episode gets its own new set unless a set is kept
    for reuse): its own approved sets, the sets kept for future episodes, the repository plates (the studio's kept
    library), and whatever it already uses. Each with `own` / `kept` flags."""
    recs = records(db)
    mine = {ep.set_id, *(ep.scene_set_ids or [])}
    out = {}
    for k, s in usable(db).items():
        r = recs.get(k, {})
        own = r.get("episode_id") == ep.id
        kept = s["source"] == "repository" or bool(r.get("kept"))
        if own or kept or k in mine:
            out[k] = {**s, "own": own, "kept": kept}
    return out


REPO_SETS = REPO_ROOT / "production" / "animation" / "sets"
_thumbs: dict[str, str] = {}      # set id -> storage key of its thumbnail (made once per process)


STAGING_KEYS = ("plate", "width", "height", "floor_y", "stand_min_x", "stand_max_x")


def repo_spec(set_id: str) -> dict | None:
    """A repository plate the acting renderer can stage (its JSON has the plate and the blocking), else None."""
    p = REPO_SETS / f"{set_id}.json"
    if not p.exists():
        return None
    try:
        spec = json.loads(p.read_text())
    except ValueError:
        return None
    return spec if all(spec.get(k) is not None for k in STAGING_KEYS) else None


def usable(db) -> dict[str, dict]:
    """Every set an episode may use: approved studio sets and the repository plates that have blocking (both are
    approved sets the acting renderer can stage). Candidates and rejected sets are not usable."""
    out = {}
    for p in sorted(REPO_SETS.glob("*.json")):
        spec = repo_spec(p.stem)
        if spec is None:
            continue
        out[p.stem] = {"id": p.stem, "label": p.stem.replace("-", " ").capitalize(), "source": "repository",
                       "description": spec.get("note", ""), "style_version": "v1", "width": spec.get("width"),
                       "height": spec.get("height"), "seat": bool(seats_of(spec)), "seats": len(seats_of(spec))}
    for k, r in approved(db).items():
        out[k] = {"id": k, "label": r.get("label", k), "source": "studio", "description": r.get("description", ""),
                  "style_version": r.get("style_version") or "v1", "width": r.get("width"), "height": r.get("height"),
                  "seat": bool(seats_of(r.get("blocking") or {})), "seats": len(seats_of(r.get("blocking") or {}))}
    return out


def spec_for(db, set_id: str, folder: Path) -> dict | None:
    """The acting renderer's set spec (plate path + blocking) for a usable set, or None."""
    if set_id in approved(db):
        return plate_for(db, set_id, folder)
    spec = repo_spec(set_id)
    if spec is not None:
        spec = dict(spec)
        spec["plate"] = str(REPO_ROOT / spec["plate"])
    return spec


def blocking_of(db, set_id: str) -> dict | None:
    """A usable set's staging (no image download): floor, standing area, seats, table front."""
    if set_id in approved(db):
        return dict(approved(db)[set_id].get("blocking") or {})
    return repo_spec(set_id)


def seats_of(blocking: dict) -> list[dict]:
    """The set's seats: `seats` (several), else the older single `seat`."""
    return list(blocking.get("seats") or ([blocking["seat"]] if blocking.get("seat") else []))


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
    """Which episodes use each set, as their set or for scene changes (so repeats are visible in the picker)."""
    from .models import Episode
    out: dict[str, list[dict]] = {}
    for e in db.query(Episode).order_by(Episode.id):
        if e.id == exclude_episode:
            continue
        for sid in dict.fromkeys([e.set_id, *(e.scene_set_ids or [])]):
            if sid:
                out.setdefault(sid, []).append({"id": e.id, "title": e.title})
    return out


def suggest(db, word: str | None, among: dict | None = None) -> str | None:
    """A set whose id, label or description mentions the video notes' setting word (shown, never applied), among the
    given sets (an episode's own and kept sets), else among all usable sets."""
    w = (word or "").strip().lower()
    if not w or w in ("other", "indoors", "outdoors"):
        return None
    for k, s in (among if among is not None else usable(db)).items():
        if w in f"{k} {s['label']} {s['description']}".lower().replace("-", " "):
            return k
    return None


RULES = ("Studio rules (always): an EMPTY room with no people, characters or animals; {seats}no written text, "
         "letters, numbers, signs, posters, logos or brands anywhere (screens and boards are blank, frames are empty); "
         "nothing copied from any existing show, film or place.")
OLD_STYLE_LOOK = {"v1": "warm painted look, soft evening lamp light, cosy wood (old house style with a reference image)",
                  "v2": "soft painted gradients, warm lamp light against a cool window (old house style with a reference image)"}
# Palettes offered by the variety guard when the description fixes no colours (rotated per episode, skipping any whose
# colours the recent sets already use).
PALETTES = (("slate blue walls", "pale grey concrete floor", "cool white daylight"),
            ("sage green walls", "light grey tile floor", "soft overcast daylight"),
            ("dusty pink walls", "white tile floor", "bright daylight"),
            ("charcoal walls", "black rubber floor", "cool white spotlights"),
            ("pale yellow walls", "blue linoleum floor", "cool fluorescent light"),
            ("teal walls", "light birch floor", "bright noon daylight"),
            ("lilac walls", "grey carpet", "soft cool daylight"),
            ("terracotta walls", "white stone floor", "clear morning light"),
            ("navy walls", "pale grey carpet", "cool evening blue light"),
            ("mint walls", "white vinyl floor", "even fluorescent light"))


def rules_text(seats: int | None) -> str:
    s = f"seating for at least {seats} {'person' if seats == 1 else 'people'} (chairs, stools or sofa places); " if seats else ""
    return RULES.format(seats=s)


def prompt_parts(db, description: str, seats: int | None = None, variety: str = "", view_line: str = "") -> list[dict]:
    """The exact prompt a set candidate is generated from, as labelled parts (what the page shows and what is sent):
    the studio's set style, the description (yours, or the set notes verbatim), the studio rules, the variety guard,
    and the view line for a two-sided room."""
    parts = [{"part": "studio style", "text": SET_STYLE_FLAT},
             {"part": "your description", "text": f"Setting: {description}"},
             {"part": "studio rules", "text": rules_text(seats)}]
    if variety.strip():
        parts.append({"part": "variety guard", "text": variety.strip()})
    if view_line:
        parts.append({"part": "view", "text": view_line})
    return parts


def prompt_for(db, description: str, seats: int | None = None, variety: str = "", view_line: str = "") -> str:
    return "\n".join(p["text"] for p in prompt_parts(db, description, seats, variety, view_line))


# ------------------------------------------------------------------ the variety guard
def _scan(text: str) -> str:
    """The look words found in an older set's description (colours, floor, light, room), for its signature."""
    from . import set_notes as SN
    t = (text or "").lower()
    found = [w for w in sorted(SN.WORDS, key=len, reverse=True)
             if len(w) > 3 and re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", t)]
    keep, seen = [], set()
    for w in found:
        if not any(w in s for s in seen):
            keep.append(w)
            seen.add(w)
    return ", ".join(keep[:8])


def recent_signatures(db, exclude_episode: int | None = None, n: int = 5) -> list[str]:
    """A short signature per recent studio set (newest first): its stored look, else the look words of its description,
    plus the look the old house style gave every set."""
    rs = [(k, r) for k, r in records(db).items() if r.get("status") in ("candidate", "approved")
          and (exclude_episode is None or r.get("episode_id") != exclude_episode)]
    rs.sort(key=lambda kv: -kv[1].get("created", 0))
    out = []
    for k, r in rs[:n]:
        sig = r.get("signature") or _scan(r.get("description", ""))
        old = OLD_STYLE_LOOK.get(r.get("style_version") or "v1") if not r.get("flat_style") else ""
        out.append(f"{r.get('label', k)}: " + "; ".join(x for x in (sig, old) if x))
    return out


def palette_for(seed: int, avoid: str) -> tuple[str, ...]:
    """The episode's palette: rotated by the episode id, skipping palettes whose wall colour the recent sets use."""
    a = avoid.lower()
    for i in range(len(PALETTES)):
        p = PALETTES[(seed + i) % len(PALETTES)]
        if p[0].removesuffix(" walls") not in a:
            return p
    return PALETTES[seed % len(PALETTES)]


def variety_text(db, ep_id: int | None, description: str = "") -> str:
    """The variety guard appended to a new set's prompt: the recent sets' look and the instruction to differ, plus a
    palette for this episode when the description fixes no wall or floor colour."""
    sigs = recent_signatures(db, ep_id)
    if not sigs:
        return ""
    from . import set_notes as SN
    d = description.lower()
    has_colour = any(re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", d) for c in SN.COLOURS)
    text = ("Variety guard: the studio's recent sets look like this:\n- " + "\n- ".join(sigs) +
            "\nWhere the setting above does not fix them, make this set clearly different from all of these: a different "
            "wall and floor palette, a different floor material, different light and time of day, and a different "
            "furniture layout. Avoid warm cosy painted-wood interiors.")
    if not has_colour:
        text += "\nPalette for this set: " + ", ".join(palette_for(ep_id or 0, " ".join(sigs))) + "."
    return text


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
    for i, s in enumerate(seats_of(blocking)):
        d.ellipse((s["x"] - 14, s["hip_y"] - 14, s["x"] + 14, s["hip_y"] + 14), outline=(255, 220, 0), width=4)
        d.line((s["x"] - 20, s["feet_y"], s["x"] + 20, s["feet_y"]), fill=(255, 220, 0), width=3)
        d.text((s["x"] + 18, s["hip_y"] - 10), str(i + 1), fill=(255, 220, 0))
    tf = blocking.get("table_front")
    if tf:
        d.rectangle((tf["x0"], tf["y0"], tf["x1"], tf["y1"]), outline=(255, 120, 0), width=3)
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
    cfg["background"] = None       # a set plate is its own scenery: no flat background instruction
    # text only (no style reference image: every set used to be an edit of the same plate and came out alike); the
    # prompt is exactly the one the page showed when the owner clicked (stored in the job), else built the same way
    cfg["use_reference"] = False
    prompt = p.get("prompt") or prompt_for(db, p["description"], variety=variety_text(db, p.get("episode_id"), p["description"]))
    providers.image_generate(cfg, prompt, out, reference=None)
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
                         "style_version": version, "episode_id": p.get("episode_id"), "flat_style": True, "prompt": prompt,
                         "signature": p.get("signature") or _scan(p["description"]),
                         # a set made for an episode stays that episode's until kept; one made in Settings > Sets
                         # (no episode) is a deliberate library set, kept for reuse
                         "kept": p.get("episode_id") is None,
                         # the seats the proposal asked for: the approval screen asks for at least this many to be marked
                         **({"seats_wanted": int(p["seats"])} if p.get("seats") else {}),
                         **{k: p[k] for k in ("view", "room") if p.get(k)}}
    save(db, recs)
    ctx.log(f"set candidate {p['set_id']}: {w}x{h}, awaiting owner approval")
    return {"set_id": p["set_id"], "asset_id": a.id, "width": w, "height": h}
