"""feat/3d-rig PR 2: the Studio 3D rig animator as a Motion option beside the 2D one (nothing removed), the renderer run
under a virtual display on Linux, and the approved head drawings handed to the renderer (the mock for the rest)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import Env

from oddstudio import acting, capabilities


class CommandTest(unittest.TestCase):
    def test_xvfb_only_for_3d_on_linux_without_a_display(self):
        with mock.patch("sys.platform", "linux"), mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("shutil.which", lambda n: "/usr/bin/xvfb-run" if n == "xvfb-run" else None):
            os.environ.pop("DISPLAY", None)
            self.assertEqual(acting.node_command("node", ["r.mjs", "a.json", "out"], True)[:3], ["xvfb-run", "-a", "-s"])
            self.assertEqual(acting.node_command("node", ["r.mjs"], False), ["node", "r.mjs"], "the 2D renderer needs no display")
            with mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
                self.assertEqual(acting.node_command("node", ["r.mjs"], True), ["node", "r.mjs"], "a display is there already")
        with mock.patch("sys.platform", "darwin"):
            self.assertEqual(acting.node_command("node", ["r.mjs"], True), ["node", "r.mjs"], "macOS: headless-gl needs no X")

    def test_the_3d_option_needs_a_display_on_linux(self):
        self.assertIn("tool:gl-display", capabilities.CAPABILITIES["motion"]["providers"]["procedural-rig-3d"]["needs"])
        with mock.patch("sys.platform", "linux"), mock.patch("shutil.which", lambda n: None):
            with mock.patch.dict(os.environ, {"DISPLAY": ""}):
                self.assertFalse(capabilities.tool_present("gl-display"), "no display and no xvfb-run: unavailable")
            with mock.patch.dict(os.environ, {"DISPLAY": ":99"}):
                self.assertTrue(capabilities.tool_present("gl-display"))
        with mock.patch("sys.platform", "linux"), mock.patch("shutil.which", lambda n: "/usr/bin/xvfb-run"):
            self.assertTrue(capabilities.tool_present("gl-display"))
        with mock.patch("sys.platform", "darwin"):
            self.assertTrue(capabilities.tool_present("gl-display"))

    def test_the_3d_option_sits_beside_the_2d_one(self):
        motion = capabilities.CAPABILITIES["motion"]["providers"]
        self.assertIn("procedural-rig", motion, "the 2D rig animator stays")
        self.assertEqual(motion["procedural-rig-3d"]["label"], "Studio 3D rig animator (three.js, CPU, free)")
        self.assertTrue(motion["procedural-rig-3d"]["implemented"])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def test_both_rig_animators_use_the_acting_renderer_and_only_one_is_3d(self):
        from oddstudio.db import new_session
        for provider, on, three in (("procedural-rig", True, False), ("procedural-rig-3d", True, True), ("none", False, False)):
            self.c.put("/api/settings/motion", json={"provider": provider})
            with new_session() as db:
                self.assertEqual((acting.enabled(db), acting.three_d(db)), (on, three), provider)

    def test_approved_head_drawings_are_handed_to_the_renderer(self):
        from PIL import Image
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset
        from oddstudio.storage import storage
        cid = self.c.post("/api/characters", json={"key": "mortimer", "name": "Uncle Mortimer"}).json()["id"]
        f = Path(tempfile.mkdtemp()) / "side.png"
        Image.new("RGBA", (40, 50), (200, 180, 160, 255)).save(f)
        storage().put_file("characters/mortimer/head-angles/side.png", f, "image/png")
        storage().put_file("characters/mortimer/head-angles/back.png", f, "image/png")
        with new_session() as db:
            db.add(CharacterAsset(character_id=cid, kind="head-angle", expression="side", storage_key="characters/mortimer/head-angles/side.png", status="approved"))
            db.add(CharacterAsset(character_id=cid, kind="head-angle", expression="back", storage_key="characters/mortimer/head-angles/back.png", status="review"))
            db.commit()
            out = acting.head_angle_files(db, db.get(Character, cid), Path(tempfile.mkdtemp()))
        self.assertEqual(sorted(out), ["side"], "only approved drawings; the rest use the mock")
        self.assertTrue(Path(out["side"]).exists())


if __name__ == "__main__":
    unittest.main()
