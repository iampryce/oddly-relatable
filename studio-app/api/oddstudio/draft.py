"""First-draft assembly of an audio-first episode (owner request 2026-11-23, Episode 14): a watchable 9:16 draft built
from what exists, to judge the whole episode rather than single shots. Free and local; never published.

- The picture: each scene's approved set plate (the wide view) seen through a per-scene camera crop that fills the
  whole 1080x1920 frame (no bars): computed to hold everyone in the scene with a safe margin of 6% of the frame width
  on each side, centred on their heads and shoulders with the head line about a third of the way down; adjustable per
  scene in the workspace. A set too narrow for everyone gets the closest crop inside the plate (never bars) and the
  draft's notes name who falls outside the safe margin; a crop smaller than the frame is scaled up, and said.
- The cast: every character in the scene's staging, at its seat in staging order (speaker first, as the rig seats
  them) or standing on the floor line, drawn from its own approved neutral pose at the height the rig uses for that
  set (acting.cast_height), so all heads share one scale. A seated figure keeps its upper body and has its legs
  shortened to the seat's feet line; a desk front marked on the set is drawn back over anyone seated behind it.
- The speaker of a line with a keyed talking clip (the shot comparison's InfiniteTalk cutout, keyed): the transparent
  clip is placed exactly over the same approved pose it was cut from (talking_key / head_layout), so its head is the
  same size as everyone else's; the pose's body continues below it. A line without a keyed clip shows the speaker's
  approved neutral pose and a "no clip yet" mark, so the gaps are obvious.
- The sound: the episode's own recording, so the lines are in script order with the script's pauses exactly as
  recorded; then the end card from Settings (silent).
- Outputs: one draft MP4 and the per-scene pieces in the Video Library, labelled "Draft: not for publishing". They are
  never the episode's video, so they are never offered to the publishing step.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DRAFT_W, DRAFT_H, FPS = 1080, 1920, 30
END_CARD_S = 2.5
LABEL = "Draft: not for publishing"
IT = "wavespeed-infinitetalk-fast"
CLIP_FADE = 0.08          # the bottom of a talking clip fades into the pose's body below it


# ------------------------------------------------------------------ timeline (pure)
def timeline(scenes: list[dict], total: float) -> list[dict]:
    """The draft's segments in order: every line at its recorded start and end, and the pauses between them, scene by
    scene. scenes: [{"id", "position", "lines": [{"start", "end", ...}]}] in script order. A scene runs from its first
    line (the first scene from 0) to the next scene's first line (the last to the end of the recording)."""
    out = []
    starts = []
    for i, sc in enumerate(scenes):
        timed = [ln for ln in sc["lines"] if "start" in ln]
        starts.append(0.0 if i == 0 else (min(float(ln["start"]) for ln in timed) if timed else None))
    for i, sc in enumerate(scenes):
        t0 = starts[i] if starts[i] is not None else (out[-1]["end"] if out else 0.0)
        t1 = next((s for s in starts[i + 1:] if s is not None), total)
        t = t0
        for li, ln in sorted(((li, ln) for li, ln in enumerate(sc["lines"]) if "start" in ln), key=lambda x: float(x[1]["start"])):
            s, e = max(t, float(ln["start"])), min(t1, float(ln["end"]))
            if s > t + 1e-6:
                out.append({"scene": i, "line": None, "start": round(t, 3), "end": round(s, 3)})
            if e > s:
                out.append({"scene": i, "line": li, "start": round(s, 3), "end": round(e, 3)})
                t = e
        if t1 > t + 1e-6:
            out.append({"scene": i, "line": None, "start": round(t, 3), "end": round(t1, 3)})
    return out


def scene_ranges(segments: list[dict]) -> list[tuple[int, float, float]]:
    """(scene index, start, end) of each scene in the draft (for the per-scene pieces)."""
    out: dict[int, list[float]] = {}
    for s in segments:
        r = out.setdefault(s["scene"], [s["start"], s["end"]])
        r[0], r[1] = min(r[0], s["start"]), max(r[1], s["end"])
    return [(k, v[0], v[1]) for k, v in sorted(out.items())]


# ------------------------------------------------------------------ placement (pure)
def contain(plate_w: int, plate_h: int, w: int = DRAFT_W, h: int = DRAFT_H) -> dict:
    """The whole plate in the 9:16 frame: scale and offset (plate px -> frame px)."""
    s = min(w / plate_w, h / plate_h)
    return {"s": s, "ox": (w - plate_w * s) / 2, "oy": (h - plate_h * s) / 2}


