"""Rig check at pose approval (render job 267, attempt 2, 2026-11-21): a pose whose hands are hidden (in a hoodie
pocket, under sleeves) used to fail an hour into the render with "cannot convert float NaN to integer". Now the rig
extraction says clearly what could not be found and what to change; approving a pose runs that check, the pose card
shows the result, and production refuses to start while a character's body pose cannot be rigged. A normal pose
still passes. Synthetic figures (test_rig_v2.v2_figure), so no generated art is needed."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from helpers import Env
from test_rig_v2 import GREY, RIG, v2_figure

from oddstudio import engine


def hidden_hands_figure(path: Path) -> Path:
    """The same v2 figure, but the arms end inside the torso (hands in a pocket): no hand blobs beside the body."""
    v2_figure(path)
    im = Image.open(path).convert("RGBA")
    d = ImageDraw.Draw(im)
    d.rectangle((150, 336, 236, 700), fill=GREY)    # erase the left arm and hand
    d.rectangle((364, 336, 450, 700), fill=GREY)    # and the right
    for sx, ex in ((238, 262), (362, 338)):          # arms bent in to the middle of the torso, hands out of sight
        d.line((sx, 345, ex, 520), fill=(15, 15, 15), width=10)
    im.save(path)
    return path


def run_rig(pose: Path, out: Path):
    return subprocess.run([sys.executable, str(RIG), str(pose), str(out)], capture_output=True, text=True, timeout=300)


class RigExtractErrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oddstudio-rigcheck-"))

    def test_hidden_hands_give_a_clear_error_never_nan(self):
        f = hidden_hands_figure(self.tmp / "ralph.png")
        self.assertTrue(engine.make_cutout(f))
        r = run_rig(f, self.tmp / "rig")
        self.assertEqual(r.returncode, 2, r.stderr[-800:])
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("NaN", r.stderr)
        line = [ln for ln in r.stderr.splitlines() if ln.startswith("RIG-ERROR ")][0]
        err = json.loads(line[len("RIG-ERROR "):])
        self.assertEqual(err["part"], "hands")
        self.assertIn("could not be found", err["message"])
        self.assertIn("arms visible at the sides, hands not in pockets, no sleeves covering the hands", err["message"])
        self.assertFalse((self.tmp / "rig" / "rig.json").exists())

    def test_a_normal_pose_still_rigs(self):
        f = v2_figure(self.tmp / "ok.png")
        self.assertTrue(engine.make_cutout(f))
        r = run_rig(f, self.tmp / "rig")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        body = json.loads((self.tmp / "rig" / "rig.json").read_text())["body"]
        self.assertTrue(all(isinstance(v, (int, float)) for v in body["hand_l"] + body["hand_r"]))

    def test_the_message_is_read_from_the_output(self):
        from oddstudio.rig_check import rig_error
        out = 'warning\nRIG-ERROR {"part": "feet", "message": "the feet could not be found; redraw"}\n'
        self.assertEqual(rig_error(out), "the feet could not be found; redraw")
        self.assertEqual(rig_error("Traceback...\nValueError: boom\n"), "ValueError: boom")


class ApprovalCheckTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def pose(self, cid, expression, draw):
        """A pose awaiting review, as the pose job leaves it (cut-out PNG in storage)."""
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        from oddstudio.storage import sha256_file, storage
        f = draw(Path(tempfile.mkdtemp()) / f"{expression}.png")
        self.assertTrue(engine.make_cutout(f))
        key = f"characters/{cid}/{expression}-{f.stat().st_size}.png"
        storage().put_file(key, f, "image/png")
        with new_session() as s:
            a = CharacterAsset(character_id=cid, kind="pose", expression=expression, storage_key=key, sha256=sha256_file(f),
                               width=600, height=1200, feet={"x": 300, "y": 1120}, figure_height=1060, status="review",
                               style_version="v2")
            s.add(a)
            s.commit()
            return a.id

    def card(self, cid, aid):
        c = next(x for x in self.c.get("/api/characters").json() if x["id"] == cid)
        return next(a for a in c["assets"] if a["id"] == aid)

    def character(self, key, name):
        r = self.c.post("/api/characters", json={"key": key, "name": name, "visual_description": "a grey hoodie", "scope": "recurring"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def test_approving_a_pose_with_hidden_hands_warns_and_blocks_production(self):
        cid = self.character("ralph", "Ralph")
        aid = self.pose(cid, "neutral", hidden_hands_figure)
        self.assertEqual(self.c.post(f"/api/character-assets/{aid}/decision", json={"decision": "approve"}).status_code, 200)
        self.assertIsNone(self.card(cid, aid)["rig_check"], "queued: the card says it is waiting for the worker")
        ran = self.env.run_jobs(["rig_check"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        chk = self.card(cid, aid)["rig_check"]
        self.assertIs(chk["ok"], False)
        self.assertEqual(chk["role"], "body")
        self.assertIn("Ralph", chk["message"])
        self.assertIn("hands not in pockets", chk["message"])
        self.assertEqual(self.card(cid, aid)["status"], "approved", "the check never changes the owner's approval")
        from oddstudio import rig_check
        from oddstudio.db import new_session
        from oddstudio.models import Character
        with new_session() as s:
            bad = rig_check.blocking_problems(s, [s.get(Character, cid)])
        self.assertEqual(len(bad), 1)
        self.assertIn("Ralph", bad[0])

    def test_a_normal_pose_passes_and_expressions_are_checked_too(self):
        cid = self.character("nia", "Nia")
        n = self.pose(cid, "neutral", v2_figure)
        h = self.pose(cid, "happy", lambda p: v2_figure(p, mouth="smile"))
        self.assertEqual(self.c.post(f"/api/characters/{cid}/sheet/decision", json={"decision": "approve"}).status_code, 200)
        self.env.run_jobs(["rig_check"])
        self.assertEqual((self.card(cid, n)["rig_check"]["ok"], self.card(cid, n)["rig_check"]["role"]), (True, "body"))
        self.assertEqual((self.card(cid, h)["rig_check"]["ok"], self.card(cid, h)["rig_check"]["role"]), (True, "face"))
        from oddstudio import rig_check
        from oddstudio.db import new_session
        from oddstudio.models import Character
        with new_session() as s:
            self.assertEqual(rig_check.blocking_problems(s, [s.get(Character, cid)]), [])

    def test_rig_check_on_all_existing_approved_poses_is_informational(self):
        """Poses approved before the check existed: one action checks them all and changes no approval."""
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        from oddstudio.routes_characters import refresh_art
        from oddstudio.models import Character
        ralph, nia = self.character("ralph", "Ralph"), self.character("nia", "Nia")
        r_id, n_id = self.pose(ralph, "neutral", hidden_hands_figure), self.pose(nia, "neutral", v2_figure)
        with new_session() as s:   # approved the old way: no check was queued
            for aid in (r_id, n_id):
                s.get(CharacterAsset, aid).status = "approved"
            s.flush()
            for cid in (ralph, nia):
                refresh_art(s, s.get(Character, cid))
            s.commit()
        self.assertIsNone(self.card(ralph, r_id)["rig_check"])
        r = self.c.post("/api/characters/rig-check-all").json()
        self.assertEqual(sorted(r["queued"]), ["Nia", "Ralph"])
        self.assertEqual(self.c.post("/api/characters/rig-check-all").json()["already_running"], 2, "no duplicate jobs")
        self.env.run_jobs(["rig_check"])
        self.assertIs(self.card(ralph, r_id)["rig_check"]["ok"], False)
        self.assertIs(self.card(nia, n_id)["rig_check"]["ok"], True)
        self.assertEqual((self.card(ralph, r_id)["status"], self.card(nia, n_id)["status"]), ("approved", "approved"))

    def test_new_pose_prompts_ask_for_visible_hands(self):
        from types import SimpleNamespace
        from oddstudio.tasks import pose_prompt
        c = SimpleNamespace(name="Ralph", visual_description="a grey hoodie", skin_tone="")
        for v in ("v1", "v2"):
            self.assertIn("arms hanging at the sides with both hands visible", pose_prompt(c, "neutral", False, False, version=v))
            self.assertIn("never in pockets or covered by sleeves", pose_prompt(c, "smug", False, False, version=v))


if __name__ == "__main__":
    unittest.main()
