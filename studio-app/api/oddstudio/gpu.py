"""Self-hosted GPU worker control (docs/GPU-INFRASTRUCTURE.md §11, owner-accepted 2026-11-22).

Modes (Settings > GPU worker):
  off     nothing self-hosted runs (the default)
  own     a machine we own runs the worker image: the one address (`worker_url`) and its token (Credentials:
          gpu_worker_token). No rental, so no cost and no cap.
  rented  a RunPod Secure Cloud pod per session, launched when an approved self-hosted clip needs it and TERMINATED
          (never just stopped) afterwards. Billed per second; nothing is kept on rented storage.

Spend control for rented sessions (the cap is separate from fal.ai's experimental budget, owner decision §13-2):
  * the ledger ("_gpu_sessions" settings row) records each session: pod, GPU type, the hourly price at launch,
    launch/terminate times and its cost. Cost accrues from launch (boot and idle time count).
  * before a launch the studio RESERVES price x (maximum lifetime + 5 min): a launch is refused when this month's
    committed spend (ended sessions' cost + each live session's reservation or accrued cost, whichever is higher) plus
    the new reservation would pass `monthly_cap_usd`. Because of the reservation a session cannot take spend past the
    cap.
  * while a clip runs, the session is checked at every poll: at the cap or the maximum lifetime the clip is stopped
    with the reason and the pod is terminated.

Idle shutdown, four layers (§11.1): (1) the idle timer and (2) the maximum lifetime, applied by `sweep`; (3) the
orphan sweep: any pod on the account with our name prefix that is not a live session here is terminated, and a live
session whose pod has gone is closed; (4) the worker's own self-limit (it refuses jobs after its lifetime or idle
limit). `sweep` runs in a background thread of every studio worker process, every 30 s and once at start-up, so it
works even while that process is busy with a long job, and after a restart.

The worker image, its job API and the provider adapter are portable: changing `mode` and `worker_url` moves the work
to our own machine; nothing else changes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets as pysecrets
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import runpod
from .auth import current_user
from .db import get_db
from .models import Event, Job, Setting
from .providers import ProviderError, ProviderNotConfigured
from .secrets_store import secret

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
ROW = "_gpu_sessions"
MODES = ("off", "own", "rented")
SLACK_MIN = 5                 # the reservation covers the lifetime plus one sweep interval and a margin
BOOT_TIMEOUT_S = 25 * 60      # weights download + ComfyUI start (estimate §16: 10-20 min)
POLL_S = 3.0                  # worker status polls while a clip runs
BOOT_POLL_S = 10.0
LIVE = ("launching", "ready")

clock = time.time             # tests replace these three
sleep = time.sleep
url_for = runpod.worker_url


class GpuUnavailable(ProviderError):
    """A self-hosted clip cannot run now (mode off, not configured, the cap). Never retried automatically."""

    def __init__(self, message: str):
        super().__init__(message, transient=False)


# ------------------------------------------------------------------ settings and ledger
def cfg(db: Session) -> dict:
    from .settings_store import get_section
    return get_section(db, "gpu")


def _fernet():
    from .secrets_store import _fernet as f
    return f()


def ledger(db: Session, lock: bool = False) -> dict:
    q = db.query(Setting).filter_by(key=ROW)
    row = (q.with_for_update() if lock else q).one_or_none()
    return json.loads(json.dumps(row.value)) if row else {"sessions": {}, "orphans": []}


def save(db: Session, led: dict) -> None:
    # keep a year of sessions (the monthly figures need only this month)
    cutoff = clock() - 400 * 86400
    led["sessions"] = {k: s for k, s in led["sessions"].items() if s.get("launched_at", 0) > cutoff or s.get("status") in LIVE}
    led["orphans"] = (led.get("orphans") or [])[-50:]
    row = db.get(Setting, ROW)
    if row:
        row.value = led
    else:
        db.add(Setting(key=ROW, value=led))


def month_of(t: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(t))


def accrued(s: dict, t: float) -> float:
    if s.get("status") not in LIVE:
        return float(s.get("cost_usd") or 0.0)
    return round(float(s.get("price_per_hour") or 0) * max(0.0, t - s["launched_at"]) / 3600, 4)


def committed(s: dict, t: float) -> float:
    return accrued(s, t) if s.get("status") not in LIVE else max(float(s.get("reserved_usd") or 0), accrued(s, t))


def month_figures(db: Session, t: float | None = None) -> dict:
    t = clock() if t is None else t
    ss = [s for s in ledger(db)["sessions"].values() if month_of(s["launched_at"]) == month_of(t)]
    return {"spent_usd": round(sum(accrued(s, t) for s in ss), 4), "committed_usd": round(sum(committed(s, t) for s in ss), 4)}


def live_sessions(db: Session) -> list[dict]:
    return [s for s in ledger(db)["sessions"].values() if s.get("status") in LIVE]


def planned_price(db: Session) -> tuple[float, str]:
    """The hourly price used for estimates: own machine 0; a live session's price; else RunPod's list price."""
    c = cfg(db)
    if c["mode"] == "own":
        return 0.0, "own machine: no rental cost"
    live = live_sessions(db)
    if live:
        return float(live[0]["price_per_hour"]), "the live session's price"
    p = runpod.PRICES.get(c["gpu_type"])
    return (p, "RunPod list price, 2026-11-12") if p is not None else (0.0, f"no list price for {c['gpu_type']}")


def reservation_usd(db: Session, price: float | None = None) -> float:
    price = planned_price(db)[0] if price is None else price
    return round(price * (int(cfg(db)["max_lifetime_minutes"]) + SLACK_MIN) / 60, 4)


def availability(db: Session) -> dict:
    """What the owner sees before approving a self-hosted clip: mode, price, this month's spend against the cap, the
    reservation a new session takes, and whether a clip can run now (with the reason when not)."""
    c = cfg(db)
    price, src = planned_price(db)
    fig = month_figures(db)
    live = live_sessions(db)
    out = {"mode": c["mode"], "gpu_type": c["gpu_type"] if c["mode"] == "rented" else "", "price_per_hour": price,
           "price_source": src, "cap_usd": float(c["monthly_cap_usd"]), "warn_at": float(c["warn_at"]),
           "spent_usd": fig["spent_usd"], "committed_usd": fig["committed_usd"], "live_session": bool(live),
           "reservation_usd": 0.0 if c["mode"] != "rented" or live else reservation_usd(db, price),
           "idle_minutes": int(c["idle_minutes"]), "max_lifetime_minutes": int(c["max_lifetime_minutes"]), "ok": False, "reason": ""}
    out["warning"] = c["mode"] == "rented" and fig["spent_usd"] >= out["warn_at"] * out["cap_usd"]
    if c["mode"] == "off":
        out["reason"] = "Settings > GPU worker: the mode is off"
    elif c["mode"] == "own":
        if not c["worker_url"]:
            out["reason"] = "Settings > GPU worker: set the worker address"
        elif not secret("gpu_worker_token"):
            out["reason"] = "Settings > Credentials: save the GPU worker token"
        else:
            out["ok"] = True
    else:
        if not secret("runpod_api_key"):
            out["reason"] = "Settings > Credentials: save the RunPod API key"
        elif "@sha256:" not in c["image"]:
            out["reason"] = "Settings > GPU worker: the worker image must be pinned by digest (…@sha256:…)"
        elif price <= 0:
            out["reason"] = f"no price known for {c['gpu_type']}"
        elif not live and fig["committed_usd"] + out["reservation_usd"] > out["cap_usd"] + 1e-9:
            out["reason"] = (f"Paused: monthly GPU cap reached (${fig['committed_usd']:.2f} committed of ${out['cap_usd']:.2f}; "
                             f"a new session reserves ${out['reservation_usd']:.2f}). Raise the cap or wait for next month")
        else:
            out["ok"] = True
    return out


def check_can_run(db: Session) -> dict:
    a = availability(db)
    if not a["ok"]:
        raise GpuUnavailable(a["reason"])
    return a


# ------------------------------------------------------------------ the worker's HTTP job API (client)
def _w(method: str, url: str, token: str, path: str, **kw) -> httpx.Response:
    try:
        return httpx.request(method, url.rstrip("/") + path, headers={"Authorization": f"Bearer {token}"},
                             timeout=kw.pop("timeout", 60), follow_redirects=False, **kw)
    except httpx.HTTPError as e:
        raise ProviderError(f"GPU worker {path.split('/')[1] if '/' in path else path}: {type(e).__name__}", transient=False) from None


def _json(r: httpx.Response, what: str, ok=(200, 202)) -> dict:
    if r.status_code not in ok:
        try:
            msg = r.json().get("error") or r.text
        except ValueError:
            msg = r.text
        raise ProviderError(f"GPU worker {what}: HTTP {r.status_code}: {str(msg)[:200]}", transient=False)
    return r.json()


def worker_health(url: str, token: str) -> dict:
    return _json(_w("GET", url, token, "/health", timeout=20), "health", ok=(200,))


def worker_submit(url: str, token: str, job: dict) -> dict:
    return _json(_w("POST", url, token, "/jobs", json=job, timeout=90), "submit")


def worker_status(url: str, token: str, jid: str) -> dict:
    return _json(_w("GET", url, token, f"/jobs/{jid}", timeout=30), "status", ok=(200,))


def worker_fetch(url: str, token: str, jid: str, out: dict, dest: Path) -> Path:
    """Download one output and check its SHA-256 against the worker's record."""
    r = _w("GET", url, token, f"/jobs/{jid}/outputs/{out['name']}", timeout=95)
    if r.status_code != 200:
        raise ProviderError(f"GPU worker output: HTTP {r.status_code}", transient=False)
    dest.write_bytes(r.content)
    got = hashlib.sha256(r.content).hexdigest()
    if got != out.get("sha256"):
        raise ProviderError("GPU worker output: checksum mismatch (the file was not kept)", transient=False)
    return dest


