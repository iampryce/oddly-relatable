"""Long-form production (D-L1 to D-L5): two-pass writing with outline approval, quality and duration rules, segment
planning, joining, independent segment retries, selective regeneration and the complete workflow through the REAL
engine. The writer, voice and failure injection are test stand-ins; segmentation, rendering, joining and checks are real."""
import json
import os
import subprocess
import unittest
from pathlib import Path

from helpers import Env, fake_voice

from oddstudio import longform, providers
from oddstudio.script_schema import ScriptError

HAS_FFMPEG = bool(os.environ.get("FFMPEG") and os.environ.get("FFPROBE"))
SCENES_PER_ACT = 5


def outline_doc(scene_seconds=20, jokes=None):
    acts = []
    for a in range(1, 4):
        acts.append({"title": ["Setup", "Escalation", "Payoff"][a - 1], "purpose": f"act {a} purpose",
                     "scenes": [{"id": f"a{a}s{i}", "heading": f"Act {a} scene {i}", "summary": f"Something new happens ({a}.{i})",
                                 "beats": [f"development {a}.{i}"], "jokes": (jokes or {}).get(f"a{a}s{i}", [f"joke {a}.{i}"]),
                                 "characters": ["character-01"], "location": "living-room-empty-03", "est_seconds": scene_seconds}
                                for i in range(1, SCENES_PER_ACT + 1)]})
    return {"title": "The Long Voice Note", "logline": "One voice note, three acts of panic.", "premise": "p", "twist": "t", "ending": "e",
            "quality_notes": "Each act escalates.", "characters": [{"key": "character-01", "role": "lead"}], "acts": acts}


def act_answer(prompt):
    act = int(prompt.split("Write ACT ")[1].split(" ")[0])
    return {"scenes": [{"id": f"a{act}s{i}", "heading": f"Act {act} scene {i}", "location": "living-room-empty-03", "description": "d",
                        "action": "a", "camera": "c",
                        "lines": [{"speaker": "character-01", "text": f"Act {act}, scene {i}: something new.", "expression": "worried", "shot": "wide", "duration": 1.6},
                                  {"speaker": "character-01", "text": f"Reaction {act}.{i}!", "expression": "shocked", "shot": "close", "duration": 1.4}]}
                       for i in range(1, SCENES_PER_ACT + 1)]}


def writer(system, prompt):
    if "THREE-ACT OUTLINE" in prompt:
        return outline_doc()
    if "Write ACT " in prompt:
        return act_answer(prompt)
    raise AssertionError("unexpected prompt")


class LongFormUnitTest(unittest.TestCase):
    def test_outline_rules(self):
        ok = longform.validate_outline(outline_doc(), {"character-01"})
        self.assertEqual(ok["runtime_estimate_seconds"], 300)
        self.assertEqual(longform.outline_warnings(ok), [])
        two = outline_doc(); two["acts"] = two["acts"][:2]
        with self.assertRaisesRegex(ScriptError, "exactly three acts"):
            longform.validate_outline(two, {"character-01"})
        with self.assertRaisesRegex(ScriptError, "over the 7½-minute cap"):
            longform.validate_outline(outline_doc(scene_seconds=31), {"character-01"})
        no_beats = outline_doc(); no_beats["acts"][0]["scenes"][0]["beats"] = []
        with self.assertRaisesRegex(ScriptError, "at least one story beat"):
            longform.validate_outline(no_beats, {"character-01"})
        short = longform.validate_outline(outline_doc(scene_seconds=12), {"character-01"})
        self.assertIn("Do not pad it", longform.outline_warnings(short)[0], "under target: flagged for the owner, never padded")
        rep = longform.validate_outline(outline_doc(jokes={"a1s1": ["The Spreadsheet!"], "a3s2": ["the spreadsheet"]}), {"character-01"})
        self.assertTrue(any("Joke repeated in scenes a1s1, a3s2" in w for w in longform.outline_warnings(rep)))

    def test_segment_planning(self):
        scenes = [{"scene": f"s{i}", "duration": 20.0, "lines": [{"start": 0, "duration": 10}, {"start": 10, "duration": 10}]} for i in range(5)]
        plan = longform.plan_segments(scenes)
        self.assertEqual([[p["scene"] for p in seg] for seg in plan], [["s0", "s1"], ["s2", "s3"], ["s4"]])
        self.assertTrue(all(sum(p["duration"] for p in seg) <= longform.SEGMENT_MAX for seg in plan))
        # A scene longer than a segment is split between lines, never inside a line.
        long_scene = [{"scene": "big", "duration": 100.0, "lines": [{"start": 20 * k, "duration": 20} for k in range(5)]}]
        parts = [p for seg in longform.plan_segments(long_scene) for p in seg]
        self.assertEqual([p["lines"] for p in parts], [[0, 2], [2, 4], [4, 5]])
        self.assertEqual(sum(p["duration"] for p in parts), 100.0)
        with self.assertRaisesRegex(ValueError, "single line lasts over"):
            longform.plan_segments([{"scene": "x", "duration": 70, "lines": [{"start": 0, "duration": 70}]}])


