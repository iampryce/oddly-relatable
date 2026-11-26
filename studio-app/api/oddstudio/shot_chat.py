"""Chat under each shot: a conversation attached to one thing being made (a character master, a shot still, a shot's
animation clip, the acting notes of one shot, a prompt-writer draft). The owner gives context in plain words; the
assistant answers and may propose ONE change, which the owner applies (or dismisses) with a click. Applying always goes
through the step's existing handler, so the same checks and the same cost confirmation apply as for the step's own
buttons. Nothing paid runs without the owner's click and the confirmed price (confirm_usd, HTTP 409 otherwise).

Threads: one per (step, item), kept in the settings table: `threads:<episode_id>` for an episode's items and
`threads:characters` for character masters (characters are studio-wide). Each message: id, role, text, time; an
assistant message may carry a proposal and its status (pending | applied | dismissed | queued | note).

Context (built here from the database, never taken from the browser): the episode title, the step, the shot number and
time range, the item's current prompt or draft, the acting beats of that shot (from `acting:<id>`; the reference video
is described by those beat texts only, never by its frames), the approved character descriptions and the house style
(Settings > Studio style), the item's settings (model, length, price) and the last 10 messages of the thread. Keys are
never read for the context: they come only from secrets_store.secret() for the call itself and are never logged or
returned.

Assistant (Settings > Chat under each shot): OpenAI (default "gpt-5.5", $5 / $30 per million tokens in / out) through
the official OpenAI SDK (Responses API), or Anthropic (the studio chat's model and price, chat.MODELS) through the
official Anthropic SDK. Each message is estimated before it is sent (like the studio chat: the request must carry the
most it can cost); one call, never retried. An empty balance or a missing key is answered in plain English and the
typed message stays in the box (nothing is saved on failure).

Proposals: a fixed set per step, validated strictly (unknown types or fields are refused and left out of the reply):
  master  note_only | redo_master                        (new master candidates: paid, generate_master)
  still   note_only | redo_still {prompt?}               (a new still take: paid, stick_shots.make_still)
  clip    note_only | rerender_shot {settings}           (a new clip: paid, stick_shots.animate; cfg/steps are not
                                                          offered by the current video provider, so a proposal using
                                                          them is queued for the own-GPU animation step)
  acting  note_only | edit_beat {shot, beat_index, fields} (free, acting_analysis.edit_beat)
  prompt  note_only | update_prompt {prompt}             (free, the draft becomes this text: prompt_writer.edit)
  talk    note_only | rerender_talking_shot {prompt?, use_guide?}
                                                         (a new talking-shot render on the rented GPU: paid,
                                                          talking_s2v.render with its confirm_usd / cap 409s; thread
                                                          key talk:<shot>)
  pose    note_only | redo_pose {prompt, character?}     (a new picture of one reaction pose: paid, the masked face
          | edit_beat                                     edit of reactions.generate_poses; item "<shot>:<pose>")
  clip    ... | reanimate_shot {move_prompts?}           (a reaction shot animated again: paid, reactions.animate)
"""
from __future__ import annotations

import json
import math
import re
import secrets as pysecrets
import time
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, Job, Setting
from .secrets_store import secret
from .settings_store import get_section

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

STEPS = {"master": "Character master", "still": "Shot still", "clip": "Shot animation",
         "acting": "Acting notes (from the reference video)", "prompt": "Prompt writer draft",
         "talk": "Talking shot", "pose": "Reaction pose (face-only edit)"}
ALLOWED = {"master": ("note_only", "redo_master"), "still": ("note_only", "redo_still"),
           "clip": ("note_only", "rerender_shot", "reanimate_shot"), "acting": ("note_only", "edit_beat"),
           "prompt": ("note_only", "update_prompt"), "talk": ("note_only", "rerender_talking_shot"),
           "pose": ("note_only", "redo_pose", "edit_beat")}
HISTORY = 10                    # messages of the thread sent with each new one
CHARS_PER_TOKEN = 3.5
TYPICAL_OUTPUT = 500
ITEM = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
POSE_ITEM = re.compile(r"^\d{1,3}:\d{1,2}$")       # "<shot>:<pose>": the thread is "pose:<shot>:<pose>"
NO_CREDIT = {"openai": "Your OpenAI balance is empty; add credit at platform.openai.com > Billing, or switch the "
                       "assistant in Settings > Chat under each shot. Your message was not sent and is still in the box.",
             "anthropic": "Your Anthropic balance is empty; add credit at console.anthropic.com > Billing, or switch the "
                          "assistant in Settings > Chat under each shot. Your message was not sent and is still in the box."}
NO_KEY = {"openai": "Save the OpenAI API key under Settings > Credentials, or switch the assistant in Settings > Chat "
                    "under each shot.",
          "anthropic": "Save the Anthropic API key under Settings > Credentials, or switch the assistant in Settings > "
                       "Chat under each shot."}

_test_handler = None            # tests only: fn(url, headers, body) -> (status, json), behind each SDK's mock transport


def set_test_handler(fn) -> None:
    """Tests only: answer the SDKs' HTTP requests in-process (no network, no cost)."""
    global _test_handler
    _test_handler = fn


def _mock_client(provider: str):
    """An HTTP client for the provider's SDK that hands every request to the test handler. The OpenAI SDK uses httpx,
    the Anthropic SDK (2.x) its own httpx2: each gets a client of its own library."""
    lib = __import__("httpx2" if provider == "anthropic" else "httpx")

    def handle(request):
        status, body = _test_handler(str(request.url), dict(request.headers), request.content.decode())
        return lib.Response(status, json=body)
    return lib.Client(transport=lib.MockTransport(handle))


