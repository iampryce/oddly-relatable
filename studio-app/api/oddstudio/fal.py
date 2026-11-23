"""fal.ai hosted generation (motion capability): asynchronous queue jobs with progress, cancellation, cost estimates
and a hard experimental spend cap.

Queue API (fal docs, 2026-11): POST https://queue.fal.run/<model> -> {request_id, status_url, response_url, cancel_url};
GET status_url -> IN_QUEUE (queue_position) | IN_PROGRESS | COMPLETED (error?); GET response_url -> model output;
PUT cancel_url. Auth: "Authorization: Key <FAL_KEY>".

Spend control: every paid request is estimated from the model's published price BEFORE submission and refused when
spent + estimate would exceed the cap (Settings > Motion: budget_usd, default $25). Spend is recorded per request in
the "_fal_spend" settings row (estimates of submitted requests; fal bills by its own metering).
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import httpx

from .providers import ProviderError, ProviderNotConfigured, http_error
from .secrets_store import secret

QUEUE = "https://queue.fal.run"
LEDGER = "_fal_spend"

# Commercially suitable open-weight video models on fal, with the published price formula (2026-11-17).
MODELS = {
    "wan-2.2-a14b": {"endpoint": "fal-ai/wan/v2.2-a14b/image-to-video", "label": "Wan 2.2 A14B (Apache-2.0)",
                     "licence": "Apache-2.0 (open weights; commercial use allowed)",
                     "defaults": {"resolution": "720p", "num_frames": 81, "frames_per_second": 16, "aspect_ratio": "9:16"},
                     "price": "$0.08 per video-second at 720p ($0.06 580p, $0.04 480p), billed at 16 fps"},
    "wan-2.2-5b": {"endpoint": "fal-ai/wan/v2.2-5b/image-to-video", "label": "Wan 2.2 TI2V 5B (Apache-2.0)",
                   "licence": "Apache-2.0 (open weights; commercial use allowed)",
                   "defaults": {"resolution": "720p", "num_frames": 121, "frames_per_second": 24},
                   "price": "$0.15 per video"},
    "ltx-2-19b": {"endpoint": "fal-ai/ltx-2-19b/image-to-video", "label": "LTX-2 19B (LTX-2 Community Licence)",
                  "licence": "LTX-2 Community Licence: free for commercial use under $10M annual revenue",
                  "defaults": {"num_frames": 121, "fps": 25, "video_size": {"width": 720, "height": 1280}, "generate_audio": False},
                  "price": "$0.0018 per megapixel of video (width x height x frames)"},
}


def estimate(model: str, params: dict) -> float:
    m = MODELS[model]
    p = {**m["defaults"], **params}
    if model == "wan-2.2-a14b":
        rate = {"720p": 0.08, "580p": 0.06, "480p": 0.04}[p.get("resolution", "720p")]
        return round(rate * p["num_frames"] / 16, 4)
    if model == "wan-2.2-5b":
        return 0.15
    if model == "ltx-2-19b":
        vs = p.get("video_size") or {"width": 1280, "height": 720}
        return round(0.0018 * math.ceil(vs["width"] * vs["height"] * p["num_frames"] / 1e6), 4)
    raise KeyError(model)


def actual_cost(model: str, video: dict, body: dict) -> float | None:
    """Price of what fal actually returned, from the published formula and the output's real size and length."""
    try:
        frames = video.get("num_frames") or body.get("num_frames")
        if model == "wan-2.2-a14b":
            rate = {"720p": 0.08, "580p": 0.06, "480p": 0.04}[body.get("resolution", "720p")]
            return round(rate * body.get("num_frames", frames) / 16, 4)   # billed on requested frames at 16 fps
        if model == "wan-2.2-5b":
            return 0.15
        if model == "ltx-2-19b" and video.get("width") and video.get("height") and frames:
            return round(0.0018 * math.ceil(video["width"] * video["height"] * frames / 1e6), 4)
    except Exception:
        return None
    return None


def correct_spend(db, estimated: float, actual: float) -> None:
    from .models import Setting
    row = db.get(Setting, LEDGER)
    if row:
        led = dict(row.value)
        led["total"] = round(led["total"] - estimated + actual, 4)
        row.value = led
        db.commit()


def spent(db) -> dict:
    from .models import Setting
    row = db.get(Setting, LEDGER)
    return dict(row.value) if row else {"total": 0.0, "requests": []}


def budget(db) -> float:
    from .settings_store import get_section
    return float(get_section(db, "motion").get("budget_usd") or 25.0)


def check_budget(db, cost: float, who: str = "fal.ai") -> None:
    """The experimental budget (Settings > Motion), shared by every hosted video provider (fal.ai, WaveSpeed)."""
    led, cap = spent(db), budget(db)
    if led["total"] + cost > cap + 1e-9:
        raise ProviderError(f"{who}: estimated ${cost:.2f} would exceed the experimental budget "
                            f"(${led['total']:.2f} of ${cap:.2f} used); raise it in Settings > Motion to continue")


