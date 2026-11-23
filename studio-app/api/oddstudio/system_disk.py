"""Disk usage for the Overview page (2026-11-23, after the disk filled up during a deploy).

Read-only: nothing here deletes anything. Two sources:
  - the disk itself, measured now (os.statvfs on the studio's work folder, which is on the server's disk; the same
    numbers as `df -h`): size, used, free and the percent used;
  - the weekly housekeeping report, disk-report.json, written by deploy/maintenance.sh (dry run or --apply) into
    /srv/stickman/reports and mounted read-only into the API container (ODD_DISK_REPORT): the biggest consumers
    (backups, release folders, Docker images and build cache, media, database, logs) and what --apply would free.
The level is "ok" below 80%, "warn" from 80% and "critical" from 90%; the page shows a yellow warning or a red banner
that names the biggest consumers."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from .auth import current_user
from .config import get_settings

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

WARN_AT = 80
CRITICAL_AT = 90
STALE_DAYS = 8                     # the report is weekly: older than this, the page says so
DEFAULT_REPORT = "/srv/reports/disk-report.json"
FREE_KEYS = ("releases", "images", "build_cache", "backups", "journal", "other", "total")


def report_path() -> Path:
    return Path(os.environ.get("ODD_DISK_REPORT", DEFAULT_REPORT))


def disk_usage(path: Path) -> tuple[int, int, int]:
    """(size, used, free) in bytes for the filesystem holding `path`, as df counts them (free = what a normal user can
    still write, so used + free can be less than size: the filesystem keeps some blocks back for root)."""
    st = os.statvfs(path)
    return st.f_blocks * st.f_frsize, (st.f_blocks - st.f_bfree) * st.f_frsize, st.f_bavail * st.f_frsize


def percent_used(used: int, free: int) -> int:
    """df's Use%: used / (used + free), rounded up."""
    return math.ceil(used * 100 / (used + free)) if used + free > 0 else 0


def level_for(pct: int) -> str:
    return "critical" if pct >= CRITICAL_AT else "warn" if pct >= WARN_AT else "ok"


def _int(v) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise ValueError("not a size")
    return int(v)


def read_report(path: Path, now: datetime | None = None) -> tuple[dict | None, str | None]:
    """The housekeeping report, checked and trimmed to what the page shows, or (None, the reason it cannot be shown).
    The file is data written by a script on the server: every field is checked, nothing in it is trusted further."""
    if not path.is_file():
        return None, ("No housekeeping report yet. On the server, run maintenance.sh without options (a dry run: it "
                      "removes nothing) to see what uses the disk.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8")[:200_000])
        generated = datetime.strptime(str(raw["generated_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        consumers = [{"key": str(c["key"])[:40], "label": str(c["label"])[:80], "bytes": _int(c["bytes"])}
                     for c in raw["consumers"]]
        mode = "apply" if raw.get("mode") == "apply" else "dry-run"
        frees = raw.get("freed" if mode == "apply" else "would_free") or {}
        frees = {k: _int(frees[k]) for k in FREE_KEYS if k in frees}
    except (OSError, ValueError, KeyError, TypeError) as e:
        return None, f"The housekeeping report could not be read ({type(e).__name__}); run maintenance.sh again."
    now = now or datetime.now(timezone.utc)
    age_days = max(0.0, (now - generated).total_seconds() / 86400)
    consumers.sort(key=lambda c: c["bytes"], reverse=True)
    return {"generated_at": generated.strftime("%Y-%m-%dT%H:%M:%SZ"), "age_days": round(age_days, 1),
            "stale": age_days > STALE_DAYS, "mode": mode, "consumers": consumers,
            ("freed" if mode == "apply" else "would_free"): frees}, None


@router.get("/system/disk")
def disk():
    work = get_settings().work_dir
    path = work if work.exists() else Path("/")
    size, used, free = disk_usage(path)
    pct = percent_used(used, free)
    report, problem = read_report(report_path())
    return {"size": size, "used": used, "free": free, "percent": pct, "level": level_for(pct),
            "warn_at": WARN_AT, "critical_at": CRITICAL_AT,
            "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "report": report, "report_problem": problem,
            "biggest": [c for c in (report or {}).get("consumers", []) if c["bytes"] > 0][:4]}