# ------------------------------------------------------------------ proposals (pure, strict)
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteOnly(_Strict):
    type: Literal["note_only"]


class UpdatePrompt(_Strict):
    type: Literal["update_prompt"]
    prompt: str = Field(min_length=1, max_length=8000)


class BeatFields(_Strict):
    t_start: float | None = Field(default=None, ge=0, le=36000)
    t_end: float | None = Field(default=None, ge=0, le=36000)
    on_word: str | None = Field(default=None, max_length=80)
    expression: str | None = Field(default=None, max_length=400)
    eyes_and_gaze: str | None = Field(default=None, max_length=400)
    head_and_body: str | None = Field(default=None, max_length=400)
    hands: str | None = Field(default=None, max_length=400)
    hold_or_move: Literal["hold", "move"] | None = None
    intensity: Literal["subtle", "clear", "big"] | None = None


class EditBeat(_Strict):
    type: Literal["edit_beat"]
    shot: int = Field(ge=1, le=999)
    beat_index: int = Field(ge=0, le=200)
    fields: BeatFields


class RedoStill(_Strict):
    type: Literal["redo_still"]
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)


class RedoMaster(_Strict):
    type: Literal["redo_master"]


class RerenderSettings(_Strict):
    prompt: str | None = Field(default=None, min_length=1, max_length=1500)
    seconds: int | None = Field(default=None, ge=1, le=20)
    cfg: float | None = Field(default=None, ge=0, le=30)
    steps: int | None = Field(default=None, ge=1, le=200)


class RerenderShot(_Strict):
    type: Literal["rerender_shot"]
    settings: RerenderSettings


class RerenderTalkingShot(_Strict):
    type: Literal["rerender_talking_shot"]
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    use_guide: bool | None = None


class RedoPose(_Strict):
    type: Literal["redo_pose"]
    prompt: str = Field(min_length=1, max_length=4000)
    character: str | None = Field(default=None, min_length=1, max_length=80)


class ReanimateShot(_Strict):
    type: Literal["reanimate_shot"]
    move_prompts: dict[str, str] | None = Field(default=None, max_length=40)


Proposal = Annotated[Union[NoteOnly, UpdatePrompt, EditBeat, RedoStill, RedoMaster, RerenderShot, RerenderTalkingShot,
                           RedoPose, ReanimateShot],
                     Field(discriminator="type")]
_proposal = TypeAdapter(Proposal)


def validate_proposal(step: str, item: str, raw, allowed: tuple | None = None) -> dict:
    """The proposal as a clean dict, or ValueError (unknown type, a type this step does not offer, unknown or invalid
    fields, an edit_beat for another shot, a beat edit that changes nothing)."""
    if not isinstance(raw, dict):
        raise ValueError("the proposal is not an object")
    if raw.get("type") not in (allowed or ALLOWED[step]):
        raise ValueError(f"\"{raw.get('type')}\" is not a change this step can make")
    try:
        p = _proposal.validate_python(raw).model_dump(exclude_none=True)
    except ValidationError as e:
        raise ValueError(f"the proposal is not valid ({e.error_count()} problem(s))")
    if p["type"] == "edit_beat":
        if str(p["shot"]) != str(item).split(":")[0]:
            raise ValueError("a beat edit must be for this thread's shot")
        if not p["fields"]:
            raise ValueError("the beat edit changes nothing")
    if p["type"] == "rerender_shot" and not p["settings"]:
        p["settings"] = {}
    if p["type"] == "reanimate_shot":
        from .reactions import check_move_prompts
        p["move_prompts"] = check_move_prompts(p.get("move_prompts") or {})
        if not p["move_prompts"]:
            p.pop("move_prompts")
    return p


def describe(p: dict) -> str:
    """"What will change", in plain words."""
    t = p["type"]
    if t == "update_prompt":
        return "The draft prompt is replaced by the text below (it stays a draft until you click Use this prompt)."
    if t == "edit_beat":
        bits = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in p["fields"].items())
        return f"Shot {p['shot']}, beat {p['beat_index'] + 1}: {bits}."
    if t == "redo_still":
        return ("A new still for this shot (a new take; the earlier takes are kept)"
                + (", drawn from the prompt below." if p.get("prompt") else ", drawn from the shot's usual prompt."))
    if t == "redo_master":
        return "New master candidates for this character (they go to review; the approved master stays until you replace it)."
    if t == "rerender_shot":
        s = p["settings"]
        bits = [f"{k}: {v}" for k, v in s.items() if k != "prompt"]
        return ("A new clip for this shot (the earlier clips are kept)" + (f", with {', '.join(bits)}" if bits else "")
                + (", moved as the prompt below says." if s.get("prompt") else "."))
    if t == "rerender_talking_shot":
        guide = ("" if "use_guide" not in p else
                 ", following the actor's head" if p["use_guide"] else ", without the movement guide")
        return ("A new render of this talking shot on the rented GPU (the earlier results are kept)" + guide
                + (", from the prompt below (it also becomes the shot's prompt)." if p.get("prompt") else ", from the shot's current prompt."))
    if t == "redo_pose":
        who = f" of {p['character']}" if p.get("character") else ""
        return (f"A new picture of this pose: only the face{who} is redrawn inside its oval, from the prompt below "
                "(the earlier pictures are kept; nothing is approved for you).")
    if t == "reanimate_shot":
        n = len(p.get("move_prompts") or {})
        return ("This reaction shot is animated again from its approved poses (the earlier results are kept)"
                + (f", with {n} move prompt(s) changed as below." if n else ", with the current move prompts."))
    return "Nothing changes: this is advice only."


