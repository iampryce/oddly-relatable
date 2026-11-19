"""Acting renderer integration: the procedural 2D animator (production/animation) as a production render path.

Used when Settings > Motion selects "procedural-rig". It renders the same segments/episodes as the pose engine, with
the same inputs (approved character art, recorded voice clips, storyboard lines) and the same outputs (an MP4 with the
voice mix, and the mix WAV), so segment planning, the join, revisions and the review gates are unchanged.

  rigs     built from each character's approved poses (the registry the pose engine uses), cached by content hash
  acting   per line: the script's gesture / move / look_at / reactions; missing gestures are inferred from the
           line's expression, so older scripts act too
  lipsync  Rhubarb cues from each recorded clip (cached by the clip's hash)
  audio    clips placed at their line starts and mixed with FFmpeg
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import engine
from .analysis import lipsync
from .config import REPO_ROOT, get_settings
from .settings_store import get_section
from .storage import sha256_file, storage

ANIM = REPO_ROOT / "production" / "animation"
GAP, SCENE_GAP, TAIL, BEAT = 0.12, 0.45, 0.6, 0.35
END_CARD = 1.8   # seconds of the show's end card (the same card the pose engine adds to short episodes)

# Expression words -> a gesture, when the script gives none (scripts written before acting instructions still act).
EXPRESSION_GESTURE = [
    (("shock", "surpris", "panic", "horrif", "stunned"), "arms_up"),
    (("worr", "nervous", "confus", "guilty", "awkward", "embarrass"), "head_scratch"),
    (("angry", "annoy", "furious", "irritat", "stern"), "hands_on_hips"),
    (("smug", "proud", "confident", "unimpressed", "deadpan"), "cross_arms"),
    (("happy", "excite", "joy", "delight", "cheer"), "open_palms"),
    (("laugh",), "hand_on_chest"),
    (("sorry", "plead", "apolog", "sad"), "hand_on_chest"),
    (("despair", "defeat", "facepalm", "tired"), "facepalm"),
]


def enabled(db) -> bool:
    return get_section(db, "motion").get("provider") == "procedural-rig"


def infer_gesture(expression: str, index: int) -> str | None:
    e = (expression or "").lower()
    for words, g in EXPRESSION_GESTURE:
        if any(w in e for w in words):
            return g
    return None


# ---------------------------------------------------------------- rigs
def _registry(c) -> dict:
    p = Path(c.registry_path)
    p = p if p.is_absolute() else REPO_ROOT / p
    return json.loads(p.read_text(encoding="utf-8"))


def _pose_file(reg: dict, pose_id: str) -> Path:
    f = Path(reg["poses"][pose_id]["file"])
    return f if f.is_absolute() else REPO_ROOT / f


def rig_for(ctx, c) -> Path:
    """Build (or reuse) the character's rig from its approved poses: the neutral body plus one head per expression."""
    reg = _registry(c)
    neutral_id = c.expressions.get("neutral") or c.expressions.get(c.default_expression) or next(iter(c.expressions.values()))
    sources = [("neutral", _pose_file(reg, neutral_id))]
    for name, pid in sorted(c.expressions.items()):
        if pid != neutral_id and name != "neutral":
            sources.append((name, _pose_file(reg, pid)))
    h = hashlib.sha256((ANIM / "rig_extract.py").read_bytes())
    for name, f in sources:
        h.update(name.encode()); h.update(sha256_file(f).encode())
    d = get_settings().work_dir / "rigs" / f"{c.key}-{h.hexdigest()[:12]}"
    if (d / "rig.json").exists():
        return d
    d.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    r = subprocess.run([py, str(ANIM / "rig_extract.py"), str(sources[0][1]), str(d)], capture_output=True, text=True,
                       timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise engine.EngineRunError(f"could not rig {c.name} from the approved neutral pose: {(r.stderr or r.stdout)[-400:]}")
    for name, f in sources[1:]:
        r = subprocess.run([py, str(ANIM / "rig_extract.py"), str(f), str(d), "--head-only", name], capture_output=True,
                           text=True, timeout=600, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            ctx.log(f"{c.name}: expression '{name}' not rigged ({(r.stderr or r.stdout).strip()[-160:]}); neutral face used")
    ctx.log(f"{c.name}: rig built from {len(sources)} approved pose(s)")
    return d


def face_for(rig_faces: set[str], c, expression: str) -> str:
    """The rig face for a line's expression, matched like the pose engine (exact, then loose), else neutral."""
    e = (expression or "").lower()
    if e in rig_faces:
        return e
    for name in rig_faces:
        if name in e or e in name:
            return name
    return "neutral"


# ---------------------------------------------------------------- lip sync
def cues_for(clip: Path, text: str) -> list[dict]:
    cache = get_settings().work_dir / "lipsync" / f"{sha256_file(clip)}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    cues = lipsync(clip, text)["cues"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(cues))
    return cues


# ---------------------------------------------------------------- render
def render(ctx, ep, refs: list[list[tuple[int, int]]], clips: dict, chars_by_key: dict, folder: Path,
           end_card: str | None = None) -> tuple[Path, Path, dict]:
    """refs: per scene, the (scene_id, line_index) pairs to perform (a segment, or the whole episode).
    Returns (mp4 with audio, mix wav, report)."""
    from .models import StoryboardScene
    db = ctx.db
    folder.mkdir(parents=True, exist_ok=True)
    scenes = {sid: db.get(StoryboardScene, sid) for rs in refs for sid, _ in rs}
    present = [k for rs in refs for sid, li in rs for k in [scenes[sid].lines[li]["speaker"]] + list(scenes[sid].characters)]
    keys = list(dict.fromkeys(k for k in present if k in chars_by_key))
    first_scene_cast = set(scenes[refs[0][0][0]].characters) if refs and refs[0] else set()
    prod = get_section(db, "production")
    env_id = (scenes[refs[0][0][0]].location if refs and refs[0] else "") or prod.get("environment") or "living-room-empty-03"
    from . import sets as studio_sets
    st = studio_sets.plate_for(db, env_id, folder / "set")   # an approved studio set (Settings > Sets)
    if st is None:
        set_file = ANIM / "sets" / f"{env_id}.json"
        if not set_file.exists():
            set_file = ANIM / "sets" / "living-room-empty-03.json"
        st = json.loads(set_file.read_text())
        st["plate"] = str(REPO_ROOT / st["plate"])

    cast, faces = {}, {}
    for k in keys:
        c = chars_by_key[k]
        rd = rig_for(ctx, c)
        rig = json.loads((rd / "rig.json").read_text())
        faces[k] = set(rig["faces"])
        lips = sum(rig["faces"]["neutral"]["mouth"].get("color", [0, 0, 0])) > 150   # coloured lips (not a black line)
        cast[k] = {"rig": str(rd), "height": 530, "lips": lips, "start": "on" if (k in first_scene_cast or not first_scene_cast) else "off"}

    lines, t, entered = [], 0.5, {k for k in keys if cast[k]["start"] == "on"}
    gain = float(get_section(db, "voice").get("gain", 1.0))
    audio = []
    prev_scene = None
    for rs in refs:
        for sid, li in rs:
            if prev_scene is not None and sid != prev_scene:
                t += SCENE_GAP
            prev_scene = sid
            ln = scenes[sid].lines[li]
            k = ln["speaker"]
            clip = clips.get(sid, {}).get(li)
            cues, seconds = [], float(ln.get("duration") or 1.6)
            if clip:
                local = storage().get_to_file(clip["key"], folder / "voice" / Path(clip["key"]).name)
                seconds = clip["seconds"]
                cues = cues_for(local, ln["text"])
                audio.append((local, t))
            entry = {"speaker": k, "text": ln["text"], "start": round(t, 3), "end": round(t + seconds + BEAT, 3), "shot": ln.get("shot", "wide"),
                     "expression": face_for(faces.get(k, {"neutral"}), chars_by_key[k], ln.get("expression", "")), "cues": cues}
            for f in ("gesture", "look_at", "reactions"):
                if ln.get(f):
                    entry[f] = ln[f]
            if ln.get("move"):
                entry["move"] = ln["move"]
            if "gesture" not in entry:
                g = infer_gesture(ln.get("expression", ""), li)
                if g:
                    entry["gesture"] = g
            for r in entry.get("reactions", []):
                if r.get("expression") and r["character"] in faces:
                    r["expression"] = face_for(faces[r["character"]], chars_by_key[r["character"]], r["expression"])
            if k not in entered and "move" not in entry:
                entry["move"] = {"type": "enter"}       # a character not on stage walks in for their first line
            entered.add(k)
            lines.append(entry)
            t = entry["end"] + GAP
    duration = round(t + TAIL + (END_CARD if end_card else 0), 3)

    s = get_settings()
    from .tasks import current_script
    hook = engine.strip_emoji((current_script(db, ep) or {}).get("hook") or ep.title)
    # presentation (locked, owner 2026-11-17): comic speech bubbles by the speaker and a permanent top hook banner
    spec = {"width": 1080, "height": 1920, "fps": int(prod.get("fps", 30)), "duration": duration, "captions": False,
            "bubbles": True, "hook": hook,
            "font": str(REPO_ROOT / "skills/directing-stickman-videos/assets/fonts/NotoSans.ttf"), "set": st, "cast": cast, "lines": lines,
            "end_card": {"text": end_card, "seconds": END_CARD} if end_card else None}
    spec_file = folder / "acting.json"
    spec_file.write_text(json.dumps(spec, indent=1))
    silent = folder / "acting-video.mp4"
    env = engine.env_for_node()
    if s.ffmpeg:
        env["FFMPEG"] = s.ffmpeg
    r = subprocess.run([s.node_bin, str(ANIM / "render-acting.mjs"), str(spec_file), str(silent)], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(REPO_ROOT), env=env, timeout=s.job_timeout_seconds, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not silent.exists():
        raise engine.EngineRunError("the acting renderer failed: " + (r.stderr or r.stdout)[-800:])
    report = json.loads(r.stdout.strip().splitlines()[-1])

    # voice mix: every clip at its line start, padded to the video's length
    ff = s.ffmpeg or "ffmpeg"
    wav = folder / "acting-mix.wav"
    if audio:
        args = [ff, "-v", "error", "-y"]
        for f, _ in audio:
            args += ["-i", str(f)]
        filt = [f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(st0 * 1000)}:all=1,volume={gain}[a{i}]" for i, (_, st0) in enumerate(audio)]
        filt.append("".join(f"[a{i}]" for i in range(len(audio))) + f"amix=inputs={len(audio)}:normalize=0:duration=longest,apad,atrim=0:{duration}[out]")
        args += ["-filter_complex", ";".join(filt), "-map", "[out]", "-c:a", "pcm_s16le", "-ar", "48000", str(wav)]
    else:
        args = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration), "-c:a", "pcm_s16le", str(wav)]
    subprocess.run(args, check=True, timeout=600, stdin=subprocess.DEVNULL)
    mp4 = folder / "acting.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(silent), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-t", str(duration), "-movflags", "+faststart", str(mp4)],
                   check=True, timeout=600, stdin=subprocess.DEVNULL)
    ctx.log(f"acting render: {len(lines)} lines, {duration:.1f} s, {report.get('render_seconds')} s to render")
    return mp4, wav, {**report, "lines": len(lines), "cast": keys}
