"""The episode's Talking shots rows (2026-11-23): each row carries its talking clip, the keyed copy's previews over grey
and over the set, the check frames, the keying state as it really is, and Key again (free), the same as the shot
comparison's cell, so the normal path never needs the comparison page. WaveSpeed is stubbed: no network, no cost."""
import unittest
from unittest import mock

from test_asset_labels import IT, KeyLabelTest

from oddstudio.db import new_session
from oddstudio.models import Asset, Job
from oddstudio import shot_compare as SC


class TalkingRowTest(KeyLabelTest):
    def rows(self):
        return self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()["lines"]

    def test_a_keyed_row_has_its_clip_previews_check_frames_and_key_again(self):
        p = self.clip()
        r = self.rows()[0]
        self.assertTrue(r["clip_url"], "the clip is there before keying")
        self.assertIn(r["key"]["status"], ("queued", "running"))
        self.assertFalse(r["can_key_again"], "not while it is keying")
        self.assertEqual(self.env.run_jobs(["shot_key"])[0][1], "succeeded")
        r = self.rows()[0]
        self.assertEqual((r["status"], r["key"]["status"]), ("keyed", "done"))
        self.assertTrue(all(r["key"]["urls"][x] for x in ("keyed", "over_set", "over_grey", "check")))
        self.assertEqual(r["preview_url"], r["key"]["urls"]["over_set"])
        self.assertTrue(r["key"]["quality"]["ok"])
        self.assertEqual(len(r["key"]["check_at"]), 3, "one check frame per second of the 3 s clip")
        self.assertTrue(r["can_key_again"])
        # Key again from the row: the same free endpoint, nothing sent, nothing charged, the clip untouched
        res = self.row(p["id"])["results"][IT]
        with new_session() as s:
            before = (s.get(Asset, res["asset_id"]).sha256, s.get(Asset, res["raw_asset_id"]).sha256)
        self.assertEqual(self.c.post(f"/api/motion/shot/{r['plan_id']}/key", json={"model": IT}).status_code, 200)
        self.assertFalse(self.rows()[0]["can_key_again"], "queued again: not offered twice")
        self.assertEqual(self.env.run_jobs(["shot_key"])[0][1], "succeeded")
        res = self.row(p["id"])["results"][IT]
        self.assertEqual(res["actual_usd"], 0.045, "no new charge")
        with new_session() as s:
            self.assertEqual((s.get(Asset, res["asset_id"]).sha256, s.get(Asset, res["raw_asset_id"]).sha256), before)
        self.assertTrue(self.rows()[0]["can_key_again"])

    def test_a_failed_or_stopped_key_shows_why_and_offers_key_again(self):
        p = self.clip()
        with new_session() as s:
            j = s.query(Job).filter_by(kind="shot_key").one()
            j.status, j.error = "failed", "PendingRollbackError: This Session's transaction has been rolled back"
            recs = SC.records(s)
            recs[p["id"]]["results"][IT]["key"] = {"status": "running", "colour": "#FF00FF"}
            SC.save(s, recs)
            s.commit()
        r = self.rows()[0]
        self.assertEqual(r["key"]["status"], "failed")
        self.assertIn("stopped: PendingRollbackError", r["key"]["error"])
        self.assertTrue(r["can_key_again"])

    def test_a_clip_in_the_bin_has_no_link_and_no_key_again(self):
        p = self.clip()
        self.env.run_jobs(["shot_key"])
        aid = self.row(p["id"])["results"][IT]["asset_id"]
        with mock.patch("oddstudio.bin.hidden_ids", return_value={aid}):
            r = self.rows()[0]
        self.assertEqual((r["clip_url"], r["clip_binned"], r["can_key_again"]), (None, True, False))


if __name__ == "__main__":
    unittest.main()
