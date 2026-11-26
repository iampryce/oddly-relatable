"""Reactions and close-ups (guided flow, steps 6-8): the owner-tested method of 2026-11-26, run from the dashboard.

Which shots: every storyboard shot (shot_frames.py) that is NOT a talking shot (talking_s2v.talking_rows) and shows at
least one character. One character on a close or medium shot is a CLOSE-UP; anything else is a GROUP reaction.

The method (ported from the owner's scripts gpu_acting.py / compose_acting.py; do not change without the owner):
  1. Base picture = an exact ZOOM CROP of the approved seating master of the shot's side of the room (the owner picks
     one approved still per side; no new background is ever drawn). The crop box is suggested from the character's
     head in the master and the owner can move and resize it. The crop is upscaled to 1280x720 with Lanczos.
  2. Poses: from the acting analysis' beats for that shot (owner-editable): pose 0 is the crop as it is; every beat
     gives a pose; a big snappy move adds an overshoot pose first (S1 -> S2b -> S2). Each changed face is a MASKED
     Qwen-Image-Edit-2511 edit (SetLatentNoiseMask on an oval over the face interior: brows, eyes, moustache, mouth)
     and the result is pasted back onto the ORIGINAL pixels through the same oval, so nothing outside the face can
     change (unmasked edits added glasses, hair, hands and noses: ep15-ISSUES #21). Group shots: one masked edit per
     visible character, one at a time, each pasted through its own oval. Prompts are written by GPT (prompt_writer)
     or the built-in template (labelled), and always carry the EYELINE: listeners look slightly screen-left toward
     the speaker, the speaker slightly screen-right; straight at the camera only when the beat says so (#22).
     Every pose waits for the owner's Approve.
  3. Moves between consecutive poses: Wan 2.2 i2v 14B first+last frame (WanFirstLastFrameToVideo), 33 frames at
     16 fps, 4 steps (2 high-noise + 2 low-noise with the lightx2v 4-step LoRAs), CFG 1, shift 5, 1280x720. A hold
     longer than 0.4 s is a LIVING HOLD: first and last frame are the same pose, with a tremble/blink prompt.
  4. Assembly on the studio server (FFmpeg + Pillow): the timeline from the poses (times relative to the shot),
     moves eased out (fast start, settle), living holds at natural speed, the background LOCKED to the base pixels
     outside a feathered box around the character(s), 25 fps, one MP4 per shot; a review copy with the episode's
     original audio.

Cost: GPU price per hour x measured times (Qwen masked edit 60-90 s, FLF clip about 2.5 min, about 10 min to start a
session and download the models). "About" uses the first GPU type and the typical times, "at most" the most expensive
allowed type, the slow times and 25% margin. The request must carry "at most" (confirm_usd, 409 otherwise); a run
that would pass the monthly GPU cap is refused (409); the session itself is cap-checked by gpu.py and the job stops
before a step that would pass the confirmed amount. The session is the shared ComfyUI session kind (comfy_session.py).

Nothing is approved by itself: crops, poses and shots each wait for the owner's click. The private reference video's
pictures are never used here: only its acting notes (text).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import random
import re
import secrets as pysecrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Character, Episode, Event, Job, Setting
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import sha256_file, storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

JOB_POSES, JOB_ANIMATE = "reaction_poses", "reaction_animate"
W, H = 1280, 720
FPS = 25                                   # the assembled shot
FLF_FPS, FLF_FRAMES = 16, 33               # one Wan clip: 33 frames at 16 fps (2.06 s)
FLF_STEPS, FLF_SPLIT, FLF_CFG, FLF_SHIFT = 4, 2, 1.0, 5.0
LIVE_MIN_S = 0.4                           # holds longer than this are living holds
EASE_POWER = 2.2
LOCK_FEATHER = 25
# measured 2026-11-26 (L40S / RTX 6000 Ada): Qwen masked edit 60-90 s, FLF clip about 2.5 min, start-up + downloads
EDIT_MIN, EDIT_MIN_MAX, FLF_MIN, SETUP_MIN, MAX_MARGIN = 1.0, 1.5, 2.5, 10.0, 1.25
MOVE_S = {"big": 0.25, "clear": 0.35, "subtle": 0.5}
POLL_S = 5.0
MAX_POSES = 12

HF = "https://huggingface.co/Comfy-Org"
QWEN_MODELS = [
    {"folder": "diffusion_models", "filename": "qwen_image_edit_2511_fp8mixed.safetensors", "type": "diffusion_model", "base": "Qwen-Image",
     "url": f"{HF}/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors"},
    {"folder": "text_encoders", "filename": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "text_encoder", "base": "Qwen-Image",
     "url": f"{HF}/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"},
    {"folder": "vae", "filename": "qwen_image_vae.safetensors", "type": "vae", "base": "Qwen-Image",
     "url": f"{HF}/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"},
]
WAN_MODELS = [
    {"folder": "diffusion_models", "filename": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "type": "diffusion_model", "base": "Wan 2.2",
     "url": f"{HF}/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"},
    {"folder": "diffusion_models", "filename": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "type": "diffusion_model", "base": "Wan 2.2",
     "url": f"{HF}/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"},
    {"folder": "loras", "filename": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "type": "lora", "base": "Wan 2.2",
     "url": f"{HF}/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"},
    {"folder": "loras", "filename": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "type": "lora", "base": "Wan 2.2",
     "url": f"{HF}/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"},
    {"folder": "text_encoders", "filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "text_encoder", "base": "Wan 2.1",
     "url": f"{HF}/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"},
    {"folder": "vae", "filename": "wan_2.1_vae.safetensors", "type": "vae", "base": "Wan 2.1",
     "url": f"{HF}/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"},
]

TEMPLATE_LABEL = "template prompt (GPT unavailable)"
# what a masked face edit may and may not do (gpu_acting.py "NOADD" + the smudged-mouth lesson, ep15 round 3)
KEEP = (" Only the eyes, eyebrows, mouth and any moustache change. Do not add glasses, hair, a nose, objects or hands. "
        "Same simple stick-figure face style, thick black lines.")
MOUTH = (" If the mouth opens, draw a clear, fully drawn dark mouth of medium size with a thick black outline, never a "
         "huge wide-open mouth.")
FLF_SUFFIX = " Static locked-off camera, no zoom. Flat 2D cartoon, same drawing."
FLF_NEG = "3D, realistic, camera movement, zoom, pan, morphing, extra characters, changing faces, extra limbs, blurry, text"
CAMERA_WORDS = re.compile(r"\b(camera|viewer|lens|straight at us|at the audience|into the camera)\b", re.I)


def key(eid: int) -> str:
    return f"reactions:{eid}"


def _slug(k: str) -> str:
    """A character key as it may appear in a file or storage name."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(k))[:40] or "x"


# ================================================================== pure parts: crop, masks, paste-back, lock
def fit_169(x: float, y: float, w: float, h: float, mw: int, mh: int, min_w: float = 64.0) -> dict:
    """A 16:9 box in master pixels: the given box's centre and width (height follows), at least min_w wide, at most the
    whole master, moved (not shrunk) to lie inside the master."""
    cx, cy = float(x) + float(w) / 2, float(y) + float(h) / 2
    w = max(min_w, min(float(w), float(mw), mh * 16 / 9))
    h = w * 9 / 16
    x0 = min(max(0.0, cx - w / 2), mw - w)
    y0 = min(max(0.0, cy - h / 2), mh - h)
    return {"x": round(x0, 2), "y": round(y0, 2), "w": round(w, 2), "h": round(h, 2)}


def box_from_owner(cx: float, cy: float, w: float, mw: int, mh: int) -> dict:
    """The owner's box (centre + width, master pixels) as a valid 16:9 box inside the master."""
    w = max(64.0, min(float(w), float(mw), mh * 16 / 9))
    return fit_169(cx - w / 2, cy - w * 9 / 32, w, w * 9 / 16, mw, mh)


def suggest_crop(heads: list[dict], mw: int, mh: int, close: bool) -> dict:
    """The crop a shot starts with. Close-up: the head about 30% of the crop's height, its centre at 38% from the top.
    Group: every head in, with 3 head radii on each side. No head known: the whole master (16:9 centre)."""
    if not heads:
        w = min(float(mw), mh * 16 / 9)
        return {**fit_169((mw - w) / 2, (mh - w * 9 / 16) / 2, w, w * 9 / 16, mw, mh), "source": "auto"}
    r = max(h["r"] for h in heads)
    if close:
        hgt = 2 * r / 0.30
        w = hgt * 16 / 9
        cx, cy = heads[0]["x"], heads[0]["y"]
    else:
        x0, x1 = min(h["x"] for h in heads) - 3 * r, max(h["x"] for h in heads) + 3 * r
        w = max(x1 - x0, (2 * r / 0.18) * 16 / 9)
        hgt = w * 9 / 16
        cx, cy = (x0 + x1) / 2, sum(h["y"] for h in heads) / len(heads)
    w = min(w, float(mw), mh * 16 / 9)
    hgt = w * 9 / 16
    return {**fit_169(cx - w / 2, cy - 0.38 * hgt, w, hgt, mw, mh), "source": "auto"}


def head_in_crop(head: dict, box: dict) -> dict:
    """A head in master pixels -> the same head in the 1280x720 base."""
    s = W / box["w"]
    return {"x": (head["x"] - box["x"]) * s, "y": (head["y"] - box["y"]) * s, "r": head["r"] * s}


def default_oval(head: dict | None, slot: int = 0, n: int = 1) -> dict:
    """The face-interior oval (base pixels): a little inside the round head so the head's outline is never redrawn.
    Without a head: evenly spread across the picture, a little above the middle (the owner moves it)."""
    if head:
        return {"cx": round(head["x"], 1), "cy": round(head["y"], 1), "rx": round(head["r"] * 0.78, 1),
                "ry": round(head["r"] * 0.8, 1), "source": "auto"}
    return {"cx": round(W * (slot + 1) / (n + 1), 1), "cy": 300.0, "rx": 90.0, "ry": 95.0, "source": "auto"}


def clamp_oval(o: dict) -> dict:
    rx = min(max(float(o["rx"]), 8.0), W / 2)
    ry = min(max(float(o["ry"]), 8.0), H / 2)
    return {"cx": round(min(max(float(o["cx"]), 0.0), W), 1), "cy": round(min(max(float(o["cy"]), 0.0), H), 1),
            "rx": round(rx, 1), "ry": round(ry, 1), "source": o.get("source", "owner")}


def crop_image(master, box: dict):
    """The exact zoom crop of the master, upscaled to 1280x720 with Lanczos (PIL image)."""
    from PIL import Image
    b = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
    return master.convert("RGB").resize((W, H), Image.LANCZOS, box=b)


