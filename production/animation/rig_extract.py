"""Build a cut-out animation rig from one approved full-body pose (prototype, owner request 2026-11-17).

The approved image is only READ. Derived parts are written to the output folder:
  head-<name>.png   head (hair, face, ears) with the painted mouth removed (skin-filled), for drawn mouth shapes
  mouth-<name>.png  the original painted mouth (the character's resting mouth, shown when silent)
  torso.png         clothing and neck (arm lines below the shoulders removed)
  shoe-l.png / shoe-r.png
  rig.json          joints in source pixels: neck, shoulders, hips, knees, ankles, hands; line width; eyes; mouth box;
                    skin colour. Limbs are drawn by the animator as stick lines (the house style), so only their
                    joints are measured.

    python rig_extract.py <pose.png> <out_dir> [--head-only <name>]   (--head-only: an extra expression head)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


HANDS_ADVICE = "arms visible at the sides, hands not in pockets, no sleeves covering the hands"
FEET_ADVICE = "both legs and feet visible below the body, nothing (a long coat, a dress, a bag) covering them"
FACE_ADVICE = "a clear front-facing face with both eyes and the mouth visible, nothing covering them"


class RigError(ValueError):
    """A pose the rig cannot be built from, with what to change in the art (never a NaN or index error)."""

    def __init__(self, part: str, what: str, advice: str):
        self.part, self.what, self.advice = part, what, advice
        super().__init__(f"{what}; redraw the pose with {advice}")

    def as_dict(self) -> dict:
        return {"part": self.part, "message": str(self)}


def runs(row: np.ndarray) -> list[tuple[int, int]]:
    out, s = [], None
    for x, v in enumerate(row):
        if v and s is None:
            s = x
        elif not v and s is not None:
            out.append((s, x - 1)); s = None
    if s is not None:
        out.append((s, len(row) - 1))
    return out


def components(mask: np.ndarray) -> list[np.ndarray]:
    """4-connected components of a boolean mask -> list of (N,2) [y,x] arrays (small images only)."""
    seen = np.zeros_like(mask, bool)
    comps = []
    H, W = mask.shape
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, pts = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        comps.append(np.array(pts))
    return comps


NECK_RANGE = {"v1": (0.30, 0.50), "v2": (0.15, 0.45)}   # v2 heads are about 30% of the height: the neck sits higher


def find_neck(rgba: np.ndarray, style: str = "v1") -> dict:
    """Top of the figure and the neck (narrowest outline row in the style's neck range of the height)."""
    a = rgba[:, :, 3] > 128
    rows = np.nonzero(a.any(1))[0]
    top, bot = int(rows[0]), int(rows[-1])
    H = bot - top
    best = None
    lo, hi = NECK_RANGE[style]
    for y in range(top + int(lo * H), top + int(hi * H)):
        r = runs(a[y])
        w = sum(e - s + 1 for s, e in r)
        if r and (best is None or w < best[1]):
            best = (y, w, r)
    return {"top": top, "bottom": bot, "height": H, "neck": [(best[2][0][0] + best[2][-1][1]) / 2, best[0]]}


def measure_body(rgba: np.ndarray, style: str = "v1") -> dict:
    a = rgba[:, :, 3] > 128
    rows = np.nonzero(a.any(1))[0]
    top, bot = int(rows[0]), int(rows[-1])
    H = bot - top
    # neck: narrowest single-run row in the style's neck range (v1: 30-50% of the height)
    best = None
    lo, hi = NECK_RANGE[style]
    for y in range(top + int(lo * H), top + int(hi * H)):
        r = runs(a[y])
        w = sum(e - s + 1 for s, e in r)
        if r and (best is None or w < best[1]):
            best = (y, w, r)
    if best is None:
        raise RigError("body", "the neck could not be found", "the whole figure standing upright with the head on top")
    neck_y = best[0]
    neck_x = (best[2][0][0] + best[2][-1][1]) / 2
    # arms separate from the torso: first row below the neck with >= 3 runs (arm, torso, arm)
    split = next((y for y in range(neck_y + 10, bot) if len(runs(a[y])) >= 3), None)
    if split is None or split + 40 >= bot or len(runs(a[split + 4])) < 3 or len(runs(a[split + 40])) < 2:
        raise RigError("hands", "the arms and hands could not be found apart from the body", HANDS_ADVICE)
    r = runs(a[split + 4])
    arm_l, arm_r = r[0], r[-1]
    # line width: arm run width just below the split
    lw = int(np.median([e - s + 1 for s, e in (runs(a[split + 40])[0], runs(a[split + 40])[-1])]))
    # trace each arm line down to the hand blob (run wider than 2.2 line widths)
    inferred = []

    def trace(side):
        y, last, last_w = split + 4, None, 0
        while y < bot:
            rr = runs(a[y])
            if not rr:
                break
            run = rr[0] if side == "l" else rr[-1]
            cx = (run[0] + run[1]) / 2
            if last is not None and abs(cx - last[1]) > 1.5 * lw:
                # the outer line jumped to another part of the body: the arm ended here with no hand drawn (hidden in
                # a sleeve). Only a clean, free line end counts: a long arm (over 15% of the height) whose last row is
                # about one line wide. Anything else (an arm that merges into the body or a pocket) stays a clear error.
                if last[0] - split > 0.15 * H and last_w <= 1.6 * lw:
                    inferred.append(side)
                    return last, (last[1], float(last[0]))
                break
            if run[1] - run[0] + 1 > 2.2 * lw and y > split + 60:
                break
            last, last_w = (y, cx), run[1] - run[0] + 1
            y += 1
        # hand: the blob below; centroid of the outer run over the next rows while it stays wide
        ys, xs = [], []
        for yy in range(y, min(bot, y + 200)):
            rr = runs(a[yy])
            if not rr:
                break
            run = rr[0] if side == "l" else rr[-1]
            if run[1] - run[0] + 1 < 1.5 * lw and yy > y + 20:
                break
            for x in range(run[0], run[1] + 1):
                ys.append(yy); xs.append(x)
        if last is None or not xs or y >= bot:
            raise RigError("hands", f"the {'left' if side == 'l' else 'right'} hand could not be found", HANDS_ADVICE)
        return last, (float(np.mean(xs)), float(np.mean(ys)))
    (wl_y, wl_x), hand_l = trace("l")
    (wr_y, wr_x), hand_r = trace("r")
    shoulder_l = ((arm_l[0] + arm_l[1]) / 2, split - 6)
    shoulder_r = ((arm_r[0] + arm_r[1]) / 2, split - 6)
    # hips: first row (below the hands' top) where the middle structure is two narrow runs (the legs)
    hip_y, legs = None, None
    for y in range(int(min(hand_l[1], hand_r[1])) - 120, bot):
        rr = [x for x in runs(a[y]) if x[1] - x[0] + 1 < 2.0 * lw]
        mids = [x for x in rr if abs((x[0] + x[1]) / 2 - neck_x) < 0.25 * H]
        allr = runs(a[y])
        inner = [x for x in allr if abs((x[0] + x[1]) / 2 - neck_x) < 0.2 * H]
        if len(inner) == 2 and all(x[1] - x[0] + 1 < 2.0 * lw for x in inner):
            hip_y, legs = y, inner
            break
    if legs is None:
        raise RigError("feet", "the legs could not be found", FEET_ADVICE)
    leg_l_x, leg_r_x = (legs[0][0] + legs[0][1]) / 2, (legs[1][0] + legs[1][1]) / 2
    # ankles: first row below the hips where a leg run gets wide (the shoe)
    ankle_y = next((y for y in range(hip_y + 40, bot) if any(x[1] - x[0] + 1 > 2.5 * lw for x in runs(a[y]))), None)
    if ankle_y is None or len(runs(a[ankle_y - 3])) < 2:
        raise RigError("feet", "the feet could not be found", FEET_ADVICE)
    # leg x at the ankle row - 2 (legs can slant)
    rr = runs(a[ankle_y - 3])
    ank_l_x, ank_r_x = (rr[0][0] + rr[0][1]) / 2, (rr[-1][0] + rr[-1][1]) / 2
    return {"top": top, "bottom": bot, "height": H, "neck": [neck_x, neck_y], "arm_split_y": split, "line_width": lw,
            "shoulder_l": list(shoulder_l), "shoulder_r": list(shoulder_r), "hand_l": list(hand_l), "hand_r": list(hand_r),
            "hip_y": hip_y, "hip_l": [leg_l_x, hip_y], "hip_r": [leg_r_x, hip_y],
            "ankle_l": [ank_l_x, ankle_y], "ankle_r": [ank_r_x, ankle_y], **({"hands_inferred": inferred} if inferred else {})}


def eye_pair(cands: list, head_w: int) -> list:
    """The two eye whites: the PAIR of white shapes most alike in size and at the same height, each at most 40% of the
    head's width (white hair, a white hat or a glint is not an eye; Episode 14's Uncle Mortimer). Falls back to the
    two biggest when no pair qualifies."""
    def box(c):
        y0, x0 = c.min(0); y1, x1 = c.max(0)
        return {"c": c, "w": x1 - x0 + 1, "h": y1 - y0 + 1, "cy": (y0 + y1) / 2, "n": len(c)}
    bs = [box(c) for c in cands if len(c) > 30]
    ok = [b for b in bs if b["w"] <= 0.4 * head_w]
    best, score = None, None
    for i in range(len(ok)):
        for j in range(i + 1, len(ok)):
            a, b = ok[i], ok[j]
            ratio = max(a["n"], b["n"]) / max(1, min(a["n"], b["n"]))
            dy = abs(a["cy"] - b["cy"]) / max(a["h"], b["h"])
            if ratio <= 2.0 and dy <= 0.6:
                s = ratio + dy - 0.000001 * (a["n"] + b["n"])   # alike first, then the bigger pair
                if score is None or s < score:
                    best, score = [a["c"], b["c"]], s
    return best or [b["c"] for b in (ok if len(ok) >= 2 else bs)[:2]]


def face_features(rgba: np.ndarray, top: int, neck_y: int, neck_x: float) -> dict:
    """Eyes (the two biggest white discs) and the mouth (lowest non-skin mark under the eyes, near the centre line)."""
    head = rgba[top:neck_y]
    rgb = head[:, :, :3].astype(int)
    alpha = head[:, :, 3] > 128
    white = alpha & (rgb.min(2) > 225)
    comps = eye_pair(sorted(components(white), key=len, reverse=True)[:8], head.shape[1])
    eyes = []
    for c in sorted(comps, key=lambda c: c[:, 1].mean()):
        y0, x0 = c.min(0); y1, x1 = c.max(0)
        eyes.append({"cx": float((x0 + x1) / 2), "cy": float((y0 + y1) / 2 + top), "w": float(x1 - x0), "h": float(y1 - y0)})
    for e in eyes:
        x0, x1 = int(e["cx"] - e["w"] / 2), int(e["cx"] + e["w"] / 2)
        y0, y1 = int(e["cy"] - e["h"] / 2 - top), int(e["cy"] + e["h"] / 2 - top)
        dark = alpha[y0:y1, x0:x1] & (rgb[y0:y1, x0:x1].max(2) < 90)
        ys, xs = np.nonzero(dark)
        # the pupil: dark pixels away from the eye rim (the outline is also dark)
        keep = ((xs + x0 - e["cx"]) ** 2 / (e["w"] / 2) ** 2 + (ys + y0 + top - e["cy"]) ** 2 / (e["h"] / 2) ** 2) < 0.7
        xs, ys = xs[keep], ys[keep]
        e["pupil"] = {"cx": float(xs.mean() + x0), "cy": float(ys.mean() + y0 + top),
                      "r": float(max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 + 1)}
    eye_bottom = max(e["cy"] + e["h"] / 2 for e in eyes) - top
    eye_cx = (eyes[0]["cx"] + eyes[1]["cx"]) / 2
    eye_dx = eyes[1]["cx"] - eyes[0]["cx"]
    # skin: median colour of a band under the eyes, beside the nose
    sy0, sy1 = int(eye_bottom + 5), int(eye_bottom + 0.12 * (neck_y - top))
    band = [rgb[y, x] for y in range(sy0, sy1) for x in (int(eye_cx - 0.45 * eye_dx), int(eye_cx + 0.45 * eye_dx)) if alpha[y, x]]
    skin = np.median(np.array(band), 0)
    # mouth search box: under the eyes, central
    y0, y1 = int(eye_bottom + 0.06 * (neck_y - top)), int(neck_y - top - 0.04 * (neck_y - top))
    x0, x1 = int(eye_cx - 0.42 * eye_dx), int(eye_cx + 0.42 * eye_dx)
    dist = np.abs(rgb[y0:y1, x0:x1] - skin).sum(2)
    mark = (dist > 110) & alpha[y0:y1, x0:x1]
    comps = [c for c in components(mark) if len(c) > 60]
    # the mouth: the lowest sizeable mark whose width is at least 1.5x its height (the nose is rounder and higher);
    # tiny stubble dots were dropped above
    cand = []
    for c in comps:
        h = c[:, 0].max() - c[:, 0].min() + 1
        w = c[:, 1].max() - c[:, 1].min() + 1
        cx = c[:, 1].mean() + x0
        if w >= 1.5 * h and w > 0.12 * eye_dx and abs(cx - eye_cx) < 0.25 * eye_dx:
            cand.append((len(c), c, w, h))
    # the mouth is the biggest centred mark (a neck shadow or stubble is smaller; the nose is rounder)
    if not cand:
        # an open "O" mouth (surprise) is round: take the biggest centred mark of any shape
        for c in comps:
            h = c[:, 0].max() - c[:, 0].min() + 1
            w = c[:, 1].max() - c[:, 1].min() + 1
            if w > 0.1 * eye_dx and abs(c[:, 1].mean() + x0 - eye_cx) < 0.25 * eye_dx:
                cand.append((len(c), c, w, h))
    cand.sort(key=lambda t: t[0])
    _, c, w, h = cand[-1]
    my0, mx0 = c.min(0); my1, mx1 = c.max(0)
    mouth = {"x0": float(mx0 + x0), "x1": float(mx1 + x0), "y0": float(my0 + y0 + top), "y1": float(my1 + y0 + top)}
    mouth["cx"], mouth["cy"] = (mouth["x0"] + mouth["x1"]) / 2, (mouth["y0"] + mouth["y1"]) / 2
    mouth["w"], mouth["h"] = mouth["x1"] - mouth["x0"], mouth["y1"] - mouth["y0"]
    mouth["color"] = [int(v) for v in np.median(rgb[c[:, 0] + y0, c[:, 1] + x0], 0)]
    return {"eyes": eyes, "mouth": mouth, "skin": [int(v) for v in skin]}


def detect_style(rgba: np.ndarray) -> str:
    """v1 heads have white eye discs with a dark pupil inside; house style v2 heads (owner decision 2026-11-20) have solid
    black eyes and no whites at all. Looks at the top 45% of the figure only."""
    a = rgba[:, :, 3] > 128
    rows = np.nonzero(a.any(1))[0]
    top, bot = int(rows[0]), int(rows[-1])
    head = rgba[top: top + int(0.45 * (bot - top))]
    rgb = head[:, :, :3].astype(int)
    alpha = head[:, :, 3] > 128
    white = (alpha & (rgb.min(2) > 225))[::2, ::2]
    area = alpha.sum() / 4
    discs = []
    for c in components(white):
        if not (0.002 * area < len(c) < 0.25 * area):
            continue
        (y0, x0), (y1, x1) = c.min(0) * 2, c.max(0) * 2
        box = rgb[y0:y1 + 1, x0:x1 + 1]
        if box.size and 0.03 < (box.max(2) < 90).mean() < 0.6:   # a dark pupil inside the white disc
            discs.append((len(c), (y0 + y1) / 2, y1 - y0 + 1))
    # v1: a PAIR of eye whites, similar in size and at the same height (a white v2 head and torso are neither)
    for i in range(len(discs)):
        for j in range(i + 1, len(discs)):
            (n1, y1_, h1), (n2, y2_, h2) = discs[i], discs[j]
            if max(n1, n2) / min(n1, n2) < 1.6 and abs(y1_ - y2_) < 0.5 * max(h1, h2):
                return "v1"
    return "v2"


def _holes(mask: np.ndarray) -> list[np.ndarray]:
    """Components of ~mask that do not touch the border of the (cropped) mask: the shapes enclosed by it."""
    H, W = mask.shape
    out = []
    for c in components(~mask):
        if c[:, 0].min() == 0 or c[:, 1].min() == 0 or c[:, 0].max() == H - 1 or c[:, 1].max() == W - 1:
            continue
        out.append(c)
    return out


def face_features_v2(rgba: np.ndarray, top: int, neck_y: int, neck_x: float) -> dict:
    """House style v2 face: the head's fill (white or the character's skin tone) is the largest light region; the eyes are
    the two similar, roughly round or upright solid black shapes enclosed by it at about the same height; the mouth is
    the biggest enclosed mark below them (a thin line, an O or a D). Also measures the mouth's curve (positive: the
    middle is lower than the corners, a smile; negative: a frown) so spoken mouth shapes keep the expression."""
    head = rgba[top:neck_y]
    rgb = head[:, :, :3].astype(int)
    alpha = head[:, :, 3] > 128
    light = alpha & (rgb.max(2) > 110)
    small = components(light[::2, ::2])
    big = max(small, key=len)
    (y0, x0), (y1, x1) = big.min(0) * 2, big.max(0) * 2 + 1
    fill = np.zeros_like(light)
    fill[big[:, 0] * 2, big[:, 1] * 2] = True
    from PIL import ImageFilter as F
    fill = (np.array(Image.fromarray(fill.astype(np.uint8) * 255).filter(F.MaxFilter(3))) > 0) & light
    skin = np.median(rgb[fill], 0)
    crop = fill[y0:y1 + 1, x0:x1 + 1]
    feats = []
    for c in _holes(crop):
        cy, cx = c[:, 0].mean() + y0, c[:, 1].mean() + x0
        h = c[:, 0].max() - c[:, 0].min() + 1
        w = c[:, 1].max() - c[:, 1].min() + 1
        feats.append({"c": c, "cx": float(cx), "cy": float(cy), "w": float(w), "h": float(h), "n": len(c)})
    head_w = x1 - x0
    tiny = 0.0004 * fill.sum()
    cands = [f for f in feats if f["n"] > tiny and f["h"] >= 0.85 * f["w"] and f["cy"] < y0 + 0.75 * (y1 - y0)]
    best = None
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i], cands[j]
            if abs(a["cx"] - b["cx"]) < 0.15 * head_w:
                continue
            score = abs(a["cy"] - b["cy"]) / max(a["h"], b["h"]) + abs(a["n"] - b["n"]) / max(a["n"], b["n"])
            if best is None or score < best[0]:
                best = (score, a, b)
    if best is None:
        raise ValueError("v2 face: could not find two solid black eyes")
    eyes = []
    for f in sorted(best[1:], key=lambda f: f["cx"]):
        r = max(f["w"], f["h"]) / 2
        eyes.append({"cx": f["cx"], "cy": f["cy"] + top, "w": f["w"], "h": f["h"], "pupil": {"cx": f["cx"], "cy": f["cy"] + top, "r": float(r)}})
    eye_cx = (eyes[0]["cx"] + eyes[1]["cx"]) / 2
    eye_dx = eyes[1]["cx"] - eyes[0]["cx"]
    eye_bottom = max(e["cy"] + e["h"] / 2 for e in eyes) - top
    under = [f for f in feats if f is not best[1] and f is not best[2] and f["cy"] - f["h"] / 2 > eye_bottom
             and abs(f["cx"] - eye_cx) < 0.45 * eye_dx and f["n"] > tiny]
    if under:
        mf = max(under, key=lambda f: f["n"])
        c = mf["c"]
        mx0, mx1 = c[:, 1].min() + x0, c[:, 1].max() + x0
        my0, my1 = c[:, 0].min() + y0, c[:, 0].max() + y0
        w = mx1 - mx0 + 1
        side = c[c[:, 1] + x0 < mx0 + 0.2 * w]
        side2 = c[c[:, 1] + x0 > mx1 - 0.2 * w]
        mid = c[np.abs(c[:, 1] + x0 - (mx0 + mx1) / 2) < 0.1 * w]
        curve = 0.0
        if len(side) and len(side2) and len(mid) and (my1 - my0 + 1) < 0.5 * w:   # only a line-like mouth has a curve
            curve = float(np.clip((mid[:, 0].mean() - (side[:, 0].mean() + side2[:, 0].mean()) / 2) / w, -0.3, 0.3))
        color = [int(v) for v in np.median(rgb[c[:, 0] + y0, c[:, 1] + x0], 0)]
    else:   # no visible mouth: a short line's place under the eyes
        mx0, mx1 = eye_cx - 0.25 * eye_dx, eye_cx + 0.25 * eye_dx
        my0 = my1 = eye_bottom + 0.45 * (neck_y - top - eye_bottom)
        curve, color = 0.0, [18, 18, 18]
    mouth = {"x0": float(mx0), "x1": float(mx1), "y0": float(my0 + top), "y1": float(my1 + top)}
    mouth["cx"], mouth["cy"] = (mouth["x0"] + mouth["x1"]) / 2, (mouth["y0"] + mouth["y1"]) / 2
    mouth["w"], mouth["h"] = mouth["x1"] - mouth["x0"], mouth["y1"] - mouth["y0"]
    mouth["color"], mouth["curve"] = color, round(curve, 3)
    return {"eyes": eyes, "mouth": mouth, "skin": [int(v) for v in skin], "style": "v2"}


