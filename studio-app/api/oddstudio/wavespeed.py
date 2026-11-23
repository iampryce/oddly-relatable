"""WaveSpeedAI hosted generation (talking shots in the shot comparison): one task per owner click, never retried.

API (WaveSpeed docs, read 2026-11-23):
- submit: POST https://api.wavespeed.ai/api/v3/<model id> with "Authorization: Bearer <key>" and a JSON body; the task
  id is data.id. A submit is NEVER retried: WaveSpeed warns that a retry after an unclear failure can create a second,
  billed task.
- result: GET https://api.wavespeed.ai/api/v3/predictions/<id>/result, polled at least 2 s apart. data.status
  "completed" -> data.outputs (URLs); "failed", "cancelled", "timeout" or "deleted" end it. Only this GET (and the
  download of the finished video, also a GET) may be repeated after a rate limit, a server error or a dropped
  connection.
- outputs are deleted by WaveSpeed after 7 days, so the video is downloaded into our storage at once.

Spend: the estimate is checked against the experimental budget (Settings > Motion, shared with fal.ai's ledger) before
submitting and recorded once WaveSpeed accepts the task. The key lives in the credential store as `wavespeed_api_key`
and is only ever put in the Authorization header; it is never logged, returned or stored anywhere else.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from .providers import ProviderError, ProviderNotConfigured
from .secrets_store import secret

API = "https://api.wavespeed.ai/api/v3"
DONE, FAILED = "completed", ("failed", "cancelled", "timeout", "deleted")
POLL_S = 3.0
GET_TRIES = 5          # a poll or the download: repeated after 429 / 5xx / network errors (GETs only, never billed)

_test_run = None       # tests only: fn(endpoint, body, out) -> {"id", "outputs", ...} (the video already written)
_sleep = time.sleep    # tests replace this


def set_test_run(fn) -> None:
    """Tests only: replace the network calls (submit, poll, download) with fn(endpoint, body, out)."""
    global _test_run
    _test_run = fn


def _key() -> str:
    k = secret("wavespeed_api_key")
    if not k:
        raise ProviderNotConfigured("WaveSpeed: save the WaveSpeed API key under Settings > Credentials")
    return k


def _error(what: str, r: httpx.Response, key: str) -> ProviderError:
    # never transient: the shot comparison does not retry a paid call by itself; the owner decides
    return ProviderError(f"WaveSpeed {what}: HTTP {r.status_code}: {r.text[:300].replace(key, '***')}", transient=False)


def _get(url: str, headers: dict, what: str, key: str, timeout: int = 60) -> httpx.Response:
    """A GET (poll or download) repeated after a rate limit, a server error or a dropped connection."""
    last: Exception | None = None
    for i in range(GET_TRIES):
        try:
            r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            if r.status_code == 429 or r.status_code >= 500:
                last = _error(what, r, key)
            elif r.status_code >= 400:
                raise _error(what, r, key)
            else:
                return r
        except httpx.HTTPError as e:
            last = ProviderError(f"WaveSpeed {what}: {type(e).__name__}", transient=False)
        _sleep(min(30, 2 * 2 ** i))
    raise last or ProviderError(f"WaveSpeed {what}: no answer", transient=False)


def run(db, endpoint: str, body: dict, cost: float, note: str, out: Path, log, progress=None, accepted=None,
        timeout: int = 1800) -> tuple[dict, dict]:
    """Submit ONE task, poll it to completion and download the video to `out`. The estimate is checked against the
    experimental budget before submitting and recorded once WaveSpeed accepts the task (`accepted(task_id)` is called
    then, so the caller can count it too). Returns (result, timing)."""
    from . import fal
    fal.check_budget(db, cost, who="WaveSpeed")
    t0 = time.time()
    if _test_run is not None:
        fal.reserve(db, endpoint, cost, f"test: {note}", who="WaveSpeed")
        if accepted:
            accepted("test-task")
        data = _test_run(endpoint, body, out)
        return data, {"request_id": data.get("id", "test"), "seconds": round(time.time() - t0, 1)}
    key = _key()
    from .config import get_settings
    if get_settings().env == "test":
        raise ProviderError("WaveSpeed: no network calls in tests (set a test stub)", transient=False)
    h = {"Authorization": f"Bearer {key}"}
    try:
        r = httpx.post(f"{API}/{endpoint}", json=body, headers={**h, "Content-Type": "application/json"}, timeout=60)
    except httpx.HTTPError as e:
        # unclear whether WaveSpeed accepted it: not retried; the owner checks WaveSpeed's dashboard before running again
        raise ProviderError(f"WaveSpeed submit: {type(e).__name__}; not retried (check WaveSpeed before running again)", transient=False)
    if r.status_code >= 400:
        raise _error("submit", r, key)       # refused: not billed and not recorded
    tid = ((r.json() or {}).get("data") or {}).get("id")
    if not tid:
        raise ProviderError("WaveSpeed submit: no task id in the answer", transient=False)
    fal.reserve(db, endpoint, cost, f"wavespeed {tid}: {note}", who="WaveSpeed")   # accepted: counts against the budget
    if accepted:
        accepted(tid)
    log(f"WaveSpeed: task {tid} accepted, estimated ${cost:.3f}")
    last, d = None, {}
    while True:
        if time.time() - t0 > timeout:
            raise ProviderError(f"WaveSpeed: no result after {timeout} s (task {tid})", transient=False)
        d = (_get(f"{API}/predictions/{tid}/result", h, "result", key).json() or {}).get("data") or {}
        state = d.get("status")
        if state != last:
            log(f"WaveSpeed: {state}")
            last = state
        if progress:
            progress({"status": state, "elapsed": round(time.time() - t0)})
        if state == DONE:
            break
        if state in FAILED:
            raise ProviderError(f"WaveSpeed: task {tid} {state}: {str(d.get('error') or '')[:300]}", transient=False)
        _sleep(POLL_S)
    outs = d.get("outputs") or []
    if not outs or not isinstance(outs[0], str):
        raise ProviderError(f"WaveSpeed: task {tid} finished without a video", transient=False)
    out.write_bytes(_get(outs[0], {}, "download", key, timeout=300).content)
    return {**d, "id": tid}, {"request_id": tid, "seconds": round(time.time() - t0, 1),
                              "inference_ms": (d.get("timings") or {}).get("inference"), "output_url": outs[0]}
