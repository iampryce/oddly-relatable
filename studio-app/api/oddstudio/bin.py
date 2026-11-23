"""The Bin (owner decision 2026-11-21): delete old generated things safely.

Delete = move to the Bin (soft delete): the item is hidden from every page and picker and can be restored for 30 days.
"Delete forever" / "Empty Bin" remove the database rows and the files (storage files and the episode's work folder,
always inside the studio's data folders), after a confirmation that lists exactly what goes and the space freed.
Items in the Bin for more than 30 days are purged by the weekly maintenance --apply (`python -m oddstudio.bin purge`),
and logged. Backups are unchanged: until purged, binned items are still in the database and storage they back up.

Kinds: character, pose (a character's pose in any status), set (candidate or approved), episode, clip (a
motion-comparison video). Protection (refused with the reason naming the episode): anything used by another
non-deleted episode (characters, approved poses of a character in use, sets), locked repository art, and episodes that
are rendered or published. Deleting an episode never deletes the characters or sets it used.
Archive (Characters page, Clean up) is different: it only hides a character on that page; nothing is ever removed.
"""
from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Asset, BinItem, Character, CharacterAsset, Episode, Event, StoryboardScene

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
KINDS = ("character", "pose", "set", "episode", "clip")
KEEP_DAYS = 30
RENDERED = ("producing", "video_review", "final_approved", "publishing", "published")


def now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ what is binned (hidden everywhere)
def hidden(db: Session, kind: str) -> set[str]:
    return {b.ref for b in db.query(BinItem).filter_by(kind=kind)}


def hidden_ids(db: Session, kind: str) -> set[int]:
    return {int(x) for x in hidden(db, kind) if x.isdigit()}


def live_episodes(db: Session) -> list[Episode]:
    gone = hidden_ids(db, "episode")
    return [e for e in db.query(Episode).all() if e.id not in gone]


# ------------------------------------------------------------------ files and sizes
def _size(key: str) -> int:
    from .storage import storage
    try:
        p = storage().local_path(key)
        return p.stat().st_size if p and p.exists() else 0
    except (ValueError, OSError):
        return 0


def _work_folder(eid: int):
    from .config import get_settings
    root = get_settings().work_dir.resolve()
    p = (root / "episodes" / str(int(eid))).resolve()
    return p if p.is_relative_to(root) and p.exists() else None


def _folder_size(p) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p else 0


def files_of(db: Session, kind: str, ref: str) -> tuple[list[str], int, str | None]:
    """(storage keys, bytes including the work folder, work folder path) of an item."""
    from . import sets
    keys: list[str] = []
    folder = None
    if kind == "character":
        keys = [a.storage_key for a in db.query(CharacterAsset).filter_by(character_id=int(ref))]
    elif kind == "pose":
        a = db.get(CharacterAsset, int(ref))
        keys = [a.storage_key] if a else []
    elif kind == "set":
        r = sets.records(db).get(ref) or {}
        keys = [a.storage_key for a in (db.get(Asset, r.get(k)) for k in ("asset_id", "preview_asset_id") if r.get(k)) if a]
    elif kind == "episode":
        keys = [a.storage_key for a in db.query(Asset).filter_by(episode_id=int(ref))]
        f = _work_folder(int(ref))
        folder = str(f) if f else None
    elif kind == "clip":
        a = db.get(Asset, int(ref))
        keys = [a.storage_key] if a else []
    size = sum(_size(k) for k in keys) + (_folder_size(_work_folder(int(ref))) if kind == "episode" else 0)
    return keys, size, folder


# ------------------------------------------------------------------ protection
def _set_users(db: Session, set_id: str) -> list[Episode]:
    out = []
    for e in live_episodes(db):
        scene_sets = {s.set_id for s in db.query(StoryboardScene).filter_by(episode_id=e.id) if s.set_id}
        if e.set_id == set_id or set_id in (e.scene_set_ids or []) or set_id in scene_sets:
            out.append(e)
    return out


