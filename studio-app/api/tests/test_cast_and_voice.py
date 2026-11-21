"""Story-driven characters (pose and expression sheets, approval, reuse) and voice (assignment, preview, dialogue,
synchronisation). The image and voice models are test stand-ins (refused outside ODD_ENV=test); everything else
(cut-out, sheet, registry, engine render, audio placement, QA) is the real code."""
import json
import os
import subprocess
import unittest
from pathlib import Path

from helpers import Env, fake_pose_image, fake_voice, sample_script

from oddstudio import providers

HAS_FFMPEG = bool(os.environ.get("FFMPEG") and os.environ.get("FFPROBE"))


def story_with_dad():
    s = sample_script("Dad and the remote")
    s["new_characters"] = [{"key": "dad", "name": "Dad", "description": "Strict but secretly soft", "bubble_style": "him",
                            "visual_description": "tall, square head, thick moustache, blue cardigan", "voice_style": "deep, slow, deadpan"}]
    s["characters"].append({"key": "dad", "role": "catches him"})
    s["scenes"][1]["lines"].append({"speaker": "dad", "text": "Who touched my remote?", "expression": "angry", "shot": "wide",
                                    "delivery": "slow and suspicious"})
    return s


class CastAndVoiceTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(lambda s, p: story_with_dad())
        providers.set_test_image(fake_pose_image)
        providers.set_test_voice(fake_voice)

    def tearDown(self):
        providers.set_test_text_responder(None)
        providers.set_test_image(None)
        providers.set_test_voice(None)
        self.env.close()

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.text)
        return r.json()

    def episode_through_storyboard(self):
        c = self.c
        i = self.ok(c.post("/api/ideas", json={"title": "Remote", "premise": "Dad's remote goes missing.", "status": "submitted"}), 201)
        eid = self.ok(c.post(f"/api/ideas/{i['id']}/start", json={}), 201)["id"]
        self.env.run_jobs(["generate_script"])
        return eid

    def dad(self):
        return next(x for x in self.ok(self.c.get("/api/characters")) if x["key"] == "dad")

    def test_restyle_replaces_design_only_after_approval(self):
        """A restyle redraws a character in the house style; the old poses stay in use until the owner approves the new
        sheet, and are then superseded (kept in history, never mixed into production)."""
        c = self.c
        eid = self.episode_through_storyboard()
        self.ok(c.put("/api/settings/image", json={"provider": "openai"}))
        self.ok(c.post(f"/api/episodes/{eid}/cast/generate"))
        self.env.run_jobs(["character_sheet"])
        self.ok(c.post(f"/api/characters/{self.dad()['id']}/sheet/decision", json={"decision": "approve"}))
        old = {a["id"] for a in self.dad()["assets"] if a["kind"] == "pose" and a["status"] == "approved"}
        self.assertEqual(c.post(f"/api/characters/{self.dad()['id']}/restyle", json={}).status_code, 409)   # no OpenAI key
        c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test"}})
        self.assertEqual(c.post(f"/api/characters/{self.dad()['id']}/restyle", json={}).status_code, 422)   # needs a description
        j = self.ok(c.post(f"/api/characters/{self.dad()['id']}/restyle", json={"visual_description": "a simple flat moustache; a flat blue top"}))
        self.assertTrue(j["payload"]["restyle"])
        self.env.run_jobs(["character_sheet"])
        dad = self.dad()
        new = {a["id"] for a in dad["assets"] if a["kind"] == "pose" and a["status"] == "review"}
        self.assertEqual(len(new), 2, "both expressions redrawn")
        self.assertEqual({a["id"] for a in dad["assets"] if a["kind"] == "pose" and a["status"] == "approved"}, old, "old design in use until approval")
        self.ok(c.post(f"/api/characters/{dad['id']}/sheet/decision", json={"decision": "approve"}))
        dad = self.dad()
        st = {a["id"]: a["status"] for a in dad["assets"] if a["kind"] == "pose"}
        self.assertTrue(all(st[i] == "superseded" for i in old))
        self.assertTrue(all(st[i] == "approved" for i in new))
        self.assertEqual(dad["visual_description"], "a simple flat moustache; a flat blue top")

    def test_character_voice_names_its_engine(self):
        heard = []
        providers.set_test_voice(lambda text, voice, instr, out: heard.append(voice) or fake_voice(text, voice, instr, out))
        from pathlib import Path
        import tempfile
        providers.speak({"provider": "piper"}, "hi", "kokoro:bm_george", Path(tempfile.mkdtemp()) / "x")
        self.assertEqual(heard, ["bm_george"])

    def test_story_introduces_character_sheet_approval_and_reuse(self):
        c = self.c
        eid = self.episode_through_storyboard()
        dad = self.dad()
        self.assertEqual((dad["scope"], dad["art_status"], dad["voice_style"]), ("episode", "none", "deep, slow, deadpan"))
        cast = {x["key"]: x for x in self.ok(c.get(f"/api/episodes/{eid}/cast"))}
        self.assertEqual(cast["dad"]["missing_expressions"], ["neutral", "angry"])
        self.assertEqual(cast["character-01"]["missing_expressions"], [], "locked approved art is never regenerated")
        # Image generation is off: refused, nothing generated.
        self.assertEqual(c.post(f"/api/episodes/{eid}/cast/generate").status_code, 409)
        self.ok(c.put("/api/settings/image", json={"provider": "openai"}))
        jobs = self.ok(c.post(f"/api/episodes/{eid}/cast/generate"))
        self.assertEqual([(j["kind"], j["payload"]["expressions"]) for j in jobs], [("character_sheet", ["neutral", "angry"])])
        self.assertEqual(c.post(f"/api/episodes/{eid}/cast/generate").status_code, 409, "no duplicate sheet while one is queued")
        ran = self.env.run_jobs(["character_sheet"])
        self.assertEqual(ran, [("character_sheet", "succeeded", "")])
        dad = self.dad()
        poses = [a for a in dad["assets"] if a["kind"] == "pose"]
        self.assertEqual(sorted(a["expression"] for a in poses), ["angry", "neutral"])
        self.assertTrue(all(a["status"] == "review" for a in poses))
        self.assertEqual(len([a for a in dad["assets"] if a["kind"] == "sheet"]), 1, "one labelled sheet for review")
        self.assertEqual(dad["art_status"], "review")
        # Not usable before the owner approves; not promotable either.
        self.assertEqual(c.post(f"/api/characters/{dad['id']}/promote").status_code, 409)
        self.ok(c.post(f"/api/characters/{dad['id']}/sheet/decision", json={"decision": "approve"}))
        dad = self.dad()
        self.assertEqual(dad["art_status"], "approved")
        self.assertEqual(sorted(dad["expressions"]), ["angry", "neutral"])
        # The generated poses were real cut-outs (transparent background).
        from PIL import Image
        from oddstudio.storage import storage
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        with new_session() as s:
            a = s.query(CharacterAsset).filter_by(kind="pose", expression="neutral", character_id=dad["id"]).one()
            img = Image.open(storage().local_path(a.storage_key))
            self.assertEqual(img.mode, "RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertTrue(700 <= a.feet["y"] <= 710, a.feet)   # bottom of the drawn feet (10 px line at y=700)
        # Promote: the character becomes part of the reusable cast.
        self.assertEqual(self.ok(c.post(f"/api/characters/{dad['id']}/promote"))["scope"], "recurring")
        # A later story reuses Dad without re-introducing him (an existing key in new_characters is ignored).
        self.assertEqual(len([x for x in self.ok(c.get("/api/characters")) if x["key"] == "dad"]), 1)

    def test_voice_assignment_and_preview(self):
        c = self.c
        self.episode_through_storyboard()
        dad = self.dad()
        self.assertEqual(c.post(f"/api/characters/{dad['id']}/voice/preview", json={}).status_code, 409, "no voice provider yet")
        self.ok(c.put("/api/settings/voice", json={"provider": "openai", "default_voice": "alloy"}))
        body = {k: dad[k] for k in ("key", "name", "description", "visual_description", "bubble_style", "scope", "default_expression")}
        self.ok(c.put(f"/api/characters/{dad['id']}", json={**body, "episode_id": dad["episode_id"], "voice": "onyx", "voice_style": "gravelly, slow"}))
        self.ok(c.post(f"/api/characters/{dad['id']}/voice/preview", json={"text": "Who touched my remote?"}))
        self.assertEqual(self.env.run_jobs(["voice_preview"]), [("voice_preview", "succeeded", "")])
        samples = [a for a in self.dad()["assets"] if a["kind"] == "voice-sample"]
        self.assertEqual(len(samples), 1)
        self.assertIn("audio", c.get(samples[0]["url"]).headers["content-type"])
        self.assertEqual(self.dad()["voice"], "onyx")

    def test_voice_direction(self):
        from oddstudio.models import Character
        from oddstudio.tasks import voice_direction
        d = voice_direction(Character(name="Dad", voice_style="deep, slow"), {"expression": "angry", "delivery": "whispered"})
        self.assertIn("deep, slow", d); self.assertIn("angry", d); self.assertIn("whispered", d)

    @unittest.skipUnless(HAS_FFMPEG, "set FFMPEG and FFPROBE to render")
    def test_generated_character_and_voices_in_a_real_render(self):
        """A story-introduced character (generated, approved) is animated by the real engine, and every dialogue line
        is voiced and placed exactly at its line's start in the final mix."""
        c, run = self.c, self.env.run_jobs
        eid = self.episode_through_storyboard()
        self.ok(c.put("/api/settings/image", json={"provider": "openai"}))
        self.ok(c.put("/api/settings/voice", json={"provider": "openai", "default_voice": "alloy"}))
        self.ok(c.post(f"/api/episodes/{eid}/cast/generate"))
        run(["character_sheet"])
        self.ok(c.post(f"/api/characters/{self.dad()['id']}/sheet/decision", json={"decision": "approve"}))
        self.ok(c.post(f"/api/episodes/{eid}/script/approve", json={}))
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/generate"))
        ran = run(["generate_storyboard", "scene_reference"])
        self.assertEqual([x for x in ran if x[1] != "succeeded"], [])
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/approve", json={}))
        c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        self.ok(c.post(f"/api/episodes/{eid}/production/start"))
        ran = run()
        self.assertEqual([x for x in ran if x[1] != "succeeded"], [], ran)
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["stage"], "video_review")
        voice_jobs = [j for j in d["jobs"] if j["kind"] == "scene_voice"]
        clips = [clip for j in voice_jobs for clip in j["result"]["clips"]]
        self.assertEqual(len(clips), 4, "every dialogue line was voiced")
        # The render's story places each clip at its line's start, and each line lasts at least as long as its clip.
        from oddstudio.config import get_settings
        story = json.loads((get_settings().work_dir / "episodes" / str(eid) / "r1" / "render" / "story.json").read_text())
        voice = story["audio"]["voice"]
        self.assertEqual(len(voice), 4)
        starts = [v["start"] for v in voice]
        self.assertEqual(starts, sorted(starts))
        lines = [ln for s in story["scenes"] for ln in s["lines"]]
        for clip, ln in zip(sorted(clips, key=lambda x: x["asset_id"]), lines):
            self.assertGreaterEqual(ln["duration"], clip["seconds"] + 0.4 - 1e-6)
        timings = subprocess.run([os.environ.get("NODE_BIN", "node"), str(Path(__file__).parents[1] / "oddstudio" / "node" / "line-timings.mjs"),
                                  str(get_settings().work_dir / "episodes" / str(eid) / "r1" / "render" / "story.json"),
                                  str(self.env.tmp / "timing-check")], capture_output=True, text=True, check=True, env={**os.environ})
        expected = [ln["start"] for sc in json.loads(timings.stdout) for ln in sc["lines"]]
        self.assertEqual(starts, expected, "each voice clip starts exactly when its line appears")
        # QA of the real MP4: audio present and active.
        qa = next(a for a in d["assets"] if a["label"] == "QA report")
        report = c.get(qa["url"]).json()
        self.assertNotIn("fail", json.dumps([x.get("status") for x in report.get("checks", [])]), report)
        # Editing the dialogue after voicing is caught (no stale audio).
        from oddstudio.db import new_session
        from oddstudio.models import StoryboardScene
        with new_session() as s:
            sc = s.query(StoryboardScene).filter_by(episode_id=eid, position=1).one()
            lines = list(sc.lines); lines[0] = {**lines[0], "text": "Changed after recording"}; sc.lines = lines; s.commit()
        from oddstudio.tasks import Ctx, _voice_audio
        from oddstudio.models import Episode, Job
        from oddstudio import engine
        with new_session() as s:
            ep = s.get(Episode, eid)
            with self.assertRaises(engine.EngineInputError):
                _voice_audio(Ctx(s, s.query(Job).first()), ep, json.loads(json.dumps(story)), self.env.tmp / "stale")


if __name__ == "__main__":
    unittest.main()