def queued_reason(p: dict) -> str | None:
    """Why a proposal waits for a step that is not built yet (None when it can be applied now)."""
    if p["type"] == "rerender_shot" and ({"cfg", "steps"} & set(p["settings"])):
        return ("Queued for when the own-GPU animation step exists: the current video service has no cfg or steps "
                "settings, so this cannot be applied yet.")
    return None


# ------------------------------------------------------------------ settings and cost (pure)
def assistant(db: Session) -> dict:
    """{provider, model, label, usd_in, usd_out, max_tokens} from Settings > Chat under each shot."""
    from .chat import MODELS
    cfg = get_section(db, "shot_chat")
    if cfg.get("provider") == "anthropic":
        m = MODELS["anthropic"]
        return {"provider": "anthropic", "model": m["model"], "label": m["label"], "usd_in": m["usd_in"],
                "usd_out": m["usd_out"], "max_tokens": int(cfg["max_tokens"])}
    return {"provider": "openai", "model": cfg["model"], "label": f"{cfg['model']} (OpenAI)",
            "usd_in": float(cfg["usd_in"]), "usd_out": float(cfg["usd_out"]), "max_tokens": int(cfg["max_tokens"])}


def allowed_for(db: Session, ref) -> tuple:
    """The proposals this thread offers. A clip thread of a REACTION shot (reactions.py) offers reanimate_shot only (its
    clip is made from approved poses, not by the stick video service); other clip threads keep rerender_shot."""
    if ref.step != "clip":
        return ALLOWED[ref.step]
    from . import reactions as R
    ep = db.get(Episode, ref.episode_id) if ref.episode_id else None
    is_reaction = bool(ep and ref.item.isdigit() and any(r["index"] == int(ref.item) for r in R.reaction_rows(db, ep)))
    return ("note_only", "reanimate_shot") if is_reaction else ("note_only", "rerender_shot")


def check_settings(v: dict) -> None:
    if v.get("provider", "openai") not in ("openai", "anthropic"):
        raise ValueError("shot_chat.provider must be openai or anthropic")
    if "model" in v and not (isinstance(v["model"], str) and re.match(r"^[A-Za-z0-9._-]{1,80}$", v["model"])):
        raise ValueError("shot_chat.model must be a model name (letters, digits, dots, dashes)")
    for k in ("usd_in", "usd_out"):
        if k in v and not (isinstance(v[k], (int, float)) and not isinstance(v[k], bool) and 0 < v[k] <= 200):
            raise ValueError(f"shot_chat.{k} must be a price per million tokens above 0 and at most 200")
    mt = v.get("max_tokens", 2000)
    if not (isinstance(mt, int) and not isinstance(mt, bool) and 256 <= mt <= 16000):
        raise ValueError("shot_chat.max_tokens must be a whole number between 256 and 16000")


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / CHARS_PER_TOKEN))


def cost_usd(a: dict, tin: int, tout: int) -> float:
    return round(tin * a["usd_in"] / 1e6 + tout * a["usd_out"] / 1e6, 6)


def estimate(a: dict, system: str, messages: list[dict]) -> dict:
    tin = estimate_tokens(system) + sum(estimate_tokens(m["content"]) + 4 for m in messages)
    mt = a["max_tokens"]
    return {"provider": a["provider"], "model": a["model"], "label": a["label"], "input_tokens": tin,
            "max_output_tokens": mt, "usd_typical": round(cost_usd(a, tin, min(mt, TYPICAL_OUTPUT)), 4),
            "usd_max": round(cost_usd(a, tin, mt), 4), "usd_per_mtok": {"input": a["usd_in"], "output": a["usd_out"]}}


# ------------------------------------------------------------------ threads (storage)
class Ref(BaseModel):
    episode_id: int | None = Field(default=None, ge=1)
    step: Literal["master", "still", "clip", "acting", "prompt", "talk", "pose"]
    item: str = Field(min_length=1, max_length=40)


def row_key(ref: Ref) -> str:
    return "threads:characters" if ref.step == "master" else f"threads:{ref.episode_id}"


def thread_id(ref: Ref) -> str:
    return f"{ref.step}:{ref.item}"


def check_ref(db: Session, ref: Ref) -> None:
    if ref.step == "pose":
        if not POSE_ITEM.match(ref.item):
            raise HTTPException(422, "the item of a pose thread is <shot>:<pose>")
    elif not ITEM.match(ref.item):
        raise HTTPException(422, "not a valid item")
    if ref.step == "master":
        if not ref.item.isdigit() or db.get(Character, int(ref.item)) is None:
            raise HTTPException(404, "character not found")
        return
    if ref.episode_id is None or db.get(Episode, ref.episode_id) is None:
        raise HTTPException(404, "episode not found")
    if ref.step in ("still", "clip", "acting", "talk") and not ref.item.isdigit():
        raise HTTPException(422, "the item of this step is a shot number")


def load_all(db: Session, ref: Ref) -> dict:
    row = db.get(Setting, row_key(ref))
    return json.loads(json.dumps(row.value)) if row else {"threads": {}}


def save_all(db: Session, ref: Ref, v: dict) -> None:
    row = db.get(Setting, row_key(ref))
    if row:
        row.value = v
    else:
        db.add(Setting(key=row_key(ref), value=v))


def get_thread(db: Session, ref: Ref) -> dict:
    return (load_all(db, ref).get("threads") or {}).get(thread_id(ref)) or {"messages": [], "usd": 0.0}


def put_thread(db: Session, ref: Ref, t: dict) -> None:
    v = load_all(db, ref)
    v.setdefault("threads", {})[thread_id(ref)] = t
    save_all(db, ref, v)


