"""Episode 14's scene 1 still (owner request 2026-11-22): a black circle over Uncle Mortimer's face (his white hair was
taken for an eye), characters far too big for the set's close seats, seated arms and legs drawn as loops, and a "POV"
banner nobody asked for. Covered here: the eye pair rule, the cast height fitted to the seats, the per-episode hook
banner (default off for audio episodes; migration 0014 keeps it for script-first and already-rendered episodes), and
the set rules (chairs facing the camera, seats spaced for big-headed characters). The seated limb anchors are checked
with renderer frames (the API test image has no canvas)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from helpers import Env, sample_script

from oddstudio import acting, providers

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "production" / "animation"))
import rig_extract as RX  # noqa: E402


def blob(x0, y0, w, h):
    """A component as rig_extract gives it: an array of (y, x) pixels."""
    ys, xs = np.mgrid[y0:y0 + h, x0:x0 + w]
    return np.stack([ys.ravel(), xs.ravel()], 1)


class EyePairTest(unittest.TestCase):
    def test_white_hair_is_not_an_eye(self):
        hair = blob(60, 20, 495, 273)                     # Mortimer: a big white hair shape on a 586 px head
        left, right = blob(150, 260, 146, 176), blob(312, 262, 146, 177)
        glint = blob(500, 100, 20, 20)
        got = RX.eye_pair(sorted([hair, left, right, glint], key=len, reverse=True), 586)
        xs = sorted(int(c[:, 1].min()) for c in got)
        self.assertEqual(xs, [150, 312], "the two alike shapes at the same height, not the hair")

    def test_ordinary_eyes_are_unchanged_and_a_lone_shape_falls_back(self):
        a, b = blob(100, 200, 120, 130), blob(300, 202, 118, 128)
        self.assertEqual(sorted(int(c[:, 1].min()) for c in RX.eye_pair([a, b], 600)), [100, 300])
        big, small = blob(0, 0, 500, 300), blob(0, 400, 40, 40)
        self.assertEqual(len(RX.eye_pair([big, small], 600)), 2, "no qualifying pair: the two biggest, as before")

    def test_a_full_extraction_with_white_hair(self):
        """A v1 face whose white hair is bigger than its eyes: both eyes are found, none is the hair."""
        from test_rig_v2 import v2_figure  # noqa: F401  (the synthetic figure helpers live there)
        tmp = Path(tempfile.mkdtemp())
        im = Image.new("RGBA", (600, 1400), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((30, 20, 570, 560), fill=(254, 231, 204, 255), outline=(10, 10, 10, 255), width=14)   # head
        d.ellipse((90, 30, 510, 200), fill=(250, 250, 250, 255))                                          # white hair
        for cx in (215, 385):                                                                             # two eyes
            d.ellipse((cx - 70, 260, cx + 70, 420), fill=(253, 252, 250, 255), outline=(10, 10, 10, 255), width=8)
            d.ellipse((cx - 22, 320, cx + 22, 364), fill=(10, 10, 10, 255))
        d.line((270, 485, 330, 485), fill=(10, 10, 10, 255), width=10)                                    # mouth
        rgba = np.array(im)
        f = RX.face_features(rgba, 20, 560, 300.0)
        widths = sorted(round(e["w"]) for e in f["eyes"])
        self.assertTrue(all(w < 200 for w in widths), f"no eye as wide as the hair: {widths}")
        self.assertAlmostEqual(f["eyes"][0]["cy"], f["eyes"][1]["cy"], delta=5)


class CastHeightTest(unittest.TestCase):
    def test_close_seats_draw_the_cast_smaller_and_wide_seats_keep_the_default(self):
        # fix/seated-limbs-and-spacing: no head overlap (was 25%), never below MIN_HEIGHT (318 px)
        ep14 = [{"x": 269}, {"x": 422}, {"x": 561}, {"x": 690}]
        h = acting.cast_height(ep14, 0.422)
        self.assertEqual(h, 318, "Episode 14: no overlap needs 305 px on seats 129 px apart; the floor is 318")
        self.assertEqual(acting.cast_height([{"x": 100}, {"x": 250}], 0.42), 357, "no overlap: 150 px / 0.42")
        self.assertEqual(acting.cast_height([{"x": 100}, {"x": 500}], 0.42), 530, "seats far apart: the default")
        self.assertEqual(acting.cast_height([{"x": 300}], 0.42), 530, "one seat")
        self.assertEqual(acting.cast_height([], 0.42), 530, "no seats")
        self.assertEqual(acting.cast_height([{"x": 100}, {"x": 120}], 0.42), 318, "never below the floor (60% of the default)")
        rig = {"faces": {"neutral": {"size": [586, 558]}}, "body": {"height": 1400}}
        self.assertAlmostEqual(acting.head_ratio(rig), 0.4186, places=3)
        self.assertEqual(acting.head_ratio({}), 0.0)


class HookBannerTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def audio_episode(self):
        return self.c.post("/api/audio-episodes", json={"title": "Will test", "format": "short", "rights_confirmed": True,
                                                        "rights_source": "own_recording"}).json()["id"]

    def script_episode(self):
        providers.set_test_text_responder(lambda s, p: sample_script())
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        return eid

    def hook(self, eid):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            return acting.episode_hook(s, s.get(Episode, eid))

    def test_audio_episodes_start_without_a_banner_and_the_switch_and_text_work(self):
        a = self.audio_episode()
        e = self.c.get(f"/api/episodes/{a}").json()
        self.assertEqual((e["hook_banner"], e["hook_text"]), (False, ""), "audio episodes: off by default")
        self.assertEqual(self.hook(a), "", "no banner in the stills or the render")
        r = self.c.put(f"/api/episodes/{a}/hook", json={"enabled": True, "text": "  POV:   the will is read  "})
        self.assertEqual((r.json()["hook_banner"], r.json()["hook_text"]), (True, "POV: the will is read"))
        self.assertEqual(self.hook(a), "POV: the will is read", "the episode's own text")
        r = self.c.put(f"/api/episodes/{a}/hook", json={"enabled": True, "text": ""})
        self.assertEqual(self.hook(a), "Will test", "no own text and no script hook: the title")
        self.c.put(f"/api/episodes/{a}/hook", json={"enabled": False})
        self.assertEqual(self.hook(a), "")
        self.assertEqual(self.c.put(f"/api/episodes/{a}/hook", json={"enabled": True, "text": "x" * 121}).status_code, 422)
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            s.get(Episode, a).stage = "producing"
            s.commit()
        self.assertEqual(self.c.put(f"/api/episodes/{a}/hook", json={"enabled": True}).status_code, 409, "not during a render")

    def test_script_first_episodes_keep_their_banner_with_the_scripts_hook(self):
        eid = self.script_episode()
        self.assertTrue(self.c.get(f"/api/episodes/{eid}").json()["hook_banner"])
        self.assertEqual(self.hook(eid), sample_script().get("hook") or "Card")
        self.c.put(f"/api/episodes/{eid}/hook", json={"enabled": False})
        self.assertEqual(self.hook(eid), "", "switched off: no banner in the pose engine's render either")


class MigrationTest(unittest.TestCase):
    def test_0014_keeps_the_banner_where_it_was_shown_and_drops_it_for_unrendered_audio_episodes(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine
        from oddstudio import config
        api = Path(__file__).resolve().parents[1]
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig14-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = Config(str(api / "alembic.ini"))
            cfg.set_main_option("script_location", str(api / "migrations"))
            command.upgrade(cfg, "0013")
            eng = create_engine(os.environ["DATABASE_URL"])
            ins = ("insert into episodes (id, title, stage, source, revision, storyboard_version, last_error, format, created_at, "
                   "updated_at) values (?, ?, ?, ?, 1, 1, '', 'short', '2026-11-22', '2026-11-22')")
            with eng.begin() as conn:
                for row in ((1, "script-first", "script_review", "script"), (2, "audio, unrendered", "storyboard_review", "audio"),
                            (3, "audio, rendered", "video_review", "audio"), (4, "audio, published", "published", "audio")):
                    conn.exec_driver_sql(ins, row)
            command.upgrade(cfg, "0014")
            with eng.connect() as conn:
                got = {i: bool(v) for i, v in conn.exec_driver_sql("select id, hook_banner from episodes order by id").fetchall()}
            self.assertEqual(got, {1: True, 2: False, 3: True, 4: True})
            command.downgrade(cfg, "0013")
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


class SetRulesTest(unittest.TestCase):
    def test_chairs_face_the_camera_and_seats_are_spaced_for_the_cast(self):
        from oddstudio import sets
        r = sets.rules_text(4)
        self.assertIn("never with their backs to the camera", r)
        self.assertIn("at least one chair's width between neighbouring seats", r)
        self.assertIn("seating for at least 4 people", r)


if __name__ == "__main__":
    unittest.main()
