"""Prompt writing (guided flow, step 3). The owner's rule: every generation prompt is written by ChatGPT first, then
shown to the owner, who can edit it before anything is generated from it.

Input: what is being made (a character master, a shot still, a face-only edit, or a movement clip), the shot or beat
notes (typed, and the acting analysis of the chosen shot when there is one), the character's approved description, and
the studio's house style text (Settings > Studio style, by default stick_style.STICK_MAN_MASTER_PROMPT).
Output: the prompt text, saved as a draft. The owner edits it and clicks "Use this prompt" (status approved); nothing
is approved by itself.

Model: Settings > Guided generation (default "gpt-5.5"), called with the official OpenAI Python SDK (Responses API).
Cost: estimated before the call (input tokens from the text, plus at most max output tokens, at the prices in Settings);
the request must carry the most it can cost (confirm_usd, HTTP 409 otherwise). The real token usage and cost are saved
with the draft. One call, never retried. The key comes only from secrets_store.secret("openai_api_key").
"""
from __future__ import annotations

import json
import math
import secrets as pysecrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, Setting
from .secrets_store import secret
from .settings_store import get_section

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

KINDS = ("master", "still", "face_edit", "movement")
CHARS_PER_TOKEN = 3.5
TYPICAL_OUTPUT = 700
NO_CREDIT = "Your OpenAI balance is empty; add credit at platform.openai.com > Billing"

_http_client = None            # tests only: an httpx.Client with a mock transport, handed to the OpenAI SDK


def set_test_http_client(c) -> None:
    global _http_client
    _http_client = c


def key(eid: int) -> str:
    return f"prompts:{eid}"


WHAT = {
    "master": ("a CHARACTER MASTER image: one character, full body, plain white background. It becomes the only "
               "source of this character's look, so describe the look precisely and nothing else."),
    "still": ("a SHOT STILL: the approved set and the approved character masters are given to the image model as "
              "reference images. Say who is where, seated or standing, facing whom, and the expression and pose of "
              "each person. Never redesign a character: refer to them as 'the character in reference image N'."),
    "face_edit": ("a FACE-ONLY EDIT inside a mask on an approved image: only the eyes, eyebrows and mouth change. "
                  "Describe the new expression and nothing outside the face."),
    "movement": ("a MOVEMENT clip from an approved still (image-to-video): describe the motion from the first pose to "
                 "the last, its timing and how big it is. The camera does not move unless the notes say so. The "
                 "characters' design never changes."),
}

SYSTEM = ("You write prompts for image and video generation models for a small studio making 2D stick-figure comedy "
          "cartoons. Write ONE prompt, ready to paste, in plain English, at most 180 words. Keep the house style "
          "rules. Use the notes for acting and staging. Do not add text, captions, speech bubbles, logos or "
          "watermarks. Reply with the prompt only: no title, no explanation, no quotation marks.")


# ------------------------------------------------------------------ prompt text and cost (pure)
def user_message(kind: str, house_style: str, character: str, notes: str, acting: str) -> str:
    parts = [f"WHAT IS BEING MADE: {WHAT[kind]}", f"HOUSE STYLE:\n{house_style.strip()}"]
    if character:
        parts.append(f"THE CHARACTER (approved description):\n{character.strip()}")
    if acting:
        parts.append(f"ACTING NOTES FROM THE REFERENCE (for timing and acting only, never for the look):\n{acting.strip()}")
    if notes.strip():
        parts.append(f"SHOT / BEAT NOTES FROM THE OWNER:\n{notes.strip()}")
    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / CHARS_PER_TOKEN))


def cost_usd(tin: int, tout: int, cfg: dict) -> float:
    return round(tin * float(cfg["prompt_usd_in"]) / 1e6 + tout * float(cfg["prompt_usd_out"]) / 1e6, 6)


def estimate(cfg: dict, system: str, message: str) -> dict:
    tin = estimate_tokens(system) + estimate_tokens(message) + 8
    mt = int(cfg["prompt_max_tokens"])
    return {"model": cfg["prompt_model"], "input_tokens": tin, "max_output_tokens": mt,
            "usd_typical": round(cost_usd(tin, min(mt, TYPICAL_OUTPUT), cfg), 4), "usd_max": round(cost_usd(tin, mt, cfg), 4),
            "usd_per_mtok": {"input": float(cfg["prompt_usd_in"]), "output": float(cfg["prompt_usd_out"])}}