def add_messages(db: Session, ref: Ref, msgs: list[dict], usd: float = 0.0) -> dict:
    t = get_thread(db, ref)
    t["messages"] = (t.get("messages") or []) + msgs
    t["usd"] = round((t.get("usd") or 0.0) + usd, 6)
    put_thread(db, ref, t)
    return t


# ------------------------------------------------------------------ context (server-side only)
def _shot(db: Session, eid: int, n: int) -> dict | None:
    from . import shot_frames as SF
    shots = SF.migrated(SF.stored(db, eid)).get("shots") or []
    return shots[n - 1] if 1 <= n <= len(shots) else None


def _latest_job_prompt(db: Session, eid: int, kind: str, index: int) -> str | None:
    for j in db.query(Job).filter_by(kind=kind, episode_id=eid).order_by(Job.id.desc()).limit(50):
        if (j.payload or {}).get("index") == index and (j.payload or {}).get("prompt"):
            return j.payload["prompt"]
    return None


def _beats(analysis: dict | None, n: int) -> list[str]:
    """The acting beats of one shot as numbered lines (the model refers to them by number)."""
    s = next((x for x in (analysis or {}).get("shots") or [] if x.get("shot") == n), None)
    if not s:
        return []
    out = [f"What the reference shows: {s.get('what_the_reference_shows', '')}".strip()]
    for i, b in enumerate(s.get("beats") or []):
        bits = [f"{k.replace('_', ' ')}: {b[k]}" for k in ("expression", "eyes_and_gaze", "head_and_body", "hands") if b.get(k)]
        word = f" on '{b['on_word']}'" if b.get("on_word") else ""
        out.append(f"[beat_index {i}] {b.get('t_start')}-{b.get('t_end')} s {b.get('character', '')}{word}: "
                   f"{'; '.join(bits)} ({b.get('hold_or_move', '')}, {b.get('intensity', '')})")
    return out


def build_context(db: Session, ref: Ref) -> dict:
    """Everything the assistant is told about this item, from the database. Only named, non-secret fields."""
    from . import acting_analysis as AA
    from . import prompt_writer as PW
    from .stick_pipeline import IMAGE_PROVIDERS, VIDEO_PROVIDERS, approved_master, master_prompt
    st = get_section(db, "stick")
    ip, vp = IMAGE_PROVIDERS.get(st.get("image_provider")), VIDEO_PROVIDERS.get(st.get("video_provider"))
    cx: dict = {"step": STEPS[ref.step], "house_style": (st.get("style_prompt") or "").strip()}
    chars: list[Character] = []

    if ref.step == "master":
        c = db.get(Character, int(ref.item))
        chars = [c]
        cx["item"] = f"Character master of {c.name}"
        cx["current_prompt"] = master_prompt(st.get("style_prompt") or "", c)
        cx["settings"] = {"image_model": ip["model"] if ip else "none", "candidates_per_run": int(st.get("master_candidates") or 2),
                          "usd_per_image": ip["usd_per_image"] if ip else None,
                          "has_approved_master": approved_master(db, c.id) is not None}
    else:
        ep = db.get(Episode, ref.episode_id)
        cx["episode"] = ep.title
        analysis = AA.stored(db, ep.id).get("result")
        n = int(ref.item) if ref.item.isdigit() else int(ref.item.split(":")[0]) if ref.step == "pose" else None
        if ref.step == "prompt":
            p = next((x for x in PW.stored(db, ep.id).get("prompts") or [] if x.get("id") == ref.item), None)
            if p is None:
                raise HTTPException(404, "prompt not found")
            n = p.get("shot")
            cx["item"] = f"{p['kind']} prompt draft" + (f" for shot {n}" if n else "")
            cx["current_prompt"] = p.get("text") or ""
            cx["settings"] = {"kind": p["kind"], "status": p.get("status"), "written_by_model": p.get("model"),
                              "owner_notes": p.get("notes") or ""}
            if p.get("character_id"):
                c = db.get(Character, p["character_id"])
                chars = [c] if c else []
        shot = _shot(db, ep.id, n) if n else None
        if n:
            cx["shot"] = n
        if shot:
            cx["time_range"] = f"{float(shot['t0']):.1f}-{float(shot['t1']):.1f} s"
            cx["framing"] = shot.get("shot")
            names = {c.key: c for c in db.query(Character).filter(Character.key.in_(shot.get("people") or []))}
            if ref.step != "prompt" or not chars:
                chars = [names[k] for k in shot.get("people") or [] if k in names]
        if ref.step == "still":
            from . import stick_shots as SS
            cx["item"] = f"Still of shot {n}"
            if shot:
                info = SS.shot_context(db, ep, SF_plan(db, ep.id), shot)
                default = SS.still_prompt(shot, info["names"], info["standing"], info["speaker"], info["said"],
                                          info["action"], SS.aspect_ratio(ep))
                cx["current_prompt"] = _latest_job_prompt(db, ep.id, "stick_shot_still", n) or default
                cx["settings"] = {"image_model": ip["model"] if ip else "none", "aspect_ratio": SS.aspect_ratio(ep),
                                  "usd_per_image": ip["usd_per_image"] if ip else None,
                                  "takes": len(shot.get("versions") or []), "approved": bool(shot.get("approved"))}
        if ref.step == "clip":
            from . import stick_shots as SS
            cx["item"] = f"Animation clip of shot {n}"
            if shot:
                info = SS.shot_context(db, ep, SF_plan(db, ep.id), shot)
                cx["current_prompt"] = (_latest_job_prompt(db, ep.id, "stick_shot_animate", n)
                                        or SS.motion_prompt(shot, info["names"], info["speaker"], info["action"]))
                cx["settings"] = {"video_model": vp["model"] if vp else "none",
                                  "seconds": int(st.get("video_seconds") or 5),
                                  "allowed_seconds": vp["durations"] if vp else [],
                                  "usd_per_second": vp["usd_per_second"] if vp else None,
                                  "clips": len(SS.clips_of(shot)), "still_approved": bool(shot.get("approved")),
                                  "clip_approved": bool(shot.get("clip_approved")),
                                  "note": "the current video service takes a prompt and a length only (no cfg or steps)"}
        if ref.step == "talk":
            from . import talking_s2v as TS
            cx["item"] = f"Talking shot {n} (Wan 2.2 Speech-to-Video from the approved still)"
            cx.update(TS.chat_context(db, ep, n))
        if ref.step == "pose":
            cx.update(_pose_context(db, ep, n, int(ref.item.split(":")[1])))
        if ref.step == "clip":
            rc = _reaction_clip_context(db, ep, n)
            if rc:
                cx.update(rc)
        if ref.step == "acting":
            cx["item"] = f"Acting notes of shot {n}"
            cx["settings"] = {"analysis_model": ", ".join(AA.stored(db, ep.id).get("model_used") or []) or "not run yet"}
        if n:
            cx["acting_beats"] = _beats(analysis, n)
    # the look as approved by the owner (name, one accessory, expression): the visual description only
    cx["characters"] = [f"{c.name}: {(c.visual_description or '').strip() or '(no description yet)'}"
                        + ("" if approved_master(db, c.id) else " (no approved master yet)") for c in chars if c]
    t = get_thread(db, ref)
    cx["history"] = [{"role": m["role"], "content": m["text"]} for m in (t.get("messages") or [])][-HISTORY:]
    return cx


