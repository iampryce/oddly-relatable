"""Audio-first Stage 2 (owner decision 2026-11-20): scenes as runs of consecutive recorded line ids (cuts only between
lines), per-line acting (expression, gesture, look_at, shot, reactions), the validator, the deterministic fallback
split, the gate that refuses dialogue edits on audio episodes, and "none" as the audio episodes' dialogue display."""
import io
import unittest
import wave

from helpers import Env

from oddstudio import analysis, providers
from oddstudio.audio_scenes import build_script, check_runs, guard_dialogue, simple_runs
from oddstudio.script_schema import ScriptError, validate_script

WORDS = [{"start": 0.10, "end": 0.30, "word": "Who"}, {"start": 0.32, "end": 0.55, "word": "took"},
         {"start": 0.57, "end": 0.70, "word": "my"}, {"start": 0.72, "end": 1.20, "word": "charger?"},
         {"start": 2.10, "end": 2.30, "word": "Not"}, {"start": 2.32, "end": 2.60, "word": "me."},
         {"start": 4.70, "end": 4.80, "word": "I"}, {"start": 4.82, "end": 5.30, "word": "swear."}]
TRANSCRIPT = {"provider": "openai", "model": "whisper-1", "language": "en", "duration": 5.6,
              "text": "Who took my charger? Not me. I swear.", "segments": [], "words": WORDS}


def L(i, start, end, speaker, text):
    return {"id": f"l{i}", "start": start, "end": end, "speaker": speaker, "text": text, "words": []}


LINES = [L(1, 0.1, 1.2, "dan", "Who took my charger?"), L(2, 2.1, 2.6, "kim", "Not me."), L(3, 4.7, 5.3, "kim", "I swear.")]


