"""Characters page housekeeping (owner request 2026-11-21): which episodes use each character, and archiving or
deleting characters that no live episode uses.

A character is USED by an episode when its key is the episode's own character (scope episode), is on screen in a
storyboard scene, is in the episode's current script (cast or a speaker), or is mapped from an audio speaker. An episode
is LIVE until it is published. Archiving only hides a character on the Characters page (reversible); deleting removes
it and its pose records for good and needs the names typed back as confirmation. Approved repository artwork (locked
characters) is never archived or deleted here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, ScriptVersion, StoryboardScene, Setting

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
ROW = "_archived_characters"
FINISHED = ("published",)


def archived(db: Session) -> set[int]:
    row = db.get(Setting, ROW)
    return set((row.value or {}).get("ids", [])) if row else set()


def _save_archived(db: Session, ids: set[int]) -> None:
    row = db.get(Setting, ROW)
    if row:
        row.value = {"ids": sorted(ids)}
    else:
        db.add(Setting(key=ROW, value={"ids": sorted(ids)}))


def usage(db: Session) -> dict[str, list[dict]]:
    """{character key: [{id, title, stage, live}]} for every episode that uses it."""
    out: dict[str, dict[int, dict]] = {}
    eps = {e.id: e for e in db.query(Episode).all()}

    def add(key, eid):
        e = eps.get(eid)
        if key and e is not None:
            out.setdefault(key, {})[eid] = {"id": e.id, "title": e.title, "stage": e.stage, "live": e.stage not in FINISHED}

    for c in db.query(Character).filter(Character.episode_id.isnot(None)):
        add(c.key, c.episode_id)
    from .acting import referenced   # speaker, look-at target and reactions: everyone the renderer casts
    for s in db.query(StoryboardScene).all():
        for k in s.characters or []:
            add(k, s.episode_id)
        for ln in s.lines or []:
            for k in referenced(ln):
                add(k, s.episode_id)
    for e in eps.values():
        for k in ((e.audio_transcript or {}).get("cast") or {}).values():
            add(k, e.id)
        if e.script_version:
            sv = db.query(ScriptVersion).filter_by(episode_id=e.id, version=e.script_version).one_or_none()
            if sv is not None:
                c = sv.content or {}
                for ch in c.get("characters", []):
                    add(ch.get("key"), e.id)
                for sc in c.get("scenes", []):
                    for ln in sc.get("lines", []):
                        for k in referenced(ln):
                            add(k, e.id)
    return {k: sorted(v.values(), key=lambda x: x["id"]) for k, v in out.items()}


@router.get("/characters/usage")
def get_usage(db: Session = Depends(get_db)):
    return {"usage": usage(db), "archived": sorted(archived(db))}


class IdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


def _removable(db: Session, ids: list[int], verb: str) -> list[Character]:
    chars = [db.get(Character, i) for i in ids]
    if any(c is None for c in chars):
        raise HTTPException(404, "character not found")
    locked = [c.name for c in chars if c.locked]
    if locked:
        raise HTTPException(409, f"approved repository artwork cannot be {verb}: {', '.join(locked)}")
    use = usage(db)
    busy = [f"{c.name} ({', '.join(e['title'] for e in use.get(c.key, []) if e['live'])})"
            for c in chars if any(e["live"] for e in use.get(c.key, []))]
    if busy:
        raise HTTPException(409, f"used by a live episode, so it cannot be {verb}: {'; '.join(busy)}")
    return chars


@router.post("/characters/archive")
def archive(body: IdsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    chars = _removable(db, body.ids, "archived")
    _save_archived(db, archived(db) | {c.id for c in chars})
    db.add(Event(episode_id=None, kind="character", message=f"Archived by {user}: {', '.join(c.name for c in chars)}"))
    db.commit()
    return {"archived": sorted(archived(db))}


@router.post("/characters/unarchive")
def unarchive(body: IdsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    _save_archived(db, archived(db) - set(body.ids))
    db.add(Event(episode_id=None, kind="character", message=f"Restored from the archive by {user}: {len(body.ids)} character(s)"))
    db.commit()
    return {"archived": sorted(archived(db))}


class DeleteIn(IdsIn):
    confirm_names: list[str] = Field(min_length=1, max_length=200)


@router.post("/characters/delete")
def delete(body: DeleteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Permanent: the characters and their pose records. The owner confirms by sending back exactly their names."""
    chars = _removable(db, body.ids, "deleted")
    names = sorted(c.name for c in chars)
    if sorted(body.confirm_names) != names:
        raise HTTPException(422, f"confirm by naming exactly: {', '.join(names)}")
    for c in chars:
        db.delete(c)
    _save_archived(db, archived(db) - {c.id for c in chars})
    db.add(Event(episode_id=None, kind="character", message=f"Deleted by {user}: {', '.join(names)}"))
    db.commit()
    return {"deleted": names}
