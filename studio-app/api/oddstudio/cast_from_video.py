"""Cast from video (guided flow, step 4 "Cast"; owner request 2026-11-26): after the reference video is uploaded, the
studio describes each character from the video IN WORDS, the owner picks one of five styles for the episode (seeing a
preview of one character in each style first, if they like), and character masters are drawn from those words in that
style. The owner approves one master per character; it is then locked and used by every later step.

The owner's standing rules, and how this module keeps them:
- The reference video's PICTURES never go to an image or video generator. Only Gemini (an analyser) watches the video,
  and it returns words only (JSON). The image model is given text (the description + the style block) and the studio's
  OWN style reference images (Settings > Cast styles / Studio style). safe_reference_files() refuses anything stored
  under private/ (where the reference video and its key frames live), so a video frame cannot be passed even by
  mistake. Describing in words also keeps us from copying a real actor's likeness: the request asks for general traits
  only (no face, no identifying marks).
- Characters never change: an approved master is locked. New candidates for a character that has one, and approving
  one of them, need the owner's explicit "new version" (new_version=true, HTTP 409 otherwise). Editing the written
  description afterwards never touches the approved master.
- Every paid call shows its cost first and the request must carry it (confirm_usd, HTTP 409 otherwise): the Gemini
  description (its "at most" price), each GPT master prompt (its "at most" price), each preview and each candidate
  ($0.04 per image with Nano Banana 2.1 on WaveSpeed). A paid call is never retried. Nothing is approved or chosen by
  itself: previews never choose the style, candidates wait for the owner's click.
- Keys come only from secrets_store.secret() and are never logged or returned.

Gemini tier rules: the same as the acting analysis (Settings > Guided generation): the paid model first; the free-tier
models only when the owner ticks "use the free tier" for this run (Google may use free-tier uploads to improve its
models), and only after the paid model answers 429 or 503.

Storage (settings table): `cast:<episode id>` the descriptions, the master prompts, the style previews and the
characters added from the library; `cast_meta` the style (and episode, prompt) each preview or candidate was drawn in;
`cast_library` the owner's saved characters (reusable in later episodes at no cost); `owner_heads:<episode id>` the
head positions the owner clicked on pictures of an episode whose style is not the stick man (automatic head finding
looks for white round stick heads, so it only works for that style).
"""
from __future__ import annotations

import json
import math
import re
import secrets as pysecrets
import tempfile
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .cast_styles import DEFAULT_STYLES, STYLE_IDS
from .db import get_db
from .models import Asset, Character, CharacterAsset, Episode, Event, Job, Setting
from .providers import ProviderError
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

JOB_DESCRIBE, JOB_IMAGES = "cast_describe", "cast_images"
PREVIEW_KIND = "cast-preview"
MAX_CHARACTERS = 8
MAX_REFS = 4
CHARS_PER_TOKEN = 3.5
FPS = 1                        # the description needs the people, not the timing: one frame a second is enough
HEAD_NOTE = ("Automatic head finding works for the stick-man style; for other styles click each head once.")


def key(eid: int) -> str:
    return f"cast:{eid}"


# ================================================================== settings: the five style presets
def styles(db: Session) -> dict[str, dict]:
    """The presets, each merged over its default (so a field added later is never missing)."""
    saved = get_section(db, "cast").get("styles") or {}
    out = {}
    for sid in STYLE_IDS:
        out[sid] = {**DEFAULT_STYLES[sid], **(saved.get(sid) or {})}
    return out


def style_block(db: Session, sid: str) -> tuple[str, list[dict]]:
    """(style text, style reference refs) of one preset. The stick man falls back to Settings > Studio style."""
    p = styles(db)[sid]
    text, refs = (p.get("style_prompt") or "").strip(), list(p.get("references") or [])
    if sid == "stick":
        st = get_section(db, "stick")
        text = text or (st.get("style_prompt") or "").strip()
        if not refs and st.get("style_reference"):
            refs = [st["style_reference"]]
    return text, refs


def check_cast_settings(db: Session, v: dict) -> None:
    """Settings > Cast styles: refused values never reach a provider."""
    from .stick_pipeline import reference_image
    if "styles" in v:
        s = v["styles"]
        if not isinstance(s, dict) or set(s) - set(STYLE_IDS):
            raise ValueError(f"cast.styles must only hold the presets {', '.join(STYLE_IDS)}")
        for sid, p in s.items():
            if not isinstance(p, dict) or set(p) - {"label", "style_prompt", "references", "note"}:
                raise ValueError(f"cast.styles.{sid} may only hold label, style_prompt, references and note")
            text = p.get("style_prompt", DEFAULT_STYLES[sid]["style_prompt"])
            if not isinstance(text, str) or len(text) > 8000 or (sid != "stick" and len(text.strip()) < 20):
                raise ValueError(f"cast.styles.{sid}.style_prompt must be 20 to 8000 characters"
                                 + (" (the stick man may be empty: it then uses Settings > Studio style)" if sid == "stick" else ""))
            label = p.get("label", DEFAULT_STYLES[sid]["label"])
            if not (isinstance(label, str) and 1 <= len(label.strip()) <= 40):
                raise ValueError(f"cast.styles.{sid}.label must be 1 to 40 characters")
            refs = p.get("references", [])
            if not isinstance(refs, list) or len(refs) > MAX_REFS:
                raise ValueError(f"cast.styles.{sid}.references must be a list of up to {MAX_REFS} images")
            for r in refs:
                if reference_image(db, r) is None:
                    raise ValueError(f"cast.styles.{sid}.references: each must be an uploaded style example or approved character art")
    n = v.get("candidates", 2)
    if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 4):
        raise ValueError("cast.candidates must be 1 to 4")
    mt = v.get("describe_max_tokens", 8000)
    if not (isinstance(mt, int) and not isinstance(mt, bool) and 1000 <= mt <= 30000):
        raise ValueError("cast.describe_max_tokens must be a whole number between 1000 and 30000")


# ================================================================== descriptions (pure)
TEXT_FIELDS = ("role", "age", "build", "accessory", "personality")


def _clip(x, n: int = 200) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()[:n]


def _hair(h) -> dict:
    if isinstance(h, dict):
        return {"style": _clip(h.get("style"), 120), "colour": _clip(h.get("colour") or h.get("color"), 60)}
    return {"style": _clip(h, 120), "colour": ""}


def _clothing(c) -> list[dict]:
    items = c if isinstance(c, list) else [c] if c else []
    out = []
    for it in items[:8]:
        if isinstance(it, dict):
            g = {"garment": _clip(it.get("garment") or it.get("item"), 80), "colour": _clip(it.get("colour") or it.get("color"), 60)}
        else:
            g = {"garment": _clip(it, 80), "colour": ""}
        if g["garment"]:
            out.append(g)
    return out


def _list(x, n: int = 6) -> list[str]:
    items = x if isinstance(x, list) else [x] if x else []
    return [s for s in (_clip(i, 160) for i in items[:n]) if s]


def match_name(name: str, cast: list[str]) -> str | None:
    """The script's cast name for a name Gemini gave: exact (any case), else the same first word, else None."""
    n = name.strip().lower()
    for c in cast:
        if c.lower() == n:
            return c
    first = n.split(" ")[0] if n else ""
    hits = [c for c in cast if first and c.lower().split(" ")[0] == first]
    return hits[0] if len(hits) == 1 else None


