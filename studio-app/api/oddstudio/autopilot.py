""""Make whole episode": the autopilot at the top of the guided page. The owner sets ONE total budget (USD) and confirms
it (confirm_usd = that budget); the autopilot then runs the guided steps in order by calling each step's EXISTING
function (the same checks, estimates and 409s as the step's own buttons; no logic is duplicated here):

  acting analysis -> prompts (talking shots and reaction faces, GPT) -> cast (characters described from the reference
  video, master prompts, master candidates in the episode's style; cast_from_video.py) -> walls and seating
  pictures -> shot stills -> talking shots -> reactions (poses, animation) -> quality check (+ automatic redos)
  -> clip approvals -> assembly -> the final cut

Owner gates (it STOPS and WAITS, and never approves anything itself, memory "no-self-approvals"): the episode's style
(never chosen for the owner), character masters,
walls and seating pictures, the seating picture each side's close-ups are cut from, crops and poses, shot stills,
every talking / reaction result, and the final cut. While it waits, the list says what to approve and where.

Money (memory "show-cost-before-paid-calls"): the budget confirmed by the owner is the only consent. Before EACH paid
action the autopilot takes that action's "at most" price from the step's own estimate and starts it only when it fits
in what is left of the budget and, for GPU work, in the monthly GPU cap (gpu.py); otherwise it pauses with a plain
message. Each action is counted at its "at most" price until its job reports what it really cost (talking shots,
reactions, the acting analysis and the quality check report it); failed jobs keep their "at most" price. So the
autopilot never passes the budget. A failed job pauses the run (paid work is never retried by itself).

Quality check: at most Settings > Quality check "automatic redos per shot" (default 1) redos per shot, only for a
problem the check calls "clear" and only on a result the owner has not approved; the redo is the check's own proposal
applied through the shot chat's route (shot_chat.route), with its price inside the budget.

GPU: the steps share one rented ComfyUI session. While the autopilot runs GPU steps, comfy_session.others_waiting()
says so (holds_gpu), so a finished job leaves the session up for the next one; when the autopilot waits for the
owner, pauses, stops or finishes it releases the session (terminated unless a GPU job is still running, which then
turns it off itself), and the idle sweep is the backstop. Stop terminates the session at once.

It moves on from a background thread of the studio worker (gpu.start_sweeper calls tick_all every 30 s) and right
after the owner's Start / Resume. Keys are only read through secrets_store.secret() and never shown: the providers
summary says whether each provider is ready, never a key.
"""
from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import CharacterAsset, Episode, Event, Job, Setting
from .secrets_store import secret
from .settings_store import get_section

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

STEPS = ("acting", "prompts", "masters", "sets", "stills", "talking", "reactions", "quality", "approvals", "assembly")
LABEL = {"acting": "Acting analysis", "prompts": "Prompts", "masters": "Cast (characters and their masters)",
         "sets": "Walls and seating pictures", "stills": "Shot stills", "talking": "Talking shots",
         "reactions": "Reaction shots", "quality": "Quality check", "approvals": "Your review of the clips",
         "assembly": "Assembly and the final cut"}
GPU_KINDS = ("talk_render", "poses", "animate", "redo")
SYNC_PAID = ("talk_prompt", "pose_prompt", "cast_prompt")        # paid calls made inside the request (no job to report the cost)
LIVE = ("running", "waiting")
ACTIVE = ("queued", "running")
MAX_BUDGET = 500.0
EPS = 1e-9


def key(eid: int) -> str:
    return f"autopilot:{eid}"


# ================================================================== state
def stored(db: Session, eid: int, lock: bool = False) -> dict:
    q = db.query(Setting).filter_by(key=key(eid))
    row = (q.with_for_update() if lock else q).one_or_none()
    return json.loads(json.dumps(row.value)) if row else {"status": "off"}


def save(db: Session, eid: int, v: dict) -> None:
    v["log"] = (v.get("log") or [])[-80:]
    v["actions"] = (v.get("actions") or [])[-300:]
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


def spent(v: dict) -> float:
    """What the run has used: each action's real cost when known, else its "at most" price."""
    return round(sum(float(a["usd"] if a.get("usd") is not None else a.get("usd_max") or 0.0)
                     for a in v.get("actions") or []), 6)


def remaining(v: dict) -> float:
    return round(float(v.get("budget_usd") or 0.0) - spent(v), 6)


def _log(v: dict, text: str) -> None:
    v.setdefault("log", []).append({"at": time.time(), "text": text})


def holds_gpu(db: Session) -> bool:
    """True while a running autopilot has GPU work next (comfy_session.others_waiting keeps the session up)."""
    for row in db.query(Setting).filter(Setting.key.like("autopilot:%")):
        v = row.value or {}
        if v.get("status") in LIVE and v.get("keep_gpu"):
            return True
    return False


def _comfy_jobs_active(db: Session) -> bool:
    from . import comfy_session as CS
    return db.query(Job).filter(Job.kind.in_(CS.JOB_KINDS), Job.status.in_(ACTIVE)).first() is not None


def release_gpu(db: Session, v: dict, reason: str) -> None:
    """No more GPU work for now: the session is terminated unless a GPU job is still running (that job turns it off
    when it ends, since the autopilot no longer holds it)."""
    from . import comfy_session as CS
    v["keep_gpu"] = False
    if CS.live(db) and not _comfy_jobs_active(db):
        try:
            CS.stop(db, reason)
            _log(v, "The rented GPU was turned off (" + reason + ")")
        except Exception as e:   # noqa: BLE001 -- the idle sweep tries again
            _log(v, f"The GPU could not be turned off now ({str(e)[:120]}); the idle sweep will")


def pause(db: Session, v: dict, msg: str) -> None:
    v["status"], v["message"], v["waiting_for"] = "paused", msg, []
    _log(v, msg)
    release_gpu(db, v, "the autopilot paused")


# ================================================================== plans: one per step (facts only, nothing runs)
def _plan(**kw) -> dict:
    return {"actions": [], "waiting": [], "notes": [], "busy": "", "blocked": "", **kw}


