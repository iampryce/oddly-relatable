"""Per-scene sets (owner decision 2026-11-21): a story that moves location changes set at a scene cut.

- The episode's sets: its own set (chosen explicitly, feat/episode-set) plus the approved sets the owner adds "for
  scene changes". Only these can be used by a scene.
- A scene uses its own set when it has one, else the episode's set (the owner's explicit choice, not a default).
- Who assigns them: the simple split (from the accepted video notes: a scene changes set only when the notes' setting
  changes AND one of the episode's sets matches the new setting; otherwise it keeps the previous scene's set), the AI
  writer (given the episode's sets and the continuity rules; an unknown set keeps the previous scene's set, and the
  event log says so), or the owner on the storyboard.
- Continuity: a set changes only at a cut; each cut starts the scene in its own staging (seated/standing) on its own
  set's seats; a set that is no longer approved blocks production with the scene named (never a silent default).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Episode, Event, StoryboardScene

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
LOCKED = ("producing", "publishing")
CONTINUITY = ("Keep the same set from scene to scene; change it only when the story clearly moves to another place, "
              "and only to one of the listed sets.")


def episode_sets(db: Session, ep: Episode) -> list[str]:
    """The sets this episode's scenes may use: its own set first, then the extra ones (approved ones only)."""
    from . import sets
    ok = sets.usable(db)
    out = [s for s in [ep.set_id, *(ep.scene_set_ids or [])] if s and s in ok]
    return list(dict.fromkeys(out))


def sets_text(db: Session, ep: Episode) -> str:
    from . import sets
    ok = sets.usable(db)
    ids = episode_sets(db, ep)
    if len(ids) < 2:
        return ""
    rows = "\n".join(f"- {k}: {ok[k]['label']}. {ok[k]['description'][:160]}" for k in ids)
    return (f"\nSETS for this episode (give each scene a \"set\" from this list; the first is the episode's main set). "
            f"{CONTINUITY}\n{rows}\n")


def continuity(scenes: list[dict], allowed: list[str]) -> list[str]:
    """Each scene's set after the rules: unknown sets keep the previous scene's set. Returns what was changed."""
    notes, prev = [], None
    for s in scenes:
        want = s.get("set")
        if want and want not in allowed:
            notes.append(f"{s.get('id')}: {want!r} is not one of this episode's sets; kept "
                         f"{prev or 'the episode set'}")
            want = prev
        if want:
            s["set"] = want
        else:
            s.pop("set", None)
        prev = want or prev
    return notes


def from_notes(db: Session, scenes: list[dict], first_settings: list[str | None], allowed: list[str]) -> None:
    """The simple split: a scene changes set only when the notes' setting changes and an episode set matches it."""
    from . import sets
    ok = sets.usable(db)
    prev_word, prev_set = None, None
    for s, word in zip(scenes, first_settings):
        if word and prev_word is not None and word != prev_word:
            w = word.lower()
            match = next((k for k in allowed if w in f"{k} {ok[k]['label']} {ok[k]['description']}".lower().replace("-", " ")), None)
            if match:
                prev_set = match
        if prev_set and prev_set != (allowed[0] if allowed else None):
            s["set"] = prev_set
        if word:
            prev_word = word


def scene_set(ep: Episode, scene) -> str | None:
    return getattr(scene, "set_id", None) or ep.set_id


def problems(db: Session, ep: Episode, scenes) -> list[str]:
    """Scenes whose set cannot be staged (withdrawn, or not one of the episode's sets): production refuses."""
    from . import sets
    ok = sets.usable(db)
    allowed = set(episode_sets(db, ep))
    out = []
    for sc in scenes:
        sid = getattr(sc, "set_id", None)
        if sid and (sid not in ok or sid not in allowed):
            out.append(f"scene {sc.position} ({sc.heading}) uses the set {sid!r}, which is "
                       + ("not an approved set any more" if sid not in ok else "not one of this episode's sets"))
    return out


# ------------------------------------------------------------------ routes
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


class SceneSetsIn(BaseModel):
    set_ids: list[str] = Field(default_factory=list, max_length=8)


@router.put("/episodes/{eid}/scene-sets")
def put_scene_sets(eid: int, body: SceneSetsIn, db: Session = Depends(get_db)):
    """The extra approved sets this episode's scenes may change to (its own set is always included)."""
    from . import sets
    ep = _episode(db, eid)
    if ep.stage in LOCKED:
        raise HTTPException(409, f"not while the episode is {ep.stage}")
    ok = sets.usable(db)
    bad = [s for s in body.set_ids if s not in ok]
    if bad:
        raise HTTPException(422, f"only approved sets can be used: {', '.join(bad)}")
    ep.scene_set_ids = [s for s in dict.fromkeys(body.set_ids) if s != ep.set_id]
    db.add(Event(episode_id=ep.id, kind="episode", message="Sets for scene changes: " + (", ".join(ep.scene_set_ids) or "none")))
    db.commit()
    return {"set_id": ep.set_id, "scene_set_ids": ep.scene_set_ids}


class SceneSetIn(BaseModel):
    set_id: str | None = None


@router.put("/episodes/{eid}/scenes/{scene_id}/set")
def put_scene_set(eid: int, scene_id: int, body: SceneSetIn, db: Session = Depends(get_db)):
    """The owner's choice of set for one storyboard scene (before the storyboard is approved)."""
    ep = _episode(db, eid)
    sc = db.get(StoryboardScene, scene_id)
    if sc is None or sc.episode_id != ep.id:
        raise HTTPException(404, "scene not found")
    if ep.stage != "storyboard_review":
        raise HTTPException(409, "a scene's set can be changed while the storyboard is in review (approve it again after)")
    if body.set_id and body.set_id not in episode_sets(db, ep):
        raise HTTPException(422, "choose one of this episode's sets (add more under Set, \"for scene changes\")")
    sc.set_id = body.set_id if body.set_id and body.set_id != ep.set_id else None
    db.add(Event(episode_id=ep.id, kind="storyboard", message=f"Scene {sc.position}: set {body.set_id or ep.set_id}"))
    db.commit()
    return {"scene_id": sc.id, "set_id": sc.set_id or ep.set_id}
