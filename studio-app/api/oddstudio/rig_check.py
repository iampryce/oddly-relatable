"""Rig check at pose approval (fix for render job 267, attempt 2, 2026-11-21): Ralph's approved neutral pose had its
hands hidden (hoodie pocket or sleeves), so the acting rig could not be built and the render failed with a NaN error
an hour into production. Now, whenever a pose is approved, the worker runs the same rig extraction on the character's
approved poses (the body from the rig's body pose, a head for every other expression) and records the result. The pose
card shows it, and production refuses to start while the body pose of a character in the episode cannot be rigged.
The approved images are only read; the check never changes an approval.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import REPO_ROOT

ROW = "_rig_checks"
RIG = REPO_ROOT / "production" / "animation" / "rig_extract.py"


def rig_error(output: str) -> str:
    """The clear message rig_extract.py prints (a `RIG-ERROR {...}` line); otherwise the last line of its output."""
    for line in reversed((output or "").strip().splitlines()):
        if line.startswith("RIG-ERROR "):
            try:
                return json.loads(line[len("RIG-ERROR "):])["message"]
            except (ValueError, KeyError):
                break
    lines = [ln for ln in (output or "").strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "the rig extraction failed")[-300:]


def body_pose_id(c) -> str | None:
    """The pose the acting rig builds the body from (the same choice as acting.rig_for)."""
    e = c.expressions or {}
    return e.get("neutral") or e.get(c.default_expression) or next(iter(e.values()), None)


def records(db) -> dict:
    from .models import Setting
    row = db.get(Setting, ROW)
    return dict(row.value) if row else {}


def save(db, recs: dict) -> None:
    from .models import Setting
    row = db.get(Setting, ROW)
    if row:
        row.value = recs
    else:
        db.add(Setting(key=ROW, value=recs))


def for_asset(db, asset_id: int) -> dict | None:
    return records(db).get(str(asset_id))


def check(c, poses: list[tuple[int, str, Path]], body_asset: int, folder: Path, timeout: int = 600) -> dict[str, dict]:
    """Run the rig extraction: the body pose first (the whole rig), then a head for every other approved pose.
    Returns {asset_id: {ok, role, message}}; ok is None when a pose could not be checked yet."""
    out: dict[str, dict] = {}
    now = time.time()
    body = next((p for p in poses if p[0] == body_asset), None)
    if body is None:
        return out
    rig_dir = Path(tempfile.mkdtemp(prefix="rig-check-", dir=folder))
    r = subprocess.run([sys.executable, str(RIG), str(body[2]), str(rig_dir)], capture_output=True, text=True,
                       timeout=timeout, stdin=subprocess.DEVNULL)
    ok = r.returncode == 0
    out[str(body[0])] = {"ok": ok, "role": "body", "checked": now,
                         "message": "the rig can be built from this pose" if ok else
                         f"{c.name}: the acting rig cannot be built from this pose: {rig_error(r.stderr or r.stdout)}"}
    for aid, name, f in poses:
        if aid == body_asset:
            continue
        if not ok:
            out[str(aid)] = {"ok": None, "role": "face", "checked": now,
                             "message": f"not checked: {c.name}'s body pose must pass the rig check first"}
            continue
        h = subprocess.run([sys.executable, str(RIG), str(f), str(rig_dir), "--head-only", name], capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        out[str(aid)] = {"ok": h.returncode == 0, "role": "face", "checked": now,
                         "message": "the face can be animated" if h.returncode == 0 else
                         f"{c.name}: this expression's face cannot be rigged ({rig_error(h.stderr or h.stdout)}); "
                         "the neutral face is used instead"}
    return out


def blocking_problems(db, chars: list) -> list[str]:
    """Characters whose rig BODY pose failed its check (production would fail during the render)."""
    from .models import Job
    recs = records(db)
    bad = []
    pending = {j.character_id for j in db.query(Job).filter(Job.kind == "rig_check", Job.status.in_(("queued", "running")))}
    for c in chars:
        if c.locked or c.art_status != "approved":
            continue
        if c.id in pending:
            bad.append(f"{c.name}: the rig check of the approved poses is still running; start production when it has finished.")
            continue
        pid = body_pose_id(c)
        rec = recs.get(pid[1:]) if pid and pid.startswith("p") else None
        if rec and rec.get("role") == "body" and rec.get("ok") is False:
            bad.append(rec["message"])
    return bad


# ------------------------------------------------------------------ job
from .tasks import Ctx, task  # noqa: E402


@task
def rig_check(ctx: Ctx) -> dict:
    from . import engine
    from .models import Character, CharacterAsset
    from .storage import storage
    db, job = ctx.db, ctx.job
    c = db.get(Character, job.character_id)
    if c is None or c.locked or c.art_status != "approved":
        return {"checked": 0}
    pid = body_pose_id(c)
    assets = db.query(CharacterAsset).filter_by(character_id=c.id, kind="pose", status="approved").all()
    folder = ctx.folder("rig-checks", c.key)
    poses = []
    for a in assets:
        src = storage().get_to_file(a.storage_key, folder / f"pose-{a.id}.png")
        trimmed, _ = engine.trim_pose(src, folder / f"pose-{a.id}-trim.png", a.feet or {"x": 0, "y": 0})   # what the render rigs
        poses.append((a.id, a.expression, trimmed))
    res = check(c, poses, int(pid[1:]) if pid and pid.startswith("p") else -1, folder)
    recs = records(db)
    recs.update(res)
    save(db, recs)
    for v in res.values():
        if v["ok"] is False:
            ctx.log(v["message"])
    db.commit()
    return {"checked": len(res), "failed": sum(1 for v in res.values() if v["ok"] is False)}
