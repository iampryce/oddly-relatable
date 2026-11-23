"""Talking shots without a background (owner request 2026-11-23): the character alone, to be placed over the episode's
approved set at assembly.

1. The first frame: the character's own approved pose (its transparent art, never the set plate), cut to the same
   head and shoulders as the "head" framing (720x900, head near the top, ending in the upper vest, no hands), on a flat
   solid key colour with no gradient, no shadow and no set. The colour is #FF00FF unless the character's approved art
   comes close to it (then the next candidate); the colour used is recorded with the plan. The art's edge is made hard
   (alpha at 50%) so no pixel of the first frame is a mix of the art and the key colour.
2. After a clip finishes, a free local keying step: the key colour is removed with a colour key (the same maths as
   FFmpeg's colorkey: a small similarity, then a soft blend), the edge is softened by one pixel, and the key colour's
   spill is removed in a thin band along the edge only (so the thick outline and white hair keep no magenta fringe, and
   purple or pink clothing inside the character is never touched). FFmpeg decodes and encodes; the keyed frames are
   computed here, so the result is the same on every machine.
   Outputs: a keyed copy with transparency (VP9 WebM with alpha, our line audio in Opus), previews over the episode's
   approved set and over mid-grey (H.264), and one check image (3 timepoints x the 2 backgrounds). The clip it was made
   from is never changed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

KEY_CANDIDATES = ("#FF00FF", "#00FF00", "#0000FF", "#00FFFF")
SIMILARITY = 0.12     # distance (0..1, RGB) under which a pixel is fully the key colour
BLEND = 0.10          # then alpha ramps up over this distance (edge softening)
EDGE_CHOKE_PX = 2    # the matte is pulled in this far past the halo scaling leaves along the outline
CHOKE = 0.20        # edge alpha under this becomes transparent (no speck of compression noise along the outline)
ART_MARGIN = 0.30    # a candidate is refused when any opaque art pixel is this close to it (it would be keyed out)
GREY = (128, 128, 128)
CHECK_AT = (0.10, 0.50, 0.90)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def distance(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    """Normalised RGB distance to the key colour, 0 (the key itself) to 1."""
    k = np.array(key, dtype=np.float32)
    return np.sqrt(((rgb.astype(np.float32) - k) ** 2).sum(-1)) / (255.0 * np.sqrt(3.0))


def art_near(path: Path, key: tuple[int, int, int], margin: float = ART_MARGIN) -> bool:
    """Whether any opaque pixel of the approved art is close enough to the key colour to be keyed out with it."""
    with Image.open(path) as im:
        a = np.asarray(im.convert("RGBA"))
    opaque = a[:, :, 3] >= 128
    if not opaque.any():
        return False
    return bool((distance(a[:, :, :3][opaque], key) < margin).any())


def key_colour(art: list[Path]) -> str:
    """#FF00FF unless the character's approved art contains it (or something close); then the next candidate."""
    for c in KEY_CANDIDATES:
        if not any(art_near(p, hex_rgb(c)) for p in art):
            return c
    raise ValueError("every key colour appears in this character's approved art")


def compose_cutout(pose: Path, colour: str, out: Path) -> dict:
    """The head-and-shoulders cutout on the flat key colour: the same crop as the "head" framing, from the character's
    own transparent art only. Returns the layout used (for the plan)."""
    from .shot_compare import FRAME_SIZE, body_marks, head_layout
    ow, oh = FRAME_SIZE["cutout"]
    fig = Image.open(pose).convert("RGBA")
    fig = fig.crop(fig.getchannel("A").getbbox() or (0, 0, fig.width, fig.height))
    lay = head_layout(body_marks(fig), ow, oh)
    s = lay["scale"]
    size = (max(1, round(fig.width * s)), max(1, round(fig.height * s)))
    figs = fig.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")   # premultiplied: no dark or key halo
    hard = figs.getchannel("A").point(lambda v: 255 if v >= 128 else 0)      # no art pixel mixed with the key colour
    canvas = Image.new("RGB", (ow, oh), hex_rgb(colour))
    canvas.paste(figs.convert("RGB"), (lay["x"], lay["y"]), hard)
    canvas.save(out)
    return {"colour": colour, "fit": lay["fit"], "size": [ow, oh]}