def worker_cancel(url: str, token: str, jid: str) -> None:
    try:
        _w("POST", url, token, f"/jobs/{jid}/cancel", timeout=20)
    except ProviderError:
        pass


def worker_delete(url: str, token: str, jid: str) -> None:
    try:
        _w("DELETE", url, token, f"/jobs/{jid}", timeout=20)
    except ProviderError:
        pass


# ------------------------------------------------------------------ sessions
def _event(db: Session, msg: str) -> None:
    db.add(Event(episode_id=None, kind="job", message=msg[:500]))


def ensure_worker(db: Session, log=print) -> dict:
    """A worker ready for a job: {"url", "token", "session" (None on our own machine), "price_per_hour"}. On rented
    mode this reuses the live session or launches one (cap-checked, reservation recorded BEFORE the pod is created)."""
    c = cfg(db)
    a = check_can_run(db)
    if c["mode"] == "own":
        url, token = c["worker_url"], secret("gpu_worker_token")
        h = worker_health(url, token)
        if not h.get("ready"):
            raise GpuUnavailable(f"the GPU worker at the configured address is not ready: {h.get('failed') or 'still starting'}")
        if h.get("expired"):
            raise GpuUnavailable(f"the GPU worker is not taking jobs: {h['expired']}")
        return {"url": url, "token": token, "session": None, "price_per_hour": 0.0}
    # rented: reuse a live session, else reserve and launch (the ledger row is locked while deciding; it is created
    # first so that even the very first launch is decided under the lock)
    db.expire_all()
    if db.get(Setting, ROW) is None:
        save(db, {"sessions": {}, "orphans": []})
        db.commit()
    led = ledger(db, lock=True)
    # only worker-image sessions are reused here; ComfyUI sessions (comfy_session.py) have their own entry point
    live = [s for s in led["sessions"].values() if s.get("status") in LIVE and s.get("kind", "worker") == "worker"]
    if live:
        s = live[0]
        db.commit()
        if s["status"] == "ready" and s.get("pod_id"):
            # a reused session must still answer and take jobs; otherwise it is closed and a new one launched
            try:
                h = worker_health(url_for(s["pod_id"]), _token(s))
                stale = h.get("expired") or ("" if h.get("ready") else "not ready")
            except ProviderError as e:
                stale = str(e)[:120]
            if not stale:
                return _wait_ready(db, s["id"], log)
            terminate_session(db, s["id"], f"the worker stopped answering or taking jobs ({stale})")
            return ensure_worker(db, log)
        return _wait_ready(db, s["id"], log)
    gpu_type = c["gpu_type"]
    price, src = runpod.price(gpu_type)       # live catalog price when readable, else the list price
    reserved = reservation_usd(db, price)
    fig = month_figures(db)
    if fig["committed_usd"] + reserved > float(c["monthly_cap_usd"]) + 1e-9:
        db.commit()
        raise GpuUnavailable(f"Paused: monthly GPU cap reached (${fig['committed_usd']:.2f} committed of "
                             f"${float(c['monthly_cap_usd']):.2f}; a new session reserves ${reserved:.2f})")
    sid = uuid.uuid4().hex[:12]
    token = pysecrets.token_urlsafe(32)
    t = clock()
    s = {"id": sid, "name": runpod.NAME_PREFIX + sid, "status": "launching", "launched_at": t, "last_used": t,
         "gpu_type": gpu_type, "image": c["image"], "price_per_hour": price, "price_source": src, "reserved_usd": reserved,
         "token": _fernet().encrypt(token.encode()).decode(), "pod_id": None, "clips": 0, "reason": "", "cost_usd": 0.0}
    led["sessions"][sid] = s
    save(db, led)
    _event(db, f"GPU session {sid}: launching {gpu_type} at ${price:.2f}/h ({src}); reserved ${reserved:.2f} of the monthly cap")
    db.commit()
    log(f"GPU: launching a {gpu_type} session ({sid}), ${price:.2f}/h, reserved ${reserved:.2f}")
    try:
        pod = runpod.create(s["name"], gpu_type, c["image"], disk_gb=int(c["disk_gb"]), env={
            "WORKER_TOKEN": token, "IMAGE_DIGEST": c["image"],
            "WORKER_MAX_LIFETIME_S": str(int(c["max_lifetime_minutes"]) * 60 + 600),
            "WORKER_IDLE_S": str(int(c["idle_minutes"]) * 60 + 300)})
    except Exception as e:
        _close(db, sid, f"launch failed: {str(e)[:200]}", pod_gone=True)
        raise
    led = ledger(db, lock=True)
    s = led["sessions"][sid]
    s["pod_id"] = pod["id"]
    real = float(pod.get("cost") or 0)
    if real > 0 and abs(real - price) > 1e-6:           # the rate RunPod actually bills replaces the estimate
        s["price_per_hour"], s["price_source"] = real, "the pod's reported rate"
        s["reserved_usd"] = reservation_usd(db, real)
    save(db, led)
    db.commit()
    over = month_figures(db)
    if over["committed_usd"] > float(c["monthly_cap_usd"]) + 1e-9:
        terminate_session(db, sid, "monthly GPU cap reached (the pod's billed rate is higher than the list price)")
        raise GpuUnavailable("Paused: monthly GPU cap reached once the pod's billed rate was known; the pod was terminated")
    return _wait_ready(db, sid, log)