def _act(kind: str, what: str, usd: float, **args) -> dict:
    return {"kind": kind, "what": what, "usd": round(float(usd or 0.0), 6), "gpu": kind in GPU_KINDS, "args": args}


def _wait(what: str, where: str) -> dict:
    return {"what": what, "where": where}


def pictures_ready(db: Session) -> tuple[bool, str]:
    from .stick_pipeline import IMAGE_PROVIDERS
    pid = get_section(db, "stick").get("image_provider")
    if pid not in IMAGE_PROVIDERS:
        return False, "No picture service is chosen (Settings > Studio style): new pictures cannot be made"
    if not secret("wavespeed_api_key", db):
        return False, "WaveSpeed: no key saved (Settings > Credentials): new pictures cannot be made"
    return True, ""


def _image_usd(db: Session, count: int = 1) -> float:
    from .stick_pipeline import IMAGE_PROVIDERS, image_cost
    ip = IMAGE_PROVIDERS.get(get_section(db, "stick").get("image_provider"))
    return image_cost(count, ip["usd_per_image"])["usd"] if ip else 0.0


def plan_acting(db: Session, ep: Episode, v: dict) -> dict:
    from . import acting_analysis as AA
    a = AA.stored(db, ep.id)
    if a.get("result"):
        return _plan(notes=[] if a.get("accepted") else ["The acting notes are used as they are; you have not marked them "
                                                         "right yet (step 2)."])
    if AA._active(db, ep.id).first():
        return _plan(busy="the acting analysis is running")
    if not secret("gemini_api_key", db):
        return _plan(notes=["Gemini: no key, so the acting analysis is skipped; prompts are written without acting notes."])
    p = AA.plan(db, ep)
    if not p["reference_video"]:
        return _plan(notes=["No reference video (step 1): the acting analysis is skipped."])
    if not p["shots"]:
        return _plan(notes=["No storyboard and no video length yet: the acting analysis is skipped."])
    return _plan(actions=[_act("acting", "Acting analysis of the reference video", p["estimate"]["usd_max"])])


def plan_prompts(db: Session, ep: Episode, v: dict) -> dict:
    from . import prompt_writer as PW
    from . import reactions as R
    from . import talking_s2v as T
    if not secret("openai_api_key", db):
        return _plan(notes=["OpenAI: no key, so prompts use the built-in templates (labelled as such)."])
    if v.get("openai_no_credit"):
        return _plan(notes=["OpenAI: no credit, so the remaining prompts use the built-in templates (labelled as such)."])
    done = set(v.get("prompted") or [])
    cfg = PW.config(db)
    acts = []
    tv = T.stored(db, ep.id)
    for r in T.talking_rows(db, ep):
        k = f"talk:{r['index']}"
        p = ((tv.get("shots") or {}).get(str(r["index"])) or {}).get("prompt") or {}
        if k in done or p.get("source") == "gpt" or p.get("edited"):
            continue
        usd = PW.estimate(cfg, PW.SYSTEM, T._prompt_message(db, ep, r))["usd_max"]
        acts.append(_act("talk_prompt", f"Prompt for talking shot {r['index']} (GPT)", usd, shot=r["index"]))
    rv = R.stored(db, ep.id)
    for row in R.reaction_rows(db, ep):
        st = R.ensure_shot(db, ep, rv, row)
        chars = R._people(db, row["people"])
        names = {kk: c.name for kk, c in chars.items()}
        for i, pose in enumerate(st.get("poses") or []):
            k = f"pose:{row['index']}:{i}"
            faces = pose.get("faces") or {}
            if not faces or k in done or all(((f.get("prompt") or {}).get("source") in ("gpt", "owner")) for f in faces.values()):
                continue
            usd = 0.0
            for fk in faces:
                el = R.eyeline_for(db, ep, rv, row["side"], fk, names)
                usd += PW.estimate(cfg, PW.SYSTEM, R._prompt_message(db, ep, row, pose, fk, chars,
                                                                     R.eyeline_text(el["direction"], el["toward"])))["usd_max"]
            acts.append(_act("pose_prompt", f"Face prompt(s) for reaction shot {row['index']}, pose {i} (GPT)", usd,
                             shot=row["index"], pose=i))
    if rv.pop("_dirty", False):
        R.save(db, ep.id, rv)
        db.commit()
    return _plan(actions=acts)


def plan_masters(db: Session, ep: Episode, v: dict) -> dict:
    """The cast step: (1) the characters described from the reference video (Gemini, words only), (2) the episode's
    style, which only the owner chooses, (3) per character without an approved master: its master prompt (GPT, when
    the key and credit are there; otherwise the template) and its candidates in that style, then (4) the owner's
    approval. An episode without descriptions and without a chosen style keeps the earlier stick-man path."""
    from . import cast_from_video as CV
    from . import guided
    from . import stick_pipeline as SP
    out = _plan()
    cast = guided.cast(db, ep)
    missing = [c for c in cast if SP.approved_master(db, c.id) is None]
    if not missing:
        return out
    cv = CV.stored(db, ep.id)
    if not cv.get("characters"):
        if CV._describe_active(db, ep.id):
            out["busy"] = "the characters are being described from the reference video"
            return out
        info = CV.describe_info(db, ep, cv)
        if info["reference_video"] and info["key_set"] and info["estimate"]:
            out["actions"].append(_act("cast_describe", "Describe the characters from the reference video",
                                       info["estimate"]["usd_max"]))
            return out
    if ep.style:
        return _plan_cast(db, ep, v, cv, missing, out)
    if cv.get("characters"):
        out["waiting"].append(_wait("Choose the episode's style (you can make a preview of each style first)", "Guided steps, step 4: Cast"))
        return out
    for c in missing:
        if SP.approved_master(db, c.id) is not None:
            continue
        review = db.query(CharacterAsset).filter_by(character_id=c.id, kind=SP.MASTER_KIND, status="review").first()
        if SP._active(db, c.id).first():
            out["busy"] = f"{c.name}'s master candidates are being drawn"
        elif review is not None:
            out["waiting"].append(_wait(f"Approve a master for {c.name}", "Characters page"))
        elif c.locked:
            out["waiting"].append(_wait(f"{c.name} uses repository artwork: approve its master", "Characters page"))
        elif not (c.visual_description or "").strip():
            out["waiting"].append(_wait(f"Write {c.name}'s look (name, one accessory, expression)", "Characters page"))
        else:
            ok, why = pictures_ready(db)
            if not ok:
                out["blocked"] = why
                return out
            n = int(get_section(db, "stick").get("master_candidates") or 2)
            out["actions"].append(_act("master", f"Master candidates for {c.name}", _image_usd(db, n), character=c.id))
    return out


