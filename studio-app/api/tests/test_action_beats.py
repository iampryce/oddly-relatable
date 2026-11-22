"""Action beats and the video's people (PR 8 feat/action-beats, owner decisions 2026-11-21).

- Beats derived from the v2 per-person frames (sit, stand, walk, lean, turn, nod, shake, phone, gestures; lying and
  kneeling marked "will be skipped"), editable, acted only for people the owner confirmed (person map = a suggestion
  from timing, never applied by itself).
- One room seen from two angles (shot / reverse shot) is one setting with two views; short setting flips are smoothed
  to the room's setting and the unsmoothed value stays as "was".
- The speaker comes from the audio timing (the labelled speaker's line) through the confirmed people, in preference
  to the vision "talking" flag, which is used only when informative.
- Two views -> two linked set candidates (same description + a view line), and a cut to the other side switches plates
  and flips the marks, only when both view sets exist; single-view episodes are unchanged.
- The estimate is calibrated (OpenAI x1.7); a provider hint appears when emotions are nearly all neutral."""
import unittest

from helpers import Env, fake_pose_image
from test_episode_sets import add_studio_set

from oddstudio import beats as BT
from oddstudio import notes_v2 as NV
from oddstudio import providers

LINES = [{"id": "l1", "start": 0.0, "end": 9.8, "text": "I leave everything to the cat.", "speaker": "mortimer", "words": []},
         {"id": "l2", "start": 10.2, "end": 19.8, "text": "The cat?", "speaker": "ralph", "words": []},
         {"id": "l3", "start": 20.2, "end": 29.8, "text": "And the house.", "speaker": "mortimer", "words": []}]


def frame(t, view, setting, furniture, mort, ralph, talking_all=True):
    """Shot / reverse shot: the speaker's side shows Mortimer, the family's side shows Ralph (positions flip)."""
    return {"t": t, "shot": "medium", "setting": setting, "furniture": furniture, "view": view,
            "people": [{"person": 1, "talking": talking_all, **mort}, {"person": 2, "talking": talking_all, **ralph}]}