def oval_mask(o: dict, size: tuple[int, int] = (W, H)):
    """The mask sent to the edit model: white inside the oval, black outside (L)."""
    from PIL import Image, ImageDraw
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse((o["cx"] - o["rx"], o["cy"] - o["ry"], o["cx"] + o["rx"], o["cy"] + o["ry"]), fill=255)
    return m


def paste_mask(o: dict, feather: float = 4.0):
    """The paste-back mask: the oval, softened INWARD only (a blurred copy multiplied by the hard oval), so every pixel
    outside the oval keeps the original exactly."""
    from PIL import ImageChops, ImageFilter
    hard = oval_mask(o)
    soft = hard.filter(ImageFilter.GaussianBlur(feather)) if feather > 0 else hard
    return ImageChops.multiply(hard, soft)


def paste_back(base, edited, o: dict):
    """The edit model's picture (any size) pasted onto the base through the oval: outside the oval, the base's pixels."""
    from PIL import Image
    ed = edited.convert("RGB")
    if ed.size != base.size:
        ed = ed.resize(base.size, Image.LANCZOS)
    return Image.composite(ed, base.convert("RGB"), paste_mask(o))


def lock_box(ovals: list[dict]) -> tuple[int, int, int, int]:
    """The box around the character(s) where the animation may show: about 3 face widths across each face, from just
    above the head to the bottom of the picture (the body sits below the face)."""
    x0 = min(o["cx"] - 3.2 * o["rx"] for o in ovals)
    x1 = max(o["cx"] + 3.2 * o["rx"] for o in ovals)
    y0 = min(o["cy"] - 2.6 * o["ry"] for o in ovals)
    return (int(max(0, x0)), int(max(0, y0)), int(min(W, x1)), H)


def lock_mask(ovals: list[dict], feather: int = LOCK_FEATHER):
    """White inside the character box (feathered): during moves and living holds the clip shows only there; outside,
    the base picture's own pixels (the room never wobbles)."""
    from PIL import Image, ImageFilter
    m = Image.new("L", (W, H), 0)
    m.paste(255, lock_box(ovals))
    return m.filter(ImageFilter.GaussianBlur(feather)) if feather else m


# ================================================================== pure parts: heads in the master
def find_heads(img) -> list[dict]:
    """Head-like regions of a seating master (stick heads are plain white circles): [{x, y, r, score}] in master
    pixels, best first. The owner moves the crop when the guess is wrong."""
    import numpy as np
    from PIL import Image
    mw, mh = img.size
    s = max(1.0, mw / 320.0)
    sw, sh = max(1, int(mw / s)), max(1, int(mh / s))
    a = np.asarray(img.convert("RGB").resize((sw, sh), Image.BILINEAR), dtype=np.int16)
    white = (a.min(axis=2) > 200) & (a.max(axis=2) - a.min(axis=2) < 30)
    h, w = white.shape
    grown = white.copy()            # bridge the face's thin dark lines (eyes, brows, mouth) so a head is one region
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            grown[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] |= white[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)]
    seen = np.zeros_like(grown, dtype=bool)
    out = []
    for y0 in range(h):
        for x0 in range(w):
            if not grown[y0, x0] or seen[y0, x0]:
                continue
            stack, pix = [(y0, x0)], []
            seen[y0, x0] = True
            while stack:
                y, x = stack.pop()
                if white[y, x]:
                    pix.append((y, x))
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < h and 0 <= xx < w and grown[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            if len(pix) < 20:
                continue
            ys, xs = np.array([p[0] for p in pix]), np.array([p[1] for p in pix])
            bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
            aspect = min(bw, bh) / max(bw, bh)
            fill = len(pix) / float(bw * bh)
            if aspect < 0.75 or not 0.4 < fill < 0.9 or bw > w * 0.4:
                continue
            score = len(pix) * aspect * (1 - abs(fill - 0.785))
            out.append({"x": round(float((xs.min() + xs.max()) / 2 * s + s / 2), 1),
                        "y": round(float((ys.min() + ys.max()) / 2 * s + s / 2), 1),
                        "r": round(float(bh) / 2 * s, 1), "score": round(float(score), 1)})
    out.sort(key=lambda d: -d["score"])
    return out


def heads_for_people(heads: list[dict], members: list[str]) -> dict[str, dict]:
    """The side's characters (in seat order, left to right) matched to the best head-like regions, sorted by x. Only
    when there are at least as many heads as people; otherwise nobody is matched (the owner sets the crop)."""
    if not members or len(heads) < len(members):
        return {}
    best = sorted(heads[:len(members)], key=lambda d: d["x"])
    return dict(zip(members, best))


# ================================================================== pure parts: poses, timeline, assembly
def beat_want(b: dict) -> str:
    """What the face should show for one acting beat (face fields only; the body is not redrawn)."""
    bits = [str(b.get(k) or "").strip().rstrip(".") for k in ("expression", "eyes_and_gaze") if b.get(k)]
    return "; ".join(x for x in bits if x) or "neutral"


def _pose(label: str, t: float, faces: dict, move_s: float, beat: int | None = None) -> dict:
    return {"id": pysecrets.token_hex(4), "label": label[:120], "t": round(t, 2), "move_s": round(move_s, 2),
            "faces": json.loads(json.dumps(faces)), "beat": beat, "takes": [], "approved": None}


def poses_from_beats(beats: list[dict], t0: float, dur: float, people: dict[str, str]) -> list[dict]:
    """Poses from the acting beats of one shot (times absolute, as the analysis gives them). people: {name (lower):
    character key}. Pose 0 is the crop as it is (a "hold" beat right at the start becomes pose 0's face). A big move
    adds an overshoot pose (a bigger version) before it settles, as in the owner's test (S1 -> S2b -> S2)."""
    poses = [_pose("as it is", 0.0, {}, 0.0)]
    faces: dict[str, dict] = {}
    for bi, b in sorted(enumerate(beats), key=lambda x: float(x[1].get("t_start") or 0)):
        k = people.get(str(b.get("character") or "").strip().lower())
        if not k:
            continue
        t = min(max(float(b.get("t_start") or t0) - t0, 0.0), max(0.0, dur - 0.1))
        want = beat_want(b)
        faces = {**faces, k: {"want": want}}
        label = (b.get("expression") or want)[:60]
        if t <= 0.15 and (b.get("hold_or_move") or "hold") == "hold" and len(poses) == 1:
            poses[0].update(label=label, faces=json.loads(json.dumps(faces)), beat=bi)
            continue
        if len(poses) >= MAX_POSES:
            break
        intensity = b.get("intensity") if b.get("intensity") in MOVE_S else "clear"
        t = max(t, poses[-1]["t"] + 0.1)
        if intensity == "big" and (b.get("hold_or_move") or "move") == "move" and len(poses) + 2 <= MAX_POSES:
            over = {**faces, k: {"want": f"an EXTREME, bigger version of: {want}"}}
            poses.append(_pose(f"{label} (overshoot)", t, over, MOVE_S["big"], bi))
            poses.append(_pose(label, t + MOVE_S["big"] + 0.02, faces, 0.2, bi))
        else:
            poses.append(_pose(label, t, faces, MOVE_S[intensity], bi))
    return [p for p in poses if p["t"] < dur or p is poses[0]]


def same_faces(a: dict, b: dict) -> bool:
    return {k: v.get("want") for k, v in (a.get("faces") or {}).items()} == {k: v.get("want") for k, v in (b.get("faces") or {}).items()}


def timeline(poses: list[dict], dur: float) -> list[dict]:
    """The shot as segments (seconds from the shot start): hold (the pose's still), move (pose a -> pose b, eased),
    live (a living hold, 0.4 s or longer, as in the owner's shot 13). A move takes the pose's move_s (at least 2
    frames), never past the next pose; a hold that would be shorter than 2 frames is given to the move instead. A pose
    with the same faces as the one before is a continuation, not a move."""
    ps = sorted(enumerate(poses), key=lambda x: (x[1]["t"], x[0]))
    keep: list[tuple[int, dict]] = []
    for i, p in ps:
        if keep and same_faces(keep[-1][1], p):
            continue
        keep.append((i, p))
    seg: list[dict] = []
    for n, (i, p) in enumerate(keep):
        start = 0.0 if n == 0 else min(max(p["t"], 0.0), dur)
        nxt = keep[n + 1][1]["t"] if n + 1 < len(keep) else dur
        nxt = min(max(nxt, start), dur)
        hold_from = start
        if n > 0:
            gap = nxt - start
            m = min(max(float(p.get("move_s") or 0.3), 2 / FPS), gap)
            if gap - m < 2 / FPS:
                m = gap
            if m > 0:
                seg.append({"kind": "move", "a": keep[n - 1][0], "b": i, "t0": round(start, 3), "t1": round(start + m, 3)})
            hold_from = start + m
        if nxt - hold_from > 1e-6:
            kind = "live" if nxt - hold_from >= LIVE_MIN_S - 1e-6 else "hold"
            seg.append({"kind": kind, "a": i, "b": i, "t0": round(hold_from, 3), "t1": round(nxt, 3)})
    return seg


def clip_name(s: dict) -> str:
    return f"mv-{s['a']}-{s['b']}" if s["kind"] == "move" else f"hold-{s['a']}"


def clips_needed(seg: list[dict]) -> list[dict]:
    """The Wan clips a timeline needs (each move, each living hold), once each."""
    out, seen = [], set()
    for s in seg:
        if s["kind"] in ("move", "live") and clip_name(s) not in seen:
            seen.add(clip_name(s))
            out.append(s)
    return out


def ease_out(frames: list, n: int, power: float = EASE_POWER) -> list:
    """A move played in n frames, fast at the start and settling at the end (compose_acting.ease_out)."""
    k = len(frames) - 1
    return [frames[round((1 - (1 - i / max(1, n - 1)) ** power) * k)] for i in range(n)]


def natural(frames: list, n: int, src_fps: int = FLF_FPS) -> list:
    """A living-hold clip at its own speed, looping when the hold is longer (compose_acting.natural)."""
    return [frames[round(i * src_fps / FPS) % len(frames)] for i in range(n)]


def compose(seg: list[dict], total: int, still, clip, base, lock):
    """Yield the shot's frames (PIL RGB). still(i) -> pose i's picture; clip(name) -> that clip's frames. Moves and
    living holds show only inside the lock mask; outside it the base's pixels."""
    from PIL import Image
    out: list = [None] * total
    for s in seg:
        a, b = round(s["t0"] * FPS), min(total, round(s["t1"] * FPS))
        if b <= a:
            continue
        if s["kind"] == "hold":
            for i in range(a, b):
                out[i] = ("still", s["a"])
        else:
            fr = clip(clip_name(s))
            pick = ease_out(fr, b - a) if s["kind"] == "move" else natural(fr, b - a)
            for i, f in enumerate(pick):
                out[a + i] = ("clip", f)
    last = ("still", seg[0]["a"] if seg else 0)
    for i in range(total):
        cur = out[i] or last
        last = cur
        if cur[0] == "still":
            yield still(cur[1])
        else:
            f = cur[1] if cur[1].size == (W, H) else cur[1].resize((W, H), Image.LANCZOS)
            yield Image.composite(f.convert("RGB"), base, lock)


# ================================================================== pure parts: prompts
def eyeline_text(direction: str, toward: str, beat_text: str = "") -> str:
    """The eyeline sentence every face prompt carries (ep15-ISSUES #22)."""
    if CAMERA_WORDS.search(beat_text or ""):
        return "The eyes look straight at the viewer (the acting notes ask for it)."
    t = f", toward {toward}" if toward else ""
    if direction == "right":
        return f"The eyes look slightly to the RIGHT of the viewer (screen-right){t}, not at the camera."
    return f"The eyes look slightly to the LEFT of the viewer (screen-left){t}, not at the camera."


def face_template(name: str, look: str, want: str, eyeline: str) -> str:
    who = f"{name} ({look.strip().rstrip('.')})" if look.strip() else name
    return f"Change the facial expression of {who} to: {want.strip().rstrip('.')}. {eyeline}" + KEEP + MOUTH


def with_rules(text: str, eyeline: str) -> str:
    """A written prompt with the eyeline and the face-only rules made sure of (GPT may leave them out)."""
    t = text.strip()
    if not re.search(r"screen-left|screen-right|straight at the viewer", t, re.I):
        t = f"{t.rstrip('.')}. {eyeline}"
    if "Do not add glasses" not in t:
        t += KEEP
    return t


def move_template(who: str, a: str, b: str, intensity: str, others: bool) -> str:
    rest = " The people beside them stay still." if others else ""
    if intensity == "big":
        return f"Very fast snappy cartoon take: {who} goes from {a} to {b}, quick and clear, then settles.{rest}"
    return f"{who} changes from {a} to {b}, a clear cartoon move that settles at the end.{rest}"


def hold_template(who: str, b: str, others: bool) -> str:
    rest = " The people beside them stay still." if others else ""
    return f"{who} holds {b}, trembling very slightly, blinks once. Almost no movement.{rest}"


# ================================================================== pure parts: graphs (ported from gpu_acting.py)
def edit_graph(image: str, mask: str, prompt: str, seed: int, prefix: str) -> dict:
    """Qwen-Image-Edit-2511 (template wiring: 40 steps, CFG 4, AuraFlow shift 3.1, CFGNorm) that may only repaint
    inside the mask: the latent of the picture with SetLatentNoiseMask from the mask's red channel."""
    q = {m["type"]: m["filename"] for m in QWEN_MODELS}
    g = {"u": {"class_type": "UNETLoader", "inputs": {"unet_name": q["diffusion_model"], "weight_dtype": "default"}},
         "m": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["u", 0], "shift": 3.1}},
         "cn": {"class_type": "CFGNorm", "inputs": {"model": ["m", 0], "strength": 1.0}},
         "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": q["text_encoder"], "type": "qwen_image", "device": "default"}},
         "v": {"class_type": "VAELoader", "inputs": {"vae_name": q["vae"]}},
         "li1": {"class_type": "LoadImage", "inputs": {"image": image}},
         "sc": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["li1", 0]}}}
    refs = {"image1": ["sc", 0]}
    g["pe"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["c", 0], "prompt": prompt, "vae": ["v", 0], **refs}}
    g["ne"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["c", 0], "prompt": "", "vae": ["v", 0], **refs}}
    g["pm"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["pe", 0], "reference_latents_method": "index_timestep_zero"}}
    g["nm"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["ne", 0], "reference_latents_method": "index_timestep_zero"}}
    g["le"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["sc", 0], "vae": ["v", 0]}}
    g["mk"] = {"class_type": "LoadImageMask", "inputs": {"image": mask, "channel": "red"}}
    g["nm2"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["le", 0], "mask": ["mk", 0]}}
    g["k"] = {"class_type": "KSampler", "inputs": {"model": ["cn", 0], "seed": seed, "steps": 40, "cfg": 4.0, "sampler_name": "euler",
                                                   "scheduler": "simple", "positive": ["pm", 0], "negative": ["nm", 0],
                                                   "latent_image": ["nm2", 0], "denoise": 1.0}}
    g["d"] = {"class_type": "VAEDecode", "inputs": {"samples": ["k", 0], "vae": ["v", 0]}}
    g["s"] = {"class_type": "SaveImage", "inputs": {"images": ["d", 0], "filename_prefix": prefix}}
    return g