def _plan_cast(db: Session, ep: Episode, v: dict, cv: dict, missing: list, out: dict) -> dict:
    from . import cast_from_video as CV
    from . import prompt_writer as PW
    gpt = bool(secret("openai_api_key", db)) and not v.get("openai_no_credit")
    n = int(get_section(db, "cast").get("candidates") or 2)
    for c in missing:
        review = db.query(CharacterAsset).filter_by(character_id=c.id, kind="master", status="review").first()
        if CV._busy(db, c.id):
            out["busy"] = f"{c.name}'s pictures are being drawn"
        elif review is not None:
            out["waiting"].append(_wait(f"Approve a master for {c.name}", "Guided steps, step 4: Cast"))
        elif c.locked:
            out["waiting"].append(_wait(f"{c.name} uses repository artwork: approve its master", "Characters page"))
        elif CV._desc_for(cv, c.id) is None and not (c.visual_description or "").strip():
            out["waiting"].append(_wait(f"Link or write {c.name}'s description", "Guided steps, step 4: Cast"))
        else:
            ok, why = pictures_ready(db)
            if not ok:
                out["blocked"] = why
                return out
            p = (cv.get("prompts") or {}).get(str(c.id)) or {}
            k = f"cast:{c.id}:{ep.style}"
            if gpt and p.get("style") != ep.style and k not in (v.get("prompted") or []):
                usd = PW.estimate(PW.config(db), CV.PROMPT_SYSTEM, CV.prompt_message(db, cv, c, ep.style))["usd_max"]
                out["actions"].append(_act("cast_prompt", f"Master prompt for {c.name} (GPT)", usd, character=c.id))
            out["actions"].append(_act("cast_candidates", f"Master candidates for {c.name}", _image_usd(db, n),
                                       character=c.id, count=n))
    return out


def plan_sets(db: Session, ep: Episode, v: dict) -> dict:
    from . import room_sets as RS
    out = _plan()
    if not RS.sides_of(db, ep.id):
        out["waiting"].append(_wait("Make the storyboard: it gives the sides of the room and who sits where", "the episode page"))
        return out
    vw = RS.view(db, ep, light=True)
    pending_sides = set()
    for w in vw["walls"]:
        if w["busy"]:
            out["busy"] = f"the wall \"{w['name']}\" is being drawn"
        elif not w["takes"]:
            out["actions"].append(_act("wall", f"Picture of the wall \"{w['name']}\"", _image_usd(db), wall=w["id"]))
            pending_sides.add(w["side"])
        elif not w["approved"]:
            out["waiting"].append(_wait(f"Approve a picture of the wall \"{w['name']}\"", "step 5"))
            pending_sides.add(w["side"])
    for s in vw["seating"]:
        if s["busy"]:
            out["busy"] = f"the seating picture for {s['label']} is being made"
        elif s["approved"]:
            continue
        elif s["takes"]:
            out["waiting"].append(_wait(f"Approve the seating picture for {s['label']}", "step 5"))
        elif s["missing_masters"]:
            out["waiting"].append(_wait(f"Approve a master for {', '.join(s['missing_masters'])}", "Characters page"))
        elif s["side"] not in pending_sides:       # a wall of this side still on its way: the seating waits for it
            out["actions"].append(_act("seating", f"Seating picture for {s['label']}", _image_usd(db), side=s["side"]))
    for r in vw["repairs"]:
        if r.get("status") == "done" and r.get("approved") is None:
            out["waiting"].append(_wait(f"Decide on the repaired picture ({r.get('label') or r['id']})", "step 5"))
    if out["actions"]:
        ok, why = pictures_ready(db)
        if not ok:
            out["blocked"] = why
    return out


def plan_stills(db: Session, ep: Episode, v: dict) -> dict:
    """Stills for the talking shots and the shots that are neither talking nor reaction shots (reaction shots are cut
    from the seating picture instead)."""
    from . import reactions as R
    from . import shot_frames as SF
    from . import stick_shots as SS
    out = _plan()
    shots = SF.migrated(SF.stored(db, ep.id)).get("shots") or []
    if not shots:
        out["waiting"].append(_wait("Make the storyboard", "the episode page"))
        return out
    reacting = {r["index"] for r in R.reaction_rows(db, ep)}
    for s in shots:
        idx = int(s["index"])
        if idx in reacting or (s.get("approved") and s.get("chosen")):
            continue
        if SS._busy_on(db, ep.id, idx):
            out["busy"] = f"the still of shot {idx} is being drawn"
        elif any(x.get("source") == "still" for x in s.get("versions") or []):
            out["waiting"].append(_wait(f"Approve a still for shot {idx}", "the storyboard on the episode page"))
        else:
            out["actions"].append(_act("still", f"Still for shot {idx}", _image_usd(db), shot=idx))
    if out["actions"]:
        ok, why = pictures_ready(db)
        if not ok:
            out["blocked"] = why
    return out


def _gpu_ok(db: Session) -> tuple[bool, str]:
    from . import comfy_session as CS
    a = CS.availability(db)
    return a["ok"], a["reason"]


