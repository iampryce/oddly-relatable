"""Self-hosted GPU proof of concept (docs/GPU-INFRASTRUCTURE.md §11, §16): the studio side.

Everything is stubbed: RunPod is a fake transport (no account, no network, no cost) and the worker is the real job API
on its stub backend on 127.0.0.1 (no GPU, no model). Covered: settings checks; the monthly cap with reservations; a
rented session launched, reused and terminated when idle; the maximum lifetime; orphan pods; the cap reached while a
clip runs; our own machine by changing one address; and the self-hosted columns of the shot comparison keeping every
guarantee (own art and audio only, our audio under the result, length within one frame, per-run approval)."""
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from test_shot_compare import ShotBase

from oddstudio import gpu, runpod
from oddstudio import shot_compare as SC

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gpu-worker"))
import server as WS  # noqa: E402

WF = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{input:image.png}}"}},
      "2": {"class_type": "LoadAudio", "inputs": {"audio": "{{input:audio.wav}}", "seconds": "{{param:seconds}}"}},
      "3": {"class_type": "Prompt", "inputs": {"text": "{{param:prompt}}", "seed": "{{param:seed}}"}}}
DUB = {"1": {"class_type": "LoadVideo", "inputs": {"video": "{{input:video.mp4}}"}},
       "2": {"class_type": "LoadAudio", "inputs": {"audio": "{{input:audio.wav}}"}}}
IMAGE = "registry.example/oddstudio-gpu-worker@sha256:" + "a" * 64


class FakeRunPod:
    """RunPod's REST API v2 as the adapter uses it. Creating a pod starts a stub worker with the token the studio
    passed in the pod's environment (so the studio talks to it exactly as to a real pod)."""

    def __init__(self, tmp: Path, cost: float = 2.89, ready_after: int = 0):
        self.tmp, self.cost, self.ready_after = tmp, cost, ready_after
        self.pods, self.calls, self.servers, self.n = {}, [], {}, 0

    def __call__(self, method, path, json=None, params=None):
        self.calls.append((method, path, json))
        if path.startswith("/v2/catalog/gpus/"):
            return 200, {"id": path.rsplit("/", 1)[1], "price": {"secure": 2.89, "community": 1.99}}
        if method == "POST" and path == "/v2/pods":
            self.n += 1
            pid = f"pod{self.n}"
            state = self.tmp / pid
            state.mkdir(parents=True)
            if not self.ready_after:
                (state / "ready").touch()
            w = WS.Worker(json["env"]["WORKER_TOKEN"], self.tmp / f"{pid}-jobs", WS.StubBackend(), state_dir=state)
            httpd = WS.serve(w, "127.0.0.1", 0)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.servers[pid] = (httpd, state)
            self.pods[pid] = {"id": pid, "name": json["name"], "status": "RUNNING", "cost": self.cost, "gpu": json["gpu"],
                              "image": json["image"], "env": json["env"], "ports": json["ports"]}
            return 201, self.pods[pid]
        if method == "GET" and path == "/v2/pods":
            return 200, {"pods": [p for p in self.pods.values() if p["status"] != "TERMINATED"],
                         "pagination": {"nextCursor": None, "hasNextPage": False}}
        if path.startswith("/v2/pods/"):
            pid = path.rsplit("/", 1)[1]
            p = self.pods.get(pid)
            if method == "GET":
                return (200, p) if p and p["status"] != "TERMINATED" else (404, {"detail": "not found"})
            if method == "DELETE":
                if not p or p["status"] == "TERMINATED":
                    return 404, {"detail": "not found"}
                p["status"] = "TERMINATED"
                self.servers[pid][0].shutdown()
                self.servers[pid][0].server_close()
                return 204, {}
        if path == "/v2/billing/balance":
            return 200, {"balanceAmount": 24.5, "billingMode": "PREPAID"}
        return 404, {"detail": "no such route"}

    def url(self, pod_id):
        return f"http://127.0.0.1:{self.servers[pod_id][0].server_address[1]}"

    def live(self):
        return [p for p in self.pods.values() if p["status"] != "TERMINATED"]

    def close(self):
        for httpd, _ in self.servers.values():
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass


