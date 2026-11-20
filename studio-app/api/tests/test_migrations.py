"""Migrations: one head only (two changes that both add a revision on the same parent must be chained before they reach
main; CI fails here, so the auto-deploy never runs a release that cannot migrate), and 0006 is additive and reversible."""
import os
import tempfile
import unittest
from pathlib import Path

API = Path(__file__).resolve().parents[1]


def alembic_config():
    from alembic.config import Config
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "migrations"))
    return cfg


class MigrationsTest(unittest.TestCase):
    def test_single_head(self):
        from alembic.script import ScriptDirectory
        heads = ScriptDirectory.from_config(alembic_config()).get_heads()
        self.assertEqual(len(heads), 1, f"more than one migration head {heads}: set the later revision's down_revision "
                                        "to the other one")

    def test_0006_is_additive_and_reversible(self):
        from alembic import command
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig6-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = alembic_config()
            command.upgrade(cfg, "0005")
            eng = create_engine(os.environ["DATABASE_URL"])
            with eng.begin() as conn:   # rows written by the previous release
                conn.exec_driver_sql("insert into characters (key, name, description, visual_description, bubble_style, scope, expressions, "
                                     "default_expression, locked, art_status, voice, voice_style, created_at, updated_at) values "
                                     "('old', 'Old', '', '', 'neutral', 'recurring', '{}', 'neutral', 0, 'approved', '', '', '2026-11-20', '2026-11-20')")
                conn.exec_driver_sql("insert into character_assets (character_id, kind, expression, storage_key, sha256, width, height, status, created_at) "
                                     "values (1, 'pose', 'neutral', 'characters/old/poses/n.png', '', 0, 0, 'approved', '2026-11-20')")
            command.upgrade(cfg, "0006")
            with eng.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("select skin_tone from characters").scalar(), "")
                self.assertEqual(conn.exec_driver_sql("select style_version from character_assets").scalar(), "v1")
            command.downgrade(cfg, "0005")
            self.assertNotIn("skin_tone", {c["name"] for c in inspect(eng).get_columns("characters")})
            self.assertNotIn("style_version", {c["name"] for c in inspect(eng).get_columns("character_assets")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


if __name__ == "__main__":
    unittest.main()
