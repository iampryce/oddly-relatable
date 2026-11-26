"""Rented ComfyUI sessions: a second session KIND on the GPU manager (gpu.py), for the talking shots.

Why a session kind and not a new worker-contract job: the portable worker image (gpu.py, docs/GPU-INFRASTRUCTURE.md
§11.2) is not built and published yet, while the official image runpod/comfyui:2.5.0-comfyuiv0.45.0-cuda13.2 ran the
owner's talking-shot method on real GPUs (2026-11-26). So a session of kind "comfyui" launches that image as it is and
the studio talks to ComfyUI directly (comfy.py). Everything that controls money is shared with gpu.py, unchanged:

  * the same ledger row ("_gpu_sessions"): each session records kind, pod, GPU type, hourly price, reservation and cost;
  * the same monthly cap with reservation BEFORE the pod is created (price x (maximum lifetime + 5 min));
  * the same pod name prefix (runpod.NAME_PREFIX), so the orphan sweep covers these pods;
  * the same sweep (idle timer, maximum lifetime, cap, pod gone) and gpu.terminate_session (terminate, never stop).
    The talking-shot job carries "backend": "gpu" in its payload, so the idle timer never fires while it runs.

Launch: Settings > GPU worker must be "rented" and the RunPod key saved. GPU types are tried in order: NVIDIA L40S, then
NVIDIA RTX 6000 Ada Generation; the A100 only when Settings > GPU worker "allow expensive GPUs" is on (off by default).
RunPod answers HTTP 400 when a type cannot be placed now: the next type is tried. Each try is cap-checked at its price.
The pod gets a random ComfyUI password (COMFYUI_PASSWORD, Bearer auth on https://<pod>-8188.proxy.runpod.net) and a
throwaway SSH public key (PUBLIC_KEY, port 22/tcp) used only to read the actor's pose points with MediaPipe
(pose_remote.py). Both are kept encrypted in the ledger and dropped when the session ends. 120 GB disk, no volume.
"""
from __future__ import annotations

import secrets as pysecrets
import uuid

from sqlalchemy.orm import Session

from . import gpu, runpod
from .comfy import Client, proxy_url
from .providers import ProviderError, ProviderNotConfigured
from .secrets_store import secret

KIND = "comfyui"
IMAGE = "runpod/comfyui:2.5.0-comfyuiv0.45.0-cuda13.2"
DISK_GB = 120
PORTS = ["8188/http", "22/tcp"]
CHEAP_GPUS = ["NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"]
EXPENSIVE_GPUS = ["NVIDIA A100 80GB PCIe"]
BOOT_TIMEOUT_S = 25 * 60
MODELS_TIMEOUT_S = 45 * 60
POLL_S = 10.0


def gpu_order(cfg: dict) -> list[str]:
    """The GPU types to try, cheapest first; the A100 only when the owner allowed expensive GPUs."""
    return CHEAP_GPUS + (EXPENSIVE_GPUS if cfg.get("allow_expensive_gpus") else [])


def prices(cfg: dict) -> dict[str, float]:
    """USD per hour for each GPU type in the order (live catalog when readable, else the list price)."""
    out = {}
    for g in gpu_order(cfg):
        try:
            out[g] = runpod.price(g)[0]
        except (ProviderError, ProviderNotConfigured):
            out[g] = runpod.PRICES.get(g, 0.0)
    return out


def list_prices(cfg: dict) -> list[float]:
    """The list prices (runpod.PRICES) of the allowed types, in preference order; no network call."""
    return [runpod.PRICES.get(g, 0.0) for g in gpu_order(cfg)]


def live(db: Session) -> list[dict]:
    return [s for s in gpu.live_sessions(db) if s.get("kind") == KIND]


def availability(db: Session) -> dict:
    """Whether a talking-shot render can start now, with the reason when not, and the prices it would pay."""
    c = gpu.cfg(db)
    fig = gpu.month_figures(db)
    out = {"mode": c["mode"], "gpus": [{"id": g, "usd_per_hour": p} for g, p in zip(gpu_order(c), list_prices(c))],
           "allow_expensive_gpus": bool(c.get("allow_expensive_gpus")), "cap_usd": float(c["monthly_cap_usd"]),
           "spent_usd": fig["spent_usd"], "committed_usd": fig["committed_usd"],
           "max_lifetime_minutes": int(c["max_lifetime_minutes"]), "live_session": bool(live(db)), "ok": False, "reason": ""}
    if c["mode"] != "rented":
        out["reason"] = "Settings > GPU worker: set the mode to \"Rented\" (talking shots run on a rented RunPod GPU)"
    elif not secret("runpod_api_key"):
        out["reason"] = "Settings > Credentials: save the RunPod API key"
    else:
        out["ok"] = True
    return out