def normalise_descriptions(raw, cast: list[str], traits: dict | None = None) -> list[dict]:
    """Gemini's answer as a clean list (at most 8, one per name). Seen in practice: {"characters": [...]}, a bare
    list, or {"characters": {"<name>": {...}}}. Names are mapped to the script's cast where possible; the personality
    comes from the acting analysis' traits for that character when there are some."""
    if isinstance(raw, dict):
        items = raw.get("characters", raw.get("cast", []))
        if isinstance(items, dict):
            items = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in items.items()]
    else:
        items = raw
    traits = traits or {}
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        name = _clip(it.get("name"), 80)
        if not name:
            continue
        mapped = match_name(name, cast)
        name = mapped or name
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        d = {"id": pysecrets.token_hex(4), "name": name, "in_script": mapped is not None,
             "hair": _hair(it.get("hair")), "clothing": _clothing(it.get("clothing")),
             "must_never": _list(it.get("must_never"))}
        for k in TEXT_FIELDS:
            d[k] = _clip(it.get(k), 300)
        t = traits.get(name) or {}
        if isinstance(t, dict) and t.get("traits"):
            d["personality"] = _clip(t["traits"], 300)
            d["personality_from"] = "acting analysis"
        out.append(d)
        if len(out) >= MAX_CHARACTERS:
            break
    return out


def description_text(d: dict) -> str:
    """The description as plain lines for a prompt (only the fields that are filled in)."""
    lines = [f"Character: {d.get('name') or 'unnamed'}" + (f" ({d['role']})" if d.get("role") else "") + "."]
    if d.get("age"):
        lines.append(f"Age: {d['age']}.")
    if d.get("build"):
        lines.append(f"Build: {d['build']}.")
    h = d.get("hair") or {}
    if h.get("style") or h.get("colour"):
        lines.append("Hair: " + ", ".join(x for x in (h.get("style"), h.get("colour")) if x) + ".")
    cl = [" ".join(x for x in (g.get("colour"), g.get("garment")) if x) for g in d.get("clothing") or []]
    if cl:
        lines.append("Clothing: " + ", ".join(cl) + ".")
    if d.get("accessory"):
        lines.append(f"Signature accessory (this is what tells them apart): {d['accessory']}.")
    if d.get("personality"):
        lines.append(f"Personality (show it only in the expression and stance): {d['personality']}.")
    if d.get("must_never"):
        lines.append("Must never: " + "; ".join(d["must_never"]) + ".")
    return "\n".join(lines)


def template_prompt(style_text: str, d: dict, has_refs: bool) -> str:
    """The master prompt without GPT: the style block unchanged, then the character's own lines."""
    tail = ("Use the reference image(s) only for the drawing style (line weight, shapes, colouring, finish); do not copy "
            "their characters, accessories or poses. " if has_refs else "")
    return (f"{style_text.strip()}\n\n{description_text(d)}\n\n{tail}Neutral standing master: one character only, full "
            "body, plain background.")


DESCRIBE_PROMPT = """You are a character designer. Watch this reference video. We are making an ORIGINAL animated cartoon
of the same story, and we need a WRITTEN description of each person's part and outward look, to design new cartoon
characters from. Never describe the real person's face or anything that would identify them (no facial features, skin
marks, tattoos, real names): describe only general traits a cartoon character can use.

Our cast names: {cast}.
Map each person to one of these names from what is said and done; call anyone else who matters "Person 1", "Person 2".

Return JSON only:
{{"characters": [{{"name": "<cast name>", "role": "their part in the story, a few words",
  "age": "approximate age, e.g. 'about 60'", "build": "e.g. slim, average, stocky, tall, short",
  "hair": {{"style": "...", "colour": "..."}},
  "clothing": [{{"garment": "...", "colour": "..."}}],
  "accessory": "ONE signature accessory that tells them apart (e.g. round glasses, a cap, a bow tie, pearls)",
  "personality": "3 to 6 words", "must_never": ["what the character must never have or do, e.g. 'no beard'"]}}]}}
Rules: at most {n} characters, the main people first; exactly one accessory each, and no two characters share the same
accessory; plain, short words."""


def describe_prompt(cast: list[str]) -> str:
    return DESCRIBE_PROMPT.format(cast=", ".join(cast) or "(not named yet)", n=MAX_CHARACTERS)


