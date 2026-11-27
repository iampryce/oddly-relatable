"""Narrated stick-man shorts: the "New short" wizard (owner-approved style guide studio-work/RIVET-STYLE-GUIDE.md, 2026-11-27).

An episode of kind "narrated_short" (episodes.kind, migration 0017): ONE narrator, 1-2 recurring house characters from
the cast library acting out each sentence. Its wizard state lives in the settings table (short:<episode id>), like the
other guided steps. The steps, each on the one wizard page, in plain English:

  1. Choose     niche, characters (approved masters from the cast library; a new one is made in the Cast flow), format
                (9:16 default, 16:9, 1:1) and length (30 s ... 10 min). Free.
  2. Ideas      GPT writes 10 ideas (title, hook line, twist, why it animates well, true / legend / fiction); or the
                owner types their own. Anything presented as TRUE is flagged "check before publishing".
  3. Script     GPT writes the narration only, on the story template (hook, setup, escalation 2-4 beats, pivot, payoff as
                the last words; about 3.7 words per second). The owner edits it and approves it (only that click).
  4. Scenes     the approved script split into one scene per sentence (very short ones merged, long ones cut at a comma;
                3-6 s each, free). Per scene GPT writes a picture prompt and an animation prompt (or the built-in
                templates, labelled, free); the owner can edit both.
  5. Voice      Gemini text-to-speech (tts.py; voice picker, style instruction; tier rules there) or the owner's own
                recording; then word timings with the studio's transcription (Settings > Transcription). The owner
                listens and approves a take.
  6. Pictures   Nano Banana (WaveSpeed, stick_pipeline's provider) per scene with the characters' approved masters as the
                reference images; the price per image is shown and confirmed first; the owner approves each picture.
  7. Motion     engine "Wan 2.2 on the rented GPU": image-to-video per scene on ONE rented ComfyUI session for all scenes
                (comfy_session.py), turned off when done. The Code kit and Omni Flash are shown as coming soon.
  8. Assembly   frame-exact: each scene runs from its sentence's first word to the next scene's first word (assembly.py's
                segment_frames: absolute frame positions, so nothing drifts); a clip is cut, held or slowed (at most
                1.25x slower, never faster; holding preferred) to fit. Optional music auto-levelled to -6 dB under the
                voice (gated RMS, the kit's mix rule), captions on by default (bold, high contrast, upper middle, a few
                words at a time, drawn by production/animation/overlay.mjs). Free (FFmpeg on the studio server).
  9. Publish    GPT writes the thumbnail prompt (the character + the one visual idea, 3-5 words), 5 titles, a description
                and hashtags; Nano makes the thumbnail (price shown first). The owner approves the final video.

Money: every paid action has its "at most" price computed before anything is sent and the request must carry it
(confirm_usd; HTTP 409 otherwise, nothing started). Paid calls are never retried. Keys only through secrets_store.secret().
Nothing approves itself: script, voice, pictures, clips and the final cut each wait for the owner's click
(memory "no-self-approvals"). The autopilot ("Make this short", short_autopilot.py) runs these same functions inside one
confirmed budget and stops at every approval.

Characters never change (memory "characters-never-change"): the masters are the only source of the look; every picture
request carries REFERENCE_RULES whatever the prompt says, and the prompt writer is told to refer to "the character in
reference image N" only.
"""
from __future__ import annotations

import difflib
import hashlib
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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import serialize as S
from . import tts
from .auth import current_user
from .db import get_db
from .models import Asset, Character, Episode, Event, Job, PublishRecord, Setting
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import sha256_file, storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

KIND = "narrated_short"
NICHES = {"what_if": "What-if stories", "money": "Money", "psychology": "Psychology and self-improvement",
          "history": "History", "weird_facts": "Weird facts", "custom": "Custom"}
FORMATS = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (960, 960)}      # the assembled frame
WAN_SIZES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (960, 960)}    # the Wan 2.2 i2v frame
LENGTHS = (30, 45, 60, 90, 120, 180, 300, 600)
MAX_CHARACTERS = 2
WPS = tts.WORDS_PER_SECOND              # 3.7 spoken words per second
SCENE_MIN_S, SCENE_MAX_S = 3.0, 6.0
FPS = 25                                # the assembled video
WAN_FPS, WAN_MIN_FRAMES, WAN_MAX_FRAMES = 16, 33, 81
WAN_STEPS, WAN_SPLIT, WAN_CFG, WAN_SHIFT = 4, 2, 1.0, 5.0
MAX_SLOW = 1.25                         # a short clip is slowed at most this much; it is never sped up
HOLD_OK_S = 1.0                         # a shortfall up to this is only held (holding is preferred over slowing)
MUSIC_UNDER_DB = 6.0                    # the music bed sits 6 dB under the voice (50 %), gated RMS
GATE_DB = -50.0                         # blocks quieter than this are silence and do not count in the level
CAPTION_WORDS = 3
PROMPT_BATCH = 12                       # scenes per prompt-writing call
JOB_PICTURE, JOB_VOICE, JOB_MOTION, JOB_ASSEMBLY, JOB_THUMB = ("short_picture", "short_voice", "short_motion",
                                                               "short_assembly", "short_thumbnail")
JOBS = (JOB_PICTURE, JOB_VOICE, JOB_MOTION, JOB_ASSEMBLY, JOB_THUMB)
ENGINES = {"wan_gpu": {"label": "Wan 2.2 on the rented GPU", "ready": True,
                       "note": "Image-to-video per scene on one rented GPU session; turned off when done."},
           "code_kit": {"label": "Code kit (free)", "ready": False,
                        "note": "Coming soon: the cartoon-short-kit renderer on the studio server."},
           "omni_flash": {"label": "Omni Flash (Google)", "ready": False,
                          "note": "Coming soon: needs Google billing (price to confirm)."}}
TEMPLATE_LABEL = "built-in template (no GPT)"
HOUSE_LOOK = ("Clean 3D-style background (a simple, tidy room, street or town), bright readable colours, soft light. "
              "The characters are flat 2D stick figures with bold black lines, exactly as drawn in their reference images.")
NEGATIVE = ("changing the characters' design, new or extra characters, morphing faces, extra limbs, realistic humans, "
            "text, captions, speech bubbles, watermark, flicker, camera shake, fast camera moves")
LABELS = ("true", "legend", "fiction")
CHECK_FLAG = "check before publishing"


def key(eid: int) -> str:
    return f"short:{eid}"


# ================================================================== pure parts: text
_SENT = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")


def words_of(text: str) -> int:
    return len((text or "").split())


def seconds_of(text: str) -> float:
    return round(words_of(text) / WPS, 2)


def target_words(seconds: int) -> int:
    return int(round(seconds * WPS))


def split_sentences(text: str) -> list[str]:
    """Sentences of the narration (a quote or bracket after the full stop stays with its sentence)."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return []
    out, last = [], 0
    for m in _SENT.finditer(t):
        out.append(t[last:m.end()].strip())
        last = m.end()
    out.append(t[last:].strip())
    return [s for s in out if s]


def _cut_long(sentence: str) -> list[str]:
    """A sentence longer than 6 s is cut at commas / semicolons / dashes into parts of at least 3 s when possible."""
    if seconds_of(sentence) <= SCENE_MAX_S:
        return [sentence]
    parts = [p.strip() for p in re.split(r"(?<=[,;:—–])\s+", sentence) if p.strip()]
    out, cur = [], ""
    for p in parts:
        nxt = f"{cur} {p}".strip()
        if cur and seconds_of(nxt) > SCENE_MAX_S and seconds_of(cur) >= SCENE_MIN_S:
            out.append(cur)
            cur = p
        else:
            cur = nxt
    if cur:
        if out and seconds_of(cur) < SCENE_MIN_S and seconds_of(out[-1] + " " + cur) <= SCENE_MAX_S * 1.5:
            out[-1] = out[-1] + " " + cur
        else:
            out.append(cur)
    return out


def split_scenes(text: str) -> list[str]:
    """One scene per sentence: very short sentences (under 3 s) are merged with the next one (the last with the one
    before) while the result stays within 6 s; sentences over 6 s are cut at a comma when they have one."""
    pieces = [p for s in split_sentences(text) for p in _cut_long(s)]
    out: list[str] = []
    for p in pieces:
        if out and seconds_of(out[-1]) < SCENE_MIN_S and seconds_of(out[-1] + " " + p) <= SCENE_MAX_S:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    if len(out) > 1 and seconds_of(out[-1]) < SCENE_MIN_S and seconds_of(out[-2] + " " + out[-1]) <= SCENE_MAX_S:
        out[-2:] = [out[-2] + " " + out[-1]]
    return out


def same_text(a: str, b: str) -> bool:
    n = lambda t: re.sub(r"\s+", " ", (t or "").strip())
    return n(a) == n(b)


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", (w or "").lower().replace("’", "'"))


def scene_starts(scene_texts: list[str], words: list[dict], duration: float) -> list[float]:
    """When each scene starts in the narration: the time of its sentence's FIRST word, found by aligning the script's
    words with the transcription's words (difflib). The first scene starts at 0 (it covers any lead-in). A scene whose
    words were not heard is placed by interpolation between its neighbours (by word count). Strictly increasing, at
    least one frame apart, all before `duration`."""
    n = len(scene_texts)
    if n == 0:
        return []
    script, first = [], []
    for t in scene_texts:
        first.append(len(script))
        script += [x for x in (_norm(w) for w in t.split()) if x]
    heard = [(x, float(w.get("start") or 0.0)) for w in words or [] for x in [_norm(str(w.get("word") or ""))] if x]
    matched: dict[int, float] = {}
    if heard and script:
        sm = difflib.SequenceMatcher(a=script, b=[h[0] for h in heard], autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                matched[a + k] = heard[b + k][1]
    total = max(1, len(script))
    dur = float(duration or 0.0) or (total / WPS)
    starts: list[float | None] = []
    for i in range(n):
        lo, hi = first[i], first[i + 1] if i + 1 < n else len(script)
        hit = next((matched[j] for j in range(lo, min(hi, lo + 3)) if j in matched), None)
        if hit is not None and lo in matched:
            starts.append(matched[lo])
        elif hit is not None:
            j = next(j for j in range(lo, min(hi, lo + 3)) if j in matched)
            starts.append(max(0.0, hit - (j - lo) / WPS))      # the first word or two were missed: step back
        else:
            starts.append(None)
    # fill the gaps by interpolation on the word index
    known = [(first[i], s) for i, s in enumerate(starts) if s is not None]
    for i, s in enumerate(starts):
        if s is not None:
            continue
        before = [(w, t) for w, t in known if w < first[i]]
        after = [(w, t) for w, t in known if w > first[i]]
        w0, t0 = before[-1] if before else (0, 0.0)
        w1, t1 = after[0] if after else (total, dur)
        starts[i] = t0 + (t1 - t0) * ((first[i] - w0) / max(1, w1 - w0))
    out = [0.0]
    step = 1.0 / FPS
    for s in starts[1:]:
        out.append(round(max(float(s), out[-1] + step), 3))
    limit = dur - step
    for i in range(len(out) - 1, 0, -1):          # never past the end (pulled back, still a frame apart)
        out[i] = round(min(out[i], limit - (len(out) - 1 - i) * step), 3)
    return out


def timing_rows(starts: list[float], end: float, fps: int = FPS) -> list[dict]:
    """[{start, frames, first_frame, seconds}] per scene: assembly.segment_frames (absolute frame positions)."""
    from .assembly import segment_frames
    return [{"start": round(starts[i], 3), "first_frame": a, "frames": n, "seconds": round(n / fps, 3)}
            for i, (a, n) in enumerate(segment_frames(starts, end, fps))]


def wan_length(seconds: float) -> int:
    """Frames of the Wan clip that covers `seconds` (16 fps; 4k+1 frames; 33 to 81, i.e. 2 s to 5 s)."""
    need = max(1, math.ceil(seconds * WAN_FPS))
    k = math.ceil((need - 1) / 4)
    return int(min(WAN_MAX_FRAMES, max(WAN_MIN_FRAMES, 4 * k + 1)))


def fit_short(src_frames: int, src_fps: float, slot_frames: int, fps: int = FPS) -> dict:
    """How a clip fills its scene: longer = the end is cut; shorter by up to HOLD_OK_S = its last frame is held;
    shorter by more = slowed (at most MAX_SLOW) and the rest held. Never sped up."""
    slot = slot_frames / fps
    have = src_frames / src_fps if src_fps and src_frames > 0 else 0.0
    out = {"stretch": 1.0, "held_s": 0.0, "cut_s": 0.0, "warnings": []}
    if have <= 0:
        out["held_s"] = round(slot, 3)
        out["warnings"].append("the clip has no frames: the picture is held")
        return out
    if have >= slot - 1e-6:
        if have > slot + 1.0 / fps:
            out["cut_s"] = round(have - slot, 3)
        return out
    short = slot - have
    if short <= HOLD_OK_S + 1e-9:
        out["held_s"] = round(short, 3)
        return out
    st = min(MAX_SLOW, slot / have)
    out["stretch"] = round(st, 4)
    out["held_s"] = round(max(0.0, slot - have * st), 3)
    out["warnings"].append(f"the clip is {short:.2f} s shorter than the scene: slowed to {st * 100:.0f}%"
                           + (f" and its last frame held for {out['held_s']:.2f} s" if out["held_s"] > 1.0 / fps else ""))
    return out


def caption_chunks(words: list[dict], max_words: int = CAPTION_WORDS, gap: float = 0.6) -> list[dict]:
    """A few words at a time: [{start, end, text}] (upper case). A chunk ends after max_words words, at the end of a
    sentence or clause, or before a pause longer than `gap`; it shows until the next chunk starts (or 0.3 s after its
    last word)."""
    ws = [w for w in words or [] if str(w.get("word") or "").strip()]
    chunks, cur = [], []
    for i, w in enumerate(ws):
        cur.append(w)
        text = str(w["word"]).strip()
        nxt = ws[i + 1] if i + 1 < len(ws) else None
        pause = nxt is not None and float(nxt["start"]) - float(w["end"]) > gap
        if len(cur) >= max_words or re.search(r"[.!?,;:…]$", text) or pause or nxt is None:
            chunks.append(cur)
            cur = []
    out = []
    for i, c in enumerate(chunks):
        a = float(c[0]["start"])
        b = float(c[-1]["end"]) + 0.3
        if i + 1 < len(chunks):
            b = min(b, float(chunks[i + 1][0]["start"])) if float(chunks[i + 1][0]["start"]) - float(c[-1]["end"]) <= gap else b
        text = " ".join(str(w["word"]).strip() for w in c).upper()
        out.append({"start": round(a, 3), "end": round(max(b, a + 0.2), 3), "text": text})
    return out


def gated_rms_db(samples, rate: int, block_s: float = 0.05, gate_db: float = GATE_DB) -> float | None:
    """The level of a sound in dBFS, counting only blocks louder than the gate (silences do not lower it). Samples are
    floats in [-1, 1]. None when everything is below the gate."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float64)
    n = max(1, int(rate * block_s))
    blocks = len(x) // n
    if blocks == 0:
        return None
    b = x[: blocks * n].reshape(blocks, n)
    rms = np.sqrt((b ** 2).mean(axis=1))
    with np.errstate(divide="ignore"):
        db = 20 * np.log10(np.maximum(rms, 1e-12))
    keep = rms[db > gate_db]
    if keep.size == 0:
        return None
    return round(float(20 * math.log10(math.sqrt(float((keep ** 2).mean())))), 3)


