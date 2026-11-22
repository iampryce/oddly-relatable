"""Rebuild scenes from audio (owner request 2026-11-22, Episode 14): after the script was approved, build the scenes
again from the recording so later fixes (scene continuity) apply. Allowed at script approved, storyboard review and
storyboard approved only. The preview says what is discarded and what the AI writer costs; nothing changes without
confirm. It discards the storyboard and the script approval only; poses, sets, the episode's set, the Reference plan
and its acceptance, the recording and the cast stay. Nothing is approved for the owner."""
import unittest

from helpers import Env
from test_episode_sets import add_studio_set
from test_seating_and_plan import LINES, RAW

from oddstudio import video_notes as VN


class RebuildScenesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset, Episode
        add_studio_set("office", description="a small office", kept=True)
        ranges, _ = VN.clean_notes(RAW, 5.0)
        with new_session() as s:
            for k in ("mortimer", "winnie", "ralph"):
                c = Character(key=k, name=k.title(), scope="episode", art_status="approved")
                s.add(c)
                s.flush()
                a = CharacterAsset(character_id=c.id, kind="pose", expression="neutral", storage_key=f"characters/{k}/n.png",
                                   width=10, height=10, status="approved")
                s.add(a)
                s.flush()
                c.expressions = {"neutral": f"p{a.id}"}
            ep = Episode(title="The Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True, set_id="office",
                         audio_transcript={"lines": LINES, "silent_cast": [{"name": "Ralph", "character_key": "ralph"}],
                                           "video_notes": {"ranges": ranges, "frames": 2, "redacted": 0, "length": 5.0}})
            s.add(ep)
            s.commit()
            self.eid = ep.id
        self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept")          # test step (the owner accepts)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": "simple"}).status_code, 200)
        self.env.run_jobs(["audio_scenes"])

    def tearDown(self):
        self.env.close()

    def ep(self):
        return self.c.get(f"/api/episodes/{self.eid}").json()

    def snapshot(self):
        from oddstudio import sets
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset, Episode
        with new_session() as s:
            ep = s.get(Episode, self.eid)
            return {"poses": sorted((a.id, a.status) for a in s.query(CharacterAsset).all()),
                    "sets": {k: r.get("status") for k, r in sets.records(s).items()}, "set_id": ep.set_id,
                    "plan": (ep.audio_transcript.get("reference_plan") or {}).get("accepted"),
                    "lines": ep.audio_transcript["lines"], "silent": ep.audio_transcript["silent_cast"]}

    def to_storyboard(self):
        self.c.post(f"/api/episodes/{self.eid}/script/approve", json={})       # test step (the owner approves)
        self.c.post(f"/api/episodes/{self.eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        self.assertEqual(self.ep()["stage"], "storyboard_review")

    def test_preview_changes_nothing_then_confirm_rebuilds_and_keeps_everything_else(self):
        self.to_storyboard()
        before = self.snapshot()
        v1 = self.ep()["script_version"]
        p = self.c.get(f"/api/episodes/{self.eid}/audio/rebuild-scenes").json()
        self.assertEqual(p["discards"]["storyboard_scenes"], len(self.ep()["scenes"]))
        self.assertIn("approval of script v1", p["discards"]["script_approval"])
        self.assertIn("poses and their approvals", p["keeps"])
        self.assertIn("the Reference plan and its acceptance", p["keeps"])
        self.assertEqual(p["cost"]["writer"]["provider"], "none", "no text provider here: the writer path is free")
        r = self.c.post(f"/api/episodes/{self.eid}/audio/rebuild-scenes", json={"mode": "simple"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("job", r.json(), "without confirm: the preview only")
        self.assertEqual(self.ep()["stage"], "storyboard_review")
        self.assertTrue(self.ep()["scenes"], "nothing discarded without confirm")
        r = self.c.post(f"/api/episodes/{self.eid}/audio/rebuild-scenes", json={"mode": "simple", "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["job"]["kind"], "audio_scenes")
        e = self.ep()
        self.assertEqual((e["stage"], e["scenes"]), ("script_generating", []), "the storyboard is discarded")
        ran = self.env.run_jobs(["audio_scenes"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        e = self.ep()
        self.assertEqual(e["stage"], "script_review", "back to script review: the new script needs the owner's approval")
        self.assertEqual(e["script_version"], v1 + 1, "a new script version; the old one stays in the history")
        self.assertEqual(self.snapshot(), before, "poses, sets, the episode's set, the plan acceptance, lines and cast untouched")

    def test_allowed_only_after_the_script_was_approved_and_before_production(self):
        self.assertEqual(self.ep()["stage"], "script_review")
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/audio/rebuild-scenes").status_code, 409,
                         "in script review the ordinary build is used")
        self.c.post(f"/api/episodes/{self.eid}/script/approve", json={})
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/audio/rebuild-scenes").status_code, 200, "script approved")
        self.c.post(f"/api/episodes/{self.eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/audio/rebuild-scenes").status_code, 200, "storyboard review")
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        for stage, ok in (("storyboard_approved", 200), ("producing", 409), ("video_review", 409), ("published", 409)):
            with new_session() as s:
                s.get(Episode, self.eid).stage = stage
                s.commit()
            r = self.c.post(f"/api/episodes/{self.eid}/audio/rebuild-scenes", json={"mode": "simple"})
            self.assertEqual(r.status_code, ok, stage)

    def test_a_plan_changed_since_acceptance_must_be_accepted_again_first(self):
        self.to_storyboard()
        self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ["0:shot"]})   # withdraws the acceptance
        r = self.c.post(f"/api/episodes/{self.eid}/audio/rebuild-scenes", json={"mode": "simple", "confirm": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("accept the Reference plan first", r.text)
        self.assertTrue(self.ep()["scenes"], "nothing discarded")


if __name__ == "__main__":
    unittest.main()