class GpuTestBase(ShotBase):
    def setUp(self):
        super().setUp()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="gpu-test-"))
        wfdir = self.tmpdir / "workflows"
        wfdir.mkdir()
        for name in ("infinitetalk-480p", "wan-2.2-s2v-480p"):
            (wfdir / f"{name}.json").write_text(json.dumps(WF))
        (wfdir / "latentsync-1.6.json").write_text(json.dumps(DUB))
        self._wfdir, SC.WORKFLOW_DIR = SC.WORKFLOW_DIR, wfdir
        self.rp = FakeRunPod(self.tmpdir / "pods")
        runpod.set_test_transport(self.rp)
        self._url_for, gpu.url_for = gpu.url_for, self.rp.url
        self._sleep, gpu.sleep = gpu.sleep, lambda s: time.sleep(0.02)
        self._clock = gpu.clock

    def tearDown(self):
        SC.WORKFLOW_DIR = self._wfdir
        runpod.set_test_transport(None)
        gpu.url_for, gpu.sleep, gpu.clock = self._url_for, self._sleep, self._clock
        self.rp.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def rented(self, **kw):
        self.c.put("/api/settings/credentials", json={"values": {"runpod_api_key": "rp-test-key"}})
        r = self.c.put("/api/settings/gpu", json={"mode": "rented", "image": IMAGE, **kw})
        self.assertEqual(r.status_code, 200, r.text)

    def row(self, pid):
        return next(p for p in self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()["plans"] if p["id"] == pid)

    def sweep(self):
        from oddstudio.db import new_session
        with new_session() as s:
            return gpu.sweep(s, log=lambda *_: None)


class GpuSettingsTest(GpuTestBase):
    def test_settings_are_checked_and_the_defaults_are_the_accepted_ones(self):
        g = self.c.get("/api/settings").json()["sections"]["gpu"]
        self.assertEqual((g["mode"], g["monthly_cap_usd"], g["warn_at"], g["idle_minutes"], g["max_lifetime_minutes"]),
                         ("off", 50.0, 0.8, 5, 120), "the owner's accepted §13 defaults")
        bad = [{"mode": "always-on"}, {"image": "registry.example/worker:latest"}, {"worker_url": "http://10.0.0.5:8000"},
               {"worker_url": "https://user:pw@gpu.example"}, {"monthly_cap_usd": -1}, {"idle_minutes": 0},
               {"max_lifetime_minutes": 10000}, {"provider": "modal"}, {"gpu_type": "H100; rm -rf"}]
        for v in bad:
            self.assertEqual(self.c.put("/api/settings/gpu", json=v).status_code, 422, v)
        self.assertEqual(self.c.put("/api/settings/gpu", json={"worker_url": "https://gpu.example.internal:8000"}).status_code, 200)

    def test_why_a_self_hosted_clip_cannot_run_is_always_said(self):
        a = self.c.get("/api/gpu").json()
        self.assertEqual((a["ok"], a["reason"]), (False, "Settings > GPU worker: the mode is off"))
        self.c.put("/api/settings/gpu", json={"mode": "rented"})
        self.assertIn("RunPod API key", self.c.get("/api/gpu").json()["reason"])
        self.c.put("/api/settings/credentials", json={"values": {"runpod_api_key": "rp-test-key"}})
        self.assertIn("pinned by digest", self.c.get("/api/gpu").json()["reason"])
        self.c.put("/api/settings/gpu", json={"image": IMAGE})
        a = self.c.get("/api/gpu").json()
        self.assertTrue(a["ok"], a)
        self.assertEqual(a["reservation_usd"], round(2.89 * 125 / 60, 4), "price x (lifetime + 5 min)")
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 5})
        a = self.c.get("/api/gpu").json()
        self.assertFalse(a["ok"])
        self.assertIn("Paused: monthly GPU cap reached", a["reason"])
        self.assertNotIn("rp-test-key", json.dumps(a))
        self.assertEqual(self.rp.calls, [], "checking availability never calls RunPod")


