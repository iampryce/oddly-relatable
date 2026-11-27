"""Bridge to the existing production engine (`production/`, Node). The engine is used exactly as its CLI documents:

    node production/cli.mjs build      STORY OUT                 compile + layout checks
    node production/cli.mjs storyboard OUT/project.json          renderer-exact stills
    node production/cli.mjs produce    STORY OUT                 compile, audio bed, storyboard, MP4, QA, manifest

This module only writes the engine's normal story JSON (oddly-relatable/story@1, face-to-face scenes) from the approved
storyboard, and reads the engine's own outputs. The engine and the renderer are not modified.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from .config import REPO_ROOT, get_settings
from .providers import env_for_node

CLI = REPO_ROOT / "production" / "cli.mjs"
ENV_REGISTRY = REPO_ROOT / "production" / "environments" / "environments.json"
POSITIONS = {1: [640], 2: [400, 880], 3: [300, 640, 980], 4: [250, 490, 790, 1030]}
SHOT = {"wide": "Wide", "medium": "Medium 1.3x", "close": "Close"}


class EngineInputError(ValueError):
    """The storyboard cannot be produced as it stands (for example a character without approved pose art)."""


class EngineRunError(RuntimeError):
    pass


def environments() -> list[str]:
    return sorted(json.loads(ENV_REGISTRY.read_text(encoding="utf-8"))["environments"])


def engine_id(key: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", key.lower()).strip("-")
    return s or "member"


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")


# Performance directions written into a line for the voice engine (Fish Audio reads inline tags such as [whisper] or
# [laughs]). They are spoken as acting, never shown: bubbles, captions and the hook show the words only. Only short
# bracketed words count as directions, so text like "[2]" is left alone.
DIRECTION_TAG = re.compile(r"\s*\[[A-Za-z][A-Za-z ,'\-]{0,38}\]\s*")


def strip_direction(text: str) -> str:
    """The words of a line without its performance tags (\"[whispers] Not now.\" -> \"Not now.\")."""
    out = DIRECTION_TAG.sub(" ", text or "")
    out = re.sub(r"\s+([,.!?;:\u2026])", r"\1", re.sub(r"\s{2,}", " ", out))
    return out.strip()


def hook_text(text: str) -> str:
    """The POV banner's text: performance tags removed, emoji KEPT (the acting renderer draws them with a colour emoji
    font); spacing tidied. Bubbles and captions still use viewer_text (no emoji: their font has none)."""
    return re.sub(r"\s{2,}", " ", strip_direction(text)).strip()


def viewer_text(text: str) -> str:
    """What the viewer sees for a line (bubble or caption): no performance tags, no emoji; a line that is only a
    direction (\"[laughs]\") shows the house style's silent beat \"...\"."""
    return strip_emoji(strip_direction(text))


def strip_emoji(text: str) -> str:
    """The bundled font has no emoji; they are removed from bubbles (the writer is also told not to use them)."""
    t = re.sub(r"\s{2,}", " ", _EMOJI.sub("", text)).strip()
    return t or "..."


def pose_for(char, expression: str) -> str:
    exp = (expression or "").lower()
    if exp in char.expressions:
        return char.expressions[exp]
    for name, pose in char.expressions.items():           # loose match: "very shocked" -> "shocked"
        if name in exp:
            return pose
    return char.expressions.get(char.default_expression) or next(iter(char.expressions.values()))


def check_cast_ready(chars: list) -> None:
    missing = [c.name for c in chars if not c.registry_path or not c.expressions or c.art_status != "approved"]
    if missing:
        raise EngineInputError("These characters have no approved pose art yet, so they cannot be animated: "
                               + ", ".join(missing) + ". Generate and approve their poses under Characters.")


def _poses_before(sc, chars, chars_by_key, start: int) -> dict:
    """Each cast member's pose when line `start` begins (line 0 sets everyone; later lines set their speaker)."""
    state = {}
    for li, ln in enumerate(sc.lines[:start]):
        speaker = chars_by_key[ln["speaker"]]
        if li == 0:
            state = {c.key: pose_for(c, ln.get("expression", "") if c is speaker else c.default_expression) for c in chars}
        state[speaker.key] = pose_for(speaker, ln.get("expression", ""))
    return state


def build_story(*, episode_id: int, revision: int, title: str, script: dict, scenes: list, chars_by_key: dict,
                production: dict, only_scene_ids: set[int] | None = None, end_card: bool = True,
                parts: list[dict] | None = None, segment: tuple[int, int] | None = None) -> dict:
    """Engine story for the approved storyboard (or a subset of scenes, for previews and scene re-runs).

    Long-form segments (D-L2): `parts` lists the scene parts of one segment ({"scene": scene_key, "lines": [a, b]}; a long
    scene may be split between lines, never inside one) and `segment` = (index, count). Only the first segment carries
    the hook and only the last one the end card. Every part keeps its scene's full cast and placements, so characters
    stand in the same places on both sides of a split (continuity)."""
    envs = set(environments())
    out_scenes = []
    used = []
    if parts is not None:
        by_key = {sc.scene_key: sc for sc in scenes}
        work = [(by_key[p["scene"]], p["lines"][0], p["lines"][1]) for p in parts]
    else:
        work = [(sc, 0, len(sc.lines)) for sc in scenes if only_scene_ids is None or sc.id in only_scene_ids]
    for sc, first, last in work:
        keys = []
        for k in list(sc.characters) + [ln["speaker"] for ln in sc.lines]:
            if k not in keys:
                keys.append(k)
        if len(keys) > 4:
            raise EngineInputError(f"scene {sc.position}: at most 4 characters on screen")
        chars = []
        for k in keys:
            if k not in chars_by_key:
                raise EngineInputError(f"scene {sc.position}: unknown character {k!r}")
            chars.append(chars_by_key[k])
        check_cast_ready(chars)
        used += [c for c in chars if c not in used]
        scene_poses = {}
        for li in range(first, last):
            ln = sc.lines[li]
            scene_poses.setdefault(ln["speaker"], set()).add(pose_for(chars_by_key[ln["speaker"]], ln.get("expression", "")))
        for c in chars:   # members who only react keep their default pose
            scene_poses.setdefault(c.key, set()).add(pose_for(c, c.default_expression))
        has_wide = any(sc.lines[li].get("shot", "wide") == "wide" for li in range(first, last)) or len(chars) == 1
        xs, fig_h = cast_layout(chars, scene_poses, has_wide)
        cast = []
        for i, c in enumerate(chars):
            m = {"id": engine_id(c.key), "character": c.engine_character,
                 "placement": {"feetX": xs[i], "feetY": 2070, "figureHeight": fig_h}, "z": i,
                 "speech": {"style": c.bubble_style}}
            if c.registry_path and c.registry_path != f"production/characters/{c.engine_character}.json":
                m["registry"] = c.registry_path
            cast.append(m)
        lines = []
        state = _poses_before(sc, chars, chars_by_key, first)
        for li in range(first, last):
            ln = sc.lines[li]
            speaker = chars_by_key[ln["speaker"]]
            line = {"speaker": engine_id(speaker.key), "text": viewer_text(ln["text"]), "pose": pose_for(speaker, ln.get("expression", ""))}
            if li == first:   # every cast member needs a pose on the first line (the poses in effect at a split)
                start_pose = {c.key: state.get(c.key, pose_for(c, ln.get("expression", "") if c is speaker else c.default_expression)) for c in chars}
                start_pose[speaker.key] = pose_for(speaker, ln.get("expression", ""))
                line["poses"] = {engine_id(c.key): start_pose[c.key] for c in chars}
                line.pop("pose")
            shot = ln.get("shot", "wide")
            line["shot"] = {"camera": SHOT[shot]}
            if shot != "wide":
                line["shot"]["focus"] = engine_id(speaker.key)
                if len(chars) > 1:
                    line["shot"]["single"] = True
            if ln.get("duration"):
                line["duration"] = ln["duration"]
            lines.append(line)
        env = sc.location if sc.location in envs else production.get("environment", "living-room-empty-03")
        sid = engine_id(sc.scene_key) + f"-{sc.position}" + (f"-l{first}" if parts is not None and (first or last < len(sc.lines)) else "")
        out_scenes.append({"id": sid, "format": "face-to-face", "environment": env, "cast": cast, "lines": lines})
    if not out_scenes:
        raise EngineInputError("no scenes to produce")
    end_lines = [{"text": title[:40], "size": 84, "weight": 800}]
    inter = script.get("interactive") or {}
    if inter.get("type", "none") != "none":
        # The engine's title card wraps long lines itself, so the question is not cut. Options are lettered here,
        # after removing a letter the writer may already have added ("A: ...", "B) ...").
        end_lines.append({"text": inter["question"], "size": 52, "weight": 700})
        for i, o in enumerate(inter["options"]):
            o = re.sub(r"^\s*[A-Da-d]\s*[:.)\-]\s*", "", o)
            end_lines.append({"text": f"{chr(65 + i)}: {o}", "size": 46})
    end_lines.append({"text": production.get("end_card", "Oddly Relatable"), "size": 50, "weight": 700, "color": "#BC4C15"})
    story = {"schema": "oddly-relatable/story@1", "id": f"ep{episode_id}-r{revision}", "title": title,
             "format": {"width": 1080, "height": 1920, "fps": int(production.get("fps", 30))},
             "endCard": {"duration": 3 if inter.get("type", "none") == "none" else 5, "lines": end_lines,
                         "background": {"type": "solid", "color": "#2A1D16"}, "caption": production.get("end_card", "Oddly Relatable")},
             "scenes": out_scenes}
    if not end_card:
        # Scene previews show the scene only. The renderer needs at least one caption, so a brief one (before the
        # first storyboard still) replaces the end card's.
        del story["endCard"]
        story["captions"] = [{"start": 0, "end": 0.3, "text": out_scenes[0]["id"]}]
    if segment is not None:
        index, count = segment
        story["id"] = f"ep{episode_id}-r{revision}-seg{index + 1}"
        if index < count - 1:
            # Not the last segment: no end card. The renderer requires one caption, so a single-frame caption sits on
            # the segment's first frame (a scene cut); it is not perceptible at 30 fps.
            del story["endCard"]
            story["captions"] = [{"start": 0, "end": round(1 / int(production.get("fps", 30)), 4), "text": production.get("end_card", "Oddly Relatable")}]
        if index > 0:
            return story   # only the first segment carries the hook
    if script.get("hook"):
        story["hook"] = {"text": viewer_text(script["hook"]), "start": 0, "duration": 2.5}
    return story


def run_node(args: list[str], *, timeout: int, log: Callable[[str], None], watch: Callable[[], None] | None = None) -> tuple[int, str]:
    """Run the engine CLI (argument list, no shell), streaming its output to `log`; `watch` is polled while it runs."""
    s = get_settings()
    # stdin=DEVNULL: FFmpeg (run by the engine) reads stdin for keyboard commands and can block on an inherited pipe.
    p = subprocess.Popen([s.node_bin, str(CLI), *args], cwd=str(REPO_ROOT), env=env_for_node(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    t = threading.Thread(target=lambda: [lines.append(x) for x in p.stdout], daemon=True)  # type: ignore[union-attr]
    t.start()
    start = time.time()
    while p.poll() is None:
        if time.time() - start > timeout:
            p.kill()
            raise EngineRunError(f"the engine did not finish within {timeout} s")
        if watch:
            watch()
        time.sleep(1)
    t.join(5)
    if p.stdout:
        p.stdout.close()
    text = "".join(lines)
    log(text[-20000:])
    if watch:
        watch()
    return p.returncode, text


def write_story(story: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "story.json"
    f.write_text(json.dumps(story, indent=1), encoding="utf-8")
    return f


def preview(story: dict, folder: Path, log: Callable[[str], None]) -> Path:
    """Compile and paint renderer-exact storyboard stills. Returns the storyboard sheet."""
    s = get_settings()
    story_file = write_story(story, folder)
    out = folder / "build"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    code, text = run_node(["build", str(story_file), str(out)], timeout=s.job_timeout_seconds, log=log)
    if code != 0:
        raise EngineRunError("the engine refused the scene: " + last_error(text))
    code, _ = run_node(["storyboard", str(out / "project.json")], timeout=s.job_timeout_seconds, log=log)
    sheet = out / "storyboard" / "storyboard-sheet.png"
    if code != 0 or not sheet.exists():
        raise EngineRunError("the engine could not paint storyboard stills (are FFMPEG and FFPROBE set on the worker?)")
    return sheet


def produce(story: dict, folder: Path, log: Callable[[str], None], progress: Callable[[dict], None]) -> dict:
    """Full production through the engine. Returns the engine's run record; raises on failure."""
    s = get_settings()
    story_file = write_story(story, folder)
    out = folder / "produce"
    run_file = out / "production-run.json"

    def watch():
        if run_file.exists():
            try:
                progress(json.loads(run_file.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass   # the engine is mid-write; read it on the next poll

    args = ["produce", str(story_file), str(out)] + (["--replace"] if out.exists() else [])
    code, text = run_node(args, timeout=s.job_timeout_seconds, log=log, watch=watch)
    run = json.loads(run_file.read_text(encoding="utf-8")) if run_file.exists() else {}
    if code != 0:
        failed = [st for st in run.get("stages", []) if st.get("status") == "failed"]
        why = failed[0].get("error") if failed else (run.get("status") or last_error(text))
        raise EngineRunError(f"engine production failed: {why}")
    return {"run": run, "folder": out}


def last_error(output: str) -> str:
    """The engine prints errors as 'Error: ...'; return the last one (or the last output line)."""
    errs = [ln.strip() for ln in output.splitlines() if "Error" in ln]
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return (errs[-1] if errs else (lines[-1] if lines else "no output"))[:600]


def trim_pose(src: Path, dst: Path, feet: dict, border: int = 12) -> tuple[Path, dict]:
    """Copy of a cut-out pose trimmed to its opaque figure plus `border` pixels; returns it and the moved feet anchor."""
    img = Image.open(src).convert("RGBA")
    box = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
    left, top = max(0, box[0] - border), max(0, box[1] - border)
    right, bottom = min(img.width, box[2] + border), min(img.height, box[3] + border)
    if not dst.exists() or Image.open(dst).size != (right - left, bottom - top):
        img.crop((left, top, right, bottom)).save(dst)
    return dst, {"x": feet["x"] - left, "y": feet["y"] - top}


_reach_cache: dict[str, tuple[float, float]] = {}


def reach(char, pose_ids: set[str] | None = None) -> tuple[float, float]:
    """How far a character's widest poses reach left and right of the feet anchor, per unit of figure height. The engine
    places a pose by its feet, so a pose with arms out to one side reaches further on that side than half its width."""
    ids = sorted(pose_ids) if pose_ids else sorted(set(char.expressions.values()))
    key = f"{char.key}:{char.registry_path}:{ids}"
    if key not in _reach_cache:
        reg_file = Path(char.registry_path) if Path(char.registry_path).is_absolute() else REPO_ROOT / char.registry_path
        reg = json.loads(reg_file.read_text(encoding="utf-8"))
        left = right = 0.0
        for pid in ids:
            p = reg["poses"].get(pid)
            if not p:
                continue
            f = Path(p["file"]) if Path(p["file"]).is_absolute() else REPO_ROOT / p["file"]
            with Image.open(f) as im:
                left = max(left, p["feet"]["x"] / p["figureHeight"])
                right = max(right, (im.width - p["feet"]["x"]) / p["figureHeight"])
        _reach_cache[key] = (left or 0.25, right or 0.25)
    return _reach_cache[key]


FIGURE_HEIGHT, EDGE, GAP = 760, 48, 24


def cast_layout(chars: list, used: dict | None = None, has_wide: bool = True) -> tuple[list[float], float]:
    """Feet positions and figure height for a scene: members spread evenly across the frame by the real reach (each side)
    of the poses this scene uses, and the cast scaled down together only when a WIDE shot needs everyone side by side
    and they would not otherwise fit. A scene of singles keeps full size (no member is ever cut by an edge)."""
    reaches = [reach(c, (used or {}).get(c.key)) for c in chars]
    total = sum(l + r for l, r in reaches)
    gaps = GAP * (len(chars) - 1)
    h = min(FIGURE_HEIGHT, (1280 - 2 * EDGE - gaps) / total) if has_wide else FIGURE_HEIGHT
    free = 1280 - 2 * EDGE - total * h
    if free < 0:
        # Singles only, at full size: members cannot stand side by side, and need not (only the focus is on screen).
        # Spread them evenly within the frame so every member can be framed on the background.
        x0, x1 = EDGE + reaches[0][0] * h, 1280 - EDGE - reaches[-1][1] * h
        n = len(chars)
        return [round(x0 + (x1 - x0) * i / max(1, n - 1), 1) for i in range(n)], round(h, 1)
    step = free / (len(chars) + 1)
    xs, x = [], EDGE
    for left, right in reaches:
        x += step
        xs.append(round(x + left * h, 1))
        x += (left + right) * h
    return xs, round(h, 1)


def make_cutout(png: Path) -> bool:
    """Ensure a pose image is a cut-out. Image models often return a flat background instead of transparency: when the
    four corners share one flat colour, that colour is flood-filled to transparent from each corner (characters have
    bold outlines, so the fill stops at the figure). Returns True if the file was changed. Anything else is left for
    analyse_pose to refuse."""
    img = Image.open(png).convert("RGBA")
    w, h = img.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    if all(img.getpixel(c)[3] <= 16 for c in corners):
        # Already transparent. Image models often add a faint glow around the figure (semi-transparent pixels), which
        # shows as a halo on a set and inflates the measured figure. Bold-outline art has crisp edges, so pixels below
        # 40% opacity are dropped.
        alpha = img.getchannel("A")
        cleaned = alpha.point(lambda v: 0 if v < 102 else v)
        if cleaned.getbbox() != alpha.getbbox() or list(cleaned.getdata()) != list(alpha.getdata()):
            img.putalpha(cleaned)
            img.save(png)
            return True
        return False
    first = img.getpixel(corners[0])
    if any(max(abs(a - b) for a, b in zip(img.getpixel(c)[:3], first[:3])) > 24 for c in corners):
        return False
    original = img.copy()
    img = fill_from_corners(img, corners, thresh=40)
    if sum(first[:3]) / 3 < 235:
        img = clear_enclosed_background(img, original, first[:3])
    if sum(first[:3]) / 3 < 200:
        img = defringe(img, first[:3])
    img.save(png)
    return True


def _reach(mask, seed):
    """Pixels of `mask` connected (4-neighbour) to `seed`: the same region as a flood fill, computed with whole-row and
    whole-column numpy passes (a pixel joins when its run along a row or column touches a reached pixel), repeated
    until nothing changes. A few passes for poses, against seconds for a pixel-by-pixel fill."""
    import numpy as np
    reached = np.zeros_like(mask)
    if not mask[seed]:
        return reached
    reached[seed] = True

    def spread(m, r):
        # runs of True along axis 1: each run is reached if any of its pixels is
        h, w = m.shape
        flat_m, flat_r = m.ravel(), r.ravel()
        starts = m & ~np.concatenate([np.zeros((h, 1), bool), m[:, :-1]], axis=1)
        run_id = np.cumsum(starts.ravel()) * flat_m
        hit = np.zeros(run_id.max() + 1, bool)
        hit[run_id[flat_r & flat_m]] = True
        hit[0] = False
        return hit[run_id].reshape(h, w)

    while True:
        before = int(reached.sum())
        reached = spread(mask, reached)
        reached = spread(mask.T, reached.T).T
        if int(reached.sum()) == before:
            return reached


def fill_from_corners(img: Image.Image, corners, thresh: int = 40) -> Image.Image:
    """Make the background reached from each corner transparent: a pixel is background when its RGBA differs from that
    corner's colour by at most `thresh` in total (as PIL's ImageDraw.floodfill counts it), and it is connected to the
    corner. Same result as the pixel-by-pixel flood fill, much faster."""
    import numpy as np
    a = np.array(img.convert("RGBA")).astype(np.int32)
    clear = np.zeros(a.shape[:2], bool)
    for (x, y) in corners:
        if a[y, x, 3] <= 16 or clear[y, x]:
            continue
        near = np.abs(a - a[y, x]).sum(2) <= thresh
        clear |= _reach(near, (y, x))
    a[clear] = 0
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def clear_enclosed_background(img: Image.Image, original: Image.Image, bg: tuple, min_frac: float = 0.0001,
                              local_tol: int = 10) -> Image.Image:
    """Make background pockets the corner flood fill cannot reach transparent: the gaps between an arm and the body,
    or inside a bag handle, are closed off by the outline, so they kept the background colour and showed as grey
    slivers on a set. The background is often a gentle gradient, so a candidate (a plain grey region of at least
    min_frac of the image, roughly the background's brightness) is compared with the ORIGINAL background just around
    it (pixels the flood fill cleared nearby), not the corner: within local_tol it is background. A similar but
    different grey (hair, a moustache) differs from the background next to it and stays. Thin lines and anti-aliased
    specks are never seeds (the mask is eroded first). Only applied on non-white backgrounds: on white, the big white
    eyes would match."""
    import numpy as np
    from PIL import ImageDraw, ImageFilter
    full = np.array(img.convert("RGBA"))
    # work only inside the figure's box (everything outside it is already cleared): much less to scan
    box = Image.fromarray(full[:, :, 3]).getbbox()
    if not box:
        return img
    x0, y0, x1, y1 = box
    a = full[y0:y1, x0:x1].astype(np.int16)
    o = np.array(original.convert("RGB"))[y0:y1, x0:x1].astype(np.int16)
    rgb = a[:, :, :3]
    cleared = a[:, :, 3] == 0
    plain = (rgb.max(2) - rgb.min(2) <= 10) & (np.abs(rgb.mean(2) - float(np.mean(bg[:3]))) <= 40) & ~cleared
    seeds = np.array(Image.fromarray((plain * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))) > 0
    if not seeds.any():
        return img
    mask = Image.fromarray((plain * 255).astype(np.uint8))
    min_px = int(img.width * img.height * min_frac)
    h, w = plain.shape
    changed = False
    while seeds.any():
        y, x = np.argwhere(seeds)[0]
        m = mask.copy()
        ImageDraw.floodfill(m, (int(x), int(y)), 128)
        region = np.array(m) == 128
        seeds &= ~region
        n = int(region.sum())
        if n < min_px:
            continue
        ys, xs = np.nonzero(region)
        ry0, ry1, rx0, rx1 = max(0, ys.min() - 80), min(h, ys.max() + 81), max(0, xs.min() - 80), min(w, xs.max() + 81)
        near_bg = cleared[ry0:ry1, rx0:rx1]
        if near_bg.sum() < 50:
            continue
        local = o[ry0:ry1, rx0:rx1][near_bg].mean(0)
        if np.abs(rgb[region].mean(0) - local).max() <= local_tol:
            a[region, 3] = 0
            changed = True
    if not changed:
        return img
    full[y0:y1, x0:x1, 3] = a[:, :, 3].astype(np.uint8)
    return Image.fromarray(full, "RGBA")


def defringe(img: Image.Image, bg: tuple, rounds: int = 3) -> Image.Image:
    """Remove the background-coloured fringe a flood fill leaves around dark outlines on a non-white flat background
    (house style v2 poses are drawn on mid-grey): edge pixels close to the background colour become transparent, and
    the anti-aliased edge pixels between the ink and the background become ink with partial transparency, so the line
    blends cleanly onto any set. White backgrounds (v1) never get here."""
    import numpy as np
    from PIL import ImageFilter
    a = np.array(img.convert("RGBA")).astype(np.int32)
    bgv = np.array(bg[:3], dtype=np.int32)
    bg_l = int(bgv.mean())
    for _ in range(rounds):
        clear = a[:, :, 3] <= 16
        near = np.array(Image.fromarray((clear * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
        edge = near & ~clear
        if not edge.any():
            break
        rgb = a[:, :, :3]
        close = edge & (np.abs(rgb - bgv).max(2) <= 36)
        a[close, 3] = 0
    clear = a[:, :, 3] <= 16
    near = np.array(Image.fromarray((clear * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
    edge = near & ~clear
    rgb = a[:, :, :3]
    grey = edge & ((rgb.max(2) - rgb.min(2)) < 24) & (rgb.mean(2) < bg_l)
    if grey.any():
        lum = rgb[grey].mean(1)
        a[grey, 3] = np.clip((bg_l - lum) / max(1, bg_l - 18) * 255, 0, 255).astype(np.int32)
        a[grey, :3] = 18
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def compose_sheet(entries: list[tuple[str, Path]], out: Path, title: str) -> Path:
    """Expression sheet for owner review: every pose side by side at the same scale, labelled."""
    from PIL import ImageDraw, ImageFont
    cell_w, cell_h, pad, head = 300, 470, 16, 70
    cols = min(4, max(1, len(entries)))
    rows = (len(entries) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (cell_w + pad), head + rows * (cell_h + pad)), (245, 242, 236))
    d = ImageDraw.Draw(sheet)
    try:
        big, small = ImageFont.load_default(size=30), ImageFont.load_default(size=22)
    except TypeError:   # Pillow < 10.1
        big = small = ImageFont.load_default()
    d.text((pad, 18), title, fill=(30, 30, 30), font=big)
    for i, (label, f) in enumerate(entries):
        x, y = pad + (i % cols) * (cell_w + pad), head + (i // cols) * (cell_h + pad)
        d.rectangle([x, y, x + cell_w, y + cell_h], fill=(255, 255, 255), outline=(220, 214, 204))
        im = Image.open(f).convert("RGBA")
        box = im.getchannel("A").getbbox() or (0, 0, im.width, im.height)
        im = im.crop(box)
        scale = min((cell_w - 20) / im.width, (cell_h - 60) / im.height)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        sheet.paste(im, (x + (cell_w - im.width) // 2, y + 10 + (cell_h - 60 - im.height)), im)
        d.text((x + 12, y + cell_h - 40), label, fill=(60, 60, 60), font=small)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def analyse_pose(png: Path) -> dict:
    """Feet anchor and figure height of a transparent pose image (what the engine's registry needs)."""
    img = Image.open(png)
    if img.mode != "RGBA":
        raise EngineInputError("pose image has no transparency; poses must be cut-outs on a transparent background")
    alpha = img.getchannel("A")
    w, h = img.size
    corners = [alpha.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    if max(corners) > 16:
        raise EngineInputError("pose image background is not transparent")
    box = alpha.point(lambda v: 255 if v > 16 else 0).getbbox()
    if not box:
        raise EngineInputError("pose image is empty")
    left, top, right, bottom = box
    # Feet: the centre of the opaque pixels in the bottom 2% of the figure.
    band_top = bottom - max(2, (bottom - top) // 50)
    xs = [x for y in range(band_top, bottom) for x in range(left, right) if alpha.getpixel((x, y)) > 16]
    feet_x = round(sum(xs) / len(xs)) if xs else (left + right) // 2
    return {"width": w, "height": h, "feet": {"x": feet_x, "y": bottom}, "figure_height": bottom - top}


def write_registry(char, poses: list[dict], folder: Path) -> Path:
    """Pose registry (engine format) for a generated character. `poses`: [{pose_id, file, sha256, feet, figure_height, expression}]."""
    folder.mkdir(parents=True, exist_ok=True)
    reg = {"character": char.engine_character, "displayName": char.name,
           "note": "Generated by Rivet AI Studio from owner-approved pose images. Do not edit by hand.",
           "poses": {p["pose_id"]: {"name": p["expression"], "file": str(p["file"]), "sha256": p["sha256"], "feet": p["feet"],
                                     "figureHeight": p["figure_height"], "approval": "OWNER_APPROVED_IN_STUDIO",
                                     "status": "approved in the studio dashboard"} for p in poses}}
    f = folder / "registry.json"
    f.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    return f
