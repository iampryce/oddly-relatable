"""Face expressions drawn by code on the character's approved neutral drawing ("we draw only once", owner 2026-11-24).

An image generator redraws the whole character for every expression, so hair, clothes and colours drift. Here an
expression changes ONLY the face: the brows and mouth found on the approved neutral are cleared to the skin colour and
new brows, eyelids and a mouth are drawn in the drawing's own line weight. Every other pixel (hair, hat, clothes,
colours, body, arms) is the approved drawing, unchanged, so the character cannot drift between expressions, shots or
episodes. No AI call, no cost.

How the face is found (house style: big round white eyes with black pupils, line brows, a simple mouth):
- eyes: the two largest round near-white regions in the upper part of the figure;
- skin: the median colour just below the eyes; the face is the skin region connected to that point, and its hull is
  the face plus everything it encloses (brows, mouth);
- brows: thick dark strokes in the band above the eyes (thin lines such as a veil net stay);
- mouth: dark or red marks inside the hull below the eyes (grey moustaches and pink cheek circles stay);
- lips: when the original mouth is red (lipstick), closed-mouth lines are drawn in that red.

The new poses go to review like any pose: only the owner's approval makes them part of the character.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .engine import _reach

EXPRESSIONS = ("smug", "shocked", "angry", "deadpan", "worried", "happy", "laughing")
SS = 4   # supersampling for smooth lines


class FaceNotFound(ValueError):
    pass


def _dilate(m: np.ndarray, n: int) -> np.ndarray:
    for _ in range(n):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g
    return m


def _components(mask: np.ndarray, min_px: int) -> list[np.ndarray]:
    out, left = [], mask.copy()
    while left.any():
        y, x = np.argwhere(left)[0]
        region = _reach(left, (int(y), int(x)))
        left &= ~region
        if region.sum() >= min_px:
            out.append(region)
    return out


def analyse(img: Image.Image) -> dict:
    a = np.array(img.convert("RGBA")).astype(np.int32)
    h, w = a.shape[:2]
    op = a[..., 3] > 128
    rgb = a[..., :3]
    white = op & (rgb.min(2) > 232)
    white[int(h * 0.45):] = False
    eyes = []
    for r in sorted(_components(white, max(300, h * w // 1000)), key=lambda m: -int(m.sum())):
        ys, xs = np.nonzero(r)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        bw, bh = x1 - x0, y1 - y0
        if 0.5 < bw / max(bh, 1) < 1.6 and r.sum() > 0.55 * bw * bh:
            eyes.append((x0, y0, x1, y1))
        if len(eyes) == 2:
            break
    if len(eyes) < 2:
        raise FaceNotFound("could not find two round white eyes on the neutral drawing")
    eyes.sort()
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = eyes
    eh, ew = max(ly1 - ly0, ry1 - ry0), max(lx1 - lx0, rx1 - rx0)
    cy, run, x = (ly0 + ly1) // 2, 0, lx0 - 1
    while x > 0 and rgb[cy, x].max() < 90:
        run, x = run + 1, x - 1
    lw = max(4, run)
    cheek = rgb[ly1 + lw + 6: ly1 + lw + 6 + max(4, eh // 5), lx0:rx1]
    ok = cheek.min(2) > 120
    if not ok.any():
        raise FaceNotFound("could not find the skin colour below the eyes")
    skin = tuple(int(v) for v in np.median(cheek[ok], 0))
    return {"eyes": eyes, "eh": int(eh), "ew": int(ew), "lw": int(lw), "skin": skin}


def _face(a: np.ndarray, f: dict) -> tuple[np.ndarray, np.ndarray]:
    """face: skin pixels connected to the cheek; hull: the face plus everything it encloses."""
    rgb = a[..., :3].astype(np.int32)
    (lx0, ly0, lx1, ly1), _ = f["eyes"]
    seed = (int(ly1 + f["lw"] * 3 + 4), int((lx0 + lx1) / 2))
    skinlike = (np.abs(rgb - np.array(f["skin"])).max(2) <= 40) & (a[..., 3] > 128)
    face = _reach(skinlike, seed)
    if not face.any():
        raise FaceNotFound("could not find the face around the eyes")
    ys, xs = np.nonzero(face)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    sub = ~face[y0:y1, x0:x1]
    padded = np.pad(sub, 1, constant_values=True)
    outside = _reach(padded, (0, 0))[1:-1, 1:-1]
    hull = np.zeros_like(face)
    hull[y0:y1, x0:x1] = ~outside
    return face, hull


def render(img: Image.Image, expression: str, f: dict | None = None) -> Image.Image:
    if expression not in EXPRESSIONS:
        raise ValueError(f"no face drawing for {expression!r}; available: {', '.join(EXPRESSIONS)}")
    img = img.convert("RGBA")
    f = dict(f or analyse(img))
    W, H = img.size
    a = np.array(img)
    rgb = a[..., :3].astype(np.int32)
    (lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1) = f["eyes"]
    eh, ew, lw, skin = f["eh"], f["ew"], f["lw"], f["skin"]
    face, hull = _face(a, f)

    # brows: thick dark strokes in the band above the eyes, inside the face hull (thin net lines stay)
    bx0, by0 = int(max(0, lx0 - ew * .15)), int(max(0, min(ly0, ry0) - eh * .55))
    bx1, by1 = int(min(W, rx1 + ew * .15)), int(max(0, min(ly0, ry0) - lw * 1.2))
    dark = rgb[by0:by1, bx0:bx1].max(2) < 90
    thick = dark.copy()
    for dy in (-2, 0, 2):
        for dx in (-2, 0, 2):
            thick &= np.roll(np.roll(dark, dy, 0), dx, 1)
    if not thick.any() or not _components(thick, 12):
        # thin brows (some characters): a 3-pixel-wide test instead of 5
        thick = dark.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                thick &= np.roll(np.roll(dark, dy, 0), dx, 1)
    brow_w = lw
    skinlike = (np.abs(rgb - np.array(skin)).max(2) <= 40) & (a[..., 3] > 128)
    brows_all = np.zeros_like(face)
    if thick.any():
        brow_w = int(max(lw, round(thick.sum() / max(1, thick.any(0).sum()) + 4)))
        band_skin = skinlike[by0:by1, bx0:bx1]
        for comp in _components(thick, 12):
            # a brow is a thick stroke largely surrounded by skin (measured: brows 0.42-0.59, hair outlines 0.35 or less)
            ring = _dilate(comp, 5) & ~_dilate(comp, 2)
            if ring.any() and band_skin[ring].mean() >= 0.38:
                stroke = _dilate(comp, 4) & (rgb[by0:by1, bx0:bx1].max(2) < 200)
                brows_all[by0:by1, bx0:bx1] |= stroke
        a[brows_all, :3] = skin

    # mouth: dark or red marks inside the hull below the eyes (grey moustaches and pink cheeks stay)
    eyezone = np.zeros_like(face)
    for (x0, y0, x1, y1) in f["eyes"]:
        eyezone[max(0, y0 - lw * 3): y1 + lw * 3, max(0, x0 - lw * 3): x1 + lw * 3] = True
    below = np.zeros_like(face)
    below[int(max(ly1, ry1) + lw):, :] = True
    greyish = ((rgb.max(2) - rgb.min(2)) < 25) & (rgb.max(2) > 110)
    blush = (rgb[..., 0] > 230) & (rgb[..., 1] > 140) & (rgb[..., 2] > 140) & (rgb[..., 0] - rgb[..., 2] > 50)
    mouth = hull & ~face & ~eyezone & below & ~greyish & ~blush
    lips = None
    if mouth.any():
        red = mouth & (rgb[..., 0] > 140) & (rgb[..., 1] < 90)
        if red.sum() > 40:
            lips = tuple(int(v) for v in np.median(rgb[red], 0))
        mouth = _dilate(mouth, 2) & hull & ~greyish & ~blush & (np.abs(rgb - np.array(skin)).max(2) > 8)
        a[mouth, :3] = skin
    base = Image.fromarray(a)

    # new features on a transparent layer (supersampled), laid over the cleared drawing: no other pixel changes
    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    dr = ImageDraw.Draw(big)
    k = lambda v: v * SS
    L = brow_w * SS
    ink = (18, 18, 18, 255)
    lip = (lips + (255,)) if lips else ink
    inside = (tuple(int(v * .8) for v in lips) + (255,)) if lips else (120, 35, 45, 255)   # an open mouth reads as a mouth
    mid, my, mw = (lx1 + rx0) / 2, ly1 + eh * .42, ew * .45
    lc, rc, by, bh = (lx0 + lx1) / 2, (rx0 + rx1) / 2, min(ly0, ry0) - eh * .22, ew * .32

    def lid(box, frac, slant=0.0):
        x0, y0, x1, y1 = box
        cut = y0 + (y1 - y0) * frac
        m = Image.new("L", big.size, 0)
        ImageDraw.Draw(m).ellipse([k(x0 + 1), k(y0 + 1), k(x1 - 1), k(y1 - 1)], fill=255)
        cover = Image.new("L", big.size, 0)
        ImageDraw.Draw(cover).polygon([(k(x0 - 2), k(y0 - 2)), (k(x1 + 2), k(y0 - 2)), (k(x1 + 2), k(cut + slant)),
                                       (k(x0 - 2), k(cut - slant))], fill=255)
        big.paste(Image.new("RGBA", big.size, skin + (255,)), (0, 0), Image.fromarray(np.minimum(np.array(m), np.array(cover))))
        dr.line([(k(x0 + (x1 - x0) * .04), k(cut - slant)), (k(x1 - (x1 - x0) * .04), k(cut + slant))], fill=ink, width=L)

    def brow(cx, y, half, tilt, arch=0.0):   # tilt > 0: inner end lower (angry); arch: upward bow
        dr.line([(k(cx - half), k(y - tilt)), (k(cx), k(y - arch)), (k(cx + half), k(y + tilt))], fill=ink, width=L, joint="curve")

    e = expression
    if e == "smug":
        lid(f["eyes"][0], .42); lid(f["eyes"][1], .42)
        brow(lc, by - eh * .02, bh, 0); brow(rc, by - eh * .1, bh, 0, eh * .06)
        dr.line([(k(mid - mw * .7), k(my + eh * .02)), (k(mid + mw * .3), k(my + eh * .03)), (k(mid + mw * .8), k(my - eh * .07))],
                fill=lip, width=L, joint="curve")
    elif e == "shocked":
        brow(lc, by - eh * .14, bh, -eh * .03, eh * .05); brow(rc, by - eh * .14, bh, eh * .03, eh * .05)
        ow, oh = mw * .7, eh * .45
        dr.ellipse([k(mid - ow / 2), k(my - oh * .35), k(mid + ow / 2), k(my + oh * .65)], fill=inside, outline=ink, width=L)
    elif e == "angry":
        lid(f["eyes"][0], .25, eh * .1); lid(f["eyes"][1], .25, -eh * .1)
        brow(lc, by + eh * .02, bh, -eh * .1); brow(rc, by + eh * .02, bh, eh * .1)
        dr.arc([k(mid - mw * .55), k(my), k(mid + mw * .55), k(my + eh * .35)], 200, 340, fill=lip, width=L)
    elif e == "deadpan":
        lid(f["eyes"][0], .45); lid(f["eyes"][1], .45)
        brow(lc, by, bh, 0); brow(rc, by, bh, 0)
        dr.line([(k(mid - mw * .5), k(my)), (k(mid + mw * .5), k(my))], fill=lip, width=L)
    elif e == "worried":
        brow(lc, by - eh * .04, bh, eh * .09); brow(rc, by - eh * .04, bh, -eh * .09)
        pts = [(mid - mw * .5 + i * mw / 5, my + (eh * .03 if i % 2 else -eh * .03)) for i in range(6)]
        dr.line([(k(x), k(y)) for x, y in pts], fill=lip, width=L, joint="curve")
    else:   # happy, laughing
        brow(lc, by - eh * .08, bh, 0, eh * .06); brow(rc, by - eh * .08, bh, 0, eh * .06)
        if e == "laughing":
            lid(f["eyes"][0], .35); lid(f["eyes"][1], .35)
        sw, sh = mw * (1.0 if e == "happy" else 1.1), eh * (.4 if e == "happy" else .5)
        dr.chord([k(mid - sw / 2), k(my - sh * .6), k(mid + sw / 2), k(my + sh)], 0, 180, fill=inside, outline=ink, width=L)
    # the new lines never leave the face: clipped to the face hull (plus half a line for the outline's edge)
    layer = np.array(big.resize((W, H), Image.LANCZOS))
    allowed = hull | brows_all
    for (x0, y0, x1, y1) in f["eyes"]:
        allowed[max(0, y0 - lw * 2): y1 + lw * 2, max(0, x0 - lw * 2): x1 + lw * 2] = True
    band = np.zeros_like(allowed)
    band[by0:by1, bx0:bx1] = skinlike[by0:by1, bx0:bx1] | brows_all[by0:by1, bx0:bx1]
    allowed |= band
    layer[..., 3] = np.where(_dilate(allowed, max(1, brow_w // 2)), layer[..., 3], 0)
    out = base.copy()
    out.alpha_composite(Image.fromarray(layer))
    return out


def make(neutral: Path, expressions: list[str], out_dir: Path) -> list[tuple[str, Path]]:
    img = Image.open(neutral).convert("RGBA")
    f = analyse(img)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for e in expressions:
        p = out_dir / f"{e}-face-from-neutral.png"
        render(img, e, f).save(p)
        made.append((e, p))
    return made