def placement(geo: dict, spot: dict, height: float, fit: dict) -> dict:
    """Where a character's approved pose goes in the frame. geo: the pose's own measures in pose pixels (fig_h,
    neck_x, hip_y, head_w); spot: {"x", "hip_y", "feet_y"} for a seat, or {"x", "floor_y"} standing; height: the cast
    height in set pixels. Returns the pose-pixel -> frame-pixel scale and origin, the leg length when seated, and the
    head width in frame pixels (the same for every character drawn at this height with this head ratio)."""
    k = height / geo["fig_h"]                                   # pose px -> set px
    s = fit["s"]
    if "hip_y" in spot:
        ox_set, oy_set = spot["x"] - geo["neck_x"] * k, spot["hip_y"] - geo["hip_y"] * k
        # in pose px; nothing below the hips for someone seated behind a desk (the desk hides their legs)
        legs = 0.0 if spot.get("behind_desk") else max(1.0, (spot["feet_y"] - spot["hip_y"]) / k)
    else:
        ox_set, oy_set = spot["x"] - geo["neck_x"] * k, spot["floor_y"] - geo["fig_h"] * k
        legs = geo["fig_h"] - geo["hip_y"]
    return {"scale": k * s, "x": fit["ox"] + ox_set * s, "y": fit["oy"] + oy_set * s, "legs": legs,
            "seated": "hip_y" in spot, "head_w": geo["head_w"] * k * s}


def clip_placement(place: dict, lay: dict, clip_size: tuple[int, int] = (720, 900)) -> dict:
    """The keyed talking clip over the same pose it was cut from: clip px -> pose px is (c - lay.x) / lay.scale, so the
    clip lands exactly on the pose (its head is the pose's head, at the same scale)."""
    sc = place["scale"] / lay["scale"]
    return {"scale": sc, "x": place["x"] - lay["x"] * sc, "y": place["y"] - lay["y"] * sc,
            "w": max(1, round(clip_size[0] * sc)), "h": max(1, round(clip_size[1] * sc)),
            "cut_pose_y": (clip_size[1] * (1 - CLIP_FADE) - lay["y"]) / lay["scale"]}


SAFE_MARGIN = 0.06       # of the frame width, on each side
HEAD_LINE = 1 / 3        # the heads' centre this far down the frame
ASPECT = DRAFT_W / DRAFT_H
IDENTITY = {"s": 1.0, "ox": 0.0, "oy": 0.0}


def char_box(geo: dict, place: dict) -> dict:
    """A placed character's box in plate pixels (from a placement made with IDENTITY): its sides, the top of the head,
    the centre of the head and the shoulder line."""
    s = place["scale"]
    return {"left": place["x"], "right": place["x"] + geo["fig_w"] * s, "top": place["y"],
            "head_y": place["y"] + geo["neck_y"] * s / 2, "shoulder_y": place["y"] + geo["vest_y"] * s}


def camera(boxes: dict[str, dict], plate_w: int, plate_h: int) -> dict:
    """The scene's crop of the plate (9:16, in plate pixels) and its notes: wide enough for everyone with SAFE_MARGIN of
    the frame width on each side, the heads' centre at HEAD_LINE, kept inside the plate (no bars). A set too narrow
    for everyone gets the closest crop inside the plate, and the notes say who is outside the safe margin."""
    notes = []
    lo = min(b["left"] for b in boxes.values())
    hi = max(b["right"] for b in boxes.values())
    head = sum(b["head_y"] for b in boxes.values()) / len(boxes)
    w = (hi - lo) / (1 - 2 * SAFE_MARGIN)
    h = w / ASPECT
    max_w = min(plate_w, plate_h * ASPECT)
    if w > max_w + 1e-6:
        w, h = max_w, max_w / ASPECT
    x = (lo + hi) / 2 - w / 2
    y = head - h * HEAD_LINE
    x, y = min(max(0.0, x), plate_w - w), min(max(0.0, y), plate_h - h)
    crop = {"x": round(x, 2), "y": round(y, 2), "w": round(w, 2), "h": round(h, 2)}
    notes += crop_notes(crop, boxes)
    return {**crop, "notes": notes}


def crop_notes(crop: dict, boxes: dict[str, dict]) -> list[str]:
    """What the draft says about a crop: who is outside the safe margin, and any upscaling of the plate."""
    out = []
    m = SAFE_MARGIN * crop["w"]
    cut = [k for k, b in boxes.items() if b["left"] < crop["x"] + m - 0.5 or b["right"] > crop["x"] + crop["w"] - m + 0.5]
    if cut:
        out.append(f"{', '.join(cut)} outside the safe margin: the seats are wider apart than a 9:16 crop of this set allows "
                   "(adjust the crop, move the seat, or use a closer set view)")
    if crop["w"] < DRAFT_W - 0.5:
        out.append(f"the set plate is scaled up x{DRAFT_W / crop['w']:.2f} for this crop")
    return out


def check_crop(crop: dict, plate_w: int, plate_h: int) -> dict:
    """An owner's crop: kept 9:16 and inside the plate (no bars); refused when it cannot be."""
    w = float(crop["w"])
    if w <= 50:
        raise ValueError("the crop is too small")
    h = w / ASPECT
    if w > plate_w + 0.5 or h > plate_h + 0.5:
        raise ValueError(f"a 9:16 crop {w:.0f} px wide does not fit inside this {plate_w}x{plate_h} set (it would leave bars)")
    x, y = float(crop["x"]), float(crop["y"])
    if x < -0.5 or y < -0.5 or x + w > plate_w + 0.5 or y + h > plate_h + 0.5:
        raise ValueError("the crop must stay inside the set plate (no bars)")
    return {"x": round(x, 2), "y": round(y, 2), "w": round(w, 2), "h": round(h, 2)}


