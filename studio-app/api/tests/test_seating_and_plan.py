"""Seating and the Reference plan (owner decisions 2026-11-21).

- A set can have several seats and a table front; marking them is validated on the set approval screen.
- Each scene starts in the arrangement of the video notes (who is seated or standing, whom they face), speaker first;
  the first scene's seated characters take the set's seats in that order (more than the seats: they stand).
- Where an episode has video notes, the Reference plan lists per range what will be used (set, seating, shot,
  reactors), with the unedited and edited values and a used/ignored toggle; nothing is built until it is accepted,
  and editing the notes or a toggle withdraws the acceptance.
- The owner's edits override the notes; only the notes' fixed-list values are ever used."""
import re
import unittest

from helpers import Env

from oddstudio import video_notes as VN
from oddstudio.acting import seat_starts

LINES = [{"id": "l1", "start": 0.2, "end": 2.0, "text": "I leave everything to the cat.", "speaker": "mortimer", "words": []},
         {"id": "l2", "start": 2.4, "end": 4.0, "text": "The cat?", "speaker": "winnie", "words": []}]
RAW = {"ranges": [{"start": 0, "end": 2.2, "shot": "wide", "camera": "pan", "setting": "office", "furniture": "long table",
                   "time": "evening", "roles": [
                       {"role": "speaker", "position": "left", "pose": "seated", "facing": "reactor 1", "emotion": "smug"},
                       {"role": "reactor 1", "position": "center", "pose": "seated", "facing": "speaker", "emotion": "shocked"},
                       {"role": "reactor 2", "position": "right", "pose": "standing", "facing": "speaker", "emotion": "angry"}]},
                  {"start": 2.2, "end": 4.2, "shot": "close", "camera": "static", "setting": "office",
                   "roles": [{"role": "speaker", "pose": "seated", "emotion": "shocked"}]}]}


class SeatStartsTest(unittest.TestCase):
    def test_speaker_first_and_no_more_than_the_seats(self):
        st = {"mortimer": "seated", "ralph": "seated", "winnie": "standing"}
        self.assertEqual(seat_starts(st, ["mortimer", "ralph", "winnie"], 2),
                         ({"mortimer": "seat:0", "ralph": "seat:1", "winnie": "on"}, []))
        self.assertEqual(seat_starts(st, ["mortimer", "ralph", "winnie"], 1),
                         ({"mortimer": "seat:0", "ralph": "on", "winnie": "on"}, ["ralph"]))
        self.assertEqual(seat_starts({"ghost": "seated"}, ["mortimer"], 3), ({}, []), "only cast members")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, Episode
        ranges, _ = VN.clean_notes(RAW, 5.0)
        with new_session() as s:
            for k in ("mortimer", "winnie", "ralph"):
                s.add(Character(key=k, name=k.title(), scope="episode", art_status="none"))
            ep = Episode(title="The Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": LINES, "silent_cast": [{"name": "Ralph", "character_key": "ralph"}],
                                           "video_notes": {"ranges": ranges, "frames": 2, "redacted": 0, "length": 5.0}})
            s.add(ep)
            s.commit()
            self.eid = ep.id

    def tearDown(self):
        self.env.close()

    def plan(self):
        return self.c.get(f"/api/episodes/{self.eid}/reference-plan").json()

    def edit_setting(self, value):
        notes = self.c.get(f"/api/episodes/{self.eid}/audio").json()["video_notes"]
        ranges = [{k: v for k, v in r.items() if k != "line_ids"} for r in notes["ranges"]]
        for r in ranges:
            r["setting"] = value
        r = self.c.put(f"/api/episodes/{self.eid}/audio/video-notes", json={"ranges": ranges})
        self.assertEqual(r.status_code, 200, r.text)

    def test_the_plan_lists_each_range_with_notes_on_what_cannot_be_done(self):
        p = self.plan()
        self.assertTrue(p["needs_acceptance"])
        first = p["ranges"][0]["items"]
        self.assertEqual(first["set"]["value"], "office, long table, evening")
        self.assertEqual(first["seating"]["value"], "Mortimer seated, facing Ralph; Ralph seated, facing Mortimer; Winnie standing, facing Mortimer")
        self.assertEqual(first["reactors"]["value"], "Ralph (shocked), Winnie (angry)")
        self.assertIn("does not pan", first["shot"]["note"])
        self.assertIn("choose the episode's set", first["seating"]["note"])
        self.assertTrue(all(it["used"] for it in first.values()))

    def test_nothing_is_built_until_the_plan_is_accepted_and_edits_withdraw_it(self):
        r = self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": "simple"})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept").json()["accepted"])
        self.edit_setting("dining room")
        self.assertFalse(self.plan()["accepted"], "an edit of the notes withdraws the acceptance")
        self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept")
        self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ["1:shot"]})
        self.assertFalse(self.plan()["accepted"], "a toggle withdraws it too")
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ["7:shot"]}).status_code, 422)

    def test_my_edits_override_the_notes_and_show_both_values(self):
        # the vision model called a family gathering an "office"
        self.edit_setting("dining room")
        it = self.plan()["ranges"][0]["items"]["set"]
        self.assertEqual((it["original"], it["value"], it["edited"]), ("office, long table, evening", "dining room, long table, evening", True))
        v = self.c.post(f"/api/episodes/{self.eid}/set-proposal/propose").json()
        self.assertTrue(v["text"].startswith("An original dining room with a long table, evening"), v["text"])
        self.assertNotIn("office", v["text"])
        self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ["0:set", "1:set"]})
        v = self.c.post(f"/api/episodes/{self.eid}/set-proposal/propose").json()
        self.assertTrue(v["text"].startswith("An original room,"), "an ignored set item is not used: " + v["text"])

    def test_the_notes_drive_the_seating_shots_and_reactors(self):
        self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept")
        self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": "simple"})
        ran = self.env.run_jobs(["audio_scenes"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        sc = self.c.get(f"/api/episodes/{self.eid}").json()["script"]["content"]["scenes"]
        self.assertEqual(list(sc[0]["staging"].items()), [("mortimer", "seated"), ("ralph", "seated"), ("winnie", "standing")],
                         "speaker first, in the notes' arrangement")
        l1 = sc[0]["lines"][0]
        self.assertEqual((l1["shot"], l1["look_at"]), ("wide", "ralph"), "the shot, and the speaker faces reactor 1")
        self.assertEqual([r["character"] for r in l1["reactions"]], ["ralph", "ralph"][:len(l1["reactions"])])
        self.assertEqual([ln["text"] for s in sc for ln in s["lines"]], [ln["text"] for ln in LINES], "dialogue untouched")
        words = set(re.findall(r"[a-z]+", " ".join(v for s in sc for v in (s.get("staging") or {}).values())))
        self.assertLessEqual(words, {"seated", "standing"}, "only fixed values")

    def test_the_plan_survives_a_transcript_rebuild(self):
        from oddstudio.audio_first import KEEP_KEYS
        self.assertIn("reference_plan", KEEP_KEYS, "re-transcribing or re-trimming keeps your ignored items")

    def test_ignored_items_are_not_used(self):
        self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ["0:seating", "0:shot", "0:reactors"]})
        self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept")
        self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": "simple"})
        self.env.run_jobs(["audio_scenes"])
        sc = self.c.get(f"/api/episodes/{self.eid}").json()["script"]["content"]["scenes"]
        l1 = sc[0]["lines"][0]
        self.assertNotIn("staging", sc[0])
        self.assertNotIn("look_at", l1)
        self.assertNotIn("reactions", l1)
        self.assertEqual(l1["shot"], "wide", "no shot note: the default")


