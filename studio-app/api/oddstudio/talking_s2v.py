"""Talking shots (guided flow, step 9): the owner-approved method of 2026-11-26, run from the dashboard.

Which shots: the storyboard's shots (shot_frames.py) whose kind is "talk", or in which the person speaking (the
recording's line over the shot, mapped by the transcript's person map) is on screen. The picture is the shot's APPROVED
still; nothing runs on an unapproved still.

The method (do not change without the owner):
  * Model: Wan 2.2 Speech-to-Video on a rented ComfyUI session (comfy_session.py). Settings "B": 20 steps, CFG 4.5,
    uni_pc / simple, ModelSamplingSD3 shift 8, 1024x576, 16 fps. A piece is at most 77 frames and always 4k+1 frames;
    longer shots are chained: WanSoundImageToVideoExtend + KSampler + LatentConcat on "t" (build_graph).
  * Audio: a VOICE-ONLY copy of the shot's slice of the episode recording: everything is muted except the speaker's
    words (Whisper word times from the transcript), each word cut to its natural length (0.07 s per character + 0.10 s)
    so laughter over a stretched word drops out (voice_spans). The final episode keeps the original audio.
  * Prompt: written by GPT with the shot's acting beats (prompt_writer.py, cost confirmed first). Without an OpenAI key
    or credit the built-in template is used and labelled "template prompt (GPT unavailable)". Always editable.
  * Movement guide (optional, on by default): the speaker's actor's pose points from the private reference video
    (MediaPipe on the GPU session, pose_remote.py), only frames where that actor is on screen (signature match), gaps
    filled from his nearest frame, no guide below 40% coverage. HEAD ONLY (neck + face points; shoulder and arm lines
    made the model draw thick black shoulders), the head placed over the character's neck from the first frame so only
    CHANGES carry over. Drawn OpenPose-style on black and fed as control_video. The reference picture never goes to any
    generator: only the drawn skeleton does.
  * The first 2 frames of each result settle from the still: trim_start_frames=2 is stored for the assembly.

The actor's signature (which person in the reference is the speaker's actor): the owner's marks when there are any (on
the acting analysis' key frames: "this frame shows X's actor"); otherwise automatic: the pose seen most often (head
position and size) across all of that speaker's talking shots, since the reference usually shows the person who talks.
The automatic choice is shown as such and the owner can correct it with one mark.

Cost: GPU price per hour x estimated minutes (about 11 min per 77-frame piece on an L40S / RTX 6000 Ada, scaled by
frames, plus about 10 min of start-up and model download per session). "About" uses the first GPU type, "at most" the
most expensive allowed type plus 25%. The request must carry "at most" (confirm_usd, 409 otherwise); a run that would
pass the monthly GPU cap is refused (409), and the session itself is cap-checked by gpu.py. The job stops before a shot
that would take the run past the confirmed amount.

Nothing is approved by itself: each result waits for the owner's "Approve" click.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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

JOB = "talking_render"
# settings "B" (owner, 2026-11-26)
STEPS, CFG, SAMPLER, SCHEDULER, SHIFT = 20, 4.5, "uni_pc", "simple", 8.0
W, H, FPS, PIECE = 1024, 576, 16, 77
TRIM_START_FRAMES = 2
MIN_COVERAGE = 0.4
# measured 2026-11-26: about 11 min per 77-frame piece including model load (L40S / RTX 6000 Ada); start-up + downloads
MIN_PER_PIECE, SETUP_MIN, POSE_MIN, MAX_MARGIN = 11.0, 10.0, 4.0, 1.25
POLL_S = 10.0

MODELS = [
    {"folder": "diffusion_models", "filename": "wan2.2_s2v_14B_fp8_scaled.safetensors", "type": "diffusion_model", "base": "Wan 2.2",
     "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors"},
    {"folder": "audio_encoders", "filename": "wav2vec2_large_english_fp16.safetensors", "type": "audio_encoder", "base": "Wan 2.2",
     "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors"},
    {"folder": "text_encoders", "filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "text_encoder", "base": "Wan 2.1",
     "url": "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"},
    {"folder": "vae", "filename": "wan_2.1_vae.safetensors", "type": "vae", "base": "Wan 2.1",
     "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"},
]

TEMPLATE_LABEL = "template prompt (GPT unavailable)"
BASE = ("A 2D cartoon stick figure, {who}, speaks. {pron} speaks in a natural way: the small simple mouth opens and closes "
        "softly with each syllable and stays SMALL, never wider than the gap between the eyes. Small natural head "
        "movements, slight eyebrow lifts on stressed words. When the speaking stops the mouth closes and {pron_l} stays "
        "still. Same drawing and line style throughout, flat colours, bold black outlines, static camera.")
HOLDS = " {pron} keeps the same pose and keeps holding anything in the hands the whole time."
NEG = ("teeth, tongue, lips, big mouth, wide open mouth, yawning, nose, realistic, 3D, photo, extra characters, changing face, "
       "changing style, morphing, dropping the paper, extra limbs, camera movement, zoom, blurry, text, subtitles, watermark")


def key(eid: int) -> str:
    return f"talkshots:{eid}"


# ================================================================== pure parts
def frames_for(seconds: float) -> int:
    return max(1, math.ceil(round(seconds * FPS, 6)))


def plen(n: int) -> int:
    """Frames for one piece: Wan needs 4k+1 frames (at least 5)."""
    return 4 * ((max(n, 5) - 1 + 3) // 4) + 1


def pieces(frames: int) -> list[int]:
    """The piece lengths of a shot: the first up to 77 frames, then extensions of up to 77, each 4k+1."""
    first = plen(min(PIECE, frames))
    out, rest = [first], frames - first
    while rest > 0:
        L = plen(min(PIECE, rest))
        out.append(L)
        rest -= L
    return out


def voice_spans(words: list[dict], t0: float, t1: float) -> list[tuple[float, float]]:
    """The kept stretches of the shot's audio (seconds from the shot start): each of the speaker's words, cut to its
    natural length (0.07 s per character + 0.10 s, counted back from the word's end) with 0.05 s of margin."""
    dur = t1 - t0
    keep = []
    for w in words:
        a, b = float(w["start"]) - t0, float(w["end"]) - t0
        if b <= 0 or a >= dur:
            continue
        a = max(a, b - (0.07 * len(str(w.get("word", "")).strip()) + 0.10)) - 0.05
        keep.append((round(max(0.0, a), 3), round(min(dur, b + 0.05), 3)))
    return keep


def gate_filter(spans: list[tuple[float, float]]) -> str:
    """FFmpeg audio filter that mutes everything outside the spans."""
    gate = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in spans) or "0"
    return f"volume=enable='not({gate})':volume=0"


def template_prompt(name: str, look: str, acting_beats: list[dict], pron: str = "They") -> str:
    """The built-in prompt (prep.py's method): BASE + the holding line + "Acting in this shot: ..."."""
    who = f"{name} ({look.strip().rstrip('.')})" if look.strip() else name
    text = BASE.format(who=who, pron=pron, pron_l=pron.lower()) + HOLDS.format(pron=pron)
    act = " Then ".join(", ".join(x for x in (b.get("expression", ""), b.get("eyes_and_gaze", ""), b.get("head_and_body", ""))
                                  if x).strip(", ") for b in acting_beats)
    return text + (f" Acting in this shot: {act}." if act.strip() else "")


