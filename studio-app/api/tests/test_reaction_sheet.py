"""The reaction sheet and the shot list (2026-11-24): plain data on the storyboard, the same for every renderer; and the
frame layout ("band": a 16:9 picture band in the 9:16 frame). Edits never touch the script or its approval; the full
layout leaves the render spec exactly as before."""
import json
import unittest
from pathlib import Path

from helpers import Env

from oddstudio import acting
from oddstudio import reaction_sheet as RS
from oddstudio.script_schema import validate_script

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "examples" / "ep14-scene2-reactions.json"


class ExampleTest(unittest.TestCase):
    """The Phase 0 B draft for Episode 14, scene 2, validated by the same rules as the routes."""

    def test_the_scene_2_draft_validates(self):
        d = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        beats = []
        for r in d["reactions"]:
            ln = d["lines"][r["line"]]
            beats += RS.check_beats(r["beats"], name=r["character"], usable=set(d["approved"][r["character"]]),
                                    words=ln["words"], start=ln["start"], end=ln["end"])
        self.assertEqual(len(beats), 8, "7 rows in the draft; Sidney's row is two beats")
        self.assertEqual([b["word_text"] for b in beats],
                         ["Ralph", "bone", "toad", "lentitudinous", "toad", "toad", "leave", "yacht"])
        yacht = beats[-1]
        self.assertEqual((yacht["t"], yacht.get("estimated")), (17.65, True), "the badly timed word, set by hand")
        self.assertEqual(beats[0]["t"], 8.24, "a beat's time defaults to its word's start")
        lo, hi = d["scene_span"]
        shots = RS.check_shots(d["shots"], lo=lo, hi=hi, cast=set(d["cast"]))
        self.assertEqual([s["type"] for s in shots], ["ots", "mcu", "mcu", "medium", "mcu", "ots", "cu", "cu"])
        self.assertEqual(shots[3]["on_screen"], ["ralph", "sidney", "winifred"], "the family on screen at \"toad\"")
        self.assertTrue(shots[3]["start"] <= 12.16 < shots[3]["end"])


class RulesTest(unittest.TestCase):
    W = [{"word": "To", "start": 1.0, "end": 1.2}, {"word": "my", "start": 1.2, "end": 1.4}, {"word": "nephew", "start": 1.4, "end": 2.0}]

    def beats(self, b, usable=("neutral", "worried")):
        return RS.check_beats(b, name="Ralph", usable=set(usable), words=self.W, start=1.0, end=2.0)

    def test_beat_rules(self):
        self.assertEqual(self.beats([{"word": 2, "expression": "worried", "move": "flinch"}])[0]["t"], 1.4)
        for bad, why in (({"word": 3}, "not in this line"), ({"word": 0, "expression": "sad"}, "no approved 'sad'"),
                         ({"word": 0, "move": "spin"}, "the move"), ({"word": 0, "strength": "huge"}, "strength"),
                         ({"word": 0, "t": 9.5}, "outside this line"), ({"expression": "neutral"}, "choose the word")):
            with self.assertRaises(RS.SheetError) as e:
                self.beats([bad])
            self.assertIn(why, str(e.exception))
        with self.assertRaises(RS.SheetError) as e:
            RS.check_beats([{"word": 0}], name="Ralph", usable={"neutral"}, words=[], start=1.0, end=2.0)
        self.assertIn("word timings", str(e.exception))
        two = self.beats([{"word": 2}, {"word": 0}])
        self.assertEqual([b["word"] for b in two], [0, 2], "ordered by time")

    def test_shot_rules(self):
        ok = {"start": 1.0, "end": 2.0, "type": "mcu", "on_screen": ["a"]}
        self.assertEqual(len(RS.check_shots([ok, {**ok, "start": 2.0, "end": 3.0}], lo=0, hi=5, cast={"a", "b"})), 2)
        for shots, why in (([ok, {**ok, "start": 1.5, "end": 3.0}], "do not overlap"), ([{**ok, "end": 6.0}], "outside this scene"),
                           ([{**ok, "on_screen": ["z"]}], "not in this episode's cast"), ([{**ok, "type": "ots"}], "whose shoulder"),
                           ([{**ok, "end": 1.0}], "end after it starts"), ([{**ok, "type": "drone"}], "the type"),
                           ([{**ok, "on_screen": []}], "who is on screen")):
            with self.assertRaises(RS.SheetError) as e:
                RS.check_shots(shots, lo=0, hi=5, cast={"a", "b"})
            self.assertIn(why, str(e.exception))

    def test_scene_span(self):
        scenes = [{"lines": [{"start": 0.0, "end": 6.22}]}, {"lines": [{"start": 7.32, "end": 17.98}]}, {"lines": [{"start": 19.62, "end": 21.4}]}]
        self.assertEqual(RS.scene_span(scenes, 1), (6.22, 19.62))
        self.assertEqual(RS.scene_span(scenes, 0), (0.0, 7.32))
        self.assertEqual(RS.scene_span(scenes, 2, 60.0), (17.98, 60.0))

    def test_beats_survive_a_whole_scene_edit(self):
        doc = {"title": "t", "characters": [{"key": "m"}, {"key": "r"}], "scenes": [{"id": "s1", "heading": "h", "lines": [
            {"speaker": "m", "text": "To my nephew", "reactions": [{"character": "r", "beats": [
                {"word": 2, "t": 1.4, "expression": "worried", "move": "flinch", "strength": "strong", "reason": "x", "extra": 1}]}]}]}]}
        r = validate_script(doc, {"m", "r"})["scenes"][0]["lines"][0]["reactions"][0]
        self.assertEqual(r["beats"][0]["move"], "flinch")
        self.assertNotIn("extra", r["beats"][0])


