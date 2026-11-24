"""Pose cut-outs: background pockets enclosed by the outline (between an arm and the body) become transparent;
similar but different greys (hair, a moustache) and white eyes stay."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from oddstudio import engine

BG = (205, 205, 205)


def figure(bg):
    im = Image.new("RGB", (400, 600), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((130, 40, 270, 180), fill=(250, 220, 190), outline=(0, 0, 0), width=6)          # head
    d.ellipse((160, 80, 200, 120), fill=(255, 255, 255), outline=(0, 0, 0), width=4)          # white eye
    d.rectangle((175, 140, 225, 150), fill=(170, 170, 170))                                    # grey moustache
    d.rectangle((150, 180, 250, 400), fill=(30, 40, 90), outline=(0, 0, 0), width=6)          # body
    d.rectangle((110, 180, 150, 400), fill=bg, outline=(0, 0, 0), width=6)                    # enclosed pocket (arm gap)
    d.line((110, 180, 110, 400), fill=(0, 0, 0), width=8)                                      # arm
    d.line((185, 400, 185, 560), fill=(0, 0, 0), width=8)
    d.line((215, 400, 215, 560), fill=(0, 0, 0), width=8)
    return im


class CutoutGapsTest(unittest.TestCase):
    def cut(self, bg):
        f = Path(tempfile.mkdtemp()) / "p.png"
        figure(bg).save(f)
        engine.make_cutout(f)
        return Image.open(f).convert("RGBA")

    def test_enclosed_pocket_removed_moustache_kept(self):
        im = self.cut(BG)
        self.assertEqual(im.getpixel((130, 300))[3], 0)       # the arm gap is now transparent
        self.assertEqual(im.getpixel((5, 5))[3], 0)           # outside, as before
        self.assertGreater(im.getpixel((200, 145))[3], 200)   # grey moustache kept
        self.assertGreater(im.getpixel((180, 100))[3], 200)   # eye kept
        self.assertGreater(im.getpixel((200, 300))[3], 200)   # body kept

    def test_white_background_keeps_white_eyes(self):
        im = self.cut((255, 255, 255))
        self.assertGreater(im.getpixel((180, 100))[3], 200)


if __name__ == "__main__":
    unittest.main()
