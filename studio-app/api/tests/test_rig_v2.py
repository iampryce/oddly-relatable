"""House style v2 rig and cut-out: the acting rig finds solid black eyes (not white discs), the thin-line mouth and its
bend; v1 art is still detected as v1; the grey background leaves no fringe around the ink after the cut-out.
Synthetic figures drawn here, so the test needs no generated art."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[3]
RIG = REPO / "production" / "animation" / "rig_extract.py"
GREY = (128, 128, 128, 255)


def v2_figure(path: Path, mouth: str = "frown", skin=(255, 255, 255)) -> Path:
    """A minimal v2 stick figure on mid-grey, drawn at 2x and reduced (anti-aliased edges, like generated art)."""
    k = 2
    im = Image.new("RGBA", (600 * k, 1200 * k), GREY)
    d = ImageDraw.Draw(im)
    s = lambda *v: [x * k for x in v]
    lw = 10 * k
    d.ellipse(s(180, 70, 420, 310), fill=skin + (255,), outline=(15, 15, 15), width=lw)       # head
    d.chord(s(185, 60, 415, 200), 180, 360, fill=(70, 45, 30), outline=(15, 15, 15), width=lw)  # flat hair cap
    for x in (255, 345):                                                                      # solid black eyes
        d.ellipse(s(x - 8, 166, x + 8, 198), fill=(15, 15, 15))
    d.line(s(232, 150, 272, 158), fill=(15, 15, 15), width=8 * k)                             # brows
    d.line(s(328, 158, 368, 150), fill=(15, 15, 15), width=8 * k)
    mid = 262 if mouth == "smile" else 238
    d.line(s(268, 250, 300, mid, 332, 250), fill=(15, 15, 15), width=5 * k, joint="curve")   # thin-line mouth
    d.line(s(300, 310, 300, 332), fill=(15, 15, 15), width=lw)                                # neck
    d.polygon(s(238, 330, 362, 330, 346, 640, 254, 640), fill=skin + (255,), outline=(15, 15, 15), width=lw)  # tapered torso
    for sx, hx in ((232, 196), (368, 404)):                                                   # arms + blob hands
        d.line(s(sx, 345, hx, 640), fill=(15, 15, 15), width=lw)
        d.ellipse(s(hx - 22, 630, hx + 22, 680), fill=(15, 15, 15))
    for lx, fx in ((276, 256), (324, 344)):                                                   # legs + blob feet
        d.line(s(lx, 640, lx, 1100), fill=(15, 15, 15), width=lw)
        d.ellipse(s(fx - 42, 1092, fx + 42, 1120), fill=(15, 15, 15))
    im.resize((600, 1200), Image.LANCZOS).save(path)
    return path


class RigV2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oddstudio-rig-"))
        sys.path.insert(0, str(REPO / "production" / "animation"))
        sys.path.insert(0, str(REPO / "studio-app" / "api"))

    def cut(self, name, **kw):
        from oddstudio import engine
        f = v2_figure(self.tmp / f"{name}.png", **kw)
        self.assertTrue(engine.make_cutout(f))
        return f

    def test_v2_rig_finds_black_eyes_mouth_and_bend(self):
        neutral = self.cut("neutral", mouth="frown")
        r = subprocess.run([sys.executable, str(RIG), str(neutral), str(self.tmp / "rig")], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        rig = json.loads((self.tmp / "rig" / "rig.json").read_text())
        self.assertEqual(rig["style"], "v2")
        f = rig["faces"]["neutral"]
        self.assertTrue(f["static_eyes"])
        self.assertTrue(all(abs(e["cx"] - x) < 6 for e, x in zip(f["eyes"], (255, 345))), f["eyes"])   # the two drawn eyes
        self.assertTrue(all(abs(e["cy"] - 182) < 6 for e in f["eyes"]))
        self.assertTrue(abs(f["mouth"]["cx"] - 300) < 8 and abs(f["mouth"]["cy"] - 246) < 10, f["mouth"])
        self.assertLess(f["mouth"]["curve"], -0.05, "a frown bends the other way from a smile")
        self.assertGreater(f["skin"][0], 240)
        self.assertTrue((self.tmp / "rig" / "head-neutral.png").exists())
        smile = self.cut("smile", mouth="smile")
        r = subprocess.run([sys.executable, str(RIG), str(smile), str(self.tmp / "rig"), "--head-only", "happy"],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        rig = json.loads((self.tmp / "rig" / "rig.json").read_text())
        self.assertGreater(rig["faces"]["happy"]["mouth"]["curve"], 0.05)

    def test_skin_tone_heads_are_v2_too(self):
        import numpy as np
        import rig_extract
        f = self.cut("tone", skin=(150, 105, 80))
        self.assertEqual(rig_extract.detect_style(np.array(Image.open(f).convert("RGBA"))), "v2")

    def test_v1_art_is_still_v1(self):
        import numpy as np
        import rig_extract
        art = REPO / "bible/concepts/lookdev-richenv/extracted/canonical-character-01_01-neutral.png"
        self.assertEqual(rig_extract.detect_style(np.array(Image.open(art).convert("RGBA"))), "v1")

    def test_grey_background_leaves_no_fringe(self):
        import numpy as np
        f = self.cut("fringe")
        a = np.array(Image.open(f).convert("RGBA")).astype(int)
        clear = a[:, :, 3] <= 16
        from PIL import ImageFilter
        near = np.array(Image.fromarray((clear * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
        edge = near & ~clear
        greyish = edge & (np.abs(a[:, :, :3] - 128).max(2) <= 36)
        self.assertEqual(int(greyish.sum()), 0, "no background-grey pixels left on the figure's edge")
        self.assertGreater(int(edge.sum()), 100)


if __name__ == "__main__":
    unittest.main()
