"""Sets and seating masters (guided flow, step 5): an episode's room made end to end in the dashboard, with the method
the owner proved on Episode 15 (2026-11-26; memory "new-stack-gpu", ep15-ISSUES rows 16-22).

1. WALLS, one straight-on picture each. The image model (Settings > Studio style: Nano Banana 2.1 edit on WaveSpeed)
   CANNOT move the camera around a room: given the wide shot and asked to "show the other side" it returns the same
   view (tested 3 times, also with ChatGPT-written prompts). What works is describing ONE wall as if you stand facing
   it, listing what is on it, with the establishing wide shot passed ONLY as a style/material reference. So every wall
   prompt (template, GPT or the owner's) is checked: wording that asks to move, turn or rotate the camera/view is
   refused (owner) or replaced by the template (GPT). One paid image per click (cost shown, confirm_usd), the owner
   approves one take per wall.
2. SEATING MASTER per side of the room (the storyboard's sides: set id -> characters in seat order): one paid Nano
   picture with the side's approved wall (else its set plate) as image 1 and every character's approved master after
   it, seated left to right in the stored order. The owner approves one; reactions.py offers it first as that side's
   seating master (the owner still picks it there, or with "Use for close-ups" here: never automatic).
3. REPAIRS of an approved picture (wall, seating master or storyboard still) on the rented ComfyUI session
   (comfy_session.py, the gpu.py ledger and monthly cap), Qwen-Image-Edit-2511 masked edits as in the owner's
   famwall.py / react_gpu.py "halo":
     background  people cut out with rembg (birefnet-general) on the GPU over SSH (cutout_remote.py); repaint mask =
                 the owner's box MINUS the people (alpha dilated 17 px); masked repaint with the owner's/GPT's words;
                 second pass on the thin band between the tight outline (alpha > 40, dilated 3 px) and the wide one
                 (dilated 21 px) inside the box, to remove leftovers (the "halo"); then the ORIGINAL people pasted
                 back through the tight outline, so they stay pixel-exact. Outside the box nothing changes.
     face        one masked face edit inside an oval (reactions.edit_graph / paste_back), eyeline sentence added.
   Before/after are shown; only the owner's Approve makes the result the picture (a new take/version).
4. CHARACTER CHECK of every approved still and seating master: heads counted with reactions.find_heads (free) and, on
   the owner's click, Gemini asked "which of these characters are visible" with each one's one-line description (paid,
   or the free tier when the owner ticks it, which lets Google use the picture). Missing or merged characters (Ep15:
   Sidney merged into Ronald in every wide) are flagged with "Remake this picture" (one paid Nano image, confirmed).
5. EYELINE per side, stored where reactions.py keeps it (reactions:<eid> "eyelines"): default from the main speaker
   (the speaker's side looks screen-right, the others screen-left toward the speaker). Shown here, used by the
   seating prompt, the reaction face prompts and the talking-shot prompt.

Nothing is approved by itself. Paid calls: the price is shown first and the request carries it (409 otherwise); a paid
submit is never retried. Keys only through secrets_store.secret(). Reference-video pictures are never used here.
"""
from __future__ import annotations

import base64
import io
import json
import math
import random
import re
import secrets as pysecrets
import shutil
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import reactions as R
from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Character, Episode, Event, Job, Setting
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

JOB_IMAGE, JOB_REPAIR = "room_image", "room_repair"
TEMPLATE_LABEL = "template prompt (GPT unavailable)"
# the owner-proven mask sizes (famwall.py / react_gpu.py "halo"), in picture pixels
PEOPLE_DILATE, TIGHT_DILATE, WIDE_DILATE = 17, 3, 21
TIGHT_ALPHA, PEOPLE_ALPHA = 40, 8
AREA_FEATHER = 4.0
CUTOUT_MIN, CUTOUT_MIN_MAX = 4.0, 8.0        # pip install + the BiRefNet model download on the pod, then the cut-out
GEMINI_IMAGE_TOKENS, GEMINI_MAX_OUT = 1300, 4000
TARGET = re.compile(r"^(wall|seating|still):([A-Za-z0-9_-]{1,40})$")
MAX_WALLS = 12

# wording that asks the image model to move the viewpoint (it cannot; ep15 set-angle test 2026-11-26)
_MOVE = r"(move|moves|moved|moving|rotate|rotates|rotated|rotating|turn|turns|turned|turning|swing|swings|orbit|pan|pans|spin|flip)"
_VIEW = r"(camera|viewpoint|point of view|view|angle|perspective)"
CAMERA_MOVE = re.compile(rf"\b{_MOVE}\b[^.\n]{{0,30}}\b{_VIEW}\b|\b{_VIEW}\b[^.\n]{{0,30}}\b{_MOVE}\b|\breverse (angle|shot)\b"
                         r"|\bfrom the (other|opposite) side\b", re.I)

REPAINT_KEEP = (" Keep exactly the same flat 2D cartoon style, bold black outlines, lighting and colours as the rest of "
                "the picture. Seen straight-on. Do not add people.")
HALO = ("Fill this thin area with the background around it, seamlessly continuing it: {want}. No people, no outlines or "
        "shadows of people, no light leaks. Same flat 2D cartoon style.")


def key(eid: int) -> str:
    return f"roomsets:{eid}"


# ================================================================== pure parts: prompts
def straight_on_problem(text: str) -> str | None:
    """Why a wall prompt cannot be used (it asks the model to move the camera), or None."""
    m = CAMERA_MOVE.search(text or "")
    if not m:
        return None
    return (f"\"{m.group(0)}\": the image model cannot move or turn the camera around a room. Describe the wall itself, "
            "as if you stand facing it, and list what is on it")


def wall_template(name: str, contents: str, has_ref: bool) -> str:
    """One wall, straight-on, with what is on it. The reference (the establishing wide shot) is for style only."""
    parts = [f"A straight-on picture of one wall of a room: the {name.strip().rstrip('.')}. We stand in the middle of the "
             "room facing this wall squarely; the wall is flat and parallel to the picture and fills it from edge to edge, "
             "with a strip of floor along the bottom."]
    if contents.strip():
        parts.append(f"On and in front of this wall: {contents.strip().rstrip('.')}.")
    if has_ref:
        parts.append("The reference image shows the same room. Use it ONLY for the drawing style, the colours, the materials "
                     "and the lighting (wallpaper, wood, fabrics); do not copy its layout or its view.")
    parts.append("Nobody in the picture: no people, no characters. Clean polished flat 2D cartoon background, bold black "
                 "outlines, rich colours. No text, no captions, no watermark.")
    return " ".join(parts)


def seating_template(people: list[tuple[str, str]], has_wall: bool, eyeline: str) -> str:
    """The side's picture with its characters seated in order: image 1 the wall (or set), then each master."""
    n = len(people)
    first = ("Image 1 is this side of the room, seen straight-on: keep its wall, furniture, colours, lighting and the "
             "same straight-on view exactly.") if has_wall else \
            "Image 1 is the room: keep its furniture, colours and lighting."
    lines = [first,
             f"The next {n} image(s) are the approved character masters, in seat order. Draw each character EXACTLY as in "
             "their image (same head, eyes, line style, accessory and colours); never redesign them, never merge two of "
             "them into one, and add nobody else.",
             f"Seat exactly {n} character(s) side by side on chairs in front of the wall, from left to right:"]
    for i, (name, look) in enumerate(people):
        lines.append(f"{i + 1}. {name} (image {i + 2})" + (f": {look.strip().rstrip('.')}" if look.strip() else "") + ".")
    lines.append(f"All {n} must be clearly visible, each on their own chair, the whole head and face showing, not overlapping.")
    if eyeline:
        lines.append(eyeline)
    lines.append("Full bodies, seated, a wide picture of this whole side. Clean polished 2D cartoon, bold black outlines. "
                 "No text, no captions, no speech bubbles, no watermark.")
    return "\n".join(lines)


def ensure_seats(text: str, people: list[tuple[str, str]]) -> str:
    """A written seating prompt with every character named (GPT may leave one out: that is how Sidney went missing)."""
    if all(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n, _ in people):
        return text
    order = ", ".join(f"{n} (image {i + 2})" for i, (n, _) in enumerate(people))
    return f"{text.rstrip()}\nSeat order, left to right, all {len(people)} clearly visible and separate: {order}."


def remake_prompt(base: str, names: list[str]) -> str:
    """A picture made again after the character check flagged it: the same prompt, with the cast spelled out."""
    return (f"{base.rstrip()}\nIMPORTANT: exactly {len(names)} different characters must be visible: {', '.join(names)}. "
            "Each keeps their own look and accessory from their image; never merge two characters into one and never "
            "leave anyone out.")


def repaint_text(want: str) -> str:
    t = want.strip().rstrip(".")
    return f"Repaint ONLY the background inside the masked area: {t}." + REPAINT_KEEP