def crop_fit(crop: dict) -> dict:
    """Plate px -> frame px for a crop: it fills the whole frame."""
    s = DRAFT_W / crop["w"]
    return {"s": s, "ox": -crop["x"] * s, "oy": -crop["y"] * s}


def spots(staging: dict, cast: list[str], blocking: dict) -> dict[str, dict]:
    """Seats in staging order (speaker first, as the rig seats them); the rest stand, spread along the floor."""
    from .acting import seat_starts
    from .sets import seats_of
    seats = seats_of(blocking)
    starts, _ = seat_starts(staging or {k: "standing" for k in cast}, cast, len(seats))
    out, standing = {}, []
    for k in cast:
        st = starts.get(k, "on")
        if st.startswith("seat:"):
            out[k] = dict(seats[int(st[5:])])
        else:
            standing.append(k)
    lo, hi = blocking.get("stand_min_x", 0), blocking.get("stand_max_x", blocking.get("width", 1000))
    for i, k in enumerate(standing):
        out[k] = {"x": lo + (hi - lo) * (i + 1) / (len(standing) + 1), "floor_y": blocking.get("floor_y", 0)}
    return out


# ------------------------------------------------------------------ pictures
def pose_geometry(fig: Image.Image) -> dict:
    """The pose's own measures (alpha-cropped pose pixels): height, neck x, hip line, head width."""
    from .shot_compare import body_marks, rig_module
    import numpy as np
    m = body_marks(fig)
    hip = None
    try:
        rx = rig_module()
        a = np.array(fig.convert("RGBA"))
        b = rx.measure_body(a, rx.detect_style(a))
        hip = (b["hip_l"][1] + b["hip_r"][1]) / 2
    except Exception:            # noqa: BLE001 (the house proportions: legs are about 40% of the height)
        pass
    return {"fig_h": fig.height, "fig_w": fig.width, "neck_x": m["neck_x"], "neck_y": m["neck_y"], "vest_y": m["vest_y"],
            "hip_y": float(hip or 0.60 * fig.height), "head_w": m["head_w"]}


def seated(fig: Image.Image, geo: dict, legs: float) -> Image.Image:
    """A front-facing seated figure from a standing pose: the upper body as drawn, the legs shortened to the seat."""
    hip = round(geo["hip_y"])
    up = fig.crop((0, 0, fig.width, hip))
    if legs < 1:
        return up
    lg = fig.crop((0, hip, fig.width, fig.height)).resize((fig.width, max(1, round(legs))), Image.LANCZOS)
    out = Image.new("RGBA", (fig.width, up.height + lg.height), (0, 0, 0, 0))
    out.paste(up, (0, 0))
    out.paste(lg, (0, up.height), lg)
    return out


def background(plate: Path, crop: dict) -> Image.Image:
    """The scene's crop of the set plate, filling the whole frame (no bars)."""
    with Image.open(plate) as im:
        box = (crop["x"], crop["y"], crop["x"] + crop["w"], crop["y"] + crop["h"])
        return im.convert("RGB").resize((DRAFT_W, DRAFT_H), Image.LANCZOS, box=box)


def _font(size: int):
    from .config import REPO_ROOT
    for f in ("skills/directing-stickman-videos/assets/fonts/NotoSans.ttf",):
        p = REPO_ROOT / f
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def tag(img: Image.Image, text: str, xy: tuple[int, int], fill=(200, 30, 30), size: int = 40) -> None:
    d = ImageDraw.Draw(img)
    f = _font(size)
    box = d.textbbox(xy, text, font=f)
    d.rectangle((box[0] - 14, box[1] - 10, box[2] + 14, box[3] + 10), fill=fill)
    d.text(xy, text, font=f, fill=(255, 255, 255))


def end_card(text: str) -> Image.Image:
    img = Image.new("RGB", (DRAFT_W, DRAFT_H), (0x2A, 0x1D, 0x16))
    d = ImageDraw.Draw(img)
    f = _font(84)
    box = d.textbbox((0, 0), text, font=f)
    d.text(((DRAFT_W - (box[2] - box[0])) / 2, DRAFT_H / 2 - 60), text, font=f, fill=(0xBC, 0x4C, 0x15))
    tag(img, LABEL, (40, DRAFT_H - 120), fill=(90, 90, 90), size=34)
    return img


# ------------------------------------------------------------------ the keyed clips
def keyed_clips(db, ep) -> dict[tuple[int, int], dict]:
    """(scene id, line) -> the newest keyed InfiniteTalk clip for that line: {"keyed_asset_id", "pid", "speaker"}."""
    from . import shot_compare as SC
    out: dict[tuple[int, int], dict] = {}
    for p in sorted(SC.records(db).values(), key=lambda p: p.get("created", 0)):
        if p.get("episode_id") != ep.id or p.get("own_frame"):
            continue
        k = ((p.get("results") or {}).get(IT) or {}).get("key") or {}
        if k.get("status") == "done" and k.get("keyed_asset_id"):
            out[(p["scene_id"], p["line"])] = {"keyed_asset_id": k["keyed_asset_id"], "pid": p["id"], "speaker": p.get("speaker")}
    return out