def flf_graph(a: str, b: str, prompt: str, seed: int, prefix: str, length: int = FLF_FRAMES) -> dict:
    """Wan 2.2 i2v 14B from picture a to picture b (gpu_acting.flf): high-noise model for steps 0-2, low-noise for
    2-4, each with its lightx2v 4-step LoRA, ModelSamplingSD3 shift 5, CFG 1, euler/simple, 1280x720, 16 fps."""
    m = {x["filename"]: x for x in WAN_MODELS}
    names = list(m)
    hi, lo, lhi, llo, te, vae = names
    common = {"steps": FLF_STEPS, "cfg": FLF_CFG, "sampler_name": "euler", "scheduler": "simple",
              "positive": ["w", 0], "negative": ["w", 1]}
    return {"a": {"class_type": "LoadImage", "inputs": {"image": a}},
            "b": {"class_type": "LoadImage", "inputs": {"image": b}},
            "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": te, "type": "wan", "device": "default"}},
            "v": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
            "uh": {"class_type": "UNETLoader", "inputs": {"unet_name": hi, "weight_dtype": "default"}},
            "ul": {"class_type": "UNETLoader", "inputs": {"unet_name": lo, "weight_dtype": "default"}},
            "lh": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["uh", 0], "lora_name": lhi, "strength_model": 1.0}},
            "ll": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ul", 0], "lora_name": llo, "strength_model": 1.0}},
            "sh": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lh", 0], "shift": FLF_SHIFT}},
            "sl": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["ll", 0], "shift": FLF_SHIFT}},
            "p": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": prompt.strip() + FLF_SUFFIX}},
            "n": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": FLF_NEG}},
            "w": {"class_type": "WanFirstLastFrameToVideo", "inputs": {"positive": ["p", 0], "negative": ["n", 0], "vae": ["v", 0],
                  "start_image": ["a", 0], "end_image": ["b", 0], "width": W, "height": H, "length": length, "batch_size": 1}},
            "k1": {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["sh", 0], "add_noise": "enable", "noise_seed": seed,
                   "latent_image": ["w", 2], "start_at_step": 0, "end_at_step": FLF_SPLIT, "return_with_leftover_noise": "enable"}},
            "k2": {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["sl", 0], "add_noise": "disable", "noise_seed": 0,
                   "latent_image": ["k1", 0], "start_at_step": FLF_SPLIT, "end_at_step": FLF_STEPS, "return_with_leftover_noise": "disable"}},
            "d": {"class_type": "VAEDecode", "inputs": {"samples": ["k2", 0], "vae": ["v", 0]}},
            "cv": {"class_type": "CreateVideo", "inputs": {"images": ["d", 0], "fps": FLF_FPS}},
            "sv": {"class_type": "SaveVideo", "inputs": {"video": ["cv", 0], "filename_prefix": "video/" + prefix, "format": "auto", "codec": "auto"}}}


def image_outputs(outputs: dict) -> list[dict]:
    out = []
    for node in outputs.values():
        for f in node.get("images") or []:
            if isinstance(f, dict) and str(f.get("filename", "")).lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                out.append(f)
    return out


# ================================================================== pure parts: cost
def estimate(edits: int, clips: int, prices: list[float]) -> dict:
    """GPU minutes and cost of one run: about 10 min to start, 60-90 s per masked edit, about 2.5 min per Wan clip."""
    if edits <= 0 and clips <= 0:
        return {"minutes": 0.0, "minutes_max": 0.0, "usd_typical": 0.0, "usd_max": 0.0, "edits": 0, "clips": 0,
                "label": "nothing to make"}
    minutes = round(SETUP_MIN + edits * EDIT_MIN + clips * FLF_MIN, 1)
    minutes_max = round(SETUP_MIN + edits * EDIT_MIN_MAX + clips * FLF_MIN, 1)
    p0 = prices[0] if prices else 0.0
    pmax = max(prices) if prices else 0.0
    typ, mx = round(p0 * minutes / 60, 2), round(pmax * minutes_max * MAX_MARGIN / 60, 2)
    what = ", ".join(x for x in (f"{edits} face edit(s)" if edits else "", f"{clips} clip(s)" if clips else "") if x)
    return {"minutes": minutes, "minutes_max": minutes_max, "usd_typical": typ, "usd_max": mx, "edits": edits, "clips": clips,
            "usd_per_hour": p0, "usd_per_hour_max": pmax,
            "label": f"{what}: about {minutes:.0f} GPU min, about ${typ:.2f}, at most ${mx:.2f}"}


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


def _st(v: dict, idx: int) -> dict:
    return v.setdefault("shots", {}).setdefault(str(idx), {})


def _plan(db: Session, eid: int) -> dict:
    from . import shot_frames as SF
    return SF.migrated(SF.stored(db, eid))


def reaction_rows(db: Session, ep: Episode) -> list[dict]:
    """The storyboard's reaction shots: [{index, t0, t1, side, people, shot, kind}] (kind close | group)."""
    from . import talking_s2v as T
    talking = {r["index"] for r in T.talking_rows(db, ep)}
    out = []
    for s in _plan(db, ep.id).get("shots") or []:
        people = [p for p in s.get("people") or [] if p]
        if int(s["index"]) in talking or not people:
            continue
        close = len(people) == 1 and (s.get("shot") or "wide") in ("close", "medium")
        out.append({"index": int(s["index"]), "t0": float(s["t0"]), "t1": float(s["t1"]), "side": s.get("side") or "",
                    "people": people, "shot": s.get("shot") or "wide", "kind": "close" if close else "group"})
    return out


def master_candidates(db: Session, ep: Episode) -> dict[str, list[dict]]:
    """Per side: the approved storyboard stills on that side (wide shots and the most people first)."""
    plan = _plan(db, ep.id)
    order = {"wide": 0, "medium": 1, "close": 2}
    out: dict[str, list[dict]] = {}
    for s in plan.get("shots") or []:
        if s.get("approved") and s.get("chosen") and s.get("side"):
            out.setdefault(s["side"], []).append({"asset_id": s["chosen"], "shot": int(s["index"]), "framing": s.get("shot"),
                                                  "people": len(s.get("people") or [])})
    for k, lst in out.items():
        seen, uniq = set(), []
        for c in sorted(lst, key=lambda c: (order.get(c["framing"], 3), -c["people"], c["shot"])):
            if c["asset_id"] not in seen:
                seen.add(c["asset_id"])
                uniq.append(c)
        out[k] = uniq
    return out


