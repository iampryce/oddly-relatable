"""feat/3d-rig PR 1: neutral head angles (three-quarter, side, back) drawn from the approved front pose, cost shown and
capped, started and approved only by the owner, and the mock used until an angle is approved."""
import tempfile
import unittest
from pathlib import Path

from helpers import Env, fake_pose_image

from oddstudio import head_angles as HA
from oddstudio import providers


class HeadAnglesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.calls = []

        def image(prompt, out_file, reference):
            self.calls.append((prompt, reference))
            return fake_pose_image(prompt, out_file, reference)
        providers.set_test_image(image)
        self.c.put("/api/settings/image", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})
        self.cid = self.c.post("/api/characters", json={"key": "mortimer", "name": "Uncle Mortimer",
                                                        "visual_description": "an old man with white hair and a green vest"}).json()["id"]

    def tearDown(self):
        providers.set_test_image(None)
        self.env.close()

    def approve_neutral(self):
        from PIL import Image
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        from oddstudio.storage import storage
        f = Path(tempfile.mkdtemp()) / "neutral.png"
        Image.new("RGB", (60, 140), (200, 180, 160)).save(f)
        storage().put_file("characters/mortimer/poses/neutral.png", f, "image/png")
        with new_session() as db:
            a = CharacterAsset(character_id=self.cid, kind="pose", expression="neutral", storage_key="characters/mortimer/poses/neutral.png",
                               status="approved", width=60, height=140)
            db.add(a)
            db.commit()
            return a.id

    def test_the_front_pose_is_required_and_the_cap_refuses(self):
        v = self.c.get(f"/api/characters/{self.cid}/head-angles").json()
        self.assertFalse(v["can_generate"])
        self.assertIn("approve the neutral pose first", v["reason"])
        self.assertEqual([r["status"] for r in v["angles"]], ["mock", "mock", "mock"], "nothing approved: the mock is used")
        r = self.c.post(f"/api/characters/{self.cid}/head-angles/generate", json={"angles": ["side"], "max_usd": 1})
        self.assertEqual(r.status_code, 409)
        self.approve_neutral()
        v = self.c.get(f"/api/characters/{self.cid}/head-angles").json()
        self.assertTrue(v["can_generate"])
        self.assertEqual(v["cost_missing"]["images"], 3)
        r = self.c.post(f"/api/characters/{self.cid}/head-angles/generate", json={"angles": ["three-quarter", "side", "back"], "max_usd": 0.3})
        self.assertEqual(r.status_code, 422, "3 images could cost $0.60: over a $0.30 cap")
        self.assertIn("cap", r.json()["detail"])
        r = self.c.post(f"/api/characters/{self.cid}/head-angles/generate", json={"angles": ["front"], "max_usd": 1})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.calls, [], "nothing was drawn")

    def test_drawn_from_the_front_pose_reviewed_and_approved_one_per_angle(self):
        self.approve_neutral()
        r = self.c.post(f"/api/characters/{self.cid}/head-angles/generate", json={"angles": ["three-quarter", "side", "back"], "max_usd": 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.post(f"/api/characters/{self.cid}/head-angles/generate",
                                     json={"angles": ["side"], "max_usd": 1}).status_code, 409, "one request at a time")
        ran = self.env.run_jobs(["head_angles"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(len(self.calls), 3)
        for (prompt, ref), angle in zip(self.calls, HA.ANGLES):
            self.assertIn("Draw ONLY this character's HEAD", prompt)
            self.assertIn(HA.VIEW[angle], prompt)
            self.assertEqual(Path(ref).name, "neutral.png", "the approved front pose is the reference")
        v = self.c.get(f"/api/characters/{self.cid}/head-angles").json()
        self.assertEqual([r["status"] for r in v["angles"]], ["review", "review", "review"], "nothing approved by itself")
        side = v["angles"][1]["review"][0]["id"]
        v = self.c.post(f"/api/head-angles/{side}/decision", json={"decision": "approve"}).json()
        self.assertEqual([r["status"] for r in v["angles"]], ["review", "approved", "review"])
        # a second side drawing, approved, retires the first
        self.c.post(f"/api/characters/{self.cid}/head-angles/generate", json={"angles": ["side"], "max_usd": 1})
        self.env.run_jobs(["head_angles"])
        v = self.c.get(f"/api/characters/{self.cid}/head-angles").json()
        new = v["angles"][1]["review"][0]["id"]
        self.c.post(f"/api/head-angles/{new}/decision", json={"decision": "approve"})
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset
        with new_session() as db:
            self.assertEqual(db.get(CharacterAsset, side).status, "rejected")
            self.assertEqual({k: a.id for k, a in HA.approved_angles(db, db.get(Character, self.cid)).items()}, {"side": new})
            # head angles never change the character's expressions or art status
            self.assertEqual(db.get(Character, self.cid).expressions, {})
        back = v["angles"][2]["review"][0]["id"]
        v = self.c.post(f"/api/head-angles/{back}/decision", json={"decision": "reject"}).json()
        self.assertEqual(v["angles"][2]["status"], "mock", "the back drawing rejected: the mock stays in use")


if __name__ == "__main__":
    unittest.main()