class PresentationTest(unittest.TestCase):
    def test_the_full_layout_adds_nothing_to_the_spec(self):
        class Ep:
            dialogue_display = "captions"
            layout = None
        full = acting.presentation(Ep, "x")
        self.assertEqual(set(full), {"bubbles", "captions", "hook", "banner_font", "emoji_font"}, "exactly as before")
        Ep.layout = "full"
        self.assertEqual(acting.presentation(Ep, "x"), full)
        Ep.layout = "band"
        self.assertEqual(acting.presentation(Ep, "x"), {**full, "layout": "band"})

    def test_spec_shots_in_time_order_with_their_scene(self):
        class Sc:
            def __init__(self, position, shots):
                self.position, self.shots = position, shots
        out = RS.spec_shots([Sc(1, None), Sc(2, [{"start": 9.0, "end": 10.0}, {"start": 7.0, "end": 9.0}])])
        self.assertEqual([(x["scene"], x["start"]) for x in out], [(2, 7.0), (2, 9.0)])
        self.assertEqual(RS.spec_shots([Sc(1, None)]), [], "no shot list: no key in the spec")


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, Episode, ScriptVersion, StoryboardScene
        with new_session() as db:
            for key, name, ex in (("mortimer", "Uncle Mortimer", {"neutral": "p1"}),
                                  ("ralph", "Ralph", {"neutral": "p2", "worried": "p3"}), ("sidney", "Sidney", {"neutral": "p4"})):
                db.add(Character(key=key, name=name, art_status="approved", expressions=ex, registry_path="generated",
                                 default_expression="neutral"))
            words = [{"word": "To", "start": 7.32, "end": 7.32}, {"word": "my", "start": 7.32, "end": 7.56},
                     {"word": "nephew", "start": 7.56, "end": 7.96}, {"word": "Ralph", "start": 8.24, "end": 8.76}]
            tr = {"duration": 60.0, "lines": [{"id": "l1", "start": 0.0, "end": 6.22, "text": "Being of sound mind", "speaker": "mortimer",
                                               "words": [{"word": "Being", "start": 0.0, "end": 0.5}]},
                                              {"id": "l2", "start": 7.32, "end": 8.76, "text": "To my nephew, Ralph,", "speaker": "mortimer", "words": words}]}
            ep = Episode(title="Will", stage="storyboard_review", source="audio", script_version=1, approved_script_version=1,
                         audio_transcript=tr)
            db.add(ep)
            db.flush()
            db.add(ScriptVersion(episode_id=ep.id, version=1, content={"title": "Will", "scenes": []}, source="audio"))
            s1 = StoryboardScene(episode_id=ep.id, position=1, scene_key="s1", heading="Opening", characters=["mortimer", "ralph", "sidney"],
                                 lines=[{"speaker": "mortimer", "text": "Being of sound mind", "line_id": "l1", "start": 0.0, "end": 6.22}])
            s2 = StoryboardScene(episode_id=ep.id, position=2, scene_key="s2", heading="Ralph", characters=["mortimer", "ralph"],
                                 lines=[{"speaker": "mortimer", "text": "To my nephew, Ralph,", "line_id": "l2", "start": 7.32, "end": 8.76,
                                         "reactions": [{"character": "ralph", "expression": "neutral"}]}])
            db.add_all([s1, s2])
            db.commit()
            self.eid, self.s2 = ep.id, s2.id

    def tearDown(self):
        self.env.close()

    def url(self, tail):
        return f"/api/episodes/{self.eid}/scenes/{self.s2}/{tail}"

    def test_reaction_beats_are_stored_on_the_line_without_touching_the_script(self):
        r = self.c.put(self.url("lines/0/reactions"), json={"character": "ralph", "beats": [
            {"word": 3, "expression": "neutral", "move": "lift", "strength": "medium", "reason": "named first"}]})
        self.assertEqual(r.status_code, 200, r.text)
        rx = r.json()["lines"][0]["reactions"]
        self.assertEqual(rx[0]["expression"], "neutral", "the line's own reaction expression stays")
        self.assertEqual((rx[0]["beats"][0]["t"], rx[0]["beats"][0]["word_text"]), (8.24, "Ralph"))
        # a new listener joins the line
        r = self.c.put(self.url("lines/0/reactions"), json={"character": "sidney", "beats": [{"word": 2, "move": "glance", "strength": "light"}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["character"] for x in r.json()["lines"][0]["reactions"]], ["ralph", "sidney"])
        bad = self.c.put(self.url("lines/0/reactions"), json={"character": "ralph", "beats": [{"word": 3, "expression": "sad"}]})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("worried", bad.json()["detail"], "the approved ones are named")
        self.assertEqual(self.c.put(self.url("lines/0/reactions"), json={"character": "mortimer", "beats": []}).status_code, 422,
                         "the speaker does not react to their own line")
        self.assertEqual(self.c.put(self.url("lines/4/reactions"), json={"character": "ralph", "beats": []}).status_code, 404)
        r = self.c.put(self.url("lines/0/reactions"), json={"character": "sidney", "beats": []})
        self.assertNotIn("beats", r.json()["lines"][0]["reactions"][1], "an empty list removes the beats")
        from oddstudio.db import new_session
        from oddstudio.models import Episode, ScriptVersion
        with new_session() as db:
            ep = db.get(Episode, self.eid)
            self.assertEqual((ep.stage, ep.approved_script_version), ("storyboard_review", 1), "approvals untouched")
            self.assertEqual(db.query(ScriptVersion).filter_by(episode_id=self.eid).count(), 1, "no new script version")
            ep.stage = "producing"
            db.commit()
        self.assertEqual(self.c.put(self.url("lines/0/reactions"), json={"character": "ralph", "beats": []}).status_code, 409,
                         "not during a render")

    def test_the_shot_list_is_checked_against_the_scene_span_and_cast(self):
        shots = [{"start": 6.22, "end": 7.94, "type": "ots", "camera": "behind Ralph", "on_screen": ["mortimer"], "over_shoulder_of": "ralph"},
                 {"start": 7.94, "end": 8.94, "type": "mcu", "camera": "from Mortimer's side", "on_screen": ["ralph"]}]
        r = self.c.put(self.url("shots"), json={"shots": shots})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["shots"]), 2)
        bad = self.c.put(self.url("shots"), json={"shots": [{**shots[0], "start": 5.0}]})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("outside this scene (6.22-", bad.json()["detail"], "the scene starts where the previous one's last line ends")
        self.assertEqual(self.c.put(self.url("shots"), json={"shots": [{**shots[1], "on_screen": ["nobody"]}]}).status_code, 422)
        self.assertEqual(self.c.put(self.url("shots"), json={"shots": []}).json()["shots"], [], "an empty list removes it")

    def test_script_first_episodes_have_no_recording_to_time_against(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            db.get(Episode, self.eid).source = "script"
            db.commit()
        r = self.c.put(self.url("shots"), json={"shots": []})
        self.assertEqual(r.status_code, 409)
        self.assertIn("no recording", r.json()["detail"])

    def test_the_layout_setting(self):
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}").json()["layout"], "full")
        r = self.c.put(f"/api/episodes/{self.eid}/layout", json={"value": "band"})
        self.assertEqual((r.status_code, r.json()["layout"]), (200, "band"))
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/layout", json={"value": "square"}).status_code, 422)
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/layout", json={"value": "full"}).json()["layout"], "full")
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            self.assertIsNone(db.get(Episode, self.eid).layout, "full is stored as the default (NULL)")
            db.get(Episode, self.eid).stage = "producing"
            db.commit()
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/layout", json={"value": "band"}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