def _reservation(cfg: dict, price: float) -> float:
    return round(price * (int(cfg["max_lifetime_minutes"]) + gpu.SLACK_MIN) / 60, 4)


def password(s: dict) -> str:
    return gpu._fernet().decrypt(s["password"].encode()).decode()


def ssh_key(s: dict) -> str:
    return gpu._fernet().decrypt(s["ssh_key"].encode()).decode() if s.get("ssh_key") else ""


def client(s: dict) -> Client:
    return Client(proxy_url(s["pod_id"]), password(s))


def _session_out(s: dict) -> dict:
    return {"session": s["id"], "pod_id": s["pod_id"], "gpu_type": s["gpu_type"], "price_per_hour": s["price_per_hour"],
            "launched_at": s["launched_at"], "client": client(s)}


def launch(db: Session, log=print) -> dict:
    """Reuse the live ComfyUI session, or launch one (cap-checked and reserved before each create). Waits until
    ComfyUI answers. Returns {session, pod_id, gpu_type, price_per_hour, launched_at, client}."""
    from .pose_remote import new_keypair
    c = gpu.cfg(db)
    a = availability(db)
    if not a["ok"]:
        raise gpu.GpuUnavailable(a["reason"])
    db.expire_all()
    if db.get(gpu.Setting, gpu.ROW) is None:
        gpu.save(db, {"sessions": {}, "orphans": []})
        db.commit()
    led = gpu.ledger(db, lock=True)
    mine = [s for s in led["sessions"].values() if s.get("status") in gpu.LIVE and s.get("kind") == KIND]
    db.commit()
    if mine:
        s = mine[0]
        if s["status"] == "ready" and s.get("pod_id") and client(s).ready():
            return _session_out(s)
        if s["status"] == "launching" and s.get("pod_id"):
            return _wait_ready(db, s["id"], log)
        gpu.terminate_session(db, s["id"], "ComfyUI stopped answering")
    order = gpu_order(c)
    p = prices(c)
    sid = uuid.uuid4().hex[:12]
    pw = pysecrets.token_urlsafe(24)
    priv, pub = new_keypair()
    f = gpu._fernet()
    tried: list[str] = []
    for g in order:
        price = p[g] or runpod.PRICES.get(g, 0.0)
        reserved = _reservation(c, price)
        led = gpu.ledger(db, lock=True)
        fig = gpu.month_figures(db)
        # this session's own reservation for the type that was not available is replaced, not added
        own = gpu.committed(led["sessions"][sid], gpu.clock()) if sid in led["sessions"] else 0.0
        if fig["committed_usd"] - own + reserved > float(c["monthly_cap_usd"]) + 1e-9:
            db.commit()
            if sid in led["sessions"]:
                gpu._close(db, sid, "monthly GPU cap reached before a pod was created", pod_gone=True)
            raise gpu.GpuUnavailable(f"Paused: monthly GPU cap reached (${fig['committed_usd']:.2f} committed of "
                                     f"${float(c['monthly_cap_usd']):.2f}; a {g} session reserves ${reserved:.2f})")
        t = gpu.clock()
        s = led["sessions"].get(sid) or {"id": sid, "kind": KIND, "name": runpod.NAME_PREFIX + sid, "status": "launching",
                                         "launched_at": t, "last_used": t, "image": IMAGE, "pod_id": None, "clips": 0,
                                         "reason": "", "cost_usd": 0.0,
                                         "password": f.encrypt(pw.encode()).decode(),
                                         "ssh_key": f.encrypt(priv.encode()).decode()}
        s.update(gpu_type=g, price_per_hour=price, price_source="RunPod catalog or list price", reserved_usd=reserved,
                 launched_at=t, last_used=t)
        led["sessions"][sid] = s
        gpu.save(db, led)
        gpu._event(db, f"GPU session {sid} (ComfyUI): launching {g} at ${price:.2f}/h; reserved ${reserved:.2f} of the monthly cap")
        db.commit()
        log(f"Starting a rented {g} (${price:.2f}/h)")
        try:
            pod = runpod.create(s["name"], g, IMAGE, disk_gb=DISK_GB, ports=PORTS,
                                env={"COMFYUI_PASSWORD": pw, "PUBLIC_KEY": pub})
        except runpod.GpuTypeUnavailable:
            tried.append(g)
            log(f"No {g} is free on RunPod right now; trying the next type")
            continue
        except Exception as e:
            gpu._close(db, sid, f"launch failed: {str(e)[:200]}", pod_gone=True)
            raise
        led = gpu.ledger(db, lock=True)
        s = led["sessions"][sid]
        s["pod_id"] = pod["id"]
        real = float(pod.get("cost") or 0)
        if real > 0 and abs(real - price) > 1e-6:          # the rate RunPod actually bills replaces the estimate
            s["price_per_hour"], s["price_source"] = real, "the pod's reported rate"
            s["reserved_usd"] = _reservation(c, real)
        gpu.save(db, led)
        db.commit()
        if gpu.month_figures(db)["committed_usd"] > float(c["monthly_cap_usd"]) + 1e-9:
            gpu.terminate_session(db, sid, "monthly GPU cap reached (the pod's billed rate is higher than the list price)")
            raise gpu.GpuUnavailable("Paused: monthly GPU cap reached once the pod's billed rate was known; the pod was terminated")
        return _wait_ready(db, sid, log)
    if sid in gpu.ledger(db)["sessions"]:
        gpu._close(db, sid, "no GPU of the allowed types was available", pod_gone=True)
    hint = "" if c.get("allow_expensive_gpus") else " or allow expensive GPUs in Settings > GPU worker"
    raise gpu.GpuUnavailable(f"No GPU free on RunPod right now (tried {', '.join(tried)}): try again later{hint}")