def features(rgba: np.ndarray, top: int, neck_y: int, neck_x: float, style: str) -> dict:
    return face_features_v2(rgba, top, neck_y, neck_x) if style == "v2" else face_features(rgba, top, neck_y, neck_x)


def chin_row(rgba: np.ndarray, top: int, neck_y: int, face: dict) -> int:
    """Bottom of the face's skin region (the chin). A turtleneck or collar can hide the neck, so the narrowest row
    of the outline is not always under the chin."""
    rgb = rgba[:, :, :3].astype(int)
    alpha = rgba[:, :, 3] > 128
    skin = np.array(face["skin"])
    lim = min(rgba.shape[0], neck_y + int(0.15 * (neck_y - top)))
    mask = alpha[top:lim] & (np.abs(rgb[top:lim] - skin).sum(2) < 60)
    e0, e1 = face["eyes"]
    seed = (int(max(e0["cy"] + e0["h"] / 2, e1["cy"] + e1["h"] / 2) + 6 - top), int((e0["cx"] + e1["cx"]) / 2))
    comp = next((c for c in components(mask) if any((c[:, 0] == seed[0]) & (np.abs(c[:, 1] - seed[1]) < 4))), None)
    if comp is None:
        return neck_y
    # the face's bottom edge along the centre line (ignores neck skin that is narrower than the face)
    cx = seed[1]
    col = comp[np.abs(comp[:, 1] - cx) < 6]
    return int(col[:, 0].max() + top)


