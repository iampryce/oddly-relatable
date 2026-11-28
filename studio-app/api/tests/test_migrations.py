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


    def test_0015_is_additive_and_the_previous_release_keeps_working(self):
        """0015 only adds two nullable columns: rows the previous release wrote are untouched and read back the same, the
        previous release's inserts (which do not name the new columns) still work, and it downgrades cleanly."""
        from alembic import command
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig15-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = alembic_config()
            command.upgrade(cfg, "0014")
            eng = create_engine(os.environ["DATABASE_URL"])
            ep_cols = {c["name"] for c in inspect(eng).get_columns("episodes")}
            sc_cols = {c["name"] for c in inspect(eng).get_columns("storyboard_scenes")}
            with eng.connect() as conn:
                before_ep = conn.exec_driver_sql("select count(*) from episodes").scalar()
            command.upgrade(cfg, "0015")
            i = inspect(eng)
            new_ep = {c["name"]: c for c in i.get_columns("episodes")}
            new_sc = {c["name"]: c for c in i.get_columns("storyboard_scenes")}
            self.assertEqual(set(new_ep) - ep_cols, {"layout"}, "only the layout column is added to episodes")
            self.assertEqual(set(new_sc) - sc_cols, {"shots"}, "only the shots column is added to storyboard_scenes")
            self.assertTrue(ep_cols <= set(new_ep) and sc_cols <= set(new_sc), "no column removed or renamed")
            self.assertTrue(new_ep["layout"]["nullable"] and new_sc["shots"]["nullable"],
                            "nullable: the previous release's inserts, which do not name them, still work")
            with eng.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("select count(*) from episodes").scalar(), before_ep)
            command.downgrade(cfg, "0014")
            self.assertNotIn("layout", {c["name"] for c in inspect(eng).get_columns("episodes")})
            self.assertNotIn("shots", {c["name"] for c in inspect(eng).get_columns("storyboard_scenes")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()

    def test_0016_is_additive_and_the_previous_release_keeps_working(self):
        """0016 only adds six nullable columns to character_assets: a pose the previous release wrote is untouched and
        reads back with a NULL dimension (the default: standing, front), the previous release's insert (which names none
        of the new columns) still works, and it downgrades cleanly."""
        from alembic import command
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig16-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        new_cols = {"posture", "body_turn", "view", "framing", "provenance", "parent_asset_id"}
        # the previous release's insert, exactly the columns it knows (SQLite does not enforce the character's foreign key)
        insert = ("insert into character_assets (character_id, kind, expression, storage_key, sha256, width, height, status, "
                  "style_version, created_at) values (1, 'pose', 'neutral', 'characters/x/{n}.png', '', 10, 10, 'approved', "
                  "'v1', '2026-11-24 00:00:00')")
        try:
            cfg = alembic_config()
            command.upgrade(cfg, "0015")
            eng = create_engine(os.environ["DATABASE_URL"])
            before = {c["name"] for c in inspect(eng).get_columns("character_assets")}
            with eng.begin() as conn:
                conn.exec_driver_sql(insert.format(n=1))
            command.upgrade(cfg, "0016")
            cols = {c["name"]: c for c in inspect(eng).get_columns("character_assets")}
            self.assertEqual(set(cols) - before, new_cols, "only the six new columns are added")
            self.assertTrue(before <= set(cols), "no column removed or renamed")
            self.assertTrue(all(cols[k]["nullable"] for k in new_cols), "all nullable")
            with eng.begin() as conn:
                conn.exec_driver_sql(insert.format(n=2))
                rows = conn.exec_driver_sql("select posture, body_turn, view, framing, provenance, parent_asset_id, status "
                                            "from character_assets order by id").all()
            self.assertEqual([tuple(r) for r in rows], [(None,) * 6 + ("approved",)] * 2,
                             "the old row and the old insert read back with the default dimension (NULL)")
            command.downgrade(cfg, "0015")
            self.assertEqual({c["name"] for c in inspect(eng).get_columns("character_assets")}, before)
            with eng.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("select count(*) from character_assets").scalar(), 2)
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


if __name__ == "__main__":
    unittest.main()