def _pose_context(db: Session, ep: Episode, n: int, i: int) -> dict:
    from . import reactions as R
    row = next((r for r in R.reaction_rows(db, ep) if r["index"] == n), None)
    if row is None:
        raise HTTPException(404, f"shot {n} is not a reaction shot")
    v = R.stored(db, ep.id)
    st = R.ensure_shot(db, ep, v, row)
    if not 0 <= i < len(st.get("poses") or []):
        raise HTTPException(404, "no such pose")
    p = st["poses"][i]
    chars = R._people(db, row["people"])
    pr = R.pose_prompts(db, ep, v, row, p, chars, R.shot_beats(db, ep.id, n))
    return {"item": f"Pose {i} ('{p['label']}') of reaction shot {n}",
            "current_prompt": {k: x["text"] for k, x in pr.items()} or "(no face change: the crop as it is)",
            "settings": {"method": "Qwen-Image-Edit-2511 masked edit (face interior only), pasted back onto the original pixels",
                         "pose_time_s": p["t"], "faces": {k: f.get("want") for k, f in (p.get("faces") or {}).items()},
                         "characters_in_pose": list((p.get("faces") or {}).keys()), "pictures": len(p.get("takes") or []),
                         "approved": bool(p.get("approved")),
                         "rules": "prompts must keep the eyeline sentence (screen-left / screen-right); never a huge mouth"}}


def _reaction_clip_context(db: Session, ep: Episode, n: int | None) -> dict | None:
    from . import reactions as R
    if not n:
        return None
    row = next((r for r in R.reaction_rows(db, ep) if r["index"] == n), None)
    if row is None:
        return None
    v = R.stored(db, ep.id)
    st = R.ensure_shot(db, ep, v, row)
    seg = R.timeline(st.get("poses") or [], row["t1"] - row["t0"])
    mp = R.move_prompts(st, row, seg, R._people(db, row["people"]))
    return {"item": f"Animated reaction shot {n}",
            "current_prompt": {x["key"]: x["text"] for x in mp.values()},
            "settings": {"method": "Wan 2.2 first+last frame between approved poses (33 frames, 16 fps, 4 steps), "
                                   "living holds over 0.4 s, assembled at 25 fps with the room locked",
                         "poses": [{"pose": j, "label": p["label"], "t": p["t"]} for j, p in enumerate(st.get("poses") or [])],
                         "move_prompt_keys": "the pose number a move goes into (2), or hold-2 for pose 2's living hold",
                         "results": len(st.get("clips") or []), "approved": bool(st.get("approved"))}}


def SF_plan(db: Session, eid: int) -> dict:
    from . import shot_frames as SF
    return SF.migrated(SF.stored(db, eid))


SCHEMAS = {
    "note_only": '{"type": "note_only"}',
    "update_prompt": '{"type": "update_prompt", "prompt": "<the full new prompt>"}',
    "edit_beat": ('{"type": "edit_beat", "shot": <this shot>, "beat_index": <n>, "fields": {only the fields to change, '
                  'from: t_start, t_end, on_word, expression, eyes_and_gaze, head_and_body, hands, '
                  'hold_or_move ("hold"|"move"), intensity ("subtle"|"clear"|"big")}}'),
    "redo_still": '{"type": "redo_still", "prompt": "<the full new still prompt, or leave out to reuse the current one>"}',
    "redo_master": '{"type": "redo_master"}',
    "redo_pose": ('{"type": "redo_pose", "prompt": "<the full new face prompt, keeping the eyeline sentence>", '
                  '"character": "<the character key, only when the pose changes several faces>"}'),
    "reanimate_shot": ('{"type": "reanimate_shot", "move_prompts": {"<pose number or hold-<pose>>": "<new move prompt>"}}  '
                       '(only for an animated reaction shot; leave move_prompts out to animate again as it is)'),
    "rerender_shot": ('{"type": "rerender_shot", "settings": {"prompt": "<the motion prompt>", "seconds": <one of the '
                      'allowed seconds>}}  (add "cfg" or "steps" only if the owner asks for them: they wait for the '
                      'own-GPU step)'),
    "rerender_talking_shot": ('{"type": "rerender_talking_shot", "prompt": "<the full new positive prompt, or leave out to '
                              'keep the current one>", "use_guide": <true|false, or leave out to keep the current '
                              'choice>}  (the model and its settings are fixed; only the prompt and the movement guide '
                              'can change)'),
}