def music_gain_db(voice_db: float | None, music_db: float | None, under: float = MUSIC_UNDER_DB) -> float:
    """The gain (dB) that puts the music's gated level `under` dB below the voice's gated level."""
    if voice_db is None or music_db is None:
        return -60.0 if music_db is not None else 0.0
    return round((voice_db - under) - music_db, 3)


def _shift_input(n: int, first_pic: int) -> int:
    """overlay_graph numbers the pictures from input 2; here they come after the voice (1) and the music (2, if any)."""
    return n if n < 2 else n - 2 + first_pic


def mix_graph(gain_db: float | None) -> str:
    """The audio filter: the voice alone, or the voice plus the looped music at its gain; one limiter on the whole mix
    (no ducking or compression, so the -6 dB ratio holds)."""
    if gain_db is None:
        return "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad,alimiter=limit=0.95[aout]"
    return (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad[vo];"
            f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain_db:.3f}dB[mu];"
            f"[vo][mu]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]")


# ================================================================== pure parts: prompts
IDEAS_SYSTEM = (
    "You write ideas for narrated stick-man YouTube shorts. One narrator tells an original short story while 1-2 "
    "recurring stick-man characters act out each sentence in clean 3D-style worlds. Ideas must be ORIGINAL (no real "
    "people's likeness), visual (each sentence can be shown as one simple picture), with a hook that works as the very "
    "first line (a paradox, a question or a surprising fact) and a short ironic twist or one-line lesson at the end. "
    "Label each idea: \"true\" when it presents real facts as true, \"legend\" when it retells a legend or myth "
    "(the narration will say \"legend says\"), \"fiction\" when it is invented. Reply with JSON only: "
    "{\"ideas\": [{\"title\": \"...\", \"hook\": \"<the first line>\", \"twist\": \"<the ending>\", "
    "\"why_it_animates\": \"<why this is easy and fun to show>\", \"label\": \"true|legend|fiction\"}]} with exactly 10 ideas.")

SCRIPT_SYSTEM = (
    "You write the NARRATION of a narrated stick-man short: plain spoken English, words to be read aloud only (no scene "
    "directions, no headings, no speaker names, no emoji, no hashtags). Follow the story template exactly:\n"
    "1. Hook: the first line, no setup: a paradox, a question or a surprising fact.\n"
    "2. Setup in 1-2 lines: who, where, one concrete detail.\n"
    "3. Escalation in 2-4 beats, each bigger than the last.\n"
    "4. Pivot: \"But...\" or \"Here's the thing...\".\n"
    "5. Payoff / twist: short, ironic or a one-line lesson. These are the LAST words of the video.\n"
    "Short sentences: one sentence becomes one picture, so each sentence must be easy to show with the characters. "
    "About 3.7 spoken words per second. Original story only; never present unchecked facts as true; a legend is told "
    "as \"legend says\". Reply with the narration only.")

PROMPTS_SYSTEM = (
    "You write two prompts per scene of a narrated stick-man short. The PICTURE prompt is for an image model that gets "
    "the approved character masters as reference images: refer to each character ONLY as \"the character in reference "
    "image N\" (never describe or redesign their look), say where they are, what they do and feel in this one moment, "
    "and describe a clean 3D-style background with bright readable colours. The ANIMATION prompt is for image-to-video "
    "from that picture: one simple action that matches the sentence, small and clear, static camera or a gentle slow "
    "push-in, the characters' design never changes. No text, captions, speech bubbles, logos or watermarks. Reply with "
    "JSON only: {\"scenes\": [{\"scene\": <n>, \"picture\": \"...\", \"animation\": \"...\"}]}")

PUBLISH_SYSTEM = (
    "You write the publishing pack of a narrated stick-man YouTube short. Reply with JSON only: "
    "{\"thumbnail_prompt\": \"<for an image model given the character masters as reference images: the character "
    "in reference image 1 plus the ONE visual idea of the story, big and simple, bright colours, clean 3D-style "
    "background, with 3 to 5 words of bold text at most>\", \"thumbnail_text\": \"<those 3-5 words>\", "
    "\"titles\": [5 titles, at most 70 characters each], \"description\": \"<2-4 sentences>\", "
    "\"hashtags\": [5-8 hashtags starting with #]}. Never claim unchecked facts as true.")


def names_line(names: list[str]) -> str:
    return "; ".join(f"the character in reference image {i + 1} ({n})" for i, n in enumerate(names))


def reference_rules(names: list[str]) -> str:
    """Appended to EVERY picture request (characters never change): the masters are the only source of the look."""
    if not names:
        return ("Nobody from the cast is in this picture. " + HOUSE_LOOK)
    refs = ", ".join(f"image {i + 1} is {n}" for i, n in enumerate(names))
    return (f"Reference images: {refs}. Draw each character EXACTLY as in their reference image (same head, eyes, line "
            "style, accessory and colours); never redesign them, never merge them, add nobody else. " + HOUSE_LOOK +
            " No text, no captions, no speech bubbles, no watermark.")


def picture_request(prompt: str, names: list[str], aspect: str) -> str:
    return f"{prompt.strip()}\n\nFrame: {aspect}. {reference_rules(names)}"


def picture_template(text: str, names: list[str]) -> str:
    who = names_line(names) or "the scene"
    return (f"One moment that shows this narration line: \"{text.strip()}\". {who[0].upper() + who[1:]} acts it out with "
            "a clear, readable pose and expression. Clean 3D-style background that fits the line, bright readable colours.")


def animation_template(text: str) -> str:
    return (f"Simple, small action that matches the line \"{text.strip()[:200]}\": the character moves clearly once, then "
            "settles. Static camera. Same drawing, line style and colours throughout; the character's design never changes.")


def thumbnail_template(title: str, names: list[str]) -> str:
    return (f"YouTube thumbnail for \"{title}\": {names_line(names[:1]) or 'the character'} in the middle, big and clear, "
            "with the one visual idea of the story; bright colours, clean 3D-style background, 3 to 5 words of bold text.")


def ideas_message(niche: str, custom: str, names: list[str], seconds: int, avoid: list[str]) -> str:
    parts = [f"NICHE: {NICHES.get(niche, niche)}" + (f" ({custom.strip()})" if custom.strip() else ""),
             f"LENGTH: {seconds} seconds (about {target_words(seconds)} words of narration)",
             "THE HOUSE CHARACTERS (recurring stick men): " + (", ".join(names) or "one stick man")]
    if avoid:
        parts.append("ALREADY USED (do not repeat): " + "; ".join(avoid[:30]))
    return "\n".join(parts)


def script_message(idea: dict, niche: str, names: list[str], seconds: int, notes: str = "") -> str:
    parts = [f"IDEA: {idea.get('title', '')}", f"HOOK LINE: {idea.get('hook', '')}", f"TWIST: {idea.get('twist', '')}",
             f"LABEL: {idea.get('label', 'fiction')}", f"NICHE: {NICHES.get(niche, niche)}",
             "CHARACTERS: " + (", ".join(names) or "one stick man"),
             f"LENGTH: {seconds} seconds = about {target_words(seconds)} words (3.7 words per second)"]
    if notes.strip():
        parts.append(f"OWNER'S NOTES: {notes.strip()}")
    return "\n".join(parts)


def prompts_message(scenes: list[dict], names: list[str], aspect: str, script: str) -> str:
    lines = [f"FRAME: {aspect}", "REFERENCE IMAGES: " + (names_line(names) or "none"),
             "HOUSE LOOK: " + HOUSE_LOOK, "THE WHOLE NARRATION (context): " + script[:3000], "SCENES:"]
    lines += [f"{s['n']}. {s['text']}" for s in scenes]
    return "\n".join(lines)


def publish_message(title: str, script: str, names: list[str], label: str) -> str:
    return (f"TITLE IDEA: {title}\nLABEL: {label}\nCHARACTERS (reference images): {names_line(names)}\n"
            f"NARRATION:\n{script[:6000]}")


def parse_json(text: str, list_key: str = "") -> dict:
    """The JSON object of a model's answer (a code fence or words around it are ignored). A bare list is accepted as
    {list_key: list} when the caller names the key it expects."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    obj = re.search(r"\{.*\}", raw, re.S)
    arr = re.search(r"\[.*\]", raw, re.S)
    o, a = (obj.group(0) if obj else ""), (arr.group(0) if arr else "")
    for cand in ((raw, a, o) if list_key else (raw, o, a)):
        if not cand:
            continue
        try:
            d = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict):
            return d
        if isinstance(d, list) and list_key:
            return {list_key: d}
    raise HTTPException(502, "the answer was not the JSON that was asked for; nothing was saved (not retried)")


def clean_ideas(raw) -> list[dict]:
    out = []
    for x in (raw or [])[:10]:
        if not isinstance(x, dict) or not str(x.get("title") or "").strip():
            continue
        label = str(x.get("label") or "fiction").lower().strip()
        label = label if label in LABELS else "fiction"
        out.append({"id": pysecrets.token_hex(4), "title": str(x["title"]).strip()[:120],
                    "hook": str(x.get("hook") or "").strip()[:300], "twist": str(x.get("twist") or "").strip()[:300],
                    "why_it_animates": str(x.get("why_it_animates") or "").strip()[:300], "label": label,
                    "check": label == "true"})
    return out


# ================================================================== state
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = json.loads(json.dumps(v))
    else:
        db.add(Setting(key=key(eid), value=json.loads(json.dumps(v))))


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None or getattr(ep, "kind", None) != KIND:
        raise HTTPException(404, "narrated short not found")
    return ep


def _event(db: Session, eid: int, msg: str, kind: str = "episode") -> None:
    db.add(Event(episode_id=eid, kind=kind, message=msg))


def characters_of(db: Session, v: dict) -> list[Character]:
    out = []
    for cid in (v.get("choose") or {}).get("characters") or []:
        c = db.get(Character, int(cid))
        if c is not None:
            out.append(c)
    return out


def names_of(db: Session, v: dict) -> list[str]:
    return [c.name for c in characters_of(db, v)]


def aspect_of(v: dict) -> str:
    return (v.get("choose") or {}).get("format") or "9:16"


def seconds_target(v: dict) -> int:
    return int((v.get("choose") or {}).get("seconds") or 30)


def script_versions(v: dict) -> list[dict]:
    return (v.get("script") or {}).get("versions") or []


def current_script(v: dict) -> dict | None:
    vs = script_versions(v)
    return vs[-1] if vs else None


def approved_script(v: dict) -> dict | None:
    a = (v.get("script") or {}).get("approved")
    return next((x for x in script_versions(v) if x["v"] == a), None) if a else None


def scenes_of(v: dict) -> list[dict]:
    return (v.get("scenes") or {}).get("items") or []


def scene_or_404(v: dict, n: int) -> dict:
    s = next((x for x in scenes_of(v) if x["n"] == n), None)
    if s is None:
        raise HTTPException(404, f"no scene {n}")
    return s


def takes_of(v: dict) -> list[dict]:
    return (v.get("voice") or {}).get("takes") or []


def approved_take(v: dict) -> dict | None:
    a = (v.get("voice") or {}).get("approved")
    return next((t for t in takes_of(v) if t["id"] == a), None) if a else None


def take_fits(v: dict, t: dict | None) -> bool:
    """A generated take fits when it reads the approved script as it is now (an uploaded one is the owner's reading)."""
    sc = approved_script(v)
    if not t or not sc:
        return False
    return t.get("source") == "upload" or same_text(t.get("text") or "", sc["text"])


def masters_ready(db: Session, v: dict) -> list[str]:
    """Names of the chosen characters WITHOUT an approved master (nothing can be drawn for them)."""
    from .stick_pipeline import approved_master
    return [c.name for c in characters_of(db, v) if approved_master(db, c.id) is None]


def _active(db: Session, eid: int, kinds=JOBS, scene: int | None = None):
    q = db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(("queued", "running")))
    jobs = q.all()
    if scene is None:
        return jobs
    return [j for j in jobs if scene in ((j.payload or {}).get("scenes") or [(j.payload or {}).get("n")])]


