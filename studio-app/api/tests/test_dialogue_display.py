"""Dialogue display (bubbles / none / captions) per episode with a Settings > Production default (new episodes: none;
existing episodes keep bubbles), and the POV banner: the hook keeps its emoji (drawn with a bundled colour emoji font,
OFL) while performance tags are removed; the writer is told to write a "POV: ..." hook."""
import os
import tempfile
import unittest
from pathlib import Path

from helpers import Env, sample_script

from oddstudio import acting, engine, providers, writer
from oddstudio.script_schema import ScriptError, validate_script

REPO = Path(__file__).resolve().parents[3]
FONTS = REPO / "skills/directing-stickman-videos/assets/fonts"


class BannerTextTest(unittest.TestCase):
    def test_hook_keeps_emoji_and_drops_tags(self):
        self.assertEqual(engine.hook_text("[whispers] POV: the card says sorry 😬"), "POV: the card says sorry 😬")
        self.assertEqual(engine.viewer_text("POV: the card says sorry 😬"), "POV: the card says sorry", "bubbles: no emoji")

    def test_presentation_follows_the_episode(self):
        class Ep:
            dialogue_display = "none"
        p = acting.presentation(Ep, "POV: oops 🤣")
        self.assertEqual((p["bubbles"], p["captions"], p["hook"]), (False, False, "POV: oops 🤣"))
        Ep.dialogue_display = "captions"
        self.assertEqual((acting.presentation(Ep, "x")["bubbles"], acting.presentation(Ep, "x")["captions"]), (False, True))
        Ep.dialogue_display = "bubbles"
        self.assertEqual((acting.presentation(Ep, "x")["bubbles"], acting.presentation(Ep, "x")["captions"]), (True, False))
        self.assertTrue(Path(p["banner_font"]).exists() and Path(p["emoji_font"]).exists())

    def test_bundled_fonts_carry_their_licence(self):
        for font, lic in (("Anton-Regular.ttf", "OFL-Anton.txt"), ("NotoColorEmoji-Regular.ttf", "OFL-NotoColorEmoji.txt")):
            self.assertTrue((FONTS / font).exists(), font)
            self.assertIn("SIL Open Font License", (FONTS / lic).read_text())

    def test_writer_asks_for_a_pov_hook_with_at_most_one_emoji(self):
        prompt = writer.system_prompt({"house_style": "x"})
        self.assertIn("starts with 'POV: '", prompt)
        self.assertIn("at most one emoji", prompt)
        self.assertIn("Never use emoji in dialogue", prompt)

    def test_script_accepts_a_pov_hook(self):
        s = sample_script()
        s["hook"] = "POV: you signed the boss's birthday card with deepest condolences 🤣"
        self.assertEqual(validate_script(s)["hook"], s["hook"])
        s["hook"] = "POV: " + "word " * 20
        with self.assertRaises(ScriptError):
            validate_script(s)


class DialogueDisplayTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(lambda s, p: sample_script())

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def new_episode(self):
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        return self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": False}).json()

    def test_default_for_new_episodes_is_none_and_follows_settings(self):
        self.assertEqual(self.c.get("/api/settings").json()["sections"]["production"]["dialogue_display"], "none")
        self.assertEqual(self.new_episode()["dialogue_display"], "none")
        self.assertEqual(self.c.put("/api/settings/production", json={"dialogue_display": "captions"}).status_code, 200)
        self.assertEqual(self.new_episode()["dialogue_display"], "captions")
        self.assertEqual(self.c.put("/api/settings/production", json={"dialogue_display": "subtitles"}).status_code, 422)
        a = self.c.post("/api/audio-episodes", json={"title": "Audio", "rights_confirmed": True, "rights_source": "own_recording"}).json()
        self.assertEqual(a["dialogue_display"], "captions")

    def test_change_per_episode(self):
        ep = self.new_episode()
        r = self.c.put(f"/api/episodes/{ep['id']}/dialogue-display", json={"value": "bubbles"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["dialogue_display"], "bubbles")
        self.assertEqual(self.c.get(f"/api/episodes/{ep['id']}").json()["dialogue_display"], "bubbles")
        self.assertEqual(self.c.put(f"/api/episodes/{ep['id']}/dialogue-display", json={"value": "speech"}).status_code, 422)
        events = [e["message"] for e in self.c.get(f"/api/episodes/{ep['id']}").json()["events"]]
        self.assertTrue(any("Dialogue on screen: none -> bubbles" in m for m in events), events)

    def test_locked_while_rendering(self):
        ep = self.new_episode()
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            s.get(Episode, ep["id"]).stage = "producing"
            s.commit()
        self.assertEqual(self.c.put(f"/api/episodes/{ep['id']}/dialogue-display", json={"value": "captions"}).status_code, 409)


class MigrationTest(unittest.TestCase):
    def test_0007_existing_episodes_keep_bubbles(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        api = Path(__file__).resolve().parents[1]
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig7-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = Config(str(api / "alembic.ini"))
            cfg.set_main_option("script_location", str(api / "migrations"))
            command.upgrade(cfg, "0006")
            eng = create_engine(os.environ["DATABASE_URL"])
            with eng.begin() as conn:
                conn.exec_driver_sql("insert into episodes (title, stage, revision, storyboard_version, last_error, format, created_at, updated_at) "
                                     "values ('old', 'video_review', 1, 0, '', 'short', '2026-11-20', '2026-11-20')")
            command.upgrade(cfg, "0007")
            with eng.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("select dialogue_display from episodes").scalar(), "bubbles")
            command.downgrade(cfg, "0006")
            self.assertNotIn("dialogue_display", {c["name"] for c in inspect(eng).get_columns("episodes")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


if __name__ == "__main__":
    unittest.main()
