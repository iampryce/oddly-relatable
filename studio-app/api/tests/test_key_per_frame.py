"""Keying frame by frame (2026-11-23). Measured on Episode 13's clip (plan bb029347a9): the model's magenta drifts during
the clip (about (250,34,230) at the start to (240,57,210) at the end), so one fixed key colour left a pink veil over
grey from about 3 s, and light pink slivers stayed in the enclosed gaps between the arm lines and the vest.

Pure numpy, no FFmpeg: synthetic frames whose key colour drifts like that, enclosed gaps, our own padding, a red mouth
with its dark interior, pink tongue and pink skin shading; and one real frame of that clip (the open red mouth and both
arm gaps). The clip-level parts (check frames, the recorded check, Key again) are in test_talking_key.py."""
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import helpers  # noqa: F401  (puts the API package on the path)
from oddstudio import talking_key as K

MAGENTA = (255, 0, 255)
START, END = (250, 34, 230), (240, 57, 210)
W, H = 360, 450
FIXTURE = Path(__file__).parent / "fixtures" / "keying" / "ep13-line1-3s.png"
TONGUE_FIXTURE = Path(__file__).parent / "fixtures" / "keying" / "ep13-line1-5s-tongue.png"   # 4.97 s: pink tongue, pink chin

SKIN = (250, 224, 200)
CHEEK = (240, 190, 190)          # pink skin shading
REAL_SKIN = (234, 207, 196)      # measured beside the mouth in the real clip
MOUTH_RED = (190, 23, 50)        # the real mouth's red interior
MOUTH_DARK = (57, 21, 18)        # its dark shading
TONGUE = (230, 120, 140)
VEST = (48, 78, 42)


def mix(a, b, t):
    return tuple(round(x * (1 - t) + y * t) for x, y in zip(a, b))


def frame(bg, pad=0) -> np.ndarray:
    """A head-and-shoulders frame on background `bg`: a skin head with a black outline, an open red mouth (dark interior,
    pink tongue), pink cheeks, a green vest between two arm lines, and in each gap between an arm line and the vest a
    light pink sliver (the key mixed with white) that touches no edge. `pad` columns of the exact plan key on each side,
    as finish() pads."""
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((90, 30, 270, 230), fill=SKIN, outline=(10, 10, 10), width=8)
    d.ellipse((120, 140, 150, 160), fill=CHEEK)
    d.ellipse((210, 140, 240, 160), fill=CHEEK)
    d.ellipse((155, 165, 205, 205), fill=MOUTH_DARK, outline=(10, 10, 10), width=3)
    d.ellipse((165, 182, 195, 200), fill=MOUTH_RED)
    d.ellipse((172, 190, 188, 199), fill=TONGUE)
    d.rectangle((150, 120, 160, 130), fill=REAL_SKIN)
    d.polygon([(130, 250), (230, 250), (250, 450), (110, 450)], fill=VEST, outline=(10, 10, 10))
    for x0 in (60, 280):                                     # the arm lines, each with an enclosed gap beside the vest
        d.rectangle((x0, 250, x0 + 20, 450), fill=(10, 10, 10))
    gap = mix(bg, (255, 255, 255), 0.20)                     # light pink: the key mixed with white (measured: 0.53-0.99 key)
    d.polygon([(82, 300), (128, 300), (118, 420), (82, 420)], fill=(10, 10, 10))
    d.polygon([(88, 310), (122, 310), (114, 410), (88, 410)], fill=gap)
    d.polygon([(232, 300), (278, 300), (278, 420), (242, 420)], fill=(10, 10, 10))
    d.polygon([(238, 310), (272, 310), (272, 410), (246, 410)], fill=gap)
    a = np.asarray(im).copy()
    if pad:
        a[:, :pad] = MAGENTA
        a[:, -pad:] = MAGENTA
    return a


def over_grey(f, a):
    return (f * a[..., None] + 128 * (1 - a[..., None])).round().clip(0, 255).astype(np.uint8)


def old_key(fr):
    """The keying before this change: one fixed colour (the plan's), no per-frame colour, no mix rule."""
    f = fr.astype(np.float32)
    return np.clip((K.distance(f, MAGENTA) - K.SIMILARITY) / K.BLEND, 0.0, 1.0)