def _token(s: dict) -> str:
    return _fernet().decrypt(s["token"].encode()).decode()


def _wait_ready(db: Session, sid: str, log) -> dict:
    """Wait until the session's worker answers "ready" (weights checked, ComfyUI up); the cap, the lifetime and the
    boot timeout are checked on every poll."""
    t0 = clock()
    said = False
    while True:
        why = check_session(db, sid)
        if why:
            raise GpuUnavailable(f"Stopped: {why}")
        s = ledger(db)["sessions"][sid]
        if s["status"] == "ready":
            return {"url": url_for(s["pod_id"]), "token": _token(s), "session": sid, "price_per_hour": s["price_per_hour"]}
        if s.get("pod_id"):
            try:
                h = worker_health(url_for(s["pod_id"]), _token(s))
                if h.get("failed"):
                    terminate_session(db, sid, f"the worker could not start: {h['failed'][:200]}")
                    raise GpuUnavailable(f"Stopped: the worker could not start ({h['failed'][:200]})")
                if h.get("ready"):
                    led = ledger(db, lock=True)
                    led["sessions"][sid].update(status="ready", ready_at=clock(), worker=h.get("gpu", ""))
                    save(db, led)
                    db.commit()
                    log(f"GPU: session {sid} ready after {round(clock() - s['launched_at'])} s")
                    continue
            except ProviderError as e:
                if isinstance(e, GpuUnavailable):
                    raise
                if not said:
                    log("GPU: waiting for the worker to start (weights download and ComfyUI)")
                    said = True
        if clock() - t0 > BOOT_TIMEOUT_S:
            terminate_session(db, sid, f"the worker did not become ready within {BOOT_TIMEOUT_S // 60} min")
            raise GpuUnavailable(f"Stopped: the worker did not become ready within {BOOT_TIMEOUT_S // 60} min")
        sleep(BOOT_POLL_S)


