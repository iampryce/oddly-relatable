"""Disk usage on the Overview page (2026-11-23): the disk measured now, the level (yellow from 80%, red from 90%), the
biggest consumers from the housekeeping report (deploy/maintenance.sh), and a report that is missing, broken or old.
Read-only: the route has no way to remove anything."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from helpers import Env

from oddstudio import system_disk as SD

G = 1024 ** 3


def report(**over):
    r = {"version": 1, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "dry-run",
         "disk": {"size": 96 * G, "used": 87 * G, "free": 9 * G, "percent": 91},
         "consumers": [{"key": "backups", "label": "Backups", "bytes": 7 * G},
                       {"key": "releases", "label": "Release folders", "bytes": 21 * G},
                       {"key": "images", "label": "Docker images", "bytes": 38 * G},
                       {"key": "build_cache", "label": "Docker build cache", "bytes": 5 * G},
                       {"key": "media", "label": "Media (videos, stills, voice)", "bytes": 3 * G},
                       {"key": "database", "label": "Database", "bytes": 65 * 1024 ** 2},
                       {"key": "logs", "label": "Logs and journal", "bytes": 0}],
         "would_free": {"releases": 19 * G, "images": 11 * G, "build_cache": 0, "backups": 0, "journal": 0, "other": 0,
                        "total": 30 * G},
         "keep": {"live": "a" * 40, "previous": ["b" * 40], "rollback": "b" * 40, "deploy_backups": 3}}
    r.update(over)
    return r


class DiskTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.path = self.env.tmp / "reports" / "disk-report.json"
        self.path.parent.mkdir()
        os.environ["ODD_DISK_REPORT"] = str(self.path)

    def tearDown(self):
        os.environ.pop("ODD_DISK_REPORT", None)

    def get(self, size, used, free):
        with mock.patch.object(SD, "disk_usage", return_value=(size, used, free)):
            r = self.c.get("/api/system/disk")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def write(self, data):
        self.path.write_text(json.dumps(data) if not isinstance(data, str) else data)

    def test_levels_follow_the_percent_used_as_df_counts_it(self):
        self.write(report())
        for used, free, pct, level in [(50 * G, 46 * G, 53, "ok"), (76 * G, 20 * G, 80, "warn"), (85 * G, 11 * G, 89, "warn"),
                                       (87 * G, 9 * G, 91, "critical"), (96 * G, 0, 100, "critical")]:
            d = self.get(96 * G, used, free)
            self.assertEqual((d["percent"], d["level"]), (pct, level), (used, free))
        self.assertEqual((d["warn_at"], d["critical_at"]), (80, 90))
        self.assertEqual(SD.percent_used(1, 199), 1, "rounded up, like df")

    def test_the_biggest_consumers_come_from_the_report_biggest_first(self):
        self.write(report())
        d = self.get(96 * G, 87 * G, 9 * G)
        self.assertEqual([c["key"] for c in d["biggest"]], ["images", "releases", "backups", "build_cache"])
        self.assertEqual([c["key"] for c in d["report"]["consumers"]][-1], "logs", "every consumer, biggest first")
        self.assertEqual(d["report"]["would_free"]["total"], 30 * G)
        self.assertEqual(d["report"]["mode"], "dry-run")
        self.assertFalse(d["report"]["stale"])
        self.assertIsNone(d["report_problem"])

    def test_after_apply_the_report_says_what_was_freed(self):
        r = report(mode="apply")
        r["freed"] = r.pop("would_free")
        self.write(r)
        d = self.get(96 * G, 50 * G, 46 * G)
        self.assertEqual(d["report"]["freed"]["images"], 11 * G)
        self.assertNotIn("would_free", d["report"])

    def test_no_report_yet_says_how_to_make_one(self):
        d = self.get(96 * G, 87 * G, 9 * G)
        self.assertIsNone(d["report"])
        self.assertEqual(d["biggest"], [])
        self.assertIn("maintenance.sh without options", d["report_problem"])
        self.assertEqual(d["level"], "critical", "the live disk numbers do not need the report")

    def test_a_broken_or_odd_report_is_not_shown(self):
        for bad in ["{not json", json.dumps({"generated_at": "yesterday", "consumers": []}),
                    json.dumps(report(consumers=[{"key": "x", "label": "X", "bytes": -1}])),
                    json.dumps(report(consumers=[{"key": "x", "label": "X", "bytes": "lots"}]))]:
            self.write(bad)
            d = self.get(96 * G, 50 * G, 46 * G)
            self.assertIsNone(d["report"], bad)
            self.assertIn("could not be read", d["report_problem"])

    def test_an_old_report_is_marked_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.write(report(generated_at=old))
        d = self.get(96 * G, 50 * G, 46 * G)
        self.assertTrue(d["report"]["stale"])
        self.assertGreaterEqual(d["report"]["age_days"], 10)

    def test_the_real_disk_is_measured_without_a_mock(self):
        d = self.c.get("/api/system/disk").json()
        self.assertGreater(d["size"], 0)
        self.assertTrue(0 <= d["percent"] <= 100)
        self.assertLessEqual(d["used"], d["size"])

    def test_sign_in_is_required_and_the_route_only_reads(self):
        self.c.post("/api/auth/logout")
        self.assertEqual(self.c.get("/api/system/disk").status_code, 401)
        self.env.login()
        for method in ("post", "put", "delete"):
            self.assertEqual(getattr(self.c, method)("/api/system/disk").status_code, 405, method)


if __name__ == "__main__":
    unittest.main()
