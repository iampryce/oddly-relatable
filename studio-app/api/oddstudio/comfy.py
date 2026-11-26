"""A small client for a ComfyUI server reached through RunPod's HTTPS proxy (ported from the owner-verified test client,
2026-11-26). Used by the rented ComfyUI sessions (comfy_session.py) for the talking shots.

Every request carries the session password as a Bearer token (the official runpod/comfyui image checks it) and the
User-Agent "curl/8.7.1": Cloudflare in front of the proxy blocks the default Python agent. The password is never logged
or returned.

Calls used:
  GET  /system_stats                       ComfyUI is up (200)
  POST /upload/image (multipart)           puts a file (image, audio or video) in ComfyUI's input folder
  POST /prompt {prompt, client_id}         queues a graph -> {prompt_id, node_errors}
  GET  /history/{id}                       status and outputs of a queued graph
  GET  /view?filename&subfolder&type       downloads one output
  GET  /models/{folder}                    the model files ComfyUI sees in one folder
  POST /v2/manager/queue/install_model     ComfyUI-Manager: queue one model download (needs Sec-Fetch-Site and Origin)
  POST /v2/manager/queue/start             ComfyUI-Manager: start the queued downloads
  GET  /v2/manager/queue/status            {is_processing, pending_count, ...}
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

import httpx

from .providers import ProviderError

UA = "curl/8.7.1"          # Cloudflare blocks python-httpx's default agent on the RunPod proxy
_transport = None          # tests only: an httpx transport (httpx.MockTransport) instead of the network


def set_test_transport(t) -> None:
    global _transport
    _transport = t


class ComfyError(ProviderError):
    """ComfyUI refused or failed a request. Never retried automatically (GPU time is paid)."""

    def __init__(self, message: str):
        super().__init__(message, transient=False)


def proxy_url(pod_id: str, port: int = 8188) -> str:
    return f"https://{pod_id}-{port}.proxy.runpod.net"


class Client:
    def __init__(self, base: str, password: str):
        self.base = base.rstrip("/")
        self._h = {"Authorization": f"Bearer {password}", "User-Agent": UA}

    # -------------------------------------------------------------- plumbing
    def _req(self, method: str, path: str, *, timeout: float = 60, headers: dict | None = None, **kw) -> httpx.Response:
        try:
            with httpx.Client(transport=_transport, timeout=timeout, follow_redirects=False) as c:
                return c.request(method, self.base + path, headers={**self._h, **(headers or {})}, **kw)
        except httpx.HTTPError as e:
            raise ComfyError(f"ComfyUI {path.split('?')[0]}: {type(e).__name__}") from None

    def _json(self, method: str, path: str, ok=(200,), **kw):
        r = self._req(method, path, **kw)
        if r.status_code not in ok:
            raise ComfyError(f"ComfyUI {method} {path.split('?')[0]}: HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json() if r.content else {}
        except ValueError:
            raise ComfyError(f"ComfyUI {path.split('?')[0]}: the answer was not JSON") from None

    def _manager_headers(self) -> dict:
        # ComfyUI-Manager only accepts queue calls that look like they come from its own page
        return {"Sec-Fetch-Site": "same-origin", "Origin": self.base}

    # -------------------------------------------------------------- server
    def ready(self) -> bool:
        try:
            return self._req("GET", "/system_stats", timeout=20).status_code == 200
        except ComfyError:
            return False

    def upload(self, path: Path, name: str | None = None) -> str:
        """Put one local file in ComfyUI's input folder (overwriting a file of the same name). Returns its name."""
        name = name or path.name
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            r = self._req("POST", "/upload/image", timeout=300, files={"image": (name, f, ctype)}, data={"overwrite": "true"})
        if r.status_code != 200:
            raise ComfyError(f"ComfyUI upload of {name}: HTTP {r.status_code}")
        try:
            return r.json().get("name") or name
        except ValueError:
            return name

    # -------------------------------------------------------------- graphs
    def submit(self, graph: dict, client_id: str = "oddstudio") -> str:
        r = self._req("POST", "/prompt", timeout=60, json={"prompt": graph, "client_id": client_id})
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code != 200 or body.get("node_errors"):
            detail = json.dumps(body.get("node_errors") or body.get("error") or r.text[:300])[:600]
            raise ComfyError(f"ComfyUI refused the graph (HTTP {r.status_code}): {detail}")
        if not body.get("prompt_id"):
            raise ComfyError("ComfyUI returned no prompt id")
        return body["prompt_id"]

    def status(self, prompt_id: str) -> dict:
        """{"done": bool, "error": str, "outputs": {node: {...}}} for a queued graph."""
        h = self._json("GET", f"/history/{quote(prompt_id, safe='')}", timeout=30)
        item = h.get(prompt_id) or {}
        st = item.get("status") or {}
        if st.get("status_str") == "error":
            msgs = [m for m in st.get("messages") or [] if m and m[0] == "execution_error"]
            detail = ""
            if msgs and isinstance(msgs[0][1], dict):
                m = msgs[0][1]
                detail = f"{m.get('node_type', '')}: {m.get('exception_message', '')}".strip(": ")
            return {"done": True, "error": (detail or "the graph failed on the GPU")[:400], "outputs": item.get("outputs") or {}}
        return {"done": bool(st.get("completed")), "error": "", "outputs": item.get("outputs") or {}}

    def download(self, f: dict, dest: Path) -> Path:
        q = (f"/view?filename={quote(f['filename'], safe='')}&subfolder={quote(f.get('subfolder', ''), safe='')}"
             f"&type={quote(f.get('type', 'output'), safe='')}")
        r = self._req("GET", q, timeout=600)
        if r.status_code != 200 or not r.content:
            raise ComfyError(f"ComfyUI download of {f['filename']}: HTTP {r.status_code}")
        dest.write_bytes(r.content)
        return dest

    # -------------------------------------------------------------- models (ComfyUI-Manager)
    def model_files(self, folder: str) -> list[str]:
        try:
            out = self._json("GET", f"/models/{quote(folder, safe='')}", timeout=30)
        except ComfyError:
            return []
        return [str(x) for x in out] if isinstance(out, list) else []

    def missing_models(self, models: list[dict]) -> list[dict]:
        seen: dict[str, list[str]] = {}
        out = []
        for m in models:
            if m["folder"] not in seen:
                seen[m["folder"]] = self.model_files(m["folder"])
            if m["filename"] not in seen[m["folder"]]:
                out.append(m)
        return out

    def install_models(self, models: list[dict]) -> None:
        """Queue each model download with ComfyUI-Manager, then start the queue."""
        for m in models:
            body = {"name": m["filename"], "filename": m["filename"], "url": m["url"], "save_path": m["folder"],
                    "type": m.get("type", m["folder"]), "base": m.get("base", ""), "ui_id": m["filename"]}
            self._json("POST", "/v2/manager/queue/install_model", ok=(200, 201), timeout=60, json=body,
                       headers=self._manager_headers())
        self._json("POST", "/v2/manager/queue/start", ok=(200, 201), timeout=60, headers=self._manager_headers())

    def downloads_idle(self) -> bool:
        q = self._json("GET", "/v2/manager/queue/status", timeout=30, headers=self._manager_headers())
        return not q.get("is_processing") and int(q.get("pending_count") or 0) == 0


def video_outputs(outputs: dict) -> list[dict]:
    """Every video file a finished graph reports, in node order. With a LoadVideo node in the graph the control video's
    passthrough is listed as well (first); the caller keeps the real result (the larger file)."""
    out = []
    for node in outputs.values():
        for f in (node.get("videos") or []) + (node.get("gifs") or []) + (node.get("images") or []):
            if isinstance(f, dict) and str(f.get("filename", "")).lower().endswith((".mp4", ".webm", ".mov")):
                out.append(f)
    return out
