"""Editing the staging of an APPROVED set (owner request 2026-11-22, Episode 14): a set approved before its seats were
marked could not be fixed, so the episode said "the episode's set has 0 seat(s): 5 seated person(s) will stand".
Now the seats, the table front, the floor line and the standing area can be edited on an approved set. The picture and
the approval never change; the staging preview is redrawn; every episode using the set is re-checked and told."""
import unittest

from helpers import Env
from test_episode_sets import add_studio_set

SEATS = [{"x": 10, "hip_y": 60, "feet_y": 80}, {"x": 20, "hip_y": 60, "feet_y": 80},
         {"x": 35, "hip_y": 60, "feet_y": 80}, {"x": 50, "hip_y": 60, "feet_y": 80}]


class SetStagingEditTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def episode_using(self, set_id, seated=5):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        roles = [{"role": "speaker", "pose": "seated"}] + [{"role": f"reactor {n}", "pose": "seated"} for n in range(1, seated)]
        with new_session() as s:
            ep = Episode(title="Will test", stage="audio_labelling", source="audio", audio_rights_confirmed=True, set_id=set_id,
                         audio_transcript={"lines": [{"id": "l1", "speaker": "a", "text": "Hi.", "start": 0, "end": 3}],
                                           "video_notes": {"ranges": [{"start": 0, "end": 4, "setting": "office", "roles": roles}],
                                                           "length": 4.0}})
            s.add(ep)
            s.commit()
            return ep.id

    def record(self, sid):
        from oddstudio import sets
        from oddstudio.db import new_session
        with new_session() as s:
            return sets.records(s)[sid]

    def test_an_approved_sets_seats_and_table_front_can_be_edited_without_touching_its_approval(self):
        add_studio_set("will-test", status="approved")
        before = self.record("will-test")
        eid = self.episode_using("will-test", seated=4)
        plan = self.c.get(f"/api/episodes/{eid}/reference-plan").json()
        self.assertIn("has 0 seat(s)", plan["ranges"][0]["items"]["seating"]["note"], "the problem as the owner saw it")
        r = self.c.put("/api/sets/will-test/staging", json={"blocking": {"seats": SEATS, "table_front": {"x0": 5, "y0": 62, "x1": 55, "y1": 78}}})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["status"], len(out["blocking"]["seats"]), out["blocking"]["table_front"]["x1"]), ("approved", 4, 55))
        self.assertTrue(out["preview_url"], "the staging preview is redrawn")
        after = self.record("will-test")
        self.assertEqual((after["status"], after["asset_id"]), (before["status"], before["asset_id"]), "never the approval or the picture")
        self.assertEqual(after["blocking"]["floor_y"], before["blocking"]["floor_y"], "untouched fields stay")
        self.assertNotEqual(after.get("preview_asset_id"), before.get("preview_asset_id"))
        self.assertEqual(out["episodes"], [{"id": eid, "title": "Will test", "seats": 4, "seated_at_once": 4, "ok": True,
                                            "note": "enough seats for the 4 seated at once"}], "every episode using it is re-checked")
        plan = self.c.get(f"/api/episodes/{eid}/reference-plan").json()
        note = plan["ranges"][0]["items"]["seating"]["note"]
        self.assertNotIn("seat(s):", note, "the seating warning is gone")
        self.assertIn("drawn about", note, "seats 10-15 px apart are close: the plan says the cast is drawn smaller")
        from oddstudio.db import new_session
        from oddstudio.models import Event
        with new_session() as s:
            msgs = [e.message for e in s.query(Event).filter_by(episode_id=eid)]
        self.assertTrue(any("staging edited" in m and "0 -> 4 seat(s)" in m for m in msgs), msgs)

    def test_too_few_seats_are_reported_and_bad_staging_is_refused(self):
        add_studio_set("will-test", status="approved")
        eid = self.episode_using("will-test", seated=5)
        out = self.c.put("/api/sets/will-test/staging", json={"blocking": {"seats": SEATS}}).json()
        self.assertEqual((out["episodes"][0]["ok"], out["episodes"][0]["note"]), (False, "the notes seat up to 5 at once: 1 will stand"))
        self.assertEqual(eid, out["episodes"][0]["id"])
        bad = [{"seats": [{"x": 10, "hip_y": 90, "feet_y": 80}]}, {"seats": [{"x": 999, "hip_y": 10, "feet_y": 20}]},
               {"table_front": {"x0": 50, "y0": 10, "x1": 40, "y1": 20}}, {"floor_y": 0}, {"stand_min_x": 50, "stand_max_x": 10},
               {"seats": [{"x": 10}]}, {"floor_y": "low"}]
        for b in bad:
            self.assertEqual(self.c.put("/api/sets/will-test/staging", json={"blocking": b}).status_code, 422, b)
        self.assertEqual(len(self.record("will-test")["blocking"]["seats"]), 4, "a refused edit changes nothing")
        # the table front can be removed again
        out = self.c.put("/api/sets/will-test/staging", json={"blocking": {"table_front": None}}).json()
        self.assertNotIn("table_front", out["blocking"])

    def test_only_candidates_and_approved_sets(self):
        add_studio_set("gone", status="rejected")
        self.assertEqual(self.c.put("/api/sets/gone/staging", json={"blocking": {"seats": SEATS}}).status_code, 404)
        self.assertEqual(self.c.put("/api/sets/nowhere/staging", json={"blocking": {"seats": SEATS}}).status_code, 404)
        add_studio_set("cand", status="candidate")
        r = self.c.put("/api/sets/cand/staging", json={"blocking": {"seats": SEATS}})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "candidate"), "a candidate stays a candidate")
        self.assertEqual(r.json()["episodes"], [])


if __name__ == "__main__":
    unittest.main()
