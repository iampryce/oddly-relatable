"""The episode's own set (owner decision 2026-11-21): no silent default. Every episode needs an explicitly chosen
APPROVED set before production starts; reuse is a deliberate pick that shows which other episodes use the set; the
video notes' setting word is shown as a suggestion and never applied by itself; the renderer uses the episode's set
and refuses clearly without one; existing episodes keep the set they render with today (migration 0008)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from helpers import Env, sample_script

from oddstudio import engine, providers

LIVING = "living-room-empty-03"


def add_studio_set(set_id, status="approved", label=None, description=""):
    """A studio set record (as Settings > Sets stores it), with a tiny real image as its asset."""
    from PIL import Image
    from oddstudio import sets
    from oddstudio.db import new_session
    from oddstudio.tasks import store_asset
    tmp = Path(tempfile.mkdtemp()) / f"{set_id}.png"
    Image.new("RGB", (60, 100), (120, 90, 60)).save(tmp)
    with new_session() as db:
        a = store_asset(db, ep_id=None, src=tmp, key=f"sets/{set_id}/{set_id}.png", kind="set-candidate",
                        label=set_id, content_type="image/png")
        recs = sets.records(db)
        recs[set_id] = {"label": label or set_id.title(), "description": description, "status": status, "asset_id": a.id,
                        "width": 60, "height": 100, "blocking": {"floor_y": 90, "stand_min_x": 5, "stand_max_x": 55},
                        "style_version": "v1"}
        sets.save(db, recs)
        db.commit()


class EpisodeSetTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(lambda s, p: sample_script())

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def ready(self, title="Card"):
        """A script-first episode with an approved storyboard, set to the rig animator (test steps only)."""
        i = self.c.post("/api/ideas", json={"title": title, "premise": "A card goes wrong.", "status": "submitted"}).json()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        self.env.run_jobs(["generate_script"])
        self.c.post(f"/api/episodes/{eid}/script/approve", json={})
        self.c.post(f"/api/episodes/{eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={})
        self.c.put("/api/settings/motion", json={"provider": "procedural-rig"})
        return eid

    def choose(self, eid, set_id):
        return self.c.put(f"/api/episodes/{eid}/set", json={"set_id": set_id})

    def test_no_silent_default_production_needs_a_chosen_set(self):
        eid = self.ready()
        self.assertIsNone(self.c.get(f"/api/episodes/{eid}").json()["set_id"], "new episodes start without a set")
        r = self.c.post(f"/api/episodes/{eid}/production/start")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("choose this episode's set first", r.text)
        self.assertEqual(self.choose(eid, LIVING).status_code, 200)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/production/start").status_code, 200)

    def test_only_approved_sets_can_be_chosen(self):
        add_studio_set("kitchen", status="candidate")
        add_studio_set("office", status="approved", description="a small office, daytime")
        eid = self.ready()
        r = self.choose(eid, "kitchen")
        self.assertEqual(r.status_code, 422, "a candidate is not a set yet")
        self.assertIn("approved in Settings > Sets", r.text)
        self.assertEqual(self.choose(eid, "nowhere").status_code, 422)
        self.assertEqual(self.choose(eid, "office").status_code, 200)
        opts = self.c.get(f"/api/episodes/{eid}/set-options").json()
        self.assertEqual(opts["current"], "office")
        self.assertEqual(sorted(o["id"] for o in opts["options"]), [LIVING, "office"])
        self.assertEqual([(c["id"], c["label"], c["for_this_episode"]) for c in opts["candidates"]], [("kitchen", "Kitchen", False)])
        self.assertTrue(all(o["thumbnail"] for o in opts["options"]), "every option has a thumbnail")

    def test_reuse_is_visible_and_deliberate(self):
        first, second = self.ready("First"), self.ready("Second")
        self.choose(first, LIVING)
        opts = self.c.get(f"/api/episodes/{second}/set-options").json()
        living = next(o for o in opts["options"] if o["id"] == LIVING)
        self.assertEqual(living["used_in"], [{"id": first, "title": "Group Chat Emergency"}])
        self.choose(second, LIVING)
        events = [e["message"] for e in self.c.get(f"/api/episodes/{second}").json()["events"]]
        self.assertTrue(any("reused, already in 1 other episode(s)" in m for m in events), events)

    def test_the_set_cannot_change_during_a_render_and_a_withdrawn_set_blocks(self):
        add_studio_set("office")
        eid = self.ready()
        self.choose(eid, "office")
        from oddstudio import sets
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            db.get(Episode, eid).stage = "producing"
            db.commit()
        self.assertEqual(self.choose(eid, LIVING).status_code, 409)
        with new_session() as db:
            db.get(Episode, eid).stage = "storyboard_approved"
            recs = sets.records(db)
            recs["office"]["status"] = "rejected"
            sets.save(db, recs)
            db.commit()
        r = self.c.post(f"/api/episodes/{eid}/production/start")
        self.assertEqual(r.status_code, 409)
        self.assertIn("not an approved set any more", r.text)

    def test_the_video_notes_setting_is_a_suggestion_only(self):
        add_studio_set("office", description="a small office, daytime")
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            ep = Episode(title="Audio", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"media_hints": {"setting": "office", "from": "video notes"}})
            db.add(ep)
            db.commit()
            eid = ep.id
        opts = self.c.get(f"/api/episodes/{eid}/set-options").json()
        self.assertEqual(opts["suggestion"], {"word": "office", "set_id": "office"})
        self.assertIsNone(opts["current"], "never applied by itself")

    def test_a_repository_plate_without_staging_is_not_offered(self):
        from oddstudio import sets
        from oddstudio.db import new_session
        bad = sets.REPO_SETS / "no-blocking-test.json"
        bad.write_text(json.dumps({"plate": "x.png", "width": 10, "height": 10}))
        try:
            with new_session() as db:
                self.assertNotIn("no-blocking-test", sets.usable(db))
                self.assertIsNone(sets.spec_for(db, "no-blocking-test", self.env.tmp))
                self.assertIsNotNone(sets.spec_for(db, LIVING, self.env.tmp))
        finally:
            bad.unlink()

    def test_the_renderer_refuses_without_a_set(self):
        from oddstudio import acting
        from oddstudio.db import new_session
        with new_session() as db:
            for ep, msg in ((SimpleNamespace(set_id=None, source="script"), "has no set"),
                            (SimpleNamespace(set_id="nowhere", source="script"), "not an approved set")):
                with self.assertRaises(engine.EngineInputError) as e:
                    acting.render(SimpleNamespace(db=db), ep, [], {}, {}, self.env.tmp / "render")
                self.assertIn(msg, str(e.exception))


class MigrationTest(unittest.TestCase):
    def test_0008_existing_episodes_keep_the_set_they_render_with(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        api = Path(__file__).resolve().parents[1]
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig8-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = Config(str(api / "alembic.ini"))
            cfg.set_main_option("script_location", str(api / "migrations"))
            command.upgrade(cfg, "0007")
            eng = create_engine(os.environ["DATABASE_URL"])
            ins = ("insert into episodes (id, title, stage, revision, storyboard_version, last_error, format, created_at, updated_at) "
                   "values (:id, :t, 'video_review', 1, 1, '', 'short', '2026-11-21', '2026-11-21')")
            scene = ("insert into storyboard_scenes (episode_id, position, scene_key, heading, location, description, action, camera, "
                     "characters, lines, status, production_status, revision_note, created_at, updated_at) values "
                     "(:e, 1, 's1', 'h', :loc, '', '', '', '[]', '[]', 'draft', 'done', '', '2026-11-21', '2026-11-21')")
            cols = {c["name"] for c in inspect(eng).get_columns("storyboard_scenes")}
            with eng.begin() as conn:
                conn.exec_driver_sql("insert into settings (key, value, updated_at) values (?, ?, '2026-11-21')",
                                     ("_sets", json.dumps({"office": {"status": "approved"}, "kitchen": {"status": "candidate"}})))
                for eid, title, loc in ((1, "office scene", "office"), (2, "kitchen candidate", "kitchen"),
                                        (3, "unknown place", "moon-base"), (4, "no storyboard", None)):
                    conn.exec_driver_sql(ins.replace(":id", str(eid)).replace(":t", f"'{title}'"))
                    if loc:
                        sql = scene.replace(":e", str(eid)).replace(":loc", f"'{loc}'")
                        # only the columns this schema version has
                        names = [n.strip() for n in sql.split("(")[1].split(")")[0].split(",")]
                        values = [v.strip() for v in sql.split("values (")[1].rstrip(")").split(",")]
                        keep = [(n, v) for n, v in zip(names, values) if n in cols]
                        conn.exec_driver_sql(f"insert into storyboard_scenes ({', '.join(n for n, _ in keep)}) values "
                                             f"({', '.join(v for _, v in keep)})")
            command.upgrade(cfg, "0008")
            with eng.connect() as conn:
                got = dict(conn.exec_driver_sql("select id, set_id from episodes order by id").fetchall())
            self.assertEqual(got, {1: "office", 2: LIVING, 3: LIVING, 4: LIVING},
                             "an approved studio set is kept; anything the renderer could not stage renders as the living room today")
            command.downgrade(cfg, "0007")
            self.assertNotIn("set_id", {c["name"] for c in inspect(eng).get_columns("episodes")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


if __name__ == "__main__":
    unittest.main()