class GpuSessionTest(GpuTestBase):
    def test_a_rented_session_is_launched_reused_and_terminated_when_idle(self):
        gpu.clock = (lambda t: lambda: t)(time.time())   # frozen: "not idle yet" must not depend on how slow the machine is
        self.rented()
        plans = self.batch_ready()
        ids = [p["id"] for p in plans]
        body = {"plan_ids": ids, "models": ["infinitetalk-480p"]}
        s = self.c.post("/api/motion/shot-batch/run", json=body).json()
        self.assertEqual(s["clips"], 2)
        self.assertEqual(s["gpu"]["clips"], 2)
        self.assertTrue(s["fits"])
        self.assertEqual(s["fal_usd"], 0, "self-hosted clips are not on fal.ai's budget")
        exp = round(66.0 * 3.0 * 2.89 / 3600, 4)
        self.assertEqual(s["items"][0]["usd"], exp, "the estimate: GPU seconds at the hourly price")
        self.assertEqual(self.rp.calls, [], "the summary launches nothing")
        r = self.c.post("/api/motion/shot-batch/run", json={**body, "confirm": True, "expected_usd": s["total_usd"]})
        self.assertEqual(r.json()["queued"], 2)
        self.assertEqual(self.rp.calls, [], "approving queues; nothing is launched until the worker runs the clip")
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual([x[1] for x in ran], ["succeeded", "succeeded"], ran)
        creates = [c for c in self.rp.calls if c[0] == "POST"]
        self.assertEqual(len(creates), 1, "one session for both clips")
        sent = creates[0][2]
        self.assertEqual((sent["cloud"], sent["gpu"], sent["image"], sent["ports"]), ("SECURE", {"id": "NVIDIA H100 PCIe", "count": 1}, IMAGE, ["8000/http"]))
        self.assertNotIn("mounts", sent, "no volume: nothing bills after a terminate")
        self.assertTrue(sent["name"].startswith("oddstudio-gpu-"))
        self.assertNotIn("rp-test-key", json.dumps(sent), "the RunPod key never goes to the pod")
        self.assertEqual(sent["env"]["WORKER_MAX_LIFETIME_S"], str(120 * 60 + 600))
        for pid in ids:
            res = self.row(pid)["results"]["infinitetalk-480p"]
            self.assertEqual(res["status"], "done", res)
            self.assertTrue(res["check"]["length_ok"], res["check"])
            self.assertAlmostEqual(res["check"]["audio_seconds"], self.row(pid)["seconds"], delta=1 / 30, msg="our line audio under it")
            self.assertTrue(res["url"])
            self.assertGreaterEqual(res["actual_usd"], 0)
            self.assertIn("GPU session", res["worker"])
        st = self.c.get("/api/gpu").json()
        self.assertEqual(len(st["sessions"]), 1)
        self.assertEqual((st["sessions"][0]["status"], st["sessions"][0]["clips"]), ("ready", 2))
        self.assertEqual(len(self.rp.live()), 1)
        self.assertEqual(self.sweep(), [], "not idle yet")
        t0 = time.time()
        gpu.clock = lambda: t0 + 6 * 60
        done = self.sweep()
        self.assertIn("idle for 5 min", done[0])
        self.assertEqual(self.rp.live(), [], "terminated, not stopped")
        sess = self.c.get("/api/gpu").json()["sessions"][0]
        self.assertEqual(sess["status"], "ended")
        self.assertGreater(sess["cost_usd"], 0, "boot and idle time count")

    def test_maximum_lifetime_orphans_and_vanished_pods(self):
        self.rented()
        plans = self.batch_ready()
        self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "wan-2.2-s2v-480p"})
        self.env.run_jobs(["shot_generate"])
        self.assertEqual(len(self.rp.live()), 1)
        # an orphan: a pod with our prefix that the studio does not know (a crash between create and save, say)
        self.rp("POST", "/v2/pods", {"name": "oddstudio-gpu-lost", "gpu": {"id": "x"}, "image": IMAGE, "env": {"WORKER_TOKEN": "z" * 40}, "ports": []})
        self.rp("POST", "/v2/pods", {"name": "someone-elses-pod", "gpu": {"id": "x"}, "image": IMAGE, "env": {"WORKER_TOKEN": "z" * 40}, "ports": []})
        done = self.sweep()
        self.assertTrue(any("orphan pod pod2" in d for d in done), done)
        self.assertEqual(sorted(p["name"][:14] for p in self.rp.live()), ["oddstudio-gpu-", "someone-elses-"],
                         "only our prefix is touched; the live session stays")
        t0 = time.time()
        gpu.clock = lambda: t0 + 121 * 60
        self.assertIn("maximum lifetime reached", self.sweep()[0])
        self.assertEqual([p["name"] for p in self.rp.live()], ["someone-elses-pod"])
        # a live session whose pod disappeared (deleted in the console) is closed
        gpu.clock = time.time
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 50})
        self.c.post(f"/api/motion/shot/{plans[1]['id']}/run", json={"model": "wan-2.2-s2v-480p"})
        self.env.run_jobs(["shot_generate"])
        pod = next(p for p in self.rp.live() if p["name"].startswith("oddstudio-gpu-"))
        pod["status"] = "TERMINATED"
        self.assertTrue(any("the pod no longer exists" in d for d in self.sweep()))

    def test_the_cap_reached_while_a_clip_runs_stops_it_and_terminates_the_pod(self):
        # The reservation means a session cannot cross the cap by itself; the stop is the backstop for the cap being
        # lowered (or the bill being higher) while a clip runs. Here the owner lowers the cap mid-clip.
        self.rented()
        plans = self.batch_ready()
        self.assertEqual(self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"}).status_code, 200)
        real = SC.gpu_params
        SC.gpu_params = lambda model, p: {**real(model, p), "stub_wait": 3}
        calls = {"n": 0}

        def clock():
            calls["n"] += 1
            if calls["n"] == 60:
                from oddstudio.db import new_session
                from oddstudio.settings_store import put_section
                with new_session() as s:
                    put_section(s, "gpu", {"monthly_cap_usd": 0.0})
            return time.time()
        gpu.clock = clock
        try:
            ran = self.env.run_jobs(["shot_generate"])
        finally:
            SC.gpu_params = real
        self.assertGreaterEqual(calls["n"], 60, "the clip was still running when the cap changed")
        self.assertEqual(ran[0][1], "failed", ran)
        res = self.row(plans[0]["id"])["results"]["infinitetalk-480p"]
        self.assertIn("Stopped: monthly GPU cap reached", res["error"])
        self.assertEqual(self.rp.live(), [], "the pod is terminated")
        a = self.c.get("/api/gpu").json()
        self.assertFalse(a["ok"])
        self.assertIn("Paused", a["reason"])
        r = self.c.post(f"/api/motion/shot/{plans[1]['id']}/run", json={"model": "infinitetalk-480p"})
        self.assertEqual(r.status_code, 409, "no new session past the cap")
        self.assertIn("monthly GPU cap", r.text)

    def test_a_launch_never_passes_the_cap(self):
        self.rented(monthly_cap_usd=6.0)      # the reservation (2.89/h x 125 min = $6.02) does not fit
        plans = self.batch_ready()
        r = self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("a new session reserves $6.02", r.text)
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 6.1})
        self.assertEqual(self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"}).status_code, 200)
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 6.0})       # lowered after approval, before the run
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("monthly GPU cap", self.row(plans[0]["id"])["results"]["infinitetalk-480p"]["error"])
        self.assertEqual([c for c in self.rp.calls if c[0] == "POST"], [], "nothing was launched")

    def test_a_worker_that_cannot_start_is_terminated(self):
        self.rented()
        self.rp.ready_after = 1        # the pod's worker never becomes ready
        plans = self.batch_ready()
        self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"})

        orig = self.rp.__class__.__call__

        def failing(rp, method, path, json=None, params=None):
            st = orig(rp, method, path, json, params)
            if method == "POST" and path == "/v2/pods":
                (rp.servers[st[1]["id"]][1] / "failed").write_text("checksum mismatch for wan.safetensors")
            return st
        self.rp.__class__.__call__ = failing
        try:
            ran = self.env.run_jobs(["shot_generate"])
        finally:
            self.rp.__class__.__call__ = orig
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("could not start", self.row(plans[0]["id"])["results"]["infinitetalk-480p"]["error"])
        self.assertEqual(self.rp.live(), [])

    def test_a_session_whose_worker_stopped_answering_is_replaced_not_reused(self):
        self.rented()
        plans = self.batch_ready()
        self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"})
        self.env.run_jobs(["shot_generate"])
        httpd, _ = self.rp.servers["pod1"]
        httpd.shutdown()
        httpd.server_close()            # the pod is still billed, but its worker no longer answers
        self.c.post(f"/api/motion/shot/{plans[1]['id']}/run", json={"model": "infinitetalk-480p"})
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(self.rp.pods["pod1"]["status"], "TERMINATED", "the silent session's pod is terminated")
        self.assertEqual([p["id"] for p in self.rp.live()], ["pod2"])
        ss = {s["id"]: s for s in self.c.get("/api/gpu").json()["sessions"]}
        self.assertEqual(sorted(s["status"] for s in ss.values()), ["ended", "ready"])
        self.assertIn("stopped answering", next(s for s in ss.values() if s["status"] == "ended")["reason"])

    def test_the_owner_can_stop_a_session(self):
        self.rented()
        plans = self.batch_ready()
        self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"})
        self.env.run_jobs(["shot_generate"])
        sid = self.c.get("/api/gpu").json()["sessions"][0]["id"]
        r = self.c.post(f"/api/gpu/sessions/{sid}/terminate")
        self.assertEqual(r.json()["status"], "ended")
        self.assertIn("terminated by", r.json()["reason"])
        self.assertEqual(self.rp.live(), [])
        self.assertEqual(self.c.get("/api/gpu/balance").json()["balance_usd"], 24.5)


