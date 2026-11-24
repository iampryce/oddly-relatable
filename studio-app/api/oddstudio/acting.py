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


def line_texts(text: str) -> tuple[str, str]:
    """(bubble text, lip-sync guide) for a line. The voice clip was made from the full line, performance tags included;
    the bubble shows the words only, and Rhubarb is guided by the spoken words (a tag is acted, not said)."""
    return engine.viewer_text(text), engine.strip_direction(text)


FONTS = REPO_ROOT / "skills/directing-stickman-videos/assets/fonts"


def presentation(ep, hook: str) -> dict:
    """How the dialogue and the hook appear (owner decision 2026-11-20): the episode's dialogue display (bubbles | none
    | captions) and the POV banner (heavy condensed font, colour emoji kept)."""
    mode = getattr(ep, "dialogue_display", None) or "bubbles"
    # the frame layout (2026-11-24): "band" draws the picture in a 16:9 band in the middle of the 9:16 frame, the captions
    # under it and the banner flat above it; the full frame (the default) adds nothing, so its spec is exactly as before
    band = (getattr(ep, "layout", None) or "full") == "band"
    return {"bubbles": mode == "bubbles", "captions": mode == "captions", "hook": engine.hook_text(hook),
            "banner_font": str(FONTS / "Anton-Regular.ttf"), "emoji_font": str(FONTS / "NotoColorEmoji-Regular.ttf"),
            **({"layout": "band"} if band else {})}


def episode_hook(db, ep) -> str:
    """The banner text this episode shows: "" when its banner is off; else its own text, the script's hook, or the
    title. Used by the acting renderer (video and stills) and the pose engine's final render alike."""
    from .serialize import hook_on
    if not hook_on(ep):
        return ""
    own = (getattr(ep, "hook_text", None) or "").strip()
    if own:
        return own
    from .tasks import current_script
    try:
        script = current_script(db, ep) or {}
    except Exception:  # noqa: BLE001 -- no script yet: the title
        script = {}
    return script.get("hook") or ep.title


HEIGHT = 530          # a character's standing height in set pixels (the default)
HEAD_OVERLAP = 0.0    # seated neighbours' heads never overlap (owner decision 2026-11-23; was 25%)
MIN_HEIGHT = 318      # the floor on the cast height (60% of the default), so figures never get tiny
TYPICAL_HEAD = 0.42   # a head's width / the figure's height for the studio's characters (when no rig is at hand)


def row_neighbours(seats: list[dict], row_tol: float) -> list[tuple[int, int, int]]:
    """(seat number, seat number, px apart) for seats side by side in the same row: neighbours by x whose hips are
    less than row_tol apart in height (a seat behind a desk and the audience row in front of it never collide).
    Seat numbers are 1-based, in the set's order (as the Set panel shows them)."""
    pts = sorted(((s["x"], s.get("hip_y", 0), i + 1) for i, s in enumerate(seats or [])), key=lambda p: p[0])
    out = []
    for i, (x, y, n) in enumerate(pts):
        # the nearest seat to the right in the same row
        nxt = next(((x2, n2) for x2, y2, n2 in pts[i + 1:] if abs(y2 - y) < row_tol), None)
        if nxt:
            out.append((n, nxt[1], int(round(nxt[0] - x))))
    return out


def cast_height(seats: list[dict], head_ratio: float, default: int = HEIGHT) -> int:
    """The characters' height for a set: the default, unless the set's seats are too close together for heads this
    big (head width = head_ratio x height); then the largest height at which neighbouring seated heads do not overlap
    at all (HEAD_OVERLAP), never below MIN_HEIGHT (then the Set panel warns about the seats)."""
    if head_ratio <= 0:
        return default
    gaps = [g for _, _, g in row_neighbours(seats, head_ratio * default) if g > 0]
    if not gaps:
        return default
    fit = min(gaps) / ((1 - HEAD_OVERLAP) * head_ratio)
    return int(min(default, max(MIN_HEIGHT, fit)))