# ------------------------------------------------------------------ keying
def _box3(a: np.ndarray) -> np.ndarray:
    """3x3 box blur (edge pixels repeated)."""
    p = np.pad(a, 1, mode="edge")
    return sum(p[y:y + a.shape[0], x:x + a.shape[1]] for y in range(3) for x in range(3)) / 9.0


def _grow(a: np.ndarray, op) -> np.ndarray:
    """3x3 minimum (erode) or maximum (dilate) of a matte."""
    p = np.pad(a, 1, mode="edge")
    out = p[0:a.shape[0], 0:a.shape[1]]
    for y in range(3):
        for x in range(3):
            out = op(out, p[y:y + a.shape[0], x:x + a.shape[1]])
    return out


def key_frame(rgb: np.ndarray, key: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """One frame: (straight RGB float 0..255 with the spill removed along the edge, alpha float 0..1)."""
    f = rgb.astype(np.float32)
    a = np.clip((distance(f, key) - SIMILARITY) / BLEND, 0.0, 1.0)
    # matte choke of EDGE_CHOKE_PX: scaling and compression leave a thin light halo hugging the outline (overshoot with
    # no key colour in it, so neither the key nor the despill sees it); the matte is pulled in past it. The outline is
    # far thicker than that, so the character keeps its shape and its outline
    for _ in range(EDGE_CHOKE_PX):
        a = _grow(a, np.minimum)
    a = (a + _box3(a)) / 2.0                                              # one pixel of softening on the edge
    near = _box3(_box3((a < 0.999).astype(np.float32))) > 0               # the edge band (about two pixels)
    hi = [i for i in range(3) if key[i] >= 128]
    lo = [i for i in range(3) if key[i] < 128]
    if hi and lo:
        # Spill: how much of the key colour is mixed into an edge pixel (for magenta, how far red and blue stand above
        # green). A pixel that is part key is also part transparent: its alpha drops by that share, and the key's share
        # is taken out of its colour (un-mixed), so half white hair + half magenta becomes white at half opacity, and a
        # compression speck on the outline fades instead of staying as a grey dot. Only in the edge band.
        spill = np.clip(f[..., hi].min(-1) - f[..., lo].max(-1), 0, None) / 255.0
        a = np.where(near, np.minimum(a, 1.0 - spill), a)
        k = np.array(key, np.float32) / 255.0
        un = (f - (1.0 - a)[..., None] * k * 255.0) / np.maximum(a, 1e-3)[..., None]
        f = np.where(near[..., None], np.clip(un, 0, 255), f)
        # choke: an almost-transparent edge pixel is mostly compression noise (un-mixing would brighten it into a
        # speck), so the edge's alpha below CHOKE becomes fully transparent and the rest of the ramp is stretched
        a = np.where(near, np.clip((a - CHOKE) / (1.0 - CHOKE), 0.0, 1.0), a)
    f[a <= 0.0] = 0.0
    return f, a


def _probe(video: Path, ffprobe: str) -> tuple[int, int, float, float]:
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                        "-of", "default=nw=1", str(video)], capture_output=True, text=True, timeout=60)
    kv = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    num, den = (kv.get("r_frame_rate") or "30/1").split("/")
    return int(kv["width"]), int(kv["height"]), float(num) / float(den or 1), float(kv.get("duration") or 0)