class GpuShotComparisonTest(GpuTestBase):
    def test_our_own_machine_is_one_address_and_costs_nothing(self):
        state = self.tmpdir / "own"
        state.mkdir()
        (state / "ready").touch()
        w = WS.Worker("o" * 40, self.tmpdir / "own-jobs", WS.StubBackend(), state_dir=state)
        httpd = WS.serve(w, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            self.c.put("/api/settings/credentials", json={"values": {"gpu_worker_token": "o" * 40}})
            self.c.put("/api/settings/gpu", json={"mode": "own", "worker_url": f"http://127.0.0.1:{httpd.server_address[1]}"})
            plans = self.batch_ready()
            req = {r["model"]: r for r in plans[0]["requests"]}
            self.assertEqual(req["infinitetalk-480p"]["estimate"]["usd"], 0.0)
            self.assertEqual(req["infinitetalk-480p"]["sends"],
                             ["the medium first frame (approved set + approved neutral pose)", "the line's own recorded audio"])
            self.assertEqual(req["infinitetalk-480p"]["body"]["inputs"], ["image.png", "audio.wav"], "files, never URLs")
            self.assertEqual(self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "infinitetalk-480p"}).status_code, 200)
            ran = self.env.run_jobs(["shot_generate"])
            self.assertEqual(ran[0][1], "succeeded", ran)
            res = self.row(plans[0]["id"])["results"]["infinitetalk-480p"]
            self.assertEqual((res["status"], res["actual_usd"], res["worker"]), ("done", 0.0, "our own machine"))
            self.assertTrue(res["check"]["length_ok"])
            self.assertEqual(self.rp.calls, [], "no provider involved")
            self.assertEqual(w.jobs, {}, "the job's files are deleted on the worker once the studio has the clip")
            # a failed clip's job does not stay on the worker either, and a later submission never reuses its id
            real = SC.gpu_params
            SC.gpu_params = lambda model, p: {**real(model, p), "stub_fail": "out of memory (test)"}
            try:
                self.c.post(f"/api/motion/shot/{plans[1]['id']}/run", json={"model": "infinitetalk-480p"})
                ran = self.env.run_jobs(["shot_generate"])
            finally:
                SC.gpu_params = real
            self.assertEqual(ran[0][1], "failed")
            self.assertIn("out of memory", self.row(plans[1]["id"])["results"]["infinitetalk-480p"]["error"])
            self.assertEqual(w.jobs, {}, "the failed job's files are deleted too")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_guarantees_and_refusals(self):
        import os
        os.environ.pop("PUBLIC_URL", None)        # self-hosted clips need no public URL (files travel in the request)
        self.rented()
        plans = self.batch_ready()
        pid = plans[0]["id"]
        opts = self.c.get("/api/motion/shot/options", params={"episode_id": self.eid}).json()
        self.assertEqual([m["id"] for m in opts["gpu_models"]], list(SC.GPU_MODELS))
        self.assertTrue(all("Apache-2.0" in m["licence"] for m in opts["gpu_models"]))
        # lip-sync over the Kling clip needs that clip first
        r = self.c.post(f"/api/motion/shot/{pid}/run", json={"model": "latentsync-1.6"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("needs this line's Kling 2.6 Pro", r.text)
        # a model whose workflow is not pinned cannot run
        (SC.WORKFLOW_DIR / "wan-2.2-s2v-480p.json").unlink()
        r = self.c.post(f"/api/motion/shot/{pid}/run", json={"model": "wan-2.2-s2v-480p"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("workflow is not pinned", r.text)
        s = self.c.post("/api/motion/shot-batch/run", json={"plan_ids": [pid], "models": ["wan-2.2-s2v-480p", "latentsync-1.6"]}).json()
        self.assertEqual(s["clips"], 0)
        self.assertEqual(len(s["skipped"]), 2)
        # mode off: refused with the reason, before anything is queued
        self.c.put("/api/settings/gpu", json={"mode": "off"})
        r = self.c.post(f"/api/motion/shot/{pid}/run", json={"model": "infinitetalk-480p"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("the mode is off", r.text)
        b = {"plan_ids": [pid], "models": ["infinitetalk-480p"]}
        s = self.c.post("/api/motion/shot-batch/run", json=b).json()
        self.assertFalse(s["fits"])
        self.assertEqual(self.c.post("/api/motion/shot-batch/run", json={**b, "confirm": True, "expected_usd": s["total_usd"]}).status_code, 409)
        self.assertEqual(self.rp.calls, [])

    def test_lip_sync_over_our_kling_clip_and_fal_budget_untouched(self):
        self.rented()
        plans = self.batch_ready()
        pid = plans[0]["id"]
        self.stub({"i2v": 5, "avatar": 3.04})
        self.c.post(f"/api/motion/shot/{pid}/run", json={"model": "kling-2.6-pro-i2v"})
        self.env.run_jobs(["shot_generate"])
        self.assertEqual(self.c.post(f"/api/motion/shot/{pid}/run", json={"model": "latentsync-1.6"}).status_code, 200)
        b = self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()
        self.assertEqual(b["pending_usd"], 0, "a queued self-hosted clip is not counted on fal.ai's budget")
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        res = self.row(pid)["results"]["latentsync-1.6"]
        self.assertEqual(res["status"], "done")
        self.assertTrue(res["check"]["length_ok"])
        self.assertTrue(res["workflow_sha256"])
        from oddstudio import fal
        from oddstudio.db import new_session
        with new_session() as s:
            self.assertAlmostEqual(fal.spent(s)["total"], 0.35, places=3, msg="only the Kling clip is on fal.ai's ledger")