def plan_talking(db: Session, ep: Episode, v: dict) -> dict:
    from . import talking_s2v as T
    vw = T.view(db, ep, light=True)
    if vw["busy"]:
        return _plan(busy="talking shots are rendering")
    out = _plan()
    todo = [s["index"] for s in vw["shots"] if not s["blocked"] and not s["renders"]]
    for s in vw["shots"]:
        if s["blocked"] and not s["renders"]:
            out["notes"].append(f"Talking shot {s['index']}: {s['blocked']}.")
    if todo:
        ok, why = _gpu_ok(db)
        if not ok:
            out["blocked"] = f"Talking shots need the rented GPU: {why}"
            return out
        rows = [r for r in T.talking_rows(db, ep) if r["index"] in todo]
        usd = T.render_estimate(db, ep.id, rows, T.stored(db, ep.id))["usd_max"]
        out["actions"].append(_act("talk_render", f"Render talking shot(s) {', '.join(map(str, todo))}", usd, shots=todo))
    return out


def plan_reactions(db: Session, ep: Episode, v: dict) -> dict:
    from . import reactions as R
    vw = R.view(db, ep, light=True)
    if vw["busy"]:
        return _plan(busy="a reaction shot is being made on the GPU")
    out = _plan()
    for m in vw["masters"]:
        if m["shots"] and not m["chosen"]:
            out["waiting"].append(_wait(f"Pick the seating picture the close-ups of \"{m['side']}\" are cut from", "step 6"))
    rows = {r["index"]: r for r in R.reaction_rows(db, ep)}
    rv = R.stored(db, ep.id)
    prices = R._prices(db)
    for s in vw["shots"]:
        i = s["index"]
        if s["blocked"]:
            continue
        if not s["crop_approved"]:
            out["waiting"].append(_wait(f"Approve the crop of reaction shot {i}", "step 6"))
            continue
        st = R.ensure_shot(db, ep, rv, rows[i])
        poses = st.get("poses") or []
        need = [k for k, p in enumerate(poses) if p.get("faces") and not p.get("takes")]
        if need:
            chars = R._people(db, rows[i]["people"])
            beats = R.shot_beats(db, ep.id, i)
            prompts = {k: R.pose_prompts(db, ep, rv, rows[i], poses[k], chars, beats) for k in need}
            usd = R.estimate(R.edits_needed(st, need, prompts), 0, prices)["usd_max"]
            out["actions"].append(_act("poses", f"Faces for reaction shot {i} (pose(s) {', '.join(map(str, need))})", usd, shot=i))
            continue
        if any(not R.pose_ready(st, k) for k in range(len(poses))):
            out["waiting"].append(_wait(f"Approve the poses of reaction shot {i}", "step 7"))
            continue
        if not s["clips"]:
            n = len(R.clips_needed(R.timeline(poses, rows[i]["t1"] - rows[i]["t0"])))
            out["actions"].append(_act("animate", f"Animate reaction shot {i}", R.estimate(0, n, prices)["usd_max"], shot=i))
    if rv.pop("_dirty", False):
        R.save(db, ep.id, rv)
        db.commit()
    if out["actions"]:
        ok, why = _gpu_ok(db)
        if not ok:
            out["blocked"] = f"Reaction shots need the rented GPU: {why}"
    return out


def plan_quality(db: Session, ep: Episode, v: dict) -> dict:
    from . import clip_qa as Q
    from . import shot_chat as SC
    prov = Q.provider(db)
    if not prov["ready"]:
        return _plan(notes=[prov["note"]])
    if db.query(Job).filter(Job.kind == Q.JOB, Job.episode_id == ep.id, Job.status.in_(ACTIVE)).first():
        return _plan(busy="the quality check is running")
    out = _plan()
    q = get_section(db, "quality")
    cl = Q.clips(db, ep)
    checks = Q.stored(db, ep.id).get("checks") or {}
    todo = [c for c in cl if Q.check_key(c) not in checks]
    if todo:
        est = Q.sum_estimates([Q.clip_estimate(db, ep, c, prov, float(q["qa_inline_mb"])) for c in todo], prov)
        out["actions"].append(_act("qa", f"Quality check of {len(todo)} clip(s)", est["usd_max"], shots=[c["shot"] for c in todo]))
        return out
    limit = int(q.get("max_redos_per_shot", 1))
    redos = v.get("redos") or {}
    for c in cl:
        res = checks.get(Q.check_key(c)) or {}
        fix = Q.clear_fix(res) if res else None
        k = f"{c['step']}:{c['shot']}"
        if not fix or c["approved"] or int(redos.get(k, 0)) >= limit:
            continue
        ref = SC.Ref(episode_id=ep.id, step=c["step"], item=str(c["shot"]))
        msg = next((m for m in (SC.get_thread(db, ref).get("messages") or []) if m.get("id") == res.get("message_id")), None)
        if msg is None or msg.get("proposal_status") != "pending" or msg.get("proposal") != fix:
            continue                                   # the owner already decided on this one
        cost = SC.proposal_cost(db, ref, fix) or {"usd": 0.0}
        if cost.get("usd") is None:
            out["notes"].append(f"Shot {c['shot']}: the suggested redo cannot be priced ({cost.get('label')}), so it is left to you.")
            continue
        out["actions"].append(_act("redo", f"Redo shot {c['shot']} (the quality check found a clear problem)", cost["usd"],
                                   step=c["step"], shot=c["shot"], message_id=res["message_id"]))
    return out


def plan_approvals(db: Session, ep: Episode, v: dict) -> dict:
    from . import reactions as R
    from . import talking_s2v as T
    out = _plan()
    for s in T.view(db, ep, light=True)["shots"]:
        if s["renders"] and not s["approved"]:
            out["waiting"].append(_wait(f"Watch talking shot {s['index']} and approve the result you want", "step 9"))
    for s in R.view(db, ep, light=True)["shots"]:
        if s["clips"] and not s["approved"]:
            out["waiting"].append(_wait(f"Watch reaction shot {s['index']} and approve the result you want", "step 8"))
    return out