def timing(v: dict) -> dict | None:
    """Scene starts and frames from the approved take's words (None until a fitting take is approved)."""
    t = approved_take(v)
    if not take_fits(v, t) or not scenes_of(v):
        return None
    texts = [s["text"] for s in scenes_of(v)]
    starts = scene_starts(texts, t.get("words") or [], float(t.get("seconds") or 0))
    end = float(t.get("seconds") or 0) or (starts[-1] + 3.0)
    return {"starts": starts, "end": round(end, 3), "rows": timing_rows(starts, end), "estimated": not t.get("words")}


# ================================================================== cost helpers
def gpt_estimate(db: Session, system: str, message: str, calls: int = 1) -> dict:
    from . import prompt_writer as PW
    cfg = PW.config(db)
    e = PW.estimate(cfg, system, message)
    if calls > 1:
        e = {**e, "usd_typical": round(e["usd_typical"] * calls, 4), "usd_max": round(e["usd_max"] * calls, 4), "calls": calls}
    e["label"] = f"{e['model']}: about ${e['usd_typical']:.4f}, at most ${e['usd_max']:.4f}"
    e["key_set"] = bool(secret("openai_api_key", db))
    return e


def gpt_call(db: Session, system: str, message: str, confirm: float | None, what: str, est: dict | None = None) -> dict:
    """One paid GPT call (prompt_writer's client and settings) with the "at most" price confirmed first; never retried."""
    from . import prompt_writer as PW
    est = est or gpt_estimate(db, system, message)
    if confirm is None or confirm + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"{what} can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    api_key = secret("openai_api_key", db)
    if not api_key:
        raise HTTPException(409, "save the OpenAI API key under Settings > Credentials first (or type it yourself)")
    cfg = PW.config(db)
    out = PW.call_openai(api_key, cfg["prompt_model"], system, message, int(cfg["prompt_max_tokens"]))
    if not out["text"]:
        raise HTTPException(502, "OpenAI returned an empty answer (cut off?); raise the longest answer in Settings > Guided generation")
    out["usd"] = PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg)
    out["model"] = cfg["prompt_model"]
    return out


def picture_cost(db: Session, count: int = 1) -> dict:
    from .stick_pipeline import IMAGE_PROVIDERS, image_cost
    ip = IMAGE_PROVIDERS.get(get_section(db, "stick").get("image_provider"))
    if not ip:
        return {"usd": None, "label": "no picture service chosen (Settings > Studio style)", "count": count}
    return image_cost(count, ip["usd_per_image"])


def require_exact(cost: float | None, confirm: float | None) -> None:
    from .stick_pipeline import require_confirmed
    if cost is None:
        raise HTTPException(409, "no picture service is chosen (Settings > Studio style)")
    require_confirmed(cost, confirm)


def transcription_cost(db: Session, seconds: float) -> dict:
    cfg = get_section(db, "transcription")
    p = cfg.get("provider") or "none"
    if p == "openai":
        per = float(get_section(db, "short").get("transcribe_usd_per_minute") or 0.006)
        usd = round(math.ceil(max(seconds, 1) * 1.5) / 60 * per, 4)
        return {"provider": p, "usd": usd, "label": f"word timings (OpenAI): at most ${usd:.4f}"}
    if p == "none":
        return {"provider": p, "usd": 0.0, "label": "no transcription provider: scene timing is estimated from the words"}
    return {"provider": p, "usd": 0.0, "label": f"word timings ({p}): free"}


def voice_estimate(db: Session, v: dict, use_free_tier: bool) -> dict | None:
    sc = approved_script(v)
    if not sc:
        return None
    cfg = get_section(db, "short")
    try:
        e = tts.estimate(sc["text"], cfg, bool(cfg.get("tts_paid_tier")), use_free_tier)
    except ValueError as ex:
        return {"blocked": str(ex), "usd_max": None}
    tr = transcription_cost(db, e["seconds"] * tts.MARGIN)
    total = round(e["usd_max"] + tr["usd"], 4)
    return {**e, "transcription": tr, "usd_max": total,
            "label": f"{e['label']}; {tr['label']}. Total at most ${total:.4f}"}


def motion_estimate(db: Session, clips: int) -> dict:
    from . import comfy_session as CS
    from . import gpu
    from . import reactions as R
    e = R.estimate(0, clips, CS.list_prices(gpu.cfg(db)))
    e["label"] = (f"{clips} clip(s) on one rented GPU session (about 10 min to start + about 2.5 min per clip): "
                  f"about ${e['usd_typical']:.2f}, at most ${e['usd_max']:.2f}") if clips else "nothing to animate"
    return e


# ================================================================== view
def _asset_urls(db: Session, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {a.id: storage().url(a.storage_key) for a in db.query(Asset).filter(Asset.id.in_(ids))}


def cast_options(db: Session) -> list[dict]:
    """The characters that can be used: the cast library first, then any character with an approved master."""
    from . import cast_from_video as CV
    from .stick_pipeline import approved_master
    out, seen = [], set()
    for e in CV.library_out(db):
        out.append({"character_id": e["character_id"], "name": e["name"], "master_url": e["master_url"],
                    "from": "cast library", "style": e.get("style_label")})
        seen.add(e["character_id"])
    for c in db.query(Character).order_by(Character.id):
        if c.id in seen:
            continue
        m = approved_master(db, c.id)
        if m is not None:
            out.append({"character_id": c.id, "name": c.name, "master_url": storage().url(m.storage_key),
                        "from": "approved master", "style": None})
    return out


def estimates(db: Session, ep: Episode, v: dict) -> dict:
    names = names_of(db, v)
    ch = v.get("choose") or {}
    idea = v.get("idea") or {}
    out: dict = {"ideas": gpt_estimate(db, IDEAS_SYSTEM, ideas_message(ch.get("niche") or "what_if", ch.get("custom_niche") or "",
                                                                          names, seconds_target(v), []))}
    if idea:
        out["script"] = gpt_estimate(db, SCRIPT_SYSTEM, script_message(idea, ch.get("niche") or "", names, seconds_target(v)))
    sc = approved_script(v)
    scs = scenes_of(v)
    if sc and scs:
        batches = [scs[i:i + PROMPT_BATCH] for i in range(0, len(scs), PROMPT_BATCH)]
        e = gpt_estimate(db, PROMPTS_SYSTEM, prompts_message(batches[0], names, aspect_of(v), sc["text"]), len(batches))
        out["prompts"] = e
        out["publish"] = gpt_estimate(db, PUBLISH_SYSTEM, publish_message(idea.get("title") or ep.title, sc["text"], names,
                                                                          idea.get("label") or "fiction"))
    vf = v.get("voice") or {}
    out["voice"] = voice_estimate(db, v, bool(vf.get("use_free_tier")))
    out["picture"] = picture_cost(db, 1)
    todo = [s for s in scs if not s.get("pictures")]
    out["pictures_all"] = picture_cost(db, len(todo)) if todo else None
    need = [s["n"] for s in scs if needs_clip(s)]
    out["motion"] = {**motion_estimate(db, len(need)), "scenes": need}
    out["motion_one"] = motion_estimate(db, 1)
    out["thumbnail"] = picture_cost(db, 1)
    return out


def needs_clip(s: dict) -> bool:
    return bool(s.get("picture_approved") and s.get("picture_chosen")
                and not any(c.get("picture") == s.get("picture_chosen") for c in s.get("clips") or []))


def providers(db: Session, ep: Episode, v: dict) -> list[dict]:
    """What each step uses and whether it is ready (never a key value)."""
    from . import comfy_session as CS
    from .config import get_settings
    from .stick_pipeline import IMAGE_PROVIDERS
    st = get_section(db, "stick")
    ip = IMAGE_PROVIDERS.get(st.get("image_provider"))
    oa = bool(secret("openai_api_key", db))
    gem = bool(secret("gemini_api_key", db))
    ws = bool(secret("wavespeed_api_key", db))
    a = CS.availability(db)
    tr = get_section(db, "transcription").get("provider") or "none"
    s = get_settings()
    t = approved_take(v)
    has_voice = bool(t and t.get("source") == "upload")
    return [
        {"step": "writing", "label": "Ideas, script, prompts and publish pack", "provider": f"OpenAI {get_section(db, 'guide')['prompt_model']}",
         "ready": oa, "essential": False, "note": "" if oa else "No OpenAI key: type your own idea and script; prompts use the built-in templates"},
        {"step": "voice", "label": "Narration voice", "provider": "Gemini text-to-speech", "ready": gem or has_voice,
         "essential": False, "note": "" if gem or has_voice else "No Gemini key: upload your own voice instead"},
        {"step": "timing", "label": "Word timings", "provider": tr, "ready": True, "essential": False,
         "note": "" if tr != "none" else "No transcription provider: scene timing is estimated (Settings > Transcription)"},
        {"step": "pictures", "label": "Scene pictures and thumbnail", "provider": ip["label"] if ip else "none chosen",
         "ready": bool(ip and ws), "essential": True,
         "note": "" if ip and ws else "Choose the picture service and save the WaveSpeed key (Settings)"},
        {"step": "motion", "label": "Motion (Wan 2.2)", "provider": "RunPod rented GPU", "ready": a["ok"], "essential": True,
         "note": a["reason"]},
        {"step": "assembly", "label": "Assembly", "provider": "FFmpeg on the studio server (free)", "ready": bool(s.ffmpeg),
         "essential": True, "note": "" if s.ffmpeg else "FFmpeg is not configured on the studio server"},
    ]


def assembly_plan(db: Session, ep: Episode, v: dict) -> dict:
    """Rows of the assembly: per scene its clip (the chosen one) or its approved picture held; what is missing."""
    tm = timing(v)
    rows, missing = [], []
    for i, s in enumerate(scenes_of(v)):
        clip = next((c for c in s.get("clips") or [] if c["asset_id"] == s.get("clip_chosen")), None)
        src = ("clip", clip["asset_id"]) if clip else (("still", s["picture_chosen"])
                                                      if s.get("picture_approved") and s.get("picture_chosen") else (None, None))
        if src[0] is None:
            missing.append(s["n"])
        r = {"n": s["n"], "source": src[0], "asset_id": src[1], "frames": tm["rows"][i]["frames"] if tm else None,
             "start": tm["rows"][i]["start"] if tm else None, "src_frames": clip.get("frames") if clip else None}
        if clip and tm:
            r.update(fit_short(int(clip.get("frames") or 0), WAN_FPS, r["frames"]))
        rows.append(r)
    music = (v.get("music") or {})
    sig = json.dumps({"rows": [(r["n"], r["source"], r["asset_id"], r["frames"]) for r in rows],
                      "voice": (approved_take(v) or {}).get("id"), "music": music.get("asset_id") if music.get("enabled") else None,
                      "captions": captions_on(v), "aspect": aspect_of(v)}, sort_keys=True)
    return {"rows": rows, "missing": missing, "timing": tm, "hash": hashlib.sha256(sig.encode()).hexdigest()[:16],
            "voice_ok": tm is not None}


def captions_on(v: dict) -> bool:
    return v.get("captions", True) is not False


def view(db: Session, ep: Episode) -> dict:
    from .config import get_settings
    v = stored(db, ep.id)
    scs = scenes_of(v)
    ids = set()
    for s in scs:
        ids |= {p["asset_id"] for p in s.get("pictures") or []} | {c["asset_id"] for c in s.get("clips") or []}
    ids |= {t.get("asset_id") for t in takes_of(v)}
    ids |= {c.get("asset_id") for c in (v.get("final") or {}).get("cuts") or []}
    ids |= {t.get("asset_id") for t in (v.get("publish") or {}).get("thumbnails") or []}
    ids.add((v.get("music") or {}).get("asset_id"))
    urls = _asset_urls(db, ids)
    out_scenes = []
    tm = timing(v)
    for i, s in enumerate(scs):
        out_scenes.append({**s, "pictures": [{**p, "url": urls.get(p["asset_id"])} for p in s.get("pictures") or []],
                           "clips": [{**c, "url": urls.get(c["asset_id"])} for c in s.get("clips") or []],
                           "busy": bool(_active(db, ep.id, (JOB_PICTURE, JOB_MOTION), s["n"])),
                           "estimated_seconds": seconds_of(s["text"]),
                           "timed": tm["rows"][i] if tm else None})
    vo = dict(v.get("voice") or {})
    vo["takes"] = [{**t, "url": urls.get(t.get("asset_id")), "fits": take_fits(v, t),
                    "words": len(t.get("words") or [])} for t in takes_of(v)]
    fin = dict(v.get("final") or {})
    plan = assembly_plan(db, ep, v)
    fin["cuts"] = [{**c, "url": urls.get(c.get("asset_id")), "current": c.get("hash") == plan["hash"]} for c in fin.get("cuts") or []]
    pub = dict(v.get("publish") or {})
    pub["thumbnails"] = [{**t, "url": urls.get(t.get("asset_id"))} for t in pub.get("thumbnails") or []]
    mus = dict(v.get("music") or {})
    mus["url"] = urls.get(mus.get("asset_id"))
    jobs = db.query(Job).filter(Job.kind.in_(JOBS), Job.episode_id == ep.id).order_by(Job.id.desc()).limit(20).all()
    s = get_settings()
    cfg = get_section(db, "short")
    return {"id": ep.id, "title": ep.title, "kind": KIND, "choose": v.get("choose") or {}, "ideas": v.get("ideas") or {},
            "idea": v.get("idea"), "script": {"versions": script_versions(v), "approved": (v.get("script") or {}).get("approved"),
                                              "approved_by": (v.get("script") or {}).get("approved_by")},
            "scenes": {"items": out_scenes, "version": (v.get("scenes") or {}).get("version", 0),
                       "script_version": (v.get("scenes") or {}).get("script_version")},
            "voice": vo, "timing": tm, "music": mus, "captions": captions_on(v), "motion": {"engine": "wan_gpu", "engines": ENGINES},
            "final": fin, "assembly": {k: plan[k] for k in ("rows", "missing", "hash", "voice_ok")},
            "publish": pub, "usd": round(float(v.get("usd") or 0.0), 4),
            "options": {"niches": NICHES, "formats": list(FORMATS), "lengths": list(LENGTHS), "voices": list(tts.VOICES),
                        "default_voice": cfg.get("voice") or tts.DEFAULT_VOICE, "default_style": cfg.get("style") or tts.DEFAULT_STYLE,
                        "tts_paid_tier": bool(cfg.get("tts_paid_tier")), "free_warning": tts.FREE_WARNING,
                        "max_characters": MAX_CHARACTERS, "words_per_second": WPS},
            "cast": cast_options(db), "missing_masters": masters_ready(db, v),
            "estimates": estimates(db, ep, v), "providers": providers(db, ep, v),
            "ffmpeg": bool(s.ffmpeg), "jobs": [S.job(j) for j in jobs], "busy": bool(_active(db, ep.id))}


# ================================================================== step 1: choose
class ChooseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)
    niche: Literal["what_if", "money", "psychology", "history", "weird_facts", "custom"] = "what_if"
    custom_niche: str = Field(default="", max_length=200)
    characters: list[int] = Field(default_factory=list, max_length=MAX_CHARACTERS)
    format: Literal["9:16", "16:9", "1:1"] = "9:16"
    seconds: int = Field(default=30)