def describe_body(file_uri: str, mime: str, prompt: str, max_tokens: int) -> dict:
    """The one Gemini request: the uploaded video at one frame a second, and the prompt. Words come back."""
    return {"contents": [{"parts": [{"file_data": {"mime_type": mime, "file_uri": file_uri}, "video_metadata": {"fps": FPS}},
                                    {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3, "maxOutputTokens": max_tokens,
                                 "thinkingConfig": {"thinkingLevel": "low"}}}


def describe_estimate(seconds: float, cast: list[str], gcfg: dict, max_tokens: int) -> dict:
    """Input: the video seconds (the acting analysis' tokens per second, a safe upper figure at one frame a second)
    plus the prompt; output: at most max_tokens. usd_max is what the owner confirms."""
    from .acting_analysis import TOKENS_PER_SECOND
    tin = int(seconds * TOKENS_PER_SECOND) + math.ceil(len(describe_prompt(cast)) / CHARS_PER_TOKEN)
    p_in, p_out = float(gcfg["acting_usd_in"]), float(gcfg["acting_usd_out"])
    usd = lambda o: round(tin * p_in / 1e6 + o * p_out / 1e6, 4)
    typ = min(max_tokens, 2500)
    return {"model": gcfg["acting_model"], "video_seconds": round(seconds, 1), "input_tokens": tin,
            "max_output_tokens": max_tokens, "usd_typical": usd(typ), "usd_max": usd(max_tokens),
            "label": f"1 request, {seconds:.0f} s of video: about ${usd(typ):.2f}, at most ${usd(max_tokens):.2f}"}


# ================================================================== episode state
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    _put(db, key(eid), v)


def _put(db: Session, k: str, v: dict) -> None:
    row = db.get(Setting, k)
    if row:
        row.value = json.loads(json.dumps(v))
    else:
        db.add(Setting(key=k, value=json.loads(json.dumps(v))))


def _get(db: Session, k: str) -> dict:
    row = db.get(Setting, k)
    return json.loads(json.dumps(row.value)) if row else {}


def meta(db: Session) -> dict:
    """{asset id: {style, episode_id, character_id, kind, prompt}} for every preview and candidate drawn here."""
    return _get(db, "cast_meta")


def master_style(db: Session, a: CharacterAsset | None) -> str | None:
    """The style a master was drawn in. Masters made before cast styles existed are the house stick man."""
    if a is None:
        return None
    return (meta(db).get(str(a.id)) or {}).get("style") or "stick"


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


def episode_style(ep: Episode | None) -> str:
    """The style later steps read: the episode's choice, or the house stick man when none was chosen."""
    return (getattr(ep, "style", None) or "stick") if ep is not None else "stick"


def auto_heads(db: Session, eid: int | None) -> bool:
    """Automatic head finding (white round stick heads) only works for the stick-man style."""
    return episode_style(db.get(Episode, eid) if eid else None) == "stick"


def owner_heads(db: Session, eid: int, asset_id) -> list[dict] | None:
    """The heads the owner clicked on one picture of this episode, or None when they have not clicked yet."""
    h = _get(db, f"owner_heads:{eid}").get(str(asset_id))
    return list(h) if isinstance(h, list) else None


def head_finding(db: Session, eid: int) -> dict:
    auto = auto_heads(db, eid)
    return {"auto": auto, "style": episode_style(db.get(Episode, eid)), "note": "" if auto else HEAD_NOTE}


def extra_ids(db: Session, eid: int) -> list[int]:
    """Characters this step added to the episode's cast (from the library, or linked to a description)."""
    v = stored(db, eid)
    ids = [int(i) for i in v.get("extra") or []]
    ids += [int(d["character_id"]) for d in v.get("characters") or [] if d.get("character_id")]
    out = []
    for i in ids:
        if i not in out:
            out.append(i)
    return out


def _desc_for(v: dict, cid: int) -> dict | None:
    return next((d for d in v.get("characters") or [] if d.get("character_id") == cid), None)


def _cast(db: Session, ep: Episode) -> list[Character]:
    from . import guided
    return guided.cast(db, ep)


def _char_in_cast(db: Session, ep: Episode, cid: int) -> Character:
    c = next((c for c in _cast(db, ep) if c.id == cid), None)
    if c is None:
        raise HTTPException(404, "this character is not in the episode's cast")
    return c


def _main_speaker(db: Session, ep: Episode, v: dict) -> int | None:
    from .reactions import main_speaker
    k = main_speaker(ep)
    c = db.query(Character).filter_by(key=k).first() if k else None
    linked = [d["character_id"] for d in v.get("characters") or [] if d.get("character_id")]
    if c is not None and c.id in linked:
        return c.id
    return linked[0] if linked else None


# ================================================================== images: references, requests, costs
def safe_reference_files(db: Session, refs: list[dict], folder: Path) -> list[Path]:
    """The style reference images as local files. Only the studio's own images: an uploaded style example or approved
    character art (stick_pipeline.reference_image); anything under private/ (the reference video and its key frames)
    is refused, so a frame of the reference video can never reach the image model."""
    from .stick_pipeline import reference_image
    out = []
    for r in refs[:MAX_REFS]:
        a = reference_image(db, r)
        if a is None:
            raise ValueError("a style reference image is no longer available: choose it again in Settings > Cast styles")
        if str(a.storage_key).startswith("private/"):
            raise ValueError("a private file (the reference video or its frames) can never be sent to an image model")
        out.append(storage().get_to_file(a.storage_key, folder / f"style-{r['kind']}-{a.id}{Path(a.storage_key).suffix or '.png'}"))
    return out


def image_request(prov: dict, prompt: str, ref_urls: list[str]) -> tuple[str, dict]:
    """(model endpoint, body): the edit model with the style references, or the same model's text-to-image endpoint
    when the style has no reference image yet. The body is text and our own reference URLs only."""
    from .stick_pipeline import edit_body
    if ref_urls:
        return prov["model"], edit_body(prompt, ref_urls, "3:4")
    return prov.get("t2i_model") or prov["model"], {"prompt": prompt, "aspect_ratio": "3:4", "resolution": "1k",
                                                     "output_format": "png"}


def _provider(db: Session) -> dict:
    from .stick_pipeline import image_provider
    return image_provider(db)


def _each(db: Session) -> float:
    from .stick_pipeline import IMAGE_PROVIDERS
    p = IMAGE_PROVIDERS.get(get_section(db, "stick").get("image_provider"))
    return p["usd_per_image"] if p else 0.0


def _confirm(usd: float, confirm: float | None, what: str) -> None:
    """The owner's click carries the price they saw; a different (or missing) price is refused, nothing starts."""
    if confirm is None or abs(float(confirm) - usd) > 0.0005:
        raise HTTPException(409, f"{what} costs ${usd:.2f}: confirm that amount to start (nothing was started)")


def _busy(db: Session, cid: int) -> bool:
    from .stick_pipeline import JOBS
    return db.query(Job).filter(Job.kind.in_((JOB_IMAGES, *JOBS)), Job.character_id == cid,
                                Job.status.in_(("queued", "running"))).first() is not None


def _asset_out(db: Session, a: CharacterAsset, m: dict | None = None) -> dict:
    m = m if m is not None else meta(db)
    info = m.get(str(a.id)) or {}
    return {"id": a.id, "kind": a.kind, "status": a.status, "url": storage().url(a.storage_key),
            "style": info.get("style") or ("stick" if a.kind == "master" else None), "from_preview": bool(info.get("from_preview")),
            "created_at": S.ts(a.created_at)}


def current_prompt(db: Session, ep: Episode, v: dict, c: Character, sid: str) -> dict:
    """{text, source, label} of a character's master prompt in this style: the owner's or GPT's text when it was written
    for this style, else the template (labelled as such)."""
    p = (v.get("prompts") or {}).get(str(c.id))
    if p and p.get("style") == sid and p.get("text"):
        lab = "written by GPT" if p.get("source") == "gpt" else "your own text"
        if p.get("edited") and p.get("source") == "gpt":
            lab = "written by GPT, edited by you"
        return {**p, "label": lab}
    text, refs = style_block(db, sid)
    d = _desc_for(v, c.id) or {"name": c.name, "personality": c.description}
    if not _desc_for(v, c.id) and (c.visual_description or "").strip():
        d = {**d, "accessory": c.visual_description.strip()}
    return {"text": template_prompt(text, d, bool(refs)), "source": "template", "style": sid,
            "label": "template (GPT was not used: no prompt written yet)"}


# ================================================================== GPT master prompt
PROMPT_SYSTEM = ("You write prompts for an image model for a small animation studio. Write ONE prompt, ready to paste, in "
                 "plain English, at most 200 words, for a CHARACTER MASTER: one original character, neutral standing "
                 "pose, full body, plain background. Keep the style block's rules exactly and keep its style. Describe "
                 "the character only from the written description. Never name a real person, actor, brand or studio. "
                 "No text, captions, logos or watermarks. Reply with the prompt only: no title, no explanation.")


def prompt_message(db: Session, v: dict, c: Character, sid: str) -> str:
    text, _refs = style_block(db, sid)
    d = _desc_for(v, c.id) or {"name": c.name, "accessory": (c.visual_description or "").strip(), "personality": c.description}
    return f"STYLE BLOCK (keep it):\n{text}\n\nTHE CHARACTER (written description):\n{description_text(d)}"


def prompt_estimate(db: Session, v: dict, c: Character, sid: str) -> dict:
    from . import prompt_writer as PW
    return PW.estimate(PW.config(db), PROMPT_SYSTEM, prompt_message(db, v, c, sid))


# ================================================================== the view
def library(db: Session) -> dict:
    return _get(db, "cast_library") or {"entries": {}}


def _lib_entry_for(db: Session, cid: int) -> dict | None:
    return next((e for e in (library(db).get("entries") or {}).values() if e.get("character_id") == cid), None)


def styles_out(db: Session) -> list[dict]:
    from .stick_pipeline import reference_image
    out = []
    for sid, p in styles(db).items():
        text, refs = style_block(db, sid)
        urls = []
        for r in refs:
            a = reference_image(db, r)
            if a is not None:
                urls.append(storage().url(a.storage_key))
        out.append({"id": sid, "label": p["label"], "note": p.get("note") or "", "style_prompt": text,
                    "own_prompt": bool((p.get("style_prompt") or "").strip()) or sid != "stick",
                    "examples": urls, "has_reference": bool(urls)})
    return out


def describe_info(db: Session, ep: Episode, v: dict) -> dict:
    from . import acting_analysis as AA
    from . import guided
    ref = guided.reference_video(db, ep.id)
    cast, _names = AA.cast_names(db, ep)
    gcfg = get_section(db, "guide")
    mt = int(get_section(db, "cast").get("describe_max_tokens") or 8000)
    secs = float(ref.get("seconds") or 0) if ref else 0.0
    if ref and not secs:                      # length unknown (ffprobe missing): the storyboard's shot plan, if any
        shots, _src = AA.shot_list(db, ep, None)
        secs = max((float(s["end"]) for s in shots), default=0.0)
    est = describe_estimate(secs, cast, gcfg, mt) if ref and secs else None
    job = db.query(Job).filter_by(kind=JOB_DESCRIBE, episode_id=ep.id).order_by(Job.id.desc()).first()
    d = v.get("describe") or {}
    return {"reference_video": bool(ref), "estimate": est, "key_set": bool(secret("gemini_api_key", db)),
            "free_models": list(gcfg.get("acting_free_models") or []), "cast_names": cast,
            "busy": _describe_active(db, ep.id), "job": S.job(job) if job else None,
            "made": d.get("made"), "model_used": d.get("model_used"), "usd": d.get("usd"), "partial": d.get("partial")}


def _describe_active(db: Session, eid: int) -> bool:
    return db.query(Job).filter(Job.kind == JOB_DESCRIBE, Job.episode_id == eid,
                                Job.status.in_(("queued", "running"))).first() is not None


def view(db: Session, ep: Episode) -> dict:
    from .stick_pipeline import IMAGE_PROVIDERS, approved_master, image_cost
    v = stored(db, ep.id)
    m = meta(db)
    sid = ep.style
    each = _each(db)
    n = int(get_section(db, "cast").get("candidates") or 2)
    chars = []
    for c in _cast(db, ep):
        master = approved_master(db, c.id)
        rows = (db.query(CharacterAsset).filter(CharacterAsset.character_id == c.id,
                                                CharacterAsset.kind.in_(("master", PREVIEW_KIND)))
                .order_by(CharacterAsset.id.desc()).all())
        d = _desc_for(v, c.id)
        lib = _lib_entry_for(db, c.id)
        item = {"id": c.id, "name": c.name, "key": c.key, "locked_art": bool(c.locked), "description_id": d["id"] if d else None,
                "look": (c.visual_description or "").strip(),
                "master": _asset_out(db, master, m) if master else None,
                "master_style": master_style(db, master),
                "candidates": [_asset_out(db, a, m) for a in rows if a.kind == "master" and a.status == "review"],
                "history": [_asset_out(db, a, m) for a in rows if a.kind == "master" and a.status in ("superseded", "rejected")][:12],
                "busy": _busy(db, c.id), "in_library": lib["id"] if lib else None}
        if sid:
            item["prompt"] = current_prompt(db, ep, v, c, sid)
            item["prompt_estimate"] = prompt_estimate(db, v, c, sid)
        chars.append(item)
    pv = v.get("previews") or {}
    previews = {}
    for s, ids in (pv.get("items") or {}).items():
        a = db.get(CharacterAsset, ids[-1]) if ids else None
        if a is not None:
            previews[s] = _asset_out(db, a, m)
    st = get_section(db, "stick")
    prov = IMAGE_PROVIDERS.get(st.get("image_provider"))
    jobs = (db.query(Job).filter(Job.kind.in_((JOB_IMAGES, JOB_DESCRIBE)), Job.episode_id == ep.id)
            .order_by(Job.id.desc()).limit(8).all())
    return {"episode_id": ep.id, "style": sid, "styles": styles_out(db), "describe": describe_info(db, ep, v),
            "descriptions": v.get("characters") or [], "characters": chars,
            "previews": {"character_id": pv.get("character_id"), "items": previews},
            "preview_character": pv.get("character_id") or _main_speaker(db, ep, v),
            "provider": {"id": st.get("image_provider"), "label": prov["label"] if prov else "off"},
            "usd_per_image": each, "candidates_default": n, "candidate_cost": image_cost(n, each),
            "head_finding": head_finding(db, ep.id), "library": library_out(db), "jobs": [S.job(j) for j in jobs],
            "keys": {"gemini": bool(secret("gemini_api_key", db)), "openai": bool(secret("openai_api_key", db)),
                     "wavespeed": bool(secret("wavespeed_api_key", db))}}


# ================================================================== routes: styles
@router.get("/cast/styles")
def get_styles(db: Session = Depends(get_db)):
    return {"styles": styles_out(db)}


@router.put("/cast/styles/{sid}/reference/upload", status_code=201)
async def upload_style_example(sid: str, request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's own style example for one preset (PNG or JPEG, the request body). It is added to that preset's
    references (at most four; the oldest drops off)."""
    import io
    from PIL import Image
    from .settings_store import put_section
    from .tasks import store_asset
    if sid not in STYLE_IDS:
        raise HTTPException(404, "no such style")
    raw = await request.body()
    if not raw or len(raw) > 15_000_000:
        raise HTTPException(422, "the style example must be a PNG or JPEG up to 15 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        fmt = img.format
    except Exception:
        raise HTTPException(422, "the style example must be a PNG or JPEG image")
    if fmt not in ("PNG", "JPEG"):
        raise HTTPException(422, "the style example must be a PNG or JPEG image")
    ext = "png" if fmt == "PNG" else "jpg"
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"style.{ext}"
        f.write_bytes(raw)
        n = db.query(Asset).filter_by(kind="style-reference").count() + 1
        a = store_asset(db, ep_id=None, src=f, key=f"cast/styles/{sid}-example-{n}.{ext}", kind="style-reference",
                        label=f"{styles(db)[sid]['label']} example {n}", content_type="image/png" if ext == "png" else "image/jpeg")
    db.commit()
    all_styles = styles(db)
    refs = (list(all_styles[sid].get("references") or []) + [{"kind": "asset", "id": a.id}])[-MAX_REFS:]
    all_styles[sid]["references"] = refs
    put_section(db, "cast", {"styles": {k: {f: p[f] for f in ("label", "style_prompt", "references", "note")}
                                        for k, p in all_styles.items()}})
    db.add(Event(kind="character", message=f"Cast style \"{all_styles[sid]['label']}\": example {n} uploaded by {user}"))
    db.commit()
    return {"styles": styles_out(db)}


# ================================================================== routes: the episode's cast
@router.get("/episodes/{eid}/cast-video")
def get_cast(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class DescribeIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=50)
    use_free_tier: bool = False


@router.post("/episodes/{eid}/cast-video/describe")
def describe(eid: int, body: DescribeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (Gemini watches the video and writes the descriptions): starts only with the "at most" price confirmed."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    info = describe_info(db, ep, v)
    if not info["reference_video"]:
        raise HTTPException(409, "upload the reference video first (step 1)")
    if not info["estimate"]:
        raise HTTPException(409, "the length of the reference video is unknown: upload it again")
    if not info["key_set"]:
        raise HTTPException(409, "save the Gemini API key under Settings > Credentials first")
    if info["busy"]:
        raise HTTPException(409, "the characters are already being described")
    est = info["estimate"]
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"describing the characters can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    gcfg = get_section(db, "guide")
    models = [gcfg["acting_model"]] + (list(gcfg.get("acting_free_models") or []) if body.use_free_tier else [])
    job = enqueue(db, JOB_DESCRIBE, episode_id=ep.id, payload={"models": models, "estimate": est, "by": user,
                                                               "free_tier": body.use_free_tier})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Characters from the video asked by {user} (up to ${est['usd_max']:.2f}"
                 + (", free tier allowed" if body.use_free_tier else "") + ")"))
    db.commit()
    return S.job(job)


class HairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: str = Field(default="", max_length=120)
    colour: str = Field(default="", max_length=60)


class GarmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    garment: str = Field(min_length=1, max_length=80)
    colour: str = Field(default="", max_length=60)


class DescFields(BaseModel):
    """The owner's edit of a description (free). Only the fields given change."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=300)
    age: str | None = Field(default=None, max_length=300)
    build: str | None = Field(default=None, max_length=300)
    hair: HairIn | None = None
    clothing: list[GarmentIn] | None = Field(default=None, max_length=8)
    accessory: str | None = Field(default=None, max_length=300)
    personality: str | None = Field(default=None, max_length=300)
    must_never: list[str] | None = Field(default=None, max_length=6)


class DescEditIn(DescFields):
    character_id: int | None = Field(default=None, ge=0)     # 0 = unlink from the cast


def apply_description_edit(db: Session, ep: Episode, did: str, fields: dict, user: str, character_id: int | None = None) -> dict:
    """Change one description (free). A linked character without an approved master gets the new look as its written
    look too; an approved master never changes (characters never change)."""
    from .stick_pipeline import approved_master
    v = stored(db, ep.id)
    d = next((x for x in v.get("characters") or [] if x.get("id") == did), None)
    if d is None:
        raise HTTPException(404, "no such description")
    if not fields and character_id is None:
        raise HTTPException(422, "nothing to change")
    if "must_never" in fields:
        fields["must_never"] = [_clip(s, 160) for s in fields["must_never"] if _clip(s, 160)]
    d.update(fields)
    if character_id is not None:
        if character_id == 0:
            d["character_id"] = None
        else:
            c = db.get(Character, character_id)
            if c is None:
                raise HTTPException(404, "character not found")
            if any(x.get("character_id") == c.id and x["id"] != did for x in v.get("characters") or []):
                raise HTTPException(409, f"{c.name} is already linked to another description")
            d["character_id"] = c.id
    d["edited_by"], d["edited_at"] = user, time.time()
    save(db, ep.id, v)
    note = ""
    if d.get("character_id"):
        c = db.get(Character, d["character_id"])
        if c is not None and approved_master(db, c.id) is None and not c.locked:
            c.visual_description = description_text(d)[:4000]
        elif c is not None:
            note = " (the approved master stays as it is: make a new version to change the look)"
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Cast: description of {d['name']} edited by {user}{note}"))
    db.commit()
    return d


@router.put("/episodes/{eid}/cast-video/descriptions/{did}")
def edit_description(eid: int, did: str, body: DescEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    fields = body.model_dump(exclude_none=True, exclude={"character_id"})
    apply_description_edit(db, ep, did, fields, user, body.character_id)
    return view(db, ep)


@router.post("/episodes/{eid}/cast-video/descriptions/{did}/character", status_code=201)
def create_character(eid: int, did: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Add a person the video shows (and the script does not name) as a character of this episode only (free)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    d = next((x for x in v.get("characters") or [] if x.get("id") == did), None)
    if d is None:
        raise HTTPException(404, "no such description")
    if d.get("character_id"):
        raise HTTPException(409, "this description is already linked to a character")
    base = re.sub(r"[^a-z0-9]+", "-", d["name"].lower()).strip("-")[:40] or "character"
    k, i = f"{base}-ep{ep.id}", 2
    while db.query(Character).filter_by(key=k).first() is not None:
        k, i = f"{base}-ep{ep.id}-{i}", i + 1
    c = Character(key=k, name=d["name"], description=d.get("personality") or "", visual_description=description_text(d)[:4000],
                  scope="episode", episode_id=ep.id)
    db.add(c)
    db.flush()
    d["character_id"] = c.id
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="character", message=f"Cast: {c.name} added to this episode by {user}"))
    db.commit()
    return view(db, ep)


class StyleIn(BaseModel):
    style: Literal["stick", "flat2d", "3d", "anime", "clay"]
    allow_mixed: bool = False


@router.put("/episodes/{eid}/cast-video/style")
def choose_style(eid: int, body: StyleIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's choice of the episode's style (free). The preview of that style, if there is one, becomes one of
    that character's master candidates (still waiting for approval). Approved masters in another style never change:
    the change is refused unless the owner accepts a mixed cast (allow_mixed)."""
    from .stick_pipeline import approved_master
    ep = _episode(db, eid)
    if ep.style == body.style:
        return view(db, ep)
    other = [c.name for c in _cast(db, ep) if (m := approved_master(db, c.id)) is not None and master_style(db, m) != body.style]
    if other and not body.allow_mixed:
        raise HTTPException(409, f"{', '.join(other)} already have an approved master in another style. Approved masters "
                                 "never change: make new master versions in the new style, or confirm a mixed cast")
    ep.style = body.style
    v = stored(db, eid)
    pv = v.get("previews") or {}
    ids = (pv.get("items") or {}).get(body.style) or []
    kept = None
    if ids:
        a = db.get(CharacterAsset, ids[-1])
        if a is not None and a.kind == PREVIEW_KIND:
            a.kind, a.status = "master", "review"
            m = meta(db)
            m.setdefault(str(a.id), {}).update(kind="candidate", from_preview=True)
            _put(db, "cast_meta", m)
            kept = a.id
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Episode style set to \"{styles(db)[body.style]['label']}\" by {user}"
                 + (" (its preview is kept as a master candidate)" if kept else "")))
    db.commit()
    return view(db, ep)


class PreviewIn(BaseModel):
    character_id: int | None = None
    styles: list[Literal["stick", "flat2d", "3d", "anime", "clay"]] | None = Field(default=None, min_length=1, max_length=5)
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


def _item(db: Session, ep: Episode, v: dict, c: Character, sid: str, prompt: str | None = None) -> dict:
    text, refs = style_block(db, sid)
    if prompt is None:
        prompt = current_prompt(db, ep, v, c, sid)["text"]
    return {"character_id": c.id, "style": sid, "prompt": prompt, "refs": refs}


def preview_cost(db: Session, n: int) -> dict:
    from .stick_pipeline import image_cost
    return image_cost(n, _each(db))


@router.post("/episodes/{eid}/cast-video/previews")
def make_previews(eid: int, body: PreviewIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid ($0.04 per style): one picture of one character in each chosen style, side by side, so the owner can pick
    the style by seeing it. Previews are not masters and never choose the style."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    cid = body.character_id or _main_speaker(db, ep, v)
    if not cid:
        raise HTTPException(409, "describe the characters from the video first (or link a description to a character)")
    c = _char_in_cast(db, ep, cid)
    if _desc_for(v, c.id) is None and not (c.visual_description or "").strip():
        raise HTTPException(422, f"write or link {c.name}'s description first")
    if c.locked:
        raise HTTPException(409, "this character uses approved repository artwork; it is not redrawn here")
    if _busy(db, c.id):
        raise HTTPException(409, f"{c.name}: pictures are already being made")
    prov = _provider(db)
    sids = list(dict.fromkeys(body.styles or STYLE_IDS))
    cost = preview_cost(db, len(sids))
    _confirm(cost["usd"], body.confirm_usd, f"{len(sids)} style preview(s)")
    items = [{**_item(db, ep, v, c, s), "kind": "preview"} for s in sids]
    job = enqueue(db, JOB_IMAGES, episode_id=ep.id, character_id=c.id,
                  payload={"items": items, "provider": prov["id"], "usd_each": prov["usd_per_image"], "usd": cost["usd"],
                           "by": user, "what": "previews"})
    pv = v.setdefault("previews", {})
    if pv.get("character_id") != c.id:
        v["previews"] = {"character_id": c.id, "items": {}}
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="character", message=f"{c.name}: style previews ({', '.join(sids)}) asked by {user} ({cost['label']})"))
    db.commit()
    return S.job(job)


class PromptWriteIn(BaseModel):
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


@router.post("/episodes/{eid}/cast-video/characters/{cid}/prompt")
def write_prompt(eid: int, cid: int, body: PromptWriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid (one GPT call, never retried): GPT writes the master prompt from the description and the style block. It is
    saved for the owner to read and edit; candidates are drawn from it."""
    from . import prompt_writer as PW
    ep = _episode(db, eid)
    if not ep.style:
        raise HTTPException(409, "choose the episode's style first")
    c = _char_in_cast(db, ep, cid)
    v = stored(db, eid)
    est = prompt_estimate(db, v, c, ep.style)
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"writing this prompt can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    api_key = secret("openai_api_key", db)
    if not api_key:
        raise HTTPException(409, "save the OpenAI API key under Settings > Credentials first (or use the template prompt)")
    cfg = PW.config(db)
    out = PW.call_openai(api_key, cfg["prompt_model"], PROMPT_SYSTEM, prompt_message(db, v, c, ep.style), int(cfg["prompt_max_tokens"]))
    if not out["text"]:
        raise HTTPException(502, "OpenAI returned no prompt; the template prompt is still there")
    usd = PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg)
    v = stored(db, eid)
    v.setdefault("prompts", {})[str(c.id)] = {"text": out["text"], "original": out["text"], "source": "gpt", "style": ep.style,
                                             "model": cfg["prompt_model"], "usd": usd, "at": time.time(), "by": user}
    v["usd"] = round((v.get("usd") or 0.0) + usd, 6)
    save(db, eid, v)
    db.add(Event(episode_id=eid, kind="episode", message=f"{c.name}: master prompt written by {cfg['prompt_model']} for {user} (${usd:.4f})"))
    db.commit()
    return view(db, ep)


class PromptEditIn(BaseModel):
    text: str = Field(min_length=20, max_length=8000)


@router.put("/episodes/{eid}/cast-video/characters/{cid}/prompt")
def edit_prompt(eid: int, cid: int, body: PromptEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's own master prompt text (free)."""
    ep = _episode(db, eid)
    if not ep.style:
        raise HTTPException(409, "choose the episode's style first")
    c = _char_in_cast(db, ep, cid)
    v = stored(db, eid)
    p = (v.get("prompts") or {}).get(str(c.id)) or {}
    src = p.get("source") if p.get("style") == ep.style else None
    v.setdefault("prompts", {})[str(c.id)] = {**(p if src else {}), "text": body.text, "source": src or "owner",
                                             "style": ep.style, "edited": True, "edited_by": user, "at": time.time()}
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class CandidatesIn(BaseModel):
    count: int | None = Field(default=None, ge=1, le=4)
    confirm_usd: float | None = Field(default=None, ge=0, le=10)
    new_version: bool = False
    prompt: str | None = Field(default=None, min_length=20, max_length=8000)


def make_candidates(db: Session, ep: Episode, cid: int, body: CandidatesIn, user: str) -> dict:
    """Paid ($0.04 each): master candidates in the episode's style, from the description (never from the video). They
    go to review. A character with an approved master is locked: only new_version=true draws new candidates."""
    from .stick_pipeline import approved_master
    if not ep.style:
        raise HTTPException(409, "choose the episode's style first (step 4: Cast)")
    c = _char_in_cast(db, ep, cid)
    if c.locked:
        raise HTTPException(409, "this character uses approved repository artwork; it is not redrawn here")
    if approved_master(db, c.id) is not None and not body.new_version:
        raise HTTPException(409, f"{c.name}'s master is approved and locked (characters never change). Tick \"new version\" "
                                 "to draw candidates for a new master version; the approved one stays until you approve another")
    v = stored(db, ep.id)
    if _desc_for(v, c.id) is None and not (c.visual_description or "").strip():
        raise HTTPException(422, f"write or link {c.name}'s description first")
    if _busy(db, c.id):
        raise HTTPException(409, f"{c.name}: pictures are already being made")
    prov = _provider(db)
    n = body.count or int(get_section(db, "cast").get("candidates") or 2)
    cost = preview_cost(db, n)
    _confirm(cost["usd"], body.confirm_usd, f"{n} master candidate(s)")
    item = {**_item(db, ep, v, c, ep.style, body.prompt), "kind": "candidate"}
    job = enqueue(db, JOB_IMAGES, episode_id=ep.id, character_id=c.id,
                  payload={"items": [item] * n, "provider": prov["id"], "usd_each": prov["usd_per_image"], "usd": cost["usd"],
                           "by": user, "what": "candidates", "new_version": body.new_version})
    db.add(Event(episode_id=ep.id, kind="character", message=f"{c.name}: {n} master candidate(s) in \"{styles(db)[ep.style]['label']}\" "
                 f"asked by {user} ({cost['label']})"))
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/cast-video/characters/{cid}/candidates")
def candidates(eid: int, cid: int, body: CandidatesIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return make_candidates(db, _episode(db, eid), cid, body, user)


class ApproveIn(BaseModel):
    asset_id: int
    keep: Literal["library", "episode"]          # the owner's choice: "Save to my cast library" or "this episode only"
    new_version: bool = False


@router.post("/episodes/{eid}/cast-video/characters/{cid}/approve")
def approve(eid: int, cid: int, body: ApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's approval of one candidate (only this click approves). It becomes the locked master every later step
    uses. When the character already has an approved master, this is a new master version and needs new_version=true;
    the earlier master is kept in history. keep=library also saves the character to the owner's cast library."""
    from .stick_pipeline import approved_master
    ep = _episode(db, eid)
    c = _char_in_cast(db, ep, cid)
    a = db.get(CharacterAsset, body.asset_id)
    if a is None or a.character_id != c.id or a.kind != "master":
        raise HTTPException(404, "not one of this character's master candidates")
    if a.status != "review":
        raise HTTPException(409, f"this picture is {a.status}, not waiting for a decision")
    old = approved_master(db, c.id)
    if old is not None and not body.new_version:
        raise HTTPException(409, f"{c.name}'s master is approved and locked. Tick \"new version\" to replace it with this one")
    for o in db.query(CharacterAsset).filter_by(character_id=c.id, kind="master", status="approved"):
        o.status = "superseded"
    a.status = "approved"
    c.art_status = "approved"
    m = meta(db)
    info = m.setdefault(str(a.id), {})
    info.update(approved_by=user, approved_at=time.time(), episode_id=info.get("episode_id") or ep.id)
    info.setdefault("style", ep.style or "stick")
    _put(db, "cast_meta", m)
    if body.keep == "library":
        save_to_library(db, ep, c, a, info["style"], user)
    db.add(Event(episode_id=ep.id, kind="approval",
                 message=f"{c.name}: master {'new version ' if old is not None else ''}approved by {user}"
                         + (" and saved to the cast library" if body.keep == "library" else " (this episode only)")))
    db.commit()
    return view(db, ep)


class RejectIn(BaseModel):
    asset_id: int


@router.post("/episodes/{eid}/cast-video/characters/{cid}/reject")
def reject(eid: int, cid: int, body: RejectIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    c = _char_in_cast(db, ep, cid)
    a = db.get(CharacterAsset, body.asset_id)
    if a is None or a.character_id != c.id or a.kind != "master" or a.status != "review":
        raise HTTPException(404, "not one of this character's candidates waiting for a decision")
    a.status = "rejected"
    db.add(Event(episode_id=ep.id, kind="character", message=f"{c.name}: master candidate rejected by {user}"))
    db.commit()
    return view(db, ep)


# ================================================================== the cast library
def save_to_library(db: Session, ep: Episode, c: Character, a: CharacterAsset, style: str, user: str) -> dict:
    lib = library(db)
    entries = lib.setdefault("entries", {})
    e = _lib_entry_for(db, c.id)
    v = stored(db, ep.id)
    if e is None:
        e = {"id": pysecrets.token_hex(4), "character_id": c.id, "name": c.name, "versions": [], "saved_at": time.time(),
             "saved_by": user, "episode_id": ep.id}
    e.update(style=style, master_asset_id=a.id, description=_desc_for(v, c.id))
    if a.id not in e["versions"]:
        e["versions"].append(a.id)
    entries[e["id"]] = e
    _put(db, "cast_library", lib)
    return e


def _episodes_using(db: Session, cid: int) -> list[int]:
    out = set()
    c = db.get(Character, cid)
    if c is not None and c.scope == "episode" and c.episode_id:
        out.add(c.episode_id)
    for row in db.query(Setting).filter(Setting.key.like("cast:%")):
        v = row.value or {}
        if cid in (v.get("extra") or []) or any(d.get("character_id") == cid for d in v.get("characters") or []):
            try:
                out.add(int(row.key.split(":")[1]))
            except ValueError:
                pass
    return sorted(out)


def library_out(db: Session) -> list[dict]:
    out = []
    names = styles(db)
    for e in sorted((library(db).get("entries") or {}).values(), key=lambda x: x.get("saved_at") or 0):
        a = db.get(CharacterAsset, e.get("master_asset_id")) if e.get("master_asset_id") else None
        out.append({"id": e["id"], "character_id": e["character_id"], "name": e["name"], "style": e.get("style"),
                    "style_label": (names.get(e.get("style")) or {}).get("label", e.get("style")),
                    "master_url": storage().url(a.storage_key) if a is not None else None,
                    "versions": len(e.get("versions") or []), "description": e.get("description"),
                    "used_by": _episodes_using(db, e["character_id"])})
    return out


@router.get("/cast/library")
def get_library(db: Session = Depends(get_db)):
    return {"entries": library_out(db)}


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.put("/cast/library/{lid}")
def rename_entry(lid: str, body: RenameIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Rename a saved character (free). The character keeps its key, so scripts that use it keep working."""
    lib = library(db)
    e = (lib.get("entries") or {}).get(lid)
    if e is None:
        raise HTTPException(404, "not in the cast library")
    e["name"] = body.name.strip()
    c = db.get(Character, e["character_id"])
    if c is not None and not c.locked:
        c.name = e["name"]
    _put(db, "cast_library", lib)
    db.add(Event(kind="character", message=f"Cast library: renamed to {e['name']} by {user}"))
    db.commit()
    return {"entries": library_out(db)}


@router.delete("/cast/library/{lid}")
def remove_entry(lid: str, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Remove a character from the library. Only the library entry goes: the character, its approved master and every
    version stay, so an episode that uses them keeps working."""
    lib = library(db)
    e = (lib.get("entries") or {}).pop(lid, None)
    if e is None:
        raise HTTPException(404, "not in the cast library")
    _put(db, "cast_library", lib)
    used = _episodes_using(db, e["character_id"])
    db.add(Event(kind="character", message=f"Cast library: {e['name']} removed by {user} (master kept"
                 + (f"; used by episode(s) {', '.join(map(str, used))}" if used else "") + ")"))
    db.commit()
    return {"removed": lid, "master_kept": True, "used_by": used, "entries": library_out(db)}


class UseIn(BaseModel):
    description_id: str | None = Field(default=None, max_length=20)
    allow_mixed: bool = False


@router.post("/episodes/{eid}/cast-video/library/{lid}/use")
def use_saved(eid: int, lid: str, body: UseIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Use a saved character in this episode (free: no picture is drawn; its locked master is used as it is)."""
    ep = _episode(db, eid)
    e = (library(db).get("entries") or {}).get(lid)
    if e is None:
        raise HTTPException(404, "not in the cast library")
    c = db.get(Character, e["character_id"])
    if c is None:
        raise HTTPException(404, "the saved character no longer exists")
    if ep.style and e.get("style") and e["style"] != ep.style and not body.allow_mixed:
        raise HTTPException(409, f"{e['name']} is drawn in \"{styles(db)[e['style']]['label']}\" and this episode uses "
                                 f"\"{styles(db)[ep.style]['label']}\": confirm a mixed cast to use it anyway")
    v = stored(db, ep.id)
    if body.description_id:
        d = next((x for x in v.get("characters") or [] if x.get("id") == body.description_id), None)
        if d is None:
            raise HTTPException(404, "no such description")
        for x in v.get("characters") or []:
            if x.get("character_id") == c.id:
                x["character_id"] = None
        d["character_id"] = c.id
    extra = [int(i) for i in v.get("extra") or []]
    if c.id not in extra:
        extra.append(c.id)
    v["extra"] = extra
    save(db, ep.id, v)
    db.add(Event(episode_id=ep.id, kind="character", message=f"Cast: saved character {e['name']} used in this episode by {user} (no cost)"))
    db.commit()
    return view(db, ep)


# ================================================================== owner-set heads (non-stick styles)
class HeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=20000)
    y: float = Field(ge=0, le=20000)
    r: float = Field(default=40, ge=4, le=4000)


class HeadsIn(BaseModel):
    heads: list[HeadIn] = Field(max_length=16)


@router.get("/episodes/{eid}/owner-heads/{aid}")
def get_heads(eid: int, aid: int, db: Session = Depends(get_db)):
    _episode(db, eid)
    return {"heads": owner_heads(db, eid, aid) or [], **head_finding(db, eid)}


@router.put("/episodes/{eid}/owner-heads/{aid}")
def put_heads(eid: int, aid: int, body: HeadsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's clicks: one per head, left to right as seated (free). Used instead of automatic head finding when
    the episode's style is not the stick man. The steps' cached head positions for this picture are refreshed."""
    _episode(db, eid)
    if db.get(Asset, aid) is None and db.get(CharacterAsset, aid) is None:
        raise HTTPException(404, "picture not found")
    hk = f"owner_heads:{eid}"
    v = _get(db, hk)
    v[str(aid)] = sorted([h.model_dump() for h in body.heads], key=lambda h: h["x"])
    _put(db, hk, v)
    db.commit()
    return {"heads": v[str(aid)], **head_finding(db, eid)}


# ================================================================== the jobs
from .tasks import Ctx, task  # noqa: E402


@task
def cast_describe(ctx: Ctx) -> dict:
    """Gemini watches the reference video once and writes the descriptions (words only). The uploaded file is deleted
    from Google afterwards, also when the request fails."""
    from . import acting_analysis as AA
    from . import guided
    import shutil
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    ref = guided.reference_video(db, ep.id)
    if not ref:
        raise ValueError("the reference video was removed: upload it again")
    api_key = secret("gemini_api_key", db)
    if not api_key:
        raise ValueError("save the Gemini API key under Settings > Credentials first")
    gcfg = get_section(db, "guide")
    mt = int(get_section(db, "cast").get("describe_max_tokens") or 8000)
    cast, _names = AA.cast_names(db, ep)
    free = set(gcfg.get("acting_free_models") or [])
    folder = ctx.folder("episodes", ep.id, f"cast-job{job.id}")
    video = storage().get_to_file(ref["key"], folder / f"reference{Path(ref['key']).suffix or '.mp4'}")
    try:
        with AA.client() as c:
            f = None
            try:
                f = AA.upload(c, api_key, video, ref["content_type"], f"episode-{ep.id}-cast")
                ctx.log("reference video uploaded to Gemini")
                model, d = AA.generate(c, api_key, list(p.get("models") or [gcfg["acting_model"]]),
                                       describe_body(f["uri"], ref["content_type"], describe_prompt(cast), mt), ctx.log)
            finally:
                if f is not None:
                    ctx.log("uploaded video deleted from Gemini" if AA.delete(c, api_key, f["name"])
                            else "could not confirm the uploaded video was deleted from Gemini (it expires after 48 h)")
    except httpx.HTTPError as e:
        raise ProviderError(f"Gemini could not be reached ({type(e).__name__}); not retried")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    u = d.get("usageMetadata") or {}
    tin, tout = int(u.get("promptTokenCount", 0)), int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
    usd = 0.0 if model in free else AA.cost_usd(tin, tout, gcfg)
    try:
        raw = json.loads(AA.answer_text(d))
    except ValueError:
        raise ProviderError("Gemini's answer was not valid JSON; not retried")
    traits = (AA.stored(db, ep.id).get("result") or {}).get("characters") or {}
    descs = normalise_descriptions(raw, cast, traits)
    if not descs:
        raise ProviderError("Gemini described no characters; not retried")
    byname = {ch.name.lower(): ch.id for ch in _cast(db, ep)}
    v = stored(db, ep.id)
    old = {d["name"].lower(): d for d in v.get("characters") or []}
    for d in descs:
        prev = old.get(d["name"].lower())
        d["character_id"] = (prev or {}).get("character_id") or (byname.get(d["name"].lower()) if d["in_script"] else None)
    v["characters"] = descs
    v["describe"] = {"made": time.time(), "model_used": model, "usage": {"input_tokens": tin, "output_tokens": tout},
                     "usd": round(usd, 6), "free_tier": model in free}
    save(db, ep.id, v)
    for d in descs:                        # the written look of characters that have no approved master yet
        if d.get("character_id"):
            from .stick_pipeline import approved_master
            ch = db.get(Character, d["character_id"])
            if ch is not None and not ch.locked and approved_master(db, ch.id) is None:
                ch.visual_description = description_text(d)[:4000]
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Characters from the video: {len(descs)} described by {model} (${usd:.4f})"))
    db.commit()
    return {"characters": len(descs), "usd": round(usd, 6)}


@task
def cast_images(ctx: Ctx) -> dict:
    """Previews or master candidates: one paid image per item (never retried). The request carries the prompt (text)
    and the style's own reference images only. Every picture goes to review; nothing is chosen or approved here."""
    from PIL import Image
    from . import wavespeed
    from .stick_pipeline import IMAGE_PROVIDERS
    from .storage import sha256_file
    db, job = ctx.db, ctx.job
    p = job.payload or {}
    c = db.get(Character, job.character_id)
    prov = IMAGE_PROVIDERS[p["provider"]]
    folder = ctx.folder("characters", c.key, "cast", f"job{job.id}")
    uploaded: dict[str, list[str]] = {}
    made = []
    for i, it in enumerate(p.get("items") or [], 1):
        sk = it["style"]
        if sk not in uploaded:
            files = safe_reference_files(db, it.get("refs") or [], folder)
            uploaded[sk] = [wavespeed.upload(f) for f in files]
            ctx.log(f"{sk}: {len(files)} style reference image(s) uploaded")
        endpoint, body = image_request(prov, it["prompt"], uploaded[sk])
        out = folder / f"image-{i}.png"
        try:
            wavespeed.run(db, endpoint, body, float(p["usd_each"]), f"{c.key} {it['kind']} {sk} {i}", out, ctx.log)
        except ProviderError as e:
            if made:
                db.commit()
                raise ProviderError(f"{len(made)} of {len(p['items'])} pictures made (kept); then: {e}", transient=False)
            raise
        with Image.open(out) as im:
            w, h = im.size
        kind = PREVIEW_KIND if it["kind"] == "preview" else "master"
        skey = f"characters/{c.key}/cast/{kind}-{sk}-job{job.id}-{i}.png"
        storage().put_file(skey, out, "image/png")
        a = CharacterAsset(character_id=c.id, kind=kind, expression="", storage_key=skey, sha256=sha256_file(out),
                           width=w, height=h, status="preview" if kind == PREVIEW_KIND else "review", style_version="v2")
        db.add(a)
        db.flush()
        m = meta(db)
        m[str(a.id)] = {"style": sk, "episode_id": job.episode_id, "character_id": c.id, "kind": it["kind"],
                        "prompt": it["prompt"][:8000], "job_id": job.id}
        _put(db, "cast_meta", m)
        if kind == PREVIEW_KIND:
            v = stored(db, job.episode_id)
            pv = v.setdefault("previews", {"character_id": c.id, "items": {}})
            if pv.get("character_id") != c.id:
                pv.update(character_id=c.id, items={})
            pv.setdefault("items", {}).setdefault(sk, []).append(a.id)
            save(db, job.episode_id, v)
        made.append(a.id)
        db.commit()
        ctx.log(f"{it['kind']} {i} ({sk}): saved (image {a.id})")
    db.add(Event(episode_id=job.episode_id, kind="character",
                 message=f"{c.name}: {len(made)} {'style preview(s)' if p.get('what') == 'previews' else 'master candidate(s)'} ready to look at"))
    db.commit()
    return {"made": made, "usd": round(len(made) * float(p["usd_each"]), 4)}