class PureTest(unittest.TestCase):
    def test_simple_split_cuts_at_long_pauses_and_caps_scene_length(self):
        self.assertEqual(simple_runs(LINES), [["l1", "l2"], ["l3"]])            # gaps 0.9 s and 2.1 s: only the 2nd cuts
        tight = [L(i, i * 1.0, i * 1.0 + 0.8, "dan", "x") for i in range(1, 15)]
        runs = simple_runs(tight, max_run=6)
        self.assertEqual([len(r) for r in runs], [6, 6, 2])
        self.assertEqual([x for r in runs for x in r], [ln["id"] for ln in tight])
        many = [L(i, i * 3.0, i * 3.0 + 0.5, "dan", "x") for i in range(1, 21)]  # 20 lines, all separated by pauses
        runs = simple_runs(many, max_scenes=12)
        self.assertEqual(len(runs), 12)
        self.assertEqual([x for r in runs for x in r], [ln["id"] for ln in many], "joined, never reordered")

    def test_runs_must_cover_every_line_once_in_order(self):
        ids = ["l1", "l2", "l3"]
        check_runs([["l1", "l2"], ["l3"]], ids)
        for bad, why in (([["l1"], ["l3"]], "missing"), ([["l1", "l2"], ["l2", "l3"]], "repeated"),
                         ([["l2", "l1"], ["l3"]], "out of order"), ([["l1", "l2", "l3"], []], "no lines"),
                         ([["l1", "l9"], ["l2", "l3"]], "unknown")):
            with self.assertRaises(ScriptError) as e:
                check_runs(bad, ids)
            self.assertIn(why, str(e.exception))

    def test_the_script_takes_its_dialogue_from_the_transcript(self):
        plan = {"title": "Charger", "hook": "POV: nobody took it 😬",
                "scenes": [{"heading": "Desk", "line_ids": ["l1", "l2"]}, {"heading": "Later", "line_ids": ["l3"]}],
                "lines": {"l1": {"expression": "annoyed", "gesture": "point", "look_at": "kim", "shot": "close", "text": "CHANGED"},
                          "l2": {"gesture": "moonwalk", "look_at": "dan", "shot": "extreme",
                                 "reactions": [{"character": "boss", "expression": "smug"}, {"character": "ghost"}]},
                          "l3": {"look_at": "nobody"}}}
        s = build_script("Ep", LINES, ["dan", "kim"], ["boss"], plan, known={"dan", "kim", "boss"})
        self.assertEqual([sc["heading"] for sc in s["scenes"]], ["Desk", "Later"])
        l1, l2 = s["scenes"][0]["lines"]
        self.assertEqual((l1["line_id"], l1["speaker"], l1["text"], l1["start"], l1["end"]), ("l1", "dan", "Who took my charger?", 0.1, 1.2))
        self.assertEqual((l1["expression"], l1["gesture"], l1["look_at"], l1["shot"]), ("annoyed", "point", "kim", "close"))
        self.assertNotIn("gesture", l2, "unknown gestures are dropped")
        self.assertEqual(l2["shot"], "wide", "an unknown shot falls back to wide, like a script-first line")
        self.assertEqual(l2["reactions"], [{"character": "boss", "expression": "smug"}], "the silent character reacts")
        self.assertNotIn("look_at", s["scenes"][1]["lines"][0])
        self.assertEqual([c["key"] for c in s["characters"]], ["dan", "kim", "boss"])
        self.assertEqual(s["hook"], "POV: nobody took it 😬")
        with self.assertRaises(ScriptError):
            build_script("Ep", LINES, ["dan", "kim"], [], {"scenes": [{"line_ids": ["l1"]}, {"line_ids": ["l3"]}]})

    def test_recorded_lines_keep_their_id_and_time_and_may_run_long(self):
        long = "word " * 50
        doc = {"title": "t", "characters": [{"key": "dan"}],
               "scenes": [{"heading": "h", "lines": [{"speaker": "dan", "text": long, "line_id": "l1", "start": 0, "end": 9.5}]}]}
        ln = validate_script(doc)["scenes"][0]["lines"][0]
        self.assertEqual((ln["line_id"], ln["start"], ln["end"]), ("l1", 0.0, 9.5))
        doc["scenes"][0]["lines"][0].pop("line_id")
        with self.assertRaises(ScriptError):
            validate_script(doc)                                 # a written line keeps the 140-character limit
        doc["scenes"][0]["lines"][0].update(text="hi", line_id="l1", end=None)
        with self.assertRaises(ScriptError):
            validate_script(doc)

    def test_guard_refuses_any_dialogue_change(self):
        s = build_script("Ep", LINES, ["dan", "kim"], [], None)
        flat = lambda sc: [dict(x) for scene in sc["scenes"] for x in scene["lines"]]
        before = flat(s)
        ok = [dict(x, expression="shocked", shot="close") for x in before]
        guard_dialogue(before, ok)
        for change in ({"text": "Who took it?"}, {"speaker": "kim"}, {"start": 0.2}, {"end": 1.0}):
            with self.assertRaises(ScriptError):
                guard_dialogue(before, [dict(before[0], **change)] + before[1:])
        with self.assertRaises(ScriptError):
            guard_dialogue(before, before[:2])
        with self.assertRaises(ScriptError):
            guard_dialogue(before, [before[1], before[0], before[2]])


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        analysis.set_test_analysis(transcriber=lambda cfg, audio: dict(TRANSCRIPT))

    def tearDown(self):
        analysis.set_test_analysis()
        providers.set_test_text_responder(None)
        self.env.close()

    def ready(self, cast=True, reuse=False):
        ep = self.c.post("/api/audio-episodes", json={"title": "Charger", "rights_confirmed": True, "rights_source": "own_recording"}).json()
        self.assertEqual(ep["dialogue_display"], "none", "audio episodes start with no dialogue on screen")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\0\0" * 8000)
        self.c.put(f"/api/episodes/{ep['id']}/audio", content=buf.getvalue(), headers={"Content-Type": "audio/wav"})
        self.env.run_jobs(["audio_transcribe"])
        eid = ep["id"]
        lines = self.c.get(f"/api/episodes/{eid}/audio").json()["lines"]
        for ln, sp in zip(lines, ["Dan", "Kim", "Kim"]):
            ln["speaker"] = sp
        self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": lines})
        if cast:
            speakers = ([{"label": "Dan", "character_key": "dan"}, {"label": "Kim", "character_key": "kim"}] if reuse else
                        [{"label": "Dan", "new": {"key": "dan", "name": "Dan"}}, {"label": "Kim", "new": {"key": "kim", "name": "Kim"}}])
            r = self.c.post(f"/api/episodes/{eid}/audio/cast", json={"speakers": speakers})
            self.assertEqual(r.status_code, 200, r.text)
        return eid

    def build(self, eid, mode="writer"):
        r = self.c.post(f"/api/episodes/{eid}/audio/scenes", json={"mode": mode})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["audio_scenes"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        return self.c.get(f"/api/episodes/{eid}").json()

    def test_the_writer_plans_scenes_and_acting_around_the_recorded_lines(self):
        seen = {}
        def writer(system, prompt):
            seen["system"], seen["prompt"] = system, prompt
            return {"title": "The Charger", "hook": "POV: it was you 😬",
                    "scenes": [{"heading": "The desk", "line_ids": ["l1", "l2"]}, {"heading": "Denial", "line_ids": ["l3"]}],
                    "lines": {"l1": {"expression": "annoyed", "look_at": "kim"}, "l3": {"gesture": "hands_on_hips"}}}
        providers.set_test_text_responder(writer)
        ep = self.build(self.ready())
        self.assertIn("never change, add, remove or reorder a line", seen["system"])
        self.assertIn("[l1 | dan | 0.1-1.2 s] Who took my charger?", seen["prompt"])
        self.assertEqual(ep["stage"], "script_review", "the owner reviews and approves it in the dashboard")
        s = ep["script"]["content"]
        self.assertEqual((s["title"], ep["script"]["source"]), ("The Charger", "audio-scenes"))
        self.assertEqual([[ln["line_id"] for ln in sc["lines"]] for sc in s["scenes"]], [["l1", "l2"], ["l3"]])
        self.assertIsNone(ep["approved_script_version"], "nothing is approved automatically")

    def test_a_plan_that_breaks_the_rules_falls_back_to_the_simple_split(self):
        providers.set_test_text_responder(lambda s, p: {"scenes": [{"line_ids": ["l1"]}, {"line_ids": ["l3"]}]})   # l2 lost
        ep = self.build(self.ready())
        s = ep["script"]["content"]
        self.assertEqual(ep["script"]["source"], "audio-simple-split")
        self.assertEqual([ln["line_id"] for sc in s["scenes"] for ln in sc["lines"]], ["l1", "l2", "l3"])
        self.assertTrue(any("simple split instead" in e["message"] for e in ep["events"]))

    def test_without_a_writer_or_on_request_the_simple_split_is_used(self):
        ep = self.build(self.ready())                     # no text provider configured
        self.assertEqual(ep["script"]["source"], "audio-simple-split")
        ep = self.build(self.ready(reuse=True), mode="simple")
        self.assertEqual([sc["heading"] for sc in ep["script"]["content"]["scenes"]], ["Scene 1", "Scene 2"])   # pause before l3

    def test_scenes_need_every_speaker_cast(self):
        eid = self.ready(cast=False)                       # labels "Dan"/"Kim" are not characters yet
        r = self.c.post(f"/api/episodes/{eid}/audio/scenes", json={"mode": "simple"})
        self.assertEqual(r.status_code, 409, r.text)

    def test_dialogue_edits_are_refused_staging_edits_allowed(self):
        eid = self.ready()
        ep = self.build(eid, mode="simple")
        s = ep["script"]["content"]
        put = lambda content: self.c.put(f"/api/episodes/{eid}/script", json={"content": content})
        staged = {**s, "scenes": [{**sc, "heading": "New heading", "lines": [{**ln, "expression": "shocked", "shot": "close"} for ln in sc["lines"]]}
                                  for sc in s["scenes"]]}
        self.assertEqual(put(staged).status_code, 200)
        for mutate in (lambda ln: {**ln, "text": "Who took it?"}, lambda ln: {**ln, "speaker": "kim"}, lambda ln: {**ln, "start": 0.5}):
            bad = {**s, "scenes": [{**s["scenes"][0], "lines": [mutate(s["scenes"][0]["lines"][0])] + s["scenes"][0]["lines"][1:]}] + s["scenes"][1:]}
            r = put(bad)
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn("comes from the audio", r.text)
        merged = {**s, "scenes": [{**s["scenes"][0], "lines": s["scenes"][0]["lines"] + s["scenes"][1]["lines"]}]}
        self.assertEqual(put(merged).status_code, 200, "moving a cut between lines is allowed")
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/script/generate", json={}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/script/regenerate-section", json={"section": "title"}).status_code, 409)
        # the storyboard keeps the recorded lines; its scene edits are guarded too
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/script/approve", json={}).status_code, 200)   # test only
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/storyboard/generate").status_code, 200)
        self.env.run_jobs(["generate_storyboard"])
        sc = self.c.get(f"/api/episodes/{eid}").json()["scenes"][0]
        self.assertEqual(sc["lines"][0]["line_id"], "l1")
        body = {k: sc[k] for k in ("heading", "location", "description", "action", "camera")}
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/scenes/{sc['id']}", json={**body, "lines": [{**sc["lines"][0], "text": "No"}] + sc["lines"][1:]}).status_code, 422)
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/scenes/{sc['id']}", json={**body, "lines": [{**sc["lines"][0], "expression": "sad"}] + sc["lines"][1:]}).status_code, 200)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/scenes/{sc['id']}/regenerate", json={}).status_code, 409)

    def test_back_to_labels_from_script_review(self):
        eid = self.ready()
        self.build(eid, mode="simple")
        r = self.c.post(f"/api/episodes/{eid}/audio/reopen-labels")
        self.assertEqual((r.status_code, r.json()["stage"]), (200, "audio_labelling"))
        self.assertEqual(self.build(eid, mode="simple")["script"]["version"], 2, "rebuilt as a new script version")


if __name__ == "__main__":
    unittest.main()