def _decode_rgba(ffmpeg: str, video: Path, size: tuple[int, int]):
    """Frames of a VP9 WebM with alpha, one at a time, as RGBA PIL images."""
    w, h = size
    p = subprocess.Popen([ffmpeg, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = w * h * 4
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield Image.frombytes("RGBA", (w, h), buf)
    finally:
        p.stdout.close()
        p.wait()


def _fade_bottom(im: Image.Image) -> Image.Image:
    """The clip's last CLIP_FADE of rows fade out, so it blends into the pose's body drawn below it."""
    import numpy as np
    a = np.asarray(im.getchannel("A"), dtype=np.float32)
    start = int(im.height * (1 - CLIP_FADE))
    a[start:] *= np.linspace(1.0, 0.0, im.height - start, dtype=np.float32)[:, None]
    im.putalpha(Image.fromarray(a.round().astype(np.uint8)))
    return im


# ------------------------------------------------------------------ the draft
def render(db, ep, folder: Path, log=print) -> dict:
    """Render the draft (frames composed here, encoded by FFmpeg with the recording) and the per-scene pieces."""
    from . import scene_sets
    from . import sets as studio_sets
    from .audio_production import source_audio
    from .config import get_settings
    from .models import Asset, Character, CharacterAsset
    from .settings_store import get_section
    from .shot_compare import FRAME_SIZE, body_marks, head_layout
    from .storage import storage
    from .acting import TYPICAL_HEAD, cast_height
    ff = get_settings().ffmpeg
    folder.mkdir(parents=True, exist_ok=True)
    scenes = sorted(ep.scenes, key=lambda s: s.position)
    if not scenes:
        raise RuntimeError("the episode has no storyboard scenes")
    src, total = source_audio(db, ep, folder / "source")
    end_text = get_section(db, "production").get("end_card") or "Oddly Relatable"
    chars = {c.key: c for c in db.query(Character).all()}

    # every character's approved neutral pose, measured once
    figs: dict[str, tuple[Image.Image, dict]] = {}

    def fig_of(key: str):
        if key not in figs:
            c = chars.get(key)
            pid = (c.expressions or {}).get("neutral") if c else None
            a = db.get(CharacterAsset, int(pid[1:])) if pid and pid.startswith("p") else None
            if a is None or a.status != "approved":
                raise RuntimeError(f"{key} has no approved neutral pose")
            f = Image.open(storage().get_to_file(a.storage_key, folder / f"pose-{key}.png")).convert("RGBA")
            f = f.crop(f.getchannel("A").getbbox() or (0, 0, f.width, f.height))
            figs[key] = (f, pose_geometry(f))
        return figs[key]

    # each scene's picture: the set, the cast at its places, the desk front over those behind it
    clips = keyed_clips(db, ep)
    plans, sets_cache, notes = [], {}, []
    cameras = draft_cameras(db, ep.id)
    for sc in scenes:
        sid = scene_sets.scene_set(ep, sc)
        if not sid:
            raise RuntimeError(f"scene {sc.position} has no approved set")
        if sid not in sets_cache:
            spec = studio_sets.spec_for(db, sid, folder / f"set-{sid}")
            if spec is None:
                raise RuntimeError(f"the set {sid!r} is not an approved set")
            sets_cache[sid] = spec
        spec = sets_cache[sid]
        cast = [k for k in (sc.staging or {}) if k in chars] or [k for k in (sc.characters or []) if k in chars]
        for ln in sc.lines or []:
            if ln.get("speaker") in chars and ln["speaker"] not in cast:
                cast.append(ln["speaker"])
        ratios = [fig_of(k)[1]["head_w"] / fig_of(k)[1]["fig_h"] for k in cast] or [TYPICAL_HEAD]
        h = cast_height(studio_sets.seats_of(spec), max(ratios))
        where = spots(sc.staging or {}, cast, spec)
        tf = spec.get("table_front")
        for k, w in where.items():      # seated behind the desk front: upper body only, the desk drawn over the rest
            if tf and "hip_y" in w and tf["x0"] <= w["x"] <= tf["x1"] and w["hip_y"] < tf["y1"]:
                w["behind_desk"] = True
        # the camera: computed from everyone's place in the plate, unless the owner set this scene's crop
        boxes = {k: char_box(fig_of(k)[1], placement(fig_of(k)[1], where[k], h, IDENTITY)) for k in cast}
        cam = camera(boxes, spec["width"], spec["height"])
        own = (cameras or {}).get(str(sc.id))
        if own:
            crop = check_crop(own, spec["width"], spec["height"])
            cam = {**crop, "notes": crop_notes(crop, boxes), "own": True}
        fit = crop_fit(cam)
        notes += [f"scene {sc.position}: {n}" for n in cam["notes"]]
        plans.append({"sc": sc, "spec": spec, "cast": cast, "h": h, "fit": fit, "where": where, "crop": cam,
                      "places": {k: placement(fig_of(k)[1], where[k], h, fit) for k in cast}})

    def figure_img(key: str, pl: dict, below_pose_y: float | None = None) -> tuple[Image.Image, tuple[int, int]]:
        f, geo = fig_of(key)
        place = pl["places"][key]
        img = seated(f, geo, place["legs"]) if place["seated"] else f
        top = 0
        if below_pose_y is not None:                       # only the body below a talking clip
            top = max(0, min(img.height - 1, round(below_pose_y)))
            img = img.crop((0, top, img.width, img.height))
        img = img.resize((max(1, round(img.width * place["scale"])), max(1, round(img.height * place["scale"]))), Image.LANCZOS)
        return img, (round(place["x"]), round(place["y"] + top * place["scale"]))

    def desk_front(pl: dict) -> tuple[Image.Image, tuple[int, int]] | None:
        tf = pl["spec"].get("table_front")
        if not tf:
            return None
        fit = pl["fit"]
        with Image.open(pl["spec"]["plate"]) as im:
            crop = im.convert("RGB").crop((tf["x0"], tf["y0"], tf["x1"], tf["y1"]))
        w, hh = round((tf["x1"] - tf["x0"]) * fit["s"]), round((tf["y1"] - tf["y0"]) * fit["s"])
        return crop.resize((max(1, w), max(1, hh)), Image.LANCZOS), (round(fit["ox"] + tf["x0"] * fit["s"]), round(fit["oy"] + tf["y0"] * fit["s"]))

    def behind_desk(pl: dict, key: str) -> bool:
        tf, w = pl["spec"].get("table_front"), pl["where"].get(key) or {}
        return bool(tf and "hip_y" in w and tf["x0"] <= w["x"] <= tf["x1"] and w["hip_y"] < tf["y1"])

    def base(pl: dict, speaker: str | None, clip: dict | None) -> Image.Image:
        img = background(Path(pl["spec"]["plate"]), pl["crop"])
        for k in pl["cast"]:
            if k == speaker and clip is not None:
                fi, xy = figure_img(k, pl, clip["cut_pose_y"])
            else:
                fi, xy = figure_img(k, pl)
            img.paste(fi, xy, fi)
        df = desk_front(pl)
        if df and clip is None and any(behind_desk(pl, k) for k in pl["cast"]):
            img.paste(*df)
        tag(img, LABEL, (36, 40), fill=(60, 60, 60), size=30)
        return img

    segs = timeline([{"lines": p["sc"].lines or []} for p in plans], total)
    # each segment's picture: a still, or a still with the keyed clip over it frame by frame
    enc = subprocess.Popen([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{DRAFT_W}x{DRAFT_H}", "-r", str(FPS),
                            "-i", "-", "-i", str(src), "-map", "0:v:0", "-map", "1:a:0", "-af", "apad", "-shortest",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                            str(folder / "draft.mp4")], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    written, report = 0, []

    def put(img: Image.Image, until: float):
        nonlocal written
        n = round(until * FPS) - written
        if n > 0:
            b = img.convert("RGB").tobytes()
            for _ in range(n):
                enc.stdin.write(b)
            written += n

    try:
        for seg in segs:
            pl = plans[seg["scene"]]
            if seg["line"] is None:
                put(base(pl, None, None), seg["end"])
                continue
            ln = pl["sc"].lines[seg["line"]]
            spk = ln.get("speaker")
            has = clips.get((pl["sc"].id, seg["line"]))
            if not has or spk not in pl["places"]:
                img = base(pl, None, None)
                tag(img, f"NO CLIP YET · scene {pl['sc'].position}, line {seg['line'] + 1}", (36, 120))
                put(img, seg["end"])
                report.append({"scene": pl["sc"].position, "line": seg["line"] + 1, "clip": False})
                continue
            f, geo = fig_of(spk)
            lay = head_layout(body_marks(f), *FRAME_SIZE["cutout"])
            cp = clip_placement(pl["places"][spk], lay, FRAME_SIZE["cutout"])
            still = base(pl, spk, cp)
            df = desk_front(pl) if behind_desk(pl, spk) else None
            webm = storage().get_to_file(db.get(Asset, has["keyed_asset_id"]).storage_key, folder / f"clip-{has['pid']}.webm")
            last = None
            for fr in _decode_rgba(ff, webm, FRAME_SIZE["cutout"]):
                if written >= round(seg["end"] * FPS):
                    break
                last = _fade_bottom(fr.resize((cp["w"], cp["h"]), Image.BILINEAR))
                img = still.copy()
                img.paste(last, (round(cp["x"]), round(cp["y"])), last)
                if df:
                    img.paste(*df)
                put(img, (written + 1) / FPS)
            if written < round(seg["end"] * FPS):        # a clip shorter than its line: its last frame is held
                img = still.copy()
                if last is not None:
                    img.paste(last, (round(cp["x"]), round(cp["y"])), last)
                if df:
                    img.paste(*df)
                put(img, seg["end"])
            report.append({"scene": pl["sc"].position, "line": seg["line"] + 1, "clip": True, "plan": has["pid"]})
        put(end_card(end_text), total + END_CARD_S)
    finally:
        enc.stdin.close()
        err = enc.stderr.read().decode(errors="replace")
        rc = enc.wait()
    if rc != 0:
        raise RuntimeError(f"the draft could not be encoded: {err.strip()[-300:]}")
    pieces = []
    for i, t0, t1 in scene_ranges(segs):
        out = folder / f"scene-{plans[i]['sc'].position}.mp4"
        r = subprocess.run([ff, "-v", "error", "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(folder / "draft.mp4"),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"scene {plans[i]['sc'].position}: {r.stderr.strip()[-200:]}")
        pieces.append({"scene": plans[i]["sc"].position, "path": out, "start": t0, "end": t1})
    log(f"draft: {sum(1 for r in report if r['clip'])} of {len(report)} lines with a talking clip")
    for n in notes:
        log(f"draft: {n}")
    return {"draft": folder / "draft.mp4", "pieces": pieces, "lines": report, "seconds": round(total + END_CARD_S, 3),
            "notes": notes, "crops": {str(p["sc"].position): {k: p["crop"][k] for k in ("x", "y", "w", "h")} for p in plans}}


# ------------------------------------------------------------------ the episode's Talking shots section (API)
from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from .auth import current_user  # noqa: E402
from .db import get_db  # noqa: E402

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _line_plan(recs: dict, ep_id: int, scene_id: int, line: int) -> dict | None:
    """The line's plan in the shot comparison: the newest original-art plan (not failed)."""
    best = None
    for p in recs.values():
        if (p.get("episode_id") == ep_id and p.get("scene_id") == scene_id and p.get("line") == line and not p.get("base_plan")
                and p.get("status") != "failed" and (best is None or p.get("created", 0) > best.get("created", 0))):
            best = p
    return best


def line_status(p: dict | None, db=None) -> tuple[str, str]:
    """(status, message) of a line's talking shot: not run / preparing / queued / running / failed / keying / keyed."""
    if p is None:
        return "not run", ""
    if p.get("status") == "preparing":
        return "preparing", ""
    r = (p.get("results") or {}).get(IT)
    if not r:
        return "not run", ""
    if r.get("status") in ("queued", "running"):
        return r["status"], ""
    if r.get("status") == "failed":
        return "failed", r.get("error") or ""
    k = r.get("key") or {}
    if db is not None and k:
        from .shot_compare import key_state
        k = key_state(db, p["id"], IT, k) or {}
    if k.get("status") == "done":
        return "keyed", ""
    if k.get("status") == "failed":
        return "done", f"keying failed: {k.get('error') or ''}"
    return "done", "keying…" if k.get("status") in ("queued", "running") else ""


def talking_lines(db, ep) -> list[dict]:
    from . import shot_compare as SC
    recs = SC.records(db)
    out = []
    for sc in sorted(ep.scenes, key=lambda s: s.position):
        for i, ln in enumerate(sc.lines or []):
            if "start" not in ln:
                continue
            p = _line_plan(recs, ep.id, sc.id, i)
            st, msg = line_status(p, db)
            secs = SC.bill_seconds(p) if p else round(float(ln["end"]) - float(ln["start"]), 3)
            r = ((p or {}).get("results") or {}).get(IT) or {}
            row = {"scene_id": sc.id, "scene": sc.position, "line": i, "speaker": ln.get("speaker"), "text": ln.get("text", ""),
                   "start": ln["start"], "end": ln["end"], "seconds": secs, "plan_id": (p or {}).get("id"), "status": st,
                   "message": msg, "estimate_usd": SC.estimate(IT, secs)["usd"], "actual_usd": r.get("actual_usd"),
                   "plan_ready": bool(p and p.get("status") == "ready")}
            if p and p.get("status") == "ready":
                row.update({"cap_usd": SC.plan_cap(db, p), "cap_used_usd": SC.plan_spent(p),
                            "blocked": SC.talking_blocked(db, p, IT)})
                k = r.get("key") or {}
                if k.get("status") == "done":
                    from .models import Asset
                    from .storage import storage
                    a = db.get(Asset, k.get("over_set_asset_id")) if k.get("over_set_asset_id") else None
                    row["preview_url"] = storage().url(a.storage_key) if a else None
            out.append(row)
    return out


def talking_counts(db, ep) -> dict:
    rows = talking_lines(db, ep)
    return {"lines": len(rows), "keyed": sum(r["status"] == "keyed" for r in rows),
            "running": sum(r["status"] in ("queued", "running", "preparing") for r in rows),
            "failed": sum(r["status"] == "failed" for r in rows)}


def _episode(db, eid: int):
    from .models import Episode
    ep = db.get(Episode, eid)
    if ep is None or ep.source != "audio":
        raise HTTPException(404, "an audio-first episode is needed")
    return ep


def latest_draft(db, ep) -> dict | None:
    from .models import Asset, Job
    from .storage import storage
    j = (db.query(Job).filter_by(episode_id=ep.id, kind="episode_draft").order_by(Job.id.desc()).first())
    if j is None:
        return None
    out = {"job_id": j.id, "status": j.status, "error": (j.error or "")[:300]}
    res = j.result or {}
    if j.status == "succeeded" and res.get("asset_id"):
        a = db.get(Asset, res["asset_id"])
        out.update({"url": storage().url(a.storage_key) if a else None, "label": a.label if a else "", "lines": res.get("lines"),
                    "notes": res.get("notes") or [],
                    "with_clip": res.get("with_clip"), "seconds": res.get("seconds"),
                    "pieces": [{"scene": x["scene"], "url": storage().url(db.get(Asset, x["asset_id"]).storage_key)}
                               for x in res.get("pieces", []) if db.get(Asset, x["asset_id"])]})
    return out


@router.get("/episodes/{eid}/talking-shots")
def get_talking(eid: int, db: Session = Depends(get_db)):
    """The episode's lines with their talking-shot status and cost (estimate before, actual after), the experimental
    budget, and the latest draft."""
    from . import fal
    from . import shot_compare as SC
    ep = _episode(db, eid)
    m = SC.TALKING[IT]
    return {"lines": talking_lines(db, ep), "model": {"id": IT, "label": m["label"], "price": m["price"], "terms": m["terms"]},
            "spent_usd": round(fal.spent(db)["total"], 4), "pending_usd": SC.pending_usd(db), "budget_usd": fal.budget(db),
            "draft": latest_draft(db, ep)}


class LinesIn(BaseModel):
    lines: list[dict] = Field(default_factory=list, max_length=200)    # [{"scene_id", "line"}]


@router.post("/episodes/{eid}/talking-shots/prepare")
def prepare_talking(eid: int, body: LinesIn, db: Session = Depends(get_db)):
    """Free: a shot plan for each chosen line (made without the text writer or the rig render), and the cutout first
    frame on any plan that does not have it yet. Nothing paid."""
    import tempfile
    from pathlib import Path as P
    from . import shot_compare as SC
    from .models import StoryboardScene
    ep = _episode(db, eid)
    made = 0
    for x in body.lines:
        sc = db.get(StoryboardScene, int(x.get("scene_id", 0)))
        li = int(x.get("line", -1))
        if sc is None or sc.episode_id != ep.id or not 0 <= li < len(sc.lines or []):
            raise HTTPException(404, "no such line")
        p, new = SC.plan_for_line(db, ep, sc, li, talking_only=True)
        made += new
        if not new and p.get("status") == "ready" and not (p.get("frame_assets") or {}).get("cutout"):
            with tempfile.TemporaryDirectory() as tmp:
                pose, spec = SC.frame_inputs(db, p, P(tmp))
                frame, colour = SC.make_framing(db, p, pose, spec, "cutout", P(tmp))
                aid = SC.store_frame(db, p, "cutout", frame)
            recs = SC.records(db)
            recs[p["id"]]["frame_assets"] = {**(recs[p["id"]].get("frame_assets") or {}), "cutout": aid}
            recs[p["id"]]["key_colour"] = colour
            SC.save(db, recs)
    db.commit()
    return {"queued": made, **get_talking(eid, db)}


@router.post("/episodes/{eid}/draft")
def make_draft(eid: int, db: Session = Depends(get_db)):
    """Free and local: queue the first-draft assembly."""
    from .models import Job
    from .queue import enqueue
    ep = _episode(db, eid)
    if db.query(Job).filter(Job.episode_id == ep.id, Job.kind == "episode_draft", Job.status.in_(("queued", "running"))).first():
        raise HTTPException(409, "a draft is already being made")
    j = enqueue(db, "episode_draft", episode_id=ep.id, payload={})
    db.commit()
    return {"job_id": j.id}


from .tasks import Ctx, store_asset, task  # noqa: E402


@task
def episode_draft(ctx: Ctx) -> dict:
    """Free and local: the first draft and its per-scene pieces, stored in the Video Library as drafts (never the
    episode's video, so never offered to publishing)."""
    from .models import Episode
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    folder = ctx.folder("episodes", ep.id, "draft", f"job{job.id}")
    res = render(db, ep, folder, ctx.log)
    with_clip = sum(1 for r in res["lines"] if r["clip"])
    base = f"episodes/{ep.id}/draft/job{job.id}"
    a = store_asset(db, ep_id=ep.id, src=res["draft"], key=f"{base}/draft.mp4", kind="video", revision=ep.revision,
                    label=f"{LABEL}: first draft ({with_clip} of {len(res['lines'])} lines with a talking clip)",
                    content_type="video/mp4", job_id=job.id)
    pieces = []
    for pc in res["pieces"]:
        pa = store_asset(db, ep_id=ep.id, src=pc["path"], key=f"{base}/scene-{pc['scene']}.mp4", kind="video", revision=ep.revision,
                         label=f"{LABEL}: scene {pc['scene']}", content_type="video/mp4", job_id=job.id)
        pieces.append({"scene": pc["scene"], "asset_id": pa.id, "start": pc["start"], "end": pc["end"]})
    db.commit()
    return {"asset_id": a.id, "pieces": pieces, "lines": res["lines"], "with_clip": with_clip, "seconds": res["seconds"],
            "notes": res["notes"], "crops": res["crops"]}


# ------------------------------------------------------------------ the draft's camera per scene (workspace)
CAMERAS = "_draft_cameras"      # {episode id: {scene id: {x, y, w}}}: the owner's crops (else the computed one)


def draft_cameras(db, eid: int) -> dict:
    from .models import Setting
    row = db.get(Setting, CAMERAS)
    return dict(((row.value or {}) if row else {}).get(str(eid)) or {})


def scene_cameras(db, ep, folder: Path) -> list[dict]:
    """Each scene's plate, everyone's box on it, the computed crop and the owner's crop (if any), for the workspace."""
    from . import scene_sets
    from . import sets as studio_sets
    from .acting import TYPICAL_HEAD, cast_height
    from .models import Asset, Character, CharacterAsset
    from .storage import storage
    chars = {c.key: c for c in db.query(Character).all()}
    own = draft_cameras(db, ep.id)
    geos: dict[str, dict] = {}
    out = []
    for sc in sorted(ep.scenes, key=lambda s: s.position):
        sid = scene_sets.scene_set(ep, sc)
        spec = studio_sets.spec_for(db, sid, folder / f"set-{sid}") if sid else None
        if spec is None:
            out.append({"scene_id": sc.id, "scene": sc.position, "error": "no approved set"})
            continue
        cast = [k for k in (sc.staging or {}) if k in chars] or [k for k in (sc.characters or []) if k in chars]
        for ln in sc.lines or []:
            if ln.get("speaker") in chars and ln["speaker"] not in cast:
                cast.append(ln["speaker"])
        try:
            for k in cast:
                if k not in geos:
                    pid = (chars[k].expressions or {}).get("neutral")
                    a = db.get(CharacterAsset, int(pid[1:])) if pid and pid.startswith("p") else None
                    if a is None or a.status != "approved":
                        raise RuntimeError(f"{k} has no approved neutral pose")
                    f = Image.open(storage().get_to_file(a.storage_key, folder / f"pose-{k}.png")).convert("RGBA")
                    geos[k] = pose_geometry(f.crop(f.getchannel("A").getbbox() or (0, 0, f.width, f.height)))
        except RuntimeError as e:
            out.append({"scene_id": sc.id, "scene": sc.position, "error": str(e)})
            continue
        h = cast_height(studio_sets.seats_of(spec), max([geos[k]["head_w"] / geos[k]["fig_h"] for k in cast] or [TYPICAL_HEAD]))
        where = spots(sc.staging or {}, cast, spec)
        boxes = {k: char_box(geos[k], placement(geos[k], where[k], h, IDENTITY)) for k in cast}
        cam = camera(boxes, spec["width"], spec["height"])
        mine = own.get(str(sc.id))
        rec = studio_sets.approved(db).get(sid) or {}
        a = db.get(Asset, rec.get("asset_id")) if rec.get("asset_id") else None
        out.append({"scene_id": sc.id, "scene": sc.position, "set_id": sid, "plate_url": storage().url(a.storage_key) if a else None,
                    "plate": {"w": spec["width"], "h": spec["height"]},
                    "boxes": {k: {x: round(v, 1) for x, v in b.items()} for k, b in boxes.items()},
                    "computed": cam, "own": mine,
                    "notes": crop_notes(check_crop(mine, spec["width"], spec["height"]), boxes) if mine else cam["notes"]})
    return out


@router.get("/episodes/{eid}/draft/cameras")
def get_cameras(eid: int, db: Session = Depends(get_db)):
    import tempfile
    ep = _episode(db, eid)
    with tempfile.TemporaryDirectory() as tmp:
        return {"scenes": scene_cameras(db, ep, Path(tmp)), "aspect": "9:16", "safe_margin": SAFE_MARGIN}


class CameraIn(BaseModel):
    scene_id: int
    crop: dict | None = None        # {x, y, w} in plate pixels (9:16); None: back to the computed crop


@router.put("/episodes/{eid}/draft/cameras")
def put_camera(eid: int, body: CameraIn, db: Session = Depends(get_db)):
    """Free: this scene's crop for the draft (kept 9:16 and inside the plate), or back to the computed one."""
    from . import scene_sets
    from . import sets as studio_sets
    from .models import Setting, StoryboardScene
    import tempfile
    ep = _episode(db, eid)
    sc = db.get(StoryboardScene, body.scene_id)
    if sc is None or sc.episode_id != ep.id:
        raise HTTPException(404, "no such scene")
    row = db.get(Setting, CAMERAS)
    allc = dict(row.value or {}) if row else {}
    mine = dict(allc.get(str(ep.id)) or {})
    if body.crop is None:
        mine.pop(str(sc.id), None)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            spec = studio_sets.spec_for(db, scene_sets.scene_set(ep, sc), Path(tmp))
        if spec is None:
            raise HTTPException(409, "the scene has no approved set")
        try:
            mine[str(sc.id)] = check_crop(body.crop, spec["width"], spec["height"])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(422, str(e))
    allc[str(ep.id)] = mine
    if row:
        row.value = allc
    else:
        db.add(Setting(key=CAMERAS, value=allc))
    db.commit()
    return get_cameras(eid, db)
