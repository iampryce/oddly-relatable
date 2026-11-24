"""Face expressions drawn by code on the approved neutral: only the face changes (every pixel outside the face hull
is the approved drawing), no provider is called, poses go to review, nothing is approved."""
import base64
import io
import unittest

import numpy as np
from PIL import Image, ImageDraw

from helpers import Env

from oddstudio import face_expressions as FE
from oddstudio import providers

SKIN = (253, 219, 180)


def neutral_png(lips=False) -> Image.Image:
    im = Image.new("RGBA", (600, 900), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((150, 60, 450, 360), fill=SKIN, outline=(0, 0, 0), width=8)                # head
    d.pieslice((140, 40, 460, 200), 180, 360, fill=(240, 200, 90), outline=(0, 0, 0), width=8)   # hair (fringe above the brows)
    for x0 in (200, 310):                                                                   # eyes and pupils
        d.ellipse((x0, 170, x0 + 90, 280), fill=(255, 255, 255), outline=(0, 0, 0), width=6)
        d.ellipse((x0 + 35, 215, x0 + 55, 235), fill=(0, 0, 0))
    d.line((205, 150, 285, 150), fill=(0, 0, 0), width=10)                                 # brows
    d.line((315, 150, 395, 150), fill=(0, 0, 0), width=10)
    d.line((270, 310, 330, 310), fill=(190, 25, 35) if lips else (0, 0, 0), width=8)      # mouth
    d.rectangle((220, 360, 380, 640), fill=(30, 40, 90), outline=(0, 0, 0), width=8)      # body
    d.line((260, 640, 260, 860), fill=(0, 0, 0), width=8)
    d.line((340, 640, 340, 860), fill=(0, 0, 0), width=8)
    return im


class FaceRenderTest(unittest.TestCase):
    def test_only_the_face_changes(self):
        im = neutral_png()
        a0 = np.array(im)
        f = FE.analyse(im)
        _, hull = FE._face(a0.copy(), f)
        allowed = FE._dilate(hull, 6)
        for e in FE.EXPRESSIONS:
            out = np.array(FE.render(im, e))
            changed = np.any(out != a0, axis=2)
            self.assertTrue(changed.any(), e)
            self.assertFalse((changed & ~allowed).any(), f"{e}: pixels outside the face changed")
            self.assertTrue(np.array_equal(out[360:, :], a0[360:, :]), f"{e}: the body changed")

    def test_lipstick_mouth_lines_stay_red(self):
        im = neutral_png(lips=True)
        out = np.array(FE.render(im, "deadpan")).astype(int)
        red = (out[..., 0] > 150) & (out[..., 1] < 80) & (out[..., 3] > 200)
        self.assertGreater(int(red[290:340].sum()), 50)

    def test_no_face_found_is_a_clear_error(self):
        with self.assertRaises(FE.FaceNotFound):
            FE.analyse(Image.new("RGBA", (300, 500), (0, 0, 0, 0)))


class FaceExpressionsJobTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_image(lambda *a: (_ for _ in ()).throw(AssertionError("no image provider may be called")))
        cid = self.c.post("/api/characters", json={"key": "ronald", "name": "Ronald"}).json()["id"]
        buf = io.BytesIO()
        neutral_png().save(buf, "PNG")
        self.c.post(f"/api/characters/{cid}/reference", json={"png_base64": base64.b64encode(buf.getvalue()).decode()})
        self.cid = cid

    def tearDown(self):
        providers.set_test_image(None)
        self.env.close()

    def assets(self):
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        with new_session() as s:
            return [(a.id, a.kind, a.expression, a.status) for a in s.query(CharacterAsset).filter_by(character_id=self.cid)]

    def test_needs_an_approved_neutral_then_draws_in_review(self):
        r = self.c.post(f"/api/characters/{self.cid}/face-expressions", json={"expressions": ["smug"]})
        self.assertEqual(r.status_code, 409)
        ref = next(a for a in self.assets() if a[1] == "reference")[0]
        self.c.post(f"/api/characters/{self.cid}/reference-as-pose", json={"asset_id": ref})
        pose = next(a for a in self.assets() if a[1] == "pose")[0]
        self.c.post(f"/api/character-assets/{pose}/decision", json={"decision": "approve"})
        self.assertEqual(self.c.post(f"/api/characters/{self.cid}/face-expressions", json={"expressions": ["crying"]}).status_code, 422)
        r = self.c.post(f"/api/characters/{self.cid}/face-expressions", json={"expressions": ["smug", "shocked"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["face_expressions"])
        self.assertEqual([x[1] for x in ran], ["succeeded"], ran)
        poses = sorted((e, s) for _, k, e, s in self.assets() if k == "pose")
        self.assertEqual(poses, [("neutral", "approved"), ("shocked", "review"), ("smug", "review")])


if __name__ == "__main__":
    unittest.main()
