"""Characters on the episode page (2026-11-27, owner request): right after "Lines and speakers", each speaker label
becomes a character entry, and the Cast-from-video step (cast_from_video.py: descriptions in words, style previews,
candidates, approval, "save to my cast library" or "this episode only") makes its master. No logic of the Cast step is
repeated here: this module only turns the speaker LABELS into characters.

For each label the lines carry that is not a character yet, the proposal is (the owner can change each one):
  library   a character saved in the owner's cast library with the same name: used as it is (free, its locked master;
            cast_from_video.use_saved, so its style rule applies)
  existing  a character of the studio with the same name or key (speaker_suggest.map_label)
  new       a new character of this episode only, named after the label (no art yet: its master comes from the Cast step)
Applying it (free) writes the character keys onto the lines (audio_first.apply_cast_mapping, the same as the old cast
card) and adds the characters to the Cast step's list. The old "Cast and poses" section then waits only for approved
art, which an approved master gives (cast_from_video.approve sets art_status), so it clears when every speaking
character has an approved master.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _labels(db: Session, ep: Episode) -> list[dict]:
    """The speaker labels that are not a character yet, with how many lines each says."""
    from .audio_first import speakers_of
    lines = (ep.audio_transcript or {}).get("lines") or []
    keys = {k for (k,) in db.query(Character.key)}
    return [{"label": s, "lines": sum(1 for ln in lines if ln.get("speaker") == s)} for s in speakers_of(lines) if s not in keys]


def proposals(db: Session, ep: Episode) -> list[dict]:
    from . import cast_from_video as CV
    from .audio_first import state
    from .speaker_suggest import map_label
    entries = list((CV.library(db).get("entries") or {}).values())
    chars = [{"key": c["key"], "name": c["name"]} for c in state(db, ep)["characters"]]
    out = []
    for x in _labels(db, ep):
        name = CV.match_name(x["label"], [e["name"] for e in entries])
        e = next((e for e in entries if e["name"] == name), None) if name else None
        if e is not None:
            p = {"kind": "library", "library_id": e["id"], "name": e["name"]}
        elif (m := map_label(x["label"], chars)) is not None:
            p = {"kind": "existing", "character_key": m["key"], "name": m["name"]}
        else:
            p = {"kind": "new", "name": x["label"]}
        out.append({**x, "proposal": p})
    return out


def view(db: Session, ep: Episode) -> dict:
    from . import cast_from_video as CV
    from .audio_first import state
    st = state(db, ep)
    return {"speakers": proposals(db, ep), "unlabelled_lines": st["unlabelled_lines"],
            "characters": [{"key": c["key"], "name": c["name"]} for c in st["characters"]],
            "library": [{"id": e["id"], "name": e["name"], "style_label": e["style_label"], "master_url": e["master_url"]}
                        for e in CV.library_out(db)],
            "can_apply": "audio_cast" in st["allowed_actions"]}


@router.get("/episodes/{eid}/speaker-cast")
def get_speaker_cast(eid: int, db: Session = Depends(get_db)):
    from .audio_first import audio_episode
    return view(db, audio_episode(db, eid))


class ChoiceIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    kind: Literal["library", "existing", "new"]
    library_id: str | None = Field(default=None, max_length=20)
    character_key: str | None = Field(default=None, max_length=41)
    name: str | None = Field(default=None, max_length=80)          # a new character's name (the label by default)


class ApplyIn(BaseModel):
    choices: list[ChoiceIn] = Field(min_length=1, max_length=12)
    allow_mixed: bool = False


def _new_character(db: Session, ep: Episode, name: str) -> Character:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "character"
    if not base[0].isalpha():
        base = f"c-{base}"[:30]
    k, i = f"{base}-ep{ep.id}", 2
    while db.query(Character).filter_by(key=k).first() is not None:
        k, i = f"{base}-ep{ep.id}-{i}", i + 1
    c = Character(key=k, name=name, scope="episode", episode_id=ep.id, engine_character=f"studio-{k}", art_status="none",
                  default_expression="neutral", voice="")
    db.add(c)
    db.flush()
    return c


@router.post("/episodes/{eid}/speaker-cast")
def apply(eid: int, body: ApplyIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's choice per speaker label (free): a saved character from the cast library, an existing character, or
    a new character of this episode. The lines then carry the character keys, and the characters join the Cast step."""
    from . import cast_from_video as CV
    from .audio_first import apply_cast_mapping, audio_episode, gate
    ep = audio_episode(db, eid)
    gate(ep, "audio_cast")
    labels = {x["label"] for x in _labels(db, ep)}
    mapping: dict[str, str] = {}
    added: list[int] = []
    for ch in body.choices:
        if ch.label not in labels:
            raise HTTPException(422, f"no line is labelled {ch.label!r} (or it is a character already)")
        if ch.kind == "library":
            e = (CV.library(db).get("entries") or {}).get(ch.library_id or "")
            if e is None:
                raise HTTPException(404, f"{ch.label}: not in the cast library")
            CV.use_saved(ep.id, e["id"], CV.UseIn(allow_mixed=body.allow_mixed), db, user)   # free; style rule (409)
            c = db.get(Character, e["character_id"])
        elif ch.kind == "existing":
            c = db.query(Character).filter_by(key=ch.character_key or "").first()
            if c is None:
                raise HTTPException(422, f"{ch.label}: there is no character {ch.character_key!r}")
        else:
            c = _new_character(db, ep, (ch.name or ch.label).strip() or ch.label)
        mapping[ch.label] = c.key
        added.append(c.id)
    # the Cast step's list: every mapped character (the library ones were added by use_saved)
    v = CV.stored(db, ep.id)
    extra = [int(i) for i in v.get("extra") or []]
    v["extra"] = extra + [i for i in dict.fromkeys(added) if i not in extra]
    # a description from the video with the same name is linked to its character (so its words become the look)
    by_name = {db.get(Character, i).name.lower(): i for i in added}
    for d in v.get("characters") or []:
        if not d.get("character_id") and d.get("name", "").lower() in by_name:
            d["character_id"] = by_name[d["name"].lower()]
    CV.save(db, ep.id, v)
    apply_cast_mapping(ep, mapping)
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Characters from the speakers set by {user}: "
                 + ", ".join(f"{k} → {v}" for k, v in mapping.items())))
    db.commit()
    return view(db, ep)