def isolate_head(arr: np.ndarray, face: dict) -> np.ndarray:
    """Keep only the head blob (the connected shape containing the eyes): raised fists, motion lines and props that
    reach into the head's rows in an expression pose are dropped."""
    a = arr[:, :, 3] > 40
    e0 = face["eyes"][0]
    seed = (int(e0["cy"]), int(e0["cx"] - e0["w"] / 2 - 2))   # the eye outline belongs to the head
    small = a[::2, ::2]
    comp = next((c for c in components(small) if np.any((np.abs(c[:, 0] * 2 - seed[0]) < 6) & (np.abs(c[:, 1] * 2 - seed[1]) < 6))), None)
    if comp is None:
        return arr
    keep = np.zeros_like(small)
    keep[comp[:, 0], comp[:, 1]] = True
    keep = np.repeat(np.repeat(keep, 2, 0), 2, 1)[: a.shape[0], : a.shape[1]]
    # grow by a few pixels so anti-aliased edges survive the half-resolution mask
    from PIL import ImageFilter as F
    keep = np.array(Image.fromarray(keep.astype(np.uint8) * 255).filter(F.MaxFilter(5))) > 0
    out = arr.copy()
    out[~keep] = 0
    return out


def cut_head(rgba: np.ndarray, body: dict, face: dict, out: Path, name: str, expression: bool = False) -> dict:
    top, neck_y = body["top"], body["neck"][1]
    pad = 4
    head = Image.fromarray(isolate_head(rgba[: neck_y + pad].copy(), face) if expression else rgba[: neck_y + pad].copy())
    m = face["mouth"]
    if expression:
        # an expression's mouth can be a big open shape (several colours): erase the whole mouth zone, from just
        # above the detected mouth to the chin, across its width
        m = {**m, "x0": m["x0"] - 0.15 * m["w"], "x1": m["x1"] + 0.15 * m["w"], "y0": m["y0"] - 0.25 * m["h"], "y1": m["y1"] + 0.3 * m["h"]}
    mouth_crop = head.crop((int(m["x0"]) - 6, int(m["y0"]) - 6, int(m["x1"]) + 7, int(m["y1"]) + 7))
    mouth_crop.save(out / f"mouth-{name}.png")
    # erase the painted mouth with skin colour (soft-edged ellipse, slightly larger than the mark)
    erase = Image.new("L", head.size, 0)
    ImageDraw.Draw(erase).ellipse((m["x0"] - 14, m["y0"] - 10, m["x1"] + 14, m["y1"] + 10), fill=255)
    erase = erase.filter(ImageFilter.GaussianBlur(2))
    skin = Image.new("RGBA", head.size, tuple(face["skin"]) + (255,))
    head = Image.composite(skin, head, erase)
    d = ImageDraw.Draw(head)
    arr = np.array(head)
    for e in ([] if expression or face.get("style") == "v2" else face["eyes"]):
        p = e["pupil"]
        # the eye's own white (slightly warm in the art), sampled around the pupil
        ring = arr[int(p["cy"] - 2.2 * p["r"]):int(p["cy"] + 2.2 * p["r"]), int(p["cx"] - 2.2 * p["r"]):int(p["cx"] + 2.2 * p["r"])].reshape(-1, 4)
        ring = ring[(ring[:, 3] > 200) & (ring[:, :3].min(1) > 215)]
        white = tuple(int(v) for v in np.median(ring[:, :3], 0)) + (255,)
        e["white"] = list(white[:3])
        d.ellipse((p["cx"] - p["r"] - 3, p["cy"] - p["r"] - 3, p["cx"] + p["r"] + 3, p["cy"] + p["r"] + 3), fill=white)
    bbox = head.getbbox()
    head = head.crop(bbox)
    head.save(out / f"head-{name}.png")
    return {"file": f"head-{name}.png", "origin": [bbox[0], bbox[1]], "size": list(head.size),
            "mouth_file": f"mouth-{name}.png", "mouth_origin": [int(m["x0"]) - 6, int(m["y0"]) - 6]}


