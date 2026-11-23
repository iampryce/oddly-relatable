"""Talking shots without a background: the cutout first frame (the character's own art on a flat key colour, no set),
the key colour chosen away from the character's approved art and recorded with the plan, the free keying step (no
fringe on a synthetic edge; the clip itself untouched), the previews over the set and over grey with the check image,
and the cost shown before Run unchanged. WaveSpeed is stubbed: no network, no cost."""
import subprocess
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from test_shot_compare import ShotBase
import test_talking_shots  # noqa: F401  (adds ShotBase.ready / ShotBase.row)

from oddstudio import secrets_store, wavespeed
from oddstudio import shot_compare as SC
from oddstudio import talking_key as K

IT = "wavespeed-infinitetalk-fast"
MAGENTA = (255, 0, 255)


def _ffprobe(ff: str) -> str:
    return ff.replace("ffmpeg", "ffprobe")


def decode_rgba(ff: str, video, w: int, h: int) -> np.ndarray:
    """Every frame of a VP9 WebM with alpha, as RGBA (libvpx decodes the alpha plane)."""
    r = subprocess.run([ff, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, h, w, 4)


class CutoutTest(ShotBase):
    def test_the_cutout_is_the_character_alone_on_the_key_colour(self):
        pose = self.media / "neutral.png"           # the approved pose ShotBase stores (transparent art)
        a, b = self.media / "a.png", self.media / "b.png"
        K.compose_cutout(pose, "#FF00FF", a)
        K.compose_cutout(pose, "#00FF00", b)
        ia, ib = np.asarray(Image.open(a).convert("RGB")), np.asarray(Image.open(b).convert("RGB"))
        self.assertEqual(ia.shape[:2], (900, 720))
        background = (ia != ib).any(-1)              # only the background changes with the key colour
        self.assertGreater(background.mean(), 0.2)
        self.assertTrue((ia[background] == MAGENTA).all(), "the background is exactly the key colour: no set, no gradient, no shadow")
        character = ~background
        self.assertGreater(character.mean(), 0.2, "the character fills the frame (head and shoulders)")
        self.assertFalse((K.distance(ia[character], MAGENTA) < K.SIMILARITY + K.BLEND).any(),
                         "no key colour (or anything the key would remove) inside the character")
        rows = np.nonzero(character.any(1))[0]
        self.assertLess(rows[0], 0.08 * 900, "the head near the top")

    def test_the_prepared_cutout_has_no_set_pixels(self):
        p = self.ready()
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as s:
            got = storage().get_to_file(s.get(Asset, p["frame_assets"]["cutout"]).storage_key, self.media / "got.png")
        K.compose_cutout(self.media / "neutral.png", p["key_colour"], self.media / "want.png")
        self.assertTrue(np.array_equal(np.asarray(Image.open(got)), np.asarray(Image.open(self.media / "want.png"))),
                        "the plan's cutout is the character's own art on the key colour, pixel for pixel: nothing from the set")

    def test_a_key_colour_in_the_art_is_not_used(self):
        art = self.media / "pink.png"
        im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle((10, 10, 60, 60), fill=(250, 10, 245, 255))     # nearly magenta, opaque
        ImageDraw.Draw(im).rectangle((70, 70, 90, 90), fill=(0, 255, 0, 40))         # transparent green does not count
        im.save(art)
        self.assertEqual(K.key_colour([art]), "#00FF00")
        self.assertEqual(K.key_colour([self.media / "neutral.png"]), "#FF00FF")
        purple = self.media / "purple.png"
        Image.new("RGBA", (40, 40), (110, 50, 160, 255)).save(purple)
        self.assertEqual(K.key_colour([purple]), "#FF00FF", "a purple hoodie is far enough from magenta")


class KeyEdgeTest(ShotBase):
    def test_no_fringe_on_a_thick_outline_and_white_hair(self):
        w, h, n = 320, 400, 12
        frames = self.media / "edge.mp4"
        enc = subprocess.Popen([self.ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "25", "-i", "-",
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(frames)], stdin=subprocess.PIPE)
        for i in range(n):
            im = Image.new("RGB", (w, h), MAGENTA)
            d = ImageDraw.Draw(im)
            d.ellipse((60 + i, 60, 260 + i, 260), fill=(250, 250, 250), outline=(10, 10, 10), width=12)   # white head, thick outline
            d.rectangle((110 + i, 270, 210 + i, 400), fill=(30, 90, 40), outline=(10, 10, 10), width=10)   # vest
            im = im.filter(ImageFilter.GaussianBlur(1.2))       # a soft, mixed edge like a model's output
            enc.stdin.write(im.tobytes())
        enc.stdin.close()
        self.assertEqual(enc.wait(), 0)
        wav = self.media / "edge.wav"
        subprocess.run([self.ff, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.48", str(wav)], check=True)
        before = frames.read_bytes()
        res = K.key_clip(frames, wav, "#FF00FF", None, self.media / "keyed", self.ff, _ffprobe(self.ff))
        self.assertEqual(frames.read_bytes(), before, "the clip itself is never changed")
        self.assertEqual(res["frames"], n)
        rgba = decode_rgba(self.ff, res["paths"]["keyed"], w, h).astype(int)
        self.assertEqual(rgba.shape[0], n)
        f = rgba[n // 2]
        a = f[..., 3]
        self.assertLess(a[5, 5], 10, "the key colour is gone")
        self.assertGreater(a[160, 160 + n // 2], 245, "the white head stays opaque")
        self.assertGreater(f[160, 160 + n // 2, :3].min(), 225, "and white")
        visible = a > 64
        spill = np.minimum(f[..., 0], f[..., 2]) - f[..., 1]
        self.assertLessEqual(int(spill[visible].max()), 24, "no magenta fringe on the outline or the white")
        self.assertTrue((a[visible] > 0).all())
        check = Image.open(res["paths"]["check"])
        self.assertEqual(check.size, (3 * w, 2 * h), "three timepoints, over the set and over grey")
        grey = np.asarray(Image.open(res["paths"]["check"]).convert("RGB"))[h + 5, 5]
        self.assertTrue((abs(grey.astype(int) - 128) <= 6).all(), "the grey background shows where the key was")


class KeyFlowTest(ShotBase):
    def setUp(self):
        super().setUp()
        secrets_store._cache = None
        self.calls = []

    def tearDown(self):
        wavespeed.set_test_run(None)
        super().tearDown()

    def test_the_request_and_cost_are_unchanged_and_the_clip_is_keyed_after(self):
        self.assertEqual(SC.estimate(IT, 6.22)["usd"], 0.105, "line 1 of Episode 14: still $0.105")
        p = self.ready()
        req = next(r for r in p["requests"] if r["model"] == IT)
        self.assertEqual((set(req["body"]), req["estimate"]["usd"]), ({"image", "audio", "prompt", "seed"}, 0.045))
        self.assertEqual(SC.attitude_words(req["body"]["prompt"]), [])

        def run(endpoint, body, out):
            self.calls.append(body)
            # a provider's output: the cutout frame's look, magenta around a green-and-white figure
            subprocess.run([self.ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xFF00FF:s=512x640:d=3.0:r=25",
                            "-vf", "drawbox=x=150:y=100:w=200:h=400:color=white@1:t=fill,drawbox=x=150:y=100:w=200:h=400:color=black@1:t=12",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
            return {"id": "t1", "status": "completed", "outputs": ["https://ws.example/o.mp4"]}
        wavespeed.set_test_run(run)
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["shot_generate"])[0][1], "succeeded")
        self.assertIn("first-frame-cutout.png", self.calls[0]["image"], "only the image changed: the plain-colour cutout")
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        res = self.row(p["id"])["results"][IT]
        with new_session() as s:
            clip_sha = s.get(Asset, res["asset_id"]).sha256
        ran = self.env.run_jobs(["shot_key"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        res = self.row(p["id"])["results"][IT]
        k = res["key"]
        self.assertEqual((k["status"], k["colour"], len(k["check_at"])), ("done", "#FF00FF", 3))
        self.assertTrue(all(k["urls"][x] for x in ("keyed", "over_set", "over_grey", "check")))
        self.assertEqual(self.sent, [], "keying is free: nothing sent to fal")
        self.assertEqual(len(self.calls), 1, "and nothing sent to WaveSpeed again")
        with new_session() as s:
            self.assertEqual(s.get(Asset, res["asset_id"]).sha256, clip_sha, "the clip is untouched")
            keyed = s.get(Asset, k["keyed_asset_id"])
            self.assertEqual(keyed.content_type, "video/webm")
            from oddstudio.storage import storage
            f = storage().get_to_file(keyed.storage_key, self.media / "k.webm")
        rgba = decode_rgba(self.ff, f, 720, 900)
        self.assertLess(int(rgba[0][5, 5, 3]), 10, "transparent where the key colour was (the padding too)")
        self.assertGreater(int(rgba[0][450, 360, 3]), 245, "the figure stays opaque")
        # the free keying can be run again, but not for a clip that is not a finished cutout
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/key", json={"model": IT}).status_code, 200)
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/key", json={"model": "wavespeed-kling-v1-avatar-standard"}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