def _check_choose(db: Session, body: ChooseIn) -> None:
    if body.seconds not in LENGTHS:
        raise HTTPException(422, f"the length must be one of {', '.join(map(str, LENGTHS))} seconds")
    if body.niche == "custom" and not body.custom_niche.strip():
        raise HTTPException(422, "say what the custom niche is")
    if len(set(body.characters)) != len(body.characters):
        raise HTTPException(422, "a character is chosen twice")
    for cid in body.characters:
        if db.get(Character, cid) is None:
            raise HTTPException(404, f"character {cid} not found")


def _layout_for(fmt: str) -> str | None:
    return "landscape" if fmt == "16:9" else None


@router.post("/shorts", status_code=201)
def create_short(body: ChooseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """A new narrated short (free). Its first step's choices are saved with it."""
    _check_choose(db, body)
    ep = Episode(title=(body.title or "").strip() or "New short", kind=KIND, source="script", stage="script_pending",
                 format="short" if body.seconds <= 180 and body.format != "16:9" else "long",
                 layout=_layout_for(body.format), dialogue_display="captions", hook_banner=False)
    db.add(ep)
    db.flush()
    v = {"choose": body.model_dump(exclude={"title"}), "captions": True, "created_by": user, "usd": 0.0}
    save(db, ep.id, v)
    _event(db, ep.id, f"New short created by {user} ({NICHES[body.niche]}, {body.format}, {body.seconds} s)")
    db.commit()
    return view(db, ep)


@router.get("/shorts/{eid}")
def get_short(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


@router.put("/shorts/{eid}/choose")
def put_choose(eid: int, body: ChooseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Change step 1 (free). Changing the characters or the format does not touch pictures already made: the scenes
    say which characters each picture was drawn with."""
    ep = _episode(db, eid)
    _check_choose(db, body)
    v = stored(db, eid)
    v["choose"] = body.model_dump(exclude={"title"})
    if body.title and body.title.strip():
        ep.title = body.title.strip()
    ep.layout = _layout_for(body.format)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


# ================================================================== step 2: ideas
class PaidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_usd: float | None = Field(default=None, ge=0, le=50)


def write_ideas(db: Session, ep: Episode, confirm: float | None, user: str) -> dict:
    v = stored(db, ep.id)
    ch = v.get("choose") or {}
    avoid = [i["title"] for i in (v.get("ideas") or {}).get("items") or []]
    msg = ideas_message(ch.get("niche") or "what_if", ch.get("custom_niche") or "", names_of(db, v), seconds_target(v), avoid)
    out = gpt_call(db, IDEAS_SYSTEM, msg, confirm, "writing 10 ideas")
    items = clean_ideas(parse_json(out["text"], "ideas").get("ideas"))
    if not items:
        raise HTTPException(502, "the answer had no usable ideas; nothing was saved (not retried)")
    v = stored(db, ep.id)
    v["ideas"] = {"items": items, "model": out["model"], "at": time.time(), "usd": out["usd"]}
    v["usd"] = round(float(v.get("usd") or 0) + out["usd"], 6)
    save(db, ep.id, v)
    _event(db, ep.id, f"Short: 10 ideas written by {out['model']} for {user} (${out['usd']:.4f})")
    db.commit()
    return {"usd": out["usd"], "ideas": len(items)}


@router.post("/shorts/{eid}/ideas")
def post_ideas(eid: int, body: PaidIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one GPT call; the "at most" price confirmed first): 10 new ideas."""
    ep = _episode(db, eid)
    write_ideas(db, ep, body.confirm_usd, user)
    return view(db, ep)


class IdeaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea_id: str | None = Field(default=None, max_length=20)          # one of the written ideas
    title: str | None = Field(default=None, max_length=120)            # or the owner's own
    hook: str = Field(default="", max_length=300)
    twist: str = Field(default="", max_length=300)
    label: Literal["true", "legend", "fiction"] = "fiction"


@router.put("/shorts/{eid}/idea")
def put_idea(eid: int, body: IdeaIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner picks an idea or types their own (free). Facts presented as true carry the "check before publishing"
    flag all the way to the publish pack."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.idea_id:
        it = next((x for x in (v.get("ideas") or {}).get("items") or [] if x["id"] == body.idea_id), None)
        if it is None:
            raise HTTPException(404, "no such idea")
        idea = {**it, "own": False}
    else:
        if not (body.title or "").strip():
            raise HTTPException(422, "give your idea a title")
        idea = {"id": "own", "title": body.title.strip(), "hook": body.hook.strip(), "twist": body.twist.strip(),
                "label": body.label, "check": body.label == "true", "own": True, "why_it_animates": ""}
    v["idea"] = idea
    ep.title = idea["title"][:200]
    save(db, eid, v)
    _event(db, eid, f"Short: idea \"{idea['title']}\" chosen by {user}")
    db.commit()
    return view(db, ep)


# ================================================================== step 3: script
def _add_script(v: dict, text: str, source: str, extra: dict | None = None) -> dict:
    vs = script_versions(v)
    item = {"v": (vs[-1]["v"] + 1) if vs else 1, "text": text.strip(), "source": source, "at": time.time(),
            "words": words_of(text), "seconds": seconds_of(text), **(extra or {})}
    v.setdefault("script", {}).setdefault("versions", []).append(item)
    v["script"]["versions"] = v["script"]["versions"][-30:]
    return item


class ScriptWriteIn(PaidIn):
    notes: str = Field(default="", max_length=2000)


def write_script(db: Session, ep: Episode, confirm: float | None, notes: str, user: str) -> dict:
    v = stored(db, ep.id)
    idea = v.get("idea")
    if not idea:
        raise HTTPException(409, "pick or type an idea first (step 2)")
    ch = v.get("choose") or {}
    msg = script_message(idea, ch.get("niche") or "", names_of(db, v), seconds_target(v), notes)
    out = gpt_call(db, SCRIPT_SYSTEM, msg, confirm, "writing the script")
    text = re.sub(r"^\s*(narration|script)\s*:\s*", "", out["text"].strip(), flags=re.I).strip().strip('"')
    v = stored(db, ep.id)
    item = _add_script(v, text, "gpt", {"model": out["model"], "usd": out["usd"]})
    v["usd"] = round(float(v.get("usd") or 0) + out["usd"], 6)
    save(db, ep.id, v)
    ep.stage = "script_review"
    _event(db, ep.id, f"Short: script v{item['v']} written by {out['model']} for {user} (${out['usd']:.4f}), waiting for approval")
    db.commit()
    return {"usd": out["usd"], "version": item["v"]}


@router.post("/shorts/{eid}/script/write")
def post_script(eid: int, body: ScriptWriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one GPT call, confirmed first): the narration on the story template. It waits for approval."""
    ep = _episode(db, eid)
    write_script(db, ep, body.confirm_usd, body.notes, user)
    return view(db, ep)


class ScriptEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000)


@router.put("/shorts/{eid}/script")
def put_script(eid: int, body: ScriptEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's own text or edit (free): a new version, waiting for approval (an approved version stays approved
    until the owner approves this one)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    cur = current_script(v)
    if cur and same_text(cur["text"], body.text):
        return view(db, ep)
    item = _add_script(v, body.text, "edited" if cur else "owner", {"by": user})
    save(db, eid, v)
    ep.stage = "script_review"
    _event(db, eid, f"Short: script v{item['v']} saved by {user}, waiting for approval")
    db.commit()
    return view(db, ep)


class ApproveScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


def _scenes_from(text: str) -> list[dict]:
    return [{"n": i + 1, "text": t, "picture_prompt": "", "animation_prompt": "", "prompt_source": "",
             "pictures": [], "picture_chosen": None, "picture_approved": False, "clips": [], "clip_chosen": None,
             "clip_approved": False} for i, t in enumerate(split_scenes(text))]


def split_into_scenes(v: dict, force: bool = False) -> bool:
    """Scenes from the approved script (free). Kept as they are when they already read the approved text (so a line
    rewritten from the chat keeps its pictures); made again otherwise. Returns True when made again."""
    sc = approved_script(v)
    if not sc:
        raise HTTPException(409, "approve the script first (step 3)")
    cur = scenes_of(v)
    if cur and not force and same_text(" ".join(s["text"] for s in cur), sc["text"]):
        v["scenes"]["script_version"] = sc["v"]
        return False
    old = v.get("scenes") or {}
    v["scenes"] = {"items": _scenes_from(sc["text"]), "version": int(old.get("version") or 0) + 1, "script_version": sc["v"],
                   "at": time.time()}
    return True


@router.post("/shorts/{eid}/script/approve")
def approve_script(eid: int, body: ApproveScriptIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: this version is the narration. The scenes are split from it (free)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if not any(x["v"] == body.version for x in script_versions(v)):
        raise HTTPException(404, "no such script version")
    if body.version != current_script(v)["v"]:
        raise HTTPException(409, "approve the latest version (or save the one you want again)")
    v.setdefault("script", {}).update(approved=body.version, approved_by=user, approved_at=time.time())
    remade = split_into_scenes(v)
    save(db, eid, v)
    ep.stage = "script_approved"
    _event(db, eid, f"Short: script v{body.version} approved by {user}" + ("; scenes split" if remade else ""), "approval")
    db.commit()
    return view(db, ep)


@router.post("/shorts/{eid}/script/unapprove")
def unapprove_script(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    v.setdefault("script", {}).update(approved=None, approved_by=None)
    save(db, eid, v)
    ep.stage = "script_review"
    _event(db, eid, f"Short: script approval withdrawn by {user}", "approval")
    db.commit()
    return view(db, ep)


# ================================================================== step 4: scenes
@router.post("/shorts/{eid}/scenes/split")
def post_split(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Split the approved script into scenes again (free). Pictures and clips of the old scenes are kept in storage
    but no longer used."""
    ep = _episode(db, eid)
    if _active(db, eid, (JOB_PICTURE, JOB_MOTION)):
        raise HTTPException(409, "pictures or clips are being made: wait until they finish")
    v = stored(db, eid)
    split_into_scenes(v, force=True)
    save(db, eid, v)
    _event(db, eid, f"Short: scenes split again by {user} ({len(scenes_of(v))} scenes)")
    db.commit()
    return view(db, ep)


class SceneEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    picture_prompt: str | None = Field(default=None, max_length=4000)
    animation_prompt: str | None = Field(default=None, max_length=1500)


def rewrite_line(db: Session, ep: Episode, n: int, text: str, user: str) -> dict:
    """One scene's line changes (free): the script gets a new version with that line, waiting for approval again; the
    scene keeps its pictures. The narration must be made again for the new words (the old take no longer fits)."""
    v = stored(db, ep.id)
    s = scene_or_404(v, n)
    s["text"] = text.strip()
    new_text = " ".join(x["text"] for x in scenes_of(v))
    item = _add_script(v, new_text, "edited", {"by": user, "note": f"scene {n} rewritten"})
    v["script"]["approved"] = None
    save(db, ep.id, v)
    ep.stage = "script_review"
    _event(db, ep.id, f"Short: scene {n}'s line rewritten by {user}; script v{item['v']} waits for approval")
    db.commit()
    return {"version": item["v"]}


@router.put("/shorts/{eid}/scenes/{n}")
def put_scene(eid: int, n: int, body: SceneEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner edits a scene's prompts (free) or its line (the script then waits for approval again)."""
    ep = _episode(db, eid)
    if body.text is not None:
        v = stored(db, eid)
        if not same_text(scene_or_404(v, n)["text"], body.text):
            rewrite_line(db, ep, n, body.text, user)
    v = stored(db, eid)
    s = scene_or_404(v, n)
    if body.picture_prompt is not None:
        s["picture_prompt"] = body.picture_prompt.strip()
        s["prompt_source"] = "edited"
    if body.animation_prompt is not None:
        s["animation_prompt"] = body.animation_prompt.strip()
        s["prompt_source"] = "edited"
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class PromptsIn(PaidIn):
    use_template: bool = False


def write_prompts(db: Session, ep: Episode, confirm: float | None, use_template: bool, user: str) -> dict:
    """Picture + animation prompts for every scene: GPT in batches (one confirmed total), or the templates (free)."""
    v = stored(db, ep.id)
    sc = approved_script(v)
    scs = scenes_of(v)
    if not sc or not scs:
        raise HTTPException(409, "approve the script first: the scenes come from it")
    names = names_of(db, v)
    if use_template:
        for s in scs:
            s.update(picture_prompt=picture_template(s["text"], names), animation_prompt=animation_template(s["text"]),
                     prompt_source=TEMPLATE_LABEL)
        save(db, ep.id, v)
        db.commit()
        return {"usd": 0.0, "source": TEMPLATE_LABEL}
    batches = [scs[i:i + PROMPT_BATCH] for i in range(0, len(scs), PROMPT_BATCH)]
    est = gpt_estimate(db, PROMPTS_SYSTEM, prompts_message(batches[0], names, aspect_of(v), sc["text"]), len(batches))
    if confirm is None or confirm + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"writing the scene prompts can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    got: dict[int, dict] = {}
    usd = 0.0
    for b in batches:
        one = gpt_estimate(db, PROMPTS_SYSTEM, prompts_message(b, names, aspect_of(v), sc["text"]))
        out = gpt_call(db, PROMPTS_SYSTEM, prompts_message(b, names, aspect_of(v), sc["text"]), one["usd_max"], "the scene prompts", one)
        usd += out["usd"]
        for x in parse_json(out["text"], "scenes").get("scenes") or []:
            if isinstance(x, dict) and str(x.get("scene", "")).isdigit():
                got[int(x["scene"])] = x
    v = stored(db, ep.id)
    for s in scenes_of(v):
        x = got.get(s["n"])
        if x and str(x.get("picture") or "").strip():
            s.update(picture_prompt=str(x["picture"]).strip()[:4000],
                     animation_prompt=str(x.get("animation") or animation_template(s["text"])).strip()[:1500],
                     prompt_source=est["model"])
        elif not s.get("picture_prompt"):
            s.update(picture_prompt=picture_template(s["text"], names), animation_prompt=animation_template(s["text"]),
                     prompt_source=TEMPLATE_LABEL)
    v["usd"] = round(float(v.get("usd") or 0) + usd, 6)
    save(db, ep.id, v)
    _event(db, ep.id, f"Short: scene prompts written by {est['model']} for {user} (${usd:.4f})")
    db.commit()
    return {"usd": round(usd, 6), "source": est["model"]}


@router.post("/shorts/{eid}/scenes/prompts")
def post_prompts(eid: int, body: PromptsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    write_prompts(db, ep, body.confirm_usd, body.use_template, user)
    return view(db, ep)


# ================================================================== step 5: voice
class VoiceIn(PaidIn):
    voice: str = Field(default=tts.DEFAULT_VOICE, max_length=40)
    style: str = Field(default=tts.DEFAULT_STYLE, max_length=200)
    use_free_tier: bool = False


def make_voice(db: Session, ep: Episode, body: VoiceIn, user: str) -> Job:
    """Paid (Gemini speech + the word timings, both priced first; the free tier only when ticked): one narration take."""
    if body.voice not in tts.VOICES:
        raise HTTPException(422, f"the voice must be one of {', '.join(tts.VOICES)}")
    v = stored(db, ep.id)
    sc = approved_script(v)
    if not sc:
        raise HTTPException(409, "approve the script first (step 3)")
    if _active(db, ep.id, (JOB_VOICE,)):
        raise HTTPException(409, "the narration is already being made")
    if not secret("gemini_api_key", db):
        raise HTTPException(409, "save the Gemini API key under Settings > Credentials (or upload your own voice)")
    v.setdefault("voice", {}).update(voice=body.voice, style=body.style, use_free_tier=body.use_free_tier)
    save(db, ep.id, v)
    est = voice_estimate(db, v, body.use_free_tier)
    if est.get("blocked"):
        raise HTTPException(409, est["blocked"])
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"the narration can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    tid = pysecrets.token_hex(4)
    job = enqueue(db, JOB_VOICE, episode_id=ep.id,
                  payload={"take_id": tid, "source": "gemini", "voice": body.voice, "style": body.style, "text": sc["text"],
                           "script_version": sc["v"], "free": est["tier"] == "free", "usd_max": est["usd_max"], "by": user})
    _event(db, ep.id, f"Short: narration asked by {user} ({body.voice}, \"{body.style}\"; {est['label']})")
    db.commit()
    return job


@router.post("/shorts/{eid}/voice")
def post_voice(eid: int, body: VoiceIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    make_voice(db, ep, body, user)
    return view(db, ep)


class VoiceSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: str = Field(default=tts.DEFAULT_VOICE, max_length=40)
    style: str = Field(default=tts.DEFAULT_STYLE, max_length=200)
    use_free_tier: bool = False


@router.put("/shorts/{eid}/voice/settings")
def put_voice_settings(eid: int, body: VoiceSettingsIn, db: Session = Depends(get_db)):
    """The voice, the style and the free-tier tick (free); the narration's price in the view follows them."""
    ep = _episode(db, eid)
    if body.voice not in tts.VOICES:
        raise HTTPException(422, f"the voice must be one of {', '.join(tts.VOICES)}")
    v = stored(db, eid)
    v.setdefault("voice", {}).update(voice=body.voice, style=body.style.strip(), use_free_tier=body.use_free_tier)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


MAX_UPLOAD = 60 * 1024 * 1024
AUDIO_TYPES = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac",
               "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/flac": ".flac"}


async def _read_upload(request: Request, folder: Path, name: str) -> tuple[Path, str]:
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = AUDIO_TYPES.get(ctype)
    if not ext:
        raise HTTPException(415, "upload an audio file (WAV, MP3, M4A, AAC, OGG, WEBM or FLAC)")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}{ext}"
    size = 0
    with open(path, "wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, "the file is larger than 60 MB")
            f.write(chunk)
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "the file is empty")
    return path, ctype


@router.put("/shorts/{eid}/voice/upload")
async def upload_voice(eid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's own voice (free to upload; the word timings are free or priced as shown: OpenAI transcription asks
    for confirm_usd in the query). It waits for approval like a generated take."""
    from .config import get_settings
    ep = _episode(db, eid)
    v = stored(db, eid)
    if not approved_script(v):
        raise HTTPException(409, "approve the script first (step 3): the scenes are timed against it")
    if _active(db, eid, (JOB_VOICE,)):
        raise HTTPException(409, "the narration is already being made")
    tr = transcription_cost(db, 600)
    try:
        confirm = float(request.query_params["confirm_usd"]) if "confirm_usd" in request.query_params else None
    except ValueError:
        confirm = None
    if tr["usd"] > 0 and (confirm is None or confirm + 1e-9 < tr["usd"]):
        raise HTTPException(409, f"the word timings can cost up to ${tr['usd']:.4f} (OpenAI transcription of up to 10 min): "
                                 "confirm that amount to upload (nothing was sent)")
    tid = pysecrets.token_hex(4)
    path, ctype = await _read_upload(request, get_settings().work_dir / "uploads" / f"short-{eid}", f"voice-{tid}")
    k = f"episodes/{eid}/short/voice-upload-{tid}{path.suffix}"
    storage().put_file(k, path, ctype)
    a = Asset(episode_id=eid, kind="audio", label="Narration (your own voice)", storage_key=k, content_type=ctype,
              size=path.stat().st_size, sha256=sha256_file(path))
    db.add(a)
    db.flush()
    path.unlink(missing_ok=True)
    enqueue(db, JOB_VOICE, episode_id=eid, payload={"take_id": tid, "source": "upload", "asset_id": a.id,
                                                    "script_version": approved_script(v)["v"], "usd_max": tr["usd"], "by": user})
    _event(db, eid, f"Short: own narration uploaded by {user} ({tr['label']})")
    db.commit()
    return view(db, ep)


class TakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_id: str | None = Field(default=None, max_length=20)        # None withdraws the approval


@router.post("/shorts/{eid}/voice/approve")
def approve_voice(eid: int, body: TakeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner listened: this take is the narration (only this click)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.take_id is not None:
        t = next((x for x in takes_of(v) if x["id"] == body.take_id), None)
        if t is None:
            raise HTTPException(404, "no such take")
        if not take_fits(v, t):
            raise HTTPException(409, "this take reads an older script: make the narration again for the approved script")
    v.setdefault("voice", {}).update(approved=body.take_id, approved_by=user if body.take_id else None)
    save(db, eid, v)
    _event(db, eid, f"Short: narration take {body.take_id} approved by {user}" if body.take_id
           else f"Short: narration approval withdrawn by {user}", "approval")
    db.commit()
    return view(db, ep)


# ================================================================== step 6: pictures
class PictureIn(PaidIn):
    prompt: str | None = Field(default=None, max_length=4000)


def make_picture(db: Session, ep: Episode, n: int, confirm: float | None, prompt: str | None, user: str) -> Job:
    """Paid (one Nano Banana image, the price shown and confirmed first): a new picture for one scene with the chosen
    characters' approved masters as the reference images. It waits for the owner's approval."""
    from .stick_pipeline import image_provider
    v = stored(db, ep.id)
    s = scene_or_404(v, n)
    miss = masters_ready(db, v)
    if miss:
        raise HTTPException(409, "approve a master for " + ", ".join(miss) + " first (Characters, or the Cast flow)")
    if _active(db, ep.id, (JOB_PICTURE,), n):
        raise HTTPException(409, f"scene {n}'s picture is already being made")
    prov = image_provider(db)
    cost = picture_cost(db, 1)
    require_exact(cost["usd"], confirm)
    text = (prompt or "").strip() or s.get("picture_prompt") or picture_template(s["text"], names_of(db, v))
    if prompt and prompt.strip():
        s["picture_prompt"] = prompt.strip()
        s["prompt_source"] = "edited"
        save(db, ep.id, v)
    chars = [c.id for c in characters_of(db, v)]
    job = enqueue(db, JOB_PICTURE, episode_id=ep.id,
                  payload={"n": n, "scenes_version": (v.get("scenes") or {}).get("version"), "prompt": text,
                           "characters": chars, "aspect": aspect_of(v), "provider": prov["id"], "usd": cost["usd"], "by": user})
    _event(db, ep.id, f"Short: scene {n} picture asked by {user} ({cost['label']})")
    db.commit()
    return job


@router.post("/shorts/{eid}/scenes/{n}/picture")
def post_picture(eid: int, n: int, body: PictureIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    make_picture(db, ep, n, body.confirm_usd, body.prompt, user)
    return view(db, ep)


@router.post("/shorts/{eid}/pictures/all")
def post_pictures_all(eid: int, body: PaidIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: one picture for every scene that has none yet; the total is confirmed first."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    todo = [s["n"] for s in scenes_of(v) if not s.get("pictures") and not _active(db, eid, (JOB_PICTURE,), s["n"])]
    if not todo:
        raise HTTPException(409, "every scene has a picture already")
    total = picture_cost(db, len(todo))
    require_exact(total["usd"], body.confirm_usd)
    each = picture_cost(db, 1)["usd"]
    for n in todo:
        make_picture(db, ep, n, each, None, user)
    return view(db, ep)


class PickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: int


def _pick(db: Session, eid: int, n: int, what: str, asset_id: int, approve: bool | None, user: str) -> dict:
    ep = _episode(db, eid)
    v = stored(db, eid)
    s = scene_or_404(v, n)
    pool = s.get("pictures" if what == "picture" else "clips") or []
    if asset_id not in [p["asset_id"] for p in pool]:
        raise HTTPException(422, f"not a {what} of scene {n}")
    if approve is None:
        s.update({f"{what}_chosen": asset_id, f"{what}_approved": False})
        msg = f"Short: scene {n} {what} {asset_id} chosen by {user} (not approved yet)"
    else:
        s.update({f"{what}_chosen": asset_id, f"{what}_approved": approve})
        msg = f"Short: scene {n} {what} {asset_id} {'approved' if approve else 'approval withdrawn'} by {user}"
    save(db, eid, v)
    _event(db, eid, msg, "approval" if approve is not None else "episode")
    db.commit()
    return view(db, ep)


@router.post("/shorts/{eid}/scenes/{n}/picture/approve")
def approve_picture(eid: int, n: int, body: PickIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _pick(db, eid, n, "picture", body.asset_id, True, user)


@router.post("/shorts/{eid}/scenes/{n}/picture/unapprove")
def unapprove_picture(eid: int, n: int, body: PickIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _pick(db, eid, n, "picture", body.asset_id, False, user)


@router.post("/shorts/{eid}/scenes/{n}/picture/choose")
def choose_picture(eid: int, n: int, body: PickIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _pick(db, eid, n, "picture", body.asset_id, None, user)


@router.post("/shorts/{eid}/scenes/{n}/clip/approve")
def approve_clip(eid: int, n: int, body: PickIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _pick(db, eid, n, "clip", body.asset_id, True, user)


@router.post("/shorts/{eid}/scenes/{n}/clip/choose")
def choose_clip(eid: int, n: int, body: PickIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _pick(db, eid, n, "clip", body.asset_id, None, user)


# ================================================================== step 7: motion
class MotionIn(PaidIn):
    engine: Literal["wan_gpu", "code_kit", "omni_flash"] = "wan_gpu"
    scenes: list[int] | None = Field(default=None, max_length=300)
    prompt: str | None = Field(default=None, max_length=1500)       # one scene only (the chat's redo_clip)


def _slot_seconds(v: dict, s: dict) -> float:
    tm = timing(v)
    if tm:
        i = next(i for i, x in enumerate(scenes_of(v)) if x["n"] == s["n"])
        return tm["rows"][i]["seconds"]
    return max(SCENE_MIN_S, seconds_of(s["text"]))


def start_motion(db: Session, ep: Episode, body: MotionIn, user: str) -> Job:
    """Paid (rented GPU time, "at most" confirmed first): image-to-video for the scenes on ONE ComfyUI session, turned
    off at the end. Default: every scene with an approved picture and no clip from it yet."""
    from . import comfy_session as CS
    from . import gpu
    if not ENGINES[body.engine]["ready"]:
        raise HTTPException(409, f"{ENGINES[body.engine]['label']} is coming soon: choose Wan 2.2 on the rented GPU")
    v = stored(db, ep.id)
    if body.scenes:
        want = []
        for n in body.scenes:
            s = scene_or_404(v, n)
            if not (s.get("picture_approved") and s.get("picture_chosen")):
                raise HTTPException(409, f"approve scene {n}'s picture first: only approved pictures are animated")
            want.append(s)
    else:
        want = [s for s in scenes_of(v) if needs_clip(s)]
    if not want:
        raise HTTPException(409, "no approved picture is waiting for a clip")
    if body.prompt and len(want) != 1:
        raise HTTPException(422, "a new animation prompt is for one scene at a time")
    a = CS.availability(db)
    if not a["ok"]:
        raise HTTPException(409, a["reason"])
    if _active(db, ep.id, (JOB_MOTION,)):
        raise HTTPException(409, "the scenes are already being animated")
    est = motion_estimate(db, len(want))
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"animating {len(want)} scene(s) can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    c = get_section(db, "gpu")
    fig = gpu.month_figures(db)
    if fig["committed_usd"] + est["usd_max"] > float(c["monthly_cap_usd"]) + 1e-9:
        raise HTTPException(409, f"Paused: this run (up to ${est['usd_max']:.2f}) would pass the monthly GPU cap "
                                 f"(${fig['committed_usd']:.2f} committed of ${float(c['monthly_cap_usd']):.2f})")
    if est["minutes_max"] > int(c["max_lifetime_minutes"]) - 5:
        raise HTTPException(409, "this run is longer than the maximum GPU session: raise it in Settings > GPU worker or animate fewer scenes")
    if body.prompt:
        want[0]["animation_prompt"] = body.prompt.strip()
        want[0]["prompt_source"] = "edited"
        save(db, ep.id, v)
    items = [{"n": s["n"], "picture": s["picture_chosen"],
              "prompt": s.get("animation_prompt") or animation_template(s["text"]),
              "frames": wan_length(_slot_seconds(v, s))} for s in want]
    job = enqueue(db, JOB_MOTION, episode_id=ep.id,
                  payload={"scenes": [x["n"] for x in items], "items": items, "aspect": aspect_of(v),
                           "scenes_version": (v.get("scenes") or {}).get("version"), "confirm_usd": float(body.confirm_usd),
                           "estimate": est, "backend": "gpu", "by": user})
    _event(db, ep.id, f"Short: {len(items)} scene(s) to animate asked by {user} ({est['label']})")
    db.commit()
    return job


@router.post("/shorts/{eid}/motion")
def post_motion(eid: int, body: MotionIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    start_motion(db, ep, body, user)
    return view(db, ep)


def wan_i2v_graph(image: str, prompt: str, seed: int, prefix: str, width: int, height: int, length: int) -> dict:
    """Wan 2.2 i2v 14B (the owner-proven graph, anim.py wan()): high-noise model for steps 0-2, low-noise for 2-4, each
    with its lightx2v 4-step LoRA, ModelSamplingSD3 shift 5, CFG 1, euler/simple, 16 fps."""
    from .reactions import WAN_MODELS
    hi, lo, lhi, llo, te, vae = [m["filename"] for m in WAN_MODELS]
    common = {"steps": WAN_STEPS, "cfg": WAN_CFG, "sampler_name": "euler", "scheduler": "simple",
              "positive": ["w", 0], "negative": ["w", 1]}
    return {"i": {"class_type": "LoadImage", "inputs": {"image": image}},
            "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": te, "type": "wan", "device": "default"}},
            "v": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
            "uh": {"class_type": "UNETLoader", "inputs": {"unet_name": hi, "weight_dtype": "default"}},
            "ul": {"class_type": "UNETLoader", "inputs": {"unet_name": lo, "weight_dtype": "default"}},
            "lh": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["uh", 0], "lora_name": lhi, "strength_model": 1.0}},
            "ll": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ul", 0], "lora_name": llo, "strength_model": 1.0}},
            "sh": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lh", 0], "shift": WAN_SHIFT}},
            "sl": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["ll", 0], "shift": WAN_SHIFT}},
            "p": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": prompt.strip()}},
            "n": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": NEGATIVE}},
            "w": {"class_type": "WanImageToVideo", "inputs": {"positive": ["p", 0], "negative": ["n", 0], "vae": ["v", 0],
                  "start_image": ["i", 0], "width": width, "height": height, "length": length, "batch_size": 1}},
            "k1": {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["sh", 0], "add_noise": "enable", "noise_seed": seed,
                   "latent_image": ["w", 2], "start_at_step": 0, "end_at_step": WAN_SPLIT, "return_with_leftover_noise": "enable"}},
            "k2": {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["sl", 0], "add_noise": "disable", "noise_seed": 0,
                   "latent_image": ["k1", 0], "start_at_step": WAN_SPLIT, "end_at_step": WAN_STEPS, "return_with_leftover_noise": "disable"}},
            "d": {"class_type": "VAEDecode", "inputs": {"samples": ["k2", 0], "vae": ["v", 0]}},
            "cv": {"class_type": "CreateVideo", "inputs": {"images": ["d", 0], "fps": WAN_FPS}},
            "sv": {"class_type": "SaveVideo", "inputs": {"video": ["cv", 0], "filename_prefix": "video/" + prefix, "format": "auto", "codec": "auto"}}}


# ================================================================== step 8: music, captions, assembly
class OptionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captions: bool | None = None
    music_enabled: bool | None = None


@router.put("/shorts/{eid}/options")
def put_options(eid: int, body: OptionsIn, db: Session = Depends(get_db)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.captions is not None:
        v["captions"] = body.captions
    if body.music_enabled is not None:
        if body.music_enabled and not (v.get("music") or {}).get("asset_id"):
            raise HTTPException(409, "upload the music first")
        v.setdefault("music", {})["enabled"] = body.music_enabled
    save(db, eid, v)
    db.commit()
    return view(db, ep)


@router.put("/shorts/{eid}/music")
async def upload_music(eid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's music bed (free). It is levelled automatically to 6 dB under the voice when the short is put
    together. Only upload music you have the right to use."""
    from .config import get_settings
    ep = _episode(db, eid)
    tid = pysecrets.token_hex(4)
    path, ctype = await _read_upload(request, get_settings().work_dir / "uploads" / f"short-{eid}", f"music-{tid}")
    k = f"episodes/{eid}/short/music-{tid}{path.suffix}"
    storage().put_file(k, path, ctype)
    a = Asset(episode_id=eid, kind="audio", label="Music bed", storage_key=k, content_type=ctype, size=path.stat().st_size,
              sha256=sha256_file(path))
    db.add(a)
    db.flush()
    path.unlink(missing_ok=True)
    v = stored(db, eid)
    v["music"] = {"asset_id": a.id, "enabled": True, "by": user, "at": time.time()}
    save(db, eid, v)
    _event(db, eid, f"Short: music uploaded by {user}")
    db.commit()
    return view(db, ep)


def start_assembly(db: Session, ep: Episode, user: str) -> Job:
    """Free: queue the assembly. Refused without an approved narration, while a scene has no clip or approved picture,
    without FFmpeg, or while one runs."""
    from .config import get_settings
    if not get_settings().ffmpeg:
        raise HTTPException(409, "FFmpeg is not configured on the studio server, so the short cannot be put together")
    v = stored(db, ep.id)
    p = assembly_plan(db, ep, v)
    if not scenes_of(v):
        raise HTTPException(409, "there are no scenes yet")
    if not p["voice_ok"]:
        raise HTTPException(409, "approve a narration take that reads the approved script first (step 5)")
    if p["missing"]:
        raise HTTPException(409, "scene(s) " + ", ".join(map(str, p["missing"])) + " have no clip or approved picture yet")
    if _active(db, ep.id, (JOB_ASSEMBLY,)):
        raise HTTPException(409, "the short is already being put together")
    job = enqueue(db, JOB_ASSEMBLY, episode_id=ep.id, payload={"by": user, "hash": p["hash"]})
    _event(db, ep.id, f"Short: assembly asked by {user} ({len(p['rows'])} scenes, free)")
    db.commit()
    return job


@router.post("/shorts/{eid}/assemble")
def post_assemble(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    start_assembly(db, ep, user)
    return view(db, ep)


class FinalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cut_id: str | None = Field(default=None, max_length=20)


@router.post("/shorts/{eid}/final/approve")
def approve_final(eid: int, body: FinalIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's click: this cut is the short (null withdraws it)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    cut = next((c for c in (v.get("final") or {}).get("cuts") or [] if c["id"] == body.cut_id), None) if body.cut_id else None
    if body.cut_id and cut is None:
        raise HTTPException(404, "no such cut")
    v.setdefault("final", {}).update(approved=body.cut_id, approved_by=user if body.cut_id else None)
    if cut:
        ep.video_asset_id = cut["asset_id"]
        ep.stage = "final_approved"
    else:
        ep.stage = "video_review" if (v.get("final") or {}).get("cuts") else ep.stage
    save(db, eid, v)
    _event(db, eid, f"Short: final video approved by {user}" if cut else f"Short: final approval withdrawn by {user}", "approval")
    db.commit()
    return view(db, ep)


# ================================================================== step 9: publish pack
def write_publish(db: Session, ep: Episode, confirm: float | None, user: str) -> dict:
    v = stored(db, ep.id)
    sc = approved_script(v)
    if not sc:
        raise HTTPException(409, "approve the script first")
    idea = v.get("idea") or {}
    names = names_of(db, v)
    out = gpt_call(db, PUBLISH_SYSTEM, publish_message(idea.get("title") or ep.title, sc["text"], names, idea.get("label") or "fiction"),
                   confirm, "writing the publish pack")
    d = parse_json(out["text"])
    titles = [str(t).strip()[:100] for t in d.get("titles") or [] if str(t).strip()][:5]
    tags = [("#" + str(t).strip().lstrip("#"))[:40] for t in d.get("hashtags") or [] if str(t).strip()][:10]
    v = stored(db, ep.id)
    pub = v.setdefault("publish", {})
    pub.update(thumbnail_prompt=str(d.get("thumbnail_prompt") or thumbnail_template(ep.title, names)).strip()[:2000],
               thumbnail_text=" ".join(str(d.get("thumbnail_text") or "").split()[:5]), titles=titles,
               description=str(d.get("description") or "").strip()[:4000], hashtags=tags, model=out["model"],
               at=time.time(), check=bool(idea.get("check")))
    v["usd"] = round(float(v.get("usd") or 0) + out["usd"], 6)
    save(db, ep.id, v)
    _event(db, ep.id, f"Short: publish pack written by {out['model']} for {user} (${out['usd']:.4f})")
    db.commit()
    return {"usd": out["usd"]}


@router.post("/shorts/{eid}/publish/write")
def post_publish(eid: int, body: PaidIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    write_publish(db, ep, body.confirm_usd, user)
    return view(db, ep)


class PublishEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thumbnail_prompt: str | None = Field(default=None, max_length=2000)
    titles: list[str] | None = Field(default=None, max_length=5)
    title: str | None = Field(default=None, max_length=100)            # the chosen title
    description: str | None = Field(default=None, max_length=4000)
    hashtags: list[str] | None = Field(default=None, max_length=10)


@router.put("/shorts/{eid}/publish")
def put_publish(eid: int, body: PublishEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's edits (free). The chosen title, the description and the hashtags are copied to the episode's
    publishing draft (nothing is uploaded: publishing stays its own step)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    pub = v.setdefault("publish", {})
    for k in ("thumbnail_prompt", "titles", "title", "description", "hashtags"):
        val = getattr(body, k)
        if val is not None:
            pub[k] = val
    rec = db.query(PublishRecord).filter_by(episode_id=eid).one_or_none()
    if rec is None:
        rec = PublishRecord(episode_id=eid)
        db.add(rec)
    if pub.get("title"):
        rec.title = pub["title"][:100]
    rec.description = (pub.get("description") or "") + ("\n\n" + " ".join(pub.get("hashtags") or []) if pub.get("hashtags") else "")
    rec.tags = [t.lstrip("#") for t in pub.get("hashtags") or []][:15]
    save(db, eid, v)
    db.commit()
    return view(db, ep)


def make_thumbnail(db: Session, ep: Episode, confirm: float | None, user: str) -> Job:
    from .stick_pipeline import image_provider
    v = stored(db, ep.id)
    miss = masters_ready(db, v)
    if miss:
        raise HTTPException(409, "approve a master for " + ", ".join(miss) + " first")
    if _active(db, ep.id, (JOB_THUMB,)):
        raise HTTPException(409, "the thumbnail is already being made")
    prov = image_provider(db)
    cost = picture_cost(db, 1)
    require_exact(cost["usd"], confirm)
    pub = v.get("publish") or {}
    prompt = pub.get("thumbnail_prompt") or thumbnail_template(ep.title, names_of(db, v))
    job = enqueue(db, JOB_THUMB, episode_id=ep.id,
                  payload={"prompt": prompt, "characters": [c.id for c in characters_of(db, v)], "aspect": aspect_of(v),
                           "provider": prov["id"], "usd": cost["usd"], "by": user})
    _event(db, ep.id, f"Short: thumbnail asked by {user} ({cost['label']})")
    db.commit()
    return job


@router.post("/shorts/{eid}/publish/thumbnail")
def post_thumbnail(eid: int, body: PaidIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    make_thumbnail(db, ep, body.confirm_usd, user)
    return view(db, ep)


@router.post("/shorts/{eid}/publish/thumbnail/approve")
def approve_thumbnail(eid: int, body: PickIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    pub = v.setdefault("publish", {})
    if body.asset_id not in [t["asset_id"] for t in pub.get("thumbnails") or []]:
        raise HTTPException(422, "not a thumbnail of this short")
    pub["thumbnail_approved"] = body.asset_id
    rec = db.query(PublishRecord).filter_by(episode_id=eid).one_or_none()
    if rec is None:
        rec = PublishRecord(episode_id=eid, title=(pub.get("title") or ep.title)[:100])
        db.add(rec)
    rec.thumbnail_asset_id = body.asset_id
    save(db, eid, v)
    _event(db, eid, f"Short: thumbnail {body.asset_id} approved by {user}", "approval")
    db.commit()
    return view(db, ep)


# ================================================================== chat under each scene (shot_chat.py)
def chat_context(db: Session, step: str, eid: int, item: str) -> dict:
    v = stored(db, eid)
    ep = db.get(Episode, eid)
    cx = {"item": f"Narrated short \"{ep.title}\"", "house_look": HOUSE_LOOK,
          "characters_as_references": names_line(names_of(db, v)), "format": aspect_of(v)}
    sc = approved_script(v) or current_script(v)
    if step in ("short_picture", "short_clip"):
        s = scene_or_404(v, int(item))
        cx.update(scene=s["n"], line=s["text"], picture_prompt=s.get("picture_prompt") or "",
                  animation_prompt=s.get("animation_prompt") or "", pictures=len(s.get("pictures") or []),
                  picture_approved=bool(s.get("picture_approved")), clips=len(s.get("clips") or []))
        cx["item"] += f", scene {s['n']} ({'picture' if step == 'short_picture' else 'clip'})"
    elif step == "short_script":
        cx["script"] = (sc or {}).get("text", "")
        cx["scenes"] = [{"scene": s["n"], "line": s["text"]} for s in scenes_of(v)]
    elif step == "short_voice":
        vo = v.get("voice") or {}
        cx.update(voice=vo.get("voice") or tts.DEFAULT_VOICE, style=vo.get("style") or tts.DEFAULT_STYLE,
                  voices=list(tts.VOICES), takes=len(takes_of(v)), script=(sc or {}).get("text", "")[:3000])
    return cx


def chat_cost(db: Session, eid: int, p: dict) -> dict | None:
    v = stored(db, eid)
    if p["type"] == "redo_picture":
        return picture_cost(db, 1)
    if p["type"] == "redo_clip":
        e = motion_estimate(db, 1)
        return {"usd": e["usd_max"], "label": f"up to ${e['usd_max']:.2f} of GPU time ({e['label']})"}
    if p["type"] == "regenerate_voice":
        e = voice_estimate(db, v, bool((v.get("voice") or {}).get("use_free_tier")))
        if not e or e.get("blocked"):
            return {"usd": None, "label": (e or {}).get("blocked") or "approve the script first"}
        return {"usd": e["usd_max"], "label": e["label"]}
    return None


def chat_apply(db: Session, step: str, eid: int, item: str, p: dict, confirm: float | None, user: str) -> dict:
    ep = _episode(db, eid)
    t = p["type"]
    if t == "redo_picture":
        j = make_picture(db, ep, int(item), confirm, p["prompt"], user)
        return {"done": f"A new picture for scene {item} is being made (it waits for your approval).", "job_id": j.id}
    if t == "redo_clip":
        j = start_motion(db, ep, MotionIn(scenes=[int(item)], prompt=p["prompt"], confirm_usd=confirm), user)
        return {"done": f"Scene {item} is being animated again on the rented GPU.", "job_id": j.id}
    if t == "rewrite_line":
        r = rewrite_line(db, ep, int(p["scene"]), p["text"], user)
        return {"done": f"Scene {p['scene']}'s line was rewritten; script v{r['version']} waits for your approval."}
    if t == "regenerate_voice":
        v = stored(db, eid)
        vo = v.get("voice") or {}
        j = make_voice(db, ep, VoiceIn(voice=p.get("voice") or vo.get("voice") or tts.DEFAULT_VOICE,
                                       style=p.get("style") or vo.get("style") or tts.DEFAULT_STYLE,
                                       use_free_tier=bool(vo.get("use_free_tier")), confirm_usd=confirm), user)
        return {"done": "The narration is being made again (it waits for your approval).", "job_id": j.id}
    raise HTTPException(409, "this proposal has nothing to apply")


# ================================================================== the jobs
from .tasks import Ctx, store_asset, task  # noqa: E402


def _fresh(db: Session, eid: int, p: dict) -> dict:
    db.expire_all()
    v = stored(db, eid)
    if p.get("scenes_version") is not None and (v.get("scenes") or {}).get("version") != p["scenes_version"]:
        raise ValueError("the scenes were split again since this was asked: ask again")
    return v


def _master_files(db: Session, cids: list[int], folder: Path) -> tuple[list[Path], list[str]]:
    from .stick_pipeline import approved_master
    files, names = [], []
    for cid in cids:
        c = db.get(Character, cid)
        m = approved_master(db, cid) if c else None
        if m is None:
            raise ValueError(f"{c.name if c else cid} has no approved master any more: approve one and ask again")
        files.append(storage().get_to_file(m.storage_key, folder / f"master-{cid}.png"))
        names.append(c.name)
    return files, names


@task
def short_picture(ctx: Ctx) -> dict:
    """One scene picture (paid, one image): a new picture of the scene, chosen, NOT approved."""
    from .stick_pipeline import run_images
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    eid, n = job.episode_id, int(p["n"])
    _fresh(db, eid, p)
    folder = ctx.folder("episodes", eid, "short", f"picture-job{job.id}")
    refs, names = _master_files(db, p.get("characters") or [], folder)
    full = picture_request(p["prompt"], names, p["aspect"])
    asset = None
    for _i, f in run_images(ctx, p["provider"], full, refs, 1, float(p["usd"]), p["aspect"], folder, f"short {eid} scene {n}"):
        asset = store_asset(db, ep_id=eid, src=f, key=f"episodes/{eid}/short/scene-{n:03d}-job{job.id}.png", kind="short-picture",
                            label=f"Scene {n} picture", content_type="image/png", job_id=job.id)
        db.commit()
    v = _fresh(db, eid, p)
    s = scene_or_404(v, n)
    s.setdefault("pictures", []).append({"asset_id": asset.id, "at": time.time(), "prompt": p["prompt"], "job_id": job.id,
                                         "characters": p.get("characters") or [], "usd": float(p["usd"])})
    s.update(picture_chosen=asset.id, picture_approved=False)
    v["usd"] = round(float(v.get("usd") or 0) + float(p["usd"]), 6)
    save(db, eid, v)
    _event(db, eid, f"Short: scene {n} picture made, waiting for approval")
    db.commit()
    return {"n": n, "asset_id": asset.id, "usd": float(p["usd"])}


def _words_from(tr: dict) -> list[dict]:
    out = []
    for w in tr.get("words") or []:
        try:
            out.append({"word": str(w["word"]).strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)})
        except (KeyError, TypeError, ValueError):
            continue
    return [w for w in out if w["word"]]


def _audio_seconds(path: Path) -> float | None:
    from . import media
    if path.suffix == ".wav":
        import wave
        try:
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:   # noqa: BLE001 -- not a plain PCM WAV: ask FFprobe
            pass
    try:
        return media.probe(path).get("duration")
    except media.MediaError:
        return None


@task
def short_voice(ctx: Ctx) -> dict:
    """One narration take: Gemini speech (or the owner's upload), then the word timings. It waits for approval."""
    from .analysis import transcribe
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    eid = job.episode_id
    folder = ctx.folder("episodes", eid, "short", f"voice-job{job.id}")
    cfg = get_section(db, "short")
    usd = 0.0
    if p["source"] == "gemini":
        out = folder / "narration.wav"
        r = tts.synthesize(p["text"], p["voice"], p["style"], cfg, out, free=bool(p.get("free")), log=ctx.log)
        usd = tts.cost_of(r["usage"], cfg, bool(p.get("free")))
        a = store_asset(db, ep_id=eid, src=out, key=f"episodes/{eid}/short/voice-{p['take_id']}.wav", kind="audio",
                        label=f"Narration ({p['voice']})", content_type="audio/wav", job_id=job.id)
        db.commit()
        local, seconds = out, r["seconds"]
    else:
        a = db.get(Asset, int(p["asset_id"]))
        local = storage().get_to_file(a.storage_key, folder / ("upload" + (Path(a.storage_key).suffix or ".wav")))
        seconds = _audio_seconds(local)
    tcfg = get_section(db, "transcription")
    words, warn = [], ""
    if (tcfg.get("provider") or "none") == "none":
        warn = "no transcription provider (Settings > Transcription): the scene timing is estimated from the words"
    else:
        ctx.log(f"Word timings with {tcfg.get('provider')}")
        tr = transcribe(tcfg, local)
        words = _words_from(tr)
        seconds = seconds or tr.get("duration")
        if tcfg.get("provider") == "openai":
            usd += round(math.ceil(float(seconds or 60)) / 60 * float(cfg.get("transcribe_usd_per_minute") or 0.006), 6)
    v = stored(db, eid)
    take = {"id": p["take_id"], "asset_id": a.id, "source": p["source"], "voice": p.get("voice"), "style": p.get("style"),
            "text": p.get("text") or "", "script_version": p.get("script_version"), "seconds": round(float(seconds or 0), 3),
            "words": words, "warning": warn, "at": time.time(), "usd": round(usd, 6), "free_tier": bool(p.get("free")),
            "job_id": job.id}
    v.setdefault("voice", {}).setdefault("takes", []).append(take)
    v["voice"]["takes"] = v["voice"]["takes"][-12:]
    v["usd"] = round(float(v.get("usd") or 0) + usd, 6)
    save(db, eid, v)
    _event(db, eid, f"Short: narration take {take['id']} ready ({take['seconds']:.1f} s), waiting for you to listen and approve")
    db.commit()
    return {"take": take["id"], "seconds": take["seconds"], "words": len(words), "usd": round(usd, 6)}


def _motion_run(ctx: Ctx, eid: int, confirm: float):
    """The GPU side of the motion job: reactions._Run's session handling, with this job's own progress line."""
    from . import reactions as R

    class Run(R._Run):
        def stage(self, text: str) -> None:
            self.ctx.log(text)
            self.ctx.job.progress = {"stage": text, "at": time.time()}
            self.db.commit()

        def finish(self, job_id: int) -> None:
            from . import comfy_session as CS
            if not CS.others_waiting(self.db, job_id):
                try:
                    CS.stop(self.db, "short motion finished")
                except Exception as e:   # noqa: BLE001 -- the idle sweep tries again
                    self.ctx.log(f"could not terminate the GPU now ({str(e)[:120]}); the idle sweep will")
    return Run(ctx, eid, 0, confirm)


@task
def short_motion(ctx: Ctx) -> dict:
    """Wan 2.2 i2v for each scene on ONE rented ComfyUI session; each clip is added to its scene (chosen, not
    approved). The GPU is turned off when the job ends (unless another GPU job or the autopilot needs it next)."""
    from . import reactions as R
    from .comfy import ComfyError, video_outputs
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    eid = job.episode_id
    folder = ctx.folder("episodes", eid, "short", f"motion-job{job.id}")
    run = _motion_run(ctx, eid, float(p.get("confirm_usd") or 0))
    w, h = WAN_SIZES[p.get("aspect") or "9:16"]
    made, usd = [], 0.0
    try:
        _fresh(db, eid, p)
        run.session(R.WAN_MODELS)
        cl = run.sess["client"]
        for k, it in enumerate(p["items"], 1):
            if not run.room_for(R.FLF_MIN * 1.5):
                raise ValueError(f"stopped before scene {it['n']}: it would pass the confirmed ${run.confirm:.2f}")
            pic = db.get(Asset, int(it["picture"]))
            local = storage().get_to_file(pic.storage_key, folder / f"scene-{it['n']:03d}.png")
            run.stage(f"Scene {it['n']} ({k} of {len(p['items'])}) on {run.sess['gpu_type']}")
            t0 = time.time()
            prefix = f"short{eid}-s{it['n']:03d}-{uuid.uuid4().hex[:6]}"
            outs = run.run_graph(wan_i2v_graph(cl.upload(local), it["prompt"], random.randint(1, 2**31 - 1), prefix, w, h,
                                               int(it["frames"])), R.FLF_MIN * 1.5)
            files = [f for f in video_outputs(outs) if f.get("type", "output") == "output"]
            if not files:
                raise ComfyError("the GPU returned no video")
            got = cl.download(files[-1], folder / f"clip-{it['n']:03d}{Path(files[-1]['filename']).suffix}")
            spent = float(run.sess["price_per_hour"]) * (time.time() - t0) / 3600
            usd += spent
            a = store_asset(db, ep_id=eid, src=got, key=f"episodes/{eid}/short/clip-{it['n']:03d}-job{job.id}{got.suffix}",
                            kind="short-clip", label=f"Scene {it['n']} clip", content_type="video/mp4", job_id=job.id)
            db.commit()
            v = _fresh(db, eid, p)
            s = scene_or_404(v, int(it["n"]))
            s.setdefault("clips", []).append({"asset_id": a.id, "at": time.time(), "picture": int(it["picture"]),
                                              "prompt": it["prompt"], "frames": int(it["frames"]), "fps": WAN_FPS,
                                              "job_id": job.id, "engine": "wan_gpu"})
            s.update(clip_chosen=a.id, clip_approved=False)
            save(db, eid, v)
            db.commit()
            made.append(it["n"])
    finally:
        run.finish(job.id)
    total = round(run.spent(), 4)
    v = stored(db, eid)
    v["usd"] = round(float(v.get("usd") or 0) + total, 6)
    save(db, eid, v)
    _event(db, eid, f"Short: {len(made)} clip(s) made on the rented GPU (about ${total:.2f}), each waiting for your review")
    db.commit()
    return {"scenes": made, "usd": total}


def render_captions(chunks: list[dict], size: tuple[int, int], folder: Path, log) -> tuple[list, str]:
    """[(start, end, png)] for the caption chunks, drawn by overlay.mjs (mode "short_captions"); ([], warning) without
    Node."""
    from . import acting, engine
    from .assembly import OVERLAY_SCRIPT
    from .config import REPO_ROOT, get_settings
    if not chunks:
        return [], ""
    s = get_settings()
    node = shutil.which(s.node_bin) if s.node_bin else None
    if not node:
        return [], "Node is not available on the server: the captions are left out"
    w, h = size
    spec = {"width": w, "height": h, "hook": "", "band": False, "mode": "short_captions",
            "caption_font": str(acting.FONTS / "Anton-Regular.ttf"),
            "font": str(REPO_ROOT / "skills/directing-stickman-videos/assets/fonts/NotoSans.ttf"),
            "lines": [{"text": c["text"]} for c in chunks], "out": str(folder / "captions")}
    f = folder / "captions.json"
    f.write_text(json.dumps(spec))
    r = subprocess.run([node, str(REPO_ROOT / OVERLAY_SCRIPT), str(f)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(REPO_ROOT), env=engine.env_for_node(), timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        log("caption pictures failed: " + (r.stderr or r.stdout)[-300:])
        return [], "the captions could not be drawn: they are left out"
    pics = json.loads(r.stdout.strip().splitlines()[-1]).get("lines") or []
    return [(c["start"], c["end"], Path(pth)) for c, pth in zip(chunks, pics) if pth], ""


def _level(ff: str, path: Path) -> float | None:
    """The gated RMS level (dBFS) of an audio file, decoded by FFmpeg to 16 kHz mono."""
    import numpy as np
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                       capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not r.stdout:
        return None
    x = np.frombuffer(r.stdout[: len(r.stdout) // 2 * 2], dtype="<i2").astype(np.float64) / 32768.0
    return gated_rms_db(x, 16000)


@task
def short_assembly(ctx: Ctx) -> dict:
    """The short put together on the studio server (free): scenes frame-exact on the narration's word timings, the
    music bed levelled under the voice, the captions laid over. The cut waits for the owner's approval."""
    from .assembly import _run, overlay_graph, probe_frames, segment_command
    from .config import get_settings
    db, job = ctx.db, ctx.job
    eid = job.episode_id
    ep = db.get(Episode, eid)
    s = get_settings()
    ff = s.ffmpeg
    if not ff:
        raise RuntimeError("FFmpeg is not configured on this server (FFMPEG)")
    folder = ctx.folder("episodes", eid, "short", f"assembly-job{job.id}")
    try:
        v = stored(db, eid)
        p = assembly_plan(db, ep, v)
        if p["missing"] or not p["voice_ok"]:
            raise ValueError("a scene lost its clip or picture, or the narration is no longer approved: look at the steps")
        w, h = FORMATS[aspect_of(v)]
        take = approved_take(v)
        va = db.get(Asset, take["asset_id"])
        voice = storage().get_to_file(va.storage_key, folder / ("voice" + (Path(va.storage_key).suffix or ".wav")))
        listing, warnings = [], []
        for r in p["rows"]:
            a = db.get(Asset, r["asset_id"])
            src = storage().get_to_file(a.storage_key, folder / f"src{r['n']:03d}{Path(a.storage_key).suffix or '.bin'}")
            row = {"frames": r["frames"], "source": "still" if r["source"] == "still" else "clip", "trim_start_frames": 0,
                   "stretch": 1.0}
            if r["source"] == "clip":
                real = probe_frames(s.ffprobe, src) or int(r.get("src_frames") or 0)
                fit = fit_short(real, WAN_FPS, r["frames"])
                row["stretch"] = fit["stretch"]
                warnings += [f"scene {r['n']}: {x}" for x in fit["warnings"]]
            seg = folder / f"seg{r['n']:03d}.mp4"
            ctx.log(f"scene {r['n']}: {r['source']}, {r['frames']} frames")
            _run(segment_command(ff, row, src, seg, w, h), f"make scene {r['n']}")
            listing.append(f"file '{seg.resolve().as_posix()}'")
        (folder / "list.txt").write_text("\n".join(listing) + "\n")
        total_frames = sum(r["frames"] for r in p["rows"])
        total = total_frames / FPS
        caps, cw = (render_captions(caption_chunks(take.get("words") or []), (w, h), folder, ctx.log)
                    if captions_on(v) else ([], ""))
        if cw:
            warnings.append(cw)
        if captions_on(v) and not take.get("words"):
            warnings.append("no word timings: the captions are left out")
        music = v.get("music") or {}
        gain = None
        cmd = [ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(folder / "list.txt"), "-i", str(voice)]
        if music.get("enabled") and music.get("asset_id"):
            ma = db.get(Asset, int(music["asset_id"]))
            mus = storage().get_to_file(ma.storage_key, folder / ("music" + (Path(ma.storage_key).suffix or ".mp3")))
            gain = music_gain_db(_level(ff, voice), _level(ff, mus))
            ctx.log(f"music bed: {gain:+.1f} dB (6 dB under the voice, gated RMS)")
            cmd += ["-stream_loop", "-1", "-i", str(mus)]
        first_pic = 3 if gain is not None else 2
        for _a, _b, pic in caps:
            cmd += ["-i", str(pic)]
        graph = mix_graph(gain)
        if caps:
            vg, last = overlay_graph([(a_, b_) for a_, b_, _ in caps], False)
            vg = re.sub(r"\[(\d+):v\]", lambda m: f"[{_shift_input(int(m.group(1)), first_pic)}:v]", vg)
            graph = vg + ";" + graph
            cmd += ["-filter_complex", graph, "-map", f"[{last}]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-r", str(FPS)]
        else:
            cmd += ["-filter_complex", graph, "-map", "0:v", "-c:v", "copy"]
        out = folder / "short.mp4"
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        ctx.log(f"joining {len(p['rows'])} scenes ({total_frames} frames, {total:.2f} s) over the narration")
        _run(cmd, "join the scenes")
        cid = uuid.uuid4().hex[:8]
        a = store_asset(db, ep_id=eid, src=out, key=f"episodes/{eid}/short/final-{cid}.mp4", kind="video",
                        label="Short: final cut (waiting for your approval)", content_type="video/mp4", job_id=job.id)
        db.commit()
        v = stored(db, eid)
        cut = {"id": cid, "asset_id": a.id, "at": time.time(), "by": (job.payload or {}).get("by"), "job_id": job.id,
               "frames": total_frames, "seconds": round(total, 3), "size": [w, h], "hash": p["hash"], "warnings": warnings,
               "captions": bool(caps), "music_gain_db": gain,
               "rows": [{k: r.get(k) for k in ("n", "start", "frames", "source", "stretch", "held_s", "cut_s")} for r in p["rows"]],
               "stills": sum(1 for r in p["rows"] if r["source"] == "still")}
        fin = v.setdefault("final", {})
        fin["cuts"] = ([cut] + (fin.get("cuts") or []))[:10]
        save(db, eid, v)
        ep.stage = "video_review"
        _event(db, eid, f"Short: final cut made ({len(p['rows'])} scenes, {total:.1f} s), waiting for your approval")
        db.commit()
        return {"cut": cid, "frames": total_frames, "seconds": round(total, 3), "usd": 0.0}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@task
def short_thumbnail(ctx: Ctx) -> dict:
    """The thumbnail (paid, one image) with the characters' masters as references; it waits for approval."""
    from .stick_pipeline import run_images
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    eid = job.episode_id
    folder = ctx.folder("episodes", eid, "short", f"thumb-job{job.id}")
    refs, names = _master_files(db, p.get("characters") or [], folder)
    aspect = "16:9" if p.get("aspect") != "9:16" else "9:16"
    full = f"{p['prompt'].strip()}\n\nFrame: {aspect}. " + reference_rules(names).replace(
        " No text, no captions, no speech bubbles, no watermark.", " Only the 3-5 words of bold thumbnail text, nothing else written.")
    asset = None
    for _i, f in run_images(ctx, p["provider"], full, refs, 1, float(p["usd"]), aspect, folder, f"short {eid} thumbnail"):
        asset = store_asset(db, ep_id=eid, src=f, key=f"episodes/{eid}/short/thumbnail-job{job.id}.png", kind="thumbnail",
                            label="Short thumbnail", content_type="image/png", job_id=job.id)
        db.commit()
    v = stored(db, eid)
    pub = v.setdefault("publish", {})
    pub["thumbnails"] = (pub.get("thumbnails") or []) + [{"asset_id": asset.id, "at": time.time(), "prompt": p["prompt"]}]
    v["usd"] = round(float(v.get("usd") or 0) + float(p["usd"]), 6)
    save(db, eid, v)
    _event(db, eid, "Short: thumbnail made, waiting for your approval")
    db.commit()
    return {"asset_id": asset.id, "usd": float(p["usd"])}
