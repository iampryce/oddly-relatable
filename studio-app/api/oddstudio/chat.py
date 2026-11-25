"""The studio chat: the owner asks questions about the studio and an LLM answers, with read-only context (episodes,
characters, recent jobs, non-secret settings). It never changes anything.

Provider (Settings > chat.provider, default auto): Anthropic (Claude Opus 5.5, Anthropic Python SDK) when an
`anthropic_api_key` is saved, else OpenAI when an `openai_api_key` is saved. Keys come only from the credential store and
are never logged, returned or put in the context.

Cost: every message is estimated before it is sent (input tokens estimated from the text, plus at most max_tokens of
answer, at the model's published price per million tokens) and the request carries the estimate the owner saw
(confirm_usd); after the answer the actual usage and cost are recorded. A message is one paid call, never retried
(the SDK's own retries are turned off).

History: one conversation per session id, kept in the `settings` table under "_chat:<id>" (no migration needed).
"""
from __future__ import annotations

import json
import math
import re
import secrets as pysecrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, CharacterAsset, Episode, Job, Setting
from .secrets_store import secret
from .settings_store import get_section

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

# USD per million tokens (input, output). Anthropic: published price of Claude Opus 5.5 (2026-11).
MODELS = {
    "anthropic": {"model": "claude-opus-5-5", "label": "Claude Opus 5.5 (Anthropic)", "usd_in": 4.0, "usd_out": 20.0},
    "openai": {"model": "gpt-4.1-mini", "label": "GPT-4.1 mini (OpenAI)", "usd_in": 0.40, "usd_out": 1.60},
}
PREFIX = "_chat:"
SID = re.compile(r"^[a-f0-9]{12}$")
HISTORY_TURNS = 20          # the most recent messages sent with each question
CHARS_PER_TOKEN = 3.5       # a cautious estimate (English text runs about 4 characters a token)

_test_call = None           # tests only: fn(provider, model, system, messages, max_tokens) -> {text, input_tokens, output_tokens}


def set_test_call(fn) -> None:
    """Tests only: replace the paid LLM call."""
    global _test_call
    _test_call = fn


# ------------------------------------------------------------------ cost (pure)
def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / CHARS_PER_TOKEN))


def cost_usd(provider: str, input_tokens: int, output_tokens: int) -> float:
    m = MODELS[provider]
    return round(input_tokens * m["usd_in"] / 1e6 + output_tokens * m["usd_out"] / 1e6, 6)


def estimate(provider: str, system: str, messages: list[dict], max_tokens: int) -> dict:
    """Input tokens estimated from the text; the answer at most max_tokens (the upper bound the owner confirms)."""
    tin = estimate_tokens(system) + sum(estimate_tokens(m["content"]) + 4 for m in messages)
    typical = min(max_tokens, 600)
    return {"provider": provider, "model": MODELS[provider]["model"], "label": MODELS[provider]["label"],
            "input_tokens": tin, "max_output_tokens": max_tokens,
            "usd_typical": round(cost_usd(provider, tin, typical), 4), "usd_max": round(cost_usd(provider, tin, max_tokens), 4),
            "usd_per_mtok": {"input": MODELS[provider]["usd_in"], "output": MODELS[provider]["usd_out"]}}


# ------------------------------------------------------------------ provider choice and context
def pick_provider(db: Session) -> str:
    want = get_section(db, "chat").get("provider", "auto")
    has = {"anthropic": bool(secret("anthropic_api_key", db)), "openai": bool(secret("openai_api_key", db))}
    if want in has:
        if not has[want]:
            raise HTTPException(409, f"save the {want.title()} API key under Settings > Credentials first")
        return want
    for p in ("anthropic", "openai"):
        if has[p]:
            return p
    raise HTTPException(409, "the chat needs an Anthropic or OpenAI API key (Settings > Credentials)")


SAFE_SECTIONS = ("text", "image", "voice", "motion", "production", "stick", "chat")


def studio_context(db: Session) -> str:
    """A short read-only summary of the studio for the model. Only non-secret values: no credentials, no keys."""
    eps = db.query(Episode).order_by(Episode.updated_at.desc()).limit(15).all()
    chars = db.query(Character).order_by(Character.id).limit(40).all()
    masters = {a.character_id for a in db.query(CharacterAsset).filter_by(kind="master", status="approved")}
    jobs = db.query(Job).order_by(Job.id.desc()).limit(12).all()
    settings = {}
    for k in SAFE_SECTIONS:
        v = dict(get_section(db, k))
        if k == "stick":
            v["style_prompt"] = (v.get("style_prompt") or "")[:300] + "..."
        if k == "voice":
            v.pop("library", None)
        settings[k] = v
    lines = ["EPISODES (most recent first):"]
    lines += [f"- #{e.id} \"{e.title}\": stage {e.stage}, {e.format}, revision {e.revision}" for e in eps] or ["- none"]
    lines.append("CHARACTERS:")
    lines += [f"- {c.key} ({c.name}): art {c.art_status}, master {'approved' if c.id in masters else 'none'}, "
              f"{c.scope}; look: {(c.visual_description or '')[:120]}" for c in chars] or ["- none"]
    lines.append("RECENT JOBS:")
    lines += [f"- job {j.id} {j.kind} {j.status}" + (f" (episode {j.episode_id})" if j.episode_id else "")
              + (f": {j.error[:120]}" if j.error else "") for j in jobs] or ["- none"]
    lines.append("SETTINGS (non-secret): " + json.dumps(settings, default=str)[:3000])
    return "\n".join(lines)


