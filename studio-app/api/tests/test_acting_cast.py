"""Render cast (fix for render job 267, 2026-11-21): a line can put characters on screen who do not speak (the speaker's
look-at target, silent reactions). They used to be left out of the render's cast, and the renderer crashed with
"Cannot read properties of undefined (reading 'footDrop')" when a speaker looked at one of them. Now everyone a line
references is cast (and on stage from the start when they never speak); a referenced character that is not in the
studio or has no approved art stops production with a message naming them; a single approved pose is enough
(missing expressions fall back to neutral)."""
import unittest
from types import SimpleNamespace

from helpers import Env, sample_script

from oddstudio import engine, providers
from oddstudio.acting import face_for, referenced, render_cast


def char(key, name=None, approved=True, expressions=None):
    return SimpleNamespace(key=key, name=name or key.title(), registry_path="reg.json" if approved else None,
                           expressions=expressions if expressions is not None else ({"neutral": "p1"} if approved else {}),
                           art_status="approved" if approved else "none")


class CastTest(unittest.TestCase):
    LINES = [(1, {"speaker": "mortimer", "text": "I leave it all to my cat.", "look_at": "ralph",
                  "reactions": [{"character": "ralph", "expression": "shocked"}, {"character": "sidney", "expression": "smug"}]}),
             (1, {"speaker": "mortimer", "text": "Winifred gets nothing.", "reactions": [{"character": "winifred"}]})]

    def test_everyone_a_line_references_is_cast(self):
        self.assertEqual(referenced(self.LINES[0][1]), ["mortimer", "ralph", "ralph", "sidney"])
        chars = {k: char(k) for k in ("mortimer", "ralph", "sidney", "winifred")}
        keys, speaking = render_cast(self.LINES, {1: ["mortimer"]}, chars)
        self.assertEqual(keys, ["mortimer", "ralph", "sidney", "winifred"])
        self.assertEqual(speaking, {"mortimer"}, "the three others never speak: they start on stage")

    def test_a_character_without_approved_art_is_named(self):
        chars = {"mortimer": char("mortimer"), "ralph": char("ralph", "Ralph", approved=False),
                 "sidney": char("sidney"), "winifred": char("winifred")}
        with self.assertRaises(engine.EngineInputError) as e:
            render_cast(self.LINES, {1: ["mortimer"]}, chars)
        self.assertIn("Ralph", str(e.exception))
        self.assertIn("no approved pose art", str(e.exception))

    def test_a_character_not_in_the_studio_is_named(self):
        with self.assertRaises(engine.EngineInputError) as e:
            render_cast(self.LINES, {1: ["mortimer"]}, {"mortimer": char("mortimer"), "ralph": char("ralph")})
        self.assertIn("sidney, winifred", str(e.exception))

    def test_one_approved_pose_is_enough_and_expressions_fall_back(self):
        single = char("sidney", expressions={"neutral": "p1", "smug": "p2"})
        keys, _ = render_cast([(1, {"speaker": "sidney", "text": "Mine."})], {}, {"sidney": single})
        self.assertEqual(keys, ["sidney"])
        self.assertEqual(face_for({"neutral"}, char("ralph"), "shocked"), "neutral", "no approved shocked pose: neutral")
        self.assertEqual(face_for({"neutral", "smug"}, single, "smug"), "smug")


class ScriptFirstTest(unittest.TestCase):
    """The same can happen in a script-first episode: a character who reacts but never speaks."""

    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def test_a_reacting_non_speaker_is_in_the_storyboard_and_checked_before_production(self):
        from oddstudio.db import new_session
        from oddstudio.models import Character
        with new_session() as s:
            s.add(Character(key="ralph", name="Ralph", scope="recurring", art_status="none", engine_character="studio-ralph"))
            s.commit()
        script = sample_script()
        script["characters"].append({"key": "ralph", "role": "silent"})
        script["scenes"][0]["lines"][0]["reactions"] = [{"character": "ralph", "expression": "shocked"}]
        script["scenes"][0]["lines"][0]["look_at"] = "ralph"
        providers.set_test_text_responder(lambda sy, pr: script)
        i = self.c.post("/api/ideas", json={"title": "Will", "premise": "A will is read.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/script/approve", json={}).status_code, 200)   # test only
        self.c.post(f"/api/episodes/{eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        first = self.c.get(f"/api/episodes/{eid}").json()["scenes"][0]
        self.assertIn("ralph", first["characters"], "the storyboard lists the non-speaker on screen")
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={}).status_code, 200)   # test only
        self.c.put("/api/settings/motion", json={"provider": "procedural-rig"})
        r = self.c.post(f"/api/episodes/{eid}/production/start")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("Ralph", r.text)


if __name__ == "__main__":
    unittest.main()