def plan_assembly(db: Session, ep: Episode, v: dict) -> dict:
    from . import assembly as A
    from .config import get_settings
    out = _plan()
    p = A.plan_rows(db, ep)
    if p["missing"]:
        out["waiting"].append(_wait("Approve a still or a clip for shot(s) " + ", ".join(map(str, p["missing"])), "steps 5-9"))
        return out
    if db.query(Job).filter(Job.kind == A.JOB, Job.episode_id == ep.id, Job.status.in_(ACTIVE)).first():
        return _plan(busy="the episode is being put together")
    av = A.stored(db, ep.id)
    cut = next((c for c in av.get("cuts") or [] if c.get("hash") == p["hash"]), None)
    if cut is None:
        if not get_settings().ffmpeg:
            out["blocked"] = "FFmpeg is not configured on the studio server: the episode cannot be put together"
            return out
        out["actions"].append(_act("assemble", "Put the episode together (free)", 0.0))
    elif av.get("approved") != cut["id"]:
        out["waiting"].append(_wait("Watch the final cut and approve it", "step 11"))
    return out


PLANNERS = {"acting": plan_acting, "prompts": plan_prompts, "masters": plan_masters, "sets": plan_sets, "stills": plan_stills,
            "talking": plan_talking, "reactions": plan_reactions, "quality": plan_quality, "approvals": plan_approvals,
            "assembly": plan_assembly}


# ================================================================== running one action: the steps' own functions
def _job(j: dict) -> dict:
    return {"job_id": j["id"]}


def run_acting(db, ep, a, user, v):
    from . import acting_analysis as AA
    return _job(AA.start(ep.id, AA.StartIn(confirm_usd=a["usd"], use_free_tier=bool(v.get("use_free_tier"))), db, user))


def run_talk_prompt(db, ep, a, user, v):
    from . import talking_s2v as T
    idx = a["args"]["shot"]
    T.write_prompt(ep.id, idx, T.WriteIn(confirm_usd=a["usd"]), db, user)
    p = ((T.stored(db, ep.id).get("shots") or {}).get(str(idx)) or {}).get("prompt") or {}
    v.setdefault("prompted", []).append(f"talk:{idx}")
    if p.get("source") != "gpt":            # the key is there, so the template means GPT had no credit (402)
        v["openai_no_credit"] = time.time()
        return {"usd": 0.0}
    return {"usd": float(p.get("usd") or 0.0)}


def run_pose_prompt(db, ep, a, user, v):
    from . import reactions as R
    idx, i = a["args"]["shot"], a["args"]["pose"]
    R.write_prompt(ep.id, idx, i, R.WriteIn(confirm_usd=a["usd"]), db, user)
    st = (R.stored(db, ep.id).get("shots") or {}).get(str(idx)) or {}
    faces = ((st.get("poses") or [{}] * (i + 1))[i].get("faces") or {}).values()
    v.setdefault("prompted", []).append(f"pose:{idx}:{i}")
    got = [f["prompt"] for f in faces if (f.get("prompt") or {}).get("source") == "gpt"]
    if not got:
        v["openai_no_credit"] = time.time()
    return {"usd": round(sum(float(p.get("usd") or 0.0) for p in got), 6)}


def run_master(db, ep, a, user, v):
    from . import stick_pipeline as SP
    return _job(SP.generate_master(a["args"]["character"], SP.PaidIn(confirm_usd=a["usd"]), db, user))


def run_cast_describe(db, ep, a, user, v):
    from . import cast_from_video as CV
    return _job(CV.describe(ep.id, CV.DescribeIn(confirm_usd=a["usd"], use_free_tier=bool(v.get("use_free_tier"))), db, user))


def run_cast_prompt(db, ep, a, user, v):
    from . import cast_from_video as CV
    cid = a["args"]["character"]
    v.setdefault("prompted", []).append(f"cast:{cid}:{ep.style}")
    CV.write_prompt(ep.id, cid, CV.PromptWriteIn(confirm_usd=a["usd"]), db, user)
    p = (CV.stored(db, ep.id).get("prompts") or {}).get(str(cid)) or {}
    return {"usd": float(p.get("usd") or 0.0)}


def run_cast_candidates(db, ep, a, user, v):
    from . import cast_from_video as CV
    return _job(CV.make_candidates(db, ep, a["args"]["character"],
                                   CV.CandidatesIn(count=a["args"]["count"], confirm_usd=a["usd"]), user))


def run_wall(db, ep, a, user, v):
    from . import room_sets as RS
    return _job(RS.make_wall(ep.id, a["args"]["wall"], RS.MakeIn(confirm_usd=a["usd"]), db, user))


def run_seating(db, ep, a, user, v):
    from . import room_sets as RS
    return _job(RS.make_seating(ep.id, a["args"]["side"], RS.MakeIn(confirm_usd=a["usd"]), db, user))


def run_still(db, ep, a, user, v):
    from . import stick_shots as SS
    return _job(SS.make_still(ep.id, a["args"]["shot"], SS.StillIn(confirm_usd=a["usd"]), db, user))


def run_talk_render(db, ep, a, user, v):
    from . import talking_s2v as T
    return _job(T.render(ep.id, T.RenderIn(shots=a["args"]["shots"], confirm_usd=a["usd"]), db, user))


def run_poses(db, ep, a, user, v):
    from . import reactions as R
    return _job(R.generate_poses(ep.id, a["args"]["shot"], R.GenerateIn(confirm_usd=a["usd"]), db, user))


def run_animate(db, ep, a, user, v):
    from . import reactions as R
    return _job(R.animate(ep.id, a["args"]["shot"], R.AnimateIn(confirm_usd=a["usd"]), db, user))


def run_qa(db, ep, a, user, v):
    from . import clip_qa as Q
    return _job(Q.start(db, ep, a["args"]["shots"], False, a["usd"], user))


def run_redo(db, ep, a, user, v):
    """The check's own proposal applied through the shot chat's route (as the owner's Apply would), then marked
    applied in the thread."""
    from . import shot_chat as SC
    ref = SC.Ref(episode_id=ep.id, step=a["args"]["step"], item=str(a["args"]["shot"]))
    msg = next(m for m in SC.get_thread(db, ref).get("messages") or [] if m.get("id") == a["args"]["message_id"])
    result = SC.route(db, ref, msg["proposal"], a["usd"], user)
    SC._set_status(db, ref, msg["id"], "applied", {"result": result, "applied_by": user})
    db.commit()
    k = f"{a['args']['step']}:{a['args']['shot']}"
    v.setdefault("redos", {})[k] = int(v["redos"].get(k, 0)) + 1
    return {"job_id": result.get("job_id")} if result.get("job_id") else {}


