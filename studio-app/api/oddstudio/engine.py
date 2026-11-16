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


def build_story(*, episode_id: int, revision: int, title: str, script: dict, scenes: list, chars_by_key: dict,
                production: dict, only_scene_ids: set[int] | None = None, end_card: bool = True) -> dict:
    """Engine story for the approved storyboard (or a subset of scenes, for previews and scene re-runs)."""
    envs = set(environments())
    out_scenes = []
    used = []
    for sc in scenes:
        if only_scene_ids is not None and sc.id not in only_scene_ids:
            continue
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
        xs = POSITIONS[len(chars)]
        cast = []
        for i, c in enumerate(chars):
            m = {"id": engine_id(c.key), "character": c.engine_character,
                 "placement": {"feetX": xs[i], "feetY": 2070, "figureHeight": 760}, "z": i,
                 "speech": {"style": c.bubble_style}}
            if c.registry_path and c.registry_path != f"production/characters/{c.engine_character}.json":
                m["registry"] = c.registry_path
            cast.append(m)
        lines = []
        for li, ln in enumerate(sc.lines):
            speaker = chars_by_key[ln["speaker"]]
            line = {"speaker": engine_id(speaker.key), "text": ln["text"], "pose": pose_for(speaker, ln.get("expression", ""))}
            if li == 0:   # every cast member needs a pose on the first line
                line["poses"] = {engine_id(c.key): pose_for(c, ln.get("expression", "") if c is speaker else c.default_expression)
                                 for c in chars}
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
        out_scenes.append({"id": engine_id(sc.scene_key) + f"-{sc.position}", "format": "face-to-face", "environment": env,
                           "cast": cast, "lines": lines})
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
    if script.get("hook"):
        story["hook"] = {"text": script["hook"], "start": 0, "duration": 2.5}
    return story


def run_node(args: list[str], *, timeout: int, log: Callable[[str], None], watch: Callable[[], None] | None = None) -> tuple[int, str]:
    """Run the engine CLI (argument list, no shell), streaming its output to `log`; `watch` is polled while it runs."""
    s = get_settings()
    p = subprocess.Popen([s.node_bin, str(CLI), *args], cwd=str(REPO_ROOT), env=env_for_node(),
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


def make_cutout(png: Path) -> bool:
    """Ensure a pose image is a cut-out. Image models often return a flat background instead of transparency: when the
    four corners share one flat colour, that colour is flood-filled to transparent from each corner (characters have
    bold outlines, so the fill stops at the figure). Returns True if the file was changed. Anything else is left for
    analyse_pose to refuse."""
    from PIL import ImageDraw
    img = Image.open(png).convert("RGBA")
    w, h = img.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    if all(img.getpixel(c)[3] <= 16 for c in corners):
        return False
    first = img.getpixel(corners[0])
    if any(max(abs(a - b) for a, b in zip(img.getpixel(c)[:3], first[:3])) > 24 for c in corners):
        return False
    for c in corners:
        if img.getpixel(c)[3] > 16:
            ImageDraw.floodfill(img, c, (0, 0, 0, 0), thresh=40)
    img.save(png)
    return True


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
           "note": "Generated by Oddly Relatable Studio from owner-approved pose images. Do not edit by hand.",
           "poses": {p["pose_id"]: {"name": p["expression"], "file": str(p["file"]), "sha256": p["sha256"], "feet": p["feet"],
                                     "figureHeight": p["figure_height"], "approval": "OWNER_APPROVED_IN_STUDIO",
                                     "status": "approved in the studio dashboard"} for p in poses}}
    f = folder / "registry.json"
    f.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    return f