def check_session(db: Session, sid: str) -> str:
    """'' while the session may go on; else the reason it was stopped (it is terminated here when needed)."""
    db.expire_all()
    s = ledger(db)["sessions"].get(sid)
    if s is None:
        return "the GPU session is unknown"
    if s["status"] not in LIVE:
        return s.get("reason") or "the GPU session has ended"
    c, t = cfg(db), clock()
    if t - s["launched_at"] > int(c["max_lifetime_minutes"]) * 60:
        terminate_session(db, sid, "maximum lifetime reached")
        return "maximum lifetime reached"
    if month_figures(db, t)["spent_usd"] >= float(c["monthly_cap_usd"]) - 1e-9:
        terminate_session(db, sid, "monthly GPU cap reached")
        return "monthly GPU cap reached"
    return ""


def touch(db: Session, sid: str | None, clips: int = 0) -> None:
    if not sid:
        return
    led = ledger(db, lock=True)
    s = led["sessions"].get(sid)
    if s and s["status"] in LIVE:
        s["last_used"] = clock()
        s["clips"] = int(s.get("clips") or 0) + clips
        save(db, led)
    db.commit()


def _close(db: Session, sid: str, reason: str, pod_gone: bool = False) -> dict:
    led = ledger(db, lock=True)
    s = led["sessions"][sid]
    if s["status"] in LIVE:
        t = clock()
        s.update(status="ended", ended_at=t, reason=reason, cost_usd=0.0 if pod_gone and not s.get("pod_id") else accrued(s, t))
        for k in ("password", "ssh_key"):     # a ComfyUI session's secrets are of no use once the pod is gone
            s.pop(k, None)
        save(db, led)
        _event(db, f"GPU session {sid} ended ({reason}); cost ${s['cost_usd']:.2f}")
    db.commit()
    return s


