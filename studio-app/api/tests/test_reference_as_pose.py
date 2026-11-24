"""The owner's reference drawing used unchanged as a pose (no generator redraw): cut out, sent to review, approved
only by the owner."""
import base64
import io
import unittest

from PIL import Image, ImageDraw

from helpers import Env


def master_png() -> str:
    im = Image.new("RGB", (400, 600), (205, 205, 205))
    d = ImageDraw.Draw(im)
    d.ellipse((140, 60, 260, 180), fill=(250, 220, 190), outline=(0, 0, 0), width=6)
    d.rectangle((170, 180, 230, 380), fill=(120, 30, 40), outline=(0, 0, 0), width=6)
    d.line((185, 380, 185, 540), fill=(0, 0, 0), width=8)
    d.line((215, 380, 215, 540), fill=(0, 0, 0), width=8)
    d.ellipse((165, 530, 205, 555), fill=(110, 60, 30), outline=(0, 0, 0), width=4)
    d.ellipse((205, 530, 245, 555), fill=(110, 60, 30), outline=(0, 0, 0), width=4)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class ReferenceAsPoseTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        r = self.c.post("/api/characters", json={"key": "ronald", "name": "Ronald", "visual_description": "spiky hair"})
        self.cid = r.json()["id"]
        r = self.c.post(f"/api/characters/{self.cid}/reference", json={"png_base64": master_png()})
        self.assertEqual(r.status_code, 201, r.text)
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        with new_session() as s:
            self.ref = s.query(CharacterAsset).filter_by(character_id=self.cid, kind="reference").one().id

    def tearDown(self):
        self.env.close()

    def poses(self):
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        with new_session() as s:
            return [(a.expression, a.status, a.feet) for a in s.query(CharacterAsset).filter_by(character_id=self.cid, kind="pose")]

    def test_reference_becomes_neutral_pose_in_review(self):
        r = self.c.post(f"/api/characters/{self.cid}/reference-as-pose", json={"asset_id": self.ref})
        self.assertEqual(r.status_code, 201, r.text)
        [(exp, status, feet)] = self.poses()
        self.assertEqual((exp, status), ("neutral", "review"))   # never approved by this step
        self.assertTrue(feet and feet["y"] > 500)                # cut out and measured like any pose
        again = self.c.post(f"/api/characters/{self.cid}/reference-as-pose", json={"asset_id": self.ref})
        self.assertEqual(again.status_code, 409)                  # one neutral at a time

    def test_only_this_characters_reference(self):
        self.assertEqual(self.c.post(f"/api/characters/{self.cid}/reference-as-pose", json={"asset_id": 999999}).status_code, 404)
        self.assertEqual(self.poses(), [])


if __name__ == "__main__":
    unittest.main()
