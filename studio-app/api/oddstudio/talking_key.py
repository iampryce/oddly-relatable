"""Talking shots without a background (owner request 2026-11-23): the character alone, to be placed over the episode's
approved set at assembly.

1. The first frame: the character's own approved pose (its transparent art, never the set plate), cut to the same
   head and shoulders as the "head" framing (720x900, head near the top, ending in the upper vest, no hands), on a flat
   solid key colour with no gradient, no shadow and no set. The colour is #FF00FF unless the character's approved art
   comes close to it (then the next candidate); the colour used is recorded with the plan. The art's edge is made hard
   (alpha at 50%) so no pixel of the first frame is a mix of the art and the key colour.
2. After a clip finishes, a free local keying step, frame by frame (2026-11-23: the model's magenta drifts during a
   clip, about (250,34,230) at the start to (240,57,210) at the end, so one fixed colour left a pink veil):
   - the frame's own background colour is sampled from its border (the median of the border pixels near the key colour;
     the character, which touches the bottom edge, is left out by that distance);
   - alpha comes from the distance to that sampled colour with a soft ramp (FFmpeg colorkey's maths);
   - a pixel that is the key colour mixed with a neutral (black outline, white, grey: the light pink in the enclosed
     gaps between the arm lines and the vest, or between the head and the shoulders) is background by its own colour,
     wherever it is, not only when it touches the edge: it is fitted as "share s of the key + a neutral" and turns
     transparent as s grows, its colour un-mixed to that neutral. Colours that are not such a mix (the red mouth, skin and
     its pink shading, the green vest) do not fit and are never keyed by this rule;
   - the edge is softened by one pixel, and the key's spill is removed in a thin band along the edge.
   FFmpeg decodes and encodes; the keyed frames are computed here, so the result is the same on every machine.
   Outputs: a keyed copy with transparency (VP9 WebM with alpha, our line audio in Opus), previews over the episode's
   approved set and over mid-grey (H.264), and one check image (one frame per second x the 2 backgrounds).
3. A built-in check after keying, over flat grey: the background's largest deviation from grey (99th percentile per
   frame, the worst frame of the clip) and the pink pixels left (key-colour mixes still visible). Above either limit the
   key is marked "needs attention" with the reason instead of "Keyed". The clip it was made from is never changed.
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
CHECK_EVERY_S = 1.0  # one check frame per second of the clip
RING_PX = 6          # the border ring (of the model's own picture) the frame's background colour is sampled from
SAMPLE_NEAR = 0.35   # border pixels this close to the plan's key colour are background candidates
SAMPLE_MIN = 0.02    # at least this share of the ring must be background, else the previous frame's colour is kept
PLANE_TOL = 0.07     # a pixel this close to "key colour mixed with a neutral" (residual / brightness) is such a mix
# Shares measured on Episode 13's clip: the enclosed gaps' pink is 0.53 to 0.99 key (median 0.9); the mouth's own pale
# pinks (lips, tongue highlights, which look exactly like key + white) are 0.38 at most. Only strong mixes are keyed by
# this rule; weaker ones at the character's outline are cleaned by the edge band's spill removal below.
MIX_START = 0.40     # a mix with more key than this starts to turn transparent
MIX_FULL = 0.65      # and from this share of key it is fully background
LIGHT = 170          # a mix with a light neutral (key + white: the pale pink the model paints in the enclosed gaps) is
LIGHT_START, LIGHT_FULL = 0.50, 0.70   # with a light neutral (key + white): the mouth's pale pinks reach 0.38; the
                                       # character's white (hair, shirt) is inside its
                                       # black outline, so the key never mixes with it directly
QA_BG_DEV = 6        # check: over grey, the background (99th percentile per frame) may be this far from grey at most
QA_PINK = 150        # check: at most this many pink leftover pixels in any frame
QA_PINK_SHARE = 0.40  # a visible pixel that is a key mix with this much key (what keying treats as background) is a
                      # pink leftover; less (pink cheeks, lips, skin) is the character's own colour


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def distance(rgb: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    """Normalised RGB distance to the key colour, 0 (the key itself) to 1."""
    k = np.array(key, dtype=np.float32)
    return np.sqrt(((rgb.astype(np.float32) - k) ** 2).sum(-1)) / (255.0 * np.sqrt(3.0))


def key_mix(rgb: np.ndarray, key) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each pixel fitted as "share s of the key colour + a neutral grey level": p = s * key + h * (1, 1, 1) (least
    squares). Returns (s, the neutral it is mixed with (0..255), the fit's residual relative to the pixel's brightness).
    A pixel of the key mixed with black, white or grey fits closely (small residual); a colour that is not such a mix
    (the red mouth and its dark shading, skin, the green vest) does not. The residual is relative because a dark pixel
    is close to everything in absolute terms: a dark red is not a dark magenta."""
    p = rgb.astype(np.float32)
    k = np.asarray(key, np.float32)
    kk, k1 = float(k @ k), float(k.sum())
    det = kk * 3.0 - k1 * k1
    b0, b1 = p @ k, p.sum(-1)
    sh = (3.0 * b0 - k1 * b1) / det
    hh = (kk * b1 - k1 * b0) / det
    res = np.sqrt(((p - sh[..., None] * k - hh[..., None]) ** 2).sum(-1)) / np.maximum(np.sqrt((p ** 2).sum(-1)), 0.15 * 255.0 * np.sqrt(3.0))
    neutral = np.clip(hh / np.maximum(1.0 - sh, 1e-3), 0.0, 255.0)
    return sh, neutral, res