def _wait_ready(db: Session, sid: str, log) -> dict:
    """Wait until ComfyUI answers on the proxy; the cap, the lifetime and the boot timeout are checked on every poll."""
    t0 = gpu.clock()
    said = False
    while True:
        why = gpu.check_session(db, sid)
        if why:
            raise gpu.GpuUnavailable(f"Stopped: {why}")
        s = gpu.ledger(db)["sessions"][sid]
        if s.get("pod_id") and client(s).ready():
            led = gpu.ledger(db, lock=True)
            led["sessions"][sid].update(status="ready", ready_at=gpu.clock())
            gpu.save(db, led)
            db.commit()
            log(f"The GPU is ready after {round(gpu.clock() - s['launched_at'])} s")
            return _session_out(gpu.ledger(db)["sessions"][sid])
        if not said:
            log("Waiting for ComfyUI to start on the GPU")
            said = True
        if gpu.clock() - t0 > BOOT_TIMEOUT_S:
            gpu.terminate_session(db, sid, f"ComfyUI did not start within {BOOT_TIMEOUT_S // 60} min")
            raise gpu.GpuUnavailable(f"Stopped: ComfyUI did not start within {BOOT_TIMEOUT_S // 60} min")
        gpu.sleep(POLL_S)


def ensure_models(db: Session, sess: dict, models: list[dict], log=print) -> None:
    """Download the missing model files with ComfyUI-Manager and wait until its queue is idle; then check every file
    is listed by ComfyUI (a file listed mid-download is never trusted: the queue must be idle first)."""
    cl: Client = sess["client"]
    missing = cl.missing_models(models)
    if not missing:
        return
    log(f"Downloading {len(missing)} model file(s) on the GPU: " + ", ".join(m["filename"] for m in missing))
    cl.install_models(missing)
    t0 = gpu.clock()
    while True:
        gpu.sleep(POLL_S)
        why = gpu.check_session(db, sess["session"])
        if why:
            raise gpu.GpuUnavailable(f"Stopped: {why}")
        if cl.downloads_idle():
            break
        if gpu.clock() - t0 > MODELS_TIMEOUT_S:
            raise ProviderError(f"the model downloads did not finish within {MODELS_TIMEOUT_S // 60} min", transient=False)
    still = cl.missing_models(models)
    if still:
        raise ProviderError("the GPU could not download " + ", ".join(m["filename"] for m in still), transient=False)
    log("Models ready")


def ssh_endpoint(pod_id: str) -> tuple[str, int] | None:
    """(host, port) of the pod's SSH port from RunPod's pod record, or None when it is not published (yet)."""
    p = runpod.get(pod_id) or {}
    ip = p.get("publicIp") or ""
    pm = p.get("portMappings") or {}
    port = pm.get("22") or pm.get(22)
    if ip and port:
        return str(ip), int(port)
    direct = ((p.get("ssh") or {}).get("direct") or "") if isinstance(p.get("ssh"), dict) else ""
    # e.g. "ssh root@1.2.3.4 -p 12345 -i ~/.ssh/id_ed25519"
    import re
    m = re.search(r"@([0-9A-Za-z.\-]+)\s+-p\s+(\d+)", direct)
    return (m.group(1), int(m.group(2))) if m else None


def stop(db: Session, reason: str) -> list[str]:
    """Terminate every live ComfyUI session (the owner's stop button, or the end of a render)."""
    done = []
    for s in live(db):
        gpu.terminate_session(db, s["id"], reason)
        done.append(s["id"])
    return done