class DriftTest(unittest.TestCase):
    def test_the_frames_background_colour_is_sampled_and_followed(self):
        prev = None
        for i in range(11):
            bg = mix(START, END, i / 10)
            fr = frame(bg, pad=4)
            got, share = K.sample_key(fr, MAGENTA, prev)
            prev = got
            self.assertLessEqual(max(abs(g - b) for g, b in zip(got, bg)), 2, (i, got, bg))
            self.assertGreater(share, 0.3, "most of the ring is background")
        self.assertEqual(K.picture_box(frame(START, pad=4), MAGENTA), (0, H, 4, W - 4), "our padding is not the model's picture")

    def test_the_background_stays_grey_while_the_key_drifts(self):
        prev = None
        for i in range(11):
            bg = mix(START, END, i / 10)
            fr = frame(bg, pad=4)
            prev, _ = K.sample_key(fr, MAGENTA, prev)
            f, a = K.key_frame(fr, MAGENTA, prev)
            g = over_grey(f, a)
            dev, pink = K.frame_check(g, fr, a, prev)
            self.assertLessEqual(dev, 1, f"frame {i}: the background over grey is grey")
            self.assertEqual(int(np.abs(g[5:-5, 5:40].astype(int) - 128).max()), 0, f"frame {i}: no veil at all")
            self.assertEqual(float(a[:, :4].max()), 0.0, "our padding is keyed too")
        # the same drift with one fixed colour (before): the veil the owner measured
        fr = frame(END)
        g_old = over_grey(fr.astype(np.float32), old_key(fr))
        self.assertGreater(int(np.abs(g_old[5:-5, 5:40].astype(int) - 128).max()), 6, "one fixed colour leaves a tint")

    def test_a_frame_with_no_background_on_its_border_keeps_the_previous_colour(self):
        fr = np.full((H, W, 3), VEST, np.uint8)
        self.assertEqual(K.sample_key(fr, MAGENTA, (241, 55, 211)), ((241, 55, 211), 0.0))
        self.assertEqual(K.sample_key(fr, MAGENTA)[0], MAGENTA)


class GapsAndFaceTest(unittest.TestCase):
    def setUp(self):
        self.fr = frame(END, pad=4)
        self.k, _ = K.sample_key(self.fr, MAGENTA)
        self.f, self.a = K.key_frame(self.fr, MAGENTA, self.k)

    def test_enclosed_light_pink_gaps_are_background(self):
        for (y0, y1, x0, x1) in ((320, 400, 92, 110), (320, 400, 250, 268)):
            self.assertLessEqual(float(self.a[y0:y1, x0:x1].max()), 0.01, "the sliver between the arm line and the vest")
        old = old_key(self.fr)
        self.assertGreater(float(old[320:400, 92:110].min()), 0.5, "before: the sliver stayed mostly opaque")
        _, pink = K.frame_check(over_grey(self.f, self.a), self.fr, self.a, self.k)
        self.assertLessEqual(pink, 10)

    def test_the_face_is_never_keyed(self):
        for name, colour in (("red mouth", MOUTH_RED), ("dark mouth", MOUTH_DARK), ("tongue", TONGUE),
                             ("skin", SKIN), ("pink cheek", CHEEK), ("real skin", REAL_SKIN), ("vest", VEST)):
            m = (self.fr == colour).all(-1)
            for _ in range(3):                    # its own pixels, 3 px in from its edge (the edge choke is the outline's)
                m = K._grow(m.astype(np.float32), np.minimum) > 0.5
            self.assertGreater(int(m.sum()), 10, name)
            self.assertEqual(float(self.a[m].min()), 1.0, f"{name} keeps full opacity")
            self.assertTrue(np.array_equal(self.f[m].round().astype(np.uint8), self.fr[m]), f"{name} keeps its colour")

    def test_the_mix_fit(self):
        k = np.array(END, np.float32)
        s, n, res = K.key_mix(np.array([k, 0.5 * k + 127.5, 0.3 * k, MOUTH_RED, MOUTH_DARK, REAL_SKIN], np.float32), END)
        self.assertAlmostEqual(float(s[0]), 1.0, places=2)
        self.assertAlmostEqual(float(s[1]), 0.5, places=2)
        self.assertGreater(float(n[1]), 250, "a key-and-white mix: the neutral is white")
        self.assertLess(float(res[:3].max()), 0.01, "the key, key + white and key + black fit")
        self.assertGreater(float(res[3]), K.PLANE_TOL * 2, "the red mouth does not")
        self.assertGreater(float(res[4]), K.PLANE_TOL, "nor its dark shading")
        self.assertLess(float(s[5]), K.MIX_START, "skin has hardly any key in it")