def _char_users(db: Session, key: str) -> list[dict]:
    from .character_admin import usage
    gone = hidden_ids(db, "episode")
    return [u for u in usage(db).get(key, []) if u["id"] not in gone]


def _named(eps) -> str:
    return "; ".join(f"episode {e['id'] if isinstance(e, dict) else e.id} \"{e['title'] if isinstance(e, dict) else e.title}\"" for e in eps)


def protect(db: Session, kind: str, ref: str) -> str | None:
    """Why this item may not be deleted (None: it may)."""
    from . import sets
    if kind == "character":
        c = db.get(Character, int(ref))
        if c is None:
            return "no such character"
        if c.locked:
            return f"{c.name} is approved repository artwork (locked)"
        users = _char_users(db, c.key)
        if users:
            return f"{c.name} is used by {_named(users)}"
    elif kind == "pose":
        a = db.get(CharacterAsset, int(ref))
        if a is None or a.kind != "pose":
            return "no such pose"
        c = db.get(Character, a.character_id)
        if c.locked:
            return f"{c.name}'s poses are approved repository artwork (locked)"
        users = _char_users(db, c.key)
        if a.status == "approved" and users:
            return f"{c.name}'s approved {a.expression} pose is used by {_named(users)}"
    elif kind == "set":
        if ref not in sets.records(db):
            return "no such set"
        users = _set_users(db, ref)
        if users:
            return f"the set {ref!r} is used by {_named(users)}"
    elif kind == "episode":
        e = db.get(Episode, int(ref))
        if e is None:
            return "no such episode"
        if e.stage in RENDERED:
            return f"episode {e.id} \"{e.title}\" is rendered or published ({e.stage})"
    elif kind == "clip":
        a = db.get(Asset, int(ref))
        if a is None or not is_comparison_clip(a):
            return "only motion-comparison clips can be deleted here"
    else:
        return f"unknown kind {kind!r}"
    return None


def is_comparison_clip(a) -> bool:
    """A motion-comparison video (the Leo & Ben comparison or the shot comparison), never an episode's own render."""
    key = a.storage_key or ""
    return a.kind == "video" and ("/comparison/" in key or "/shot-compare/" in key or "/draft/" in key)


def label_of(db: Session, kind: str, ref: str) -> str:
    if kind == "character":
        c = db.get(Character, int(ref))
        return f"Character {c.name} ({c.key})"
    if kind == "pose":
        a = db.get(CharacterAsset, int(ref))
        c = db.get(Character, a.character_id)
        return f"{c.name}: {a.expression} pose ({a.status})"
    if kind == "set":
        from . import sets
        r = sets.records(db).get(ref, {})
        return f"Set {r.get('label', ref)} ({r.get('status')})"
    if kind == "episode":
        e = db.get(Episode, int(ref))
        return f"Episode {e.id} \"{e.title}\" ({e.stage})"
    a = db.get(Asset, int(ref))
    return f"Clip: {a.label}"


# ------------------------------------------------------------------ move, restore, delete forever
def move(db: Session, kind: str, ref: str, user: str) -> BinItem:
    from . import sets
    from .routes_characters import refresh_art
    ref = str(ref)
    if db.query(BinItem).filter_by(kind=kind, ref=ref).first():
        raise HTTPException(409, "already in the Bin")
    why = protect(db, kind, ref)
    if why:
        raise HTTPException(409, f"cannot delete: {why}")
    keys, size, folder = files_of(db, kind, ref)
    extra = {}
    if kind == "pose":
        a = db.get(CharacterAsset, int(ref))
        extra["status"] = a.status
        a.status = "binned"
        db.flush()
        refresh_art(db, db.get(Character, a.character_id))
    elif kind == "set":
        recs = sets.records(db)
        extra["status"] = recs[ref].get("status")
        recs[ref]["status"] = "binned"
        sets.save(db, recs)
    item = BinItem(kind=kind, ref=ref, label=label_of(db, kind, ref) if kind != "set" else
                   f"Set {sets.records(db)[ref].get('label', ref)} ({extra['status']})",
                   size_bytes=size, deleted_at=now(), deleted_by=user, files=keys, extra={**extra, "folder": folder})
    db.add(item)
    db.add(Event(episode_id=int(ref) if kind == "episode" else None, kind="bin", message=f"Moved to the Bin by {user}: {item.label}"))
    db.flush()
    return item