@unittest.skipUnless(HAS_FFMPEG, "set FFMPEG and FFPROBE")
class JoinTest(unittest.TestCase):
    def clip(self, folder, name, seconds, size="360x640", freq=440):
        ff = os.environ["FFMPEG"]
        mp4, wav = folder / f"{name}.mp4", folder / f"{name}.wav"
        subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=48000",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(mp4)], check=True)
        subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=48000",
                        "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
        return mp4, wav

    def test_join_checks(self):
        env = Env()
        try:
            folder = env.tmp / "join"
            folder.mkdir()
            parts = [self.clip(folder, f"s{i}", 2 + i) for i in range(3)]
            out = folder / "joined.mp4"
            checks = longform.join_segments([p[0] for p in parts], [p[1] for p in parts], out, folder / "lists")
            self.assertTrue(checks["ok"], checks)
            self.assertEqual(checks["frames"], checks["expected_frames"])
            self.assertEqual(checks["expected_frames"], 30 * (2 + 3 + 4))
            self.assertAlmostEqual(checks["duration"], 9.0, delta=0.1)
            self.assertEqual(len(checks["joins"]), 2)
            odd = self.clip(folder, "odd", 2, size="640x360")
            with self.assertRaisesRegex(ValueError, "must share the renderer settings"):
                longform.join_segments([parts[0][0], odd[0]], [parts[0][1], odd[1]], folder / "bad.mp4", folder / "l2")
        finally:
            env.close()


class LongFormWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(writer)
        providers.set_test_voice(fake_voice)

    def tearDown(self):
        providers.set_test_text_responder(None)
        providers.set_test_voice(None)
        self.env.close()

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.text)
        return r.json()

    def long_episode_to_script(self):
        c = self.c
        idea = self.ok(c.post("/api/ideas", json={"title": "Voice note saga", "premise": "A voice note, a whole evening of panic.",
                                                  "format": "long", "target_seconds": 360, "characters": ["character-01"], "status": "submitted"}), 201)
        ep = self.ok(c.post(f"/api/ideas/{idea['id']}/start", json={}), 201)
        self.assertEqual((ep["stage"], ep["format"]), ("outline_generating", "long"))
        eid = ep["id"]
        self.assertEqual(self.env.run_jobs(["generate_outline"]), [("generate_outline", "succeeded", "")])
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["stage"], "outline_review")
        self.assertEqual(len(d["outline"]["content"]["acts"]), 3)
        # Two-pass writing: no scene is written before the outline is approved.
        self.assertEqual(c.post(f"/api/episodes/{eid}/script/generate", json={}).status_code, 409)
        self.ok(c.post(f"/api/episodes/{eid}/outline/approve", json={"comment": "Good acts"}))
        self.ok(c.post(f"/api/episodes/{eid}/script/generate", json={}))
        ran = self.env.run_jobs(["generate_act"])
        self.assertEqual(ran, [("generate_act", "succeeded", "")] * 3, "acts written one by one")
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["stage"], "script_review")
        self.assertEqual([s["act"] for s in d["script"]["content"]["scenes"]], [1] * 5 + [2] * 5 + [3] * 5)
        return eid

    def test_outline_then_acts_and_act_regeneration(self):
        c = self.c
        eid = self.long_episode_to_script()
        # A Short cannot have an outline; a long script cannot skip its acts.
        self.ok(c.post(f"/api/episodes/{eid}/script/regenerate-section", json={"section": "act:2", "instruction": "sharper"}))
        self.assertEqual(self.env.run_jobs(["regenerate_section"]), [("regenerate_section", "succeeded", "")])
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["script"]["version"], 2)
        self.assertEqual([s["act"] for s in d["script"]["content"]["scenes"]], [1] * 5 + [2] * 5 + [3] * 5)
        self.ok(c.post(f"/api/episodes/{eid}/script/approve", json={}))
        reviews = [r["gate"] for r in d["reviews"]]
        self.assertIn("outline", reviews)

    @unittest.skipUnless(HAS_FFMPEG, "set FFMPEG and FFPROBE to render")
    def test_complete_long_episode(self):
        """Outline -> acts -> storyboard -> voiced scenes -> several segments -> join -> targeted revision (only the
        affected segment re-renders) -> injected segment failure retried on its own -> final approval."""
        c, run = self.c, self.env.run_jobs
        self.ok(c.put("/api/settings/voice", json={"provider": "openai", "default_voice": "alloy"}))
        eid = self.long_episode_to_script()
        self.ok(c.post(f"/api/episodes/{eid}/script/approve", json={}))
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/generate"))
        run(["generate_storyboard"])
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/approve", json={}))
        c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        self.ok(c.post(f"/api/episodes/{eid}/production/start"))
        ran = run(["scene_prepare", "scene_voice", "plan_segments", "render_segment", "join_segments"], max_rounds=50)
        self.assertEqual([x for x in ran if x[1] != "succeeded"], [], ran)
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["stage"], "video_review")
        segs = d["segments"]
        self.assertGreaterEqual(len(segs), 2, "several segments")
        self.assertTrue(all(s["seconds"] <= longform.SEGMENT_MAX for s in segs))
        self.assertTrue(all(s["status"] == "done" and s["reused_from"] is None for s in segs))
        video = d["video"]
        report = next(a for a in d["assets"] if a["label"] == "Join report")
        checks = c.get(report["url"]).json()
        self.assertTrue(checks["ok"], checks)
        self.assertEqual(checks["frames"], checks["expected_frames"])
        self.assertEqual(checks["segments"], len(segs))
        self.assertAlmostEqual(checks["duration"], sum(s["seconds"] for s in segs) + 3, delta=1.0)   # + end card
        # Every line was voiced, so each segment's clips continue the same character voice.
        voice = [j for j in d["jobs"] if j["kind"] == "scene_voice"]
        self.assertEqual(sum(len(j["result"]["clips"]) for j in voice), 30)

        # Targeted revision: re-produce one scene of the LAST segment; every other segment is reused unchanged.
        last = segs[-1]
        scene_key = last["parts"][0]["scene"]
        sid = next(s["id"] for s in d["scenes"] if s["scene_key"] == scene_key)
        # A retake with a different voice: the scene is re-voiced, so its segment really changes.
        self.ok(c.put("/api/settings/voice", json={"default_voice": "nova"}))
        self.ok(c.post(f"/api/episodes/{eid}/video/request-revision", json={"target": "scenes", "scene_ids": [sid], "comment": "Retake"}))
        ran = run(["scene_prepare", "scene_voice", "plan_segments", "render_segment", "join_segments"], max_rounds=50)
        self.assertEqual([k for k, s, _ in ran if k == "render_segment"], ["render_segment"], "only the affected segment re-rendered")
        d2 = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual((d2["stage"], d2["revision"]), ("video_review", 2))
        self.assertEqual(sum(1 for s in d2["segments"] if s["reused_from"]), len(segs) - 1)
        self.assertNotEqual(d2["video"]["id"], video["id"])

        # A failing segment render is retried on its own (injected failure on the first attempt).
        from oddstudio import engine
        real, calls = engine.produce, {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise engine.EngineRunError("injected render failure")
            return real(*a, **k)
        engine.produce = flaky
        try:
            self.ok(c.post(f"/api/episodes/{eid}/video/request-revision", json={"target": "segments", "segment_positions": [1], "comment": "Re-render the opening"}))
            ran = run(["plan_segments", "render_segment", "join_segments"])
            self.assertEqual(ran[-1][:2], ("render_segment", "failed"))
            d3 = self.ok(c.get(f"/api/episodes/{eid}"))
            self.assertEqual(d3["stage"], "production_failed")
            failed = next(s for s in d3["segments"] if s["status"] == "failed")
            self.assertEqual(failed["position"], 1)
            self.assertTrue(all(s["status"] == "done" for s in d3["segments"] if s["position"] != 1), "other segments untouched")
            self.ok(c.post(f"/api/jobs/{failed['job_id']}/retry"))
            ran = run(["render_segment", "join_segments"])
            self.assertEqual([x[:2] for x in ran], [("render_segment", "succeeded"), ("join_segments", "succeeded")])
        finally:
            engine.produce = real
        d4 = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d4["stage"], "video_review")
        self.ok(c.post(f"/api/episodes/{eid}/video/approve", json={"comment": "Final"}))
        self.assertEqual(self.ok(c.get(f"/api/episodes/{eid}"))["stage"], "final_approved")


if __name__ == "__main__":
    unittest.main()