def master_for(db: Session, ep: Episode, v: dict, side: str) -> dict | None:
    """The side's seating master: only the owner's pick ({asset_id, by}); the suggestion is shown, never used."""
    m = (v.get("masters") or {}).get(side)
    return m if m and m.get("asset_id") else None


def _load_master(db: Session, aid: int, folder: Path):
    from PIL import Image
    a = db.get(Asset, aid)
    if not a:
        raise ValueError("the seating master's picture is missing")
    p = storage().get_to_file(a.storage_key, folder / f"master-{aid}{Path(a.storage_key).suffix or '.png'}")
    with Image.open(p) as im:
        return im.convert("RGB")


def master_info(db: Session, v: dict, aid: int) -> dict:
    """{size: [w, h], heads: [...]} of a master, read once and kept."""
    cache = v.setdefault("masters_info", {})
    if str(aid) in cache:
        return cache[str(aid)]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        try:
            im = _load_master(db, aid, Path(d))
            info = {"size": list(im.size), "heads": find_heads(im)[:12]}
        except Exception:   # noqa: BLE001 -- unreadable: the owner sets the crop by hand
            info = {"size": [W, H], "heads": []}
    cache[str(aid)] = info
    v["_dirty"] = True
    return info


def side_members(db: Session, eid: int, side: str) -> list[str]:
    return list((_plan(db, eid).get("sides") or {}).get(side) or [])


def main_speaker(ep: Episode) -> str:
    """The character with the most words in the transcript (person map applied)."""
    tr = ep.audio_transcript or {}
    pm = tr.get("person_map") or {}
    n: dict[str, int] = {}
    for ln in tr.get("lines") or []:
        k = pm.get(ln.get("speaker")) or ln.get("character") or ln.get("speaker") or ""
        if k:
            n[k] = n.get(k, 0) + len(ln.get("words") or str(ln.get("text") or "").split())
    return max(n, key=n.get) if n else ""


def eyeline_for(db: Session, ep: Episode, v: dict, side: str, k: str, names: dict[str, str]) -> dict:
    """{direction, toward}: the owner's choice for the side, else screen-right for the main speaker's side and
    screen-left for everyone else (the speaker sits screen-left of the listeners in the wide; 180-degree rule)."""
    sp = main_speaker(ep)
    sp_side = next((s for s, m in (_plan(db, ep.id).get("sides") or {}).items() if sp in m), "")
    d = (v.get("eyelines") or {}).get(side) or ("right" if side and side == sp_side else "left")
    if k == sp or d == "right":
        toward = "the people they are talking to"
    else:
        c = _people(db, [sp]).get(sp) if sp and sp not in names else None
        toward = names.get(sp) or (c.name if c else "the speaker")
    return {"direction": d, "toward": toward}


def _people(db: Session, keys: list[str]) -> dict[str, Character]:
    return {c.key: c for c in db.query(Character).filter(Character.key.in_(keys))} if keys else {}


def shot_beats(db: Session, eid: int, idx: int) -> list[dict]:
    from . import acting_analysis as AA
    res = AA.stored(db, eid).get("result") or {}
    s = next((x for x in res.get("shots") or [] if x.get("shot") == idx), None)
    return list((s or {}).get("beats") or [])


def ensure_shot(db: Session, ep: Episode, v: dict, row: dict) -> dict:
    """The shot's state, filled in on first sight: crop (suggested from the master's heads), ovals and poses from beats."""
    st = _st(v, row["index"])
    m = master_for(db, ep, v, row["side"])
    if m and (not st.get("crop") or st.get("crop_master") != m["asset_id"]):
        info = master_info(db, v, m["asset_id"])
        mw, mh = info["size"]
        hp = heads_for_people(info["heads"], side_members(db, ep.id, row["side"]))
        heads = [hp[k] for k in row["people"] if k in hp]
        st["crop"] = suggest_crop(heads, mw, mh, row["kind"] == "close")
        st["crop_master"] = m["asset_id"]
        st["crop_approved"] = False
        st.pop("ovals", None)
        v["_dirty"] = True
    if st.get("crop") and not st.get("ovals"):
        info = master_info(db, v, st["crop_master"])
        hp = heads_for_people(info["heads"], side_members(db, ep.id, row["side"]))
        st["ovals"] = {k: default_oval(head_in_crop(hp[k], st["crop"]) if k in hp else None, i, len(row["people"]))
                       for i, k in enumerate(row["people"])}
        v["_dirty"] = True
    if "poses" not in st:
        chars = _people(db, row["people"])
        names = {c.name.lower(): k for k, c in chars.items()}
        st["poses"] = poses_from_beats(shot_beats(db, ep.id, row["index"]), row["t0"], row["t1"] - row["t0"], names)
        st["poses_from"] = "acting beats" if len(st["poses"]) > 1 or st["poses"][0]["faces"] else "no beats yet"
        v["_dirty"] = True
    return st


def base_hash(st: dict) -> str:
    return hashlib.sha256(json.dumps([st.get("crop_master"), {k: st["crop"][k] for k in ("x", "y", "w", "h")}]).encode()).hexdigest()[:12]


def base_key(eid: int, idx: int, st: dict) -> str:
    return f"episodes/{eid}/reactions/shot{idx:02d}-base-{base_hash(st)}.png"


def ensure_base(db: Session, eid: int, idx: int, st: dict) -> str | None:
    """The 1280x720 zoom crop, made once per crop box (free, Pillow) and kept in storage."""
    if not st.get("crop") or not st.get("crop_master"):
        return None
    k = base_key(eid, idx, st)
    if st.get("base_key") == k:
        return k
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        try:
            im = crop_image(_load_master(db, st["crop_master"], Path(d)), st["crop"])
            p = Path(d) / "base.png"
            im.save(p)
            storage().put_file(k, p, "image/png")
        except Exception:   # noqa: BLE001
            return None
    st["base_key"] = k
    return k


def face_prompt(db: Session, ep: Episode, v: dict, row: dict, pose: dict, k: str, chars: dict, beats: list[dict]) -> dict:
    """{text, source, label} for one character's face in one pose: the owner's/GPT's text (eyeline made sure of), or
    the template."""
    f = (pose.get("faces") or {}).get(k) or {}
    names = {kk: c.name for kk, c in chars.items()}
    bt = beats[pose["beat"]] if pose.get("beat") is not None and 0 <= pose["beat"] < len(beats) else {}
    el = eyeline_for(db, ep, v, row["side"], k, names)
    eyeline = eyeline_text(el["direction"], el["toward"], " ".join(str(bt.get(x) or "") for x in ("eyes_and_gaze", "expression")))
    p = f.get("prompt")
    if p and p.get("text"):
        return {**p, "text": with_rules(p["text"], eyeline)}
    c = chars.get(k)
    text = face_template(c.name if c else k, (c.visual_description or "") if c else "", f.get("want") or "neutral", eyeline)
    label = TEMPLATE_LABEL if not secret("openai_api_key", db) else "template prompt (not written by GPT yet)"
    return {"text": text, "source": "template", "label": label}


def pose_prompts(db: Session, ep: Episode, v: dict, row: dict, pose: dict, chars: dict, beats: list[dict]) -> dict[str, dict]:
    return {k: face_prompt(db, ep, v, row, pose, k, chars, beats) for k in (pose.get("faces") or {})}


def take_valid(st: dict, t: dict) -> bool:
    return t.get("base") == (base_hash(st) if st.get("crop") else None)


def pose_ready(st: dict, i: int) -> str | None:
    """The approved picture key for pose i, or None. A pose without face changes is the crop itself (approved when the
    crop is)."""
    p = st["poses"][i]
    if not p.get("faces"):
        return (st.get("base_key") or "crop") if st.get("crop_approved") else None
    t = next((x for x in p.get("takes") or [] if x["id"] == p.get("approved")), None)
    return t["key"] if t and take_valid(st, t) else None


def edits_needed(st: dict, idxs: list[int], prompts: dict[int, dict[str, dict]]) -> int:
    """Face edits a pose run makes: every face of every pose asked for, minus faces whose exact prompt already has a
    valid result in this shot (those are reused, free)."""
    have = {(k, t["prompts"].get(k)) for p in st.get("poses") or [] for t in p.get("takes") or [] if take_valid(st, t)
            for k in (t.get("faces") or {})}
    need = set()
    for i in idxs:
        for k, pr in prompts.get(i, {}).items():
            if (k, pr["text"]) not in have:
                need.add((k, pr["text"]))
    return len(need)


def move_prompts(st: dict, row: dict, seg: list[dict], chars: dict) -> dict[str, dict]:
    """{clip name: {text, source}} for every clip of the timeline (the owner's text, else the template)."""
    poses = st["poses"]
    own = st.get("move_prompts") or {}
    out = {}
    for s in clips_needed(seg):
        a, b = poses[s["a"]], poses[s["b"]]
        changed = [k for k in row["people"] if ((b.get("faces") or {}).get(k) or {}).get("want") !=
                   ((a.get("faces") or {}).get(k) or {}).get("want")] or row["people"][:1]
        who = " and ".join(chars[k].name if k in chars else k for k in changed)
        bw = "; ".join(((b.get("faces") or {}).get(k) or {}).get("want") or "a neutral face" for k in changed)
        aw = "; ".join(((a.get("faces") or {}).get(k) or {}).get("want") or "a neutral face" for k in changed)
        others = len(row["people"]) > len(changed) or row["kind"] == "group"
        n = clip_name(s)
        key_ = str(s["b"]) if s["kind"] == "move" else f"hold-{s['b']}"
        if own.get(key_):
            out[n] = {"text": own[key_], "source": "owner", "key": key_}
        elif s["kind"] == "move":
            big = (b.get("move_s") or 0.3) <= MOVE_S["big"] + 1e-6
            out[n] = {"text": move_template(who, aw, bw, "big" if big else "clear", others), "source": "template", "key": key_}
        else:
            out[n] = {"text": hold_template(who, bw, others), "source": "template", "key": key_}
    return out


# ================================================================== view
def _prices(db: Session) -> list[float]:
    from . import comfy_session as CS
    return CS.list_prices(get_section(db, "gpu"))


def _active(db: Session, eid: int, kinds=(JOB_POSES, JOB_ANIMATE)):
    return db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(("queued", "running")))


def _url(k: str | None) -> str | None:
    return storage().url(k) if k else None