def acting_for_shot(analysis: dict | None, shot: int | None, character: str = "") -> str:
    """The acting analysis' beats for one shot (only that character's when a name is given), as short lines."""
    if not analysis or shot is None:
        return ""
    s = next((x for x in analysis.get("shots") or [] if x.get("shot") == shot), None)
    if not s:
        return ""
    lines = [f"Shot {shot}: {s.get('what_the_reference_shows', '')}".strip()]
    for b in s.get("beats") or []:
        if character and b.get("character") and b["character"].lower() != character.lower():
            continue
        bits = [b.get(k) for k in ("expression", "eyes_and_gaze", "head_and_body", "hands") if b.get(k)]
        word = f" on '{b['on_word']}'" if b.get("on_word") else ""
        lines.append(f"- {b.get('t_start')}-{b.get('t_end')} s {b.get('character', '')}{word}: {'; '.join(bits)}"
                     f" ({b.get('hold_or_move', '')}, {b.get('intensity', '')})")
    style = (analysis.get("talking_style") or {}).get(character) if character else None
    if style:
        lines.append(f"Talking style: {style}")
    return "\n".join(lines)


# ------------------------------------------------------------------ the call
def call_openai(api_key: str, model: str, system: str, message: str, max_tokens: int) -> dict:
    """One paid call (Responses API), never retried. Returns {text, input_tokens, output_tokens}."""
    import openai
    from .config import get_settings
    if _http_client is None and get_settings().env == "test":
        raise HTTPException(500, "no paid calls in tests (set a test HTTP client)")
    kw = {"http_client": _http_client} if _http_client is not None else {}
    client = openai.OpenAI(api_key=api_key, max_retries=0, timeout=180.0, **kw)
    try:
        r = client.responses.create(model=model, instructions=system, input=message, max_output_tokens=max_tokens,
                                    reasoning={"effort": "low"})
    except openai.APIStatusError as e:
        code = getattr(e, "code", None) or ((e.body or {}).get("code") if isinstance(e.body, dict) else None)
        if code == "insufficient_quota" or e.status_code == 402:
            raise HTTPException(402, NO_CREDIT)
        if e.status_code in (401, 403):
            raise HTTPException(502, "OpenAI did not accept the API key saved in Settings > Credentials")
        if e.status_code == 404:
            raise HTTPException(502, f"OpenAI does not offer the model \"{model}\" to this key: check Settings > Guided generation")
        if e.status_code == 429:
            raise HTTPException(502, "OpenAI is busy (rate limit): try again in a minute; not retried")
        raise HTTPException(502, f"OpenAI returned an error (HTTP {e.status_code}); not retried")
    except openai.APIConnectionError as e:
        raise HTTPException(502, f"OpenAI could not be reached ({type(e).__name__}); not retried")
    u = r.usage
    return {"text": (r.output_text or "").strip(), "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0), "status": getattr(r, "status", "")}


# ------------------------------------------------------------------ storage
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def _save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = v
    else:
        db.add(Setting(key=key(eid), value=v))


def config(db: Session) -> dict:
    return get_section(db, "guide")


def typical_estimate(db: Session) -> dict:
    """The cost of one prompt with no notes (for the step list)."""
    cfg = config(db)
    return estimate(cfg, SYSTEM, user_message("still", get_section(db, "stick").get("style_prompt") or "", "", "", ""))


# ------------------------------------------------------------------ routes
class WriteIn(BaseModel):
    kind: Literal["master", "still", "face_edit", "movement"]
    notes: str = Field(default="", max_length=6000)
    character_id: int | None = None
    shot: int | None = Field(default=None, ge=1, le=999)
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def _prepare(db: Session, eid: int, body: WriteIn) -> tuple[str, dict, str]:
    from . import acting_analysis as AA
    _episode(db, eid)
    cfg = config(db)
    c = None
    if body.character_id is not None:
        c = db.get(Character, body.character_id)
        if c is None:
            raise HTTPException(404, "character not found")
    if body.kind == "master" and c is None:
        raise HTTPException(422, "choose the character for a master prompt")
    look = f"{c.name}. {(c.visual_description or '').strip()}" if c else ""
    acting = acting_for_shot(AA.stored(db, eid).get("result"), body.shot, c.name if c else "")
    if not (body.notes.strip() or acting or look):
        raise HTTPException(422, "write the shot or beat notes first (or choose a shot that has an acting analysis)")
    message = user_message(body.kind, get_section(db, "stick").get("style_prompt") or "", look, body.notes, acting)
    return message, cfg, acting


@router.post("/episodes/{eid}/prompts/estimate")
def prompt_estimate(eid: int, body: WriteIn, db: Session = Depends(get_db)):
    """What writing this prompt would cost (no call is made)."""
    message, cfg, acting = _prepare(db, eid, body)
    return {**estimate(cfg, SYSTEM, message), "uses_acting": bool(acting), "key_set": bool(secret("openai_api_key", db))}


@router.post("/episodes/{eid}/prompts/write")
def write(eid: int, body: WriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: one call, only with the most it can cost confirmed. The answer is saved as a draft for the owner to edit."""
    message, cfg, acting = _prepare(db, eid, body)
    est = estimate(cfg, SYSTEM, message)
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"writing this prompt can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    api_key = secret("openai_api_key", db)
    if not api_key:
        raise HTTPException(409, "save the OpenAI API key under Settings > Credentials first")
    out = call_openai(api_key, cfg["prompt_model"], SYSTEM, message, int(cfg["prompt_max_tokens"]))
    if not out["text"]:
        raise HTTPException(502, "OpenAI returned no prompt (the answer was empty or cut off); raise the longest answer in Settings > Guided generation")
    usd = cost_usd(out["input_tokens"], out["output_tokens"], cfg)
    v = stored(db, eid)
    item = {"id": pysecrets.token_hex(5), "kind": body.kind, "character_id": body.character_id, "shot": body.shot,
            "notes": body.notes, "used_acting": bool(acting), "text": out["text"], "original": out["text"],
            "status": "draft", "model": cfg["prompt_model"], "at": time.time(),
            "usage": {"input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"]}, "usd": usd,
            "estimate": {"usd_typical": est["usd_typical"], "usd_max": est["usd_max"]}}
    v["prompts"] = [item] + (v.get("prompts") or [])
    v["usd"] = round((v.get("usd") or 0.0) + usd, 6)
    _save(db, eid, v)
    db.add(Event(episode_id=eid, kind="episode", message=f"Prompt ({body.kind}) written by {cfg['prompt_model']} for {user} (${usd:.4f})"))
    db.commit()
    return item


@router.get("/episodes/{eid}/prompts")
def list_prompts(eid: int, db: Session = Depends(get_db)):
    _episode(db, eid)
    v = stored(db, eid)
    return {"prompts": v.get("prompts") or [], "usd": round(v.get("usd") or 0.0, 4), "kinds": list(KINDS),
            "model": config(db)["prompt_model"], "key_set": bool(secret("openai_api_key", db))}


class EditIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    approve: bool = False


@router.put("/episodes/{eid}/prompts/{pid}")
def edit(eid: int, pid: str, body: EditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's edit (free). approve=true is the owner's "Use this prompt" click; any later edit makes it a draft
    again, so an approved prompt is always exactly what the owner approved."""
    _episode(db, eid)
    v = stored(db, eid)
    item = next((p for p in v.get("prompts") or [] if p["id"] == pid), None)
    if item is None:
        raise HTTPException(404, "prompt not found")
    changed = body.text != item["text"]
    item["text"] = body.text
    item["edited"] = item.get("edited") or (body.text != item.get("original"))
    if body.approve:
        item["status"], item["approved_by"] = "approved", user
    elif changed:
        item["status"] = "draft"
    _save(db, eid, v)
    if body.approve:
        db.add(Event(episode_id=eid, kind="approval", message=f"Prompt ({item['kind']}) approved by {user}"))
    db.commit()
    return item


@router.delete("/episodes/{eid}/prompts/{pid}")
def remove(eid: int, pid: str, db: Session = Depends(get_db)):
    _episode(db, eid)
    v = stored(db, eid)
    before = len(v.get("prompts") or [])
    v["prompts"] = [p for p in v.get("prompts") or [] if p["id"] != pid]
    if len(v["prompts"]) == before:
        raise HTTPException(404, "prompt not found")
    _save(db, eid, v)
    db.commit()
    return {"deleted": pid}