def run_assemble(db, ep, a, user, v):
    from . import assembly as A
    return _job(A.start(db, ep, user))


RUN = {"acting": run_acting, "talk_prompt": run_talk_prompt, "pose_prompt": run_pose_prompt, "master": run_master,
       "cast_describe": run_cast_describe, "cast_prompt": run_cast_prompt, "cast_candidates": run_cast_candidates,
       "wall": run_wall, "seating": run_seating, "still": run_still, "talk_render": run_talk_render, "poses": run_poses,
       "animate": run_animate, "qa": run_qa, "redo": run_redo, "assemble": run_assemble}


# ================================================================== the loop
def reconcile(db: Session, v: dict) -> tuple[bool, str]:
    """(work still in flight, the error of a job that failed). Finished jobs replace their "at most" price with the
    cost they report; a failed job keeps its "at most" price (it may have been billed)."""
    busy, failed = False, ""
    for a in v.get("actions") or []:
        if a.get("state") != "running" or not a.get("job_id"):
            continue
        j = db.get(Job, a["job_id"])
        if j is None:
            a["state"] = "done"
            continue
        if j.status in ACTIVE:
            busy = True
            continue
        if j.status == "succeeded":
            a["state"] = "done"
            r = j.result or {}
            if isinstance(r.get("usd"), (int, float)) and not isinstance(r.get("usd"), bool):
                a["usd"] = round(max(0.0, float(r["usd"])), 6)
        else:
            a["state"] = "failed"
            failed = failed or f"{a['what']} failed: {(j.error or 'no reason given')[:300]}"
    return busy, failed


def _user(v: dict) -> str:
    return f"Autopilot (started by {v.get('by') or 'the owner'})"


def execute(db: Session, ep: Episode, v: dict, step: str, actions: list[dict]) -> int:
    """Start the step's actions in order while each fits the budget (and the GPU cap); GPU actions one at a time (the
    GPU routes take one run at a time). Returns how many started; pauses the run when one cannot start."""
    from . import gpu
    started = 0
    for a in actions:
        if a["gpu"] and started:
            break
        left = remaining(v)
        if a["usd"] > left + EPS:
            pause(db, v, f"Paused before \"{a['what']}\": it can cost up to ${a['usd']:.2f} and ${max(left, 0):.2f} of your "
                         f"${float(v['budget_usd']):.2f} budget is left. Raise the budget and press Resume to go on.")
            return started
        if a["gpu"]:
            cap = float(gpu.cfg(db)["monthly_cap_usd"])
            fig = gpu.month_figures(db)
            if fig["committed_usd"] + a["usd"] > cap + EPS:
                pause(db, v, f"Paused before \"{a['what']}\": up to ${a['usd']:.2f} would pass the monthly GPU cap "
                             f"(${fig['committed_usd']:.2f} committed of ${cap:.2f}). Raise the cap in Settings > GPU worker "
                             "or wait for next month, then press Resume.")
                return started
        try:
            res = RUN[a["kind"]](db, ep, a, _user(v), v) or {}
        except Exception as e:   # noqa: BLE001 -- shown to the owner; nothing is retried by itself
            db.rollback()
            refused = isinstance(e, HTTPException) and e.status_code == 409     # a 409 starts nothing and calls nobody
            if a["kind"] in SYNC_PAID and not refused:
                # the call itself may have been made (and billed): counted at its "at most" price
                v.setdefault("actions", []).append({"id": uuid.uuid4().hex[:8], "step": step, "kind": a["kind"], "what": a["what"],
                                                    "usd_max": a["usd"], "usd": None, "job_id": None, "at": time.time(),
                                                    "state": "failed-seen"})
            why = e.detail if isinstance(e, HTTPException) else f"{type(e).__name__}: {str(e)[:300]}"
            pause(db, v, f"Paused at \"{a['what']}\": {why}")
            return started
        rec = {"id": uuid.uuid4().hex[:8], "step": step, "kind": a["kind"], "what": a["what"], "usd_max": a["usd"],
               "usd": res.get("usd"), "job_id": res.get("job_id"), "at": time.time(),
               "state": "running" if res.get("job_id") else "done"}
        v.setdefault("actions", []).append(rec)
        _log(v, f"Started: {a['what']} (up to ${a['usd']:.2f})" if a["usd"] else f"Started: {a['what']}")
        started += 1
        if a["gpu"]:
            v["keep_gpu"] = True
    return started


def tick(db: Session, eid: int) -> dict:
    """Move one episode's autopilot on: wait for its jobs, then plan the steps in order and start what can start."""
    ep = db.get(Episode, eid)
    v = stored(db, eid, lock=True)
    if ep is None or v.get("status") not in LIVE:
        db.commit()
        return v
    busy, failed = reconcile(db, v)
    if failed:
        pause(db, v, f"Paused: {failed}. Look at the step, then press Resume (nothing is retried by itself).")
    elif busy:
        v["status"], v["message"], v["waiting_for"] = "running", f"Working on: {LABEL.get(v.get('step'), v.get('step') or '')}", []
    else:
        _advance(db, ep, v)
    v["spent_usd"], v["ticked"] = spent(v), time.time()
    save(db, eid, v)
    db.commit()
    return v