# ================================================================== pure parts: masks
def box_px(box: dict, size: tuple[int, int]) -> tuple[int, int, int, int]:
    w, h = size
    x0 = int(max(0, min(w, round(float(box["x"])))))
    y0 = int(max(0, min(h, round(float(box["y"])))))
    x1 = int(max(x0, min(w, round(float(box["x"]) + float(box["w"])))))
    y1 = int(max(y0, min(h, round(float(box["y"]) + float(box["h"])))))
    return x0, y0, x1, y1


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    """Grow a boolean mask by r pixels in every direction (a square of side 2r+1: two separable running maxima)."""
    if r <= 0:
        return m.copy()
    a = m.copy()
    for d in range(1, r + 1):
        a[:, d:] |= m[:, :-d]
        a[:, :-d] |= m[:, d:]
    b = a.copy()
    for d in range(1, r + 1):
        b[d:, :] |= a[:-d, :]
        b[:-d, :] |= a[d:, :]
    return b


def _img(m: np.ndarray):
    from PIL import Image
    return Image.fromarray(m.astype(np.uint8) * 255, "L")


def repaint_masks(alpha, box: dict) -> dict:
    """The masks of the background repaint, from the people's alpha (L, the picture's size) and the owner's box:
    area   the box MINUS the people grown by 17 px (pass 1, the repaint)
    band   inside the box, the people grown by 21 px MINUS the tight outline (pass 2, the leftovers: the "halo")
    tight  the people (alpha > 40) grown by 3 px: the original pixels pasted back through it at the end."""
    a = np.asarray(alpha.convert("L"))
    h, w = a.shape
    inbox = np.zeros((h, w), dtype=bool)
    x0, y0, x1, y1 = box_px(box, (w, h))
    inbox[y0:y1, x0:x1] = True
    people = a > PEOPLE_ALPHA
    tight = dilate(a > TIGHT_ALPHA, TIGHT_DILATE)
    area = inbox & ~dilate(people, PEOPLE_DILATE)
    band = inbox & dilate(people, WIDE_DILATE) & ~tight
    return {"area": _img(area), "band": _img(band), "tight": _img(tight)}


def inward(mask, feather: float):
    """A mask softened INWARD only (a blurred copy multiplied by the hard mask): outside it, nothing can change."""
    from PIL import ImageChops, ImageFilter
    if feather <= 0:
        return mask
    return ImageChops.multiply(mask, mask.filter(ImageFilter.GaussianBlur(feather)))


def composite_through(base, edited, mask):
    """The edit model's picture (any size) on the base through the mask: where the mask is 0, the base's pixels."""
    from PIL import Image
    ed = edited.convert("RGB")
    if ed.size != base.size:
        ed = ed.resize(base.size, Image.LANCZOS)
    return Image.composite(ed, base.convert("RGB"), mask)


def paste_people(original, repainted, tight):
    """The original people pasted back through the tight outline: pixel-exact wherever it is set."""
    from PIL import Image
    return Image.composite(original.convert("RGB"), repainted.convert("RGB"), tight)


def mask_empty(mask) -> bool:
    return mask.getbbox() is None


def default_box(heads: list[dict], size: tuple[int, int]) -> dict:
    """The background box suggested for a repaint: the full width, from the top to a little below the heads (the wall
    behind people sitting on chairs); without heads, the top 60%."""
    w, h = size
    if heads:
        y1 = min(h, max(hd["y"] + 2.5 * hd["r"] for hd in heads))
    else:
        y1 = 0.6 * h
    return {"x": 0, "y": 0, "w": w, "h": round(y1)}


def default_oval(head: dict | None, size: tuple[int, int]) -> dict:
    if head:
        return {"cx": round(head["x"], 1), "cy": round(head["y"], 1), "rx": round(head["r"] * 0.78, 1), "ry": round(head["r"] * 0.8, 1)}
    w, h = size
    return {"cx": round(w / 2, 1), "cy": round(h * 0.4, 1), "rx": round(w * 0.06, 1), "ry": round(w * 0.065, 1)}


# ================================================================== pure parts: the character check
def check_prompt(people: list[tuple[str, str]]) -> str:
    who = "\n".join(f"- {n}: {look.strip().rstrip('.') or 'no description'}" for n, look in people)
    return ("This is a picture from a 2D stick-figure cartoon. These characters should all be in it, each as their own "
            f"separate character:\n{who}\nWhich of them are clearly visible? A character is MERGED when their features "
            "(for example their accessory) appear on another character instead of on their own. Reply with JSON only: "
            '{"visible": [names], "missing": [names], "merged": [[name, name]], "extra_people": <number of other '
            'people>, "notes": "<one short sentence>"}')


def parse_check(text: str, names: list[str]) -> dict:
    """Gemini's answer as {visible, missing, merged, extra_people, notes}, names matched to the expected ones."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0) if m else text)
    except (ValueError, TypeError):
        raise ValueError("Gemini's answer was not readable")
    if not isinstance(d, dict):
        raise ValueError("Gemini's answer was not readable")
    canon = {n.lower(): n for n in names}

    def pick(xs) -> list[str]:
        out = []
        for x in xs if isinstance(xs, list) else []:
            n = canon.get(str(x).strip().lower())
            if n and n not in out:
                out.append(n)
        return out
    visible = pick(d.get("visible"))
    missing = pick(d.get("missing"))
    if isinstance(d.get("visible"), list):       # anyone not said to be visible counts as missing
        missing += [n for n in names if n not in visible and n not in missing]
    merged = [pick(g) for g in (d.get("merged") or []) if isinstance(g, list)]
    merged = [g for g in merged if len(g) >= 2]
    try:
        extra = max(0, int(d.get("extra_people") or 0))
    except (TypeError, ValueError):
        extra = 0
    return {"visible": [n for n in visible if n not in missing], "missing": missing, "merged": merged,
            "extra_people": extra, "notes": str(d.get("notes") or "")[:300]}


def check_flags(names: list[str], heads: int | None, gemini: dict | None) -> list[str]:
    """The warnings shown on a picture (empty: nothing wrong found)."""
    out = []
    if heads is not None and heads < len(names):
        out.append(f"Only {heads} head(s) found for {len(names)} characters: someone may be missing or merged into "
                   "another character.")
    if gemini:
        if gemini.get("missing"):
            out.append(f"Gemini cannot see: {', '.join(gemini['missing'])}.")
        for g in gemini.get("merged") or []:
            out.append(f"Gemini says these look merged into one: {' and '.join(g)}.")
        if gemini.get("extra_people"):
            out.append(f"Gemini sees {gemini['extra_people']} extra person(s) who should not be there.")
    return out


# ================================================================== pure parts: cost
def repair_estimate(tool: str, prices: list[float]) -> dict:
    """GPU minutes and cost of one repair: about 10 min to start the session and download Qwen, 60-90 s per masked
    edit (background: 2 passes, face: 1), and for the background the cut-out (rembg install + model, 4-8 min)."""
    edits = 2 if tool == "background" else 1
    cut, cut_max = (CUTOUT_MIN, CUTOUT_MIN_MAX) if tool == "background" else (0.0, 0.0)
    minutes = round(R.SETUP_MIN + edits * R.EDIT_MIN + cut, 1)
    minutes_max = round(R.SETUP_MIN + edits * R.EDIT_MIN_MAX + cut_max, 1)
    p0 = prices[0] if prices else 0.0
    pmax = max(prices) if prices else 0.0
    typ, mx = round(p0 * minutes / 60, 2), round(pmax * minutes_max * R.MAX_MARGIN / 60, 2)
    what = "background repaint (2 passes + cut-out)" if tool == "background" else "face fix (1 masked edit)"
    return {"minutes": minutes, "minutes_max": minutes_max, "usd_typical": typ, "usd_max": mx, "edits": edits,
            "usd_per_hour": p0, "usd_per_hour_max": pmax,
            "label": f"{what}: about {minutes:.0f} GPU min, about ${typ:.2f}, at most ${mx:.2f}"}


def gemini_estimate(cfg: dict, prompt: str, free: bool) -> dict:
    tin = GEMINI_IMAGE_TOKENS + math.ceil(len(prompt) / 3.5)
    p_in, p_out = float(cfg["acting_usd_in"]), float(cfg["acting_usd_out"])
    typ = round(tin * p_in / 1e6 + 600 * p_out / 1e6, 4)
    mx = round(tin * p_in / 1e6 + GEMINI_MAX_OUT * p_out / 1e6, 4)
    return {"model": cfg["acting_model"], "input_tokens": tin, "max_output_tokens": GEMINI_MAX_OUT, "usd_typical": typ,
            "usd_max": mx, "free_models": list(cfg.get("acting_free_models") or []) if free else [],
            "label": f"{cfg['acting_model']}: about ${typ:.4f}, at most ${mx:.4f}" + (" (free tier allowed)" if free else "")}


# ================================================================== episode data
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    v.pop("_dirty", None)
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


def _plan(db: Session, eid: int) -> dict:
    from . import shot_frames as SF
    return SF.migrated(SF.stored(db, eid))


def sides_of(db: Session, eid: int) -> dict[str, list[str]]:
    """The storyboard's sides of the room: {set id: characters in seat order, left to right}."""
    return {k: list(m) for k, m in (_plan(db, eid).get("sides") or {}).items()}


def side_label(db: Session, sid: str) -> str:
    from . import sets as studio_sets
    rec = studio_sets.records(db).get(sid) or {}
    return rec.get("label") or sid.replace("-", " ")


