"""Oddly Relatable GPU worker: a small HTTP job API in front of ComfyUI (docs/GPU-INFRASTRUCTURE.md §11.2).

The same plain Docker image runs on a rented pod or on a machine we own; the studio only needs its address and token.
The studio calls the worker; the worker never calls the studio and holds no studio or provider credential. It keeps
only in-memory job state: if it disappears, only the running job is lost (the studio retries it).

API (every call needs "Authorization: Bearer <WORKER_TOKEN>"):
  GET    /health                       version, backend, GPU, busy/queued, self-limit
  POST   /jobs                         {"id", "kind": "comfyui-workflow", "workflow": {...}, "workflow_sha256",
                                        "params": {...}, "inputs": {"name": "<base64>"}} -> 202 {"id", "status"}
                                        (the id is the studio's job id and attempt: a repeated submit does not run twice)
  GET    /jobs/<id>                    status, progress, log tail, gpu_seconds, outputs (name, size, sha256)
  GET    /jobs/<id>/outputs/<name>     one output file
  POST   /jobs/<id>/cancel             cancel (queued or running)
  DELETE /jobs/<id>                    delete the job's files once the studio has its outputs

Self-limit (layer 4 of the idle shutdown, §11.1): after WORKER_MAX_LIFETIME_S, or WORKER_IDLE_S without a job, the
worker refuses new jobs and reports "expired". It cannot stop billing itself: the studio terminates the pod.

Backends: "comfyui" (the image's ComfyUI on 127.0.0.1:8188, the workflow graph comes from the studio with placeholders
"{{input:<name>}}" and "{{param:<key>}}") and "stub" (tests and smoke checks without a GPU: FFmpeg makes a clip of the
input image or video, no model involved). Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlreq

VERSION = "1"
ID_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}\.(png|jpg|jpeg|wav|mp3|m4a|mp4|webm|json)$")
PLACEHOLDER = re.compile(r"^\{\{(input|param):([A-Za-z0-9._-]{1,64})\}\}$")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".gif")
KINDS = ("comfyui-workflow",)


class JobError(Exception):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def substitute(node, inputs: dict, params: dict):
    """The studio's workflow graph with its placeholders filled in. A placeholder must be the whole string; an unknown
    input or parameter is an error (nothing is guessed)."""
    if isinstance(node, dict):
        return {k: substitute(v, inputs, params) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute(v, inputs, params) for v in node]
    if isinstance(node, str) and node.startswith("{{"):
        m = PLACEHOLDER.match(node)
        if not m:
            raise JobError(f"malformed placeholder {node[:40]!r}")
        kind, key = m.groups()
        src = inputs if kind == "input" else params
        if key not in src:
            raise JobError(f"the workflow needs {kind} {key!r}, which the job does not carry")
        return src[key]
    return node


class StubBackend:
    """No model: a clip made from the input image (or video) for params.seconds, so the API, the transfers and the
    studio's own steps can be tested without a GPU."""
    name = "stub"

    def run(self, job: dict, folder: Path, cancel: threading.Event, log) -> list[Path]:
        params = job["params"]
        if params.get("stub_fail"):
            raise JobError(str(params["stub_fail"])[:200])
        if params.get("stub_wait"):
            end = time.time() + float(params["stub_wait"])
            while time.time() < end:
                if cancel.is_set():
                    raise JobError("cancelled")
                time.sleep(0.05)
        seconds = max(0.2, min(60.0, float(params.get("seconds") or 3)))
        out = folder / "out" / "video.mp4"
        ins = {n: folder / "in" / n for n in job["inputs"]}
        src = next((p for n, p in ins.items() if n.endswith((".mp4", ".webm"))), None) or \
            next((p for n, p in ins.items() if n.endswith((".png", ".jpg", ".jpeg"))), None)
        ff = os.environ.get("FFMPEG", "ffmpeg")
        if src is not None and src.suffix in (".png", ".jpg", ".jpeg"):
            args = ["-loop", "1", "-framerate", "25", "-i", str(src)]
        elif src is not None:
            args = ["-stream_loop", "-1", "-i", str(src)]
        else:
            args = ["-f", "lavfi", "-i", "color=c=gray:s=480x832:r=25"]
        r = subprocess.run([ff, "-v", "error", "-y", *args, "-t", f"{seconds:.3f}", "-an", "-vf",
                            "scale=480:832:force_original_aspect_ratio=decrease,pad=480:832:(ow-iw)/2:(oh-ih)/2,fps=25",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise JobError("ffmpeg: " + r.stderr.strip()[-200:])
        log(f"stub: {seconds:.2f} s clip")
        return [out]


class ComfyBackend:
    """The image's ComfyUI: inputs are copied into its input folder, the graph is submitted, and the first video it
    writes is the job's output."""
    name = "comfyui"

    def __init__(self, url: str, input_dir: Path, output_dir: Path):
        self.url, self.input_dir, self.output_dir = url.rstrip("/"), input_dir, output_dir

    def _call(self, path: str, body: dict | None = None, timeout: int = 30) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urlreq.Request(self.url + path, data=data, headers={"Content-Type": "application/json"} if data else {})
        with urlreq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def run(self, job: dict, folder: Path, cancel: threading.Event, log) -> list[Path]:
        sub = self.input_dir / job["id"]
        sub.mkdir(parents=True, exist_ok=True)
        rel = {}
        for n in job["inputs"]:
            shutil.copyfile(folder / "in" / n, sub / n)
            rel[n] = f"{job['id']}/{n}"
        graph = substitute(job["workflow"], rel, job["params"])
        pid = self._call("/prompt", {"prompt": graph, "client_id": job["id"]}).get("prompt_id")
        if not pid:
            raise JobError("ComfyUI did not accept the workflow")
        log(f"comfyui: prompt {pid}")
        while True:
            if cancel.is_set():
                try:
                    self._call("/interrupt", {})
                finally:
                    raise JobError("cancelled")
            h = self._call(f"/history/{pid}").get(pid)
            if h:
                st = h.get("status") or {}
                if st.get("status_str") == "error":
                    msgs = [m for m in st.get("messages") or [] if m and m[0] == "execution_error"]
                    raise JobError("ComfyUI: " + json.dumps(msgs[-1][1] if msgs else st)[:300])
                if st.get("completed", True):
                    break
            time.sleep(2)
        outs = []
        for node in (h.get("outputs") or {}).values():
            for key in ("gifs", "videos", "images"):
                for f in node.get(key) or []:
                    p = self.output_dir / (f.get("subfolder") or "") / f["filename"]
                    if p.suffix.lower() in VIDEO_EXT and p.is_file():
                        outs.append(p)
        if not outs:
            raise JobError("ComfyUI finished without a video output")
        dst = folder / "out" / ("video" + outs[0].suffix.lower())
        shutil.copyfile(outs[0], dst)
        return [dst]


class Worker:
    def __init__(self, token: str, root: Path, backend, max_lifetime_s: float = 7800, idle_s: float = 900,
                 max_body: int = 64 << 20, clock=time.time, state_dir: Path | None = None):
        if len(token or "") < 32:
            raise ValueError("WORKER_TOKEN must be at least 32 characters")
        self.token, self.root, self.backend = token, root, backend
        self.max_lifetime_s, self.idle_s, self.max_body, self.clock = max_lifetime_s, idle_s, max_body, clock
        self.state_dir = state_dir        # the entrypoint writes "ready" (weights checked, ComfyUI up) or "failed" here
        self.started = self.last_activity = clock()
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue()
        root.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------------------------------------------------------------- state
    def busy(self) -> bool:
        return any(j["status"] in ("queued", "running") for j in self.jobs.values())

    def expired(self) -> str:
        now = self.clock()
        if now - self.started > self.max_lifetime_s:
            return "maximum lifetime reached"
        if not self.busy() and now - self.last_activity > self.idle_s:
            return "idle limit reached"
        return ""

    def readiness(self) -> tuple[bool, str]:
        """Ready once the entrypoint has checked the weights and started ComfyUI (always ready without a state dir)."""
        if self.state_dir is None:
            return True, ""
        failed = self.state_dir / "failed"
        if failed.is_file():
            return False, failed.read_text()[:300]
        return (self.state_dir / "ready").is_file(), ""

    def health(self) -> dict:
        ready, failed = self.readiness()
        return {"ok": True, "ready": ready, "failed": failed, "version": VERSION, "backend": self.backend.name, "image": os.environ.get("IMAGE_DIGEST", ""),
                "gpu": gpu_info(), "busy": self.busy(), "queued": sum(j["status"] == "queued" for j in self.jobs.values()),
                "expired": self.expired(), "seconds_left": max(0, round(self.max_lifetime_s - (self.clock() - self.started)))}

    def public(self, j: dict) -> dict:
        return {k: j.get(k) for k in ("id", "status", "error", "created", "started", "finished", "gpu_seconds",
                                      "outputs", "workflow_sha256")} | {"log_tail": j["log"][-20:]}

    # ---------------------------------------------------------------- calls
    def submit(self, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict):
            raise JobError("the job must be a JSON object")
        jid = str(body.get("id") or "")
        if not ID_RX.match(jid):
            raise JobError("id: letters, digits, '.', '_' or '-', at most 80 characters")
        with self.lock:
            if jid in self.jobs:
                j = self.jobs[jid]
                if j["workflow_sha256"] != body.get("workflow_sha256"):
                    return 409, {"error": "a different job already has this id"}
                return 200, self.public(j)          # idempotent: the same submit again does not run twice
            why = self.expired()
            if why:
                return 503, {"error": f"the worker is not taking jobs: {why}"}
            ready, failed = self.readiness()
            if not ready:
                return 503, {"error": f"the worker is not ready: {failed or 'still starting'}"}
        if body.get("kind") not in KINDS:
            raise JobError(f"kind must be one of {', '.join(KINDS)}")
        wf, params, inputs = body.get("workflow"), body.get("params") or {}, body.get("inputs") or {}
        if not isinstance(wf, dict) or not wf:
            raise JobError("workflow: a ComfyUI API-format graph is required")
        sha = hashlib.sha256(json.dumps(wf, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if body.get("workflow_sha256") != sha:
            raise JobError("workflow_sha256 does not match the workflow sent")
        if not isinstance(params, dict) or not isinstance(inputs, dict) or len(inputs) > 8:
            raise JobError("params and inputs must be objects (at most 8 inputs)")
        folder = self.root / jid
        (folder / "in").mkdir(parents=True, exist_ok=True)
        (folder / "out").mkdir(parents=True, exist_ok=True)
        try:
            for name, b64 in inputs.items():
                if not NAME_RX.match(name) or not isinstance(b64, str):
                    raise JobError(f"input name {name[:40]!r} is not allowed")
                (folder / "in" / name).write_bytes(base64.b64decode(b64, validate=True))
            substitute(wf, {n: n for n in inputs}, params)      # every placeholder can be filled: checked up front
        except (ValueError, JobError) as e:
            shutil.rmtree(folder, ignore_errors=True)
            raise JobError(str(e)) from None
        j = {"id": jid, "status": "queued", "error": "", "created": self.clock(), "started": None, "finished": None,
             "gpu_seconds": None, "outputs": [], "workflow_sha256": sha, "log": [], "cancel": threading.Event(),
             "workflow": wf, "params": params, "inputs": list(inputs)}
        with self.lock:
            self.jobs[jid] = j
            self.last_activity = self.clock()
        self.q.put(jid)
        return 202, self.public(j)

    def cancel(self, jid: str) -> dict:
        j = self.jobs[jid]
        j["cancel"].set()
        if j["status"] == "queued":
            j.update(status="cancelled", finished=self.clock())
        return self.public(j)

    def delete(self, jid: str) -> tuple[int, dict]:
        j = self.jobs[jid]
        if j["status"] in ("queued", "running"):
            return 409, {"error": "cancel the job first"}
        shutil.rmtree(self.root / jid, ignore_errors=True)
        with self.lock:
            self.jobs.pop(jid, None)
        return 200, {"deleted": jid}

    def output_path(self, jid: str, name: str) -> Path | None:
        j = self.jobs.get(jid)
        if not j or name not in {o["name"] for o in j["outputs"]}:
            return None
        return self.root / jid / "out" / name

    # ---------------------------------------------------------------- runner (one job at a time)
    def _loop(self):
        while True:
            jid = self.q.get()
            j = self.jobs.get(jid)
            if not j or j["status"] != "queued":
                continue
            j.update(status="running", started=self.clock())
            log = lambda t, j=j: j["log"].append(f"{time.strftime('%H:%M:%S')} {t}"[:300])
            t0 = time.monotonic()
            try:
                outs = self.backend.run(j, self.root / jid, j["cancel"], log)
                j["outputs"] = [{"name": p.name, "size": p.stat().st_size, "sha256": sha256_file(p)} for p in outs]
                j["status"] = "cancelled" if j["cancel"].is_set() else "done"
            except Exception as e:  # noqa: BLE001 -- reported to the studio as the job's error
                j.update(status="cancelled" if j["cancel"].is_set() else "failed", error=str(e)[:300])
            j.update(finished=self.clock(), gpu_seconds=round(time.monotonic() - t0, 2))
            self.last_activity = self.clock()


def gpu_info() -> str:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()[:200] if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def make_handler(w: Worker):
    class H(BaseHTTPRequestHandler):
        server_version = "oddstudio-gpu-worker"
        sys_version = ""

        def log_message(self, fmt, *args):   # no request logging (no tokens or paths in logs)
            pass

        def _send(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorised(self) -> bool:
            got = self.headers.get("Authorization", "")
            ok = got.startswith("Bearer ") and hmac.compare_digest(got[7:].encode(), w.token.encode())
            if not ok:
                self._send(401, {"error": "unauthorised"})
            return ok

        def _route(self):
            parts = [p for p in self.path.split("?")[0].split("/") if p]
            if parts and parts[0] == "jobs" and len(parts) > 1 and not ID_RX.match(parts[1]):
                return None
            return parts

        def do_GET(self):
            if not self._authorised():
                return
            parts = self._route()
            if parts == ["health"]:
                return self._send(200, w.health())
            if parts and parts[0] == "jobs" and len(parts) == 2 and parts[1] in w.jobs:
                return self._send(200, w.public(w.jobs[parts[1]]))
            if parts and parts[0] == "jobs" and len(parts) == 4 and parts[2] == "outputs":
                p = w.output_path(parts[1], parts[3])
                if p is None or not p.is_file():
                    return self._send(404, {"error": "no such output"})
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(p.stat().st_size))
                self.end_headers()
                with open(p, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
                return
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorised():
                return
            parts = self._route()
            if parts == ["jobs"]:
                raw = self.headers.get("Content-Length") or ""
                if not raw.isdigit():
                    return self._send(400, {"error": "Content-Length is required"})
                n = int(raw)
                if n <= 0 or n > w.max_body:
                    return self._send(413, {"error": f"the job must be between 1 byte and {w.max_body} bytes"})
                try:
                    code, body = w.submit(json.loads(self.rfile.read(n)))
                except (JobError, ValueError) as e:
                    return self._send(400, {"error": str(e)[:300]})
                return self._send(code, body)
            if parts and len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel" and parts[1] in w.jobs:
                return self._send(200, w.cancel(parts[1]))
            return self._send(404, {"error": "not found"})

        def do_DELETE(self):
            if not self._authorised():
                return
            parts = self._route()
            if parts and len(parts) == 2 and parts[0] == "jobs" and parts[1] in w.jobs:
                return self._send(*w.delete(parts[1]))
            return self._send(404, {"error": "not found"})

    return H


def serve(w: Worker, host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(w))
    httpd.daemon_threads = True
    return httpd


def main() -> None:
    env = os.environ
    root = Path(env.get("WORKER_ROOT", "/work/jobs"))
    if env.get("WORKER_BACKEND", "comfyui") == "stub":
        backend = StubBackend()
    else:
        comfy = Path(env.get("COMFYUI_DIR", "/opt/ComfyUI"))
        backend = ComfyBackend(env.get("COMFYUI_URL", "http://127.0.0.1:8188"), comfy / "input", comfy / "output")
    state = Path(env["WORKER_STATE_DIR"]) if env.get("WORKER_STATE_DIR") else None
    w = Worker(env.get("WORKER_TOKEN", ""), root, backend, float(env.get("WORKER_MAX_LIFETIME_S", 7800)),
               float(env.get("WORKER_IDLE_S", 900)), int(env.get("WORKER_MAX_BODY", 64 << 20)), state_dir=state)
    serve(w, "0.0.0.0", int(env.get("WORKER_PORT", 8000))).serve_forever()


if __name__ == "__main__":
    main()