def min_head_px(head_ratio: float = TYPICAL_HEAD) -> int:
    """One head width at the smallest cast height: seats closer than this always make neighbours' heads overlap."""
    return int(-(-head_ratio * MIN_HEIGHT // 1))


def spacing_warnings(seats: list[dict], head_ratio: float = TYPICAL_HEAD) -> list[dict]:
    """Seats side by side closer than one head width at the smallest cast height, in words with the numbers. A
    warning only: most generated sets space their chairs for normal proportions, and refusing them would block them."""
    need = min_head_px(head_ratio)
    out = []
    for a, b, gap in row_neighbours(seats, need):
        if gap < need:
            out.append({"seats": [a, b], "gap": gap, "need": need,
                        "text": f"seats {a} and {b} are {gap} px apart; need {need} px (one head width at the smallest "
                                f"cast height, {MIN_HEIGHT} px): their heads will overlap"})
    return out


def head_ratio(rig: dict) -> float:
    try:
        return float(rig["faces"]["neutral"]["size"][0]) / float(rig["body"]["height"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 0.0


MOTION_2D, MOTION_3D = "procedural-rig", "procedural-rig-3d"


def enabled(db) -> bool:
    """The acting renderer draws the episode: the Studio 2D rig animator or the Studio 3D rig animator (feat/3d-rig)."""
    return get_section(db, "motion").get("provider") in (MOTION_2D, MOTION_3D)


def three_d(db) -> bool:
    """Settings > Motion is the Studio 3D rig animator: the same acting, the characters drawn as 3D stickmen."""
    return get_section(db, "motion").get("provider") == MOTION_3D


def node_command(node_bin: str, args: list[str], three: bool) -> list[str]:
    """The renderer's command line. The 3D rig animator draws with headless-gl, which needs a display on Linux: without
    one (the worker) it runs under xvfb-run, a virtual display; nothing is shown anywhere."""
    import os
    import shutil
    import sys
    cmd = [node_bin, *args]
    if three and sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1920x1920x24", *cmd]
    return cmd


def head_angle_files(db, c, folder: Path) -> dict[str, str]:
    """The character's approved head drawings (three-quarter, side, back) as local files for the 3D renderer; an angle
    without an approved drawing is left out and the renderer uses its mock."""
    from .head_angles import approved_angles
    from .storage import storage
    out = {}
    for angle, a in approved_angles(db, c).items():
        dst = folder / "head-angles" / c.key / f"{angle}{Path(a.storage_key).suffix or '.png'}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        out[angle] = str(storage().get_to_file(a.storage_key, dst))
    return out


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
        from .rig_check import rig_error
        raise engine.EngineRunError(f"could not rig {c.name} from the approved neutral pose: {rig_error(r.stderr or r.stdout)}")
    for name, f in sources[1:]:
        r = subprocess.run([py, str(ANIM / "rig_extract.py"), str(f), str(d), "--head-only", name], capture_output=True,
                           text=True, timeout=600, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            from .rig_check import rig_error
            ctx.log(f"{c.name}: expression '{name}' not rigged ({rig_error(r.stderr or r.stdout)}); neutral face used")
    ctx.log(f"{c.name}: rig built from {len(sources)} approved pose(s)")
    return d


def seat_starts(staging: dict, cast: list[str], seats: int) -> tuple[dict[str, str], list[str]]:
    """How the first scene starts: seated characters take seats 0, 1, ... in staging order (speaker first); standing
    ones start on stage. Returns ({key: "seat:N" | "on"}, [seated characters left standing for want of a seat])."""
    out, left, n = {}, [], 0
    for k, pos in staging.items():
        if k not in cast:
            continue
        if pos == "seated" and n < seats:
            out[k], n = f"seat:{n}", n + 1
        else:
            out[k] = "on"
            if pos == "seated":
                left.append(k)
    return out, left


def still_times(lines: list[dict], n: int) -> list[float]:
    """The moments the storyboard stills show: the scene's first line just after it starts, then the middle of lines
    spread over the scene, at most n in all."""
    if not lines:
        return [0.5]
    pick = lines if len(lines) <= n else [lines[round(k * (len(lines) - 1) / (n - 1))] for k in range(n)] if n > 1 else lines[:1]
    out = [round(min(ln["end"], ln["start"] + 0.4), 3) if k == 0 else round((ln["start"] + ln["end"]) / 2, 3)
           for k, ln in enumerate(pick)]
    return sorted(dict.fromkeys(out))


def face_for(rig_faces: set[str], c, expression: str) -> str:
    """The rig face for a line's expression: exact, then loose, then the nearest approved one of the same family
    (casting.closest_expression), else neutral. A missing expression never stops a render."""
    from .casting import closest_expression
    f = closest_expression(expression, rig_faces)
    return f if f in rig_faces else "neutral"


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
def referenced(line: dict) -> list[str]:
    """Every character a line puts on screen: its speaker, who the speaker looks at, and who reacts."""
    keys = [line.get("speaker")]
    if line.get("look_at"):
        keys.append(line["look_at"])
    keys += [r.get("character") for r in line.get("reactions") or [] if isinstance(r, dict)]
    return [k for k in keys if k]


def render_cast(lines: list[tuple[int, dict]], scene_characters: dict, chars_by_key: dict) -> tuple[list[str], set[str]]:
    """The render's cast: everyone the lines reference (speakers, look-at targets, reactions) plus the scenes' cast, in
    order of appearance; and who of them speaks. A referenced character that is not in the studio, or has no approved
    pose art, stops the render with a message naming them (never a renderer crash on a missing rig)."""
    order = []
    for sid, ln in lines:
        order += referenced(ln) + list(scene_characters.get(sid) or [])
    keys = list(dict.fromkeys(order))
    unknown = [k for k in keys if k not in chars_by_key]
    if unknown:
        raise engine.EngineInputError("These characters are in the scenes but not in the studio: " + ", ".join(unknown)
                                      + ". Add them under Characters, or remove them from the scenes.")
    engine.check_cast_ready([chars_by_key[k] for k in keys])
    return keys, {ln["speaker"] for _, ln in lines}


def render(ctx, ep, refs: list[list[tuple[int, int]]], clips: dict, chars_by_key: dict, folder: Path,
           end_card: str | None = None, stills: int = 0) -> tuple[Path, Path, dict]:
    """refs: per scene, the (scene_id, line_index) pairs to perform (a segment, or the whole episode).
    Returns (mp4 with audio, mix wav, report).
    Audio-first episodes use the ABSOLUTE timeline (audio_production.py): each line at its recorded start and end, the
    video exactly as long as the recording, which is muxed in unchanged; the render must pass the audio QA.
    stills > 0 (storyboard stills): the same render up to the last still, saving that many frames (one in each line,
    spread over the lines) as PNG files instead of a video; no audio is needed (a line without its slice of the
    recording yet keeps a closed mouth). Returns (None, None, report with "stills": [{file, t}])."""
    from .models import StoryboardScene
    db = ctx.db
    folder.mkdir(parents=True, exist_ok=True)
    # The episode's own set, chosen explicitly by the owner (no silent default, owner decision 2026-11-21)
    from . import sets as studio_sets
    if not getattr(ep, "set_id", None):
        raise engine.EngineInputError("this episode has no set: choose an approved set for it (Storyboard tab, Set)")
    st = studio_sets.spec_for(db, ep.set_id, folder / "set")
    if st is None:
        raise engine.EngineInputError(f"the episode's set {ep.set_id!r} is not an approved set: choose another one")
    absolute = getattr(ep, "source", "") == "audio"
    if absolute:
        from . import audio_production as AP
        src_audio, total = AP.source_audio(db, ep, folder / "source")
        end_card = None                      # the video must end with the recording
    scenes = {sid: db.get(StoryboardScene, sid) for rs in refs for sid, _ in rs}
    lines_in = [(sid, scenes[sid].lines[li]) for rs in refs for sid, li in rs]
    keys, speaking = render_cast(lines_in, {sid: scenes[sid].characters for sid in scenes}, chars_by_key)
    first_scene_cast = set(scenes[refs[0][0][0]].characters) if refs and refs[0] else set()
    prod = get_section(db, "production")

    cast, faces, ratios = {}, {}, []
    for k in keys:
        c = chars_by_key[k]
        rd = rig_for(ctx, c)
        rig = json.loads((rd / "rig.json").read_text())
        ratios.append(head_ratio(rig))
        faces[k] = set(rig["faces"])
        lips = sum(rig["faces"]["neutral"]["mouth"].get("color", [0, 0, 0])) > 150   # coloured lips (not a black line)
        # on stage from the start: the first scene's cast, and characters who never speak here (silent characters only
        # react or are looked at, so they have no line of their own to walk in on)
        on = k in first_scene_cast or not first_scene_cast or k not in speaking
        cast[k] = {"rig": str(rd), "height": HEIGHT, "lips": lips, "start": "on" if on else "off"}
        if three_d(db):
            cast[k]["head_angles"] = head_angle_files(db, c, folder)
    # one height for everyone, fitted to the episode's set: close seats draw the cast smaller so seated heads do not
    # pile up (the chairs in a generated set are often spaced for normal proportions, not for big-headed characters)
    h = cast_height(studio_sets.seats_of(st), max(ratios or [0.0]))
    if h != HEIGHT:
        ctx.log(f"the set's seats are close together: characters drawn {h} px tall instead of {HEIGHT}")
    for v in cast.values():
        v["height"] = h
    # how the first scene starts (feat/seating): its seated characters take the set's seats in staging order (speaker
    # first); more seated characters than seats stand, and the log says so
    first = scenes[refs[0][0][0]] if refs and refs[0] else None
    # per-scene sets (feat/scene-sets): the render starts on its first scene's set; a scene's set that cannot be
    # staged stops the render with the scene named (never a silent default)
    from . import scene_sets
    bad = scene_sets.problems(db, ep, list(scenes.values()))
    if bad:
        raise engine.EngineInputError("; ".join(bad))
    set_specs = {ep.set_id: st}

    def set_spec(sid: str) -> dict:
        if sid not in set_specs:
            set_specs[sid] = studio_sets.spec_for(db, sid, folder / f"set-{sid}")
            if set_specs[sid] is None:
                raise engine.EngineInputError(f"the set {sid!r} is not an approved set any more")
        return set_specs[sid]
    if first is not None:
        st = set_spec(scene_sets.scene_set(ep, first))
    starts, standing = seat_starts(getattr(first, "staging", None) or {}, list(cast), len(studio_sets.seats_of(st)))
    for k, v in starts.items():
        cast[k]["start"] = v
    for k in standing:
        ctx.log(f"{k}: seated in the scene's staging, but the set has no free seat: standing")

    lines, t, entered = [], 0.5, {k for k in keys if cast[k]["start"] != "off"}
    cuts = []   # (scene id, index of its first line) for every scene after the first
    line_ids = []
    gain = float(get_section(db, "voice").get("gain", 1.0))
    audio = []
    prev_scene = None
    for rs in refs:
        for sid, li in rs:
            if prev_scene is not None and sid != prev_scene:
                t += SCENE_GAP
                cuts.append((sid, len(lines)))
            prev_scene = sid
            ln = scenes[sid].lines[li]
            k = ln["speaker"]
            clip = clips.get(sid, {}).get(li)
            cues, seconds = [], float(ln.get("duration") or 1.6)
            if absolute and not clip and not stills:
                raise engine.EngineInputError(f"{ln.get('line_id') or 'a line'}: no slice of the recording (run the scene again)")
            if clip:
                local = storage().get_to_file(clip["key"], folder / "voice" / Path(clip["key"]).name)
                seconds = clip["seconds"]
                cues = cues_for(local, line_texts(ln["text"])[1])
                if not absolute:
                    audio.append((local, t))
            start, end = AP.line_window(ln) if absolute else (round(t, 3), round(t + seconds + BEAT, 3))
            entry = {"speaker": k, "text": line_texts(ln["text"])[0], "start": start, "end": end, "shot": ln.get("shot", "wide"),
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
                entry["move"] = {"type": "enter", "auto": True}   # a character not on stage walks in for their first line
            entered.add(k)
            lines.append(entry)
            line_ids.append(ln.get("line_id"))
            t = entry["end"] + GAP
    duration = total if absolute else round(t + TAIL + (END_CARD if end_card else 0), 3)

    # later scenes: at the cut (halfway between the two lines) the set changes when it differs, and everyone is placed
    # as the scene starts (its staging on its set's seats; the scene's characters on stage, the others off). Only
    # emitted when a later scene changes set or has staging, so a one-set render without staging is exactly as before.
    scene_specs = []
    for sid, i in cuts:
        sc = scenes[sid]
        sspec = set_spec(scene_sets.scene_set(ep, sc))
        on_stage = set(sc.characters or []) | {r for ln in sc.lines for r in referenced(ln)}
        sstarts, left = seat_starts(sc.staging or {}, list(cast), len(studio_sets.seats_of(sspec)))
        for k in left:
            ctx.log(f"scene {sc.position}: {k} is seated in the staging, but the set has no free seat: standing")
        flip = scene_sets.is_reverse(db, scene_sets.scene_set(ep, sc))
        scene_specs.append({"t0": round((lines[i - 1]["end"] + lines[i]["start"]) / 2, 3), "set": sspec, "id": sid,
                            "starts": {k: sstarts.get(k) or ("on" if k in on_stage else "off") for k in cast},
                            **({"flip": True} if flip else {}),
                            "_changes": sspec is not st or bool(sc.staging) or flip})
    changes = any([x.pop("_changes") for x in scene_specs])   # (a list: every entry loses the key)
    scene_specs = scene_specs if changes else []
    # a character the scene start already places on stage does not also walk in (only the automatic entrances)
    bounds = [x["t0"] for x in scene_specs] + [float("inf")]
    for x, t_end in zip(scene_specs, bounds[1:]):
        for ln in lines:
            if x["t0"] <= ln["start"] < t_end and (ln.get("move") or {}).get("auto") and x["starts"].get(ln["speaker"]) != "off":
                ln.pop("move")
    for ln in lines:   # the marker is internal: the spec stays as before for renders without scene changes
        (ln.get("move") or {}).pop("auto", None)

    # set views (feat/set-views): each line's shot picks a view of its set (speaker, audience, two-shot); a cut to a
    # view is a scene change to that view's picture with only the people it shows seated, and back. Without approved
    # views nothing changes (missing views fall back to wide).
    from . import set_views
    first_sid = scene_sets.scene_set(ep, first) if first is not None else ep.set_id
    base = [{"t0": -1e9, "set_id": first_sid, "set": st, "starts": {k: cast[k]["start"] for k in cast}}] + [
        {"t0": x["t0"], "set_id": scene_sets.scene_set(ep, scenes[x["id"]]), "set": x["set"], "starts": x["starts"],
         **({"flip": True} if x.get("flip") else {})} for x in scene_specs]
    by_set = set_views.specs_for(db, [b["set_id"] for b in base if b["set_id"]], folder)
    if by_set:
        merged = set_views.cut(lines, base, by_set)
        if merged:
            scene_specs = merged
            ctx.log(f"set views: {sum(1 for x in merged if x.get('view') != 'wide')} cut(s) to a view")

    # timed actions from the video's beats (audio episodes: absolute times), only inside this render's span and for
    # characters in its cast; none -> the spec has no "actions" key, exactly as before
    actions = []
    if absolute and lines:
        lo, hi = lines[0]["start"] - 2.0, lines[-1]["end"] + 2.0
        seen_scenes = list(dict.fromkeys(sid for rs in refs for sid, _ in rs))
        for sid in seen_scenes:
            for a in getattr(scenes[sid], "actions", None) or []:
                if lo <= a["t"] <= hi and a["character"] in cast and (a.get("type") != "turn_to" or a.get("target") in cast):
                    actions.append(dict(a))
        actions.sort(key=lambda a: a["t"])

    from .reaction_sheet import spec_shots
    shots = spec_shots(sorted(scenes.values(), key=lambda x: x.position)) if absolute else []
    s = get_settings()
    from .tasks import current_script
    hook = episode_hook(db, ep)
    # presentation (locked, owner 2026-11-17): comic speech bubbles by the speaker and a permanent top hook banner
    spec = {"width": 1080, "height": 1920, "fps": int(prod.get("fps", 30)), "duration": duration,
            **presentation(ep, hook),
            "font": str(REPO_ROOT / "skills/directing-stickman-videos/assets/fonts/NotoSans.ttf"), "set": st, "cast": cast, "lines": lines,
            **({"scenes": scene_specs} if scene_specs else {}),
            **({"actions": actions} if actions else {}),
            # the scenes' shot lists (reaction_sheet.py), on the recording's timeline; no shot list, no key
            **({"shots": shots} if shots else {}),
            **({"flip": True} if first is not None and scene_sets.is_reverse(db, scene_sets.scene_set(ep, first)) else {}),
            "end_card": {"text": end_card, "seconds": END_CARD} if end_card else None,
            "timeline": "absolute" if absolute else "sequential"}
    if three_d(db):
        spec["engine"] = "3d"                         # the Studio 3D rig animator draws the characters
        if ep.source == "audio" and absolute:
            # who faces whom, from the reference plan (the recording's times are the timeline's)
            from .reference_plan import facing_notes
            fn = facing_notes(ep.audio_transcript or {})
            if fn:
                spec["facing_notes"] = fn
    if stills:
        spec["stills"] = still_times(lines, stills)   # the presentation (dialogue display) is the video's
    spec_file = folder / "acting.json"
    spec_file.write_text(json.dumps(spec, indent=1))
    silent = folder / ("stills" if stills else "acting-video.mp4")
    env = engine.env_for_node()
    if s.ffmpeg:
        env["FFMPEG"] = s.ffmpeg
    r = subprocess.run(node_command(s.node_bin, [str(ANIM / "render-acting.mjs"), str(spec_file), str(silent)], three_d(db)),
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=env, timeout=s.job_timeout_seconds,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not silent.exists():
        raise engine.EngineRunError("the acting renderer failed: " + (r.stderr or r.stdout)[-800:])
    report = json.loads(r.stdout.strip().splitlines()[-1])
    for w in report.get("warnings", []):
        ctx.log(f"renderer: {w}")
    if stills:
        return None, None, {**report, "lines": len(lines), "cast": keys}

    if absolute:
        mp4 = AP.mux_original(silent, src_audio, total, folder / "acting.mp4")
        wav = AP.as_wav(src_audio, total, folder / "acting-mix.wav")
        words = {x["id"]: x.get("words") or [] for x in (ep.audio_transcript or {}).get("lines", [])}
        first = min(range(len(lines)), key=lambda i: lines[i]["start"]) if lines else None
        first_word = None
        if first is not None:
            w = words.get(line_ids[first]) or []
            first_word = round(float(w[0]["start"]) if w else lines[first]["start"], 3)
        check = AP.qa(AP.probe(mp4, "v")["duration"] or 0.0, total, spec["fps"], AP.first_mouth_cue(lines), first_word)
        (folder / "qa-audio.json").write_text(json.dumps(check, indent=1))
        ctx.log("audio QA: " + ("pass" if check["pass"] else "FAIL: " + AP.qa_message(check)))
        if not check["pass"]:
            raise engine.EngineRunError("audio QA failed: " + AP.qa_message(check))
        return mp4, wav, {**report, "lines": len(lines), "cast": keys, "timeline": "absolute", "audio_qa": check}

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