def _advance(db: Session, ep: Episode, v: dict) -> None:
    notes = []
    for step in STEPS:
        try:
            plan = PLANNERS[step](db, ep, v)
        except HTTPException as e:
            db.rollback()
            pause(db, v, f"Paused at {LABEL[step]}: {e.detail}")
            return
        notes += plan["notes"]
        v["notes"] = notes
        if plan["busy"]:
            v["step"], v["status"], v["waiting_for"] = step, "running", []
            v["message"] = f"Waiting for {plan['busy']} (started outside the autopilot)"
            return
        if plan["blocked"]:
            v["step"] = step
            pause(db, v, f"Paused at {LABEL[step]}: {plan['blocked']}")
            return
        if plan["actions"]:
            v["step"], v["status"], v["waiting_for"] = step, "running", []
            if not any(a["gpu"] for a in plan["actions"]):
                if step == "quality":
                    v["keep_gpu"] = False        # a redo may follow the check: the idle sweep turns it off if not
                else:
                    release_gpu(db, v, "no GPU work in the next step")
            if execute(db, ep, v, step, plan["actions"]) and v["status"] == "running":
                v["message"] = f"Working on: {LABEL[step]}"
            return
        if plan["waiting"]:
            v["step"], v["status"], v["waiting_for"] = step, "waiting", plan["waiting"]
            v["message"] = f"Waiting for you: {len(plan['waiting'])} thing(s) to approve or do at {LABEL[step]}"
            release_gpu(db, v, "the autopilot is waiting for you")
            return
    v["step"], v["status"], v["waiting_for"] = "assembly", "finished", []
    v["message"] = "Finished: the final cut is approved."
    _log(v, "Finished: the final cut is approved")
    release_gpu(db, v, "the autopilot finished")


def tick_all(db: Session, log=print) -> list[int]:
    """Every live autopilot (the worker's background thread calls this every 30 s)."""
    ids = []
    for row in db.query(Setting).filter(Setting.key.like("autopilot:%")).all():
        if (row.value or {}).get("status") in LIVE:
            try:
                ids.append(int(row.key.split(":", 1)[1]))
            except ValueError:
                continue
    for eid in ids:
        try:
            tick(db, eid)
        except Exception as e:   # noqa: BLE001 -- one episode never stops the others
            db.rollback()
            log(f"autopilot {eid}: {type(e).__name__}: {str(e)[:200]}")
    return ids


# ================================================================== providers summary (no key values, ever)
_balance_cache: dict = {}


def _wavespeed_balance() -> float | None:
    from . import wavespeed
    hit = _balance_cache.get("v")
    if hit and time.time() - hit[1] < 60:
        return hit[0]
    try:
        b = float(wavespeed.balance())
    except Exception:   # noqa: BLE001 -- unreadable balance: shown as unknown
        return None
    _balance_cache["v"] = (b, time.time())
    return b


def needs(db: Session, ep: Episode) -> dict:
    """What the rest of the episode still needs: new pictures (masters, walls, seating, stills) and GPU work."""
    from . import guided
    from . import reactions as R
    from . import room_sets as RS
    from . import shot_frames as SF
    from . import stick_pipeline as SP
    from . import talking_s2v as T
    pics = any(SP.approved_master(db, c.id) is None for c in guided.cast(db, ep))
    rs = RS.stored(db, ep.id)
    pics = pics or any(not (rs.get("seating") or {}).get(s, {}).get("approved") for s in RS.sides_of(db, ep.id))
    reacting = {r["index"] for r in R.reaction_rows(db, ep)}
    pics = pics or any(not (s.get("approved") and s.get("chosen")) and int(s["index"]) not in reacting
                       for s in SF.migrated(SF.stored(db, ep.id)).get("shots") or [])
    tv, rv = T.stored(db, ep.id), R.stored(db, ep.id)
    g = any(not ((tv.get("shots") or {}).get(str(r["index"])) or {}).get("approved") for r in T.talking_rows(db, ep))
    g = g or any(not ((rv.get("shots") or {}).get(str(i)) or {}).get("approved") for i in reacting)
    return {"pictures": pics, "gpu": g}


def providers(db: Session, ep: Episode) -> list[dict]:
    """Which provider each step uses and whether it is ready: [{step, label, provider, ready, note, essential}]."""
    from . import clip_qa as Q
    from . import comfy_session as CS
    from . import gpu
    from .config import get_settings
    from .stick_pipeline import IMAGE_PROVIDERS
    import shutil
    gcfg = get_section(db, "guide")
    v = stored(db, ep.id)
    nd = needs(db, ep)
    out = []
    has_gem = bool(secret("gemini_api_key", db))
    out.append({"step": "acting", "label": "Acting analysis", "provider": f"Gemini {gcfg['acting_model']}", "ready": has_gem,
                "essential": False, "note": "" if has_gem else "Gemini: no key, so the acting analysis is skipped"})
    has_oa = bool(secret("openai_api_key", db))
    note = ("OpenAI: no key, so prompts will use the built-in templates" if not has_oa else
            "OpenAI: no credit last time, so prompts will use the built-in templates" if v.get("openai_no_credit") else "")
    out.append({"step": "prompts", "label": "Prompts", "provider": f"OpenAI {gcfg['prompt_model']}",
                "ready": has_oa and not v.get("openai_no_credit"), "essential": False, "note": note})
    ip = IMAGE_PROVIDERS.get(get_section(db, "stick").get("image_provider"))
    ok, why = pictures_ready(db)
    note = why
    if ok:
        bal = _wavespeed_balance()
        if bal is None:
            note = "WaveSpeed: the balance could not be read"
        elif bal < 1.0:
            note = f"WaveSpeed: low balance (${bal:.2f})"
    out.append({"step": "pictures", "label": "Masters, walls, seating pictures and stills",
                "provider": ip["label"] if ip else "none chosen", "ready": ok, "essential": nd["pictures"],
                "note": note if note else ("" if nd["pictures"] else "nothing new to draw")})
    a = CS.availability(db)
    cap = float(gpu.cfg(db)["monthly_cap_usd"])
    left = round(cap - gpu.month_figures(db)["committed_usd"], 2)
    out.append({"step": "gpu", "label": "Talking shots, reaction shots and repairs",
                "provider": "RunPod rented GPU (" + ", ".join(g["id"] for g in a["gpus"]) + ")", "ready": a["ok"],
                "essential": nd["gpu"], "note": a["reason"] if not a["ok"] else f"${left:.2f} left of the ${cap:.2f} monthly GPU cap"})
    qp = Q.provider(db)
    out.append({"step": "quality", "label": "Quality check", "provider": qp["label"] if qp["ready"] else "Gemini",
                "ready": qp["ready"], "essential": False, "note": qp["note"]})
    s = get_settings()
    node = bool(s.node_bin and shutil.which(s.node_bin))
    out.append({"step": "assembly", "label": "Assembly", "provider": "FFmpeg on the studio server (free)",
                "ready": bool(s.ffmpeg), "essential": True,
                "note": ("FFmpeg is not configured on the studio server" if not s.ffmpeg else
                         "" if node else "Node is missing: the banner and dialogue are left out of the final cut")})
    return out