class RealFrameTest(unittest.TestCase):
    """A real frame of Episode 13's line 1 at 3 s (cropped: the open red mouth and both arm gaps), where the key had
    drifted to about (242, 49, 208)."""

    def setUp(self):
        self.fr = np.asarray(Image.open(FIXTURE).convert("RGB"))
        self.k, _ = K.sample_key(self.fr, MAGENTA)
        self.f, self.a = K.key_frame(self.fr, MAGENTA, self.k)

    def test_the_drifted_key_is_sampled(self):
        self.assertLessEqual(max(abs(g - b) for g, b in zip(self.k, (242, 49, 208))), 8, self.k)

    def test_the_open_red_mouth_is_untouched(self):
        mouth = self.a[175:225, 205:275]
        self.assertEqual(float(mouth.min()), 1.0, "the mouth, its red interior and the skin around it stay opaque")
        red = (self.fr[..., 0].astype(int) - self.fr[..., 2] > 60) & (self.fr[..., 0] > 120)
        self.assertGreater(int(red[175:225, 205:275].sum()), 100)
        self.assertEqual(float(self.a[175:225, 205:275][red[175:225, 205:275]].min()), 1.0)

    def test_the_arm_gaps_are_cleared_and_the_background_is_grey(self):
        g = over_grey(self.f, self.a)
        dev, pink = K.frame_check(g, self.fr, self.a, self.k)
        self.assertLessEqual(dev, 1)
        self.assertLessEqual(pink, 40, "the gaps' pink is gone (before: about 600 pink pixels in this frame)")
        old = over_grey(self.fr.astype(np.float32), old_key(self.fr))
        self.assertGreater(int(np.abs(old[20:200, 5:40].astype(int) - 128).max()), 6, "before: the veil")


class RealMouthShadingTest(unittest.TestCase):
    """The frame at 4.97 s: the mouth's pale pinks (tongue and lip highlights, the pink shading under the lip) look like
    the key mixed with white. A first version keyed them (alpha down to 0.34); they must stay opaque."""

    def test_the_tongue_and_the_pink_shading_stay(self):
        fr = np.asarray(Image.open(TONGUE_FIXTURE).convert("RGB"))
        k, _ = K.sample_key(fr, MAGENTA)
        f, a = K.key_frame(fr, MAGENTA, k)
        self.assertEqual(float(a[160:260, 190:300].min()), 1.0, "the whole mouth, tongue and chin shading")
        pinkish = (fr[..., 0].astype(int) > 190) & (fr[..., 1].astype(int) < 215) & (fr[..., 2].astype(int) > fr[..., 1].astype(int) + 8)
        m = pinkish[160:260, 190:300]
        self.assertGreater(int(m.sum()), 30, "there is pale pink in the mouth")
        self.assertTrue(np.array_equal(f[160:260, 190:300][m].round().astype(np.uint8), fr[160:260, 190:300][m]), "with its colour")
        _, pink = K.frame_check(over_grey(f, a), fr, a, k)
        self.assertLessEqual(pink, 40)


class CheckTest(unittest.TestCase):
    def rows(self, devs, pinks):
        return [{"t": i / 30, "bg_dev": d, "pink": p, "key": mix(START, END, i / max(1, len(devs) - 1))}
                for i, (d, p) in enumerate(zip(devs, pinks))]

    def test_a_clean_clip_is_keyed(self):
        q = K.quality(self.rows([0, 1, 0], [3, 8, 0]))
        self.assertEqual((q["ok"], q["reasons"], q["bg_dev_max"], q["pink_max"]), (True, [], 1, 8))
        self.assertEqual((q["key_first"], q["key_last"]), (list(START), list(END)))

    def test_over_the_limits_it_needs_attention_and_says_why(self):
        q = K.quality(self.rows([0, 27, 3], [5, 700, 10]))
        self.assertFalse(q["ok"])
        self.assertEqual(len(q["reasons"]), 2)
        self.assertIn("up to 27 levels off grey at 0.0 s", q["reasons"][0].replace("0.03", "0.0"))
        self.assertIn("700 pink pixels are left", q["reasons"][1])

    def test_the_key_colour_moves_only_for_art_that_keying_would_remove(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as t:
            pale, strong = Path(t) / "pale.png", Path(t) / "strong.png"
            Image.new("RGBA", (40, 40), (240, 180, 240, 255)).save(pale)      # a pale pink shirt: keying leaves it
            Image.new("RGBA", (40, 40), (250, 110, 250, 255)).save(strong)    # a strong pink: it would be keyed
            self.assertEqual(K.key_colour([pale]), "#FF00FF")
            self.assertEqual(K.key_colour([strong]), "#00FF00")
            fr = np.full((40, 40, 3), (240, 180, 240), np.uint8)
            self.assertEqual(float(K.key_frame(fr, MAGENTA, END)[1].min()), 1.0, "the pale pink is not keyed, even on a drifted key")


if __name__ == "__main__":
    unittest.main()