def _people(db: Session, keys: list[str]) -> dict[str, Character]:
    return {c.key: c for c in db.query(Character).filter(Character.key.in_(keys))} if keys else {}


def _url(k: str | None) -> str | None:
    return storage().url(k) if k else None


def _take(v_take: dict) -> dict:
    return {k: v_take.get(k) for k in ("id", "asset_id", "at", "usd", "source", "prompt", "repair")} | {"url": _url(v_take.get("key"))}


def approved_take(rec: dict) -> dict | None:
    return next((t for t in rec.get("takes") or [] if t["id"] == rec.get("approved")), None)


def approved_seating(db: Session, eid: int) -> dict[str, int]:
    """{side: asset id} of the approved seating masters (reactions.py offers them first)."""
    out = {}
    for side, rec in (stored(db, eid).get("seating") or {}).items():
        t = approved_take(rec)
        if t and t.get("asset_id"):
            out[side] = int(t["asset_id"])
    return out


def wall_for_side(v: dict, side: str) -> dict | None:
    """The approved wall picture of a side (its first wall with an approved take)."""
    for w in (v.get("walls") or {}).values():
        if w.get("side") == side and approved_take(w):
            return approved_take(w)
    return None


def eyeline(db: Session, ep: Episode, side: str, k: str = "") -> dict:
    """{direction, default, toward, owner, text} of a side, from reactions' storage (one place for both steps)."""
    rv = R.stored(db, ep.id)
    names = {c.key: c.name for c in db.query(Character)}
    el = R.eyeline_for(db, ep, rv, side, k, names)
    sp = R.main_speaker(ep)
    default = "right" if sp and sp in sides_of(db, ep.id).get(side, []) else "left"
    own = (rv.get("eyelines") or {}).get(side)
    return {"direction": el["direction"], "default": default, "owner": own, "toward": el["toward"],
            "text": R.eyeline_text(el["direction"], el["toward"])}


def style_options(db: Session, ep: Episode, v: dict) -> list[dict]:
    """Pictures the owner may use as the walls' style reference: approved storyboard stills (wide shots first) and
    approved walls. All are the studio's own generated pictures."""
    order = {"wide": 0, "medium": 1, "close": 2}
    out = []
    for s in sorted((s for s in _plan(db, ep.id).get("shots") or [] if s.get("approved") and s.get("chosen")),
                    key=lambda s: (order.get(s.get("shot"), 3), int(s["index"]))):
        if not any(o["asset_id"] == s["chosen"] for o in out):
            out.append({"asset_id": s["chosen"], "label": f"Shot {s['index']} ({s.get('shot') or 'wide'})"})
    for w in (v.get("walls") or {}).values():
        t = approved_take(w)
        if t and t.get("asset_id"):
            out.append({"asset_id": t["asset_id"], "label": f"Wall: {w['name']}"})
    return out


def style_ref(db: Session, ep: Episode, v: dict) -> dict | None:
    """The owner's choice, else the first approved wide still (the establishing shot); None: text only."""
    opts = style_options(db, ep, v)
    own = (v.get("style_ref") or {}).get("asset_id")
    pick = next((o for o in opts if o["asset_id"] == own), None) if own else None
    if pick:
        return {**pick, "source": "owner"}
    return {**opts[0], "source": "suggested"} if opts else None


def wall_prompt(db: Session, ep: Episode, v: dict, w: dict) -> dict:
    p = w.get("prompt")
    if p and p.get("text"):
        return p
    text = wall_template(w["name"], w.get("contents") or "", style_ref(db, ep, v) is not None)
    return {"text": text, "source": "template",
            "label": TEMPLATE_LABEL if not secret("openai_api_key", db) else "template prompt (not written by GPT yet)"}


def seating_people(db: Session, members: list[str]) -> list[tuple[str, str]]:
    chars = _people(db, members)
    return [(chars[k].name if k in chars else k, (chars[k].visual_description or "") if k in chars else "") for k in members]


def seating_prompt(db: Session, ep: Episode, v: dict, side: str) -> dict:
    rec = (v.get("seating") or {}).get(side) or {}
    people = seating_people(db, sides_of(db, ep.id).get(side, []))
    p = rec.get("prompt")
    if p and p.get("text"):
        return {**p, "text": ensure_seats(p["text"], people)}
    text = seating_template(people, wall_for_side(v, side) is not None, eyeline(db, ep, side)["text"])
    return {"text": text, "source": "template",
            "label": TEMPLATE_LABEL if not secret("openai_api_key", db) else "template prompt (not written by GPT yet)"}


# ------------------------------------------------------------------ pictures: targets of repairs and checks
def target_picture(db: Session, ep: Episode, v: dict, target: str) -> dict:
    """{target, kind, ref, label, key, asset_id, people: [keys], side} of an APPROVED picture, or HTTP 404/409."""
    m = TARGET.match(target or "")
    if not m:
        raise HTTPException(422, "a picture is wall:<id>, seating:<side> or still:<shot>")
    kind, ref = m.group(1), m.group(2)
    if kind == "wall":
        w = (v.get("walls") or {}).get(ref)
        if w is None:
            raise HTTPException(404, "no such wall")
        t = approved_take(w)
        if not t:
            raise HTTPException(409, "approve a picture of this wall first")
        return {"target": target, "kind": kind, "ref": ref, "label": f"Wall: {w['name']}", "key": t["key"],
                "asset_id": t.get("asset_id"), "people": [], "side": w.get("side") or ""}
    if kind == "seating":
        sides = sides_of(db, ep.id)
        if ref not in sides:
            raise HTTPException(404, "not a side of this episode's storyboard")
        t = approved_take((v.get("seating") or {}).get(ref) or {})
        if not t:
            raise HTTPException(409, "approve this side's seating picture first")
        return {"target": target, "kind": kind, "ref": ref, "label": f"Seating: {side_label(db, ref)}", "key": t["key"],
                "asset_id": t.get("asset_id"), "people": sides[ref], "side": ref}
    if not ref.isdigit():
        raise HTTPException(422, "a still is still:<shot number>")
    s = next((x for x in _plan(db, ep.id).get("shots") or [] if int(x["index"]) == int(ref)), None)
    if s is None:
        raise HTTPException(404, "no such shot")
    if not (s.get("approved") and s.get("chosen")):
        raise HTTPException(409, f"approve shot {ref}'s still first")
    a = db.get(Asset, s["chosen"])
    if a is None:
        raise HTTPException(409, "the still's picture is missing")
    return {"target": target, "kind": kind, "ref": ref, "label": f"Shot {ref} still", "key": a.storage_key, "asset_id": a.id,
            "people": list(s.get("people") or []), "side": s.get("side") or ""}


def check_pictures(db: Session, ep: Episode, v: dict) -> list[dict]:
    """Every approved storyboard still with people, then every approved seating master."""
    out = []
    plan = _plan(db, ep.id)
    ids = [s["chosen"] for s in plan.get("shots") or [] if s.get("approved") and s.get("chosen") and s.get("people")]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}
    for s in plan.get("shots") or []:
        if s.get("approved") and s.get("chosen") in assets and s.get("people"):
            out.append({"target": f"still:{s['index']}", "label": f"Shot {s['index']} ({s.get('shot') or 'wide'})",
                        "asset_id": s["chosen"], "key": assets[s["chosen"]].storage_key, "people": list(s["people"]),
                        "side": s.get("side") or "", "framing": s.get("shot") or "wide"})
    sides = sides_of(db, ep.id)
    for side, rec in (v.get("seating") or {}).items():
        t = approved_take(rec)
        if t and side in sides:
            out.append({"target": f"seating:{side}", "label": f"Seating: {side_label(db, side)}", "asset_id": t.get("asset_id"),
                        "key": t["key"], "people": sides[side], "side": side, "framing": "seating"})
    return out


def _load(k: str, folder: Path):
    from PIL import Image
    p = storage().get_to_file(k, folder / f"{uuid.uuid4().hex[:8]}{Path(k).suffix or '.png'}")
    with Image.open(p) as im:
        return im.convert("RGB")


def picture_info(v: dict, k: str, auto: bool = True, owner: list[dict] | None = None) -> dict:
    """{size, heads} of a stored picture, read once and kept (heads: reactions.find_heads, the stick heads). For an
    episode in another style (auto=False) the heads are the owner's clicks (`owner`), or None (not counted) until the
    owner has clicked them: find_heads only recognises white round stick heads."""
    cache = v.setdefault("info", {})
    if k in cache and (auto or cache[k].get("heads_by") == "owner"):
        info = cache[k]
    else:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            try:
                im = _load(k, Path(d))
                info = {"size": list(im.size), "heads": R.find_heads(im)[:16] if auto else None}
            except Exception:   # noqa: BLE001 -- unreadable: nothing counted, the owner can still ask Gemini
                info = {"size": [R.W, R.H], "heads": None}
        if not auto:
            info["heads_by"] = "owner"
        cache[k] = info
        v["_dirty"] = True
    if not auto:
        info = {**info, "heads": owner[:16] if owner is not None else None}
    return info


