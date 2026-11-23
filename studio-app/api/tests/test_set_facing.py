"""feat/3d-rig PR 3: each seat's facing (toward the speaker, the camera, another seat, or away), kept and checked when
the staging is edited; empty means the default (the speaker's seat faces the camera, the others face the speaker)."""
import unittest

from helpers import Env
from test_episode_sets import add_studio_set

from oddstudio import sets


class FacingTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        add_studio_set("desk-room", status="approved")
        from oddstudio.db import new_session
        with new_session() as db:
            recs = sets.records(db)
            recs["desk-room"].update(width=1024, height=1536, blocking={"floor_y": 1498, "stand_min_x": 20, "stand_max_x": 1004})
            sets.save(db, recs)
            db.commit()

    def tearDown(self):
        self.env.close()

    def staging(self, facings):
        seats = [{"x": x, "hip_y": 920, "feet_y": 1068} for x in (180, 530, 737, 940)]
        for s, f in zip(seats, facings):
            if f is not None:
                s["facing"] = f
        return self.c.put("/api/sets/desk-room/staging", json={"blocking": {"floor_y": 1498, "stand_min_x": 20, "stand_max_x": 1004, "seats": seats}})

    def test_facing_is_kept_defaults_are_left_empty_and_bad_values_refused(self):
        r = self.staging([None, "speaker", "seat:1", "away"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([s.get("facing") for s in r.json()["blocking"]["seats"]], [None, "speaker", "seat:1", "away"])
        self.assertEqual(self.staging(["camera", None, None, None]).status_code, 200)
        for bad in (["sideways", None, None, None], [None, "seat:1", None, None], [None, "seat:7", None, None]):
            r = self.staging(bad)
            self.assertEqual(r.status_code, 422, bad)
            self.assertIn("facing", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()


class FacingNotesTest(unittest.TestCase):
    def test_the_plan_says_who_faces_whom_camera_and_unconfirmed_left_out(self):
        from unittest import mock
        from oddstudio import reference_plan as RP
        ranges = [{"start": 0.0, "end": 4.0, "roles": [
            {"role": "speaker", "who": "uncle-mortimer", "facing": "right"},
            {"role": "reactor 1", "who": "ralph", "facing": "left"},
            {"role": "reactor 2", "who": "sidney", "facing": "reactor 1"},
            {"role": "reactor 3", "who": "winifred", "facing": "camera"},
            {"role": "reactor 4", "who": None, "facing": "left"}]}]
        with mock.patch.object(RP, "effective", lambda tr: ranges):
            got = RP.facing_notes({})
        self.assertEqual(got, [{"start": 0.0, "end": 4.0, "facing": {"uncle-mortimer": "right", "ralph": "left", "sidney": "ralph"}}])