def blockers(items: list[dict]) -> list[str]:
    """Essential providers that are not ready: the run cannot start (or pauses) until they are."""
    return [f"{p['label']}: {p['note'] or 'not ready'}" for p in items if p["essential"] and not p["ready"]]


# ================================================================== view and routes
def view(db: Session, ep: Episode) -> dict:
    v = stored(db, ep.id)
    items = providers(db, ep)
    return {"status": v.get("status", "off"), "budget_usd": float(v.get("budget_usd") or 0.0), "spent_usd": spent(v),
            "remaining_usd": max(0.0, remaining(v)) if v.get("budget_usd") else 0.0, "step": v.get("step"),
            "step_label": LABEL.get(v.get("step") or "", ""), "message": v.get("message") or "",
            "waiting_for": v.get("waiting_for") or [], "notes": v.get("notes") or [], "use_free_tier": bool(v.get("use_free_tier")),
            "log": list(reversed((v.get("log") or [])[-30:])),
            "actions": [{k: a.get(k) for k in ("what", "usd_max", "usd", "state", "at", "step")}
                        for a in reversed((v.get("actions") or [])[-40:])],
            "redos": v.get("redos") or {}, "max_redos_per_shot": int(get_section(db, "quality").get("max_redos_per_shot", 1)),
            "steps": [{"key": s, "label": LABEL[s]} for s in STEPS], "providers": items, "blockers": blockers(items),
            "started_at": v.get("started_at"), "by": v.get("by")}


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


@router.get("/episodes/{eid}/autopilot")
def get_autopilot(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_usd: float = Field(gt=0, le=MAX_BUDGET)
    confirm_usd: float | None = Field(default=None, ge=0, le=MAX_BUDGET)
    use_free_tier: bool = False


def _confirm(budget: float, confirm: float | None) -> None:
    if confirm is None or abs(float(confirm) - float(budget)) > 0.005:
        raise HTTPException(409, f"confirm your budget of ${budget:.2f} to start: it is the most the whole run may spend "
                                 "(nothing was started)")


@router.post("/episodes/{eid}/autopilot/start")
def start(eid: int, body: StartIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's budget click: the whole run may spend at most this (paid actions start only inside it)."""
    ep = _episode(db, eid)
    _confirm(body.budget_usd, body.confirm_usd)
    v = stored(db, eid)
    if v.get("status") in LIVE:
        raise HTTPException(409, "the autopilot is already running for this episode")
    b = blockers(providers(db, ep))
    if b:
        raise HTTPException(409, "Cannot start: " + "; ".join(b))
    v = {"status": "running", "budget_usd": round(body.budget_usd, 2), "by": user, "started_at": time.time(),
         "use_free_tier": body.use_free_tier, "actions": [], "redos": {}, "prompted": v.get("prompted") or [],
         "log": [], "message": "Starting", "waiting_for": [], "keep_gpu": False}
    _log(v, f"Started by {user} with a budget of ${body.budget_usd:.2f}")
    save(db, eid, v)
    db.add(Event(episode_id=eid, kind="episode", message=f"Make whole episode: started by {user} (budget ${body.budget_usd:.2f})"))
    db.commit()
    tick(db, eid)
    return view(db, ep)


class ResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_usd: float | None = Field(default=None, gt=0, le=MAX_BUDGET)       # a new total budget (confirmed)
    confirm_usd: float | None = Field(default=None, ge=0, le=MAX_BUDGET)


@router.post("/episodes/{eid}/autopilot/resume")
def resume(eid: int, body: ResumeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    if v.get("status") in (None, "off", "finished"):
        raise HTTPException(409, "start the autopilot first")
    if body.budget_usd is not None:
        _confirm(body.budget_usd, body.confirm_usd)
        if body.budget_usd + EPS < spent(v):
            raise HTTPException(409, f"the new budget is below what this run has already used (${spent(v):.2f})")
        v["budget_usd"] = round(body.budget_usd, 2)
        _log(v, f"Budget changed to ${body.budget_usd:.2f} by {user}")
    for a in v.get("actions") or []:
        if a.get("state") == "failed":
            a["state"] = "failed-seen"              # the owner looked at it: not a reason to pause again
    b = blockers(providers(db, ep))
    if b:
        raise HTTPException(409, "Cannot resume: " + "; ".join(b))
    v["status"], v["message"] = "running", "Resumed"
    _log(v, f"Resumed by {user}")
    save(db, eid, v)
    db.commit()
    tick(db, eid)
    return view(db, ep)


@router.post("/episodes/{eid}/autopilot/pause")
def pause_route(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Nothing new starts; a job already running finishes (and turns the GPU off at its end)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if v.get("status") not in LIVE:
        raise HTTPException(409, "the autopilot is not running")
    pause(db, v, f"Paused by {user}")
    save(db, eid, v)
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/autopilot/stop")
def stop(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Stop the run and terminate the rented GPU now (a shot still rendering fails and can be made again)."""
    from . import comfy_session as CS
    ep = _episode(db, eid)
    v = stored(db, eid)
    v["status"], v["keep_gpu"], v["waiting_for"] = "stopped", False, []
    v["message"] = f"Stopped by {user}"
    _log(v, f"Stopped by {user}")
    save(db, eid, v)
    db.commit()
    try:
        CS.stop(db, f"autopilot stopped by {user}")
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f"The autopilot is stopped, but RunPod could not be reached; the GPU session is still open: {str(e)[:200]}")
    return view(db, ep)