def build_graph(prompt: str, negative: str, image: str, audio: str, control: str | None, frames: int, seed: int,
                prefix: str) -> dict:
    """The Speech-to-Video graph with settings B; shots longer than one piece are chained with the official extend
    nodes (WanSoundImageToVideoExtend + KSampler + LatentConcat on "t"), exactly as the verified talk_run.py."""
    lens = pieces(frames)
    g = {"u": {"class_type": "UNETLoader", "inputs": {"unet_name": MODELS[0]["filename"], "weight_dtype": "default"}},
         "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": MODELS[2]["filename"], "type": "wan", "device": "default"}},
         "v": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS[3]["filename"]}},
         "ae": {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": MODELS[1]["filename"]}},
         "au": {"class_type": "LoadAudio", "inputs": {"audio": audio}},
         "im": {"class_type": "LoadImage", "inputs": {"image": image}},
         "ea": {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["ae", 0], "audio": ["au", 0]}},
         "p": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": prompt}},
         "n": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": negative}},
         "ms": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["u", 0], "shift": SHIFT}}}
    common = {"vae": ["v", 0], "audio_encoder_output": ["ea", 0], "ref_image": ["im", 0]}
    if control:
        g["cvl"] = {"class_type": "LoadVideo", "inputs": {"file": control}}
        g["cvc"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["cvl", 0]}}
        common["control_video"] = ["cvc", 0]

    def ks(src: str, sd: int) -> dict:
        return {"class_type": "KSampler", "inputs": {"model": ["ms", 0], "seed": sd, "steps": STEPS, "cfg": CFG,
                                                     "sampler_name": SAMPLER, "scheduler": SCHEDULER, "positive": [src, 0],
                                                     "negative": [src, 1], "latent_image": [src, 2], "denoise": 1.0}}
    g["s0"] = {"class_type": "WanSoundImageToVideo", "inputs": dict(common, positive=["p", 0], negative=["n", 0], width=W,
                                                                    height=H, length=lens[0], batch_size=1)}
    g["k0"] = ks("s0", seed)
    acc = ["k0", 0]
    for j, L in enumerate(lens[1:], 1):
        g[f"e{j}"] = {"class_type": "WanSoundImageToVideoExtend",
                      "inputs": dict(common, positive=["p", 0], negative=["n", 0], length=L, video_latent=acc)}
        g[f"k{j}"] = ks(f"e{j}", seed + j)
        g[f"c{j}"] = {"class_type": "LatentConcat", "inputs": {"samples1": acc, "samples2": [f"k{j}", 0], "dim": "t"}}
        acc = [f"c{j}", 0]
    g["d"] = {"class_type": "VAEDecode", "inputs": {"samples": acc, "vae": ["v", 0]}}
    g["cv"] = {"class_type": "CreateVideo", "inputs": {"images": ["d", 0], "fps": FPS}}
    g["sv"] = {"class_type": "SaveVideo", "inputs": {"video": ["cv", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}}
    return g


def shot_minutes(frames: int) -> float:
    return round(MIN_PER_PIECE * sum(pieces(frames)) / PIECE, 2)


def estimate(frames_list: list[int], prices: list[float], lifetime_min: int, poses: bool) -> dict:
    """GPU minutes and cost of rendering these shots in as few sessions as the maximum session length allows."""
    work = sum(shot_minutes(f) for f in frames_list)
    usable = max(15.0, lifetime_min - SETUP_MIN - 5)
    sessions = max(1, math.ceil(work / usable)) if frames_list else 0
    minutes = round(work + sessions * SETUP_MIN + (POSE_MIN if poses and frames_list else 0), 1)
    p0 = prices[0] if prices else 0.0
    pmax = max(prices) if prices else 0.0
    typ, mx = round(p0 * minutes / 60, 2), round(pmax * minutes * MAX_MARGIN / 60, 2)
    too_long = [f for f in frames_list if shot_minutes(f) > usable]
    return {"minutes": minutes, "sessions": sessions, "usd_typical": typ, "usd_max": mx, "usd_per_hour": p0,
            "usd_per_hour_max": pmax, "too_long": bool(too_long),
            "label": (f"about {minutes:.0f} GPU min: about ${typ:.2f}, at most ${mx:.2f}" if frames_list else "nothing to render")}


# ------------------------------------------------------------------ the actor's pose points (MediaPipe's 33 landmarks)
def _arr(p) -> np.ndarray:
    return np.array(p, dtype=float)[:, :2]


def head_pt(a: np.ndarray) -> np.ndarray:
    return (a[7] + a[8]) / 2            # between the ears


def neck_pt(a: np.ndarray) -> np.ndarray:
    return (a[11] + a[12]) / 2          # between the shoulders


def ear_w(a: np.ndarray) -> float:
    return float(np.linalg.norm(a[7] - a[8]))


def signature_of(frames: list) -> dict | None:
    """{head: [x, y], ear} averaged over frames known to show the actor."""
    A = [_arr(p) for p in frames if p]
    if not A:
        return None
    return {"head": [round(float(v), 2) for v in np.mean([head_pt(a) for a in A], 0)],
            "ear": round(float(np.mean([ear_w(a) for a in A])), 3)}


def is_actor(a: np.ndarray, sig: dict, frame_h: float) -> bool:
    """build_controls.py's test: the head within 45 px of the signature's (at a 640 px high frame, scaled) and the ear
    distance 0.65-1.5 times the signature's."""
    tol = 45.0 * frame_h / 640.0
    e = sig["ear"] or 1e-6
    return float(np.linalg.norm(head_pt(a) - np.array(sig["head"]))) < tol and 0.65 < ear_w(a) / e < 1.5


def auto_signature(frames: list, frame_h: float, min_frames: int = 5) -> dict | None:
    """The pose seen most often: the frame with the most look-alike frames (same test as is_actor), averaged with
    them. None when fewer than min_frames have a pose."""
    A = [_arr(p) for p in frames if p]
    if len(A) < min_frames:
        return None
    heads = np.array([head_pt(a) for a in A])
    ears = np.array([max(ear_w(a), 1e-6) for a in A])
    tol = 45.0 * frame_h / 640.0
    d = np.linalg.norm(heads[:, None, :] - heads[None, :, :], axis=2)
    r = ears[None, :] / ears[:, None]
    near = (d < tol) & (r > 0.65) & (r < 1.5)
    best = int(np.argmax(near.sum(1)))
    members = np.where(near[best])[0]
    return {"head": [round(float(v), 2) for v in heads[members].mean(0)], "ear": round(float(ears[members].mean()), 3),
            "frames": int(len(members)), "of": len(A)}


def coverage(seq: list, sig: dict | None, frame_h: float) -> tuple[float, list[bool]]:
    if not seq or not sig:
        return 0.0, [False] * len(seq or [])
    ok = [p is not None and is_actor(_arr(p), sig, frame_h) for p in seq]
    return round(sum(ok) / len(ok), 3), ok


def fill_gaps(seq: list, ok: list[bool], frames: int) -> list[np.ndarray]:
    """Frames that do not show the actor take his nearest good frame; the list is padded to `frames` with the last."""
    good = [i for i, k in enumerate(ok) if k]
    if not good:
        return []
    A = [_arr(seq[i]) if ok[i] else _arr(seq[min(good, key=lambda g: abs(g - i))]) for i in range(len(seq))]
    while len(A) < frames:
        A.append(A[-1])
    return A[:frames]


# HEAD MOVEMENT ONLY: neck and face lines in the usual pose-guide colours (no shoulders or arms)
HEAD_LIMBS = [("neck", 0, (0, 0, 255)), (0, 5, (170, 0, 255)), (0, 2, (255, 0, 170)), (5, 8, (255, 0, 255)), (2, 7, (85, 0, 255))]
HEAD_POINTS = ("neck", 0, 2, 5, 7, 8)


def guide_points(A: list[np.ndarray], head_xy: tuple[float, float], neck_len: float) -> list[dict]:
    """Per frame, the head-only points lined up with the character: one scale for the clip (the character's
    head-to-neck length over the actor's in the first frame), the actor's head placed on the character's head and his
    neck neck_len below it in the FIRST frame, so a turned head or an off-centre actor at the start is not copied; only
    later changes carry over (build_controls.py)."""
    if not A:
        return []
    hx, hy = head_xy
    d0 = float(np.linalg.norm(neck_pt(A[0]) - head_pt(A[0]))) or 1.0
    sc = neck_len / d0
    face_off = np.array([hx, hy]) - head_pt(A[0]) * sc
    body_off = np.array([hx, hy + neck_len]) - neck_pt(A[0]) * sc
    out = []
    for a in A:
        q = {k: a[k] * sc + face_off for k in (0, 2, 5, 7, 8)}
        q["neck"] = neck_pt(a) * sc + body_off
        out.append({k: (round(float(v[0]), 1), round(float(v[1]), 1)) for k, v in q.items()})
    return out


def draw_guide(points: list[dict], folder: Path) -> list[Path]:
    """OpenPose-style frames on black, 1024x576 (PIL)."""
    from PIL import Image, ImageDraw
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for i, q in enumerate(points):
        im = Image.new("RGB", (W, H), "black")
        dr = ImageDraw.Draw(im)
        for f, t, c in HEAD_LIMBS:
            dr.line([q[f], q[t]], fill=c, width=6)
        for k in HEAD_POINTS:
            x, y = q[k]
            dr.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(255, 255, 255))
        p = folder / f"{i:04d}.png"
        im.save(p)
        files.append(p)
    return files