def restore(db: Session, item: BinItem, user: str) -> None:
    from . import sets
    from .routes_characters import refresh_art
    if item.kind == "pose":
        a = db.get(CharacterAsset, int(item.ref))
        if a is not None:
            want = (item.extra or {}).get("status") or "review"
            taken = db.query(CharacterAsset).filter_by(character_id=a.character_id, kind="pose", expression=a.expression,
                                                       status="approved").first()
            a.status = "review" if want == "approved" and taken else want   # never two approved poses for one expression
            db.flush()
            refresh_art(db, db.get(Character, a.character_id))
    elif item.kind == "set":
        recs = sets.records(db)
        if item.ref in recs:
            recs[item.ref]["status"] = (item.extra or {}).get("status") or "candidate"
            sets.save(db, recs)
    db.add(Event(episode_id=None, kind="bin", message=f"Restored from the Bin by {user}: {item.label}"))
    db.delete(item)


def _delete_file(key: str) -> None:
    from .storage import storage
    try:
        storage().delete(key)
    except (ValueError, OSError):
        pass


def forever(db: Session, item: BinItem, user: str) -> int:
    """Remove the rows and the files for good; returns the bytes freed."""
    from . import sets
    freed = item.size_bytes or 0
    for k in item.files or []:
        _delete_file(k)
    if item.kind == "episode":
        f = _work_folder(int(item.ref))
        if f:
            shutil.rmtree(f, ignore_errors=True)
    if item.kind == "character":
        c = db.get(Character, int(item.ref))
        if c is not None:
            db.delete(c)
    elif item.kind == "pose":
        a = db.get(CharacterAsset, int(item.ref))
        if a is not None:
            db.delete(a)
    elif item.kind == "set":
        recs = sets.records(db)
        r = recs.pop(item.ref, None) or {}
        for k in ("asset_id", "preview_asset_id"):
            a = db.get(Asset, r.get(k)) if r.get(k) else None
            if a is not None:
                db.delete(a)
        sets.save(db, recs)
    elif item.kind == "episode":
        e = db.get(Episode, int(item.ref))
        if e is not None:
            for a in db.query(Asset).filter_by(episode_id=e.id):
                db.delete(a)
            db.delete(e)
    elif item.kind == "clip":
        a = db.get(Asset, int(item.ref))
        if a is not None:
            db.delete(a)
    db.add(Event(episode_id=None, kind="bin", message=f"Deleted forever by {user}: {item.label} ({freed} bytes)"))
    db.delete(item)
    return freed


def expired(db: Session, days: int = KEEP_DAYS) -> list[BinItem]:
    cut = now() - timedelta(days=days)
    return [b for b in db.query(BinItem).order_by(BinItem.id) if _aware(b.deleted_at) < cut]


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ bulk
def bulk_candidates(db: Session, what: str) -> tuple[list[tuple[str, str]], list[str]]:
    """[(kind, ref)] the bulk action would move, and the reasons for those it must leave."""
    from . import sets
    out, left = [], []
    if what == "poses":
        locked = {c.id for c in db.query(Character).filter_by(locked=True)}
        gone = hidden_ids(db, "character")
        for a in db.query(CharacterAsset).filter(CharacterAsset.kind == "pose",
                                                 CharacterAsset.status.in_(("review", "rejected", "rig_failed"))):
            if a.character_id not in locked and a.character_id not in gone:
                out.append(("pose", str(a.id)))
    elif what == "sets":
        for k, r in sets.records(db).items():
            if r.get("status") in ("candidate", "rejected"):
                why = protect(db, "set", k)
                (left.append(why) if why else out.append(("set", k)))
    elif what == "episodes":
        for e in live_episodes(db):
            if e.stage == "production_failed":
                why = protect(db, "episode", str(e.id))
                (left.append(why) if why else out.append(("episode", str(e.id))))
    else:
        raise HTTPException(422, "unknown bulk action")
    return out, left


