"""The Bin and clearing failed jobs (owner decisions 2026-11-21).

Delete moves an item to the Bin (hidden everywhere, restorable for 30 days); Delete forever / Empty Bin / the weekly
purge remove the rows and the files; protection refuses anything another non-deleted episode uses, locked artwork and
rendered or published episodes; deleting an episode never deletes its characters or sets; bulk actions show their list
and count first. Failed jobs can be cleared from Production unless a live episode still needs them to retry."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import Env
from test_episode_sets import add_studio_set

import unittest

from oddstudio import bin as BIN


class BinRulesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset, Episode, Job
        from oddstudio.storage import storage
        f = Path(self.env.tmp) / "pose.png"
        f.write_bytes(b"x" * 2048)
        add_studio_set("kitchen")
        add_studio_set("garage", status="candidate")
        add_studio_set("attic", status="candidate")
        with new_session() as s:
            used = Episode(title="Will", stage="storyboard_review", source="audio", set_id="kitchen", scene_set_ids=["attic"],
                           audio_transcript={"lines": [], "cast": {"S1": "ralph"}})
            failed = Episode(title="Broken render", stage="production_failed", set_id="kitchen")
            done = Episode(title="Done", stage="video_review", set_id="kitchen")
            s.add_all([used, failed, done])
            s.flush()
            for k in ("ralph", "spare"):
                s.add(Character(key=k, name=k.title(), scope="episode", art_status="approved", registry_path="generated"))
            s.flush()
            spare = s.query(Character).filter_by(key="spare").one()
            ralph = s.query(Character).filter_by(key="ralph").one()
            poses = {}
            for who, exp, st in ((ralph, "neutral", "approved"), (ralph, "smug", "review"), (spare, "neutral", "approved"),
                                 (spare, "sad", "rejected")):
                key = f"characters/{who.key}/{exp}.png"
                storage().put_file(key, f, "image/png")
                a = CharacterAsset(character_id=who.id, kind="pose", expression=exp, storage_key=key, status=st)
                s.add(a)
                s.flush()
                poses[(who.key, exp)] = a.id
            ralph.expressions = {"neutral": f"p{poses[('ralph', 'neutral')]}"}
            spare.expressions = {"neutral": f"p{poses[('spare', 'neutral')]}"}
            old = Job(kind="scene_prepare", episode_id=used.id, status="failed", error="x",
                      created_at=datetime.now(timezone.utc) - timedelta(days=3), finished_at=datetime.now(timezone.utc) - timedelta(days=3))
            render = Job(kind="render_episode", episode_id=failed.id, status="failed", error="footDrop",
                         created_at=datetime.now(timezone.utc) - timedelta(days=2), finished_at=datetime.now(timezone.utc) - timedelta(days=2))
            today = Job(kind="scene_prepare", episode_id=None, status="failed", error="y")
            s.add_all([old, render, today])
            s.commit()
            self.ids = {"used": used.id, "failed": failed.id, "done": done.id, "ralph": ralph.id, "spare": spare.id,
                        "old": old.id, "render": render.id, "today": today.id, **{f"{k}:{e}": v for (k, e), v in poses.items()}}
        from oddstudio.config import get_settings
        wf = get_settings().work_dir / "episodes" / str(self.ids["failed"])
        wf.mkdir(parents=True, exist_ok=True)
        (wf / "render.mp4").write_bytes(b"y" * 4096)
        self.work_folder = wf

    def tearDown(self):
        self.env.close()

    def move(self, kind, ref):
        return self.c.post("/api/bin/move", json={"kind": kind, "ref": str(ref)})

    def test_protection_names_the_episode(self):
        r = self.move("character", self.ids["ralph"])
        self.assertEqual(r.status_code, 409)
        self.assertIn('episode', r.text)
        self.assertIn('"Will"', r.json()["detail"])
        r = self.move("pose", self.ids["ralph:neutral"])
        self.assertEqual(r.status_code, 409, "an approved pose of a character in use")
        self.assertEqual(self.move("pose", self.ids["ralph:smug"]).status_code, 200, "a pose in review is not used")
        for sid in ("kitchen", "attic"):
            r = self.move("set", sid)
            self.assertEqual(r.status_code, 409)
            self.assertIn('"Will"', r.json()["detail"])
        r = self.move("episode", self.ids["done"])
        self.assertEqual(r.status_code, 409)
        self.assertIn("rendered or published", r.text)
        lead = [c for c in self.c.get("/api/characters").json() if c["locked"]]
        if lead:
            self.assertIn("locked", self.move("character", lead[0]["id"]).text)

    def test_moved_items_are_hidden_everywhere_and_restorable(self):
        self.assertEqual(self.move("character", self.ids["spare"]).status_code, 200)
        self.assertNotIn("spare", [c["key"] for c in self.c.get("/api/characters").json()])
        self.assertEqual(self.move("episode", self.ids["failed"]).status_code, 200)
        self.assertNotIn(self.ids["failed"], [e["id"] for e in self.c.get("/api/episodes").json()])
        r = self.c.post(f"/api/jobs/{self.ids['render']}/retry")
        self.assertEqual(r.status_code, 409, "a binned episode's job cannot be retried")
        self.assertIn("in the Bin", r.text)
        self.assertEqual(self.c.get(f"/api/episodes/{self.ids['failed']}").status_code, 404)
        self.assertEqual(self.move("set", "garage").status_code, 200)
        self.assertNotIn("garage", [s["id"] for s in self.c.get("/api/sets").json()["sets"]])
        self.assertEqual(self.move("pose", self.ids["ralph:smug"]).status_code, 200)
        ralph = next(c for c in self.c.get("/api/characters").json() if c["key"] == "ralph")
        self.assertNotIn(self.ids["ralph:smug"], [a["id"] for a in ralph["assets"]])
        self.assertEqual(self.move("set", "garage").status_code, 409, "already in the Bin")
        items = {b["kind"]: b for b in self.c.get("/api/bin").json()["items"]}
        self.assertEqual(items["episode"]["days_left"], 30)
        self.assertGreater(items["episode"]["size_bytes"], 4000, "the work folder counts")
        for b in self.c.get("/api/bin").json()["items"]:
            self.assertEqual(self.c.post(f"/api/bin/{b['id']}/restore").status_code, 200)
        self.assertIn("spare", [c["key"] for c in self.c.get("/api/characters").json()])
        self.assertEqual(self.c.get(f"/api/episodes/{self.ids['failed']}").status_code, 200)
        sets = {s["id"]: s for s in self.c.get("/api/sets").json()["sets"]}
        self.assertEqual(sets["garage"]["status"], "candidate")
        ralph = next(c for c in self.c.get("/api/characters").json() if c["key"] == "ralph")
        self.assertEqual(next(a for a in ralph["assets"] if a["id"] == self.ids["ralph:smug"])["status"], "review")

    def test_deleting_an_episode_keeps_its_characters_and_sets_and_forever_removes_files(self):
        self.move("episode", self.ids["failed"])
        b = self.c.get("/api/bin").json()["items"][0]
        p = self.c.post("/api/bin/forever", json={"ids": [b["id"]]}).json()
        self.assertEqual((p["count"], p["items"][0]["label"]), (1, f'Episode {self.ids["failed"]} "Broken render" (production_failed)'))
        self.assertTrue(self.work_folder.exists(), "nothing is removed without confirm")
        r = self.c.post("/api/bin/forever", json={"ids": [b["id"]], "confirm": True}).json()
        self.assertGreater(r["freed_bytes"], 4000)
        self.assertFalse(self.work_folder.exists())
        from oddstudio.db import new_session
        from oddstudio.models import Asset, Episode
        with new_session() as s:
            self.assertIsNone(s.get(Episode, self.ids["failed"]))
            self.assertEqual(s.query(Asset).filter_by(episode_id=self.ids["failed"]).count(), 0, "its asset rows are gone too")
        self.assertIn("kitchen", [s["id"] for s in self.c.get("/api/sets").json()["sets"]], "its set stays")
        self.move("pose", self.ids["spare:sad"])
        from oddstudio.storage import storage
        path = storage().local_path("characters/spare/sad.png")
        self.assertTrue(path.exists())
        self.c.post("/api/bin/forever", json={"all": True, "confirm": True})
        self.assertFalse(path.exists(), "Empty Bin removes the files")
        self.assertEqual(self.c.get("/api/bin").json()["items"], [])

    def test_restoring_an_episode_names_what_is_gone(self):
        self.move("episode", self.ids["used"])
        self.assertEqual(self.move("character", self.ids["ralph"]).status_code, 200, "its episode is deleted: the character may go")
        b = next(x for x in self.c.get("/api/bin").json()["items"] if x["kind"] == "episode")
        r = self.c.post(f"/api/bin/{b['id']}/restore").json()
        self.assertIn("characters no longer available: ralph", r["warning"])

    def test_purge_after_30_days_by_maintenance(self):
        self.move("pose", self.ids["spare:sad"])
        self.move("set", "garage")
        from oddstudio.db import new_session
        from oddstudio.models import BinItem
        with new_session() as s:
            old = s.query(BinItem).filter_by(kind="pose").one()
            old.deleted_at = datetime.now(timezone.utc) - timedelta(days=31)
            s.commit()
        from oddstudio.storage import storage
        path = storage().local_path("characters/spare/sad.png")
        self.assertEqual(BIN.main(["purge", "--days", "30", "--dry-run"]), 0)
        self.assertTrue(path.exists(), "the dry run removes nothing")
        self.assertEqual(BIN.main(["purge", "--days", "30"]), 0)
        self.assertFalse(path.exists())
        self.assertEqual([b["kind"] for b in self.c.get("/api/bin").json()["items"]], ["set"], "the recent item stays")

    def test_bulk_actions_show_the_list_and_count_first(self):
        p = self.c.post("/api/bin/bulk/poses", json={}).json()
        self.assertEqual(p["count"], 2, "ralph's review pose and spare's rejected pose")
        s = self.c.post("/api/bin/bulk/sets", json={}).json()
        self.assertEqual(([x["ref"] for x in s["items"]], len(s["kept"])), (["garage"], 1), "attic is a candidate the Will uses")
        e = self.c.post("/api/bin/bulk/episodes", json={}).json()
        self.assertEqual([x["ref"] for x in e["items"]], [str(self.ids["failed"])])
        self.assertEqual(self.c.get("/api/bin").json()["items"], [], "previews move nothing")
        self.assertEqual(self.c.post("/api/bin/bulk/poses", json={"confirm": True}).json()["moved"], 2)
        self.assertEqual(len(self.c.get("/api/bin").json()["items"]), 2)

    def test_comparison_clips_can_be_deleted_from_the_video_library(self):
        from oddstudio.db import new_session
        from oddstudio.tasks import store_asset
        f = Path(self.env.tmp) / "clip.mp4"
        f.write_bytes(b"v" * 1000)
        eid = self.ids["used"]
        with new_session() as s:
            ids = {}
            for name, key in (("shot", f"episodes/{eid}/shot-compare/p1/kling.mp4"), ("leo", f"episodes/{eid}/comparison/wan-a1.mp4"),
                              ("render", f"episodes/{eid}/r1/final.mp4")):
                ids[name] = store_asset(s, ep_id=eid, src=f, key=key, kind="video", label=name, content_type="video/mp4").id
            s.commit()
        lib = next(e for e in self.c.get("/api/library").json() if e["id"] == eid)
        flags = {v["label"]: v["comparison_clip"] for v in lib["videos"]}
        self.assertEqual(flags, {"shot": True, "leo": True, "render": False}, "only comparison clips get a Delete")
        r = self.move("clip", ids["render"])
        self.assertEqual(r.status_code, 409, "an episode's own render is not a comparison clip")
        for name in ("shot", "leo"):
            self.assertEqual(self.move("clip", ids[name]).status_code, 200)
        lib = next(e for e in self.c.get("/api/library").json() if e["id"] == eid)
        self.assertEqual([v["label"] for v in lib["videos"]], ["render"], "deleted clips are hidden from the library")

    def test_storage_never_deletes_outside_its_folder(self):
        from oddstudio.storage import storage
        for bad in ("../secrets.txt", "/etc/passwd", "a/../../b"):
            with self.assertRaises(ValueError):
                storage().delete(bad)

    def test_clear_failed_jobs(self):
        jobs = {j["id"]: j for j in self.c.get("/api/jobs").json()}
        self.assertIn("retry it", jobs[self.ids["render"]]["keep_reason"], "the failed render a live episode needs stays")
        self.assertIsNone(jobs[self.ids["old"]]["keep_reason"])
        r = self.c.post(f"/api/jobs/{self.ids['render']}/clear")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Broken render", r.text)
        p = self.c.post("/api/jobs/clear-failed", json={}).json()
        self.assertEqual((p["ids"], [k["id"] for k in p["kept"]]), ([self.ids["old"]], [self.ids["render"]]),
                         "only jobs from before today; the needed one is kept with its reason")
        self.assertEqual(self.c.post("/api/jobs/clear-failed", json={"confirm": True}).json()["cleared"], 1)
        listed = [j["id"] for j in self.c.get("/api/jobs").json()]
        self.assertNotIn(self.ids["old"], listed)
        self.assertIn(self.ids["today"], listed)
        self.assertEqual(self.c.post(f"/api/jobs/{self.ids['today']}/clear").status_code, 200)
        self.assertNotIn(self.ids["today"], [j["id"] for j in self.c.get("/api/jobs").json()])


if __name__ == "__main__":
    unittest.main()
