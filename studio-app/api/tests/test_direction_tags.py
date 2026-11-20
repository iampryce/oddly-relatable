"""Performance tags such as [whisper] or [laughs] are acting directions for the voice engine: the TTS still receives
them, but nothing the viewer sees shows them (speech bubbles, captions, the hook banner). Text and voice models are
test stand-ins; the storyboard, the engine story and the voice job are the real code."""
import unittest

from helpers import Env, fake_voice, sample_script

from oddstudio import acting, engine, providers


class StripDirectionTest(unittest.TestCase):
    def test_tags_are_removed_from_viewer_text(self):
        cases = {
            "[whispers] Not now.": "Not now.",
            "Not now. [laughs]": "Not now.",
            "I said [sighs] fine.": "I said fine.",
            "Wait [laughing] , what?": "Wait, what?",
            "[whisper][nervous] Who took it?": "Who took it?",
            "[short pause] Okay.": "Okay.",
            "[laughs]": "...",                    # a line that is only a direction: the house silent beat
            "Room [2] is free.": "Room [2] is free.",   # not a direction: kept
            "No tags here!": "No tags here!",
        }
        for raw, shown in cases.items():
            self.assertEqual(engine.viewer_text(raw), shown, raw)

    def test_acting_renderer_bubble_and_lipsync_text(self):
        bubble, spoken = acting.line_texts("[whispers] It's not about the charger. [sighs]")
        self.assertEqual(bubble, "It's not about the charger.")
        self.assertEqual(spoken, "It's not about the charger.")
        self.assertEqual(acting.line_texts("[laughs]"), ("...", ""))


class DirectionTagsInProductionTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        script = sample_script("The charger")
        script["hook"] = "[whispers] Someone took the charger."
        script["scenes"][0]["lines"][0]["text"] = "[whispers] We need to talk...?"
        script["scenes"][0]["lines"][1]["text"] = "WHAT DID I DO [panicked]"
        script["scenes"][1]["lines"][0]["text"] = "[laughs]"
        self.script = script
        providers.set_test_text_responder(lambda s, p: script)
        self.heard = []
        providers.set_test_voice(lambda text, voice, instr, out: self.heard.append(text) or fake_voice(text, voice, instr, out))

    def tearDown(self):
        providers.set_test_text_responder(None)
        providers.set_test_voice(None)
        self.env.close()

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.text)
        return r.json()

    def approved_storyboard(self):
        c = self.c
        i = self.ok(c.post("/api/ideas", json={"title": "Charger", "premise": "A charger goes missing.", "status": "submitted"}), 201)
        eid = self.ok(c.post(f"/api/ideas/{i['id']}/start", json={}), 201)["id"]
        self.env.run_jobs(["generate_script"])
        self.ok(c.post(f"/api/episodes/{eid}/script/approve", json={}))
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/generate"))
        self.env.run_jobs(["generate_storyboard"])
        return eid

    def test_bubbles_captions_and_hook_show_no_tags(self):
        eid = self.approved_storyboard()
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        from oddstudio.settings_store import get_section
        from oddstudio.tasks import by_key
        with new_session() as s:
            ep = s.get(Episode, eid)
            story = engine.build_story(episode_id=ep.id, revision=ep.revision, title=ep.title, script=self.script,
                                       scenes=list(ep.scenes), chars_by_key=by_key(s), production=get_section(s, "production"))
        shown = [ln["text"] for sc in story["scenes"] for ln in sc["lines"]]
        self.assertEqual(shown, ["We need to talk...?", "WHAT DID I DO", "..."])
        self.assertEqual(story["hook"]["text"], "Someone took the charger.")
        self.assertNotIn("[", " ".join(shown) + story["hook"]["text"])

    def test_the_voice_engine_still_receives_the_tags(self):
        eid = self.approved_storyboard()
        self.ok(self.c.put("/api/settings/voice", json={"provider": "openai", "default_voice": "alloy"}))
        self.ok(self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={}))
        self.ok(self.c.post(f"/api/episodes/{eid}/production/start"))
        ran = self.env.run_jobs(["scene_voice"])
        self.assertEqual({x[1] for x in ran}, {"succeeded"}, ran)
        self.assertIn("[whispers] We need to talk...?", self.heard)
        self.assertIn("WHAT DID I DO [panicked]", self.heard)
        self.assertIn("[laughs]", self.heard, "a line that is only a direction is still performed")
        # the stored script keeps the tags (the owner edits them; only the viewer-facing render text drops them)
        d = self.ok(self.c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["script"]["content"]["scenes"][0]["lines"][0]["text"], "[whispers] We need to talk...?")


if __name__ == "__main__":
    unittest.main()