def cut_body(rgba: np.ndarray, body: dict, out: Path) -> dict:
    a = rgba[:, :, 3] > 128
    neck_y, split, hip_y = body["neck"][1], body["arm_split_y"], body["hip_y"]
    keep = np.zeros_like(a)
    # torso: rows neck..split full (shoulders), split..hip only the middle run (arm lines removed)
    cx = body["neck"][0]
    for y in range(neck_y - 2, hip_y + 6):
        rr = runs(a[y])
        if y < split:
            for s, e in rr:
                keep[y, s:e + 1] = True
        else:
            mid = [r for r in rr if r[0] <= cx <= r[1]] or sorted(rr, key=lambda r: abs((r[0] + r[1]) / 2 - cx))[:1]
            for s, e in mid:
                keep[y, s:e + 1] = True
    torso = rgba.copy()
    torso[~keep] = 0
    im = Image.fromarray(torso)
    bbox = im.getbbox()
    im.crop(bbox).save(out / "torso.png")
    parts = {"torso": {"file": "torso.png", "origin": [bbox[0], bbox[1]], "size": [bbox[2] - bbox[0], bbox[3] - bbox[1]]}}
    # shoes: below the ankle row, split between the legs
    ank = body["ankle_l"][1] - 2
    mid_x = int((body["ankle_l"][0] + body["ankle_r"][0]) / 2)
    for side, (x0, x1) in (("l", (0, mid_x)), ("r", (mid_x, rgba.shape[1]))):
        s = rgba[ank:body["bottom"] + 2, x0:x1]
        im = Image.fromarray(s.copy())
        bb = im.getbbox()
        im.crop(bb).save(out / f"shoe-{side}.png")
        parts[f"shoe_{side}"] = {"file": f"shoe-{side}.png", "origin": [x0 + bb[0], ank + bb[1]], "size": [bb[2] - bb[0], bb[3] - bb[1]]}
    return parts


