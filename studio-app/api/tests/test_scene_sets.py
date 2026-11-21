"""Per-scene sets (owner decision 2026-11-21): a story that moves location changes set at a cut, only to one of the
episode's sets; the simple split follows the accepted notes' setting changes, the writer chooses from the list, an
unknown set keeps the previous scene's set (logged), and a scene whose set is withdrawn blocks production with the
scene named."""
import unittest

from helpers import Env, sample_script
from test_episode_sets import add_studio_set

from oddstudio import providers
from oddstudio import video_notes as VN
from oddstudio.scene_sets import continuity

LINES = [{"id": "l1", "start": 0.2, "end": 2.0, "text": "Meeting starts now.", "speaker": "mortimer", "words": []},
         {"id": "l2", "start": 4.5, "end": 6.0, "text": "Anyone hungry?", "speaker": "winnie", "words": []},
         {"id": "l3", "start": 9.0, "end": 10.5, "text": "Back to work.", "speaker": "mortimer", "words": []}]
RAW = {"ranges": [{"start": 0, "end": 3, "setting": "office", "roles": [{"role": "speaker", "pose": "seated"}]},
                  {"start": 4, "end": 7, "setting": "kitchen", "roles": [{"role": "speaker", "pose": "standing"}]},
                  {"start": 8.5, "end": 11, "setting": "office", "roles": [{"role": "speaker", "pose": "standing"}]}]}


class ContinuityTest(unittest.TestCase):
    def test_unknown_sets_keep_the_previous_scene_set(self):
        scenes = [{"id": "s1", "set": "office"}, {"id": "s2", "set": "moon"}, {"id": "s3"}, {"id": "s4", "set": "kitchen"}]
        notes = continuity(scenes, ["office", "kitchen"])
        self.assertEqual([s.get("set") for s in scenes], ["office", "office", None, "kitchen"])
        self.assertEqual(len(notes), 1)
        self.assertIn("'moon' is not one of this episode's sets", notes[0])


class SceneSetsTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        add_studio_set("office", description="a small office, daytime")
        add_studio_set("kitchen", description="a narrow kitchen")
        add_studio_set("garage", status="candidate")
        from oddstudio.db import new_session
        from oddstudio.models import Character, Episode
        ranges, _ = VN.clean_notes(RAW, 12.0)
        with new_session() as s:
            for k in ("mortimer", "winnie"):
                s.add(Character(key=k, name=k.title(), scope="episode", art_status="none"))
            ep = Episode(title="Office Day", stage="audio_labelling", source="audio", audio_rights_confirmed=True, set_id="office",
                         audio_transcript={"lines": LINES, "video_notes": {"ranges": ranges, "length": 12.0}})
            s.add(ep)
            s.commit()
            self.eid = ep.id

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def build(self, mode="simple"):
        self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept")
        r = self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": mode})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["audio_scenes"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        return self.c.get(f"/api/episodes/{self.eid}").json()["script"]["content"]["scenes"]

    def test_only_approved_sets_for_scene_changes(self):
        r = self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": ["garage"]})
        self.assertEqual(r.status_code, 422)
        r = self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": ["kitchen", "office"]})
        self.assertEqual(r.json(), {"set_id": "office", "scene_set_ids": ["kitchen"]})

    def test_one_set_episodes_have_no_scene_sets(self):
        self.assertTrue(all("set" not in s for s in self.build()), "without extra sets every scene uses the episode's set")

    def test_the_simple_split_follows_the_notes_setting_changes(self):
        self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": ["kitchen"]})
        scenes = self.build()
        self.assertEqual(len(scenes), 3)
        self.assertEqual([s.get("set") for s in scenes], [None, "kitchen", None],
                         "the episode's set (office), the kitchen when the notes move there, back to the episode's set")

    def test_ignoring_the_set_items_keeps_one_set(self):
        self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": ["kitchen"]})
        self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ["0:set", "1:set", "2:set"]})
        self.assertTrue(all("set" not in s for s in self.build()))

    def test_the_writer_chooses_from_the_list_and_unknown_sets_are_logged(self):
        self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": ["kitchen"]})
        seen = []

        def writer(system, prompt):
            seen.append(prompt)
            return {"title": "Office Day", "scenes": [{"heading": "Meeting", "set": "office", "line_ids": ["l1"]},
                                                      {"heading": "Snack", "set": "kitchen", "line_ids": ["l2"]},
                                                      {"heading": "Back", "set": "beach", "line_ids": ["l3"]}],
                    "lines": {}}
        providers.set_test_text_responder(writer)
        scenes = self.build("writer")
        self.assertIn("SETS for this episode", seen[0])
        self.assertIn("- kitchen: Kitchen. a narrow kitchen", seen[0])
        self.assertEqual([s.get("set") for s in scenes], ["office", "kitchen", "kitchen"])
        events = [e["message"] for e in self.c.get(f"/api/episodes/{self.eid}").json()["events"]]
        self.assertTrue(any("'beach' is not one of this episode's sets" in m for m in events), events)

    def test_a_withdrawn_scene_set_blocks_production_with_the_scene_named(self):
        self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": ["kitchen"]})
        self.build()
        from oddstudio import scene_sets, sets
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        from oddstudio.tasks import save_script  # noqa: F401  (the storyboard is made by the usual job)
        self.c.post(f"/api/episodes/{self.eid}/script/approve", json={})   # test only
        self.c.post(f"/api/episodes/{self.eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        sc = self.c.get(f"/api/episodes/{self.eid}").json()["scenes"]
        self.assertEqual([s["set_id"] for s in sc], [None, "kitchen", None], "the storyboard keeps each scene's set")
        r = self.c.put(f"/api/episodes/{self.eid}/scenes/{sc[0]['id']}/set", json={"set_id": "garage"})
        self.assertEqual(r.status_code, 422, "only the episode's sets")
        with new_session() as db:
            recs = sets.records(db)
            recs["kitchen"]["status"] = "rejected"
            sets.save(db, recs)
            ep = db.get(Episode, self.eid)
            bad = scene_sets.problems(db, ep, ep.scenes)
        self.assertEqual(len(bad), 1)
        self.assertIn("scene 2", bad[0])
        self.assertIn("not an approved set any more", bad[0])


if __name__ == "__main__":
    unittest.main()