def will_frames():
    out = []
    for i in range(30):
        t = i + 0.5
        main = (i // 4) % 2 == 0           # the camera cuts between the two sides every 4 s
        mort = {"position": "left" if main else "right", "pose": "seated", "facing": "person 2"}
        ralph = {"position": "right" if main else "left", "pose": "seated" if i < 16 else "standing", "facing": "person 1",
                 "emotion": "neutral", **({"gesture": "nod"} if i in (5, 6) else {})}
        if i >= 25:
            ralph["gesture"] = "kneeling" if False else ralph.get("gesture", "none")
        out.append(frame(t, "main side" if main else "reverse side", "office" if main else "meeting room",
                         "desk" if main else "long table", mort, ralph))
    return out


class DeriveTest(unittest.TestCase):
    def test_beats_from_frames(self):
        fr = [{"t": 0.5, "people": [{"person": 1, "pose": "standing", "position": "left", "facing": "camera"}]},
              {"t": 1.5, "people": [{"person": 1, "pose": "standing", "position": "center", "facing": "person 2", "gesture": "nod"},
                                    {"person": 2, "pose": "standing"}]},
              {"t": 2.5, "people": [{"person": 1, "pose": "seated", "position": "center", "facing": "person 2", "gesture": "nod"},
                                    {"person": 2, "pose": "kneeling", "gesture": "phone_to_ear"}]},
              {"t": 3.5, "people": [{"person": 1, "pose": "standing", "position": "center", "gesture": "shrug"},
                                    {"person": 2, "pose": "kneeling", "gesture": "phone_to_ear"}]}]
        got = [(b["person"], b["t"], b["type"], b.get("target") or b.get("gesture")) for b in BT.derive(fr, 1.0)]
        self.assertEqual(got, [(1, 1.0, "turn_to", "person 2"), (1, 1.0, "walk", "center"), (2, 1.0, "enter", None),
                               (1, 1.5, "nod", None), (1, 2.0, "sit_down", None), (2, 2.0, "kneel", None),
                               (2, 2.5, "phone_to_ear", None), (1, 3.0, "stand_up", None), (1, 3.5, "gesture", "shrug")])
        self.assertIn("[will be skipped]", BT.describe({"person": 2, "t": 2.0, "type": "kneel"}, {}))

    def test_one_room_two_views_stays_one_setting(self):
        raw, _ = NV.to_ranges(will_frames(), 30.0, 1.0)
        self.assertEqual({r["setting"] for r in raw}, {"office", "meeting room"}, "the vision notes flip between the angles")
        sm = BT.smooth(raw)
        self.assertEqual({r["setting"] for r in sm}, {"office"}, "one setting for the room")
        self.assertEqual({r["furniture"] for r in sm}, {"desk"})
        self.assertEqual({r["view"] for r in sm}, {"main side", "reverse side"}, "two views of it")
        self.assertTrue(BT.two_views(sm))
        long = [{"start": 0, "end": 30, "setting": "office"}, {"start": 30, "end": 60, "setting": "kitchen"}]
        self.assertEqual([r["setting"] for r in BT.smooth(long)], ["office", "kitchen"], "a real move of 20 s or more stays")

    def test_speaker_from_audio_timing_over_an_uninformative_talking_flag(self):
        frames = will_frames()
        self.assertFalse(BT.talking_informative(frames), "everyone 'talking' in every frame says nothing")
        self.assertEqual(BT.suggest_map(frames, LINES), {"mortimer": None, "ralph": None}, "no guess from noise")
        self.assertEqual(set(BT.speakers_by_frame(frames, LINES, {}).values()), {None})
        spk = BT.speakers_by_frame(frames, LINES, {"mortimer": 1, "ralph": 2})
        self.assertEqual((spk[5.5], spk[12.5], spk[25.5]), (1, 2, 1), "the labelled speaker's lines decide")
        one = [{**f, "people": [{**p, "talking": p["person"] == (1 if f["t"] < 10 or f["t"] > 20 else 2)} for p in f["people"]]}
               for f in frames]
        self.assertEqual(BT.suggest_map(one, LINES), {"mortimer": 1, "ralph": 2}, "an informative flag gives a suggestion")

    def test_calibration_and_the_provider_hint(self):
        base = NV.estimate(60, "short", "anthropic")["usd"]
        self.assertEqual(NV.CALIBRATION["openai"], 1.7)
        self.assertGreater(NV.estimate(60, "short", "openai")["usd"], 0.02, "OpenAI raised to the measured level")
        self.assertGreater(base, 0)
        q = NV.quality(will_frames(), 30, 0, [{"provider": "openai", "input_tokens": 1, "output_tokens": 1}], 0.03, [])
        self.assertIn("Anthropic vision provider", q["hint"])
        self.assertEqual(q["views"], ["main side", "reverse side"])
        q2 = NV.quality(will_frames(), 30, 0, [{"provider": "anthropic", "input_tokens": 1, "output_tokens": 1}], 0.03, [])
        self.assertEqual(q2["hint"], "")


class EpisodeTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, Episode
        notes = {"version": 2, "people_frames": will_frames(), "length": 30.0, "frames": 30, "ranges": []}
        with new_session() as s:
            for k in ("mortimer", "ralph"):
                s.add(Character(key=k, name=k.title(), scope="episode", art_status="none"))
            ep = Episode(title="The Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": LINES, "video_notes": BT.rebuild(notes, LINES, {})})
            s.add(ep)
            s.commit()
            self.eid = ep.id

    def tearDown(self):
        providers.set_test_image(None)
        self.env.close()

    def people(self):
        return self.c.get(f"/api/episodes/{self.eid}/people").json()

    def build(self):
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/reference-plan/accept").status_code, 200)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/audio/scenes", json={"mode": "simple"}).status_code, 200)
        ran = self.env.run_jobs(["audio_scenes"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        return self.c.get(f"/api/episodes/{self.eid}").json()["script"]["content"]["scenes"]

    def test_the_person_map_is_a_suggestion_until_confirmed(self):
        p = self.people()
        self.assertEqual([x["person"] for x in p["people"]], [1, 2])
        self.assertEqual(p["map"], {}, "nothing applied by itself")
        self.assertFalse(p["talking_informative"])
        self.assertTrue(p["two_views"])
        self.assertTrue(any("nods" in b["text"] for b in p["beats"]))
        bad = self.c.put(f"/api/episodes/{self.eid}/people", json={"map": {"mortimer": 1, "ralph": 1}})
        self.assertEqual(bad.status_code, 422)
        r = self.c.put(f"/api/episodes/{self.eid}/people", json={"map": {"mortimer": 1, "ralph": 2}}).json()
        self.assertTrue(r["rebuilt"])
        self.assertTrue(any(b["text"].startswith("Ralph stands up") for b in r["beats"]))

    def test_the_plan_shows_view_and_movement_with_toggles(self):
        self.c.put(f"/api/episodes/{self.eid}/people", json={"map": {"mortimer": 1, "ralph": 2}})
        plan = self.c.get(f"/api/episodes/{self.eid}/reference-plan").json()
        first = plan["ranges"][0]["items"]
        self.assertEqual(first["view"]["value"], "main side")
        self.assertIn("one room seen from two sides", first["view"]["note"])
        self.assertEqual(first["set"]["value"], "office, desk")
        rev = plan["ranges"][1]["items"]["set"]
        self.assertEqual((rev["value"], rev["original"], rev["edited"]), ("office, desk", "meeting room, long table", True),
                         "smoothed, with the unsmoothed value as was")
        moves = [r["items"]["movement"]["value"] for r in plan["ranges"]]
        self.assertTrue(any("Ralph stands up" in m for m in moves), moves)

    def test_beats_become_actions_only_for_confirmed_people_and_ignored_movement_is_left_out(self):
        scenes = self.build()
        self.assertFalse(any(s.get("actions") for s in scenes), "no confirmed people: nothing acted")
        self.c.put(f"/api/episodes/{self.eid}/people", json={"map": {"mortimer": 1, "ralph": 2}})
        scenes = self.build()
        acts = [a for s in scenes for a in s.get("actions", [])]
        self.assertIn({"t": 16.0, "character": "ralph", "type": "stand_up"}, acts)
        self.assertIn({"t": 5.5, "character": "ralph", "type": "nod"}, acts)
        self.assertFalse(any(a["type"] == "walk" for a in acts), "a cut to the other side is not a walk")
        self.assertTrue(all(a["type"] in BT.SUPPORTED for a in acts))
        self.assertEqual([ln["text"] for s in scenes for ln in s["lines"]], [ln["text"] for ln in LINES], "dialogue untouched")
        plan = self.c.get(f"/api/episodes/{self.eid}/reference-plan").json()
        ign = [f"{r['index']}:movement" for r in plan["ranges"]]
        self.c.put(f"/api/episodes/{self.eid}/reference-plan", json={"ignored": ign})
        self.assertFalse(any(s.get("actions") for s in self.build()))

    def test_the_owner_edits_beats_with_was_values(self):
        p = self.people()
        beats = [b for b in p["beats"] if b["type"] != "nod"] + [{"person": 1, "t": 3.0, "type": "lean_in"}]
        r = self.c.put(f"/api/episodes/{self.eid}/beats", json={"beats": beats})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["beats_edited"])
        self.assertFalse(any(b["type"] == "nod" for b in r.json()["beats"]))
        bad = self.c.put(f"/api/episodes/{self.eid}/beats", json={"beats": [{"person": 1, "t": 3.0, "type": "moonwalk"}]})
        self.assertEqual(bad.status_code, 422)

    def test_two_views_two_linked_sets_and_a_plate_switch_with_a_flip(self):
        add_studio_set("office", description="a small office")
        self.c.put("/api/settings/image", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})
        prompts = []
        providers.set_test_image(lambda prompt, out, ref: (prompts.append(prompt), fake_pose_image(prompt, out, ref))[1])
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            s.get(Episode, self.eid).set_id = "office"
            s.commit()
        text = "An original office with a desk, daytime, 2 people seated facing each other."
        v = self.c.put(f"/api/episodes/{self.eid}/set-proposal", json={"text": text}).json()
        self.assertTrue(v["two_views"])
        self.assertEqual(v["two_cost"], "2 images, about $0.10-0.40")
        from oddstudio import queue
        pushed = []
        real = queue.redis_client
        queue.redis_client = lambda: type("R", (), {"lpush": lambda self, k, v: pushed.append(v)})()
        try:
            g = self.c.post(f"/api/episodes/{self.eid}/set-proposal/generate", json={"text": text, "views": True}).json()
        finally:
            queue.redis_client = real
        self.assertEqual(pushed, [x["job"]["id"] for x in g["sets"]], "both sides' jobs reach the worker queue")
        self.assertEqual([x["view"] for x in g["sets"]], ["main side", "reverse side"])
        self.assertEqual([x["prompt"] for x in g["sets"]], [v["view_prompts"]["main side"], v["view_prompts"]["reverse side"]])
        self.env.run_jobs(["set_candidate"])
        self.assertEqual(prompts, [x["prompt"] for x in g["sets"]], "exactly the prompts shown")
        sets = {s["id"]: s for s in self.c.get("/api/sets").json()["sets"]}
        a, b = (sets[x["set_id"]] for x in g["sets"])
        self.assertEqual((a["view"], b["view"], a["room"], b["room"], a["status"], b["status"]),
                         ("main side", "reverse side", a["id"], a["id"], "candidate", "candidate"), "linked, both await approval")
        # with only the main side's set, nothing switches
        self.assertTrue(all("set" not in s for s in self.build()))
        for x in g["sets"]:
            self.assertEqual(self.c.post(f"/api/sets/{x['set_id']}/decide", json={"decision": "approve"}).status_code, 200)  # test only
        self.c.put(f"/api/episodes/{self.eid}/scene-sets", json={"set_ids": [a["id"], b["id"]]})
        scenes = self.build()
        self.assertGreater(len(scenes), len(LINES) - 1)
        self.assertIn(b["id"], [s.get("set") for s in scenes], "a cut to the other side switches to its set")
        from oddstudio import scene_sets
        with new_session() as s:
            self.assertTrue(scene_sets.is_reverse(s, b["id"]))
            self.assertFalse(scene_sets.is_reverse(s, a["id"]))


if __name__ == "__main__":
    unittest.main()