def _pic_info(db: Session, ep: Episode, v: dict, pic: dict) -> dict:
    """picture_info with the episode's style: automatic head finding for the stick man, the owner's clicks otherwise."""
    from . import cast_from_video as CV
    auto = CV.auto_heads(db, ep.id)
    return picture_info(v, pic["key"], auto, None if auto else CV.owner_heads(db, ep.id, pic.get("asset_id")))


# ================================================================== view
def _active(db: Session, eid: int, kinds=(JOB_IMAGE, JOB_REPAIR)):
    return db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(("queued", "running")))


def _busy(db: Session, eid: int, what: str, ref: str) -> bool:
    return any((j.payload or {}).get("what") == what and (j.payload or {}).get("ref") == ref for j in _active(db, eid))


def _image_cost(db: Session) -> dict | None:
    from .stick_pipeline import IMAGE_PROVIDERS, image_cost
    ip = IMAGE_PROVIDERS.get(get_section(db, "stick").get("image_provider"))
    return {**image_cost(1, ip["usd_per_image"]), "provider": ip["label"]} if ip else None


def view(db: Session, ep: Episode, light: bool = False) -> dict:
    from . import comfy_session as CS
    from . import prompt_writer as PW
    from .stick_pipeline import approved_master
    v = stored(db, ep.id)
    sides = sides_of(db, ep.id)
    prices = R._prices(db)
    out: dict = {"walls": [], "seating": [], "repairs": [], "checks": []}
    for w in sorted((v.get("walls") or {}).values(), key=lambda w: w.get("at", 0)):
        p = wall_prompt(db, ep, v, w)
        out["walls"].append({"id": w["id"], "name": w["name"], "side": w.get("side") or "", "contents": w.get("contents") or "",
                             "prompt": p, "takes": [_take(t) for t in w.get("takes") or []], "approved": w.get("approved"),
                             "run": w.get("run"), "busy": _busy(db, ep.id, "wall", w["id"])})
    chars = _people(db, [k for m in sides.values() for k in m])
    for side, members in sides.items():
        rec = (v.get("seating") or {}).get(side) or {}
        no_master = [chars[k].name if k in chars else k for k in members if k not in chars or approved_master(db, chars[k].id) is None]
        wall = wall_for_side(v, side)
        row = {"side": side, "label": side_label(db, side),
               "people": [{"key": k, "name": chars[k].name if k in chars else k} for k in members],
               "takes": [_take(t) for t in rec.get("takes") or []], "approved": rec.get("approved"), "run": rec.get("run"),
               "busy": _busy(db, ep.id, "seating", side), "missing_masters": no_master,
               "wall": {"url": _url(wall["key"]), "asset_id": wall.get("asset_id")} if wall else None,
               "eyeline": eyeline(db, ep, side)}
        if not light:
            row["prompt"] = seating_prompt(db, ep, v, side)
            used = (R.stored(db, ep.id).get("masters") or {}).get(side) or {}
            t = approved_take(rec)
            row["used_for_closeups"] = bool(t and used.get("asset_id") == t.get("asset_id"))
        out["seating"].append(row)
    for rid, rp in sorted((v.get("repairs") or {}).items(), key=lambda kv: -kv[1].get("at", 0)):
        out["repairs"].append({"id": rid, **{k: rp.get(k) for k in ("target", "label", "tool", "box", "oval", "character", "want",
                                                                   "prompt", "status", "run", "approved", "at", "usd")},
                               "before_url": _url(rp.get("src_key")), "after_url": _url(rp.get("result_key")),
                               "mask_url": _url(rp.get("mask_key"))})
    for pic in check_pictures(db, ep, v):
        rec = (v.get("checks") or {}).get(pic["target"]) or {}
        names = [n for n, _ in seating_people(db, pic["people"])]
        info = _pic_info(db, ep, v, pic) if not light or pic["key"] in (v.get("info") or {}) else {"heads": None, "size": None}
        heads = None if info.get("heads") is None else len(info["heads"])
        gem = rec.get("gemini") if rec.get("asset_id") == pic["asset_id"] else None
        out["checks"].append({**{k: pic[k] for k in ("target", "label", "asset_id", "side", "framing")}, "names": names,
                              "people": [{"key": k, "name": n} for k, n in zip(pic["people"], names)],
                              "url": None if light else _url(pic["key"]), "size": info.get("size"),
                              "heads": heads, "gemini": gem, "flags": check_flags(names, heads, gem),
                              "head_points": (info.get("heads") or [])[:len(names) + 4] if not light else None})
    if v.get("_dirty"):
        save(db, ep.id, v)
        db.commit()
    out["busy"] = _active(db, ep.id).first() is not None
    from .cast_from_video import head_finding
    out["head_finding"] = head_finding(db, ep.id)
    if light:
        return out
    job = db.query(Job).filter(Job.kind.in_((JOB_IMAGE, JOB_REPAIR)), Job.episode_id == ep.id).order_by(Job.id.desc()).first()
    sr = style_ref(db, ep, v)
    if sr:
        a = db.get(Asset, sr["asset_id"])
        sr["url"] = _url(a.storage_key) if a else None
    cfg = get_section(db, "guide")
    out.update({
        "job": S.job(job) if job else None, "style_ref": sr, "style_options": style_options(db, ep, v),
        "image_cost": _image_cost(db), "availability": CS.availability(db),
        "repair_estimates": {t: repair_estimate(t, prices) for t in ("background", "face")},
        "gemini": {"key_set": bool(secret("gemini_api_key", db)), "model": cfg["acting_model"],
                   "free_models": list(cfg.get("acting_free_models") or []),
                   "estimate": gemini_estimate(cfg, check_prompt([("x", "y" * 60)] * 5), False)},
        "openai_key": bool(secret("openai_api_key", db)),
        "prompt_estimate": PW.estimate(PW.config(db), PW.SYSTEM, "x" * 2400),
        "sides_known": bool(sides)})
    return out


def summary(db: Session, ep: Episode) -> dict:
    """The guide's step 5: walls, seating masters and the character check."""
    vw = view(db, ep, light=True)
    walls, seats = vw["walls"], vw["seating"]
    wa = sum(1 for w in walls if w["approved"])
    sa = sum(1 for s in seats if s["approved"])
    waiting = any(w["takes"] and not w["approved"] for w in walls) or any(s["takes"] and not s["approved"] for s in seats)
    flagged = [c for c in vw["checks"] if c["flags"]]
    repairs = [r for r in vw["repairs"] if r.get("status") == "done" and r.get("approved") is None]
    if vw["busy"]:
        status = "running"
    elif seats and sa == len(seats) and wa == len(walls) and not flagged and not repairs:
        status = "done"
    elif waiting or flagged or repairs or wa or sa:
        status = "needs_approval"
    else:
        status = "not_started"
    detail = (f"{wa} of {len(walls)} walls approved, {sa} of {len(seats)} seating pictures approved" if seats or walls else "")
    if flagged:
        detail += f"; {len(flagged)} picture(s) may be missing a character"
    return {"status": status, "cost": _image_cost(db), "detail": detail}


# ================================================================== routes
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _event(db: Session, eid: int, msg: str, kind: str = "episode") -> None:
    db.add(Event(episode_id=eid, kind=kind, message=msg))


def _wall(v: dict, wid: str) -> dict:
    w = (v.get("walls") or {}).get(wid)
    if w is None:
        raise HTTPException(404, "no such wall")
    return w


def _side(db: Session, eid: int, side: str) -> list[str]:
    s = sides_of(db, eid)
    if side not in s:
        raise HTTPException(404, "not a side of this episode's storyboard (make the storyboard's shot frames first)")
    return s[side]