# ------------------------------------------------------------------ routes
def view(b: BinItem) -> dict:
    left = KEEP_DAYS - (now() - _aware(b.deleted_at)).days
    return {"id": b.id, "kind": b.kind, "ref": b.ref, "label": b.label, "size_bytes": b.size_bytes,
            "deleted_at": _aware(b.deleted_at).isoformat(), "deleted_by": b.deleted_by, "days_left": max(0, left),
            "files": len(b.files or [])}


@router.get("/bin")
def list_bin(db: Session = Depends(get_db)):
    items = db.query(BinItem).order_by(BinItem.deleted_at.desc()).all()
    return {"items": [view(b) for b in items], "total_bytes": sum(b.size_bytes or 0 for b in items), "keep_days": KEEP_DAYS}


class MoveIn(BaseModel):
    kind: str
    ref: str = Field(min_length=1, max_length=80)


@router.post("/bin/move")
def move_one(body: MoveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    if body.kind not in KINDS:
        raise HTTPException(422, "unknown kind")
    item = move(db, body.kind, body.ref, user)
    db.commit()
    return view(item)


@router.get("/bin/check")
def check(kind: str, ref: str, db: Session = Depends(get_db)):
    """Free: whether an item may be deleted (and why not), before the confirm dialog."""
    why = protect(db, kind, ref) if kind in KINDS else "unknown kind"
    keys, size, _ = files_of(db, kind, ref) if not why else ([], 0, None)
    return {"allowed": why is None, "reason": why, "files": len(keys), "size_bytes": size}


@router.post("/bin/{bid}/restore")
def restore_one(bid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    b = db.get(BinItem, bid)
    if b is None:
        raise HTTPException(404, "not in the Bin")
    warning = missing_for(db, b) if b.kind == "episode" else ""
    restore(db, b, user)
    db.commit()
    return {"restored": b.label, "warning": warning}


def missing_for(db: Session, b: BinItem) -> str:
    """An episode restored after some of its characters or sets were deleted: name them (production will refuse until
    they are replaced)."""
    from . import sets
    from .character_admin import usage
    eid = int(b.ref)
    e = db.get(Episode, eid)
    if e is None:
        return ""
    gone_chars = hidden_ids(db, "character")
    chars = {c.key: c for c in db.query(Character).all()}
    used = [k for k, eps in usage(db).items() if any(x["id"] == eid for x in eps)]
    missing = [k for k in used if k not in chars or chars[k].id in gone_chars]
    want = {e.set_id, *(e.scene_set_ids or [])} - {None}
    usable = sets.usable(db)
    missing_sets = [s for s in want if s not in usable]
    parts = ([f"characters no longer available: {', '.join(sorted(missing))}"] if missing else []) + \
            ([f"sets no longer available: {', '.join(sorted(missing_sets))}"] if missing_sets else [])
    return "; ".join(parts) + ("; production will ask for replacements" if parts else "")


class ForeverIn(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=500)
    all: bool = False
    confirm: bool = False


@router.post("/bin/forever")
def delete_forever(body: ForeverIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Without confirm: exactly what would go and the space freed. With confirm: remove rows and files for good."""
    q = db.query(BinItem)
    items = q.all() if body.all else [b for b in q.filter(BinItem.id.in_(body.ids or [-1]))]
    preview = {"items": [view(b) for b in items], "count": len(items), "bytes": sum(b.size_bytes or 0 for b in items)}
    if not body.confirm:
        return preview
    freed = sum(forever(db, b, user) for b in items)
    db.commit()
    return {**preview, "deleted": len(items), "freed_bytes": freed}


class BulkIn(BaseModel):
    confirm: bool = False


@router.post("/bin/bulk/{what}")
def bulk(what: str, body: BulkIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Without confirm: the list and count the bulk action would move to the Bin. With confirm: move them."""
    cands, left = bulk_candidates(db, what)
    rows = [{"kind": k, "ref": r, "label": label_of(db, k, r), "size_bytes": files_of(db, k, r)[1]} for k, r in cands]
    out = {"items": rows, "count": len(rows), "bytes": sum(r["size_bytes"] for r in rows), "kept": left}
    if not body.confirm:
        return out
    moved = [move(db, k, r, user).label for k, r in cands]
    db.commit()
    return {**out, "moved": len(moved)}


# ------------------------------------------------------------------ clearing failed jobs (Production)
FAILED_STAGES = ("production_failed", "publish_failed")


def job_keep_reason(db: Session, job) -> str | None:
    """Why a failed job must stay listed: it is the latest job of its kind for a live episode whose production (or
    publishing) failed there, so that episode needs it to retry. None: it can be cleared."""
    from .models import Job
    if job.status != "failed" or not job.episode_id:
        return None
    ep = db.get(Episode, job.episode_id)
    if ep is None or ep.id in hidden_ids(db, "episode") or ep.stage not in FAILED_STAGES:
        return None
    latest = db.query(Job).filter_by(episode_id=ep.id, kind=job.kind).order_by(Job.id.desc()).first()
    if latest is None or latest.id != job.id:
        return None
    return (f"episode {ep.id} \"{ep.title}\" is {ep.stage.replace('_', ' ')} at this step: retry it (or move the episode "
            "to the Bin) first")


def _start_of_today() -> datetime:
    t = now()
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


@router.post("/jobs/{jid}/clear")
def clear_job(jid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Hide one failed job from Production (never deleted; still in the episode's history)."""
    from .models import Job
    j = db.get(Job, jid)
    if j is None or j.status != "failed":
        raise HTTPException(409, "only failed jobs can be cleared")
    why = job_keep_reason(db, j)
    if why:
        raise HTTPException(409, f"kept: {why}")
    j.cleared_at = now()
    db.add(Event(episode_id=j.episode_id, kind="job", message=f"Failed job {j.id} ({j.kind}) cleared by {user}"))
    db.commit()
    return {"cleared": [j.id]}


class ClearIn(BaseModel):
    confirm: bool = False


@router.post("/jobs/clear-failed")
def clear_failed(body: ClearIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Failed jobs from before today. Without confirm: the count, and those kept with the reason. With confirm: clear."""
    from .models import Job
    cut = _start_of_today()
    rows = db.query(Job).filter(Job.status == "failed", Job.cleared_at.is_(None)).order_by(Job.id).all()
    old = [j for j in rows if _aware(j.finished_at or j.created_at) < cut]
    kept = [{"id": j.id, "kind": j.kind, "reason": job_keep_reason(db, j)} for j in old if job_keep_reason(db, j)]
    go = [j for j in old if not job_keep_reason(db, j)]
    out = {"count": len(go), "ids": [j.id for j in go], "kept": kept}
    if not body.confirm:
        return out
    for j in go:
        j.cleared_at = now()
    db.add(Event(episode_id=None, kind="job", message=f"{len(go)} failed job(s) from before today cleared by {user}"))
    db.commit()
    return {**out, "cleared": len(go)}


# ------------------------------------------------------------------ maintenance: python -m oddstudio.bin purge
def main(argv: list[str]) -> int:
    from .db import new_session
    if len(argv) < 1 or argv[0] != "purge":
        print("usage: python -m oddstudio.bin purge [--days N] [--dry-run]")
        return 2
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else KEEP_DAYS
    dry = "--dry-run" in argv
    with new_session() as db:
        items = expired(db, days)
        total = sum(b.size_bytes or 0 for b in items)
        print(f"bin: {len(items)} item(s) in the Bin for more than {days} days ({total} bytes)"
              + (": would purge" if dry else ": purging"))
        for b in items:
            print(f"  {'would purge' if dry else 'purged'}  {b.kind} {b.label} ({b.size_bytes} bytes)")
            if not dry:
                forever(db, b, "maintenance")
        if not dry:
            db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
