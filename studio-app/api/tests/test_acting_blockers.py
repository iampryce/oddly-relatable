"""feat/3d-rig PR 4: an expression without its own pose never blocks (the nearest approved one is used and named in the
Cast section), leftover poses waiting for review are not blockers, and a line's expression is changed in the storyboard
without touching the script or its approval."""
import unittest

from helpers import Env

from oddstudio import workspace as WS
from oddstudio.casting import cast_status, closest_expression


class ClosestTest(unittest.TestCase):
    def test_exact_loose_family_then_neutral(self):
        have = {"neutral", "angry", "smug"}
        self.assertEqual(closest_expression("angry", have), "angry")
        self.assertEqual(closest_expression("very smug", have), "smug")
        self.assertEqual(closest_expression("furious", have), "angry")
        self.assertEqual(closest_expression("proud", have), "smug")
        self.assertEqual(closest_expression("amused", have), "neutral", "no happy pose: neutral")
        self.assertEqual(closest_expression("", have), "neutral")
        self.assertEqual(closest_expression("worried", {"shocked"}), "shocked", "no neutral either: any approved one")


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset, Episode, ScriptVersion, StoryboardScene
        with new_session() as db:
            m = Character(key="mortimer", name="Uncle Mortimer", art_status="approved", expressions={"neutral": "p1", "angry": "p2"},
                          registry_path="generated", default_expression="neutral")
            db.add(m)
            db.flush()
            # a leftover pose still in review for an expression the script does not use
            db.add(CharacterAsset(character_id=m.id, kind="pose", expression="happy", storage_key="x.png", status="review"))
            ep = Episode(title="Will", stage="storyboard_review", source="audio", script_version=1, approved_script_version=1)
            db.add(ep)
            db.flush()
            self.script = {"title": "Will", "characters": [{"key": "mortimer"}],
                           "scenes": [{"id": "s1", "heading": "Reading", "lines": [{"speaker": "mortimer", "text": "To my nephew", "expression": "furious"}]}]}
            db.add(ScriptVersion(episode_id=ep.id, version=1, content=self.script, source="audio"))
            sc = StoryboardScene(episode_id=ep.id, position=1, scene_key="s1", heading="Reading", characters=["mortimer"],
                                 lines=[{"speaker": "mortimer", "text": "To my nephew", "expression": "furious", "start": 0.0, "end": 2.0}])
            db.add(sc)
            db.commit()
            self.eid, self.sid = ep.id, sc.id

    def tearDown(self):
        self.env.close()

    def test_a_missing_expression_is_a_note_and_leftover_reviews_do_not_block(self):
        from oddstudio.db import new_session
        with new_session() as db:
            row = cast_status(db, self.script)[0]
        self.assertEqual(row["missing_expressions"], ["furious"])
        self.assertEqual(row["fallbacks"], {"furious": "angry"})
        self.assertEqual(row["awaiting_review"], 0, "the happy pose in review is not for anything the script uses")
        s = WS.section_cast({"audio": False, "speakers_without_character": [], "cast_rows": [row], "script": 1})
        self.assertEqual(s["status"], "done", "approved art: nothing blocks")
        self.assertIn("furious uses angry", s["note"])
        s = WS.section_cast({"audio": False, "speakers_without_character": [], "cast_rows": [{**row, "art_status": "review"}], "script": 1})
        self.assertEqual(s["status"], "action", "no approved art at all: that still blocks")

    def test_a_line_expression_changes_without_touching_the_script_or_its_approval(self):
        url = f"/api/episodes/{self.eid}/scenes/{self.sid}/lines/0/expression"
        r = self.c.put(url, json={"expression": "angry"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["lines"][0]["expression"], "angry")
        r = self.c.put(url, json={"expression": "smug"})
        self.assertEqual(r.status_code, 422, "only the character's usable expressions")
        self.assertIn("neutral", r.json()["detail"])
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/scenes/{self.sid}/lines/5/expression", json={"expression": "angry"}).status_code, 404)
        from oddstudio.db import new_session
        from oddstudio.models import Episode, ScriptVersion
        with new_session() as db:
            ep = db.get(Episode, self.eid)
            self.assertEqual((ep.stage, ep.approved_script_version), ("storyboard_review", 1), "approvals untouched")
            sv = db.query(ScriptVersion).filter_by(episode_id=self.eid).all()
            self.assertEqual(len(sv), 1, "no new script version")
            self.assertEqual(sv[0].content["scenes"][0]["lines"][0]["expression"], "furious", "the script itself unchanged")
            ep.stage = "producing"
            db.commit()
        self.assertEqual(self.c.put(url, json={"expression": "neutral"}).status_code, 409, "not during a render")


if __name__ == "__main__":
    unittest.main()
