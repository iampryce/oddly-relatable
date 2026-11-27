""""Make this short": the autopilot (autopilot.py) for a narrated short (narrated_short.py). The same loop, budget,
GPU cap and Start / Pause / Resume / Stop routes as "Make whole episode"; only the steps differ. Each step calls the
wizard's own functions (the same checks, estimates and 409s as its buttons; nothing is duplicated here).

  ideas -> script -> scenes (split + prompts) -> voice -> pictures -> motion -> assembly -> publish pack

Owner gates (it STOPS and WAITS, and never approves or picks anything itself, memory "no-self-approvals"): choosing one
of the ideas (or typing one), approving the script, approving a narration take, approving each scene's picture, and
approving the final video. While it waits, the list says what to do and where.

Money: each paid action starts only when its "at most" price fits in what is left of the confirmed budget (and, for the
GPU, in the monthly cap); otherwise the run pauses with a plain message. GPT steps are skipped for the free templates
when there is no OpenAI key (scene prompts) or wait for the owner's own text (idea, script).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import narrated_short as NS
from .models import Episode, Job
from .secrets_store import secret
from .settings_store import get_section

STEPS = ("ideas", "script", "scenes", "voice", "pictures", "motion", "assembly", "publish")
LABEL = {"ideas": "Ideas", "script": "Script", "scenes": "Scenes and prompts", "voice": "Narration voice",
         "pictures": "Scene pictures", "motion": "Motion (Wan 2.2 on the rented GPU)", "assembly": "Timing and assembly",
         "publish": "Publish pack and thumbnail"}
ACTIVE = ("queued", "running")


def _ap():
    from . import autopilot as AP
    return AP


def _busy(db: Session, eid: int, kinds) -> bool:
    return db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(ACTIVE)).first() is not None


def plan_ideas(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    if s.get("idea"):
        return AP._plan()
    out = AP._plan()
    if not (s.get("ideas") or {}).get("items"):
        if secret("openai_api_key", db) and not v.get("openai_no_credit"):
            e = NS.estimates(db, ep, s)["ideas"]
            out["actions"].append(AP._act("short_ideas", "Write 10 ideas (GPT)", e["usd_max"]))
            return out
        out["waiting"].append(AP._wait("Type your own idea (no OpenAI key, so no ideas can be written)", "step 2"))
        return out
    out["waiting"].append(AP._wait("Pick one of the 10 ideas (or type your own)", "step 2"))
    return out


def plan_script(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    if NS.approved_script(s):
        return out
    if not NS.script_versions(s):
        if secret("openai_api_key", db) and not v.get("openai_no_credit"):
            e = NS.estimates(db, ep, s)["script"]
            out["actions"].append(AP._act("short_script", "Write the script (GPT)", e["usd_max"]))
            return out
        out["waiting"].append(AP._wait("Write the narration yourself (no OpenAI key)", "step 3"))
        return out
    out["waiting"].append(AP._wait("Read the script, edit it if you like, and approve it", "step 3"))
    return out


def plan_scenes(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    if not NS.scenes_of(s):
        out["actions"].append(AP._act("short_split", "Split the script into scenes (free)", 0.0))
        return out
    if any(not x.get("picture_prompt") for x in NS.scenes_of(s)):
        if secret("openai_api_key", db) and not v.get("openai_no_credit"):
            e = NS.estimates(db, ep, s)["prompts"]
            out["actions"].append(AP._act("short_prompts", "Write the picture and animation prompts (GPT)", e["usd_max"]))
        else:
            out["actions"].append(AP._act("short_prompts", "Picture and animation prompts from the templates (free)", 0.0,
                                          template=True))
    return out


def plan_voice(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    t = NS.approved_take(s)
    if NS.take_fits(s, t):
        return out
    if _busy(db, ep.id, (NS.JOB_VOICE,)):
        return AP._plan(busy="the narration is being made")
    fitting = [x for x in NS.takes_of(s) if NS.take_fits(s, x)]
    if fitting:
        out["waiting"].append(AP._wait("Listen to the narration and approve a take", "step 5"))
        return out
    if not secret("gemini_api_key", db):
        out["waiting"].append(AP._wait("Upload your own voice (no Gemini key, so no narration can be made)", "step 5"))
        return out
    free = bool(v.get("use_free_tier")) or bool((s.get("voice") or {}).get("use_free_tier"))
    e = NS.voice_estimate(db, s, free)
    if not e or e.get("blocked"):
        out["blocked"] = (e or {}).get("blocked") or "approve the script first"
        return out
    out["actions"].append(AP._act("short_voice", f"Make the narration (Gemini, {e['tier']} tier)", e["usd_max"], free=free))
    return out


def plan_pictures(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    miss = NS.masters_ready(db, s)
    if miss:
        out["waiting"].append(AP._wait("Approve a master for " + ", ".join(miss), "Characters / Cast"))
        return out
    ok, why = AP.pictures_ready(db)
    each = NS.picture_cost(db, 1)["usd"] or 0.0
    for x in NS.scenes_of(s):
        if _busy_scene(db, ep.id, x["n"]):
            continue
        if not x.get("pictures"):
            if not ok:
                out["blocked"] = why
                return out
            out["actions"].append(AP._act("short_picture", f"Scene {x['n']} picture (Nano Banana)", each, n=x["n"]))
    if out["actions"]:
        return out
    if any(_busy_scene(db, ep.id, x["n"]) for x in NS.scenes_of(s)):
        return AP._plan(busy="scene pictures are being made")
    for x in NS.scenes_of(s):
        if not x.get("picture_approved"):
            out["waiting"].append(AP._wait(f"Look at scene {x['n']}'s picture and approve it (or redo it)", "step 6"))
    return out


def _busy_scene(db: Session, eid: int, n: int) -> bool:
    return bool(NS._active(db, eid, (NS.JOB_PICTURE,), n))


def plan_motion(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    if _busy(db, ep.id, (NS.JOB_MOTION,)):
        return AP._plan(busy="the scenes are being animated")
    need = [x["n"] for x in NS.scenes_of(s) if NS.needs_clip(x)]
    if not need:
        return out
    ok, why = AP._gpu_ok(db)
    if not ok:
        out["blocked"] = why
        return out
    e = NS.motion_estimate(db, len(need))
    out["actions"].append(AP._act("short_motion", f"Animate {len(need)} scene(s) (Wan 2.2 on one rented GPU session)",
                                  e["usd_max"], scenes=need))
    return out


def plan_assembly(db: Session, ep: Episode, v: dict) -> dict:
    from .config import get_settings
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    if _busy(db, ep.id, (NS.JOB_ASSEMBLY,)):
        return AP._plan(busy="the short is being put together")
    p = NS.assembly_plan(db, ep, s)
    if p["missing"]:
        out["waiting"].append(AP._wait("Scene(s) " + ", ".join(map(str, p["missing"])) + " need an approved picture", "step 6"))
        return out
    fin = s.get("final") or {}
    cut = next((c for c in fin.get("cuts") or [] if c.get("hash") == p["hash"]), None)
    if cut is None:
        if not get_settings().ffmpeg:
            out["blocked"] = "FFmpeg is not configured on the studio server: the short cannot be put together"
            return out
        out["actions"].append(AP._act("short_assemble", "Put the short together (free)", 0.0))
    elif fin.get("approved") != cut["id"]:
        out["waiting"].append(AP._wait("Watch the final video and approve it", "step 8"))
    return out


def plan_publish(db: Session, ep: Episode, v: dict) -> dict:
    AP = _ap()
    s = NS.stored(db, ep.id)
    out = AP._plan()
    pub = s.get("publish") or {}
    if not pub.get("titles"):
        if secret("openai_api_key", db) and not v.get("openai_no_credit"):
            e = NS.estimates(db, ep, s)["publish"]
            out["actions"].append(AP._act("short_publish", "Write the titles, description, hashtags and thumbnail prompt (GPT)",
                                          e["usd_max"]))
            return out
        out["notes"].append("No OpenAI key: write the titles and description yourself in step 9.")
    if _busy(db, ep.id, (NS.JOB_THUMB,)):
        return AP._plan(busy="the thumbnail is being made")
    if not pub.get("thumbnails"):
        ok, why = AP.pictures_ready(db)
        if ok and not NS.masters_ready(db, s):
            out["actions"].append(AP._act("short_thumbnail", "Make the thumbnail (Nano Banana)", NS.picture_cost(db, 1)["usd"] or 0.0))
        else:
            out["notes"].append(f"The thumbnail was not made: {why or 'a character has no approved master'}")
    return out


PLANNERS = {"ideas": plan_ideas, "script": plan_script, "scenes": plan_scenes, "voice": plan_voice,
            "pictures": plan_pictures, "motion": plan_motion, "assembly": plan_assembly, "publish": plan_publish}


# ================================================================== runners: the wizard's own functions
def run_ideas(db, ep, a, user, v):
    return NS.write_ideas(db, ep, a["usd"], user)


def run_script(db, ep, a, user, v):
    return NS.write_script(db, ep, a["usd"], "", user)


def run_split(db, ep, a, user, v):
    s = NS.stored(db, ep.id)
    NS.split_into_scenes(s)
    NS.save(db, ep.id, s)
    db.commit()
    return {"usd": 0.0}


def run_prompts(db, ep, a, user, v):
    return NS.write_prompts(db, ep, a["usd"], bool(a["args"].get("template")), user)


def run_voice(db, ep, a, user, v):
    s = NS.stored(db, ep.id)
    vo = s.get("voice") or {}
    cfg = get_section(db, "short")
    j = NS.make_voice(db, ep, NS.VoiceIn(voice=vo.get("voice") or cfg.get("voice") or NS.tts.DEFAULT_VOICE,
                                         style=vo.get("style") or cfg.get("style") or NS.tts.DEFAULT_STYLE,
                                         use_free_tier=bool(a["args"].get("free")), confirm_usd=a["usd"]), user)
    return {"job_id": j.id}


def run_picture(db, ep, a, user, v):
    return {"job_id": NS.make_picture(db, ep, int(a["args"]["n"]), a["usd"], None, user).id}


def run_motion(db, ep, a, user, v):
    j = NS.start_motion(db, ep, NS.MotionIn(scenes=a["args"]["scenes"], confirm_usd=a["usd"]), user)
    return {"job_id": j.id}


def run_assemble(db, ep, a, user, v):
    return {"job_id": NS.start_assembly(db, ep, user).id}


def run_publish(db, ep, a, user, v):
    return NS.write_publish(db, ep, a["usd"], user)


def run_thumbnail(db, ep, a, user, v):
    return {"job_id": NS.make_thumbnail(db, ep, a["usd"], user).id}


RUN = {"short_ideas": run_ideas, "short_script": run_script, "short_split": run_split, "short_prompts": run_prompts,
       "short_voice": run_voice, "short_picture": run_picture, "short_motion": run_motion, "short_assemble": run_assemble,
       "short_publish": run_publish, "short_thumbnail": run_thumbnail}


def providers(db: Session, ep: Episode) -> list[dict]:
    return NS.providers(db, ep, NS.stored(db, ep.id))