def debug_image(rgba: np.ndarray, rig: dict, out: Path) -> None:
    im = Image.fromarray(rgba).convert("RGBA")
    bg = Image.new("RGBA", im.size, (235, 235, 235, 255)); bg.alpha_composite(im)
    d = ImageDraw.Draw(bg)
    b = rig["body"]
    for k in ("neck", "shoulder_l", "shoulder_r", "hand_l", "hand_r", "hip_l", "hip_r", "ankle_l", "ankle_r"):
        x, y = b[k]
        d.ellipse((x - 12, y - 12, x + 12, y + 12), outline=(255, 0, 0), width=4)
    f = rig["faces"]["neutral"]
    m = f["mouth"]; d.rectangle((m["x0"], m["y0"], m["x1"], m["y1"]), outline=(0, 180, 0), width=3)
    for e in f["eyes"]:
        d.ellipse((e["cx"] - e["w"] / 2, e["cy"] - e["h"] / 2, e["cx"] + e["w"] / 2, e["cy"] + e["h"] / 2), outline=(0, 0, 255), width=3)
    bg.save(out / "rig-debug.png")


def checked_body(rgba: np.ndarray, style: str) -> dict:
    """measure_body, but any failure is a RigError saying what to change, and no joint may be NaN."""
    try:
        body = measure_body(rgba, style)
    except RigError:
        raise
    except Exception as e:   # an unusual figure: still a clear message, never a raw NaN/index error
        raise RigError("body", f"the body could not be measured ({type(e).__name__})", f"{HANDS_ADVICE}, and {FEET_ADVICE}") from e
    for k in ("hand_l", "hand_r"):
        if not all(np.isfinite(body[k])):
            raise RigError("hands", "the hands could not be found", HANDS_ADVICE)
    for k in ("ankle_l", "ankle_r", "hip_l", "hip_r"):
        if not all(np.isfinite(body[k])):
            raise RigError("feet", "the feet could not be found", FEET_ADVICE)
    return body