def art_near(path: Path, key: tuple[int, int, int], margin: float = ART_MARGIN) -> bool:
    """Whether any opaque pixel of the approved art is close enough to the key colour to be keyed out with it: by
    distance, or because it is the key colour mixed with a neutral (a pale pink shirt with magenta, say)."""
    with Image.open(path) as im:
        a = np.asarray(im.convert("RGBA"))
    opaque = a[:, :, 3] >= 128
    if not opaque.any():
        return False
    px = a[:, :, :3][opaque]
    if (distance(px, key) < margin).any():
        return True
    sh, _, res = key_mix(px, key)
    return bool(((res < PLANE_TOL) & (sh > MIX_START)).any())


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


PAD_EXACT = 0.03     # our own padding (finish() pads to the frame size with the exact key colour)
RING_INSET = 2       # the ring starts this far inside the model's picture (codecs smear the outermost pixels)


def picture_box(rgb: np.ndarray, key) -> tuple[int, int, int, int]:
    """The model's own picture inside the frame: (top, bottom, left, right), without the bands of exactly the key colour
    that finish() pads with when the model's picture is narrower or shorter than the frame."""
    pad = distance(rgb, key) < PAD_EXACT
    h, w = pad.shape
    cols, rows = pad.mean(0) > 0.97, pad.mean(1) > 0.97
    left = next((i for i in range(w // 4) if not cols[i]), 0)
    right = next((w - i for i in range(w // 4) if not cols[w - 1 - i]), w)
    top = next((i for i in range(h // 4) if not rows[i]), 0)
    bottom = next((h - i for i in range(h // 4) if not rows[h - 1 - i]), h)
    return top, bottom, left, right


def ring(rgb: np.ndarray, key) -> np.ndarray:
    """The border ring of the model's picture (RING_PX wide, RING_INSET inside it), as a mask over the frame."""
    t, b, l, r = picture_box(rgb, key)
    t, b, l, r = t + RING_INSET, b - RING_INSET, l + RING_INSET, r - RING_INSET
    m = np.zeros(rgb.shape[:2], bool)
    if b - t > 2 * RING_PX and r - l > 2 * RING_PX:
        m[t:t + RING_PX, l:r] = m[b - RING_PX:b, l:r] = True
        m[t:b, l:l + RING_PX] = m[t:b, r - RING_PX:r] = True
    return m


def sample_key(rgb: np.ndarray, key, previous=None) -> tuple[tuple[float, float, float], float]:
    """The frame's own background colour: the median of the border pixels of the model's picture that are near the
    plan's key colour (our padding is skipped; the character, which touches the bottom edge, is far from the key and
    left out). Returns (colour, share of the ring it came from); with too little background on the ring, the previous
    frame's colour (or the plan's) is kept."""
    px = rgb[ring(rgb, key)]
    if not len(px):
        return tuple(previous if previous is not None else key), 0.0
    near = distance(px, key) < SAMPLE_NEAR
    share = float(near.mean())
    if share < SAMPLE_MIN:
        return tuple(previous if previous is not None else key), share
    return tuple(float(v) for v in np.median(px[near].astype(np.float32), axis=0)), share


def key_frame(rgb: np.ndarray, key: tuple[int, int, int], sampled=None) -> tuple[np.ndarray, np.ndarray]:
    """One frame: (straight RGB float 0..255 with the key un-mixed, alpha float 0..1). `key` is the plan's key colour;
    `sampled` the frame's own background colour (sample_key), which the frame is keyed against when given."""
    f = rgb.astype(np.float32)
    k_used = tuple(sampled) if sampled is not None else tuple(float(v) for v in key)
    # alpha from the distance to the plan's key colour (our padding, and background that kept the original colour) and
    # to the frame's own background colour, whichever is closer. The frame's colour counts only for pixels that are a
    # key mix: a drifted, pinker key comes close to a pink tongue in plain distance, but the tongue is not a key mix
    sh, neutral, res = key_mix(f, k_used)
    d = np.minimum(distance(f, key), np.where(res < PLANE_TOL, distance(f, k_used), 1.0))
    a = np.clip((d - SIMILARITY) / BLEND, 0.0, 1.0)
    # key colour mixed with a neutral, anywhere in the frame (the enclosed gaps too): background by its key share,
    # its colour un-mixed to the neutral it was mixed with
    light = neutral >= LIGHT
    start = np.where(light, LIGHT_START, MIX_START)
    full = np.where(light, LIGHT_FULL, MIX_FULL)
    mixed = (res < PLANE_TOL) & (sh > start)
    a = np.where(mixed, np.minimum(a, np.clip((full - sh) / (full - start), 0.0, 1.0)), a)
    f = np.where(mixed[..., None], neutral[..., None], f)
    # matte choke of EDGE_CHOKE_PX: scaling and compression leave a thin light halo hugging the outline (overshoot with
    # no key colour in it, so neither the key nor the despill sees it); the matte is pulled in past it. The outline is
    # far thicker than that, so the character keeps its shape and its outline
    for _ in range(EDGE_CHOKE_PX):
        a = _grow(a, np.minimum)
    a = (a + _box3(a)) / 2.0                                              # one pixel of softening on the edge
    near = _box3(_box3((a < 0.999).astype(np.float32))) > 0               # the edge band (about two pixels)
    hi = [i for i in range(3) if key[i] >= 128]
    lo = [i for i in range(3) if key[i] < 128]
    near = near & ~mixed                                                  # mixes are un-mixed already
    if hi and lo:
        # Spill: how much of the key colour is mixed into an edge pixel (for magenta, how far red and blue stand above
        # green). A pixel that is part key is also part transparent: its alpha drops by that share, and the key's share
        # is taken out of its colour (un-mixed), so half white hair + half magenta becomes white at half opacity, and a
        # compression speck on the outline fades instead of staying as a grey dot. Only in the edge band.
        spill = np.clip(f[..., hi].min(-1) - f[..., lo].max(-1), 0, None) / 255.0
        a = np.where(near, np.minimum(a, 1.0 - spill), a)
        k = np.array(k_used, np.float32) / 255.0
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


def frame_check(on_grey: np.ndarray, src: np.ndarray, a: np.ndarray, k_used) -> tuple[float, int]:
    """The built-in check of one keyed frame over flat grey: (the background's deviation from grey, 99th percentile,
    over the pixels that are clearly background in the source; the number of pink leftover pixels: visible pixels that
    are still a key-colour mix)."""
    bg = distance(src, k_used) < 0.15
    dev = float(np.percentile(np.abs(on_grey[bg].astype(np.int16) - 128).max(-1), 99)) if bg.any() else 0.0
    sh, _, res = key_mix(on_grey, k_used)
    pink = int(((res < PLANE_TOL) & (sh >= QA_PINK_SHARE) & (a > 0.02)).sum())
    return dev, pink


def quality(rows: list[dict]) -> dict:
    """The clip's check from its frames: ok, or "needs attention" with the reasons."""
    worst_bg = max(rows, key=lambda r: r["bg_dev"])
    worst_pink = max(rows, key=lambda r: r["pink"])
    reasons = []
    if worst_bg["bg_dev"] > QA_BG_DEV:
        reasons.append(f"over grey the background is up to {worst_bg['bg_dev']:.0f} levels off grey at {worst_bg['t']:.1f} s "
                       f"(limit {QA_BG_DEV}): a tint of the key colour is left")
    if worst_pink["pink"] > QA_PINK:
        reasons.append(f"{worst_pink['pink']} pink pixels are left at {worst_pink['t']:.1f} s (limit {QA_PINK}): look at the gaps "
                       "between the arms and the body in the check frames")
    first, last = rows[0]["key"], rows[-1]["key"]
    return {"ok": not reasons, "reasons": reasons,
            "bg_dev_max": round(worst_bg["bg_dev"], 1), "bg_dev_at": worst_bg["t"],
            "pink_max": worst_pink["pink"], "pink_at": worst_pink["t"],
            "key_first": [round(v) for v in first], "key_last": [round(v) for v in last],
            "limits": {"bg_dev": QA_BG_DEV, "pink": QA_PINK}}


def key_clip(src: Path, wav: Path, colour: str, plate: Path | None, out_dir: Path, ffmpeg: str, ffprobe: str) -> dict:
    """Key one finished clip, frame by frame. Writes keyed.webm (alpha), over-set.mp4, over-grey.mp4 and check.png into
    out_dir and returns their paths, the check timepoints and the clip's check (quality). `src` is only read."""
    key = hex_rgb(colour)
    w, h, fps, dur = _probe(src, ffprobe)
    n_est = max(1, round(dur * fps))
    picks = {}
    t = 0.0
    while True:                                   # one check frame per second of the clip (always at least the first)
        i_t = min(n_est - 1, int(round(t * fps)))
        if i_t in picks or (t > 0 and t >= dur):
            break
        picks[i_t] = round(t, 2)
        t += CHECK_EVERY_S
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
    rows, sampled = [], None
    try:
        while True:
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            sampled, _ = sample_key(frame, key, sampled)
            f, a = key_frame(frame, key, sampled)
            a3 = a[..., None]
            rgba = np.concatenate([np.clip(f, 0, 255), a3 * 255.0], -1).round().astype(np.uint8)
            on_set = (f * a3 + bg_set * (1 - a3)).round().clip(0, 255).astype(np.uint8)
            on_grey = (f * a3 + bg_grey * (1 - a3)).round().clip(0, 255).astype(np.uint8)
            encs["keyed"].stdin.write(rgba.tobytes())
            encs["over_set"].stdin.write(on_set.tobytes())
            encs["over_grey"].stdin.write(on_grey.tobytes())
            dev, pink = frame_check(on_grey, frame, a, sampled)
            rows.append({"t": round(i / fps, 2), "bg_dev": dev, "pink": pink, "key": sampled})
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
    # the check image: one frame per second across (half size), over the set (top) and over grey (bottom)
    times = sorted(shots)
    tw, th = max(1, w // 2), max(1, h // 2)
    grid = Image.new("RGB", (tw * len(times), th * 2), (0, 0, 0))
    for col, t in enumerate(times):
        grid.paste(Image.fromarray(shots[t][0]).resize((tw, th), Image.LANCZOS), (col * tw, 0))
        grid.paste(Image.fromarray(shots[t][1]).resize((tw, th), Image.LANCZOS), (col * tw, th))
    grid.save(paths["check"])
    return {"paths": paths, "frames": i, "check_at": times, "size": [w, h], "colour": colour, "quality": quality(rows)}
