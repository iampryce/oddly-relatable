"""Job 352 (Episode 13, plan bb029347a9): the keyed copy's label was longer than assets.label (200), the insert failed,
the failure could not even be recorded (the session needed a rollback), and the cell stayed on "Keying ... out".
Now: short labels (the terms live in the plan's result, shown under the clip), one guard that fits any label to its
column, failures recorded on a clean session, a key left "running" by a dead job shown as failed with the job's reason,
and Key again working after it. Nothing paid: WaveSpeed is stubbed and keying is local."""
import subprocess
import unittest
from unittest import mock

from test_shot_compare import ShotBase
import test_talking_shots  # noqa: F401  (ShotBase.ready / ShotBase.row)

from oddstudio import secrets_store, wavespeed
from oddstudio import shot_compare as SC

IT = "wavespeed-infinitetalk-fast"
OLD_LONG = ("Shot comparison: WaveSpeed InfiniteTalk fast (our line audio), keyed copy with transparency (VP9 WebM alpha) "
            "(InfiniteTalk, Apache-2.0 model, hosted on WaveSpeed; commercial-use terms not yet confirmed in writing)")


class GuardTest(ShotBase):
    def test_any_label_is_fitted_to_its_column(self):
        self.assertGreater(len(OLD_LONG), 200, "the label that failed job 352")
        from oddstudio.db import new_session
        from oddstudio.models import Asset, BinItem
        from oddstudio.tasks import store_asset
        f = self.media / "x.bin"
        f.write_bytes(b"x")
        with new_session() as s:
            a = store_asset(s, ep_id=self.eid, src=f, key="episodes/x/long.bin", kind="video", label=OLD_LONG, content_type="video/webm")
            b = BinItem(kind="clip", ref="1", label="y" * 400)
            s.add(b)
            s.commit()
            a2 = s.get(Asset, a.id)
            self.assertEqual(len(a2.label), 200)
            self.assertTrue(a2.label.endswith("…"))
            self.assertTrue(a2.label.startswith("Shot comparison: WaveSpeed InfiniteTalk fast"))
            self.assertEqual(len(s.get(BinItem, b.id).label), 300)
            short = store_asset(s, ep_id=self.eid, src=f, key="episodes/x/short.bin", kind="video", label="Short", content_type="video/webm")
            self.assertEqual(short.label, "Short", "a short label is untouched")


class KeyLabelTest(ShotBase):
    def setUp(self):
        super().setUp()
        secrets_store._cache = None

    def tearDown(self):
        wavespeed.set_test_run(None)
        super().tearDown()

    def clip(self):
        """A finished InfiniteTalk cutout clip (stubbed provider), waiting for its keying step."""
        p = self.ready()

        def run(endpoint, body, out):
            subprocess.run([self.ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xFF00FF:s=512x640:d=3.0:r=25",
                            "-vf", "drawbox=x=150:y=100:w=200:h=400:color=white@1:t=fill,drawbox=x=150:y=100:w=200:h=400:color=black@1:t=12",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
            return {"id": "t1", "status": "completed", "outputs": ["https://ws.example/o.mp4"]}
        wavespeed.set_test_run(run)
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["shot_generate"])[0][1], "succeeded")
        return p

    def labels(self, pid):
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        with new_session() as s:
            return [a.label for a in s.query(Asset).filter(Asset.storage_key.like(f"%/shot-compare/{pid}/%")).all()]

    def test_the_keyed_copy_stores_with_short_labels_and_the_terms_stay_on_the_page(self):
        p = self.clip()
        ran = self.env.run_jobs(["shot_key"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        res = self.row(p["id"])["results"][IT]
        self.assertEqual(res["key"]["status"], "done")
        self.assertIn("commercial-use terms not yet confirmed in writing", res["terms"], "the clip's terms, shown under it")
        self.assertIn("commercial-use terms not yet confirmed in writing", res["key"]["terms"], "and the keyed copy's")
        labels = self.labels(p["id"])
        self.assertGreaterEqual(len(labels), 6, "raw, clip, keyed copy, two previews, check frames (and the first frames)")
        self.assertTrue(all(len(x) < 120 for x in labels), [x for x in labels if len(x) >= 120])
        self.assertFalse(any("terms" in x for x in labels), "the terms text is not in any label")

    def test_a_failed_keying_shows_its_reason_and_key_again_works(self):
        p = self.clip()
        from oddstudio.models import Asset

        def broken_store(db, **kw):
            db.add(Asset(episode_id=self.eid, kind=None, storage_key=None, content_type=None))   # an insert that fails
            db.flush()
        with mock.patch.object(SC, "store_asset", broken_store):
            ran = self.env.run_jobs(["shot_key"])
        self.assertEqual(ran[0][1], "failed")
        k = self.row(p["id"])["results"][IT]["key"]
        self.assertEqual(k["status"], "failed", "recorded, not stuck on 'Keying ... out'")
        self.assertIn("IntegrityError", k["error"], "the real reason")
        r = self.c.post(f"/api/motion/shot/{p['id']}/key", json={"model": IT})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.env.run_jobs(["shot_key"])[0][1], "succeeded")
        self.assertEqual(self.row(p["id"])["results"][IT]["key"]["status"], "done")

    def test_a_key_left_running_by_a_dead_job_is_shown_failed_and_can_be_keyed_again(self):
        """Episode 13's plan after job 352: the key says "running" but its job has failed."""
        p = self.clip()
        from oddstudio.db import new_session
        from oddstudio.models import Asset, Job
        with new_session() as s:
            j = s.query(Job).filter_by(kind="shot_key").one()
            j.status, j.error = "failed", "PendingRollbackError: This Session's transaction has been rolled back"
            recs = SC.records(s)
            recs[p["id"]]["results"][IT]["key"] = {"status": "running", "colour": "#FF00FF"}
            SC.save(s, recs)
            s.commit()
            clip_id = recs[p["id"]]["results"][IT]["asset_id"]
            raw_id = recs[p["id"]]["results"][IT]["raw_asset_id"]
            before = (s.get(Asset, clip_id).sha256, s.get(Asset, raw_id).sha256)
        k = self.row(p["id"])["results"][IT]["key"]
        self.assertEqual((k["status"], k["stale"]), ("failed", True))
        self.assertIn("stopped: PendingRollbackError", k["error"])
        rows = self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()["lines"]
        self.assertEqual(rows[0]["status"], "done")
        self.assertIn("keying failed", rows[0]["message"])
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/key", json={"model": IT}).status_code, 200, "Key again is accepted")
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/key", json={"model": IT}).status_code, 409, "but not twice at once")
        ran = self.env.run_jobs(["shot_key"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(self.row(p["id"])["results"][IT]["key"]["status"], "done")
        with new_session() as s:
            self.assertEqual((s.get(Asset, clip_id).sha256, s.get(Asset, raw_id).sha256), before, "the clip and the raw file untouched")
        self.assertEqual(self.row(p["id"])["results"][IT]["actual_usd"], 0.045, "no new paid call")


if __name__ == "__main__":
    unittest.main()