# ------------------------------------------------------------------ the character's head in a still
def fit_still(src: Path, dst: Path) -> Path:
    """The still as the model sees it: cover-fitted to 1024x576 (centre crop), PNG."""
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        ImageOps.fit(im.convert("RGB"), (W, H), method=Image.LANCZOS).save(dst)
    return dst


def detect_head(img_path: Path) -> dict | None:
    """The character's head in a 1024x576 still: the white, round, compact region nearest the top centre (stick
    heads are plain white circles). Returns {x, y, r, neck} in still pixels (neck: head-centre-to-neck length,
    about the head radius), or None when nothing head-like is found. The owner can click the head instead."""
    from PIL import Image
    s = 4                                                         # work at a quarter size: 256x144
    with Image.open(img_path) as im:
        a = np.asarray(im.convert("RGB").resize((W // s, H // s)), dtype=np.int16)
    white = (a.min(axis=2) > 200) & (a.max(axis=2) - a.min(axis=2) < 30)
    h, w = white.shape
    # the face's lines (eyes, glasses, mouth) cut the white head into pieces: grow the white by 2 px (8 px in the still)
    # so thin dark lines are bridged, then judge each grown region by its own white pixels
    grown = white.copy()
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            grown[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] |= white[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)]
    seen = np.zeros_like(grown, dtype=bool)
    best, best_score = None, 0.0
    for y0 in range(h):
        for x0 in range(w):
            if not grown[y0, x0] or seen[y0, x0]:
                continue
            stack, pix = [(y0, x0)], []
            seen[y0, x0] = True
            while stack:                                          # flood fill one grown region
                y, x = stack.pop()
                if white[y, x]:
                    pix.append((y, x))
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < h and 0 <= xx < w and grown[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            if len(pix) < 60:
                continue
            ys, xs = np.array([p[0] for p in pix]), np.array([p[1] for p in pix])
            bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
            aspect = min(bw, bh) / max(bw, bh)
            fill = len(pix) / float(bw * bh)                      # a plain disc fills 0.79 of its box; a face less
            if aspect < 0.75 or not 0.4 < fill < 0.9 or bw > w * 0.5:
                continue
            cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
            central = 1.0 - min(1.0, abs(cx - w / 2) / (w / 2))
            high = 1.0 - min(1.0, cy / h)
            score = len(pix) * aspect * (1 - abs(fill - 0.785)) * (0.5 + central) * (0.5 + high)
            if score > best_score:
                # the radius from the height: hair tufts at the sides widen the box, nothing sits above or below
                best, best_score = (float(cx), float(cy), float(bh) / 2), score
    if best is None:
        return None
    cx, cy, r = best
    return {"x": round(cx * s + s / 2, 1), "y": round(cy * s + s / 2, 1), "r": round(r * s, 1), "neck": round(r * s, 1)}


# ================================================================== episode data
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


def _shot_state(v: dict, idx: int) -> dict:
    return v.setdefault("shots", {}).setdefault(str(idx), {})


def talking_rows(db: Session, ep: Episode) -> list[dict]:
    """The talking shots of the storyboard: [{index, t0, t1, frames, speaker, name, look, text, words, still,
    approved_still}] (words: the speaker's words over the shot, absolute times)."""
    from . import shot_frames as SF
    from .stick_shots import spoken_in
    v = SF.migrated(SF.stored(db, ep.id))
    tr = ep.audio_transcript or {}
    lines = tr.get("lines") or []
    pm = tr.get("person_map") or {}
    chars = {c.key: c for c in db.query(Character)}
    who = lambda ln: pm.get(ln.get("speaker")) or ln.get("character") or ln.get("speaker") or ""   # noqa: E731
    out = []
    for s in v.get("shots") or []:
        over = spoken_in(s, lines)
        people = s.get("people") or []
        speaker = s.get("speaker") or (who(over[0]) if over else "")
        if not (s.get("kind") == "talk" or (speaker and speaker in people)):
            continue
        if not speaker and people:
            speaker = people[0]
        mine = [ln for ln in over if who(ln) == speaker]
        if not mine and over and not any(ln.get("speaker") for ln in over):
            mine = over          # no speaker labels at all: every word over the shot counts (prep.py's method)
        t0, t1 = float(s["t0"]), float(s["t1"])
        words = [w for ln in mine for w in ln.get("words") or [] if float(w["end"]) > t0 and float(w["start"]) < t1]
        c = chars.get(speaker)
        out.append({"index": int(s["index"]), "t0": t0, "t1": t1, "frames": frames_for(t1 - t0), "speaker": speaker,
                    "name": c.name if c else (speaker or "the speaker"), "look": (c.visual_description or "") if c else "",
                    "text": " ".join((ln.get("text") or "").strip() for ln in mine).strip(),
                    "words": words, "still": s.get("chosen"), "approved_still": bool(s.get("approved") and s.get("chosen"))})
    return out


def acting_beats(db: Session, eid: int, idx: int, name: str) -> list[dict]:
    from . import acting_analysis as AA
    res = AA.stored(db, eid).get("result") or {}
    shot = next((x for x in res.get("shots") or [] if x.get("shot") == idx), None)
    return [b for b in (shot or {}).get("beats") or [] if (b.get("character") or "").lower() == name.lower()]


def current_prompt(db: Session, ep: Episode, row: dict, st: dict) -> dict:
    p = st.get("prompt")
    if p and p.get("text"):
        return p
    text = template_prompt(row["name"], row["look"], acting_beats(db, ep.id, row["index"], row["name"]))
    label = TEMPLATE_LABEL if not secret("openai_api_key", db) else "template prompt (not written by GPT yet)"
    return {"text": text, "source": "template", "label": label}


def _prompt_message(db: Session, ep: Episode, row: dict) -> str:
    from . import acting_analysis as AA
    from . import prompt_writer as PW
    notes = (f"{row['name']} says: \"{row['text'][:400]}\". Shot length {row['t1'] - row['t0']:.1f} s. "
             "Write the positive prompt only (a separate negative prompt already forbids teeth, tongue, lips and a big mouth).")
    acting = PW.acting_for_shot(AA.stored(db, ep.id).get("result"), row["index"], row["name"])
    look = f"{row['name']}. {row['look']}".strip()
    return PW.user_message("talking", get_section(db, "stick").get("style_prompt") or "", look, notes, acting)


def _poses(db: Session, eid: int) -> dict:
    k = stored(db, eid).get("poses_key")
    if not k:
        return {}
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        try:
            p = storage().get_to_file(k, Path(d) / "poses.json")
            return json.loads(p.read_text())
        except (OSError, ValueError, FileNotFoundError):
            return {}


def window_name(row: dict) -> str:
    return f"s{row['index']}-{row['t0']:.2f}-{row['frames']}"


def mark_window(t: float) -> str:
    return f"m-{t:.2f}"


def signature_for(v: dict, poses: dict, rows: list[dict], speaker: str) -> tuple[dict | None, str]:
    """(signature, how it was chosen) for one speaker's actor."""
    marks = [mark_window(t) for t in (v.get("actors", {}).get(speaker) or {}).get("times") or []]
    got = [poses[m]["seq"][0] for m in marks if m in poses and poses[m].get("seq") and poses[m]["seq"][0]]
    if got:
        sig = signature_of(got)
        return sig, f"from your {len(got)} marked frame(s)"
    seq, fh = [], 640.0
    for r in rows:
        w = poses.get(window_name(r))
        if r["speaker"] == speaker and w:
            seq += w.get("seq") or []
            fh = float((w.get("size") or [0, 640])[1] or 640)
    sig = auto_signature(seq, fh)
    if sig:
        return sig, f"automatic: the person seen most while this character speaks ({sig['frames']} of {sig['of']} frames)"
    return None, ""


def guide_status(v: dict, poses: dict, rows: list[dict], row: dict, ref: bool) -> dict:
    st = (v.get("shots") or {}).get(str(row["index"])) or {}
    on = st.get("guide", True)
    if not on:
        return {"on": False, "state": "off", "text": "movement guide off for this shot"}
    if not ref:
        return {"on": True, "state": "no_reference", "text": "no guide: upload the reference video in step 1"}
    w = poses.get(window_name(row))
    if not w:
        return {"on": True, "state": "not_read", "text": "the actor's movement is read on the GPU at the start of the render"}
    sig, how = signature_for(v, poses, rows, row["speaker"])
    fh = float((w.get("size") or [0, 640])[1] or 640)
    share, _ok = coverage(w.get("seq") or [], sig, fh)
    if share < MIN_COVERAGE:
        return {"on": True, "state": "low", "coverage": share, "signature": how,
                "text": f"no guide: someone else is on screen (the actor is seen {share:.0%} of the shot)"}
    return {"on": True, "state": "ok", "coverage": share, "signature": how,
            "text": f"follows the actor {share:.0%} of the shot"}


def voice_preview(db: Session, ep: Episode, row: dict, v: dict) -> str | None:
    """The voice-only audio of a shot for the owner to hear (made once with FFmpeg, free); None without FFmpeg."""
    from .config import get_settings
    spans = voice_spans(row["words"], row["t0"], row["t1"])
    if not spans or not ep.audio_asset_id or not get_settings().ffmpeg:
        return None
    h = hashlib.sha256(json.dumps([ep.audio_asset_id, row["t0"], row["t1"], spans]).encode()).hexdigest()[:12]
    vk = f"episodes/{ep.id}/talking/shot{row['index']:02d}-voice-{h}.wav"
    have = (v.get("voice") or {}).get(str(row["index"]))
    if have == vk:
        return storage().url(vk)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        try:
            make_voice(ep, row, Path(d) / "voice.wav", Path(d))
            storage().put_file(vk, Path(d) / "voice.wav", "audio/wav")
        except Exception:   # noqa: BLE001 -- a preview is optional; the render makes its own copy
            return None
    v.setdefault("voice", {})[str(row["index"])] = vk
    v["_dirty"] = True
    return storage().url(vk)


def make_voice(ep: Episode, row: dict, dst: Path, tmp: Path) -> Path:
    """The voice-only copy of the shot: mono 16 kHz WAV of the episode recording's slice, muted outside the spans."""
    from .config import get_settings
    a = ep.audio_asset_id and _asset(ep, ep.audio_asset_id)
    if not a:
        raise ValueError("the episode has no voice recording")
    src = storage().get_to_file(a.storage_key, tmp / f"episode-audio{Path(a.storage_key).suffix or '.wav'}")
    spans = voice_spans(row["words"], row["t0"], row["t1"])
    r = subprocess.run([get_settings().ffmpeg, "-v", "error", "-y", "-ss", f"{row['t0']:.3f}", "-t", f"{row['t1'] - row['t0']:.3f}",
                        "-i", str(src), "-ac", "1", "-ar", "16000", "-af", gate_filter(spans), str(dst)],
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not dst.exists():
        raise ValueError(f"the voice-only audio could not be made: {(r.stderr or '')[-200:]}")
    return dst


def _asset(ep_or_db, aid: int):
    from sqlalchemy.orm import object_session
    db = object_session(ep_or_db) if isinstance(ep_or_db, Episode) else ep_or_db
    return db.get(Asset, aid) if aid else None


def head_for(db: Session, v: dict, asset_id: int | None) -> dict | None:
    """The character's head in this still: the owner's click, else detected once and kept."""
    if not asset_id:
        return None
    heads = v.setdefault("heads", {})
    if str(asset_id) in heads:
        return heads[str(asset_id)]
    a = db.get(Asset, asset_id)
    if not a:
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        try:
            src = storage().get_to_file(a.storage_key, Path(d) / f"still{Path(a.storage_key).suffix or '.png'}")
            found = detect_head(fit_still(src, Path(d) / "fit.png"))
        except Exception:   # noqa: BLE001 -- unreadable still: the owner clicks the head instead
            found = None
    heads[str(asset_id)] = ({**found, "source": "auto"} if found else {"source": "none"})
    v["_dirty"] = True
    return heads[str(asset_id)]


# ================================================================== view
def config(db: Session) -> dict:
    return get_section(db, "gpu")


def _prices(db: Session) -> list[float]:
    """The allowed GPU types' list prices, in preference order (no network call: estimates are shown on every page
    load; the launch uses RunPod's live price, and the run stops at the confirmed amount)."""
    from . import comfy_session as CS
    return CS.list_prices(config(db))


def needs_poses(v: dict, poses: dict, rows: list[dict], ref: bool) -> bool:
    if not ref:
        return False
    marks = [mark_window(t) for a in (v.get("actors") or {}).values() for t in a.get("times") or []]
    return any((v.get("shots") or {}).get(str(r["index"]), {}).get("guide", True) and window_name(r) not in poses
               for r in rows) or any(m not in poses for m in marks)


def _active(db: Session, eid: int):
    return db.query(Job).filter(Job.kind == JOB, Job.episode_id == eid, Job.status.in_(("queued", "running")))


def renders_out(db: Session, renders: list[dict]) -> list[dict]:
    ids = [r["asset_id"] for r in renders if r.get("asset_id")]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}
    out = []
    for r in renders:
        a = assets.get(r.get("asset_id"))
        out.append({**r, "url": storage().url(a.storage_key) if a else None,
                    "preview_url": storage().url(r["preview_key"]) if r.get("preview_key") else None})
    return out


def view(db: Session, ep: Episode, light: bool = False) -> dict:
    from . import acting_analysis as AA
    from . import comfy_session as CS
    from . import guided
    from . import prompt_writer as PW
    v = stored(db, ep.id)
    rows = talking_rows(db, ep)
    ref = guided.reference_video(db, ep.id) is not None
    poses = _poses(db, ep.id) if not light else {}
    c = config(db)
    prices = _prices(db)
    frames_out = AA.frames_out(AA.stored(db, ep.id)) if not light else {}
    pcfg = PW.config(db)
    still_ids = [r["still"] for r in rows if r["still"]]
    stills = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(still_ids))} if still_ids else {}
    out = []
    for r in rows:
        st = (v.get("shots") or {}).get(str(r["index"])) or {}
        spans = voice_spans(r["words"], r["t0"], r["t1"])
        blocked = ("approve this shot's still first" if not r["approved_still"] else
                   "no words of the speaker over this shot in the transcript" if not spans else "")
        row = {"index": r["index"], "t0": r["t0"], "t1": r["t1"], "frames": r["frames"], "pieces": pieces(r["frames"]),
               "speaker": r["speaker"], "name": r["name"], "text": r["text"], "blocked": blocked,
               "voice_spans": spans, "still": None, "approved": st.get("approved"),
               "run": st.get("run"), "renders": renders_out(db, st.get("renders") or []),
               "estimate": estimate([r["frames"]], prices, int(c["max_lifetime_minutes"]), False)}
        if light:
            out.append(row)
            continue
        a = stills.get(r["still"])
        row["still"] = {"asset_id": r["still"], "url": storage().url(a.storage_key) if a else None,
                        "approved": r["approved_still"], "head": head_for(db, v, r["still"])}
        row["voice_url"] = voice_preview(db, ep, r, v)
        row["prompt"] = current_prompt(db, ep, r, st)
        row["prompt_estimate"] = PW.estimate(pcfg, PW.SYSTEM, _prompt_message(db, ep, r))
        row["guide"] = guide_status(v, poses, rows, r, ref)
        row["ref_frames"] = frames_out.get(str(r["index"]), [])
        row["actor_marks"] = (v.get("actors", {}).get(r["speaker"]) or {}).get("times") or []
        out.append(row)
    if v.pop("_dirty", False):
        save(db, ep.id, v)
        db.commit()
    todo = [x for x in out if not x["blocked"]]
    total = estimate([x["frames"] for x in todo], prices, int(c["max_lifetime_minutes"]),
                     needs_poses(v, poses, [r for r in rows if r["index"] in {x["index"] for x in todo}], ref) if not light else False)
    job = db.query(Job).filter_by(kind=JOB, episode_id=ep.id).order_by(Job.id.desc()).first()
    return {"shots": out, "total": total, "availability": CS.availability(db) if not light else None,
            "busy": _active(db, ep.id).first() is not None, "job": S.job(job) if job else None,
            "reference_video": ref, "openai_key": bool(secret("openai_api_key", db)),
            "settings": {"steps": STEPS, "cfg": CFG, "sampler": SAMPLER, "scheduler": SCHEDULER, "shift": SHIFT,
                         "size": [W, H], "fps": FPS, "piece_frames": PIECE, "trim_start_frames": TRIM_START_FRAMES}}


def summary(db: Session, ep: Episode) -> dict:
    """For the guide's step list: status, cost and where things are (no file work)."""
    vw = view(db, ep, light=True)
    shots = vw["shots"]
    approved = [s for s in shots if s.get("approved")]
    rendered = [s for s in shots if s["renders"]]
    status = ("running" if vw["busy"] else "done" if shots and len(approved) == len(shots) else
              "needs_approval" if len(rendered) > len(approved) else "not_started")
    detail = (f"{len(approved)} of {len(shots)} talking shots approved" if shots else "no talking shots in the storyboard yet")
    return {"status": status, "cost": vw["total"] if shots else None, "detail": detail}


# ================================================================== routes
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _row_or_404(db: Session, ep: Episode, idx: int) -> dict:
    r = next((x for x in talking_rows(db, ep) if x["index"] == idx), None)
    if r is None:
        raise HTTPException(404, f"shot {idx} is not a talking shot")
    return r


@router.get("/episodes/{eid}/talking")
def get_talking(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class HeadIn(BaseModel):
    x: float = Field(ge=0, le=W)
    y: float = Field(ge=0, le=H)


class EditIn(BaseModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    guide: bool | None = None
    head: HeadIn | None = None


@router.put("/episodes/{eid}/talking/{idx}")
def edit_shot(eid: int, idx: int, body: EditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's free edits: the prompt text, the movement guide on/off, the character's head in the still."""
    ep = _episode(db, eid)
    r = _row_or_404(db, ep, idx)
    v = stored(db, eid)
    st = _shot_state(v, idx)
    if body.prompt is not None:
        old = st.get("prompt") or current_prompt(db, ep, r, st)
        st["prompt"] = {**old, "text": body.prompt, "edited": True, "edited_by": user, "at": time.time()}
    if body.guide is not None:
        st["guide"] = body.guide
    if body.head is not None:
        if not r["still"]:
            raise HTTPException(409, "this shot has no still yet")
        before = (v.get("heads") or {}).get(str(r["still"])) or {}
        neck = before.get("neck") or 78.0
        v.setdefault("heads", {})[str(r["still"])] = {"x": body.head.x, "y": body.head.y, "neck": neck, "r": before.get("r"),
                                                     "source": "owner"}
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class WriteIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


@router.post("/episodes/{eid}/talking/{idx}/write-prompt")
def write_prompt(eid: int, idx: int, body: WriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one GPT call, cost confirmed first). Without an OpenAI key or credit the built-in template is kept,
    labelled "template prompt (GPT unavailable)"."""
    from . import prompt_writer as PW
    ep = _episode(db, eid)
    r = _row_or_404(db, ep, idx)
    cfg = PW.config(db)
    message = _prompt_message(db, ep, r)
    est = PW.estimate(cfg, PW.SYSTEM, message)
    v = stored(db, eid)
    st = _shot_state(v, idx)
    template = {"text": template_prompt(r["name"], r["look"], acting_beats(db, eid, idx, r["name"])), "source": "template",
                "label": TEMPLATE_LABEL, "at": time.time()}
    api_key = secret("openai_api_key", db)
    if not api_key:
        st["prompt"] = template
    else:
        if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
            raise HTTPException(409, f"writing this prompt can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
        try:
            out = PW.call_openai(api_key, cfg["prompt_model"], PW.SYSTEM, message, int(cfg["prompt_max_tokens"]))
        except HTTPException as e:
            if e.status_code != 402:
                raise
            out = None
        if out and out["text"]:
            usd = PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg)
            st["prompt"] = {"text": out["text"], "source": "gpt", "label": f"written by {cfg['prompt_model']}", "usd": usd,
                            "at": time.time(), "by": user}
            v["usd_prompts"] = round((v.get("usd_prompts") or 0.0) + usd, 6)
            db.add(Event(episode_id=eid, kind="episode", message=f"Talking shot {idx}: prompt written by {cfg['prompt_model']} (${usd:.4f})"))
        else:
            st["prompt"] = template
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class ActorIn(BaseModel):
    character: str = Field(min_length=1, max_length=80)
    t: float | None = Field(default=None, ge=0, le=36000)
    clear: bool = False


@router.post("/episodes/{eid}/talking/actor")
def mark_actor(eid: int, body: ActorIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner marks a reference frame (a key frame of the acting analysis) as showing this character's actor; the
    marks replace the automatic signature. clear=true removes the marks."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    a = v.setdefault("actors", {}).setdefault(body.character, {"times": []})
    if body.clear:
        a["times"] = []
    elif body.t is not None and round(body.t, 2) not in a["times"]:
        a["times"] = (a["times"] + [round(body.t, 2)])[-8:]
    a["by"] = user
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class ApproveIn(BaseModel):
    render_id: str | None = None


@router.post("/episodes/{eid}/talking/{idx}/approve")
def approve(eid: int, idx: int, body: ApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: this result is the shot. render_id null withdraws the approval."""
    ep = _episode(db, eid)
    _row_or_404(db, ep, idx)
    v = stored(db, eid)
    st = _shot_state(v, idx)
    if body.render_id is not None and not any(r["id"] == body.render_id for r in st.get("renders") or []):
        raise HTTPException(404, "no such result for this shot")
    st["approved"], st["approved_by"] = body.render_id, (user if body.render_id else None)
    save(db, eid, v)
    db.add(Event(episode_id=eid, kind="approval", message=(f"Talking shot {idx} approved by {user}" if body.render_id
                                                           else f"Talking shot {idx}: approval withdrawn by {user}")))
    db.commit()
    return view(db, ep)


class RenderIn(BaseModel):
    shots: list[int] | None = Field(default=None, max_length=200)
    confirm_usd: float | None = Field(default=None, ge=0, le=500)


@router.post("/episodes/{eid}/talking/render")
def render(eid: int, body: RenderIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: render these talking shots (all renderable ones when `shots` is empty) on a rented GPU. Starts only with
    the most it can cost confirmed, within the monthly GPU cap, and when no render is running."""
    from . import comfy_session as CS
    from . import gpu
    ep = _episode(db, eid)
    rows = {r["index"]: r for r in talking_rows(db, ep)}
    want = body.shots or [i for i, r in rows.items() if r["approved_still"] and voice_spans(r["words"], r["t0"], r["t1"])]
    if not want:
        raise HTTPException(409, "no talking shot can be rendered yet: approve the stills first")
    problems = []
    for i in want:
        r = rows.get(i)
        if r is None:
            problems.append(f"shot {i} is not a talking shot")
        elif not r["approved_still"]:
            problems.append(f"shot {i}: approve its still first")
        elif not voice_spans(r["words"], r["t0"], r["t1"]):
            problems.append(f"shot {i}: the transcript has no words of the speaker over it")
    if problems:
        raise HTTPException(409, "; ".join(problems))
    a = CS.availability(db)
    if not a["ok"]:
        raise HTTPException(409, a["reason"])
    if _active(db, eid).first():
        raise HTTPException(409, "a talking-shot render is already running for this episode")
    c = config(db)
    sel = [rows[i] for i in want]
    est = render_estimate(db, eid, sel, stored(db, eid))
    if est["too_long"]:
        raise HTTPException(409, "a shot is too long for the maximum GPU session length: raise it in Settings > GPU worker")
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"rendering {len(sel)} talking shot(s) can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    fig = gpu.month_figures(db)
    if fig["committed_usd"] + est["usd_max"] > float(c["monthly_cap_usd"]) + 1e-9:
        raise HTTPException(409, f"Paused: this render (up to ${est['usd_max']:.2f}) would pass the monthly GPU cap "
                                 f"(${fig['committed_usd']:.2f} committed of ${float(c['monthly_cap_usd']):.2f}). Raise the cap or wait for next month")
    job = enqueue(db, JOB, episode_id=eid, payload={"shots": want, "confirm_usd": float(body.confirm_usd), "estimate": est,
                                                    "by": user, "backend": "gpu"})
    v = stored(db, eid)
    for i in want:
        _shot_state(v, i)["run"] = {"status": "queued", "job_id": job.id, "at": time.time()}
    save(db, eid, v)
    db.add(Event(episode_id=eid, kind="episode", message=f"Talking shots {', '.join(map(str, want))}: render asked by {user} (up to ${est['usd_max']:.2f})"))
    db.commit()
    return S.job(job)


def render_estimate(db: Session, eid: int, sel: list[dict], v: dict) -> dict:
    """What rendering these rows costs with the shot settings in `v` (the render route and the chat's Apply price)."""
    from . import guided
    ref = guided.reference_video(db, eid) is not None
    return estimate([r["frames"] for r in sel], _prices(db), int(config(db)["max_lifetime_minutes"]),
                    needs_poses(v, _poses(db, eid), sel, ref))


# ------------------------------------------------------------------ the chat under each talking shot (shot_chat.py)
def chat_context(db: Session, ep: Episode, idx: int) -> dict:
    """What the assistant is told about one talking shot: its line, current prompt and settings (no keys, no pictures)."""
    r = next((x for x in talking_rows(db, ep) if x["index"] == idx), None)
    if r is None:
        raise HTTPException(404, f"shot {idx} is not a talking shot")
    v = stored(db, ep.id)
    st = (v.get("shots") or {}).get(str(idx)) or {}
    p = current_prompt(db, ep, r, st)
    renders = st.get("renders") or []
    return {"current_prompt": p["text"], "line": f"{r['name']} says: \"{r['text']}\"",
            "settings": {"model": "Wan 2.2 Speech-to-Video, settings B (20 steps, CFG 4.5, fixed by the owner)",
                         "prompt_source": p.get("label"), "negative_prompt": NEG, "frames": r["frames"],
                         "pieces": pieces(r["frames"]), "movement_guide_on": st.get("guide", True),
                         "results": len(renders), "approved": bool(st.get("approved")),
                         "still_approved": r["approved_still"]}}


def chat_render_cost(db: Session, eid: int, idx: int, use_guide: bool | None) -> dict:
    """The price shown on the chat's Apply: "at most" for this one shot, with the proposed guide choice."""
    ep = _episode(db, eid)
    r = _row_or_404(db, ep, idx)
    v = stored(db, eid)
    if use_guide is not None:
        _shot_state(v, idx)["guide"] = use_guide
    e = render_estimate(db, eid, [r], v)
    return {"usd": e["usd_max"], "label": f"up to ${e['usd_max']:.2f} on a rented GPU ({e['label']})"}


def rerender_from_chat(db: Session, eid: int, idx: int, prompt: str | None, use_guide: bool | None,
                       confirm_usd: float | None, user: str) -> dict:
    """The chat's Apply: the proposed prompt / guide choice, then the render route with ALL its checks (confirm_usd,
    the cap, the GPU mode, a render already running). If the render is refused nothing is kept: the edits are rolled
    back with it, so a refused Apply changes nothing."""
    ep = _episode(db, eid)
    r = _row_or_404(db, ep, idx)
    v = stored(db, eid)
    st = _shot_state(v, idx)
    if prompt is not None:
        old = st.get("prompt") or current_prompt(db, ep, r, st)
        st["prompt"] = {**old, "text": prompt, "edited": True, "edited_by": f"{user} (from the chat)", "at": time.time()}
    if use_guide is not None:
        st["guide"] = use_guide
    save(db, eid, v)          # not committed: render() commits it together with the job, or it is rolled back
    try:
        return render(eid, RenderIn(shots=[idx], confirm_usd=confirm_usd), db, user)
    except HTTPException:
        db.rollback()
        raise


@router.post("/episodes/{eid}/talking/stop")
def stop(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Terminate the rented GPU now; a shot still rendering fails and can be rendered again."""
    from . import comfy_session as CS
    _episode(db, eid)
    try:
        done = CS.stop(db, f"stopped by {user}")
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f"RunPod could not be reached; the session is still open: {str(e)[:200]}")
    return {"terminated": done}


# ================================================================== the job
from .tasks import Ctx, task  # noqa: E402


def _set_run(db: Session, eid: int, idx: int, **run) -> None:
    db.expire_all()
    v = stored(db, eid)
    st = _shot_state(v, idx)
    st["run"] = {**(st.get("run") or {}), **run}
    save(db, eid, v)
    db.commit()


def _merge_poses(db: Session, eid: int, new: dict, folder: Path) -> dict:
    allp = _poses(db, eid)
    allp.update(new)
    f = folder / "poses.json"
    f.write_text(json.dumps(allp))
    k = f"private/episodes/{eid}/talking/poses-{uuid.uuid4().hex[:8]}.json"
    storage().put_file(k, f, "application/json")
    v = stored(db, eid)
    old = v.get("poses_key")
    v["poses_key"] = k
    save(db, eid, v)
    db.commit()
    if old and old != k:
        storage().delete(old)
    return allp


def _read_poses(ctx: Ctx, ep: Episode, sess: dict, rows: list[dict], v: dict, folder: Path) -> dict:
    """Missing pose windows (talking shots with the guide on, and the owner's marked frames) read on the session."""
    from . import comfy_session as CS
    from . import gpu
    from . import guided
    from . import pose_remote as PR
    from .config import get_settings
    poses = _poses(ctx.db, ep.id)
    ref = guided.reference_video(ctx.db, ep.id)
    if not ref:
        return poses
    windows = {window_name(r): (r["t0"], r["frames"]) for r in rows
               if (v.get("shots") or {}).get(str(r["index"]), {}).get("guide", True) and window_name(r) not in poses}
    for a in (v.get("actors") or {}).values():
        for t in a.get("times") or []:
            if mark_window(t) not in poses:
                windows[mark_window(t)] = (t, 1)
    if not windows:
        return poses
    if not get_settings().ffmpeg:
        ctx.log("FFmpeg is not configured: no movement guides")
        return poses
    led = gpu.ledger(ctx.db)["sessions"][sess["session"]]
    ep_ = CS.ssh_endpoint(sess["pod_id"])
    if not ep_:
        ctx.log("The GPU's SSH port is not published: no movement guides this time")
        return poses
    pf = folder / "pose"
    pf.mkdir(parents=True, exist_ok=True)
    try:
        video = storage().get_to_file(ref["key"], pf / f"reference{Path(ref['key']).suffix or '.mp4'}")
        tar = PR.extract_frames(get_settings().ffmpeg, video, windows, pf)
        got = PR.read_poses(ep_[0], ep_[1], CS.ssh_key(led), tar, ctx.log)
    finally:
        shutil.rmtree(pf, ignore_errors=True)      # the reference frames never stay on disk
    return _merge_poses(ctx.db, ep.id, {k: got[k] for k in windows if k in got}, folder)


def _build_guide(v: dict, poses: dict, rows: list[dict], row: dict, head: dict | None, folder: Path) -> tuple[Path | None, dict]:
    from .config import get_settings
    info = {"used": False}
    if not (v.get("shots") or {}).get(str(row["index"]), {}).get("guide", True):
        return None, {**info, "why": "off"}
    w = poses.get(window_name(row))
    if not w:
        return None, {**info, "why": "the actor's movement could not be read"}
    if not head or head.get("x") is None:
        return None, {**info, "why": "the character's head is not set on the still"}
    sig, how = signature_for(v, poses, rows, row["speaker"])
    fh = float((w.get("size") or [0, 640])[1] or 640)
    share, ok = coverage(w.get("seq") or [], sig, fh)
    info.update(coverage=share, signature=how)
    if share < MIN_COVERAGE:
        return None, {**info, "why": "someone else is on screen"}
    A = fill_gaps(w["seq"], ok, row["frames"])
    pts = guide_points(A, (float(head["x"]), float(head["y"])), float(head.get("neck") or 78.0))
    d = folder / f"guide{row['index']:02d}"
    draw_guide(pts, d)
    out = folder / f"shot{row['index']:02d}-pose.mp4"
    r = subprocess.run([get_settings().ffmpeg, "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(d / "%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], capture_output=True, text=True, timeout=300,
                       stdin=subprocess.DEVNULL)
    shutil.rmtree(d, ignore_errors=True)
    if r.returncode != 0:
        return None, {**info, "why": "the guide video could not be made"}
    return out, {**info, "used": True}


def _mux_preview(ep: Episode, row: dict, video: Path, dst: Path, tmp: Path) -> Path | None:
    """A review copy with the ORIGINAL audio of the shot under it (the result itself stays silent for assembly)."""
    from .config import get_settings
    a = _asset(ep, ep.audio_asset_id) if ep.audio_asset_id else None
    if not a or not get_settings().ffmpeg:
        return None
    src = storage().get_to_file(a.storage_key, tmp / f"episode-audio{Path(a.storage_key).suffix or '.wav'}")
    r = subprocess.run([get_settings().ffmpeg, "-v", "error", "-y", "-i", str(video), "-ss", f"{row['t0']:.3f}",
                        "-t", f"{row['t1'] - row['t0']:.3f}", "-i", str(src), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-shortest", str(dst)], capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    return dst if r.returncode == 0 and dst.exists() else None


@task
def talking_render(ctx: Ctx) -> dict:
    from . import comfy_session as CS
    from . import gpu
    from .comfy import ComfyError, video_outputs
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    want = list(p.get("shots") or [])
    confirm = float(p.get("confirm_usd") or 0)
    rows_all = talking_rows(db, ep)
    rows = {r["index"]: r for r in rows_all}
    folder = ctx.folder("episodes", ep.id, f"talking-job{job.id}")
    t_start = gpu.clock()
    used: dict[str, float] = {}           # session id -> when this job started using it
    done, failed, skipped = [], [], []

    def spent() -> float:
        led = gpu.ledger(db)["sessions"]
        tot = 0.0
        for sid, since in used.items():
            s = led.get(sid) or {}
            end = s.get("ended_at") or gpu.clock()
            tot += float(s.get("price_per_hour") or 0) * max(0.0, end - max(since, s.get("launched_at", since))) / 3600
        return tot

    def stage(text: str) -> None:
        ctx.log(text)
        for i in want:
            if i not in done and i not in failed and i not in skipped:
                _set_run(db, ep.id, i, stage=text)

    def session() -> dict:
        s = CS.launch(db, stage)
        used.setdefault(s["session"], max(t_start, s["launched_at"]))
        return s

    sess = None
    try:
        # inputs, made on the studio server (free)
        v = stored(db, ep.id)
        inputs = {}
        for i in want:
            r = rows.get(i)
            if r is None or not r["approved_still"]:
                _set_run(db, ep.id, i, status="failed", error="not a talking shot with an approved still")
                failed.append(i)
                continue
            d = folder / f"shot{i:02d}"
            d.mkdir(parents=True, exist_ok=True)
            a = db.get(Asset, r["still"])
            src = storage().get_to_file(a.storage_key, d / f"still-src{Path(a.storage_key).suffix or '.png'}")
            still = fit_still(src, d / f"ep{ep.id}-shot{i:02d}-still.png")
            voice = make_voice(ep, r, d / f"ep{ep.id}-shot{i:02d}-voice.wav", d)
            st = (v.get("shots") or {}).get(str(i)) or {}
            prompt = current_prompt(db, ep, r, st)
            inputs[i] = {"still": still, "voice": voice, "prompt": prompt, "head": head_for(db, v, r["still"])}
        if v.pop("_dirty", False):
            save(db, ep.id, v)
            db.commit()
        todo = [i for i in want if i in inputs]
        if not todo:
            raise ValueError("nothing to render")
        stage("Starting the rented GPU")
        sess = session()
        # the actor's movement (pose points on the GPU, guides drawn here)
        poses = {}
        try:
            poses = _read_poses(ctx, ep, sess, [rows[i] for i in todo], v, folder)
        except Exception as e:   # noqa: BLE001 -- the shots still render, without a guide
            ctx.log(f"The actor's movement could not be read ({str(e)[:200]}): rendering without movement guides")
            poses = _poses(db, ep.id)
        v = stored(db, ep.id)
        for i in todo:
            ctl, info = _build_guide(v, poses, rows_all, rows[i], inputs[i]["head"], folder)
            inputs[i]["control"], inputs[i]["guide"] = ctl, info
        stage("Getting the models ready on the GPU")
        CS.ensure_models(db, sess, MODELS, stage)
        c = config(db)
        for i in todo:
            r, inp = rows[i], inputs[i]
            mins = shot_minutes(r["frames"])
            price = float(sess["price_per_hour"])
            if spent() + price * mins / 60 > confirm + 1e-9:
                _set_run(db, ep.id, i, status="skipped", error=f"not started: it would pass the confirmed ${confirm:.2f}")
                skipped.append(i)
                continue
            left = int(c["max_lifetime_minutes"]) * 60 - (gpu.clock() - sess["launched_at"])
            if left < mins * 60 * 1.3 + 60:              # the shot would not finish before the session's lifetime
                gpu.terminate_session(db, sess["session"], "replaced: the next shot would pass the maximum session length")
                stage("Starting a fresh GPU session (the maximum session length was near)")
                sess = session()
                CS.ensure_models(db, sess, MODELS, stage)
            cl = sess["client"]
            rid = uuid.uuid4().hex[:8]
            seed = random.randint(1, 2**31 - 1)
            _set_run(db, ep.id, i, status="rendering", started=time.time(), est_s=int(mins * 60), stage=f"Rendering on {sess['gpu_type']}",
                     error="")
            try:
                img = cl.upload(inp["still"])
                aud = cl.upload(inp["voice"])
                ctl = cl.upload(inp["control"]) if inp.get("control") else None
                prefix = f"video/ep{ep.id}-talk{i:02d}-{rid}"
                pid = cl.submit(build_graph(inp["prompt"]["text"], NEG, img, aud, ctl, r["frames"], seed, prefix))
                t0 = gpu.clock()
                while True:
                    gpu.sleep(POLL_S)
                    why = gpu.check_session(db, sess["session"])
                    if why:
                        raise gpu.GpuUnavailable(f"Stopped: {why}")
                    stt = cl.status(pid)
                    if stt["error"]:
                        raise ComfyError(stt["error"])
                    if stt["done"]:
                        break
                    if gpu.clock() - t0 > mins * 60 * 3 + 600:
                        raise ComfyError("the render took far longer than expected")
                files = [f for f in video_outputs(stt["outputs"]) if f.get("type", "output") == "output"]
                if not files:
                    raise ComfyError("the GPU returned no video")
                got = []
                for k, f in enumerate(files):
                    got.append(cl.download(f, folder / f"out{i:02d}-{k}{Path(f['filename']).suffix}"))
                # with a movement guide, the control video's passthrough comes back too: the result is the larger file
                result = max(got, key=lambda x: x.stat().st_size)
                elapsed = gpu.clock() - t0
                vk = f"episodes/{ep.id}/talking/shot{i:02d}-{rid}.mp4"
                storage().put_file(vk, result, "video/mp4")
                asset = Asset(episode_id=ep.id, job_id=job.id, kind="video", label=f"Talking shot {i}", storage_key=vk,
                              content_type="video/mp4", size=result.stat().st_size, sha256=sha256_file(result))
                db.add(asset)
                db.flush()
                pv = _mux_preview(ep, r, result, folder / f"preview{i:02d}.mp4", folder)
                pk = None
                if pv:
                    pk = f"episodes/{ep.id}/talking/shot{i:02d}-{rid}-review.mp4"
                    storage().put_file(pk, pv, "video/mp4")
                rec = {"id": rid, "asset_id": asset.id, "preview_key": pk, "at": time.time(), "seed": seed,
                       "prompt": inp["prompt"]["text"], "prompt_source": inp["prompt"].get("source"),
                       "guide": inp.get("guide") or {"used": False}, "gpu": sess["gpu_type"], "frames": r["frames"],
                       "pieces": pieces(r["frames"]), "seconds": round(elapsed), "trim_start_frames": TRIM_START_FRAMES,
                       "usd": round(price * elapsed / 3600, 3), "settings": "B", "job_id": job.id}
                db.commit()
                db.expire_all()
                v = stored(db, ep.id)
                st = _shot_state(v, i)
                st["renders"] = [rec] + (st.get("renders") or [])
                st["run"] = {**(st.get("run") or {}), "status": "done", "finished": time.time(), "stage": ""}
                save(db, ep.id, v)
                db.add(Event(episode_id=ep.id, kind="episode", message=f"Talking shot {i} rendered on {sess['gpu_type']} in {round(elapsed / 60)} min (not approved)"))
                db.commit()
                gpu.touch(db, sess["session"], clips=1)
                done.append(i)
            except ComfyError as e:
                _set_run(db, ep.id, i, status="failed", error=str(e)[:300], stage="")
                failed.append(i)
                ctx.log(f"shot {i}: {e}")
    except Exception as e:
        for i in want:
            if i not in done and i not in failed and i not in skipped:
                _set_run(db, ep.id, i, status="failed", error=str(e)[:300], stage="")
        raise
    finally:
        # terminate now unless another ComfyUI job (talking shots or reactions) is waiting for the same session
        if not CS.others_waiting(db, job.id):
            try:
                CS.stop(db, "talking shots finished")
            except Exception as e:   # noqa: BLE001 -- the sweep tries again
                ctx.log(f"could not terminate the GPU now ({str(e)[:120]}); the idle sweep will")
        shutil.rmtree(folder, ignore_errors=True)
    return {"done": done, "failed": failed, "skipped": skipped, "usd": round(spent(), 3)}