def terminate_session(db: Session, sid: str, reason: str) -> dict:
    """Terminate the pod (never just stop it) and close the session with its final cost. If RunPod cannot be reached,
    the session stays open (it is still billing) and the next sweep tries again."""
    db.expire_all()
    s = ledger(db)["sessions"].get(sid)
    if s is None or s["status"] not in LIVE:
        return s or {}
    if s.get("pod_id"):
        runpod.terminate(s["pod_id"])
    return _close(db, sid, reason)


def gpu_jobs_active(db: Session) -> bool:
    return any((j.payload or {}).get("backend") == "gpu"
               for j in db.query(Job).filter(Job.status.in_(("queued", "running"))).all())


def sweep(db: Session, log=print) -> list[str]:
    """Layers 1-3 of the idle shutdown. Returns what it did (for logs and tests)."""
    done = []
    c, t = cfg(db), clock()
    has_key = bool(secret("runpod_api_key"))
    for s in live_sessions(db):
        why = ""
        if t - s["launched_at"] > int(c["max_lifetime_minutes"]) * 60:
            why = "maximum lifetime reached"
        elif month_figures(db, t)["spent_usd"] >= float(c["monthly_cap_usd"]) - 1e-9:
            why = "monthly GPU cap reached"
        elif s["status"] == "launching" and t - s["launched_at"] > BOOT_TIMEOUT_S + 120:
            why = "the worker did not start"
        elif s["status"] == "ready" and not gpu_jobs_active(db) and t - s.get("last_used", s["launched_at"]) > int(c["idle_minutes"]) * 60:
            why = f"idle for {int(c['idle_minutes'])} min"
        elif c["mode"] != "rented" and not gpu_jobs_active(db):
            why = "the GPU mode is no longer 'rented'"
        if why:
            try:
                terminate_session(db, s["id"], why)
                done.append(f"terminated {s['id']}: {why}")
            except (ProviderError, ProviderNotConfigured) as e:
                done.append(f"could not terminate {s['id']} ({why}): {e}")
    if not has_key or (c["mode"] != "rented" and not live_sessions(db) and not done):
        return done
    # layer 3: the account's pods with our prefix that are not live sessions here; live sessions whose pod is gone
    try:
        pods = runpod.list_ours()
    except (ProviderError, ProviderNotConfigured) as e:
        return done + [f"could not list pods: {e}"]
    live = {s["name"]: s for s in live_sessions(db)}
    for p in pods:
        if p.get("name") not in live and p.get("status") != "TERMINATED":
            try:
                runpod.terminate(p["id"])
                led = ledger(db, lock=True)
                led["orphans"] = (led.get("orphans") or []) + [{"pod_id": p["id"], "name": p.get("name"), "at": clock(),
                                                                "price_per_hour": p.get("cost")}]
                save(db, led)
                _event(db, f"GPU: terminated pod {p['id']} ({p.get('name')}): not a live session of this studio")
                db.commit()
                done.append(f"terminated orphan pod {p['id']}")
            except ProviderError as e:
                done.append(f"could not terminate orphan pod {p['id']}: {e}")
    names = {p.get("name") for p in pods if p.get("status") != "TERMINATED"}
    for name, s in live.items():
        if s.get("pod_id") and name not in names:
            _close(db, s["id"], "the pod no longer exists")
            done.append(f"closed {s['id']}: the pod no longer exists")
    for d in done:
        log("GPU sweep: " + d)
    return done