def shot_view(db: Session, ep: Episode, v: dict, row: dict, prices: list[float], assets: dict, light: bool) -> dict:
    st = ensure_shot(db, ep, v, row)
    chars = _people(db, row["people"])
    beats = shot_beats(db, ep.id, row["index"])
    m = master_for(db, ep, v, row["side"])
    out = {"index": row["index"], "t0": row["t0"], "t1": row["t1"], "kind": row["kind"], "side": row["side"],
           "framing": row["shot"], "people": [{"key": k, "name": chars[k].name if k in chars else k} for k in row["people"]],
           "crop": st.get("crop"), "crop_approved": bool(st.get("crop_approved")), "ovals": st.get("ovals") or {},
           "approved": st.get("approved"), "run": st.get("run"), "poses_from": st.get("poses_from")}
    blocked = "" if m else "pick the seating master for this side of the room first"
    if light:
        out["blocked"] = blocked
        out["poses"] = [{"i": i, "approved": bool(pose_ready(st, i)) if st.get("crop") else False,
                         "takes": len(p.get("takes") or [])} for i, p in enumerate(st.get("poses") or [])]
        out["clips"] = len(st.get("clips") or [])
        return out
    if st.get("crop"):
        bk = ensure_base(db, ep.id, row["index"], st)
        out["base_url"] = _url(bk)
        info = master_info(db, v, st["crop_master"])
        out["master"] = {"asset_id": st["crop_master"], "size": info["size"],
                         "url": _url(assets[st["crop_master"]].storage_key) if st["crop_master"] in assets else None}
    out["beats"] = [{"index": i, **{k: b.get(k) for k in ("t_start", "t_end", "character", "on_word", "expression",
                                                       "eyes_and_gaze", "head_and_body", "hold_or_move", "intensity")}}
                    for i, b in enumerate(beats)]
    dur = row["t1"] - row["t0"]
    poses_out, prompts_by = [], {}
    for i, p in enumerate(st.get("poses") or []):
        pr = pose_prompts(db, ep, v, row, p, chars, beats)
        prompts_by[i] = pr
        takes = [{"id": t["id"], "url": _url(t["key"]), "at": t["at"], "usd": t.get("usd"), "valid": take_valid(st, t),
                  "reused": t.get("reused") or []} for t in p.get("takes") or []]
        poses_out.append({"i": i, "id": p["id"], "label": p["label"], "t": p["t"], "move_s": p["move_s"], "beat": p.get("beat"),
                          "faces": {k: {"want": f.get("want"), "prompt": pr[k]} for k, f in (p.get("faces") or {}).items()},
                          "takes": takes, "approved_take": p.get("approved"), "ready": bool(pose_ready(st, i)),
                          "estimate": estimate(edits_needed(st, [i], {i: pr}), 0, prices),
                          "as_is": not p.get("faces")})
    out["poses"] = poses_out
    todo = [i for i, p in enumerate(st.get("poses") or []) if p.get("faces") and not p.get("takes")]
    out["estimate_poses"] = estimate(edits_needed(st, todo, prompts_by), 0, prices)
    out["poses_todo"] = todo
    seg = timeline(st.get("poses") or [], dur)
    out["timeline"] = seg
    mp = move_prompts(st, row, seg, chars)
    out["moves"] = [{"name": n, "kind": "move" if n.startswith("mv-") else "live", **p} for n, p in mp.items()]
    out["estimate_animate"] = estimate(0, len(mp), prices)
    not_ready = [i for i in range(len(st.get("poses") or [])) if not pose_ready(st, i)]
    out["animate_blocked"] = (blocked or ("approve the crop first" if not st.get("crop_approved") else "") or
                              (f"approve pose(s) {', '.join(str(i) for i in not_ready)} first" if not_ready else ""))
    out["clips"] = [{**c, "url": _url(assets[c["asset_id"]].storage_key) if c.get("asset_id") in assets else None,
                     "preview_url": _url(c.get("preview_key"))} for c in st.get("clips") or []]
    out["blocked"] = blocked
    return out


def view(db: Session, ep: Episode, light: bool = False) -> dict:
    from . import comfy_session as CS
    from . import prompt_writer as PW
    v = stored(db, ep.id)
    rows = reaction_rows(db, ep)
    prices = _prices(db)
    cands = master_candidates(db, ep)
    sides = sorted({r["side"] for r in rows if r["side"]} | set(cands))
    ids = {c["asset_id"] for lst in cands.values() for c in lst}
    ids |= {(v.get("masters") or {}).get(s, {}).get("asset_id") for s in sides} - {None}
    for st in (v.get("shots") or {}).values():
        ids |= {c.get("asset_id") for c in st.get("clips") or []} - {None}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids and not light else {}
    shots = [shot_view(db, ep, v, r, prices, assets, light) for r in rows]
    masters = []
    for s in sides:
        m = master_for(db, ep, v, s)
        el = (v.get("eyelines") or {}).get(s)
        masters.append({"side": s, "chosen": m["asset_id"] if m else None, "by": m.get("by") if m else None,
                        "suggested": cands.get(s, [{}])[0].get("asset_id") if cands.get(s) else None,
                        "candidates": [{**c, "url": _url(assets[c["asset_id"]].storage_key) if c["asset_id"] in assets else None}
                                       for c in cands.get(s, [])],
                        "eyeline": el, "eyeline_default": ("right" if main_speaker(ep) in side_members(db, ep.id, s) else "left"),
                        "shots": sum(1 for r in rows if r["side"] == s)})
    if v.get("_dirty"):
        save(db, ep.id, v)
        db.commit()
    job = db.query(Job).filter(Job.kind.in_((JOB_POSES, JOB_ANIMATE)), Job.episode_id == ep.id).order_by(Job.id.desc()).first()
    out = {"shots": shots, "masters": masters, "busy": _active(db, ep.id).first() is not None, "job": S.job(job) if job else None,
           "openai_key": bool(secret("openai_api_key", db))}
    if not light:
        out["availability"] = CS.availability(db)
        out["prompt_estimate"] = PW.estimate(PW.config(db), PW.SYSTEM, "x" * 1600)
        out["settings"] = {"size": [W, H], "fps": FPS, "flf": {"frames": FLF_FRAMES, "fps": FLF_FPS, "steps": FLF_STEPS,
                                                               "cfg": FLF_CFG, "shift": FLF_SHIFT}, "live_min_s": LIVE_MIN_S}
    return out


def summary(db: Session, ep: Episode) -> dict[str, dict]:
    """The guide's steps 6 (close-ups: crops), 7 (faces: poses) and 8 (movement: assembled shots)."""
    vw = view(db, ep, light=True)
    shots = vw["shots"]
    busy = vw["busy"]
    if not shots:
        none = {"status": "not_started", "cost": None, "detail": "no reaction shots in the storyboard yet"}
        return {"closeups": dict(none), "faces": dict(none), "movement": dict(none)}
    crops = sum(1 for s in shots if s["crop_approved"])
    poses = [p for s in shots for p in s["poses"]]
    ok_p = sum(1 for p in poses if p["approved"])
    took = sum(1 for p in poses if p["takes"])
    clips = sum(1 for s in shots if s["clips"])
    ok_c = sum(1 for s in shots if s["approved"])
    no_master = sum(1 for s in shots if s["blocked"])
    return {
        "closeups": {"status": "done" if crops == len(shots) else "needs_approval" if crops < len(shots) and not no_master else "not_started",
                     "cost": {"label": "Free (cut from the seating master on the studio server)"},
                     "detail": f"{crops} of {len(shots)} reaction shots have an approved crop"
                               + (f"; {no_master} wait for a seating master" if no_master else "")},
        "faces": {"status": "running" if busy else "done" if poses and ok_p == len(poses) else
                  "needs_approval" if took > 0 else "not_started", "cost": None,
                  "detail": f"{ok_p} of {len(poses)} poses approved"},
        "movement": {"status": "running" if busy else "done" if ok_c == len(shots) else
                     "needs_approval" if clips > ok_c else "not_started", "cost": None,
                     "detail": f"{ok_c} of {len(shots)} reaction shots approved"},
    }


# ================================================================== routes
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _row(db: Session, ep: Episode, idx: int) -> dict:
    r = next((x for x in reaction_rows(db, ep) if x["index"] == idx), None)
    if r is None:
        raise HTTPException(404, f"shot {idx} is not a reaction shot")
    return r


def _event(db: Session, eid: int, msg: str, kind: str = "episode") -> None:
    db.add(Event(episode_id=eid, kind=kind, message=msg))