def checked_features(rgba, top, neck_y, neck_x, style) -> dict:
    try:
        return features(rgba, top, neck_y, neck_x, style)
    except Exception as e:
        raise RigError("face", f"the face could not be found ({e})" if isinstance(e, ValueError) and str(e) else
                       "the face could not be found", FACE_ADVICE) from e


def main():
    try:
        _main()
    except RigError as e:
        # one line the studio reads (acting.rig_error): no traceback
        print("RIG-ERROR " + json.dumps(e.as_dict()), file=sys.stderr)
        sys.exit(2)


def _main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rgba = np.array(Image.open(src).convert("RGBA"))
    head_only = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--head-only" else None
    if head_only:
        rig = json.loads((out / "rig.json").read_text())
        style = rig.get("style", "v1")
        b = find_neck(rgba, style)   # expression poses can raise arms: only the head is needed
        face = checked_features(rgba, b["top"], b["neck"][1], b["neck"][0], style)
        chin = chin_row(rgba, b["top"], b["neck"][1], face)
        if chin + 4 < b["neck"][1]:
            b["neck"][1] = chin + 4
            face = checked_features(rgba, b["top"], b["neck"][1], b["neck"][0], style)
        head = cut_head(rgba, b, face, out, head_only, expression=True)
        # express the extra head relative to its own neck so it can be swapped onto the rig's neck; its eyes are kept
        # as drawn (the expression lives in them), only the mouth is live
        rig["faces"][head_only] = {**face, **head, "neck": b["neck"], "static_eyes": True}
        (out / "rig.json").write_text(json.dumps(rig, indent=1))
        print("added head", head_only, "mouth", face["mouth"]["w"], "x", face["mouth"]["h"])
        return
    style = detect_style(rgba)
    body = checked_body(rgba, style)
    face = checked_features(rgba, body["top"], body["neck"][1], body["neck"][0], style)
    chin = chin_row(rgba, body["top"], body["neck"][1], face)
    if chin + 4 < body["neck"][1]:
        # a collar hides the neck: cut the head at the chin and look for the mouth above it
        body["neck"][1] = chin + 4
        face = checked_features(rgba, body["top"], body["neck"][1], body["neck"][0], style)
    head = cut_head(rgba, body, face, out, "neutral")
    parts = cut_body(rgba, body, out)
    rig = {"source": src.name, "image_size": [rgba.shape[1], rgba.shape[0]], "body": body, "parts": parts,
           "faces": {"neutral": {**face, **head, "neck": body["neck"], **({"static_eyes": True} if style == "v2" else {})}}}
    if style == "v2":
        rig["style"] = "v2"   # v1 rig.json stays exactly as before (no key)
    (out / "rig.json").write_text(json.dumps(rig, indent=1))
    debug_image(rgba, rig, out)
    print(json.dumps({k: body[k] for k in ("neck", "shoulder_l", "hand_l", "hip_l", "ankle_l", "line_width")}),
          "mouth", round(face["mouth"]["w"]), "x", round(face["mouth"]["h"]), "skin", face["skin"])


if __name__ == "__main__":
    main()