def _encoder(ffmpeg: str, w: int, h: int, fps: float, wav: Path, out: Path, alpha: bool) -> subprocess.Popen:
    pix = "rgba" if alpha else "rgb24"
    codec = (["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-b:v", "0", "-crf", "28", "-c:a", "libopus"] if alpha
             else ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", "-b:a", "192k"])
    return subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{w}x{h}", "-r", f"{fps:.6f}", "-i", "-",
                             "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0", *codec, "-shortest", str(out)],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def cover(plate: Path, w: int, h: int) -> np.ndarray:
    """The approved set plate cover-fitted to the clip's size (centred)."""
    with Image.open(plate) as im:
        im = im.convert("RGB")
        k = max(w / im.width, h / im.height)
        im = im.resize((max(w, round(im.width * k)), max(h, round(im.height * k))), Image.LANCZOS)
        left, top = (im.width - w) // 2, (im.height - h) // 2
        return np.asarray(im.crop((left, top, left + w, top + h)), dtype=np.float32)


def key_clip(src: Path, wav: Path, colour: str, plate: Path | None, out_dir: Path, ffmpeg: str, ffprobe: str) -> dict:
    """Key one finished clip. Writes keyed.webm (alpha), over-set.mp4, over-grey.mp4 and check.png into out_dir and
    returns their paths and the check timepoints. `src` is only read."""
    key = hex_rgb(colour)
    w, h, fps, dur = _probe(src, ffprobe)
    n_est = max(1, round(dur * fps))
    picks = {min(n_est - 1, int(t * n_est)): t for t in CHECK_AT}
    bg_set = cover(plate, w, h) if plate else np.full((h, w, 3), GREY, np.float32)
    bg_grey = np.full((h, w, 3), GREY, np.float32)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"keyed": out_dir / "keyed.webm", "over_set": out_dir / "over-set.mp4", "over_grey": out_dir / "over-grey.mp4",
             "check": out_dir / "check.png"}
    dec = subprocess.Popen([ffmpeg, "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    encs = {"keyed": _encoder(ffmpeg, w, h, fps, wav, paths["keyed"], True),
            "over_set": _encoder(ffmpeg, w, h, fps, wav, paths["over_set"], False),
            "over_grey": _encoder(ffmpeg, w, h, fps, wav, paths["over_grey"], False)}
    shots, i, size = {}, 0, w * h * 3
    try:
        while True:
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            f, a = key_frame(np.frombuffer(buf, np.uint8).reshape(h, w, 3), key)
            a3 = a[..., None]
            rgba = np.concatenate([np.clip(f, 0, 255), a3 * 255.0], -1).round().astype(np.uint8)
            on_set = (f * a3 + bg_set * (1 - a3)).round().clip(0, 255).astype(np.uint8)
            on_grey = (f * a3 + bg_grey * (1 - a3)).round().clip(0, 255).astype(np.uint8)
            encs["keyed"].stdin.write(rgba.tobytes())
            encs["over_set"].stdin.write(on_set.tobytes())
            encs["over_grey"].stdin.write(on_grey.tobytes())
            if i in picks:
                shots[picks[i]] = (on_set, on_grey)
            i += 1
    finally:
        dec.stdout.close()
        dec.wait()
        errors = []
        for name, e in encs.items():
            e.stdin.close()
            err = e.stderr.read().decode(errors="replace")
            if e.wait() != 0:
                errors.append(f"{name}: {err.strip()[-200:]}")
    if errors:
        raise RuntimeError("keying: " + "; ".join(errors))
    if i == 0:
        raise RuntimeError("keying: the clip has no frames")
    # the check image: the three timepoints across, over the set (top) and over grey (bottom)
    times = sorted(shots)
    grid = Image.new("RGB", (w * len(times), h * 2), (0, 0, 0))
    for col, t in enumerate(times):
        grid.paste(Image.fromarray(shots[t][0]), (col * w, 0))
        grid.paste(Image.fromarray(shots[t][1]), (col * w, h))
    grid.save(paths["check"])
    return {"paths": paths, "frames": i, "check_at": [round(t * dur, 2) for t in times], "size": [w, h], "colour": colour}
