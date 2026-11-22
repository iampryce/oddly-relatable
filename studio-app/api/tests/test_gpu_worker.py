"""The GPU worker's HTTP job API (studio-app/gpu-worker/server.py), on its stub backend: no GPU, no model, no network
beyond 127.0.0.1. Auth on every call, idempotent submit, outputs with SHA-256, cancel, delete, input checks, the
readiness gate and the self-limit (layer 4 of the idle shutdown)."""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gpu-worker"))
import server as WS  # noqa: E402

TOKEN = "t" * 40
WF = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{input:image.png}}"}},
      "2": {"class_type": "Seconds", "inputs": {"seconds": "{{param:seconds}}"}}}
SHA = hashlib.sha256(json.dumps(WF, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def png_b64() -> str:
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (64, 112), (200, 100, 50)).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def start(worker: WS.Worker):
    httpd = WS.serve(worker, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@unittest.skipUnless(shutil.which(os.environ.get("FFMPEG", "ffmpeg")), "needs ffmpeg")
class WorkerApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gpu-worker-test-"))
        self.now = [1000.0]
        self.w = WS.Worker(TOKEN, self.tmp / "jobs", WS.StubBackend(), max_lifetime_s=600, idle_s=120, max_body=4 << 20,
                           clock=lambda: self.now[0])
        self.httpd, self.url = start(self.w)
        self.h = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def job(self, jid="j1-a1", **params):
        return {"id": jid, "kind": "comfyui-workflow", "workflow": WF, "workflow_sha256": SHA,
                "params": {"seconds": 1.2, **params}, "inputs": {"image.png": png_b64()}}

    def wait(self, jid):
        for _ in range(400):
            st = httpx.get(f"{self.url}/jobs/{jid}", headers=self.h).json()
            if st["status"] not in ("queued", "running"):
                return st
            time.sleep(0.05)
        self.fail("the job did not finish")

    def test_every_call_needs_the_token(self):
        for method, path in (("GET", "/health"), ("POST", "/jobs"), ("GET", "/jobs/x"), ("DELETE", "/jobs/x")):
            self.assertEqual(httpx.request(method, self.url + path).status_code, 401, path)
            self.assertEqual(httpx.request(method, self.url + path, headers={"Authorization": "Bearer " + "u" * 40}).status_code, 401)
        self.assertEqual(httpx.get(self.url + "/health", headers=self.h).json()["ready"], True)
        with self.assertRaises(ValueError):
            WS.Worker("short", self.tmp / "x", WS.StubBackend())

    def test_a_job_runs_once_and_its_output_matches_its_checksum(self):
        r = httpx.post(self.url + "/jobs", headers=self.h, json=self.job())
        self.assertEqual(r.status_code, 202, r.text)
        again = httpx.post(self.url + "/jobs", headers=self.h, json=self.job())
        self.assertEqual(again.status_code, 200, "the same submit again does not run twice")
        st = self.wait("j1-a1")
        self.assertEqual(st["status"], "done", st)
        self.assertGreaterEqual(st["gpu_seconds"], 0)
        out = st["outputs"][0]
        self.assertEqual(out["name"], "video.mp4")
        data = httpx.get(f"{self.url}/jobs/j1-a1/outputs/video.mp4", headers=self.h).content
        self.assertEqual(hashlib.sha256(data).hexdigest(), out["sha256"])
        other = {**self.job(), "workflow": {"1": {"inputs": {}}}}
        other["workflow_sha256"] = hashlib.sha256(json.dumps(other["workflow"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(httpx.post(self.url + "/jobs", headers=self.h, json=other).status_code, 409, "a different job with the same id")
        self.assertEqual(httpx.delete(f"{self.url}/jobs/j1-a1", headers=self.h).status_code, 200)
        self.assertFalse((self.tmp / "jobs" / "j1-a1").exists(), "the job's files are deleted")
        self.assertEqual(httpx.get(f"{self.url}/jobs/j1-a1", headers=self.h).status_code, 404)

    def test_bad_jobs_are_refused_before_anything_runs(self):
        bad = [({**self.job(), "id": "../x"}, "id"), ({**self.job(), "kind": "shell"}, "kind"),
               ({**self.job(), "workflow_sha256": "0" * 64}, "sha256"),
               ({**self.job(), "inputs": {"../evil.png": png_b64()}}, "input name"),
               ({**self.job(), "inputs": {"image.png": "%%%"}}, "base64"),
               ({**self.job(), "params": {}}, "param 'seconds'")]
        for body, why in bad:
            r = httpx.post(self.url + "/jobs", headers=self.h, json=body)
            self.assertEqual(r.status_code, 400, why)
        big = httpx.post(self.url + "/jobs", headers=self.h, content=b"x" * (5 << 20))
        self.assertEqual(big.status_code, 413)
        self.assertEqual(httpx.get(f"{self.url}/jobs/j1-a1/outputs/..%2F..%2Fetc", headers=self.h).status_code, 404)
        self.assertEqual(self.w.jobs, {})

    def test_a_failed_and_a_cancelled_job(self):
        httpx.post(self.url + "/jobs", headers=self.h, json=self.job("f1", stub_fail="model out of memory (test)"))
        st = self.wait("f1")
        self.assertEqual((st["status"], st["error"]), ("failed", "model out of memory (test)"))
        httpx.post(self.url + "/jobs", headers=self.h, json=self.job("c1", stub_wait=5))
        time.sleep(0.2)
        self.assertEqual(httpx.delete(f"{self.url}/jobs/c1", headers=self.h).status_code, 409, "not while running")
        httpx.post(f"{self.url}/jobs/c1/cancel", headers=self.h)
        self.assertEqual(self.wait("c1")["status"], "cancelled")

    def test_the_self_limit_refuses_new_jobs(self):
        self.now[0] += 121
        h = httpx.get(self.url + "/health", headers=self.h).json()
        self.assertEqual(h["expired"], "idle limit reached")
        r = httpx.post(self.url + "/jobs", headers=self.h, json=self.job())
        self.assertEqual(r.status_code, 503)
        self.now[0] += 600
        self.assertEqual(httpx.get(self.url + "/health", headers=self.h).json()["expired"], "maximum lifetime reached")

    def test_not_ready_until_the_entrypoint_says_so(self):
        state = self.tmp / "state"
        state.mkdir()
        w = WS.Worker(TOKEN, self.tmp / "jobs2", WS.StubBackend(), state_dir=state)
        httpd, url = start(w)
        try:
            self.assertFalse(httpx.get(url + "/health", headers=self.h).json()["ready"])
            self.assertEqual(httpx.post(url + "/jobs", headers=self.h, json=self.job()).status_code, 503)
            (state / "failed").write_text("checksum mismatch for model.safetensors")
            self.assertIn("checksum", httpx.get(url + "/health", headers=self.h).json()["failed"])
            (state / "failed").unlink()
            (state / "ready").touch()
            self.assertEqual(httpx.post(url + "/jobs", headers=self.h, json=self.job()).status_code, 202)
        finally:
            httpd.shutdown()
            httpd.server_close()


class SubstituteTest(unittest.TestCase):
    def test_placeholders_are_filled_or_refused(self):
        g = WS.substitute(WF, {"image.png": "job/image.png"}, {"seconds": 2.5})
        self.assertEqual(g["1"]["inputs"]["image"], "job/image.png")
        self.assertEqual(g["2"]["inputs"]["seconds"], 2.5, "a whole-string parameter keeps its type")
        with self.assertRaises(WS.JobError):
            WS.substitute(WF, {}, {"seconds": 1})
        with self.assertRaises(WS.JobError):
            WS.substitute({"a": "{{shell:rm}}"}, {}, {})


class FetchModelsTest(unittest.TestCase):
    def test_the_weights_manifest_must_be_pinned(self):
        import fetch_models as FM
        root = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(SystemExit):
                FM.check([], root)
            with self.assertRaises(SystemExit):
                FM.check([{"url": "http://x/a", "path": "a", "sha256": "0" * 64, "licence": "Apache-2.0"}], root)
            with self.assertRaises(SystemExit):
                FM.check([{"url": "https://x/a", "path": "../a", "sha256": "0" * 64, "licence": "Apache-2.0"}], root)
            with self.assertRaises(SystemExit):
                FM.check([{"url": "https://x/a", "path": "a", "sha256": "0" * 64}], root)
            ok = FM.check([{"url": "https://huggingface.co/x/resolve/abc123/a.safetensors", "path": "diffusion/a.safetensors",
                            "sha256": "0" * 64, "licence": "Apache-2.0"}], root)
            self.assertEqual(ok[0][1], (root / "diffusion/a.safetensors").resolve())
            lock = Path(__file__).resolve().parents[2] / "gpu-worker" / "models.lock"
            self.assertEqual(json.loads(lock.read_text()), [], "nothing is pinned until the PoC's $0 step")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
