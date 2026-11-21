"""Characters page housekeeping (owner request 2026-11-21): which episodes use each character; archive or delete only
characters no live episode uses, with the names confirmed; locked repository art is never touched."""
import unittest

from helpers import Env, sample_script

from oddstudio import providers


class CharacterAdminTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(lambda s, p: sample_script())

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def char(self, key, **kw):
        r = self.c.post("/api/characters", json={"key": key, "name": key.title(), "scope": "episode", **kw})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def ids(self):
        return {c["key"]: c["id"] for c in self.c.get("/api/characters").json()}

    def test_usage_archive_and_delete(self):
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        old, spare = self.char("oldie"), self.char("spare")
        u = self.c.get("/api/characters/usage").json()
        self.assertEqual([e["id"] for e in u["usage"]["character-01"]], [eid], "the script's speaker is in use")
        self.assertNotIn("oldie", u["usage"])
        lead = self.ids()["character-01"]
        r = self.c.post("/api/characters/archive", json={"ids": [lead]})
        self.assertEqual(r.status_code, 409)
        self.assertTrue("repository artwork" in r.text or "live episode" in r.text, r.text)
        self.assertEqual(self.c.post("/api/characters/archive", json={"ids": [old]}).json()["archived"], [old])
        self.assertIn(old, self.c.get("/api/characters/usage").json()["archived"])
        self.assertEqual(self.c.post("/api/characters/unarchive", json={"ids": [old]}).json()["archived"], [])
        r = self.c.post("/api/characters/delete", json={"ids": [old, spare], "confirm_names": ["Oldie"]})
        self.assertEqual(r.status_code, 422, "the confirmation must name every character")
        self.assertIn("Oldie, Spare", r.text)
        r = self.c.post("/api/characters/delete", json={"ids": [old, spare], "confirm_names": ["Spare", "Oldie"]})
        self.assertEqual(r.json()["deleted"], ["Oldie", "Spare"])
        self.assertNotIn("oldie", self.ids())

    def test_a_storyboard_line_reference_counts_as_use(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode, StoryboardScene
        with new_session() as s:
            ep = Episode(title="Dinner", stage="storyboard_review")
            s.add(ep)
            s.flush()
            s.add(StoryboardScene(episode_id=ep.id, position=1, scene_key="s1", heading="h", location="x", description="",
                                  action="", camera="", characters=[], lines=[{"speaker": "theo", "text": "Hi.",
                                                                               "reactions": [{"character": "mae"}]}]))
            s.commit()
        theo, mae = self.char("theo"), self.char("mae")
        for cid in (theo, mae):
            self.assertEqual(self.c.post("/api/characters/archive", json={"ids": [cid]}).status_code, 409)

    def test_a_character_of_a_live_episode_is_kept(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            ep = Episode(title="Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": [], "cast": {"Speaker 2": "ralph"}})
            s.add(ep)
            s.commit()
            eid = ep.id
        rid = self.char("ralph")
        r = self.c.post("/api/characters/delete", json={"ids": [rid], "confirm_names": ["Ralph"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Ralph (Will)", r.text)
        with new_session() as s:
            s.get(Episode, eid).stage = "published"
            s.commit()
        self.assertEqual(self.c.post("/api/characters/archive", json={"ids": [rid]}).status_code, 200,
                         "a published episode is not live")


if __name__ == "__main__":
    unittest.main()