class UnconfirmedPeopleTest(unittest.TestCase):
    """Episode 14 (2026-11-22): six people in the video, four confirmed under People (Mortimer, Ralph, Sidney,
    Winifred). The two unconfirmed people used to appear as an extra Ralph and Sidney in Seating and Reactors (the
    reactors wrapped around the cast). Unconfirmed people are now left out, and nobody appears twice."""

    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, Episode
        pos = ["left", "center", "right", "background", "right", "background"]
        people = [{"person": n, "position": pos[n - 1], "pose": "standing" if n == 6 else "seated", **({"talking": True} if n == 1 else {})}
                  for n in range(1, 7)]
        frames = [{"t": t + 0.5, "shot": "wide", "setting": "office", "people": [dict(p) for p in people]} for t in range(4)]
        roles = [{"role": "speaker", "position": "left", "pose": "seated"}] + [
            {"role": f"reactor {n}", "position": pos[n], "pose": "standing" if n == 5 else "seated"} for n in range(1, 6)]
        ranges, _ = VN.clean_notes({"ranges": [{"start": 0, "end": 4, "shot": "wide", "setting": "office", "roles": roles}]}, 4.0)
        lines = [{"id": "l1", "start": 0.2, "end": 3.5, "text": "I leave everything to the cat.", "speaker": "uncle-mortimer", "words": []}]
        with new_session() as s:
            for k, n in (("uncle-mortimer", "Uncle Mortimer"), ("ralph", "Ralph"), ("sidney", "Sidney"), ("winifred", "Winifred")):
                s.add(Character(key=k, name=n, scope="episode", art_status="none"))
            ep = Episode(title="Will test", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": lines,
                                           "silent_cast": [{"name": n, "character_key": n.lower()} for n in ("Ralph", "Sidney", "Winifred")],
                                           "person_map": {"uncle-mortimer": 1, "ralph": 2, "sidney": 3, "winifred": 4},
                                           "video_notes": {"version": 2, "ranges": ranges, "people_frames": frames, "frames": 4,
                                                           "redacted": 0, "length": 4.0}})
            s.add(ep)
            s.commit()
            self.eid = ep.id

    def tearDown(self):
        self.env.close()

    def test_unconfirmed_people_are_left_out_and_nobody_appears_twice(self):
        it = self.c.get(f"/api/episodes/{self.eid}/reference-plan").json()["ranges"][0]["items"]
        seating = it["seating"]["value"]
        self.assertEqual(seating, "Uncle Mortimer seated; Ralph seated; Sidney seated; Winifred seated")
        for n in ("Ralph", "Sidney", "Winifred", "Uncle Mortimer"):
            self.assertEqual(seating.count(n), 1, f"{n} once")
        self.assertNotIn("reactor", seating)
        self.assertEqual(it["reactors"]["value"], "Ralph (neutral), Sidney (neutral), Winifred (neutral)")
        self.assertIn("2 person(s) left out (2 not confirmed under People)", it["seating"]["note"])
        # the scene builder stages the same four, once each, and gives reactions only to confirmed characters
        self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept")   # test step (the owner accepts the plan)
        self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": "simple"})
        ran = self.env.run_jobs(["audio_scenes"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        sc = self.c.get(f"/api/episodes/{self.eid}").json()["script"]["content"]["scenes"]
        self.assertEqual(list(sc[0]["staging"]), ["uncle-mortimer", "ralph", "sidney", "winifred"])
        reacts = [r["character"] for r in sc[0]["lines"][0].get("reactions", [])]
        self.assertEqual(len(reacts), len(set(reacts)), "no character reacts twice")
        self.assertTrue(set(reacts) <= {"ralph", "sidney", "winifred"})

    def test_a_beat_at_a_cut_belongs_to_the_range_that_starts_there(self):
        from oddstudio.reference_plan import effective_beats, range_index
        ranges = [{"start": 0.0, "end": 3.98}, {"start": 3.97, "end": 7.95}, {"start": 19.86, "end": 49.67}, {"start": 49.66, "end": 52.65}]
        self.assertEqual([range_index(ranges, t) for t in (1.0, 3.97, 49.66, 60.0)], [0, 1, 3, None])
        tr = {"video_notes": {"ranges": ranges, "beats": [{"id": "b1", "t": 3.97, "type": "exit", "person": 3},
                                                          {"id": "b2", "t": 19.87, "type": "enter", "person": 1},
                                                          {"id": "b3", "t": 49.66, "type": "turn_to", "person": 2, "target": "person 3"}]},
              "reference_plan": {"ignored": ["1:movement", "2:movement"]}}
        self.assertEqual([b["id"] for b in effective_beats(tr)], ["b3"], "unticking the cut's ranges keeps the turn at 49.66 s")

    def test_without_confirmed_people_the_reactors_never_wrap_around(self):
        from oddstudio.reference_plan import role_map
        m = role_map([{"speaker": "uncle-mortimer"}], ["uncle-mortimer"], ["ralph", "sidney", "winifred"])
        self.assertEqual(m, {"speaker": "uncle-mortimer", "reactor 1": "ralph", "reactor 2": "sidney", "reactor 3": "winifred"},
                         "reactor 4 and 5 are left out, not Ralph and Sidney again")


class SetSeatsTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from test_episode_sets import add_studio_set
        add_studio_set("dining", status="candidate")

    def tearDown(self):
        self.env.close()

    def test_several_seats_and_a_table_front_are_marked_on_approval(self):
        bad = self.c.post("/api/sets/dining/decide", json={"decision": "approve", "blocking": {
            "seats": [{"x": 10, "hip_y": 95, "feet_y": 90}]}})
        self.assertEqual(bad.status_code, 422, "hips must be above the feet")
        bad = self.c.post("/api/sets/dining/decide", json={"decision": "approve", "blocking": {"table_front": {"x0": 5, "y0": 50, "x1": 99, "y1": 80}}})
        self.assertEqual(bad.status_code, 422, "inside the image")
        ok = self.c.post("/api/sets/dining/decide", json={"decision": "approve", "blocking": {
            "seats": [{"x": 15, "hip_y": 70, "feet_y": 88}, {"x": 45, "hip_y": 70, "feet_y": 88}],
            "table_front": {"x0": 5, "y0": 60, "x1": 55, "y1": 80}}})
        self.assertEqual(ok.status_code, 200, ok.text)
        from oddstudio import sets
        from oddstudio.db import new_session
        with new_session() as db:
            b = sets.blocking_of(db, "dining")
            self.assertEqual(len(sets.seats_of(b)), 2)
            self.assertEqual(b["table_front"], {"x0": 5, "y0": 60, "x1": 55, "y1": 80})
            self.assertEqual(sets.usable(db)["dining"]["seats"], 2)
        self.assertEqual(sets.seats_of({"seat": {"x": 1, "hip_y": 2, "feet_y": 3}}), [{"x": 1, "hip_y": 2, "feet_y": 3}], "the old single seat still works")


if __name__ == "__main__":
    unittest.main()
