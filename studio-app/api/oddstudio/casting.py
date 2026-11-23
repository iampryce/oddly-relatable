"""Story-driven casting. There is no mandatory fixed cast: each script may reuse saved characters or introduce new
ones (`new_characters`). New characters are registered for that episode with no art; the owner generates their
pose and expression sheet, approves it, and may promote them to the recurring cast so later stories can reuse them."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import Character, CharacterAsset, Event

BASE_EXPRESSIONS = ["neutral", "happy", "shocked", "angry", "worried", "laughing"]


def writer_characters(db: Session, episode_id: int | None) -> list[Character]:
    """Characters the writer may use: the recurring cast, any character with approved art, and this episode's own."""
    from .bin import hidden_ids
    gone = hidden_ids(db, "character")
    q = db.query(Character).filter(or_(Character.scope == "recurring", Character.art_status == "approved",
                                       Character.episode_id == episode_id))
    return [c for c in q.order_by(Character.id).all() if c.id not in gone]


def register_new_characters(db: Session, episode_id: int, script: dict) -> list[str]:
    """Create the characters a script introduces (idempotent: existing keys are reused, never overwritten)."""
    from .voice_library import assign_new, used_ids
    made = []
    taken = used_ids(db)
    for c in script.get("new_characters", []):
        if db.query(Character).filter_by(key=c["key"]).first():
            continue
        new = Character(key=c["key"], name=c["name"], description=c["description"], visual_description=c["visual_description"],
                         bubble_style=c["bubble_style"], voice_style=c.get("voice_style", ""), scope="episode",
                         episode_id=episode_id, engine_character=f"studio-{c['key']}", art_status="none",
                         default_expression="neutral")
        db.add(new)
        label = assign_new(db, new, taken)
        db.add(Event(episode_id=episode_id, kind="character", message=f"New character introduced by the script: {c['name']}"
                     + (f" (voice picked from the library: {label})" if label else "")))
        made.append(c["key"])
    db.flush()
    return made


def expressions_needed(script: dict) -> dict[str, list[str]]:
    """Expressions each character uses in the script (always including neutral, the reference pose)."""
    need: dict[str, list[str]] = {}
    for s in script.get("scenes", []):
        for ln in s["lines"]:
            lst = need.setdefault(ln["speaker"], ["neutral"])
            e = (ln.get("expression") or "neutral").lower()
            if e not in lst:
                lst.append(e)
    for c in script.get("characters", []):
        need.setdefault(c["key"], ["neutral"])
    return need


# Expressions that read alike: a line asking for one without its own approved pose uses the nearest approved one
# (feat/3d-rig PR 4: a missing expression never blocks an episode; neutral is always the last resort).
EXPRESSION_FAMILIES = (
    ("angry", "furious", "mad", "annoyed", "irritated", "cross", "outraged", "frustrated", "stern"),
    ("happy", "amused", "pleased", "cheerful", "delighted", "glad", "laughing", "grinning", "smiling", "excited"),
    ("smug", "sly", "proud", "satisfied", "superior", "knowing"),
    ("shocked", "surprised", "stunned", "astonished", "startled", "amazed", "aghast"),
    ("worried", "anxious", "nervous", "concerned", "uneasy", "scared", "afraid", "fearful"),
    ("sad", "upset", "gloomy", "hurt", "disappointed", "miserable", "crying"),
    ("deadpan", "neutral", "calm", "serious", "flat", "blank", "bored"),
    ("confused", "puzzled", "bewildered", "doubtful", "skeptical"),
)


def closest_expression(wanted: str, approved) -> str:
    """The approved expression to use for `wanted`: itself, else a loose name match ("very shocked" -> "shocked"), else
    an approved expression from the same family ("furious" -> "angry"), else neutral (else any approved one)."""
    have = [e.lower() for e in approved]
    w = (wanted or "neutral").strip().lower()
    if w in have:
        return w
    for e in have:
        if e and (e in w or w in e):
            return e
    for fam in EXPRESSION_FAMILIES:
        if w in fam or any(f in w for f in fam):
            for f in fam:
                if f in have:
                    return f
    return "neutral" if "neutral" in have else (have[0] if have else "neutral")


def cast_status(db: Session, script: dict) -> list[dict]:
    """Per character in the script: art status, the expressions the script uses, and for each one without its own
    approved pose, the approved one used instead (a note, never a blocker). `awaiting_review` counts only poses still
    waiting for an expression the script uses that has no approved pose yet (leftovers are not "to review")."""
    out = []
    for key, exps in expressions_needed(script).items():
        c = db.query(Character).filter_by(key=key).first()
        if c is None:
            out.append({"key": key, "missing": True})
            continue
        have = set(c.expressions)
        missing = [e for e in exps if e not in have and not c.locked]
        pending = (db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id, CharacterAsset.kind == "pose",
                                                   CharacterAsset.status == "review", CharacterAsset.expression.in_(missing)).count()
                   if missing else 0)
        out.append({"key": key, "id": c.id, "name": c.name, "locked": c.locked, "art_status": c.art_status, "scope": c.scope,
                    "needed": exps, "approved": sorted(have), "missing_expressions": missing,
                    "fallbacks": {e: closest_expression(e, have) for e in missing} if have else {},
                    "awaiting_review": pending, "voice": c.voice})
    return out