def start_sweeper(interval: float = 30.0, log=print) -> threading.Thread:
    """Background thread in each studio worker process: sweep at start-up, then every `interval` seconds."""
    from .db import new_session

    def loop():
        while True:
            try:
                with new_session() as db:
                    sweep(db, log)
            except Exception as e:  # noqa: BLE001 -- never let the sweeper die
                log(f"GPU sweep failed: {type(e).__name__}: {str(e)[:200]}")
            time.sleep(interval)
    th = threading.Thread(target=loop, name="gpu-sweeper", daemon=True)
    th.start()
    return th


# ------------------------------------------------------------------ routes (status and the owner's stop button)
def public_session(s: dict, t: float) -> dict:
    return {k: s.get(k) for k in ("id", "kind", "status", "gpu_type", "price_per_hour", "price_source", "reserved_usd", "pod_id",
                                  "clips", "reason", "launched_at", "ready_at", "ended_at", "last_used")} | {"cost_usd": accrued(s, t)}


@router.get("/gpu")
def gpu_status(db: Session = Depends(get_db)):
    t = clock()
    ss = sorted(ledger(db)["sessions"].values(), key=lambda s: -s["launched_at"])
    return {**availability(db), "sessions": [public_session(s, t) for s in ss if month_of(s["launched_at"]) == month_of(t)][:30],
            "orphans": ledger(db).get("orphans", [])[-10:]}


@router.get("/gpu/balance")
def gpu_balance(db: Session = Depends(get_db)):
    """The RunPod account balance (the provider-side hard stop), read on request only."""
    return {"balance_usd": runpod.balance() if secret("runpod_api_key") else None}


@router.post("/gpu/sessions/{sid}/terminate")
def stop_session(sid: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    s = ledger(db)["sessions"].get(sid)
    if not s:
        raise HTTPException(404, "no such GPU session")
    try:
        s = terminate_session(db, sid, f"terminated by {user}")
    except (ProviderError, ProviderNotConfigured) as e:
        raise HTTPException(502, f"RunPod could not be reached; the session is still open: {e}")
    return public_session(s, clock())


def seed_for(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()