SYSTEM = """You help the owner of Oddly Relatable, a small studio making short 2D stick-figure comedy cartoons. The
owner is not a developer: answer in plain, short English. You are attached to ONE item being made (described below) and
the owner is giving you context about it. Use the owner's words, the acting notes and the current prompt.

Rules:
- Characters never change: never redesign a character's look; refer to the approved description only.
- The reference video is described only by its acting notes; it is never used for the look.
- You cannot run anything. You may propose at most ONE change, which the owner applies with a click. Paid changes
  always show their cost to the owner first.
- Changes this item allows (use exactly one of these shapes, or null):
{schemas}

Reply with JSON only: {{"reply": "<your answer to the owner>", "proposal": <one of the shapes above, or null>}}"""


def system_prompt(ref: Ref, cx: dict, allowed: tuple | None = None) -> str:
    body = {k: v for k, v in cx.items() if k != "history"}
    schemas = "\n".join(f"  {SCHEMAS[t]}" for t in (allowed or ALLOWED[ref.step]))
    return SYSTEM.format(schemas=schemas) + "\n\nTHE ITEM (read-only, from the studio):\n" + json.dumps(body, indent=1, default=str)


def messages_for(cx: dict, text: str) -> list[dict]:
    return list(cx["history"]) + [{"role": "user", "content": text}]