@router.get("/episodes/{eid}/reactions")
def get_reactions(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class MasterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: str = Field(min_length=1, max_length=80)
    asset_id: int | None = Field(default=None, ge=1)
    eyeline: str | None = Field(default=None, pattern="^(left|right)$")


@router.put("/episodes/{eid}/reactions/masters")
def set_master(eid: int, body: MasterIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner picks the seating master of one side of the room (an approved storyboard still) and/or the side's
    eyeline. A new master resets that side's crops to a fresh suggestion (not approved)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    known = set(master_candidates(db, ep)) | {r["side"] for r in reaction_rows(db, ep)} | set(_plan(db, eid).get("sides") or {})
    if body.side not in known:
        raise HTTPException(422, "not a side of this episode's storyboard")
    if body.asset_id is not None:
        ok = {c["asset_id"] for lst in master_candidates(db, ep).values() for c in lst}
        if body.asset_id not in ok:
            raise HTTPException(409, "pick an APPROVED still of this episode's storyboard")
        v.setdefault("masters", {})[body.side] = {"asset_id": body.asset_id, "by": user, "at": time.time()}
        _event(db, eid, f"Reactions: seating master for {body.side} picked by {user}")
    if body.eyeline is not None:
        v.setdefault("eyelines", {})[body.side] = body.eyeline
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class CropIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cx: float = Field(ge=0, le=20000)
    cy: float = Field(ge=0, le=20000)
    w: float = Field(ge=16, le=20000)


@router.put("/episodes/{eid}/reactions/{idx}/crop")
def set_crop(eid: int, idx: int, body: CropIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's crop (centre and width in master pixels; kept 16:9 inside the master). Free. The crop's approval and
    the face ovals start again; earlier pose results stay listed but cannot be approved (they show the old crop)."""
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    if not st.get("crop"):
        raise HTTPException(409, "pick the seating master for this side first")
    mw, mh = master_info(db, v, st["crop_master"])["size"]
    st["crop"] = {**box_from_owner(body.cx, body.cy, body.w, mw, mh), "source": "owner"}
    st["crop_approved"] = False
    st.pop("ovals", None)
    for p in st["poses"]:
        p["approved"] = None
    ensure_shot(db, ep, v, row)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class ApproveCropIn(BaseModel):
    approved: bool = True


@router.post("/episodes/{eid}/reactions/{idx}/crop/approve")
def approve_crop(eid: int, idx: int, body: ApproveCropIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    if not st.get("crop"):
        raise HTTPException(409, "pick the seating master for this side first")
    st["crop_approved"], st["crop_approved_by"] = body.approved, (user if body.approved else None)
    if body.approved and not ensure_base(db, eid, idx, st):
        raise HTTPException(409, "the zoom crop could not be made from the seating master")
    save(db, eid, v)
    _event(db, eid, f"Reaction shot {idx}: crop {'approved' if body.approved else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


class OvalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: str = Field(min_length=1, max_length=80)
    cx: float = Field(ge=0, le=W)
    cy: float = Field(ge=0, le=H)
    rx: float = Field(ge=8, le=W / 2)
    ry: float = Field(ge=8, le=H / 2)


@router.put("/episodes/{eid}/reactions/{idx}/oval")
def set_oval(eid: int, idx: int, body: OvalIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's face oval for one character (base pixels, 1280x720). Free."""
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    if body.character not in row["people"]:
        raise HTTPException(422, "that character is not in this shot")
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    st.setdefault("ovals", {})[body.character] = clamp_oval({**body.model_dump(), "source": "owner"})
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class PoseEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, min_length=1, max_length=120)
    t: float | None = Field(default=None, ge=0, le=600)
    move_s: float | None = Field(default=None, ge=0.08, le=3)
    faces: dict[str, str] | None = Field(default=None, max_length=12)       # character -> what the face shows ("" clears)
    prompts: dict[str, str] | None = Field(default=None, max_length=12)     # character -> the full prompt text


def _pose_or_404(st: dict, i: int) -> dict:
    if not 0 <= i < len(st.get("poses") or []):
        raise HTTPException(404, "no such pose")
    return st["poses"][i]


def apply_pose_edit(st: dict, row: dict, i: int, body: PoseEditIn, user: str) -> None:
    p = _pose_or_404(st, i)
    dur = row["t1"] - row["t0"]
    if body.label is not None:
        p["label"] = body.label
    if body.t is not None:
        if i == 0 and body.t != 0:
            raise HTTPException(422, "pose 0 starts the shot")
        p["t"] = round(min(body.t, max(0.0, dur - 0.05)), 2)
    if body.move_s is not None:
        p["move_s"] = round(body.move_s, 2)
    changed = False
    for k, want in (body.faces or {}).items():
        if k not in row["people"]:
            raise HTTPException(422, f"{k} is not in this shot")
        if want.strip():
            if (p.get("faces") or {}).get(k, {}).get("want") != want.strip():
                p.setdefault("faces", {})[k] = {"want": want.strip()[:400]}
                changed = True
        elif k in (p.get("faces") or {}):
            p["faces"].pop(k)
            changed = True
    for k, text in (body.prompts or {}).items():
        if k not in (p.get("faces") or {}):
            raise HTTPException(422, f"pose {i} does not change {k}'s face: describe the face first")
        p["faces"][k]["prompt"] = {"text": text.strip()[:4000], "source": "owner", "label": "edited by you", "by": user,
                                   "at": time.time()}
        changed = True
    if changed:
        p["approved"] = None


@router.put("/episodes/{eid}/reactions/{idx}/poses/{i}")
def edit_pose(eid: int, idx: int, i: int, body: PoseEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's edit of one pose (free): label, start time, move length, what each face shows, the prompt text.
    A changed face or prompt withdraws the pose's approval (its picture no longer matches)."""
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    apply_pose_edit(st, row, i, body, user)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class PoseAddIn(BaseModel):
    after: int = Field(ge=0, le=MAX_POSES)


@router.post("/episodes/{eid}/reactions/{idx}/poses")
def add_pose(eid: int, idx: int, body: PoseAddIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    p = _pose_or_404(st, body.after)
    if len(st["poses"]) >= MAX_POSES:
        raise HTTPException(409, f"at most {MAX_POSES} poses per shot")
    nxt = st["poses"][body.after + 1]["t"] if body.after + 1 < len(st["poses"]) else row["t1"] - row["t0"]
    new = _pose(f"{p['label']} (new)", (p["t"] + nxt) / 2, {k: {"want": f["want"]} for k, f in (p.get("faces") or {}).items()}, 0.35)
    st["poses"].insert(body.after + 1, new)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


@router.delete("/episodes/{eid}/reactions/{idx}/poses/{i}")
def delete_pose(eid: int, idx: int, i: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    _pose_or_404(st, i)
    if i == 0:
        raise HTTPException(409, "pose 0 starts the shot and cannot be removed")
    st["poses"].pop(i)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/reactions/{idx}/poses/from-beats")
def poses_again(eid: int, idx: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The poses made again from the (edited) acting beats. Earlier pose results are dropped from the list."""
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    _st(v, idx).pop("poses", None)
    ensure_shot(db, ep, v, row)
    save(db, eid, v)
    _event(db, eid, f"Reaction shot {idx}: poses made again from the acting beats by {user}")
    db.commit()
    return view(db, ep)


class WriteIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


def _prompt_message(db: Session, ep: Episode, row: dict, pose: dict, k: str, chars: dict, eyeline: str) -> str:
    from . import acting_analysis as AA
    from . import prompt_writer as PW
    c = chars.get(k)
    want = ((pose.get("faces") or {}).get(k) or {}).get("want") or "neutral"
    notes = (f"Reaction shot {row['index']}, pose '{pose['label']}'. New face of {c.name if c else k}: {want}. "
             f"Eyeline (keep it in the prompt): {eyeline} The edit is MASKED to the face interior: only eyes, "
             "eyebrows, mouth and moustache can change. Never ask for a huge wide-open mouth (it comes out as a smudge).")
    acting = PW.acting_for_shot(AA.stored(db, ep.id).get("result"), row["index"], c.name if c else "")
    look = f"{c.name}. {c.visual_description or ''}".strip() if c else k
    return PW.user_message("face_edit", get_section(db, "stick").get("style_prompt") or "", look, notes, acting)


@router.post("/episodes/{eid}/reactions/{idx}/poses/{i}/write-prompt")
def write_prompt(eid: int, idx: int, i: int, body: WriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one GPT call per changed face of this pose, cost confirmed first). Without an OpenAI key or credit the
    template is kept, labelled "template prompt (GPT unavailable)". The eyeline is always made sure of."""
    from . import prompt_writer as PW
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    p = _pose_or_404(st, i)
    if not p.get("faces"):
        raise HTTPException(409, "this pose keeps the crop as it is: describe a face first")
    chars = _people(db, row["people"])
    beats = shot_beats(db, eid, idx)
    cfg = PW.config(db)
    names = {kk: c.name for kk, c in chars.items()}
    msgs = {}
    for k in p["faces"]:
        el = eyeline_for(db, ep, v, row["side"], k, names)
        msgs[k] = _prompt_message(db, ep, row, p, k, chars, eyeline_text(el["direction"], el["toward"]))
    usd_max = round(sum(PW.estimate(cfg, PW.SYSTEM, m)["usd_max"] for m in msgs.values()), 4)
    api_key = secret("openai_api_key", db)
    if api_key and (body.confirm_usd is None or body.confirm_usd + 1e-9 < usd_max):
        raise HTTPException(409, f"writing these prompts can cost up to ${usd_max:.4f}: confirm that amount to start (nothing was sent)")
    for k in p["faces"]:
        p["faces"][k].pop("prompt", None)                 # the template, unless GPT writes it below
    if api_key:
        total = 0.0
        for k, m in msgs.items():
            try:
                out = PW.call_openai(api_key, cfg["prompt_model"], PW.SYSTEM, m, int(cfg["prompt_max_tokens"]))
            except HTTPException as e:
                if e.status_code != 402:
                    raise
                break
            if out and out["text"]:
                usd = PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg)
                total += usd
                p["faces"][k]["prompt"] = {"text": out["text"], "source": "gpt", "label": f"written by {cfg['prompt_model']}",
                                           "usd": usd, "at": time.time(), "by": user}
        if total:
            _event(db, eid, f"Reaction shot {idx}, pose {i}: prompts written by {cfg['prompt_model']} (${total:.4f})")
    p["approved"] = None
    save(db, eid, v)
    db.commit()
    return view(db, ep)


def _gpu_checks(db: Session, eid: int, est: dict, confirm: float | None, what: str) -> None:
    from . import comfy_session as CS
    from . import gpu
    a = CS.availability(db)
    if not a["ok"]:
        raise HTTPException(409, a["reason"])
    if _active(db, eid).first():
        raise HTTPException(409, "a reaction GPU run is already going for this episode")
    if confirm is None or confirm + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"{what} can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    c = get_section(db, "gpu")
    fig = gpu.month_figures(db)
    if fig["committed_usd"] + est["usd_max"] > float(c["monthly_cap_usd"]) + 1e-9:
        raise HTTPException(409, f"Paused: this run (up to ${est['usd_max']:.2f}) would pass the monthly GPU cap "
                                 f"(${fig['committed_usd']:.2f} committed of ${float(c['monthly_cap_usd']):.2f}). Raise the cap or wait for next month")
    if est.get("minutes_max", 0) > int(c["max_lifetime_minutes"]) - 5:
        raise HTTPException(409, "this run is longer than the maximum GPU session: raise it in Settings > GPU worker or run fewer poses")


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poses: list[int] | None = Field(default=None, max_length=MAX_POSES)
    confirm_usd: float | None = Field(default=None, ge=0, le=200)


def generate_poses(eid: int, idx: int, body: GenerateIn, db: Session, user: str) -> dict:
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    if not st.get("crop"):
        raise HTTPException(409, "pick the seating master for this side first")
    if not st.get("crop_approved"):
        raise HTTPException(409, "approve the crop first (step 6)")
    want = body.poses if body.poses else [i for i, p in enumerate(st["poses"]) if p.get("faces") and not p.get("takes")]
    want = [i for i in dict.fromkeys(want) if 0 <= i < len(st["poses"]) and st["poses"][i].get("faces")]
    if not want:
        raise HTTPException(409, "no pose with a face change to make")
    for i in want:
        missing = [k for k in st["poses"][i]["faces"] if k not in (st.get("ovals") or {})]
        if missing:
            raise HTTPException(409, f"pose {i}: set the face oval of {', '.join(missing)} first")
    chars = _people(db, row["people"])
    beats = shot_beats(db, eid, idx)
    prompts = {i: pose_prompts(db, ep, v, row, st["poses"][i], chars, beats) for i in want}
    est = estimate(edits_needed(st, want, prompts), 0, _prices(db))
    _gpu_checks(db, eid, est, body.confirm_usd, f"making {len(want)} pose(s)")
    ensure_base(db, eid, idx, st)
    job = enqueue(db, JOB_POSES, episode_id=eid, payload={"shot": idx, "poses": want, "confirm_usd": float(body.confirm_usd),
                                                         "estimate": est, "by": user, "backend": "gpu"})
    st["run"] = {"status": "queued", "what": "poses", "job_id": job.id, "at": time.time(), "poses": want}
    save(db, eid, v)
    _event(db, eid, f"Reaction shot {idx}: poses {', '.join(map(str, want))} asked by {user} (up to ${est['usd_max']:.2f})")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/reactions/{idx}/poses/generate")
def generate_poses_route(eid: int, idx: int, body: GenerateIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: masked face edits for these poses (all poses with a face change and no result yet when empty) on a rented
    GPU. Starts only with the most it can cost confirmed and within the monthly GPU cap."""
    return generate_poses(eid, idx, body, db, user)


class ApprovePoseIn(BaseModel):
    take_id: str | None = None


@router.post("/episodes/{eid}/reactions/{idx}/poses/{i}/approve")
def approve_pose(eid: int, idx: int, i: int, body: ApprovePoseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: this picture is the pose (null withdraws). Results of an older crop cannot be approved."""
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    p = _pose_or_404(st, i)
    if body.take_id is not None:
        t = next((x for x in p.get("takes") or [] if x["id"] == body.take_id), None)
        if t is None:
            raise HTTPException(404, "no such result for this pose")
        if not take_valid(st, t):
            raise HTTPException(409, "this result shows an older crop: make the pose again")
    p["approved"], p["approved_by"] = body.take_id, (user if body.take_id else None)
    save(db, eid, v)
    _event(db, eid, f"Reaction shot {idx}, pose {i}: {'approved' if body.take_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


class MovesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    move_prompts: dict[str, str] = Field(max_length=40)


MOVE_KEY = re.compile(r"^(hold-)?\d{1,2}$")


def check_move_prompts(mp: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, t in mp.items():
        if not MOVE_KEY.match(str(k)):
            raise ValueError(f"\"{k}\" is not a move (use the pose number it moves into, or hold-<pose>)")
        if not isinstance(t, str) or len(t) > 1500:
            raise ValueError("a move prompt is text of at most 1500 characters")
        out[str(k)] = t.strip()
    return out


@router.put("/episodes/{eid}/reactions/{idx}/moves")
def edit_moves(eid: int, idx: int, body: MovesIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's move prompts (free). Key: the pose a move goes into ("2"), or "hold-2" for pose 2's living hold;
    an empty text goes back to the template."""
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    try:
        mp = check_move_prompts(body.move_prompts)
    except ValueError as e:
        raise HTTPException(422, str(e))
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    own = st.setdefault("move_prompts", {})
    for k, t in mp.items():
        if t:
            own[k] = t
        else:
            own.pop(k, None)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class AnimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    move_prompts: dict[str, str] | None = Field(default=None, max_length=40)
    confirm_usd: float | None = Field(default=None, ge=0, le=200)


def animate(eid: int, idx: int, body: AnimateIn, db: Session, user: str) -> dict:
    ep = _episode(db, eid)
    row = _row(db, ep, idx)
    v = stored(db, eid)
    st = ensure_shot(db, ep, v, row)
    if body.move_prompts:
        try:
            mp = check_move_prompts(body.move_prompts)
        except ValueError as e:
            raise HTTPException(422, str(e))
        own = st.setdefault("move_prompts", {})
        for k, t in mp.items():
            if t:
                own[k] = t
            else:
                own.pop(k, None)
    if not st.get("crop_approved"):
        raise HTTPException(409, "approve the crop first (step 6)")
    not_ready = [i for i in range(len(st["poses"])) if not pose_ready(st, i)]
    if not_ready:
        raise HTTPException(409, f"approve pose(s) {', '.join(map(str, not_ready))} first")
    seg = timeline(st["poses"], row["t1"] - row["t0"])
    est = estimate(0, len(clips_needed(seg)), _prices(db))
    _gpu_checks(db, eid, est, body.confirm_usd, "animating this shot")
    job = enqueue(db, JOB_ANIMATE, episode_id=eid, payload={"shot": idx, "confirm_usd": float(body.confirm_usd), "estimate": est,
                                                           "by": user, "backend": "gpu"})
    st["run"] = {"status": "queued", "what": "animate", "job_id": job.id, "at": time.time()}
    save(db, eid, v)
    _event(db, eid, f"Reaction shot {idx}: animation asked by {user} (up to ${est['usd_max']:.2f})")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/reactions/{idx}/animate")
def animate_route(eid: int, idx: int, body: AnimateIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: the moves and living holds between the approved poses on a rented GPU, then the shot assembled on the
    studio server. Only with every pose approved and the most it can cost confirmed."""
    return animate(eid, idx, body, db, user)


class ApproveShotIn(BaseModel):
    clip_id: str | None = None


@router.post("/episodes/{eid}/reactions/{idx}/approve")
def approve_shot(eid: int, idx: int, body: ApproveShotIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    _row(db, ep, idx)
    v = stored(db, eid)
    st = _st(v, idx)
    if body.clip_id is not None and not any(c["id"] == body.clip_id for c in st.get("clips") or []):
        raise HTTPException(404, "no such result for this shot")
    st["approved"], st["approved_by"] = body.clip_id, (user if body.clip_id else None)
    save(db, eid, v)
    _event(db, eid, f"Reaction shot {idx}: {'approved' if body.clip_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/reactions/stop")
def stop(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import comfy_session as CS
    _episode(db, eid)
    try:
        done = CS.stop(db, f"stopped by {user}")
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f"RunPod could not be reached; the session is still open: {str(e)[:200]}")
    return {"terminated": done}


# ================================================================== the jobs
from .tasks import Ctx, task  # noqa: E402


def _set_run(db: Session, eid: int, idx: int, **run) -> None:
    db.expire_all()
    v = stored(db, eid)
    st = _st(v, idx)
    st["run"] = {**(st.get("run") or {}), **run}
    save(db, eid, v)
    db.commit()


class _Run:
    """The GPU side shared by both jobs: one ComfyUI session, money spent so far, the confirmed limit."""

    def __init__(self, ctx: Ctx, eid: int, idx: int, confirm: float):
        from . import gpu
        self.ctx, self.db, self.eid, self.idx, self.confirm = ctx, ctx.db, eid, idx, confirm
        self.t_start = gpu.clock()
        self.used: dict[str, float] = {}
        self.sess = None

    def stage(self, text: str) -> None:
        self.ctx.log(text)
        _set_run(self.db, self.eid, self.idx, stage=text)

    def session(self, models: list[dict]) -> dict:
        from . import comfy_session as CS
        self.stage("Starting the rented GPU")
        s = CS.launch(self.db, self.stage)
        self.used.setdefault(s["session"], max(self.t_start, s["launched_at"]))
        self.stage("Getting the models ready on the GPU")
        CS.ensure_models(self.db, s, models, self.stage)
        self.sess = s
        return s

    def spent(self) -> float:
        from . import gpu
        led = gpu.ledger(self.db)["sessions"]
        tot = 0.0
        for sid, since in self.used.items():
            s = led.get(sid) or {}
            end = s.get("ended_at") or gpu.clock()
            tot += float(s.get("price_per_hour") or 0) * max(0.0, end - max(since, s.get("launched_at", since))) / 3600
        return tot

    def room_for(self, minutes: float) -> bool:
        return self.spent() + float(self.sess["price_per_hour"]) * minutes / 60 <= self.confirm + 1e-9

    def run_graph(self, graph: dict, minutes: float) -> dict:
        from . import gpu
        from .comfy import ComfyError
        cl = self.sess["client"]
        pid = cl.submit(graph)
        t0 = gpu.clock()
        while True:
            gpu.sleep(POLL_S)
            why = gpu.check_session(self.db, self.sess["session"])
            if why:
                raise gpu.GpuUnavailable(f"Stopped: {why}")
            stt = cl.status(pid)
            if stt["error"]:
                raise ComfyError(stt["error"])
            if stt["done"]:
                gpu.touch(self.db, self.sess["session"], clips=1)
                return stt["outputs"]
            if gpu.clock() - t0 > minutes * 60 * 3 + 600:
                raise ComfyError("the GPU took far longer than expected")

    def finish(self, job_id: int) -> None:
        from . import comfy_session as CS
        if not CS.others_waiting(self.db, job_id):
            try:
                CS.stop(self.db, "reactions finished")
            except Exception as e:   # noqa: BLE001 -- the sweep tries again
                self.ctx.log(f"could not terminate the GPU now ({str(e)[:120]}); the idle sweep will")


def _store_png(db: Session, ep: Episode, job: Job, img, k: str, label: str, folder: Path) -> Asset:
    p = folder / f"{uuid.uuid4().hex[:8]}.png"
    img.save(p)
    storage().put_file(k, p, "image/png")
    a = Asset(episode_id=ep.id, job_id=job.id, kind="image", label=label, storage_key=k, content_type="image/png",
              size=p.stat().st_size, sha256=sha256_file(p))
    db.add(a)
    db.flush()
    return a


def _load_key(k: str, folder: Path):
    from PIL import Image
    p = storage().get_to_file(k, folder / f"{uuid.uuid4().hex[:8]}{Path(k).suffix or '.png'}")
    with Image.open(p) as im:
        return im.convert("RGB")


@task
def reaction_poses(ctx: Ctx) -> dict:
    from PIL import Image
    from .comfy import ComfyError
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    idx, want = int(p["shot"]), list(p.get("poses") or [])
    folder = ctx.folder("episodes", ep.id, f"reactions-job{job.id}")
    run = _Run(ctx, ep.id, idx, float(p.get("confirm_usd") or 0))
    done, failed, skipped = [], [], []
    _set_run(db, ep.id, idx, status="running", started=time.time(), error="", est_s=int(p.get("estimate", {}).get("minutes", 10) * 60))
    try:
        row = _row(db, ep, idx)
        v = stored(db, ep.id)
        st = ensure_shot(db, ep, v, row)
        bk = ensure_base(db, ep.id, idx, st)
        save(db, ep.id, v)
        db.commit()
        if not bk:
            raise ValueError("the zoom crop could not be made")
        base = _load_key(bk, folder)
        chars = _people(db, row["people"])
        beats = shot_beats(db, ep.id, idx)
        bh = base_hash(st)
        # faces already made in this shot (same character, same prompt, same crop) are reused, not paid again
        reuse = {}
        for pp in st["poses"]:
            for t in pp.get("takes") or []:
                if take_valid(st, t):
                    for k, fk in (t.get("faces") or {}).items():
                        reuse.setdefault((k, t["prompts"].get(k)), fk)
        cl = None
        for i in want:
            pose = st["poses"][i]
            prompts = pose_prompts(db, ep, v, row, pose, chars, beats)
            cur = base.copy()
            faces_keys, seeds, reused, usd = {}, {}, [], 0.0
            try:
                for k, pr in prompts.items():
                    o = st["ovals"][k]
                    hit = reuse.get((k, pr["text"]))
                    if hit:
                        cur = paste_back(cur, _load_key(hit, folder), o)
                        faces_keys[k] = hit
                        reused.append(k)
                        continue
                    if run.sess is None:
                        run.session(QWEN_MODELS)
                        cl = run.sess["client"]
                    if not run.room_for(EDIT_MIN_MAX):
                        raise _Skip(f"not started: it would pass the confirmed ${run.confirm:.2f}")
                    run.stage(f"Pose {i}: {chars[k].name if k in chars else k}'s face on {run.sess['gpu_type']}")
                    src = folder / f"ep{ep.id}-s{idx:02d}-p{i}-{_slug(k)}-in.png"
                    cur.save(src)
                    msk = folder / f"ep{ep.id}-s{idx:02d}-p{i}-{_slug(k)}-mask.png"
                    oval_mask(o).convert("RGB").save(msk)
                    seed = random.randint(1, 2**31 - 1)
                    t0 = time.time()
                    outs = run.run_graph(edit_graph(cl.upload(src), cl.upload(msk), pr["text"], seed,
                                                    f"ep{ep.id}-react{idx:02d}-p{i}-{uuid.uuid4().hex[:6]}"), EDIT_MIN_MAX)
                    files = [f for f in image_outputs(outs) if f.get("type", "output") == "output"]
                    if not files:
                        raise ComfyError("the GPU returned no picture")
                    got = cl.download(files[0], folder / f"edit-{i}-{_slug(k)}.png")
                    with Image.open(got) as im:
                        raw = im.convert("RGB").resize((W, H), Image.LANCZOS)
                    fk = f"episodes/{ep.id}/reactions/shot{idx:02d}-face-{_slug(k)}-{uuid.uuid4().hex[:8]}.png"
                    p2 = folder / "raw.png"
                    raw.save(p2)
                    storage().put_file(fk, p2, "image/png")
                    cur = paste_back(cur, raw, o)
                    faces_keys[k], seeds[k] = fk, seed
                    reuse[(k, pr["text"])] = fk
                    usd += float(run.sess["price_per_hour"]) * (time.time() - t0) / 3600
                tid = uuid.uuid4().hex[:8]
                pk = f"episodes/{ep.id}/reactions/shot{idx:02d}-pose{i}-{tid}.png"
                a = _store_png(db, ep, job, cur, pk, f"Reaction shot {idx}, pose {i} ({pose['label']})", folder)
                rec = {"id": tid, "key": pk, "asset_id": a.id, "at": time.time(), "base": bh, "faces": faces_keys,
                       "prompts": {k: pr["text"] for k, pr in prompts.items()}, "seeds": seeds, "reused": reused,
                       "usd": round(usd, 3), "gpu": run.sess["gpu_type"] if run.sess else None, "job_id": job.id}
                db.commit()
                db.expire_all()
                v = stored(db, ep.id)
                st = _st(v, idx)
                st["poses"][i]["takes"] = [rec] + (st["poses"][i].get("takes") or [])
                save(db, ep.id, v)
                _event(db, ep.id, f"Reaction shot {idx}: pose {i} made (not approved)")
                db.commit()
                done.append(i)
            except _Skip as e:
                skipped.append(i)
                ctx.log(f"pose {i}: {e}")
            except ComfyError as e:
                failed.append(i)
                ctx.log(f"pose {i}: {e}")
        _set_run(db, ep.id, idx, status="done" if not failed else "failed", stage="", finished=time.time(),
                 error=(f"pose(s) {', '.join(map(str, failed))} failed" if failed else
                        f"pose(s) {', '.join(map(str, skipped))} not started: the confirmed amount was reached" if skipped else ""))
    except Exception as e:
        _set_run(db, ep.id, idx, status="failed", error=str(e)[:300], stage="")
        raise
    finally:
        run.finish(job.id)
        shutil.rmtree(folder, ignore_errors=True)
    return {"done": done, "failed": failed, "skipped": skipped, "usd": round(run.spent(), 3)}


class _Skip(Exception):
    pass


def _decode(ff: str, video: Path, folder: Path) -> list:
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([ff, "-v", "error", "-y", "-i", str(video), str(folder / "%04d.png")], capture_output=True, text=True,
                       timeout=300, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise ValueError(f"a clip could not be read: {(r.stderr or '')[-200:]}")
    out = []
    for f in sorted(folder.glob("*.png")):
        with Image.open(f) as im:
            out.append(im.convert("RGB").resize((W, H), Image.LANCZOS))
    if not out:
        raise ValueError("a clip had no frames")
    return out


def encode(ff: str, frames, total: int, dst: Path) -> Path:
    """Raw RGB frames piped into FFmpeg: H.264, 25 fps, yuv420p, silent (the assembly adds the episode audio)."""
    p = subprocess.Popen([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                          "-i", "-", "-frames:v", str(total), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(dst)],
                         stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in frames:
            p.stdin.write(f.tobytes())
        p.stdin.close()
        err = p.stderr.read().decode(errors="replace")
        p.wait(timeout=600)
    finally:
        if p.poll() is None:
            p.kill()
    if p.returncode != 0 or not dst.exists():
        raise ValueError(f"the shot could not be encoded: {err[-200:]}")
    return dst


@task
def reaction_animate(ctx: Ctx) -> dict:
    from . import talking_s2v as T
    from .comfy import ComfyError, video_outputs
    from .config import get_settings
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    idx = int(p["shot"])
    folder = ctx.folder("episodes", ep.id, f"reactions-anim-job{job.id}")
    run = _Run(ctx, ep.id, idx, float(p.get("confirm_usd") or 0))
    ff = get_settings().ffmpeg
    _set_run(db, ep.id, idx, status="running", started=time.time(), error="", est_s=int(p.get("estimate", {}).get("minutes", 10) * 60))
    try:
        if not ff:
            raise ValueError("FFmpeg is not configured on the studio server")
        row = _row(db, ep, idx)
        v = stored(db, ep.id)
        st = ensure_shot(db, ep, v, row)
        if not ensure_base(db, ep.id, idx, st):
            raise ValueError("the zoom crop could not be made")
        keys = [pose_ready(st, i) for i in range(len(st["poses"]))]
        if not all(keys):
            raise ValueError("a pose is not approved any more")
        dur = row["t1"] - row["t0"]
        seg = timeline(st["poses"], dur)
        chars = _people(db, row["people"])
        mp = move_prompts(st, row, seg, chars)
        need = clips_needed(seg)
        stills = {i: _load_key(k, folder) for i, k in enumerate(keys)}
        base = _load_key(st["base_key"], folder)
        pose_files = {}
        for i, im in stills.items():
            f = folder / f"ep{ep.id}-s{idx:02d}-pose{i}.png"
            im.save(f)
            pose_files[i] = f
        clips: dict[str, Path] = {}
        usd = 0.0
        if need:
            run.session(WAN_MODELS)
            cl = run.sess["client"]
            up = {i: cl.upload(f) for i, f in pose_files.items() if any(s["a"] == i or s["b"] == i for s in need)}
            for n, s in enumerate(need, 1):
                name = clip_name(s)
                if not run.room_for(FLF_MIN * 1.5):
                    raise ValueError(f"stopped before clip {n} of {len(need)}: it would pass the confirmed ${run.confirm:.2f}")
                run.stage(f"Clip {n} of {len(need)} ({'move' if s['kind'] == 'move' else 'living hold'}) on {run.sess['gpu_type']}")
                t0 = time.time()
                outs = run.run_graph(flf_graph(up[s["a"]], up[s["b"]], mp[name]["text"], random.randint(1, 2**31 - 1),
                                               f"ep{ep.id}-react{idx:02d}-{name}-{uuid.uuid4().hex[:6]}"), FLF_MIN * 1.5)
                files = [f for f in video_outputs(outs) if f.get("type", "output") == "output"]
                if not files:
                    raise ComfyError("the GPU returned no video")
                clips[name] = cl.download(files[-1], folder / f"{name}{Path(files[-1]['filename']).suffix}")
                usd += float(run.sess["price_per_hour"]) * (time.time() - t0) / 3600
            run.finish(job.id)                  # the GPU is not needed for the assembly
            run.sess = None
        run.stage("Putting the shot together")
        frames_of: dict[str, list] = {}

        def clip(name: str) -> list:
            if name not in frames_of:
                frames_of[name] = _decode(ff, clips[name], folder / f"fr-{name}")
            return frames_of[name]
        total = max(1, round(dur * FPS))
        lock = lock_mask([st["ovals"][k] for k in row["people"] if k in st["ovals"]] or [default_oval(None)])
        out = encode(ff, compose(seg, total, lambda i: stills[i], clip, base, lock), total, folder / "shot.mp4")
        cid = uuid.uuid4().hex[:8]
        vk = f"episodes/{ep.id}/reactions/shot{idx:02d}-{cid}.mp4"
        storage().put_file(vk, out, "video/mp4")
        asset = Asset(episode_id=ep.id, job_id=job.id, kind="video", label=f"Reaction shot {idx}", storage_key=vk,
                      content_type="video/mp4", size=out.stat().st_size, sha256=sha256_file(out))
        db.add(asset)
        db.flush()
        pv = T._mux_preview(ep, row, out, folder / "review.mp4", folder)
        pk = None
        if pv:
            pk = f"episodes/{ep.id}/reactions/shot{idx:02d}-{cid}-review.mp4"
            storage().put_file(pk, pv, "video/mp4")
        rec = {"id": cid, "asset_id": asset.id, "preview_key": pk, "at": time.time(), "timeline": seg, "frames": total, "fps": FPS,
               "moves": {n: x["text"] for n, x in mp.items()}, "usd": round(usd, 3), "job_id": job.id}
        db.commit()
        db.expire_all()
        v = stored(db, ep.id)
        st = _st(v, idx)
        st["clips"] = [rec] + (st.get("clips") or [])
        st["run"] = {**(st.get("run") or {}), "status": "done", "stage": "", "finished": time.time()}
        save(db, ep.id, v)
        _event(db, ep.id, f"Reaction shot {idx} animated ({len(need)} clip(s)) and assembled (not approved)")
        db.commit()
    except Exception as e:
        _set_run(db, ep.id, idx, status="failed", error=str(e)[:300], stage="")
        raise
    finally:
        run.finish(job.id)
        shutil.rmtree(folder, ignore_errors=True)
    return {"clips": len(need), "usd": round(run.spent(), 3)}