def reserve(db, model: str, cost: float, note: str, who: str = "fal.ai") -> None:
    """Refuse when the cap would be exceeded; otherwise record the request's cost."""
    from .models import Setting
    check_budget(db, cost, who)
    led = spent(db)
    led["total"] = round(led["total"] + cost, 4)
    led["requests"] = (led.get("requests") or [])[-200:] + [{"model": model, "usd": cost, "note": note[:120], "at": time.time()}]
    row = db.get(Setting, LEDGER)
    if row:
        row.value = led
    else:
        db.add(Setting(key=LEDGER, value=led))
    db.commit()


def _key() -> str:
    k = secret("fal_key")
    if not k:
        raise ProviderNotConfigured("fal.ai: save the fal.ai API key under Settings > Credentials")
    return k


_test_run = None   # tests only: fn(endpoint, body, out) -> response JSON (the video already written to `out`)


def set_test_run(fn) -> None:
    """Tests only: replace the network call (submit, poll, download) with fn(endpoint, body, out)."""
    global _test_run
    _test_run = fn


def run(db, endpoint: str, label: str, body: dict, cost: float, note: str, out: Path, log, progress=None,
        timeout: int = 1800) -> tuple[dict, dict]:
    """Submit one queue request, poll it to completion and download the video to `out`. The estimated cost is checked
    against the cap before submitting and recorded once fal accepts the request. Returns (response JSON, timing)."""
    check_budget(db, cost)
    t0 = time.time()
    if _test_run is not None:
        reserve(db, endpoint, cost, f"test: {note}")
        data = _test_run(endpoint, body, out)
        return data, {"request_id": "test", "seconds": round(time.time() - t0, 1), "inference_seconds": None}
    key = _key()
    h = {"Authorization": f"Key {key}"}
    r = httpx.post(f"{QUEUE}/{endpoint}", json=body, headers=h, timeout=60)
    if r.status_code >= 400:
        raise http_error("fal.ai submit", r)   # refused requests are not billed and not recorded
    sub = r.json()
    reserve(db, endpoint, cost, f"{sub.get('request_id')}: {note}")   # accepted by fal: counts against the cap
    status_url, response_url, cancel_url = sub["status_url"], sub["response_url"], sub.get("cancel_url")
    log(f"fal.ai {label}: queued (request {sub['request_id']}), estimated ${cost:.2f}")
    last, st = None, {}
    try:
        while True:
            if time.time() - t0 > timeout:
                raise ProviderError(f"fal.ai: no result after {timeout} s", transient=False)
            s_ = httpx.get(status_url, headers=h, timeout=60)
            if s_.status_code >= 400:
                raise http_error("fal.ai status", s_)
            st = s_.json()
            state = st.get("status")
            if state != last:
                log(f"fal.ai: {state}" + (f" (queue position {st.get('queue_position')})" if state == "IN_QUEUE" else ""))
                last = state
            if progress:
                progress({"status": state, "queue_position": st.get("queue_position"), "elapsed": round(time.time() - t0)})
            if state == "COMPLETED":
                if st.get("error"):
                    raise ProviderError(f"fal.ai: generation failed: {st.get('error_type') or ''} {st['error']}"[:500])
                break
            time.sleep(4)
    except BaseException:
        if cancel_url and last != "COMPLETED":
            try:
                httpx.put(cancel_url, headers=h, timeout=30)
            except Exception:
                pass
        raise
    res = httpx.get(response_url, headers=h, timeout=120)
    if res.status_code >= 400:
        raise http_error("fal.ai result", res)
    data = res.json()
    url = (data.get("video") or {}).get("url")
    if not url:
        raise ProviderError("fal.ai: the result contained no video")
    v = httpx.get(url, timeout=300, follow_redirects=True)
    v.raise_for_status()
    out.write_bytes(v.content)
    return data, {"request_id": sub["request_id"], "seconds": round(time.time() - t0, 1),
                  "inference_seconds": (st.get("metrics") or {}).get("inference_time")}


def generate(db, model: str, image_url: str, prompt: str, params: dict, out: Path, log, progress=None, timeout: int = 1800) -> dict:
    """Submit one image-to-video request, poll it to completion and download the clip. Returns metadata."""
    m = MODELS[model]
    body = {**m["defaults"], **params, "image_url": image_url, "prompt": prompt}
    cost = estimate(model, params)
    data, tm = run(db, m["endpoint"], m["label"], body, cost, prompt, out, log, progress, timeout)
    meta = data.get("video") or {}
    actual = actual_cost(model, meta, body)
    if actual is not None and abs(actual - cost) > 0.0001:
        correct_spend(db, cost, actual)
    return {"actual_usd": actual if actual is not None else cost, "model": model, "endpoint": m["endpoint"],
            "request_id": tm["request_id"], "estimated_usd": cost, "seconds": tm["seconds"],
            "inference_seconds": tm["inference_seconds"], "width": meta.get("width"), "height": meta.get("height"),
            "fps": meta.get("fps"), "frames": meta.get("num_frames"), "seed": data.get("seed"), "licence": m["licence"]}
