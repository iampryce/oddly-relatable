"""RunPod adapter (docs/GPU-INFRASTRUCTURE.md §11.3): the only provider-specific code for rented GPUs.

Five calls: create (launch a pod running our worker image), get, list (our pods only, by name prefix), terminate,
price; plus the account balance (the prepaid balance is the provider-side hard stop) and the address of the worker's
HTTP port. Another provider needs another module with the same functions.

RunPod REST API v2, read from RunPod's published OpenAPI document (https://api.runpod.io/v2/openapi.json, 2026-11-22):
  POST   /v2/pods                 {name, cloud, gpu: {id, count}, image, disk, env, ports: ["8000/http"]} -> Pod
  GET    /v2/pods                 {pods: [...], pagination: {nextCursor, hasNextPage}} (cursor query parameter)
  GET    /v2/pods/{id}            Pod: id, name, status (PROVISIONING | STARTING | RUNNING | EXITED | ERROR | TERMINATED),
                                  cost (hourly compute rate in USD), createdAt, startedAt
  DELETE /v2/pods/{id}            204: terminated and deleted (irreversible; nothing keeps billing)
  GET    /v2/catalog/gpus/{id}    GPU type with price {secure, community} (USD per hour, per GPU)
  GET    /v2/billing/balance      {balanceAmount, billingMode}
  Auth: "Authorization: Bearer <api key>". HTTP ports are reached through RunPod's HTTPS proxy,
  https://<pod id>-<port>.proxy.runpod.net (RunPod docs, "Expose ports"; Cloudflare closes a request after 100 s, so the
  worker API is asynchronous: every call returns at once).

No volume is ever attached (no `mounts`): nothing bills after a terminate. Secure Cloud only (§7).
The API key comes from Settings > Credentials (runpod_api_key) and is never logged or returned.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from .providers import ProviderError, ProviderNotConfigured
from .secrets_store import secret

API = "https://api.runpod.io"
NAME_PREFIX = "oddstudio-gpu-"
LIVE = ("PROVISIONING", "STARTING", "RUNNING")
# Fallback list prices, RunPod pricing page dated 2026-11-12 (Secure Cloud, USD per hour). The live catalog price is
# used when it can be read; the pod's own reported `cost` replaces both once it exists.
PRICES = {"NVIDIA GeForce RTX 4090": 0.89, "NVIDIA GeForce RTX 5090": 1.39, "NVIDIA L40S": 1.09, "NVIDIA A40": 0.59,
          "NVIDIA A100 80GB PCIe": 2.09, "NVIDIA H100 PCIe": 2.89, "NVIDIA H100 80GB HBM3": 4.39,
          # the owner's figure for talking-shot sessions, 2026-11-26 (the live catalog price is used when readable)
          "NVIDIA RTX 6000 Ada Generation": 1.09}

_test_transport = None   # tests only: fn(method, path, json, params) -> (status, body)


def set_test_transport(fn) -> None:
    """Tests only: replace the HTTP calls with fn(method, path, json, params) -> (status, body)."""
    global _test_transport
    _test_transport = fn


def _key() -> str:
    k = secret("runpod_api_key")
    if not k:
        raise ProviderNotConfigured("RunPod: save the RunPod API key under Settings > Credentials")
    return k


def _call(method: str, path: str, json: dict | None = None, params: dict | None = None, ok=(200, 201, 204)):
    if _test_transport is not None:
        status, body = _test_transport(method, path, json, params)
    else:
        r = httpx.request(method, API + path, json=json, params=params, timeout=60,
                          headers={"Authorization": f"Bearer {_key()}", "Accept": "application/json"})
        status = r.status_code
        try:
            body = r.json() if r.content else {}
        except ValueError:
            body = {"detail": r.text[:200]}
    if status not in ok:
        detail = body.get("detail") or body.get("title") if isinstance(body, dict) else str(body)
        raise ProviderError(f"RunPod {method} {path.split('?')[0]}: HTTP {status}: {str(detail)[:200]}",
                            transient=status in (429, 500, 502, 503, 504))
    return status, body


class GpuTypeUnavailable(ProviderError):
    """HTTP 400 on create: no pod of this GPU type is free right now (the caller may try the next type)."""

    def __init__(self, gpu_id: str, detail: str = ""):
        super().__init__(f"RunPod: no {gpu_id} is available right now" + (f" ({detail[:120]})" if detail else ""),
                         transient=False)
        self.gpu_id = gpu_id


def create(name: str, gpu_id: str, image: str, env: dict, disk_gb: int, cloud: str = "SECURE", port: int = 8000,
           ports: list[str] | None = None) -> dict:
    """Launch one pod. `ports` (e.g. ["8188/http", "22/tcp"]) replaces the single worker port when given. HTTP 400
    raises GpuTypeUnavailable: RunPod answers 400 when that GPU type cannot be placed now."""
    if not name.startswith(NAME_PREFIX):
        raise ValueError("pod names start with " + NAME_PREFIX)
    if cloud != "SECURE":
        raise ValueError("Secure Cloud only")
    status, pod = _call("POST", "/v2/pods", json={"name": name, "cloud": cloud, "gpu": {"id": gpu_id, "count": 1}, "image": image,
                                                  "disk": int(disk_gb), "env": env, "ports": list(ports or [f"{port}/http"])},
                        ok=(200, 201, 400))
    if status == 400:
        detail = (pod.get("detail") or pod.get("title") or "") if isinstance(pod, dict) else ""
        raise GpuTypeUnavailable(gpu_id, str(detail))
    if not isinstance(pod, dict) or not pod.get("id"):
        raise ProviderError("RunPod: the create call returned no pod id")
    return pod


def get(pod_id: str) -> dict | None:
    """The pod, or None when it no longer exists."""
    status, body = _call("GET", f"/v2/pods/{quote(pod_id, safe='')}", ok=(200, 404))
    return None if status == 404 else body


def list_ours() -> list[dict]:
    """Every pod on the account whose name starts with our prefix (all pages)."""
    out, cursor = [], None
    for _ in range(50):
        _, body = _call("GET", "/v2/pods", params={"cursor": cursor} if cursor else None)
        out += [p for p in body.get("pods") or [] if str(p.get("name", "")).startswith(NAME_PREFIX)]
        pg = body.get("pagination") or {}
        if not pg.get("hasNextPage") or not pg.get("nextCursor"):
            break
        cursor = pg["nextCursor"]
    return out


def terminate(pod_id: str) -> bool:
    """Terminate and delete the pod. True when it was terminated now, False when it was already gone."""
    status, _ = _call("DELETE", f"/v2/pods/{quote(pod_id, safe='')}", ok=(200, 204, 404))
    return status != 404


def price(gpu_id: str, cloud: str = "SECURE") -> tuple[float, str]:
    """(USD per hour, source): the live catalog price, else the list price recorded above."""
    try:
        _, g = _call("GET", f"/v2/catalog/gpus/{quote(gpu_id, safe='')}")
        p = float(((g or {}).get("price") or {}).get("secure" if cloud == "SECURE" else "community"))
        if p > 0:
            return p, "RunPod catalog"
    except (ProviderError, ProviderNotConfigured, TypeError, ValueError):
        pass
    if gpu_id in PRICES:
        return PRICES[gpu_id], "RunPod pricing page, 2026-11-12"
    raise ProviderError(f"RunPod: no price known for {gpu_id}")


def balance() -> float | None:
    try:
        _, b = _call("GET", "/v2/billing/balance")
        return float(b.get("balanceAmount"))
    except (ProviderError, ProviderNotConfigured, TypeError, ValueError):
        return None


def worker_url(pod_id: str, port: int = 8000) -> str:
    return f"https://{pod_id}-{port}.proxy.runpod.net"