# ------------------------------------------------------------------ the call (one, never retried)
def call(db: Session, a: dict, system: str, messages: list[dict]) -> dict:
    """Returns {text, input_tokens, output_tokens}. Plain-English HTTP errors; the key never leaves this function."""
    from .config import get_settings
    if _test_handler is None and get_settings().env == "test":
        raise HTTPException(500, "no paid calls in tests (set a test handler)")
    key = secret(f"{a['provider']}_api_key", db)
    if not key:
        raise HTTPException(409, NO_KEY[a["provider"]])
    kw = {"http_client": _mock_client(a["provider"])} if _test_handler is not None else {}
    if a["provider"] == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=120.0, **kw)
        try:
            r = client.messages.create(model=a["model"], max_tokens=a["max_tokens"], system=system, messages=messages)
        except anthropic.APIStatusError as e:
            msg = json.dumps(e.body) if e.body is not None else str(e)
            if e.status_code == 402 or "credit balance" in msg.lower():
                raise HTTPException(402, NO_CREDIT["anthropic"])
            if e.status_code in (401, 403):
                raise HTTPException(502, "Anthropic did not accept the API key saved in Settings > Credentials")
            raise HTTPException(502, f"Anthropic returned an error (HTTP {e.status_code}); not retried")
        except anthropic.APIConnectionError as e:
            raise HTTPException(502, f"Anthropic could not be reached ({type(e).__name__}); not retried")
        text = "".join(b.text for b in r.content if b.type == "text")
        return {"text": text, "input_tokens": int(r.usage.input_tokens), "output_tokens": int(r.usage.output_tokens)}
    import openai
    client = openai.OpenAI(api_key=key, max_retries=0, timeout=120.0, **kw)
    try:
        r = client.responses.create(model=a["model"], instructions=system, input=messages,
                                    max_output_tokens=a["max_tokens"], reasoning={"effort": "low"},
                                    text={"format": {"type": "json_object"}})
    except openai.APIStatusError as e:
        code = getattr(e, "code", None) or ((e.body or {}).get("code") if isinstance(e.body, dict) else None)
        if code == "insufficient_quota" or e.status_code == 402:
            raise HTTPException(402, NO_CREDIT["openai"])
        if e.status_code in (401, 403):
            raise HTTPException(502, "OpenAI did not accept the API key saved in Settings > Credentials")
        if e.status_code == 404:
            raise HTTPException(502, f"OpenAI does not offer the model \"{a['model']}\" to this key: check Settings > Chat under each shot")
        if e.status_code == 429:
            raise HTTPException(502, "OpenAI is busy (rate limit): try again in a minute; not retried")
        raise HTTPException(502, f"OpenAI returned an error (HTTP {e.status_code}); not retried")
    except openai.APIConnectionError as e:
        raise HTTPException(502, f"OpenAI could not be reached ({type(e).__name__}); not retried")
    u = r.usage
    return {"text": (r.output_text or "").strip(), "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0)}


def parse_reply(step: str, item: str, text: str, allowed: tuple | None = None) -> tuple[str, dict | None, str | None]:
    """(reply text, valid proposal or None, why a proposal was left out or None)."""
    raw = text.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        d = json.loads(m.group(0) if m else raw)
    except ValueError:
        return raw or "(No answer.)", None, None
    if not isinstance(d, dict):
        return raw, None, None
    reply = str(d.get("reply") or "").strip() or "(No answer.)"
    p = d.get("proposal")
    if p is None:
        return reply, None, None
    try:
        return reply, validate_proposal(step, item, p, allowed), None
    except ValueError as e:
        return reply, None, str(e)


# ------------------------------------------------------------------ costs of paid proposals
def proposal_cost(db: Session, ref: Ref, p: dict) -> dict | None:
    """The price shown on Apply (and sent back as confirm_usd); None for free changes."""
    from .stick_pipeline import IMAGE_PROVIDERS, VIDEO_PROVIDERS, image_cost, video_cost
    st = get_section(db, "stick")
    if p["type"] == "redo_still":
        ip = IMAGE_PROVIDERS.get(st.get("image_provider"))
        return image_cost(1, ip["usd_per_image"]) if ip else {"usd": None, "label": "no image service chosen"}
    if p["type"] == "redo_master":
        ip = IMAGE_PROVIDERS.get(st.get("image_provider"))
        return image_cost(int(st.get("master_candidates") or 2), ip["usd_per_image"]) if ip else {"usd": None, "label": "no image service chosen"}
    if p["type"] == "rerender_shot":
        vp = VIDEO_PROVIDERS.get(st.get("video_provider"))
        if not vp or not vp["implemented"]:
            return {"usd": None, "label": "no video service connected"}
        return video_cost(int(p["settings"].get("seconds") or st.get("video_seconds") or 5), vp["usd_per_second"])
    if p["type"] == "rerender_talking_shot":
        from . import talking_s2v as TS
        return TS.chat_render_cost(db, ref.episode_id, int(ref.item), p.get("use_guide"))
    if p["type"] in ("redo_pose", "reanimate_shot"):
        from . import reactions as R
        ep = db.get(Episode, ref.episode_id)
        n = int(ref.item.split(":")[0])
        row = next((r for r in R.reaction_rows(db, ep) if r["index"] == n), None)
        if row is None:
            return {"usd": None, "label": "not a reaction shot"}
        v = R.stored(db, ep.id)
        st = R.ensure_shot(db, ep, v, row)
        if p["type"] == "redo_pose":
            i = int(ref.item.split(":")[1])
            poses = st.get("poses") or []
            faces = len((poses[i].get("faces") or {})) if 0 <= i < len(poses) else 1
            est = R.estimate(max(1, faces), 0, R._prices(db))      # at most every face of the pose is redrawn
        else:
            est = R.estimate(0, len(R.clips_needed(R.timeline(st.get("poses") or [], row["t1"] - row["t0"]))), R._prices(db))
        return {"usd": est["usd_max"], "label": f"up to ${est['usd_max']:.2f} of GPU time ({est['label']})"}
    return None


def message_out(db: Session, ref: Ref, m: dict) -> dict:
    out = dict(m)
    p = m.get("proposal")
    if p:
        out["what_will_change"] = describe(p)
        if m.get("proposal_status") == "pending":
            out["cost"] = proposal_cost(db, ref, p)
    return out


def thread_out(db: Session, ref: Ref) -> dict:
    t = get_thread(db, ref)
    a = assistant(db)
    return {"step": ref.step, "item": ref.item, "step_label": STEPS[ref.step],
            "messages": [message_out(db, ref, m) for m in t.get("messages") or []], "usd": round(t.get("usd") or 0.0, 4),
            "assistant": {"label": a["label"], "key_set": bool(secret(f"{a['provider']}_api_key", db))},
            "proposals": list(allowed_for(db, ref))}


# ------------------------------------------------------------------ routes
@router.get("/shot-chat/thread")
def read_thread(step: str, item: str, episode_id: int | None = None, db: Session = Depends(get_db)):
    try:
        ref = Ref(episode_id=episode_id, step=step, item=item)
    except ValidationError:
        raise HTTPException(422, "not a valid thread")
    check_ref(db, ref)
    return thread_out(db, ref)


class SendIn(Ref):
    text: str = Field(min_length=1, max_length=6000)
    confirm_usd: float | None = Field(default=None, ge=0, le=10)


def _prepare(db: Session, body: SendIn):
    ref = Ref(episode_id=body.episode_id, step=body.step, item=body.item)
    check_ref(db, ref)
    a = assistant(db)
    cx = build_context(db, ref)
    system = system_prompt(ref, cx, allowed_for(db, ref))
    return ref, a, system, messages_for(cx, body.text)


@router.post("/shot-chat/estimate")
def send_estimate(body: SendIn, db: Session = Depends(get_db)):
    """What sending this message would cost (no call is made)."""
    _ref, a, system, messages = _prepare(db, body)
    return {**estimate(a, system, messages), "key_set": bool(secret(f"{a['provider']}_api_key", db))}


@router.post("/shot-chat/send")
def send(body: SendIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Paid: one call, only with the most it can cost confirmed. Nothing is saved when the call fails, so the owner's
    message stays in the box."""
    ref, a, system, messages = _prepare(db, body)
    est = estimate(a, system, messages)
    if body.confirm_usd is None or body.confirm_usd + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"this message can cost up to ${est['usd_max']:.4f}: confirm that amount to send it (nothing was sent)")
    out = call(db, a, system, messages)
    usd = cost_usd(a, out["input_tokens"], out["output_tokens"])
    reply, proposal, rejected = parse_reply(ref.step, ref.item, out["text"], allowed_for(db, ref))
    now = time.time()
    msg = {"id": pysecrets.token_hex(5), "role": "assistant", "text": reply, "at": now, "model": a["model"],
           "usage": {"input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"]}, "usd": usd,
           "estimate": {"usd_typical": est["usd_typical"], "usd_max": est["usd_max"]}}
    if rejected:
        msg["proposal_left_out"] = rejected
    if proposal:
        msg["proposal"] = proposal
        q = queued_reason(proposal)
        msg["proposal_status"] = "note" if proposal["type"] == "note_only" else "queued" if q else "pending"
        if q:
            msg["proposal_note"] = q
    add_messages(db, ref, [{"id": pysecrets.token_hex(5), "role": "user", "text": body.text, "at": now, "by": user}, msg], usd)
    db.commit()
    return {"reply": message_out(db, ref, msg), "thread": thread_out(db, ref), "estimate": est}


class ApplyIn(Ref):
    message_id: str = Field(min_length=1, max_length=20)
    confirm_usd: float | None = Field(default=None, ge=0, le=100)


def _pending(db: Session, body: ApplyIn) -> tuple[Ref, dict, dict]:
    ref = Ref(episode_id=body.episode_id, step=body.step, item=body.item)
    check_ref(db, ref)
    t = get_thread(db, ref)
    m = next((x for x in t.get("messages") or [] if x.get("id") == body.message_id), None)
    if m is None or not m.get("proposal"):
        raise HTTPException(404, "no proposal with this id in this thread")
    if m.get("proposal_status") != "pending":
        raise HTTPException(409, f"this proposal is {m.get('proposal_status')}, not waiting for a decision")
    return ref, t, m


def route(db: Session, ref: Ref, p: dict, confirm_usd: float | None, user: str) -> dict:
    """Apply one proposal through the step's existing handler (its checks and cost confirmation included)."""
    from . import acting_analysis as AA
    from . import prompt_writer as PW
    from . import stick_pipeline as SP
    from . import stick_shots as SS
    t = p["type"]
    if t == "update_prompt":
        item = PW.edit(ref.episode_id, ref.item, PW.EditIn(text=p["prompt"], approve=False), db, user)
        return {"done": "The draft prompt was updated.", "prompt_id": item["id"]}
    if t == "edit_beat":
        AA.edit_beat(ref.episode_id, p["shot"], p["beat_index"], AA.BeatEditIn(**p["fields"]), db, user)
        return {"done": f"Beat {p['beat_index'] + 1} of shot {p['shot']} was updated."}
    if t == "redo_still":
        j = SS.make_still(ref.episode_id, int(ref.item), SS.StillIn(confirm_usd=confirm_usd, prompt=p.get("prompt")), db, user)
        return {"done": "A new still is being made.", "job_id": j["id"]}
    if t == "redo_master":
        j = SP.generate_master(int(ref.item), SP.PaidIn(confirm_usd=confirm_usd), db, user)
        return {"done": "New master candidates are being made.", "job_id": j["id"]}
    if t == "rerender_shot":
        s = p["settings"]
        seconds = int(s.get("seconds") or get_section(db, "stick").get("video_seconds") or 5)
        j = SS.animate(ref.episode_id, int(ref.item), SS.AnimateIn(seconds=seconds, confirm_usd=confirm_usd,
                                                                    prompt=s.get("prompt")), db, user)
        return {"done": "A new clip is being made.", "job_id": j["id"]}
    if t == "rerender_talking_shot":
        from . import talking_s2v as TS
        j = TS.rerender_from_chat(db, ref.episode_id, int(ref.item), p.get("prompt"), p.get("use_guide"), confirm_usd, user)
        return {"done": "The talking shot is being rendered again on the rented GPU.", "job_id": j["id"]}
    if t == "redo_pose":
        from . import reactions as R
        n, i = (int(x) for x in ref.item.split(":"))
        ep = db.get(Episode, ref.episode_id)
        row = R._row(db, ep, n)
        v = R.stored(db, ref.episode_id)
        st = R.ensure_shot(db, ep, v, row)
        faces = list((R._pose_or_404(st, i).get("faces") or {}))
        who = p.get("character") or (faces[0] if len(faces) == 1 else None)
        if who not in faces:
            raise HTTPException(409, "say which character's face to redraw (this pose changes several or none)")
        R.apply_pose_edit(st, row, i, R.PoseEditIn(prompts={who: p["prompt"]}), user)
        R.save(db, ref.episode_id, v)
        db.commit()
        j = R.generate_poses(ref.episode_id, n, R.GenerateIn(poses=[i], confirm_usd=confirm_usd), db, user)
        return {"done": f"A new picture of pose {i} is being made.", "job_id": j["id"]}
    if t == "reanimate_shot":
        from . import reactions as R
        j = R.animate(ref.episode_id, int(ref.item), R.AnimateIn(move_prompts=p.get("move_prompts"), confirm_usd=confirm_usd), db, user)
        return {"done": "The shot is being animated again.", "job_id": j["id"]}
    raise HTTPException(409, "this proposal has nothing to apply")


def _set_status(db: Session, ref: Ref, message_id: str, status: str, extra: dict) -> None:
    db.expire_all()      # the handler may have committed; re-read the thread before writing it back
    t = get_thread(db, ref)
    for m in t.get("messages") or []:
        if m.get("id") == message_id:
            m.update(proposal_status=status, decided_at=time.time(), **extra)
    put_thread(db, ref, t)


@router.post("/shot-chat/apply")
def apply(body: ApplyIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's Apply click. Paid proposals carry the price shown on the card (confirm_usd); the step's own handler
    refuses any other price with 409 and starts nothing."""
    ref, _t, m = _pending(db, body)
    p = m["proposal"]
    cost = proposal_cost(db, ref, p)
    if cost is not None and body.confirm_usd is None:
        raise HTTPException(409, f"this change costs {cost['label']}: confirm that amount to apply it (nothing was started)")
    result = route(db, ref, p, body.confirm_usd, user)
    _set_status(db, ref, m["id"], "applied", {"result": result, "applied_by": user})
    if ref.episode_id:
        db.add(Event(episode_id=ref.episode_id, kind="episode",
                     message=f"{STEPS[ref.step]} {ref.item}: chat proposal ({p['type']}) applied by {user}"))
    db.commit()
    return {"result": result, "thread": thread_out(db, ref)}


@router.post("/shot-chat/dismiss")
def dismiss(body: ApplyIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ref, _t, m = _pending(db, body)
    _set_status(db, ref, m["id"], "dismissed", {"dismissed_by": user})
    db.commit()
    return {"thread": thread_out(db, ref)}