@router.get("/episodes/{eid}/room-sets")
def get_room_sets(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class StyleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: int | None = Field(default=None, ge=1)


@router.put("/episodes/{eid}/room-sets/style-reference")
def set_style(eid: int, body: StyleIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The establishing picture the walls take their style, colours and materials from (null: the suggestion)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.asset_id is not None and body.asset_id not in {o["asset_id"] for o in style_options(db, ep, v)}:
        raise HTTPException(409, "pick an approved still or an approved wall of this episode")
    v["style_ref"] = {"asset_id": body.asset_id, "by": user} if body.asset_id else {}
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class WallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    side: str | None = Field(default=None, max_length=80)
    contents: str | None = Field(default=None, max_length=1500)
    prompt: str | None = Field(default=None, max_length=4000)      # "" goes back to the template


def _apply_wall(db: Session, eid: int, w: dict, body: WallIn, user: str) -> None:
    if body.side is not None:
        if body.side and body.side not in sides_of(db, eid):
            raise HTTPException(422, "not a side of this episode's storyboard")
        w["side"] = body.side
    if body.name is not None:
        w["name"] = body.name.strip()
    if body.contents is not None:
        w["contents"] = body.contents.strip()
    if body.prompt is not None:
        t = body.prompt.strip()
        if t:
            why = straight_on_problem(t)
            if why:
                raise HTTPException(422, why)
            w["prompt"] = {"text": t, "source": "owner", "label": "edited by you", "by": user, "at": time.time()}
        else:
            w.pop("prompt", None)


@router.post("/episodes/{eid}/room-sets/walls")
def add_wall(eid: int, body: WallIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """A new wall to draw (free): its name (e.g. "family side"), the side of the room it is behind, what is on it."""
    ep = _episode(db, eid)
    if not body.name:
        raise HTTPException(422, "give the wall a name, e.g. \"back wall\"")
    v = stored(db, eid)
    if len(v.get("walls") or {}) >= MAX_WALLS:
        raise HTTPException(409, f"at most {MAX_WALLS} walls per episode")
    wid = pysecrets.token_hex(4)
    w = {"id": wid, "name": "", "side": "", "contents": "", "takes": [], "approved": None, "at": time.time(), "by": user}
    _apply_wall(db, eid, w, body, user)
    v.setdefault("walls", {})[wid] = w
    save(db, eid, v)
    _event(db, eid, f"Sets: wall \"{w['name']}\" added by {user}")
    db.commit()
    return view(db, ep)


@router.put("/episodes/{eid}/room-sets/walls/{wid}")
def edit_wall(eid: int, wid: str, body: WallIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's edit (free). A prompt asking to move/turn the camera is refused (422): the model cannot do it."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    _apply_wall(db, eid, _wall(v, wid), body, user)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


@router.delete("/episodes/{eid}/room-sets/walls/{wid}")
def delete_wall(eid: int, wid: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    w = _wall(v, wid)
    if _busy(db, eid, "wall", wid):
        raise HTTPException(409, "this wall is being drawn")
    v["walls"].pop(wid)
    save(db, eid, v)
    _event(db, eid, f"Sets: wall \"{w['name']}\" removed by {user} (its pictures stay in the episode's files)")
    db.commit()
    return view(db, ep)


class WriteIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


def _gpt(db: Session, msg: str, confirm: float | None) -> dict | None:
    """One prompt_writer call (cost confirmed first); None without a key or credit (the template stays)."""
    from . import prompt_writer as PW
    cfg = PW.config(db)
    usd_max = PW.estimate(cfg, PW.SYSTEM, msg)["usd_max"]
    api_key = secret("openai_api_key", db)
    if not api_key:
        return None
    if confirm is None or confirm + 1e-9 < usd_max:
        raise HTTPException(409, f"writing this prompt can cost up to ${usd_max:.4f}: confirm that amount to start (nothing was sent)")
    try:
        out = PW.call_openai(api_key, cfg["prompt_model"], PW.SYSTEM, msg, int(cfg["prompt_max_tokens"]))
    except HTTPException as e:
        if e.status_code != 402:
            raise
        return None
    if not out or not out.get("text"):
        return None
    return {"text": out["text"].strip(), "usd": PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg),
            "model": cfg["prompt_model"]}


@router.post("/episodes/{eid}/room-sets/walls/{wid}/write-prompt")
def write_wall_prompt(eid: int, wid: str, body: WriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one GPT call, cost confirmed first). Without an OpenAI key or credit the template is kept, labelled. A
    written prompt that asks to move the camera is not used (the template is kept, and the label says why)."""
    from . import prompt_writer as PW
    ep = _episode(db, eid)
    v = stored(db, eid)
    w = _wall(v, wid)
    notes = (f"Wall: {w['name']}. What is on and in front of it: {w.get('contents') or '(not listed)'}. "
             + ("A reference picture of the same room is given for style, colours and materials only." if style_ref(db, ep, v)
                else "No reference picture."))
    msg = PW.user_message("wall", get_section(db, "stick").get("style_prompt") or "", "", notes, "")
    got = _gpt(db, msg, body.confirm_usd)
    w.pop("prompt", None)
    if got:
        if straight_on_problem(got["text"]):
            w["prompt"] = {**wall_prompt(db, ep, v, w), "label": "template prompt (GPT asked to move the camera, so its text was not used)"}
        else:
            w["prompt"] = {"text": got["text"], "source": "gpt", "label": f"written by {got['model']}", "usd": got["usd"],
                           "at": time.time(), "by": user}
        _event(db, eid, f"Sets: wall \"{w['name']}\" prompt written by {got['model']} (${got['usd']:.4f})")
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class MakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_usd: float | None = Field(default=None, ge=0, le=100)
    prompt: str | None = Field(default=None, max_length=4000)


def _image_provider(db: Session) -> tuple[dict, dict]:
    from .stick_pipeline import image_cost, image_provider
    prov = image_provider(db)
    return prov, image_cost(1, prov["usd_per_image"])


def make_wall(eid: int, wid: str, body: MakeIn, db: Session, user: str) -> dict:
    from .stick_pipeline import require_confirmed
    from .stick_shots import aspect_ratio
    ep = _episode(db, eid)
    v = stored(db, eid)
    w = _wall(v, wid)
    if body.prompt and body.prompt.strip():
        _apply_wall(db, eid, w, WallIn(prompt=body.prompt), user)
    if _busy(db, eid, "wall", wid):
        raise HTTPException(409, "this wall is already being drawn")
    prov, cost = _image_provider(db)
    require_confirmed(cost["usd"], body.confirm_usd)
    p = wall_prompt(db, ep, v, w)
    why = straight_on_problem(p["text"])
    if why:
        raise HTTPException(422, why)
    sr = style_ref(db, ep, v)
    refs = []
    if sr:
        a = db.get(Asset, sr["asset_id"])
        refs = [a.storage_key] if a else []
    job = enqueue(db, JOB_IMAGE, episode_id=eid, payload={"what": "wall", "ref": wid, "prompt": p["text"], "refs": refs,
                                                         "aspect_ratio": aspect_ratio(ep), "provider": prov["id"],
                                                         "usd": cost["usd"], "by": user})
    w["run"] = {"status": "queued", "job_id": job.id, "at": time.time()}
    save(db, eid, v)
    _event(db, eid, f"Sets: wall \"{w['name']}\" picture asked by {user} ({cost['label']})")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/room-sets/walls/{wid}/make")
def make_wall_route(eid: int, wid: str, body: MakeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: one straight-on picture of this wall (the establishing still only as a style reference). A new take,
    not approved."""
    return make_wall(eid, wid, body, db, user)


class ApproveIn(BaseModel):
    take_id: str | None = None


@router.post("/episodes/{eid}/room-sets/walls/{wid}/approve")
def approve_wall(eid: int, wid: str, body: ApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    w = _wall(v, wid)
    if body.take_id is not None and not any(t["id"] == body.take_id for t in w.get("takes") or []):
        raise HTTPException(404, "no such picture of this wall")
    w["approved"], w["approved_by"] = body.take_id, (user if body.take_id else None)
    save(db, eid, v)
    _event(db, eid, f"Sets: wall \"{w['name']}\" {'approved' if body.take_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


# ------------------------------------------------------------------ seating masters
class SeatingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str | None = Field(default=None, max_length=4000)


@router.put("/episodes/{eid}/room-sets/seating/{side}")
def edit_seating(eid: int, side: str, body: SeatingIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's seating prompt (free; "" goes back to the template). Every character is named in it (added if not)."""
    ep = _episode(db, eid)
    _side(db, eid, side)
    v = stored(db, eid)
    rec = v.setdefault("seating", {}).setdefault(side, {"takes": [], "approved": None})
    t = (body.prompt or "").strip()
    if t:
        rec["prompt"] = {"text": t, "source": "owner", "label": "edited by you", "by": user, "at": time.time()}
    else:
        rec.pop("prompt", None)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/room-sets/seating/{side}/write-prompt")
def write_seating_prompt(eid: int, side: str, body: WriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import prompt_writer as PW
    ep = _episode(db, eid)
    members = _side(db, eid, side)
    v = stored(db, eid)
    people = seating_people(db, members)
    notes = ("Seat these characters left to right in this order, each on their own chair, all clearly visible: "
             + "; ".join(f"{i + 1}. {n} (reference image {i + 2}): {look}" for i, (n, look) in enumerate(people))
             + f". Reference image 1 is the {'approved wall of this side, seen straight-on' if wall_for_side(v, side) else 'room'}. "
             + eyeline(db, ep, side)["text"])
    msg = PW.user_message("seating", get_section(db, "stick").get("style_prompt") or "", "", notes, "")
    got = _gpt(db, msg, body.confirm_usd)
    rec = v.setdefault("seating", {}).setdefault(side, {"takes": [], "approved": None})
    rec.pop("prompt", None)
    if got:
        rec["prompt"] = {"text": ensure_seats(got["text"], people), "source": "gpt", "label": f"written by {got['model']}",
                         "usd": got["usd"], "at": time.time(), "by": user}
        _event(db, eid, f"Sets: seating prompt for {side} written by {got['model']} (${got['usd']:.4f})")
    save(db, eid, v)
    db.commit()
    return view(db, ep)


def make_seating(eid: int, side: str, body: MakeIn, db: Session, user: str, extra: str = "") -> dict:
    from .stick_pipeline import approved_master, require_confirmed
    from .stick_shots import aspect_ratio
    ep = _episode(db, eid)
    members = _side(db, eid, side)
    v = stored(db, eid)
    rec = v.setdefault("seating", {}).setdefault(side, {"takes": [], "approved": None})
    if body.prompt and body.prompt.strip():
        rec["prompt"] = {"text": body.prompt.strip(), "source": "owner", "label": "edited by you", "by": user, "at": time.time()}
    if _busy(db, eid, "seating", side):
        raise HTTPException(409, "this side's seating picture is already being made")
    chars = _people(db, members)
    masters = []
    for k in members:
        m = approved_master(db, chars[k].id) if k in chars else None
        if m is None:
            raise HTTPException(409, f"approve a master for {chars[k].name if k in chars else k} first (step 4)")
        masters.append(m.storage_key)
    prov, cost = _image_provider(db)
    require_confirmed(cost["usd"], body.confirm_usd)
    wall = wall_for_side(v, side)
    text = seating_prompt(db, ep, v, side)["text"]
    if extra:
        text = remake_prompt(text, [n for n, _ in seating_people(db, members)])
    job = enqueue(db, JOB_IMAGE, episode_id=eid, payload={"what": "seating", "ref": side, "prompt": text,
                                                         "refs": ([wall["key"]] if wall else []) + masters,
                                                         "set_plate": None if wall else side, "aspect_ratio": aspect_ratio(ep),
                                                         "provider": prov["id"], "usd": cost["usd"], "by": user})
    rec["run"] = {"status": "queued", "job_id": job.id, "at": time.time()}
    save(db, eid, v)
    _event(db, eid, f"Sets: seating picture for {side} asked by {user} ({cost['label']})")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/room-sets/seating/{side}/make")
def make_seating_route(eid: int, side: str, body: MakeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: one picture of this side with its characters seated in order (its approved wall, else its set, as image 1;
    every character's approved master after it). A new take, not approved."""
    return make_seating(eid, side, body, db, user)


@router.post("/episodes/{eid}/room-sets/seating/{side}/approve")
def approve_seating(eid: int, side: str, body: ApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: this picture is the side's seating master (null withdraws). Close-ups use it only after the
    owner also picks it there (or clicks "Use for close-ups")."""
    ep = _episode(db, eid)
    _side(db, eid, side)
    v = stored(db, eid)
    rec = v.setdefault("seating", {}).setdefault(side, {"takes": [], "approved": None})
    if body.take_id is not None and not any(t["id"] == body.take_id for t in rec.get("takes") or []):
        raise HTTPException(404, "no such seating picture")
    rec["approved"], rec["approved_by"] = body.take_id, (user if body.take_id else None)
    rec["order"] = sides_of(db, eid)[side]
    save(db, eid, v)
    _event(db, eid, f"Sets: seating picture for {side} {'approved' if body.take_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/room-sets/seating/{side}/use-for-closeups")
def use_for_closeups(eid: int, side: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: the approved seating picture becomes this side's seating master for the close-ups (step 6;
    reactions.set_master, so its checks apply)."""
    ep = _episode(db, eid)
    _side(db, eid, side)
    t = approved_take((stored(db, eid).get("seating") or {}).get(side) or {})
    if not t or not t.get("asset_id"):
        raise HTTPException(409, "approve this side's seating picture first")
    R.set_master(eid, R.MasterIn(side=side, asset_id=int(t["asset_id"])), db, user)
    return view(db, ep)


class EyelineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    eyeline: str | None = Field(default=None, pattern="^(left|right)$")


@router.put("/episodes/{eid}/room-sets/seating/{side}/eyeline")
def set_eyeline(eid: int, side: str, body: EyelineIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Where this side looks (free; null goes back to the default from the main speaker). Stored with the reactions,
    so the seating, reaction and talking prompts all use the same rule."""
    ep = _episode(db, eid)
    _side(db, eid, side)
    rv = R.stored(db, eid)
    if body.eyeline:
        rv.setdefault("eyelines", {})[side] = body.eyeline
    else:
        (rv.get("eyelines") or {}).pop(side, None)
    R.save(db, eid, rv)
    db.commit()
    return view(db, ep)


# ------------------------------------------------------------------ repairs (rented GPU)
class BoxIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=20000)
    y: float = Field(ge=0, le=20000)
    w: float = Field(ge=8, le=20000)
    h: float = Field(ge=8, le=20000)


class OvalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cx: float = Field(ge=0, le=20000)
    cy: float = Field(ge=0, le=20000)
    rx: float = Field(ge=4, le=5000)
    ry: float = Field(ge=4, le=5000)


class RepairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=3, max_length=60)
    tool: str = Field(pattern="^(background|face)$")
    want: str = Field(min_length=3, max_length=2000)        # what to paint (background) or what the face shows
    box: BoxIn | None = None
    oval: OvalIn | None = None
    character: str | None = Field(default=None, max_length=80)
    confirm_usd: float | None = Field(default=None, ge=0, le=200)


def _gpu_checks(db: Session, eid: int, est: dict, confirm: float | None, what: str) -> None:
    from . import comfy_session as CS
    from . import gpu
    a = CS.availability(db)
    if not a["ok"]:
        raise HTTPException(409, a["reason"])
    if _active(db, eid, (JOB_REPAIR,)).first():
        raise HTTPException(409, "a repair is already running for this episode")
    if confirm is None or confirm + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"{what} can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    c = get_section(db, "gpu")
    fig = gpu.month_figures(db)
    if fig["committed_usd"] + est["usd_max"] > float(c["monthly_cap_usd"]) + 1e-9:
        raise HTTPException(409, f"Paused: this repair (up to ${est['usd_max']:.2f}) would pass the monthly GPU cap "
                                 f"(${fig['committed_usd']:.2f} committed of ${float(c['monthly_cap_usd']):.2f}). Raise the cap or wait for next month")


def start_repair(eid: int, body: RepairIn, db: Session, user: str) -> dict:
    ep = _episode(db, eid)
    v = stored(db, eid)
    pic = target_picture(db, ep, v, body.target)
    info = _pic_info(db, ep, v, pic)
    size = tuple(info["size"])
    heads = info.get("heads") or []
    rec = {"target": pic["target"], "label": pic["label"], "tool": body.tool, "want": body.want.strip(),
           "src_key": pic["key"], "src_asset": pic["asset_id"], "size": list(size), "at": time.time(), "by": user,
           "status": "queued", "approved": None}
    if body.tool == "background":
        box = body.box.model_dump() if body.box else default_box(heads, size)
        x0, y0, x1, y1 = box_px(box, size)
        if x1 - x0 < 8 or y1 - y0 < 8:
            raise HTTPException(422, "the box is outside the picture")
        rec["box"] = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
        rec["prompt"] = repaint_text(body.want)
    else:
        members = pic["people"]
        k = body.character or (members[0] if len(members) == 1 else None)
        if not k or k not in members:
            raise HTTPException(422, "say whose face to fix (a character in this picture)")
        hp = R.heads_for_people(heads, members)
        o = body.oval.model_dump() if body.oval else default_oval(hp.get(k), size)
        rec["oval"] = {"cx": min(max(o["cx"], 0), size[0]), "cy": min(max(o["cy"], 0), size[1]), "rx": o["rx"], "ry": o["ry"]}
        rec["character"] = k
        c = _people(db, [k]).get(k)
        el = eyeline(db, ep, pic["side"], k) if pic["side"] else None
        text = R.face_template(c.name if c else k, (c.visual_description or "") if c else "", body.want,
                               el["text"] if el else "The eyes look where they looked before.")
        rec["prompt"] = R.with_rules(text, el["text"]) if el else text
    est = repair_estimate(body.tool, R._prices(db))
    _gpu_checks(db, eid, est, body.confirm_usd, "this repair")
    rid = pysecrets.token_hex(4)
    job = enqueue(db, JOB_REPAIR, episode_id=eid, payload={"repair": rid, "confirm_usd": float(body.confirm_usd),
                                                          "estimate": est, "by": user, "backend": "gpu"})
    rec["run"] = {"status": "queued", "job_id": job.id, "at": time.time()}
    rec["estimate"] = est
    v.setdefault("repairs", {})[rid] = rec
    save(db, eid, v)
    _event(db, eid, f"Sets: {pic['label']} {body.tool} repair asked by {user} (up to ${est['usd_max']:.2f})")
    db.commit()
    return {**S.job(job), "repair": rid}


@router.post("/episodes/{eid}/room-sets/repairs")
def repair_route(eid: int, body: RepairIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: a masked repair of an approved picture on the rented GPU (repaint the background behind the people, or fix
    one face). Starts only with the most it can cost confirmed and within the monthly GPU cap."""
    return start_repair(eid, body, db, user)


class RepairDecisionIn(BaseModel):
    approved: bool


@router.post("/episodes/{eid}/room-sets/repairs/{rid}/approve")
def approve_repair(eid: int, rid: str, body: RepairDecisionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's decision on a repair result. Approve: the result becomes the picture (a new approved take of the
    wall / seating master, or a new approved version of the still). Reject: kept in the list, nothing changes."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    rp = (v.get("repairs") or {}).get(rid)
    if rp is None:
        raise HTTPException(404, "no such repair")
    if rp.get("status") != "done" or not rp.get("result_key"):
        raise HTTPException(409, "this repair has no result yet")
    if rp.get("approved") is not None:
        raise HTTPException(409, "this repair was already decided")
    rp["approved"], rp["decided_by"] = body.approved, user
    if body.approved:
        kind, ref = TARGET.match(rp["target"]).groups()
        take = {"id": pysecrets.token_hex(4), "key": rp["result_key"], "asset_id": rp.get("result_asset"), "at": time.time(),
                "usd": rp.get("usd"), "source": "repair", "repair": rid, "prompt": rp.get("prompt")}
        if kind == "wall":
            w = _wall(v, ref)
            w.setdefault("takes", []).append(take)
            w["approved"], w["approved_by"] = take["id"], user
        elif kind == "seating":
            rec = v.setdefault("seating", {}).setdefault(ref, {"takes": [], "approved": None})
            rec.setdefault("takes", []).append(take)
            rec["approved"], rec["approved_by"] = take["id"], user
        else:
            from . import shot_frames as SF
            plan = SF.migrated(SF.stored(db, eid))
            s = next((x for x in plan.get("shots") or [] if int(x["index"]) == int(ref)), None)
            if s is None:
                raise HTTPException(409, "the shot is gone from the storyboard")
            s.setdefault("versions", []).append({"asset_id": rp.get("result_asset"), "at": time.time(), "source": "repair",
                                                 "note": f"repaired ({rp['tool']})", "side": s.get("side"),
                                                 "people": list(s.get("people") or []), "shot": s.get("shot"),
                                                 "emotions": dict(s.get("emotions") or {})})
            s.update(chosen=rp.get("result_asset"), asset_id=rp.get("result_asset"), approved=True)
            SF.save(db, eid, plan)
    save(db, eid, v)
    _event(db, eid, f"Sets: {rp['label']} repair {'approved' if body.approved else 'rejected'} by {user}", "approval")
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/room-sets/stop")
def stop(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import comfy_session as CS
    _episode(db, eid)
    try:
        done = CS.stop(db, f"stopped by {user}")
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f"RunPod could not be reached; the session is still open: {str(e)[:200]}")
    return {"terminated": done}


# ------------------------------------------------------------------ character check
class GeminiIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=3, max_length=60)
    use_free_tier: bool = False
    confirm_usd: float | None = Field(default=None, ge=0, le=5)


def _check_target(db: Session, ep: Episode, v: dict, target: str) -> dict:
    pic = next((p for p in check_pictures(db, ep, v) if p["target"] == target), None)
    if pic is None:
        raise HTTPException(404, "not an approved still or seating picture of this episode")
    return pic


@router.post("/episodes/{eid}/room-sets/checks/gemini")
def gemini_check(eid: int, body: GeminiIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one Gemini call, cost confirmed first; the free tier only when ticked): which of the picture's characters
    are visible. The picture is one of the studio's own generated stills, never a reference-video frame."""
    from . import acting_analysis as AA
    from .providers import ProviderError
    ep = _episode(db, eid)
    v = stored(db, eid)
    pic = _check_target(db, ep, v, body.target)
    people = seating_people(db, pic["people"])
    cfg = get_section(db, "guide")
    prompt = check_prompt(people)
    est = gemini_estimate(cfg, prompt, body.use_free_tier)
    api_key = secret("gemini_api_key", db)
    if not api_key:
        raise HTTPException(409, "save the Gemini key under Settings > Credentials first")
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"this check can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    import tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        im = _load(pic["key"], Path(d))
    im.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    req = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
                                   {"text": prompt}]}],
           "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": GEMINI_MAX_OUT}}
    models = [cfg["acting_model"]] + (list(cfg.get("acting_free_models") or []) if body.use_free_tier else [])
    try:
        with AA.client() as c:
            model, d = AA.generate(c, api_key, models, req, lambda m: None)
    except ProviderError as e:
        raise HTTPException(502, str(e))
    try:
        res = parse_check(AA.answer_text(d), [n for n, _ in people])
    except ValueError as e:
        raise HTTPException(502, str(e))
    u = d.get("usageMetadata") or {}
    free = model in set(cfg.get("acting_free_models") or []) and model != cfg["acting_model"]
    usd = 0.0 if free else round(int(u.get("promptTokenCount") or 0) * float(cfg["acting_usd_in"]) / 1e6 +
                                 (int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0))
                                 * float(cfg["acting_usd_out"]) / 1e6, 6)
    v.setdefault("checks", {})[pic["target"]] = {"asset_id": pic["asset_id"], "gemini": {**res, "model": model, "usd": usd,
                                                                                        "free_tier": free, "at": time.time()}}
    save(db, eid, v)
    _event(db, eid, f"Sets: character check of {pic['label']} by {model} (${usd:.4f})"
                    + (f": missing {', '.join(res['missing'])}" if res["missing"] else ""))
    db.commit()
    return view(db, ep)


class RemakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=3, max_length=60)
    confirm_usd: float | None = Field(default=None, ge=0, le=100)


@router.post("/episodes/{eid}/room-sets/checks/remake")
def remake(eid: int, body: RemakeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one Nano image, confirmed): the flagged picture made again with every character spelled out. A still
    becomes a new take of its shot (stick_shots.make_still), a seating picture a new take of its side; neither is
    approved."""
    from . import shot_frames as SF
    from . import stick_shots as SS
    ep = _episode(db, eid)
    v = stored(db, eid)
    pic = _check_target(db, ep, v, body.target)
    names = [n for n, _ in seating_people(db, pic["people"])]
    if pic["target"].startswith("seating:"):
        return make_seating(eid, pic["side"], MakeIn(confirm_usd=body.confirm_usd), db, user, extra="remake")
    n = int(pic["target"].split(":")[1])
    plan = SF.migrated(SF.stored(db, eid))
    s = next(x for x in plan["shots"] if int(x["index"]) == n)
    cx = SS.shot_context(db, ep, plan, s)
    base = SS.still_prompt(s, cx["names"], cx["standing"], cx["speaker"], cx["said"], cx["action"], SS.aspect_ratio(ep))
    return SS.make_still(eid, n, SS.StillIn(confirm_usd=body.confirm_usd, prompt=remake_prompt(base, names)), db, user)


# ================================================================== chat (shot_chat.py threads wall:/seating:/repair:)
def chat_context(db: Session, ep: Episode, step: str, item: str) -> dict:
    v = stored(db, ep.id)
    rules = ("The image model cannot move or turn the camera around a room: a wall is always described straight-on, as "
             "if standing facing it, with what is on it. Repairs are masked edits: the people are cut out and pasted "
             "back pixel-exact, only the background inside the box changes.")
    if step == "wall":
        w = _wall(v, item)
        return {"item": f"Wall \"{w['name']}\" (a straight-on picture of one wall)", "current_prompt": wall_prompt(db, ep, v, w)["text"],
                "settings": {"what_is_on_it": w.get("contents"), "side": w.get("side"), "pictures": len(w.get("takes") or []),
                             "approved": bool(w.get("approved")), "rules": rules}}
    if step == "seating":
        members = _side(db, ep.id, item)
        rec = (v.get("seating") or {}).get(item) or {}
        return {"item": f"Seating picture of {side_label(db, item)}", "current_prompt": seating_prompt(db, ep, v, item)["text"],
                "settings": {"seat_order": [n for n, _ in seating_people(db, members)], "eyeline": eyeline(db, ep, item)["text"],
                             "pictures": len(rec.get("takes") or []), "approved": bool(rec.get("approved")),
                             "repaint_box": "optional {x, y, w, h} in picture pixels; leave it out for the area above the heads",
                             "rules": rules}}
    rp = (v.get("repairs") or {}).get(item)
    if rp is None:
        raise HTTPException(404, "no such repair")
    return {"item": f"Repair of {rp['label']} ({rp['tool']})", "current_prompt": rp.get("prompt") or "",
            "settings": {"box": rp.get("box"), "status": rp.get("status"), "approved": rp.get("approved"), "rules": rules}}


def chat_target(db: Session, ep: Episode, step: str, item: str) -> str:
    """The picture a repaint_background proposal repairs: the seating master, or the repair's own target."""
    if step == "seating":
        return f"seating:{item}"
    rp = (stored(db, ep.id).get("repairs") or {}).get(item)
    if rp is None:
        raise HTTPException(404, "no such repair")
    return rp["target"]


def chat_cost(db: Session, p: dict) -> dict:
    if p["type"] == "remake_wall":
        c = _image_cost(db)
        return c if c else {"usd": None, "label": "no image service chosen"}
    est = repair_estimate("background", R._prices(db))
    return {"usd": est["usd_max"], "label": f"up to ${est['usd_max']:.2f} of GPU time ({est['label']})"}


def chat_apply(db: Session, ep: Episode, step: str, item: str, p: dict, confirm: float | None, user: str) -> dict:
    if p["type"] == "remake_wall":
        j = make_wall(ep.id, item, MakeIn(confirm_usd=confirm, prompt=p["prompt"]), db, user)
        return {"done": "A new picture of this wall is being made.", "job_id": j["id"]}
    target = chat_target(db, ep, step, item)
    box = p.get("box")
    if box is None and step == "repair":
        box = (stored(db, ep.id).get("repairs") or {}).get(item, {}).get("box")
    j = start_repair(ep.id, RepairIn(target=target, tool="background", want=p["prompt"], box=BoxIn(**box) if box else None,
                                     confirm_usd=confirm), db, user)
    return {"done": "The background is being repainted on the rented GPU.", "job_id": j["id"]}


# ================================================================== the jobs
from .tasks import Ctx, store_asset, task  # noqa: E402


def _set_image_run(db: Session, eid: int, what: str, ref: str, **run) -> None:
    db.expire_all()
    v = stored(db, eid)
    rec = (v.get("walls") or {}).get(ref) if what == "wall" else v.setdefault("seating", {}).setdefault(ref, {"takes": [], "approved": None})
    if rec is None:
        return
    rec["run"] = {**(rec.get("run") or {}), **run}
    save(db, eid, v)
    db.commit()


@task
def room_image(ctx: Ctx) -> dict:
    """One wall or seating picture (paid, one Nano image); a new take, not approved."""
    from . import stick_shots as SS
    from .stick_pipeline import run_images
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    what, ref = p["what"], p["ref"]
    folder = ctx.folder("episodes", ep.id, "room-sets", f"{what}-job{job.id}")
    _set_image_run(db, ep.id, what, ref, status="running", started=time.time(), error="")
    try:
        refs = []
        if p.get("set_plate"):
            refs.append(SS.set_image(db, p["set_plate"], folder))
        for i, k in enumerate(p.get("refs") or []):
            refs.append(storage().get_to_file(k, folder / f"ref-{i}{Path(k).suffix or '.png'}"))
        asset = None
        for _i, f in run_images(ctx, p["provider"], p["prompt"], refs, 1, float(p["usd"]), p["aspect_ratio"], folder,
                                f"episode {ep.id} {what} {ref}"):
            k = f"episodes/{ep.id}/room-sets/{what}-{re.sub(r'[^A-Za-z0-9_-]', '_', ref)}-job{job.id}.png"
            asset = store_asset(db, ep_id=ep.id, src=f, key=k, kind="seating-master" if what == "seating" else "room-wall",
                                label=f"{'Seating' if what == 'seating' else 'Wall'} {ref}", content_type="image/png", job_id=job.id)
            db.commit()
        db.expire_all()
        v = stored(db, ep.id)
        rec = (v.get("walls") or {}).get(ref) if what == "wall" else v.setdefault("seating", {}).setdefault(ref, {"takes": [], "approved": None})
        if rec is None:
            raise ValueError("the wall was removed while it was being drawn (the picture is kept in the episode's files)")
        rec.setdefault("takes", []).append({"id": pysecrets.token_hex(4), "key": asset.storage_key, "asset_id": asset.id,
                                            "at": time.time(), "usd": float(p["usd"]), "source": "image model",
                                            "prompt": p["prompt"], "job_id": job.id})
        rec["run"] = {**(rec.get("run") or {}), "status": "done", "finished": time.time()}
        save(db, ep.id, v)
        _event(db, ep.id, f"Sets: {what} {ref} picture made (not approved)")
        db.commit()
    except Exception as e:
        _set_image_run(db, ep.id, what, ref, status="failed", error=str(e)[:300])
        raise
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {"what": what, "ref": ref, "asset_id": asset.id}


def _set_repair(db: Session, eid: int, rid: str, **fields) -> None:
    db.expire_all()
    v = stored(db, eid)
    rp = (v.get("repairs") or {}).get(rid)
    if rp is None:
        return
    run = fields.pop("run", None)
    rp.update(fields)
    if run:
        rp["run"] = {**(rp.get("run") or {}), **run}
    save(db, eid, v)
    db.commit()


class _RepairRun(R._Run):
    """reactions' GPU run (session, spend, confirmed limit, graph polling, turn-off), reporting into the repair."""

    def __init__(self, ctx: Ctx, eid: int, rid: str, confirm: float):
        super().__init__(ctx, eid, 0, confirm)
        self.rid = rid

    def stage(self, text: str) -> None:
        self.ctx.log(text)
        _set_repair(self.db, self.eid, self.rid, run={"stage": text})


def _edit(run: _RepairRun, cl, src_img, mask, prompt: str, folder: Path, name: str):
    """One masked Qwen edit on the session: the picture and the mask uploaded, the result downloaded (PIL RGB)."""
    from PIL import Image
    from .comfy import ComfyError
    if not run.room_for(R.EDIT_MIN_MAX):
        raise ValueError(f"stopped: the next step would pass the confirmed ${run.confirm:.2f}")
    src, msk = folder / f"{name}-in.png", folder / f"{name}-mask.png"
    src_img.save(src)
    mask.convert("RGB").save(msk)
    outs = run.run_graph(R.edit_graph(cl.upload(src), cl.upload(msk), prompt, random.randint(1, 2**31 - 1),
                                      f"{name}-{uuid.uuid4().hex[:6]}"), R.EDIT_MIN_MAX)
    files = [f for f in R.image_outputs(outs) if f.get("type", "output") == "output"]
    if not files:
        raise ComfyError("the GPU returned no picture")
    got = cl.download(files[0], folder / f"{name}-out.png")
    with Image.open(got) as im:
        return im.convert("RGB")


@task
def room_repair(ctx: Ctx) -> dict:
    """A background repaint (cut-out, masked repaint, halo pass, people pasted back) or a face fix on the rented GPU.
    The result waits for the owner's Approve."""
    from PIL import Image
    from . import comfy_session as CS
    from . import cutout_remote as CR
    from . import gpu
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    rid = p["repair"]
    folder = ctx.folder("episodes", ep.id, f"room-repair-job{job.id}")
    run = _RepairRun(ctx, ep.id, rid, float(p.get("confirm_usd") or 0))
    _set_repair(db, ep.id, rid, status="running", run={"status": "running", "started": time.time(), "error": "",
                                                       "est_s": int(p.get("estimate", {}).get("minutes", 10) * 60)})
    try:
        rp = (stored(db, ep.id).get("repairs") or {}).get(rid)
        if rp is None:
            raise ValueError("the repair was removed")
        orig = _load(rp["src_key"], folder)
        run.session(R.QWEN_MODELS)
        cl = run.sess["client"]
        name = f"ep{ep.id}-repair-{rid}"
        mask_show = None
        if rp["tool"] == "background":
            run.stage("Cutting the people out (rembg) on the GPU")
            led = gpu.ledger(db)["sessions"][run.sess["session"]]
            where = CS.ssh_endpoint(run.sess["pod_id"])
            if not where:
                raise ValueError("the GPU's SSH port is not published, so the people cannot be cut out")
            src = folder / "picture.png"
            orig.save(src)
            alpha_p = CR.cut_out(where[0], where[1], CS.ssh_key(led), src, folder / "alpha.png", ctx.log)
            with Image.open(alpha_p) as a:
                alpha = a.convert("L")
            masks = repaint_masks(alpha, rp["box"])
            if mask_empty(masks["area"]):
                raise ValueError("the box has no background left once the people are taken out: draw a bigger box")
            run.stage(f"Repainting the background on {run.sess['gpu_type']}")
            raw1 = _edit(run, cl, orig, masks["area"], rp["prompt"], folder, f"{name}-p1")
            cur = composite_through(orig, raw1, inward(masks["area"], AREA_FEATHER))
            if not mask_empty(masks["band"]):
                run.stage("Cleaning the thin band around the people (halo)")
                raw2 = _edit(run, cl, cur, masks["band"], HALO.format(want=rp["want"].rstrip(".")), folder, f"{name}-p2")
                cur = composite_through(cur, raw2, masks["band"])
            final = paste_people(orig, cur, masks["tight"])
            mask_show = masks["area"]
        else:
            run.stage(f"Fixing the face on {run.sess['gpu_type']}")
            o = rp["oval"]
            raw = _edit(run, cl, orig, R.oval_mask(o, orig.size), rp["prompt"], folder, f"{name}-face")
            final = R.paste_back(orig, raw, o)
            mask_show = R.oval_mask(o, orig.size)
        usd = round(run.spent(), 3)
        k = f"episodes/{ep.id}/room-sets/repair-{rid}.png"
        f = folder / "final.png"
        final.save(f)
        a = store_asset(db, ep_id=ep.id, src=f, key=k, kind="repair", label=f"Repair of {rp['label']}", content_type="image/png",
                        job_id=job.id)
        mk = f"episodes/{ep.id}/room-sets/repair-{rid}-mask.png"
        mf = folder / "mask.png"
        mask_show.save(mf)
        storage().put_file(mk, mf, "image/png")
        db.commit()
        _set_repair(db, ep.id, rid, status="done", result_key=k, result_asset=a.id, mask_key=mk, usd=usd,
                    run={"status": "done", "stage": "", "finished": time.time()})
        _event(db, ep.id, f"Sets: {rp['label']} {rp['tool']} repair made (not approved)")
        db.commit()
    except Exception as e:
        _set_repair(db, ep.id, rid, status="failed", run={"status": "failed", "error": str(e)[:300], "stage": ""})
        raise
    finally:
        run.finish(job.id)
        shutil.rmtree(folder, ignore_errors=True)
    return {"repair": rid, "usd": round(run.spent(), 3)}
