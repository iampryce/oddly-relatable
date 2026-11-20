"""Voice library and auto-casting: parsing, the built-in match, the AI pick (with fallback), new characters getting a
voice, and an owner-set voice never being overwritten."""
import unittest

from helpers import Env

from oddstudio import providers
from oddstudio.casting import register_new_characters
from oddstudio.db import new_session
from oddstudio.models import Character
from oddstudio.settings_store import put_section
from oddstudio import voice_library as vl

A = "a" * 32
B = "b" * 32
C = "c" * 32
LIB = f"""# my voices
{A} | Warm Mum | her | warm older woman, kind, slow
https://fish.audio/app/text-to-speech/?modelId={B}&text=hi | Fast Guy | him | fast talking young man, energetic
{C} | Deadpan | neutral | flat dry narrator
not-a-voice-line
"""


class ParseTest(unittest.TestCase):
    def test_parse_accepts_ids_urls_comments_and_skips_junk(self):
        lib = vl.parse_library(LIB)
        self.assertEqual([v.id for v in lib], [A, B, C])
        self.assertEqual([v.gender for v in lib], ["her", "him", "neutral"])
        self.assertEqual(lib[1].label, "Fast Guy")

    def test_duplicates_and_empty(self):
        self.assertEqual(len(vl.parse_library(f"{A} | x\n{A} | y")), 1)
        self.assertEqual(vl.parse_library(""), [])

    def test_heuristic_matches_gender_then_style_and_prefers_unused(self):
        lib = vl.parse_library(LIB)
        self.assertEqual(vl.heuristic_pick(lib, "slow and kind", "her", set()).id, A)
        self.assertEqual(vl.heuristic_pick(lib, "energetic and fast", "him", set()).id, B)
        # the matching voice is taken: a different one is preferred only when the match is close; gender still wins
        self.assertEqual(vl.heuristic_pick(lib, "warm", "her", {A}).id, A)
        self.assertIsNone(vl.heuristic_pick([], "x", "him", set()))


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        with new_session() as db:
            put_section(db, "voice", {"library": LIB})

    def tearDown(self):
        providers.set_test_text_responder(None)

    def script(self, *chars):
        return {"new_characters": [dict(key=k, name=k.title(), description="d", visual_description="v", bubble_style=b, voice_style=s)
                                   for k, b, s in chars]}

    def test_new_characters_get_distinct_library_voices(self):
        with new_session() as db:
            register_new_characters(db, 1, self.script(("mum", "her", "warm older woman"), ("kid", "him", "fast energetic young")))
            db.commit()
            voices = {c.key: c.voice for c in db.query(Character)}
        self.assertEqual(voices["mum"], f"fish:{A}")
        self.assertEqual(voices["kid"], f"fish:{B}")

    def test_no_library_means_no_voice_and_set_voice_is_kept(self):
        with new_session() as db:
            put_section(db, "voice", {"library": ""})
            register_new_characters(db, 1, self.script(("solo", "her", "x")))
            db.commit()
            self.assertEqual(db.query(Character).filter_by(key="solo").one().voice, "")
        with new_session() as db:
            put_section(db, "voice", {"library": LIB})
            ch = Character(key="own", name="Own", voice="piper:mine.onnx", bubble_style="her", voice_style="warm",
                           scope="recurring", engine_character="studio-own", art_status="none")
            db.add(ch)
            db.flush()
            self.assertIsNone(vl.assign_new(db, ch, set()))
            self.assertEqual(ch.voice, "piper:mine.onnx")

    def make_char(self):
        r = self.c.post("/api/characters", json={"key": "gran", "name": "Gran", "bubble_style": "her", "voice_style": "warm kind slow"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def test_suggest_endpoint_uses_ai_when_valid_and_never_saves(self):
        cid = self.make_char()
        providers.set_test_text_responder(lambda system, prompt: {"id": C, "reason": "dry delivery fits"})
        r = self.c.post(f"/api/characters/{cid}/suggest-voice", json={"use_ai": True}).json()
        self.assertEqual((r["voice"], r["ai"], r["reason"]), (f"fish:{C}", True, "dry delivery fits"))
        self.assertEqual(self.c.get("/api/characters").json()[-1]["voice"], "")     # not saved

    def test_suggest_falls_back_when_ai_answers_with_an_unknown_id(self):
        cid = self.make_char()
        providers.set_test_text_responder(lambda system, prompt: {"id": "f" * 32})
        r = self.c.post(f"/api/characters/{cid}/suggest-voice", json={"use_ai": True}).json()
        self.assertEqual((r["voice"], r["ai"]), (f"fish:{A}", False))

        def boom(system, prompt):
            raise RuntimeError("provider down")
        providers.set_test_text_responder(boom)
        r = self.c.post(f"/api/characters/{cid}/suggest-voice", json={"use_ai": True}).json()
        self.assertEqual((r["voice"], r["ai"]), (f"fish:{A}", False))

    def test_suggest_with_empty_library_explains(self):
        cid = self.make_char()
        with new_session() as db:
            put_section(db, "voice", {"library": ""})
        r = self.c.post(f"/api/characters/{cid}/suggest-voice", json={}).json()
        self.assertEqual(r["voice"], "")
        self.assertIn("library is empty", r["reason"])


if __name__ == "__main__":
    unittest.main()
