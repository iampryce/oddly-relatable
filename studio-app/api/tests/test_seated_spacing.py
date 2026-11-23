"""fix/seated-limbs-and-spacing (owner decision 2026-11-23): seated neighbours' heads never overlap (the cast is drawn
smaller, never below MIN_HEIGHT), and seats closer than one head width at that smallest height are WARNED about, with
the numbers, wherever seats are marked, edited, suggested or approved. Never refused: most generated sets space their
chairs for normal proportions."""
import unittest

from helpers import Env
from test_episode_sets import add_studio_set

from oddstudio import acting, sets

EP14 = [{"x": 269, "hip_y": 968, "feet_y": 1082}, {"x": 422, "hip_y": 968, "feet_y": 1082},
        {"x": 561, "hip_y": 968, "feet_y": 1082}, {"x": 690, "hip_y": 968, "feet_y": 1082}]
DESK = [{"x": 512, "hip_y": 829, "feet_y": 937}, {"x": 236, "hip_y": 1167, "feet_y": 1306},
        {"x": 512, "hip_y": 1167, "feet_y": 1306}, {"x": 788, "hip_y": 1167, "feet_y": 1306}]


class RulesTest(unittest.TestCase):
    def test_the_smallest_head_and_the_warning_text(self):
        self.assertEqual(acting.MIN_HEIGHT, 318)
        self.assertEqual(acting.HEAD_OVERLAP, 0.0)
        need = acting.min_head_px()
        self.assertEqual(need, 134, "0.42 x 318 px, rounded up")
        w = acting.spacing_warnings(EP14)
        self.assertEqual([x["seats"] for x in w], [[3, 4]])
        self.assertTrue(w[0]["text"].startswith("seats 3 and 4 are 129 px apart; need 134 px"), w[0]["text"])

    def test_a_desk_seat_and_the_row_in_front_are_different_rows(self):
        self.assertEqual(acting.row_neighbours(DESK, 134), [(2, 3, 276), (3, 4, 276)])
        self.assertEqual(acting.spacing_warnings(DESK), [])
        self.assertEqual(acting.cast_height(DESK, 0.42), 530, "the desk seat straight above a row seat is not a 0 px gap")

    def test_the_cast_height_clears_the_heads_down_to_the_floor(self):
        self.assertEqual(acting.cast_height(EP14, 0.4224), 318)
        self.assertEqual(acting.cast_height([{"x": 100}, {"x": 300}], 0.42), 476, "200 px apart: 476 px, heads just touching")
        self.assertLessEqual(0.42 * acting.cast_height([{"x": 100}, {"x": 300}], 0.42), 200)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def episode(self):
        return self.c.post("/api/audio-episodes", json={"title": "Will", "format": "short", "rights_confirmed": True,
                                                        "rights_source": "own_recording"}).json()["id"]

    def blocking(self, seats):
        return {"floor_y": 1300, "stand_min_x": 60, "stand_max_x": 960, "seats": seats}

    def big_set(self, sid, eid):
        """A candidate with a picture as large as a real set (1024 x 1536), made for the episode."""
        add_studio_set(sid, status="candidate", kept=False, episode_id=eid)
        from oddstudio.db import new_session
        with new_session() as db:
            recs = sets.records(db)
            recs[sid].update(width=1024, height=1536, blocking={"floor_y": 1300, "stand_min_x": 60, "stand_max_x": 960})
            sets.save(db, recs)
            db.commit()

    def test_marked_edited_and_approved_seats_are_warned_never_refused(self):
        eid = self.episode()
        self.big_set("will-room", eid)
        r = self.c.put("/api/sets/will-room/staging", json={"blocking": self.blocking(EP14)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([w["seats"] for w in r.json()["spacing"]], [[3, 4]], "edited: the warning comes back")
        p = self.c.get(f"/api/episodes/{eid}/set-panel").json()
        self.assertEqual((p["min_head_px"], p["min_height"]), (134, 318))
        self.assertIn("seats 3 and 4 are 129 px apart; need 134 px", p["sets"][0]["spacing"][0]["text"])
        r = self.c.post("/api/sets/will-room/decide", json={"decision": "approve", "blocking": self.blocking(EP14)})
        self.assertEqual(r.status_code, 200, "approved despite the close seats: a warning, never a refusal")
        self.assertEqual(r.json()["status"], "approved")
        self.assertEqual([w["seats"] for w in r.json()["spacing"]], [[3, 4]])
        events = [e["message"] for e in self.c.get(f"/api/episodes/{eid}").json()["events"]]
        self.assertTrue(any("approved by" in m and "seats 3 and 4 are 129 px apart" in m for m in events), events[:5])
        # wider seats: no warning
        r = self.c.put("/api/sets/will-room/staging", json={"blocking": self.blocking(DESK)})
        self.assertEqual(r.json()["spacing"], [])
        self.assertEqual(self.c.get("/api/sets").json()["min_head_px"], 134)

    def test_suggested_seats_carry_their_warning(self):
        from oddstudio import seat_suggest as SS
        per_mille = {"row": [{"x": 260, "hip_y": 630, "feet_y": 700}, {"x": 400, "hip_y": 630, "feet_y": 700},
                             {"x": 520, "hip_y": 630, "feet_y": 700}]}
        blk, _ = SS.clean(per_mille, 1024, 1536, {"floor_y": 1300, "stand_min_x": 60, "stand_max_x": 960})
        self.assertEqual([w["seats"] for w in sets.spacing_of(blk)], [[2, 3]], "143 and 123 px apart: the second pair is close")


if __name__ == "__main__":
    unittest.main()