SYSTEM = ("You are the assistant of Oddly Relatable, a small studio making short comedy cartoons with stick-man "
          "characters. Answer the owner's questions briefly and concretely, using the studio summary below when it is "
          "relevant. You cannot change anything in the studio: when something needs doing, say which page or button "
          "does it. Paid actions always show their cost and need the owner's click. If the summary does not contain "
          "the answer, say so.")


def system_prompt(db: Session) -> str:
    return f"{SYSTEM}\n\nSTUDIO SUMMARY (read-only, {time.strftime('%Y-%m-%d')}):\n{studio_context(db)}"


# ------------------------------------------------------------------ sessions
def _row(db: Session, sid: str) -> Setting:
    if not SID.match(sid or ""):
        raise HTTPException(404, "chat not found")
    row = db.get(Setting, PREFIX + sid)
    if row is None:
        raise HTTPException(404, "chat not found")
    return row


def _history(v: dict) -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in v.get("messages") or []][-HISTORY_TURNS:]


@router.get("/chat/sessions")
def list_sessions(db: Session = Depends(get_db)):
    rows = db.query(Setting).filter(Setting.key.startswith(PREFIX)).all()
    out = [{"id": r.key[len(PREFIX):], "title": r.value.get("title") or "New chat", "created": r.value.get("created"),
            "messages": len(r.value.get("messages") or []), "usd": round(r.value.get("usd") or 0.0, 4)} for r in rows]
    return sorted(out, key=lambda x: -(x["created"] or 0))


@router.post("/chat/sessions", status_code=201)
def new_session(db: Session = Depends(get_db)):
    sid = pysecrets.token_hex(6)
    db.add(Setting(key=PREFIX + sid, value={"created": time.time(), "title": "", "messages": [], "usd": 0.0}))
    db.commit()
    return {"id": sid}


@router.get("/chat/sessions/{sid}")
def get_session(sid: str, db: Session = Depends(get_db)):
    v = dict(_row(db, sid).value)
    return {"id": sid, **v}


@router.delete("/chat/sessions/{sid}")
def delete_session(sid: str, db: Session = Depends(get_db)):
    db.delete(_row(db, sid))
    db.commit()
    return {"deleted": sid}


class AskIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=8000)
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


def _prepare(db: Session, body: AskIn):
    row = _row(db, body.session_id)
    provider = pick_provider(db)
    mt = int(get_section(db, "chat").get("max_tokens") or 4000)
    system = system_prompt(db)
    messages = _history(row.value) + [{"role": "user", "content": body.text}]
    return row, provider, mt, system, messages


@router.post("/chat/estimate")
def chat_estimate(body: AskIn, db: Session = Depends(get_db)):
    """What sending this message would cost (no call is made)."""
    _row_, provider, mt, system, messages = _prepare(db, body)
    return estimate(provider, system, messages, mt)


def call_llm(provider: str, model: str, system: str, messages: list[dict], max_tokens: int, db: Session) -> dict:
    """One paid call, never retried. Returns {text, input_tokens, output_tokens}."""
    if _test_call is not None:
        return _test_call(provider, model, system, messages, max_tokens)
    from .config import get_settings
    if get_settings().env == "test":
        raise HTTPException(500, "no paid calls in tests (set a test stub)")
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=secret("anthropic_api_key", db), max_retries=0, timeout=180.0)
        try:
            r = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages,
                                       output_config={"effort": "low"})
        except anthropic.APIStatusError as e:
            raise HTTPException(502, f"Anthropic: HTTP {e.status_code}; not retried")
        except anthropic.APIConnectionError as e:
            raise HTTPException(502, f"Anthropic: {type(e).__name__}; not retried")
        text = "".join(b.text for b in r.content if b.type == "text")
        if r.stop_reason == "refusal":
            text = text or "(The model declined to answer this message.)"
        elif r.stop_reason == "max_tokens":
            text += "\n\n(The answer was cut off at the chat's length limit, Settings > Chat.)"
        return {"text": text, "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
    import httpx
    key = secret("openai_api_key", db)
    try:
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=180,
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "max_tokens": max_tokens,
                             "messages": [{"role": "system", "content": system}, *messages]})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OpenAI: {type(e).__name__}; not retried")
    if r.status_code >= 400:
        raise HTTPException(502, f"OpenAI: HTTP {r.status_code}; not retried")
    d = r.json()
    u = d.get("usage") or {}
    return {"text": d["choices"][0]["message"].get("content") or "", "input_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("completion_tokens", 0)}


@router.post("/chat/send")
def chat_send(body: AskIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Send one message (paid). It must carry the most this message can cost, as estimated and shown to the owner."""
    row, provider, mt, system, messages = _prepare(db, body)
    est = estimate(provider, system, messages, mt)
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"this message can cost up to ${est['usd_max']:.4f}: confirm that amount to send it")
    model = MODELS[provider]["model"]
    out = call_llm(provider, model, system, messages, mt, db)
    usd = cost_usd(provider, int(out["input_tokens"]), int(out["output_tokens"]))
    v = json.loads(json.dumps(row.value))
    now = time.time()
    v["messages"] = (v.get("messages") or []) + [
        {"role": "user", "content": body.text, "at": now},
        {"role": "assistant", "content": out["text"], "at": time.time(), "provider": provider, "model": model,
         "usage": {"input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"]}, "usd": usd,
         "estimate": {"usd_typical": est["usd_typical"], "usd_max": est["usd_max"]}}]
    v["title"] = v.get("title") or body.text[:60]
    v["usd"] = round((v.get("usd") or 0.0) + usd, 6)
    row.value = v
    db.commit()
    return {"reply": v["messages"][-1], "session_usd": v["usd"], "estimate": est}
