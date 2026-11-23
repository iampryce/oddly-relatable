"""Suggested seats for a set candidate (feat/episode-workspace, owner request 2026-11-22).

After a set picture is generated (our OWN image, never a video frame or a third-party picture), the studio's API vision
provider is asked once where the characters go: the seat BEHIND the main desk or table (the speaker's seat), the front
face of that desk (drawn again over seated characters so they sit behind it), the other seats as an audience row, the
floor line and the open standing floor. Coordinates come back in per-mille of the picture and are checked here: every
seat inside the picture with the hips above the feet, the desk front a box inside the picture, at most MAX_SEATS seats,
the speaker's seat first (seated characters take the seats speaker first). Anything else in the answer is dropped and
counted.

The suggestion is only a starting point: it is stored with the candidate, used as its staging while nobody has edited
it, and shown on the picture for the owner to adjust before approving. Nothing is approved by it.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

MAX_SEATS = 8
SEAT_KEYS = ("x", "hip_y", "feet_y")
BOX_KEYS = ("x0", "y0", "x1", "y1")
TOP_KEYS = {"speaker_seat", "desk_front", "row", "floor_y", "stand_x0", "stand_x1"}
PROMPT_TOKENS, OUT_TOKENS = 650, 300


def prompt(people: int) -> str:
    who = f"{people} people" if people else "a few people"
    return (
        "This picture is an EMPTY 2D cartoon set, our own drawing, for an animation in which " + who + " will sit or "
        "stand. Mark where the characters go. Give every position as whole numbers in per-mille of the picture "
        "(x: 0 = left edge, 1000 = right edge; y: 0 = top edge, 1000 = bottom edge).\n"
        'Return JSON only: {"speaker_seat": {"x": 0, "hip_y": 0, "feet_y": 0} or null, "desk_front": {"x0": 0, '
        '"y0": 0, "x1": 0, "y1": 0} or null, "row": [{"x": 0, "hip_y": 0, "feet_y": 0}], "floor_y": 0, '
        '"stand_x0": 0, "stand_x1": 0}\n'
        "- speaker_seat: the seat BEHIND the main desk or table, facing the camera (where the person speaking sits); "
        "null when there is no desk or table with a seat behind it.\n"
        "- desk_front: the front face of that desk or table (the part that would hide a seated person's legs); null "
        "when there is none.\n"
        "- row: every other seat (chairs, stools, sofa places), left to right, like an audience row.\n"
        "- hip_y: the top of the seat cushion; feet_y: the floor under that seat.\n"
        "- floor_y: where a standing person's feet rest on the open floor nearest the camera; stand_x0 and stand_x1: "
        "the left and right limits of that open floor.\n"
        f"At most {MAX_SEATS} seats in all. Nothing else.")


def _int(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return int(round(v))


def clean(raw, width: int, height: int, base: dict) -> tuple[dict, dict]:
    """(blocking, info) from the vision answer: per-mille -> pixels, checked; the floor line and standing area fall
    back to `base` (the candidate's current staging) when missing or invalid."""
    stripped = 0
    raw = raw if isinstance(raw, dict) else {}
    stripped += len(set(raw) - TOP_KEYS)
    px = lambda v, n: round(v * n / 1000)          # noqa: E731

    def seat(s) -> dict | None:
        nonlocal stripped
        if not isinstance(s, dict):
            stripped += 1
            return None
        v = {k: _int(s.get(k)) for k in SEAT_KEYS}
        if any(x is None or not 0 <= x <= 1000 for x in v.values()) or v["hip_y"] >= v["feet_y"]:
            stripped += 1
            return None
        return {"x": px(v["x"], width), "hip_y": px(v["hip_y"], height), "feet_y": px(v["feet_y"], height)}

    speaker = seat(raw["speaker_seat"]) if raw.get("speaker_seat") is not None else None
    row = [s for s in (seat(x) for x in (raw.get("row") if isinstance(raw.get("row"), list) else [])[: MAX_SEATS * 2]) if s]
    row.sort(key=lambda s: s["x"])
    seats, near = ([speaker] if speaker else []), width * 0.03
    for s in row:                                   # the same seat twice (or the speaker's seat again) is dropped
        if any(abs(s["x"] - o["x"]) < near and abs(s["hip_y"] - o["hip_y"]) < height * 0.03 for o in seats):
            stripped += 1
            continue
        seats.append(s)
    stripped += max(0, len(seats) - MAX_SEATS)
    seats = seats[:MAX_SEATS]
    desk = None
    d = raw.get("desk_front")
    if isinstance(d, dict):
        v = {k: _int(d.get(k)) for k in BOX_KEYS}
        if all(x is not None and 0 <= x <= 1000 for x in v.values()) and v["x0"] < v["x1"] and v["y0"] < v["y1"]:
            desk = {"x0": px(v["x0"], width), "y0": px(v["y0"], height), "x1": px(v["x1"], width), "y1": px(v["y1"], height)}
        else:
            stripped += 1
    elif d is not None:
        stripped += 1
    blk = {k: base[k] for k in ("floor_y", "stand_min_x", "stand_max_x") if k in base}
    fy = _int(raw.get("floor_y"))
    if fy is not None and 0 < fy <= 1000:
        blk["floor_y"] = px(fy, height)
    elif "floor_y" in raw:
        stripped += 1
    x0, x1 = _int(raw.get("stand_x0")), _int(raw.get("stand_x1"))
    if x0 is not None and x1 is not None and 0 <= x0 < x1 <= 1000:
        blk["stand_min_x"], blk["stand_max_x"] = px(x0, width), px(x1, width)
    elif "stand_x0" in raw or "stand_x1" in raw:
        stripped += 1
    blk["seats"] = seats
    if desk and speaker:
        blk["table_front"] = desk
    elif desk:
        stripped += 1                                # a desk front without a seat behind it hides nobody
    return blk, {"seats": len(seats), "speaker_seat": bool(speaker), "desk_front": bool(desk and speaker),
                 "row": len(seats) - (1 if speaker else 0), "stripped": stripped}


def summary(info: dict, people: int) -> str:
    s = f"{info['seats']} seat(s)" + (f" for {people} people" if people else "")
    if info["speaker_seat"]:
        s += ": the speaker's seat behind the desk" + (" (desk front marked)" if info["desk_front"] else "")
        if info["row"]:
            s += f", {info['row']} in the audience row"
    elif info["seats"]:
        s += " in a row"
    return s


def estimate(provider: str) -> dict:
    """One image, one call: tokens and USD (upper list-price estimate, same calibration as the video notes)."""
    from . import video_notes as VN
    from .notes_v2 import CALIBRATION
    p = VN.PRICES.get(provider)
    if not p:
        return {"configured": False}
    tin, tout = PROMPT_TOKENS + p["per_frame"] * 4, OUT_TOKENS      # a full-size picture counts as several frames
    return {"configured": True, "input_tokens": tin, "output_tokens": tout,
            "usd": round((tin * p["in"] + tout * p["out"]) / 1e6 * CALIBRATION.get(provider, 1.0), 4)}


def vision_config(db) -> dict:
    from .audio_first import hints_vision_config
    return hints_vision_config(db)


def cost_view(db) -> dict:
    """What the panel shows before "Suggest seats again": the estimate and the cap (Settings > Video and visual
    analysis), or why it cannot run."""
    from .notes_v2 import clamp_cap
    from .settings_store import get_section
    cap = clamp_cap(get_section(db, "vision").get("notes_cap_usd"))
    try:
        cfg = vision_config(db)
    except ValueError as e:
        return {"configured": False, "cap_usd": cap, "message": str(e)}
    est = estimate(cfg["provider"])
    return {**est, "provider": cfg["provider"], "cap_usd": cap, "within_cap": est.get("usd", 0) <= cap}


def run(db, set_id: str, image: Path, log=lambda m: None) -> dict | None:
    """Ask once, store the suggestion with the candidate and, while nobody has edited its staging, use it as the
    staging (the preview is redrawn). Returns {"blocking", "info", "summary"}; raises when vision is not set up or
    the estimate is over the cap."""
    from . import analysis
    from . import sets
    cost = cost_view(db)
    if not cost.get("configured"):
        raise ValueError(cost.get("message") or "no API vision provider")
    if not cost["within_cap"]:
        raise ValueError(f"about ${cost['usd']:.3f}, over the ${cost['cap_usd']:.2f} cap")
    cfg = vision_config(db)
    r = sets.records(db)[set_id]
    people = int(r.get("seats_wanted") or 0)
    analysis.last_vision_usage.clear()
    ans = analysis.analyse_images(cfg, [image], prompt(people))
    usage = dict(analysis.last_vision_usage)
    blk, info = clean(ans, r["width"], r["height"], r["blocking"])
    text = summary(info, people)
    recs = sets.records(db)
    r = recs[set_id]
    r["suggested"] = {"blocking": blk, "info": info, "summary": text, "usage": usage, "estimated_usd": cost.get("usd"),
                      "at": time.time(), "spacing": sets.spacing_of(blk)}
    for w in r["suggested"]["spacing"]:
        log(f"spacing: {w['text']}")
    r.pop("suggest_error", None)
    if r.get("status") == "candidate" and not r.get("staging_edited_at"):
        r["blocking"] = blk
        try:
            from .tasks import store_asset
            pv = sets.preview(image, blk, image.parent / f"{set_id}-suggested-{int(time.time())}.png")
            pa = store_asset(db, ep_id=None, src=pv, key=f"sets/{set_id}/{pv.name}", kind="set-candidate-preview",
                             label=f"Set staging (suggested): {r.get('label', set_id)}", content_type="image/png")
            r["preview_asset_id"] = pa.id
        except Exception as e:  # noqa: BLE001 -- the staging stands without a redrawn preview
            log(f"preview not redrawn: {e}")
    recs[set_id] = r
    sets.save(db, recs)
    if usage:
        log(f"vision call: {usage.get('provider')} {usage.get('model')}, {usage.get('input_tokens')} in / "
            f"{usage.get('output_tokens')} out tokens")
    return {"blocking": blk, "info": info, "summary": text}


# ---------------------------------------------------------------- job ("Suggest seats again", owner-started)
from .tasks import Ctx, task  # noqa: E402


@task
def set_seat_suggest(ctx: Ctx) -> dict:
    from .models import Asset
    from .storage import storage
    from . import sets
    db, p = ctx.db, ctx.job.payload or {}
    r = sets.records(db).get(p.get("set_id"))
    if not r or r.get("status") not in ("candidate", "approved"):
        return {"skipped": "no such set"}
    a = db.get(Asset, r["asset_id"])
    folder = ctx.folder("sets", p["set_id"])
    img = storage().get_to_file(a.storage_key, folder / Path(a.storage_key).name)
    got = run(db, p["set_id"], img, ctx.log)
    ctx.log(f"suggested staging: {got['summary']}")
    return {"set_id": p["set_id"], "summary": got["summary"], **got["info"]}
