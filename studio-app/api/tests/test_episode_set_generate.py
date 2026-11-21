"""A set for every episode (owner decision 2026-11-21): the studio proposes an original set description (audio: a
fixed sentence from the video notes' list values only; script-first: the AI writer from the story text), the owner
edits it, and only the owner's click generates a candidate from exactly the prompt the episode shows. The candidate
is linked to the episode and waits for approval in Settings > Sets; nothing is generated or approved by itself."""
import os
import re
import tempfile
import unittest
from pathlib import Path

from helpers import Env, fake_pose_image, sample_script

from oddstudio import providers
from oddstudio import video_notes as VN

RAW = {"ranges": [
    {"start": 0, "end": 4.5, "shot": "wide", "camera": "static", "setting": "dining room", "furniture": "long table",
     "time": "evening", "roles": [{"role": "speaker", "position": "left", "pose": "seated", "facing": "reactor 1", "emotion": "nervous"},
                                  {"role": "reactor 1", "position": "center", "pose": "seated", "facing": "speaker", "emotion": "nervous"},
                                  {"role": "reactor 2", "position": "right", "pose": "seated", "facing": "speaker", "emotion": "smug"},
                                  {"role": "reactor 3", "position": "background", "pose": "standing", "facing": "camera", "emotion": "calm"}]},
    {"start": 4.5, "end": 9, "shot": "medium", "camera": "pan", "setting": "dining room", "furniture": "golden throne",
     "time": "midnight", "brand": "Acme", "roles": [{"role": "speaker", "position": "left", "pose": "seated", "facing": "reactor 1",
                                                     "emotion": "nervous", "name": "Bob"}]},
]}


def allowed_words():
    lists = (VN.SETTINGS, VN.FURNITURE, VN.TIME_OF_DAY, VN.EMOTIONS)
    return VN.SENTENCE_WORDS | {w for vals in lists for v in vals for w in v.split()}


class ProposalTextTest(unittest.TestCase):
    def test_the_new_lists_are_cleaned(self):
        ranges, redacted = VN.clean_notes(RAW, 9.0)
        self.assertEqual(ranges[0]["furniture"], "long table")
        self.assertEqual(ranges[0]["time"], "evening")
        self.assertNotIn("furniture", ranges[1], "not on the list: dropped")
        self.assertNotIn("time", ranges[1])
        self.assertGreaterEqual(redacted, 4, "throne, midnight, brand and name are removed and counted")

    def test_the_sentence_uses_only_fixed_words_and_list_values(self):
        ranges, _ = VN.clean_notes(RAW, 9.0)
        text = VN.proposal_text(ranges)
        self.assertEqual(text, "An original dining room with a long table, evening, 3 people seated facing each other, "
                               "1 person standing; the mood is nervous.")
        words = re.findall(r"[a-z]+", text.lower())
        self.assertFalse(set(words) - allowed_words(), set(words) - allowed_words())
        self.assertNotIn("bob", text.lower())
        self.assertNotIn("acme", text.lower())
        self.assertEqual(VN.proposal_text([]), "An original room.")


class EpisodeProposalTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.prompts = []

        def image(prompt, out_file, reference):
            self.prompts.append(prompt)
            return fake_pose_image(prompt, out_file, reference)
        providers.set_test_image(image)
        self.c.put("/api/settings/image", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})

    def tearDown(self):
        providers.set_test_image(None)
        providers.set_test_text_responder(None)
        self.env.close()

    def jobs(self, kind):
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as s:
            return s.query(Job).filter_by(kind=kind).count()

    def audio_episode(self, notes=True, stage="audio_labelling"):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        ranges, _ = VN.clean_notes(RAW, 9.0)
        with new_session() as db:
            ep = Episode(title="Dinner Party", stage=stage, source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": [], "video_notes": {"ranges": ranges} if notes else None})
            db.add(ep)
            db.commit()
            return ep.id

    def test_audio_proposal_is_free_editable_and_generates_nothing_by_itself(self):
        eid = self.audio_episode()
        v = self.c.get(f"/api/episodes/{eid}/set-proposal").json()
        self.assertEqual((v["text"], v["propose_with"], v["can_propose"]), ("", "video notes", True))
        v = self.c.post(f"/api/episodes/{eid}/set-proposal/propose").json()
        self.assertTrue(v["text"].startswith("An original dining room with a long table, evening"), v)
        self.assertEqual(v["source"], "video notes")
        self.assertIn("about $0.05-0.20 per image", v["image_cost"])
        self.assertTrue(v["prompt"].endswith("\nSetting: " + v["text"]), "the shown prompt ends with exactly the box text")
        mine = "An original dining room at night with a long table, three people seated, one standing by the door."
        v = self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": mine}).json()
        self.assertEqual((v["text"], v["source"]), (mine, "edited"))
        self.assertEqual(self.jobs("set_candidate"), 0, "nothing is generated without the click")
        self.assertEqual(self.jobs("set_proposal"), 0, "the audio proposal uses no AI")

    def test_generate_sends_exactly_the_shown_prompt_and_links_the_candidate(self):
        eid = self.audio_episode()
        text = "An original rooftop garden with a bench, evening, 2 people seated facing each other."
        shown = self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": text}).json()["prompt"]
        r = self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"text": text})
        self.assertEqual(r.status_code, 200, r.text)
        g = r.json()
        self.assertEqual(g["prompt"], shown)
        self.assertEqual(g["set_id"], f"dinner-party-ep{eid}")
        again = self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"text": text}).json()
        self.assertEqual(again["set_id"], f"dinner-party-ep{eid}-2", "a second candidate never overwrites a queued one")
        ran = self.env.run_jobs(["set_candidate"])
        self.assertEqual([s for _, s, *_ in ran], ["succeeded", "succeeded"], ran)
        self.assertEqual(self.prompts, [shown, shown], "the image API gets exactly the text the episode showed")
        opts = self.c.get(f"/api/episodes/{eid}/set-options").json()
        mine = [c for c in opts["candidates"] if c["for_this_episode"]]
        self.assertEqual(sorted(c["id"] for c in mine), [g["set_id"], again["set_id"]])
        self.assertTrue(all(c["thumbnail"] for c in mine))
        sets = {s["id"]: s for s in self.c.get("/api/sets").json()["sets"]}
        self.assertEqual(sets[g["set_id"]]["status"], "candidate", "never approved by itself")
        self.assertEqual(sets[g["set_id"]]["episode_id"], eid)
        self.assertEqual(sets[g["set_id"]]["description"], text)
        self.assertNotIn(g["set_id"], [o["id"] for o in opts["options"]], "a candidate cannot be chosen until approved")

    def test_without_notes_or_while_producing(self):
        eid = self.audio_episode(notes=False)
        self.assertFalse(self.c.get(f"/api/episodes/{eid}/set-proposal").json()["can_propose"])
        r = self.c.post(f"/api/episodes/{eid}/set-proposal/propose")
        self.assertEqual(r.status_code, 409)
        self.assertIn("write the description yourself", r.text)
        busy = self.audio_episode(stage="producing")
        text = {"text": "An original kitchen with a counter, daytime."}
        self.assertEqual(self.c.put(f"/api/episodes/{busy}/set-proposal", json=text).status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{busy}/set-proposal/generate", json=text).status_code, 409)
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": "short"}).status_code, 422)

    def test_script_first_the_writer_proposes_from_the_story(self):
        seen = []

        def writer(system, prompt):
            if "ONE original set" in system:
                seen.append(prompt)
                return {"description": 'A cramped "studio flat" at night where Character 01 paces past a sofa, one person standing.'}
            return sample_script()
        providers.set_test_text_responder(writer)
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        v = self.c.get(f"/api/episodes/{eid}/set-proposal").json()
        self.assertEqual((v["propose_with"], v["can_propose"]), ("writer", True))
        r = self.c.post(f"/api/episodes/{eid}/set-proposal/propose")
        self.assertIn("job", r.json())
        self.assertEqual(self.jobs("set_candidate"), 0)
        ran = self.env.run_jobs(["set_proposal"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertIn("He reads a message.", seen[0], "the story text is what the writer reads")
        v = self.c.get(f"/api/episodes/{eid}/set-proposal").json()
        self.assertEqual(v["source"], "writer")
        self.assertEqual(v["text"], "A cramped studio flat at night where someone paces past a sofa, one person standing.",
                         "quotes and cast names are removed")
        self.assertEqual(self.jobs("set_candidate"), 0, "the writer's text is a proposal only")


class MigrationTest(unittest.TestCase):
    def test_0009_round_trip(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        api = Path(__file__).resolve().parents[1]
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig9-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = Config(str(api / "alembic.ini"))
            cfg.set_main_option("script_location", str(api / "migrations"))
            command.upgrade(cfg, "0009")
            eng = create_engine(os.environ["DATABASE_URL"])
            self.assertIn("set_proposal", {c["name"] for c in inspect(eng).get_columns("episodes")})
            command.downgrade(cfg, "0008")
            self.assertNotIn("set_proposal", {c["name"] for c in inspect(eng).get_columns("episodes")})
            self.assertIn("set_id", {c["name"] for c in inspect(eng).get_columns("episodes")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


if __name__ == "__main__":
    unittest.main()
