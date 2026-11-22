"""Storyboard stills from the renderer the video uses, and scene continuity (owner request 2026-11-22, Episode 14).

1. Stills: with the studio rig animator as the motion provider, "Refresh stills" renders the scene with the acting
   renderer (the episode's own set and seats, its dialogue display) and puts a few of its frames on the sheet. Script-
   first episodes on the old pose engine keep today's stills.
2. Continuity: a cut to a close-up is the camera, not people leaving. Every scene starts with the confirmed cast seated
   as before (same seats), unless the accepted plan has someone leave; the storyboard scene lists everyone staged."""
import unittest
from pathlib import Path

from PIL import Image

from helpers import Env, sample_script

from oddstudio import acting, engine, providers
from oddstudio import video_notes as VN
from oddstudio.audio_scenes import build_script, carry_staging

CAST4 = ["uncle-mortimer", "ralph", "sidney", "winifred"]


def ep14_notes():
    """Episode 14's shape: a wide range with all four seated, then a close-up on Ralph, then wide again."""
    seat = lambda role, who: {"role": role, "pose": "seated", "who": who}
    wide = [seat("speaker", "uncle-mortimer"), seat("reactor 1", "ralph"), seat("reactor 2", "sidney"), seat("reactor 3", "winifred")]
    return [{"start": 0.0, "end": 7.9, "shot": "wide", "roles": wide},
            {"start": 7.9, "end": 9.0, "shot": "close", "roles": [seat("reactor 1", "ralph")]},
            {"start": 9.0, "end": 30.0, "shot": "wide", "roles": wide}]


LINES = [{"id": "l1", "speaker": "uncle-mortimer", "text": "I am of sound mind.", "start": 0.0, "end": 6.9},
         {"id": "l2", "speaker": "uncle-mortimer", "text": "Ralph gets the cat.", "start": 7.32, "end": 9.5},
         {"id": "l3", "speaker": "uncle-mortimer", "text": "Sidney gets nothing.", "start": 19.6, "end": 21.4}]


class ContinuityTest(unittest.TestCase):
    def build(self, actions=None):
        plan = {"title": "The Unkind Will", "scenes": [{"line_ids": ["l1"]}, {"line_ids": ["l2"]}, {"line_ids": ["l3"]}], "lines": {}}
        s = build_script("Will", LINES, ["uncle-mortimer"], ["ralph", "sidney", "winifred"], plan, known=set(CAST4),
                         notes=ep14_notes(), actions=actions)
        return [sc.get("staging") for sc in s["scenes"]]

    def test_a_close_up_does_not_take_anyone_off_stage(self):
        st = self.build()
        everyone = {k: "seated" for k in CAST4}
        self.assertEqual(st[0], everyone)
        self.assertEqual(st[1], everyone, "scene 2 starts on a close-up of Ralph: the other three stay seated")
        self.assertEqual(list(st[1]), CAST4, "the same seat order as scene 1 (nobody changes seats at a cut)")
        self.assertEqual(st[2], everyone)

    def test_only_an_accepted_exit_takes_someone_out_and_an_enter_brings_them_back(self):
        st = self.build([{"t": 7.0, "type": "exit", "character": "sidney"}, {"t": 15.0, "type": "enter", "character": "sidney"}])
        self.assertNotIn("sidney", st[1], "the plan shows Sidney leaving before scene 2")
        self.assertEqual(st[1], {"uncle-mortimer": "seated", "ralph": "seated", "winifred": "seated"})
        self.assertEqual(st[2]["sidney"], "seated", "back for scene 3 (the wide notes seat Sidney)")

    def test_a_close_up_first_line_still_stages_everyone_in_scene_one(self):
        scenes = [{"staging": {"ralph": "seated"}}, {}]
        notes = [{"start": 0.0, "end": 2.0, "roles": [{"role": "reactor 1", "pose": "seated", "who": "ralph"}]},
                 {"start": 2.0, "end": 9.0, "roles": [{"role": "speaker", "pose": "seated", "who": "uncle-mortimer"},
                                                      {"role": "reactor 1", "pose": "seated", "who": "ralph"},
                                                      {"role": "reactor 2", "pose": "standing", "who": "sidney"}]}]
        lines = {"a": {"id": "a", "speaker": "uncle-mortimer", "start": 0.5, "end": 1.5},
                 "b": {"id": "b", "speaker": "uncle-mortimer", "start": 3.0, "end": 5.0},
                 "c": {"id": "c", "speaker": "uncle-mortimer", "start": 10.0, "end": 11.0}}
        carry_staging(scenes, [["a", "b"], ["c"]], lines, notes, ["uncle-mortimer"], ["ralph", "sidney"], [])
        self.assertEqual(scenes[0]["staging"], {"ralph": "seated", "uncle-mortimer": "seated", "sidney": "standing"})
        self.assertEqual(scenes[1]["staging"], scenes[0]["staging"])


class StoryboardCharactersTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def test_everyone_staged_is_in_the_storyboard_scene(self):
        script = sample_script()
        script["characters"].append({"key": "ralph", "role": "silent"})
        script["scenes"][1]["staging"] = {"character-01": "seated", "ralph": "seated"}
        from oddstudio.db import new_session
        from oddstudio.models import Character
        with new_session() as s:
            s.add(Character(key="ralph", name="Ralph", scope="recurring", art_status="none"))
            s.commit()
        providers.set_test_text_responder(lambda sy, p: script)
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        self.c.post(f"/api/episodes/{eid}/script/approve", json={})     # test step
        self.c.post(f"/api/episodes/{eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        scenes = self.c.get(f"/api/episodes/{eid}").json()["scenes"]
        self.assertIn("ralph", scenes[1]["characters"], "staged but never spoken to: still in the scene (seated, not off stage)")


class StillsPathTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.calls = []
        self.real_render, self.real_preview = acting.render, engine.preview

        def fake_render(ctx, ep, refs, clips, chars, folder, end_card=None, stills=0):
            self.calls.append(("acting", refs, stills, ep.set_id))
            folder.mkdir(parents=True, exist_ok=True)
            out = []
            for k in range(3):
                f = folder / f"still-{k}.png"
                Image.new("RGB", (1080, 1920), (40 * k, 90, 160)).save(f)
                out.append({"file": str(f), "t": 0.4 + k})
            return None, None, {"stills": out, "render_seconds": 1.0}

        def fake_preview(story, folder, log):
            self.calls.append(("pose engine", story["scenes"][0]["environment"]))
            folder.mkdir(parents=True, exist_ok=True)
            f = folder / "sheet.png"
            Image.new("RGB", (300, 200), (200, 100, 50)).save(f)
            return f
        acting.render, engine.preview = fake_render, fake_preview

    def tearDown(self):
        acting.render, engine.preview = self.real_render, self.real_preview
        providers.set_test_text_responder(None)
        self.env.close()

    def episode(self):
        providers.set_test_text_responder(lambda s, p: sample_script())
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        self.c.post(f"/api/episodes/{eid}/script/approve", json={})
        self.c.post(f"/api/episodes/{eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        return eid, self.c.get(f"/api/episodes/{eid}").json()["scenes"]

    def refresh(self, eid, scene):
        self.calls.clear()
        r = self.c.post(f"/api/episodes/{eid}/scenes/{scene['id']}/reference")
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["scene_reference"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        return self.c.get(f"/api/episodes/{eid}").json()["scenes"]

    def test_the_acting_renderer_makes_the_stills_when_it_is_the_motion_provider(self):
        eid, scenes = self.episode()
        self.c.put("/api/settings/motion", json={"provider": "procedural-rig"})
        scenes = self.refresh(eid, scenes[0])
        self.assertEqual(self.calls[0][0], "acting", self.calls)
        self.assertEqual(self.calls[0][2], 6, "a few frames for the sheet")
        self.assertEqual(self.calls[0][1], [[(scenes[0]["id"], i) for i in range(len(scenes[0]["lines"]))]], "the whole scene")
        ref = scenes[0]["reference"]
        self.assertIn("acting renderer", ref["label"])
        self.assertTrue(ref["url"])

    def test_script_first_episodes_on_the_old_engine_keep_todays_stills(self):
        eid, scenes = self.episode()
        self.c.put("/api/settings/motion", json={"provider": "none"})
        self.refresh(eid, scenes[0])
        self.assertEqual(self.calls[0][0], "pose engine", self.calls)


class StillTimesTest(unittest.TestCase):
    def test_the_first_line_just_after_it_starts_then_spread_over_the_scene(self):
        lines = [{"start": 10.0 + 3 * k, "end": 12.0 + 3 * k} for k in range(10)]
        t = acting.still_times(lines, 6)
        self.assertEqual(len(t), 6)
        self.assertEqual(t[0], 10.4)
        self.assertEqual(t[-1], 38.0, "the last line's middle")
        self.assertEqual(acting.still_times(lines[:2], 6), [10.4, 14.0])
        self.assertEqual(acting.still_times([], 6), [0.5])


if __name__ == "__main__":
    unittest.main()
