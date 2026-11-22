"""Shot comparison (owner request 2026-11-21, Production > Motion Model Comparison): AI video models against the rig
animator on single lines of a real episode.

Inputs are ONLY the studio's own approved art: the speaking character's approved neutral pose on the episode's (or the
scene's) approved set plate, composed locally into one first frame; and the line's own recorded audio, cut from the
episode's recording. Frames or stills from the uploaded reference video never exist after analysis and are never used.
The action description is written from the video notes' fixed-list words (staging and beats) and is editable.

Flow: plan (free, a local job: first frame, audio cut, rig render of the same line) -> the page shows, per model, the
exact request (prompt, the image and audio sent), the estimated cost and the experimental budget's running total ->
nothing is sent until the owner clicks Run for that model -> results side by side with the rig render, with the actual
cost per clip and per second. Our audio is never replaced by a model's: every output gets the original line audio,
and its length is checked to be the line's length within one frame.

Models (fal.ai, checked 2026-11-21; both pages say "Commercial use permitted (Partner)"):
- Kling 2.6 Pro image-to-video, audio off: $0.07 per second, 5 or 10 s clips (cut to the line afterwards).
- Kling AI Avatar v2 Standard: image + OUR line audio -> a talking clip as long as the audio; $0.0562 per second.

Self-hosted models (GPU_MODELS; proof of concept, docs/GPU-INFRASTRUCTURE.md §16) run on our own GPU worker (gpu.py):
the same plan, the same first frames and line audio, the same per-run approval, our audio laid under the result and
the same length check. They are sent as files to the worker (no public URL needed) and capped by the monthly GPU cap,
not by fal.ai's budget. A model whose ComfyUI workflow is not pinned yet (gpu_workflows/<name>.json) cannot run.
"""
from __future__ import annotations

import json
import math
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, CharacterAsset, Episode, Event, Setting, StoryboardScene

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
ROW = "_shot_compare"
FPS = 30
W, H = 720, 1280

MODELS = {
    "kling-2.6-pro-i2v": {
        "endpoint": "fal-ai/kling-video/v2.6/pro/image-to-video", "kind": "i2v", "rate": 0.07,
        "label": "Kling 2.6 Pro image-to-video (audio off)",
        "why": "a strong current image-to-video model; with audio off it is the cheapest Kling Pro tier",
        "price": "$0.07 per second with audio off; 5 or 10 s clips", "licence": "Commercial use permitted (fal Partner model)",
        "framing": "wide"},
    "kling-avatar-v2-standard": {
        "endpoint": "fal-ai/kling-video/ai-avatar/v2/standard", "kind": "avatar", "rate": 0.0562,
        "label": "Kling AI Avatar v2 Standard (our line audio)",
        "why": "takes an image AND our recorded line, so the mouth follows our audio; the output is as long as the audio; "
               "the page lists cartoons and stylized characters",
        "price": "$0.0562 per second of audio", "licence": "Commercial use permitted (fal Partner model)",
        "framing": "medium"},   # a talking-avatar model: head and upper body fill the frame (owner decision 2026-11-21)
}
# Self-hosted (GPU worker). gpu_seconds_per_second: GPU time per second of line, an ESTIMATE from Wan's published H100
# table at default steps (§14.5: about 330 s per 5 s clip at 480p); the proof of concept measures the real figure.
GPU_MODELS = {
    "infinitetalk-480p": {
        "backend": "gpu", "kind": "avatar", "workflow": "infinitetalk-480p", "gpu_seconds_per_second": 66.0,
        "label": "InfiniteTalk 480p (self-hosted, our line audio)", "short": "InfiniteTalk",
        "why": "open model (Apache-2.0) built on Wan 2.1 I2V-14B: image + our recorded line, the mouth follows the audio",
        "price": "GPU time on our worker (rented per second, or our own machine)",
        "licence": "Apache-2.0 (MeiGen-AI InfiniteTalk; base Wan 2.1 I2V-14B-480P, Apache-2.0)", "framing": "medium"},
    "wan-2.2-s2v-480p": {
        "backend": "gpu", "kind": "avatar", "workflow": "wan-2.2-s2v-480p", "gpu_seconds_per_second": 66.0,
        "label": "Wan 2.2 S2V-14B 480p (self-hosted, our line audio)", "short": "Wan S2V",
        "why": "Wan's own speech-to-video model (Apache-2.0): image + our recorded line",
        "price": "GPU time on our worker (rented per second, or our own machine)",
        "licence": "Apache-2.0 (Wan-AI Wan2.2-S2V-14B)", "framing": "medium"},
    "latentsync-1.6": {
        "backend": "gpu", "kind": "dub", "needs": "kling-2.6-pro-i2v", "workflow": "latentsync-1.6", "gpu_seconds_per_second": 10.0,
        "label": "LatentSync 1.6 over the Kling i2v clip (self-hosted, our line audio)", "short": "LatentSync",
        "why": "open lip-sync model (Apache-2.0): re-syncs the mouth of this line's Kling image-to-video clip to our audio",
        "price": "GPU time on our worker (rented per second, or our own machine)",
        "licence": "Apache-2.0 (ByteDance LatentSync)", "framing": "wide"},
}
ALL_MODELS = {**MODELS, **GPU_MODELS}
WORKFLOW_DIR = Path(__file__).resolve().parent / "gpu_workflows"
FRAMINGS = ("wide", "medium")
NEGATIVE = "realistic, photo, 3d render, extra characters, text, logo, watermark, deformed, blur"


# ------------------------------------------------------------------ records
def records(db: Session) -> dict:
    row = db.get(Setting, ROW)
    return dict(row.value) if row else {}


def save(db: Session, recs: dict) -> None:
    row = db.get(Setting, ROW)
    if row:
        row.value = recs
    else:
        db.add(Setting(key=ROW, value=recs))


def estimate(model: str, seconds: float, db: Session | None = None) -> dict:
    if model in GPU_MODELS:
        from . import gpu
        price, src = gpu.planned_price(db) if db is not None else (0.0, "no price yet")
        gs = GPU_MODELS[model]["gpu_seconds_per_second"] * max(1.0, seconds)
        return {"billed_seconds": round(gs), "gpu_seconds": round(gs), "usd": round(gs * price / 3600, 4), "price_per_hour": price,
                "note": f"GPU time estimate (published H100 timings, default steps; measured in the proof of concept); {src}"}
    m = MODELS[model]
    if m["kind"] == "i2v":
        billed = 5 if seconds <= 5 else 10
        note = "" if seconds <= 10 else f"the line runs {seconds:.1f} s: the 10 s clip's last frame is held to the end"
    else:
        billed, note = math.ceil(seconds), ""
    return {"billed_seconds": billed, "usd": round(m["rate"] * billed, 4), "note": note}


def prompt_for(model: str, action: str) -> str:
    if ALL_MODELS[model]["kind"] == "i2v":
        return ("2D flat cartoon animation, static camera. The character in the image " + action.strip().rstrip(".") +
                ". Keep the character's design, colours and proportions and the background exactly as in the image; "
                "no new characters, no text, no camera move.")
    return (action.strip().rstrip(".") + ". Keep the character's flat 2D design and the background exactly as in the "
            "image; the mouth follows the audio.")


def workflow_of(model: str) -> tuple[dict, str] | None:
    """The pinned ComfyUI workflow of a self-hosted model and its SHA-256, or None while it is not pinned."""
    f = WORKFLOW_DIR / f"{GPU_MODELS[model]['workflow']}.json"
    if not f.is_file():
        return None
    wf = json.loads(f.read_text())
    import hashlib
    return wf, hashlib.sha256(json.dumps(wf, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def gpu_blocked(p: dict, model: str) -> str:
    """Why a self-hosted model cannot run for this plan now ('' when it can, apart from the GPU's own availability)."""
    m = GPU_MODELS[model]
    if workflow_of(model) is None:
        return f"its ComfyUI workflow is not pinned yet (gpu_workflows/{m['workflow']}.json)"
    if m["kind"] == "dub":
        r = (p.get("results") or {}).get(m["needs"]) or {}
        if r.get("status") != "done" or r.get("binned") or not r.get("asset_id"):
            return f"it needs this line's {MODELS[m['needs']]['label']} clip first"
    return ""


def gpu_params(model: str, p: dict) -> dict:
    from .gpu import seed_for
    return {"seconds": p["seconds"], "fps": 25, "prompt": prompt_for(model, p["action"]), "negative": NEGATIVE,
            "seed": seed_for(p["id"] + model)}


def gpu_job_preview(model: str, p: dict) -> dict:
    """What the worker is sent (the files by name: they travel in the request, never by URL)."""
    m = GPU_MODELS[model]
    wf = workflow_of(model)
    return {"kind": "comfyui-workflow", "workflow": m["workflow"], "workflow_sha256": wf[1] if wf else None,
            "params": gpu_params(model, p), "inputs": gpu_input_names(model)}


def gpu_input_names(model: str) -> list[str]:
    return ["video.mp4", "audio.wav"] if GPU_MODELS[model]["kind"] == "dub" else ["image.png", "audio.wav"]


def request_for(model: str, action: str, image_url: str, audio_url: str, seconds: float) -> dict:
    """The exact JSON body sent to fal (shown to the owner before Run)."""
    if MODELS[model]["kind"] == "i2v":
        return {"prompt": prompt_for(model, action), "start_image_url": image_url,
                "duration": str(estimate(model, seconds)["billed_seconds"]), "generate_audio": False, "negative_prompt": NEGATIVE}
    return {"image_url": image_url, "audio_url": audio_url, "prompt": prompt_for(model, action)}


# ------------------------------------------------------------------ the line and its words-only action
def _episode_line(db: Session, eid: int, scene_id: int, line: int):
    ep = db.get(Episode, eid)
    sc = db.get(StoryboardScene, scene_id)
    if ep is None or sc is None or sc.episode_id != ep.id or not 0 <= line < len(sc.lines or []):
        raise HTTPException(404, "no such line")
    return ep, sc, sc.lines[line]


# The tones an action may use (a fixed list: the writer must pick from it, the phrase matcher uses it too).
TONES = ("pompous", "insulting", "pleading", "shocked", "sarcastic", "smug", "deadpan", "matter-of-fact", "nervous",
         "cheerful", "angry", "irritated", "sad", "puzzled", "excited", "mocking", "proud", "defensive", "tender",
         "exasperated", "whispering", "triumphant")
# Phrase matcher (the fallback when no text provider is set or it fails). Whole words and phrases only; a cue that
# starts with "^" counts only at the start of the line or of a sentence ("Sure, ..." is sarcastic; "not sure, ..." is
# not; "I, Mortimer" is pompous; "hi, " is not).
TONE_CUES = (
    ("pompous", ("hereby", "bequeath", "magnificent", "as you all know", "henceforth", "my dear", "allow me",
                 "esteemed", "distinguished", "^i,", "^indeed")),
    ("insulting", ("idiot", "fool", "useless", "pathetic", "stupid", "loser", "moron", "disgrace", "worthless",
                   "not a penny", "gets nothing", "nothing.")),
    ("pleading", ("please", "i beg", "just this once", "you have to", "can't you")),
    ("shocked", ("no way", "you're joking", "are you serious", "^what?!", "^excuse me?")),
    ("sarcastic", ("oh great", "how lovely", "of course you did", "^sure,", "^brilliant.", "^wonderful.")),
    ("smug", ("i told you", "as expected", "^obviously", "^naturally")),
    ("deadpan", ("^fine.", "^okay.", "^right.", "^cool.")),
)
EXPRESSION_TONE = {"smug": "smug", "deadpan": "deadpan", "angry": "angry", "annoyed": "irritated", "shocked": "shocked",
                   "worried": "nervous", "sad": "sad", "happy": "cheerful", "laughing": "cheerful", "confused": "puzzled",
                   "proud": "proud", "excited": "excited", "pleading": "pleading", "nervous": "nervous", "irritated": "irritated"}


def _cue_regex(cue: str):
    import re
    if cue.startswith("^"):
        return re.compile(r"(?:^|[.!?]\s+)" + re.escape(cue[1:]) + (r"(?!\w)" if cue[-1].isalnum() else ""))
    return re.compile(r"(?<!\w)" + re.escape(cue) + (r"(?!\w)" if cue[-1].isalnum() else ""))


_CUES = [(name, [_cue_regex(c) for c in cues]) for name, cues in TONE_CUES]


def tone_of(text: str, expression: str | None, emotion: str | None) -> str:
    """The phrase matcher: tones from whole-word cues in the line, then from its mood; a sensible tone when nothing
    matches (exclaiming, puzzled for a question, matter-of-fact otherwise)."""
    t = (text or "").strip().lower()
    tones = [name for name, rx in _CUES if any(r.search(t) for r in rx)]
    for e in (expression, emotion):
        x = EXPRESSION_TONE.get((e or "").lower())
        if x and x not in tones:
            tones.append(x)
    if not tones:
        s = (text or "").strip()
        tones = ["excited"] if s.endswith("!") else ["puzzled"] if s.endswith("?") else ["matter-of-fact"]
    return ", ".join(tones[:3])


def action_from_notes(db: Session, ep: Episode, ln: dict) -> str:
    """The action for a line, filled in automatically and editable: the video notes' fixed-list words for the line's
    time (pose, emotion, the speaker's own beats), plus the line's own words and mood (tone cues)."""
    from . import beats as BT
    from . import video_notes as VN
    from .reference_plan import effective
    tr = ep.audio_transcript or {}
    sp, acts = {}, []
    if "start" in ln and (tr.get("video_notes") or {}).get("ranges"):
        r = VN.for_line(effective(tr), ln) or {}
        sp = next((ro for ro in r.get("roles", []) if ro.get("role") == "speaker"), {})
        names = BT.names_of(db, tr)
        who = {v: k for k, v in (tr.get("person_map") or {}).items()}
        own = [b for b in (tr.get("video_notes") or {}).get("beats") or []
               if ln["start"] <= b["t"] < ln["end"] and who.get(b["person"]) == ln.get("speaker") and b["type"] in BT.SUPPORTED]
        acts = [BT.describe(b, names).split(" ", 1)[1].rsplit(" (", 1)[0] for b in own]
    tone = tone_of(ln.get("text", ""), ln.get("expression"), sp.get("emotion"))
    words = (ln.get("text") or "").strip()
    quote = (words[:90] + "…") if len(words) > 90 else words
    where = f"{sp['pose']}, " if sp.get("pose") else ""
    return (f"is {where}delivering the line in a {tone} way (\"{quote}\")" + (f"; {', '.join(acts)}" if acts else "")
            + ", with matching facial expression and natural head and hand movements")


WRITER_SYSTEM = ("You direct the acting of ONE line in an original adult 2D cartoon. Reply with one JSON object only.")
WRITER_PROMPT = ("The line: {speaker}: \"{text}\"\nBefore it: {before}\nAfter it: {after}\nStaging from the reference notes "
                 "(fixed words): {notes}\nRecorded mood: {mood}\n\nChoose 1 to 3 tones for how the line is delivered, ONLY "
                 "from: {tones}. Then write ONE sentence (at most 35 words) of what the character physically does while "
                 "saying it (face, head, hands, posture). No names of real people, no camera moves, no on-screen text. "
                 'JSON: {{"tone": ["..."], "action": ""}}')
TEXT_PRICES = {"anthropic": (2.00, 10.00), "openai": (0.40, 1.60)}     # USD per million tokens (list prices, estimate)


def writer_configured(db: Session) -> bool:
    from .settings_store import get_section
    return get_section(db, "text").get("provider", "none") not in ("none", "")


def writer_cost(db: Session, prompt: str) -> dict:
    """An estimate of one writer call (text providers do not report usage here): about 4 characters per token. With a
    fallback provider set, the higher of the two prices (either may write it), and both are named."""
    from .settings_store import get_section
    cfg = get_section(db, "text")
    prov, fb = cfg.get("provider", "none"), cfg.get("fallback", "none")
    tin, tout = (len(WRITER_SYSTEM) + len(prompt)) / 4, 120
    price = lambda p: round((tin * TEXT_PRICES[p][0] + tout * TEXT_PRICES[p][1]) / 1e6, 5) if p in TEXT_PRICES else 0.0
    usd = max(price(prov), price(fb) if fb not in ("none", "", prov) else 0.0)
    note = "" if prov in TEXT_PRICES else "no per-call API cost for this provider"
    if fb not in ("none", "", prov):
        note = f"estimate covers {prov} or its fallback {fb}"
    return {"provider": prov, "usd": usd, "note": note}


def write_action(db: Session, pid: str, ep: Episode, sc: StoryboardScene, log=print) -> None:
    """With a text provider in Settings: the line's tone and action written from its text, its neighbours and the
    video notes; the tone only from TONES. Falls back to the phrase matcher (with a note) if the call fails or gives
    nothing usable. Never overwrites the owner's own edit."""
    from . import video_notes as VN
    from .providers import ProviderError, ProviderNotConfigured, text_provider
    from .reference_plan import effective
    from .settings_store import get_section
    recs = records(db)
    p = recs[pid]
    if p.get("action_source") == "your edit" or not writer_configured(db):
        return
    lines = sc.lines or []
    i = p["line"]
    near = lambda j: f"{lines[j].get('speaker')}: {lines[j].get('text')}" if 0 <= j < len(lines) else "(none)"
    ln = lines[i]
    tr = ep.audio_transcript or {}
    r = VN.for_line(effective(tr), ln) if (tr.get("video_notes") or {}).get("ranges") else None
    prompt = WRITER_PROMPT.format(speaker=ln.get("speaker"), text=ln.get("text", "")[:400], before=near(i - 1)[:300],
                                  after=near(i + 1)[:300], notes=VN.describe(r) if r else "none",
                                  mood=ln.get("expression") or "unknown", tones=", ".join(TONES))
    cost = writer_cost(db, prompt)
    try:
        ans = text_provider(get_section(db, "text")).complete_json(WRITER_SYSTEM, prompt)
        tones = [t for t in (ans.get("tone") if isinstance(ans, dict) and isinstance(ans.get("tone"), list) else [])
                 if isinstance(t, str) and t.strip().lower() in TONES][:3]
        act = str((ans or {}).get("action") or "").strip().replace("\n", " ")[:300] if isinstance(ans, dict) else ""
        if not tones or len(act) < 8:
            raise ValueError("no tone from the list or no action")
        tone = ", ".join(t.strip().lower() for t in tones)
        quote = (ln.get("text") or "")[:90]
        update = {"tone": tone, "action": f"delivers the line in a {tone} way (\"{quote}\"): {act}",
                  "action_source": "writer", "action_cost": cost, "action_note": ""}
    except (ProviderError, ProviderNotConfigured, ValueError, TypeError, KeyError) as e:
        update = {"action_source": "phrase matcher", "action_cost": cost,
                  "action_note": f"the writer could not be used ({str(e)[:120]}): the phrase matcher's tone is used"}
        log(update["action_note"])
    # re-read just before saving: an edit the owner made while the writer was working is kept
    db.expire_all()
    recs = records(db)
    if recs[pid].get("action_source") == "your edit":
        return
    recs[pid].update(update)
    save(db, recs)
    db.commit()


@router.get("/motion/shot/options")
def options(episode_id: int, db: Session = Depends(get_db)):
    from . import fal
    ep = db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(404, "episode not found")
    chars = {c.key: c for c in db.query(Character).all()}
    lines = []
    for sc in sorted(ep.scenes, key=lambda s: s.position):
        for i, ln in enumerate(sc.lines or []):
            c = chars.get(ln.get("speaker"))
            ok = bool(c and (c.expressions or {}).get("neutral"))
            lines.append({"scene_id": sc.id, "scene": sc.position, "line": i, "speaker": ln.get("speaker"), "text": ln.get("text"),
                          "seconds": round(float(ln.get("end", 0)) - float(ln.get("start", 0)), 2) if "start" in ln else None,
                          "ready": ok and "start" in ln, "why_not": None if ok else "the speaker has no approved neutral pose",
                          "action": action_from_notes(db, ep, ln)})
    from . import gpu
    led = fal.spent(db)
    return {"episode": {"id": ep.id, "title": ep.title, "set_id": ep.set_id}, "lines": lines,
            "models": [{"id": k, **{x: m[x] for x in ("label", "why", "price", "licence")}} for k, m in MODELS.items()],
            "gpu_models": [{"id": k, "kind": m["kind"], "short": m["short"], "framing": m["framing"], "pinned": workflow_of(k) is not None,
                            **{x: m[x] for x in ("label", "why", "price", "licence")}} for k, m in GPU_MODELS.items()],
            "gpu": gpu.availability(db), "spent_usd": round(led["total"], 2), "budget_usd": fal.budget(db)}


class PlanIn(BaseModel):
    episode_id: int
    scene_id: int
    line: int = Field(ge=0)
    action: str = Field(min_length=3, max_length=400)


@router.post("/motion/shot/plan")
def make_plan(body: PlanIn, db: Session = Depends(get_db)):
    """Free: queue the local preparation (first frame from approved art, the line's audio, the rig render)."""
    from .queue import enqueue
    ep, sc, ln = _episode_line(db, body.episode_id, body.scene_id, body.line)
    if "start" not in ln or ep.source != "audio":
        raise HTTPException(409, "the comparison uses a recorded line (an audio-first episode)")
    pid = uuid.uuid4().hex[:10]
    recs = records(db)
    recs[pid] = {"id": pid, "episode_id": ep.id, "scene_id": sc.id, "line": body.line, "speaker": ln.get("speaker"),
                 "text": ln.get("text"), "start": float(ln["start"]), "end": float(ln["end"]),
                 "seconds": round(float(ln["end"]) - float(ln["start"]), 3), "action": body.action.strip(),
                 "status": "preparing", "created": time.time(), "results": {}}
    save(db, recs)
    job = enqueue(db, "shot_prepare", episode_id=ep.id, payload={"pid": pid})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Shot comparison planned for scene {sc.position}, line {body.line + 1} (free preparation)"))
    db.commit()
    return {"plan": view(db, recs[pid]), "job_id": job.id}


def framing_of(p: dict, model: str) -> str:
    """The first frame a model gets: the owner's choice for this plan, else the model's default."""
    return (p.get("framing") or {}).get(model) or ALL_MODELS[model]["framing"]


def view(db: Session, p: dict) -> dict:
    from . import fal
    from .comparison import public_url
    from .models import Asset
    from .storage import storage
    url = lambda aid: storage().url(db.get(Asset, aid).storage_key) if aid and db.get(Asset, aid) else None
    out = {**p, "frame_url": url(p.get("frame_asset_id")), "audio_url": url(p.get("audio_asset_id")),
           "rig_url": url(p.get("rig_asset_id"))}
    frames = p.get("frame_assets") or {"wide": p.get("frame_asset_id")}
    out["frame_urls"] = {f: url(a) for f, a in frames.items()}
    if p.get("status") == "ready":
        sent_img = public_url(storage().url(db.get(Asset, p["frame_asset_id"]).storage_key, 7200)) if p.get("frame_asset_id") else ""
        sent_aud = public_url(storage().url(db.get(Asset, p["audio_asset_id"]).storage_key, 7200)) if p.get("audio_asset_id") else ""
        out["requests"] = [{"model": k, "label": m["label"], "endpoint": m["endpoint"], "price": m["price"],
                            "estimate": estimate(k, p["seconds"]), "framing": framing_of(p, k),
                            "frame_url": out["frame_urls"].get(framing_of(p, k)),
                            "body": request_for(k, p["action"], f"<the {framing_of(p, k)} first frame shown>", "<the line audio shown above>", p["seconds"]),
                            "sends": [f"the {framing_of(p, k)} first frame (approved set + approved neutral pose)"]
                                     + (["the line's own recorded audio"] if m["kind"] == "avatar" else []),
                            "result": p["results"].get(k)} for k, m in MODELS.items()]
        out["requests"] += [{"model": k, "label": m["label"], "backend": "gpu", "endpoint": f"our GPU worker: workflow {m['workflow']}",
                             "price": m["price"], "estimate": estimate(k, p["seconds"], db), "framing": framing_of(p, k),
                             "frame_url": out["frame_urls"].get(framing_of(p, k)) if m["kind"] != "dub" else None,
                             "body": gpu_job_preview(k, p), "blocked": gpu_blocked(p, k),
                             "sends": ([f"the {framing_of(p, k)} first frame (approved set + approved neutral pose)"] if m["kind"] != "dub"
                                       else [f"this line's {MODELS[m['needs']]['label']} clip (made from our own art)"])
                                      + ["the line's own recorded audio"],
                             "result": p["results"].get(k)} for k, m in GPU_MODELS.items()]
        out["urls_ok"] = bool(sent_img.startswith("http") and sent_aud.startswith("http"))
    from .bin import hidden_ids
    gone = hidden_ids(db, "clip")
    for k, r in (p.get("results") or {}).items():
        if r.get("asset_id") and r["asset_id"] not in gone:
            r["url"] = url(r["asset_id"])
        elif r.get("asset_id"):
            r["binned"] = True
    led = fal.spent(db)
    out["spent_usd"], out["budget_usd"] = round(led["total"], 2), fal.budget(db)
    return out


@router.get("/motion/shot")
def list_plans(db: Session = Depends(get_db)):
    return {"plans": [view(db, p) for p in sorted(records(db).values(), key=lambda p: -p.get("created", 0))[:10]]}


class FramingIn(BaseModel):
    model: str
    framing: str


@router.put("/motion/shot/{pid}/framing")
def set_framing(pid: str, body: FramingIn, db: Session = Depends(get_db)):
    """Free: which first frame a model gets (wide: the whole set; medium: head and upper body filling the frame)."""
    recs = records(db)
    p = recs.get(pid)
    if not p:
        raise HTTPException(404, "no such plan")
    if body.model not in ALL_MODELS or body.framing not in FRAMINGS:
        raise HTTPException(422, f"framing must be one of {', '.join(FRAMINGS)}")
    if (p["results"].get(body.model) or {}).get("status") in ("queued", "running"):
        raise HTTPException(409, "not while that model is running")
    p["framing"] = {**(p.get("framing") or {}), body.model: body.framing}
    save(db, recs)
    db.commit()
    return view(db, p)


class RunIn(BaseModel):
    model: str


@router.post("/motion/shot/{pid}/run")
def run_model(pid: str, body: RunIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's approval of ONE paid request, after seeing its prompt, images and estimate."""
    from . import fal
    from .providers import ProviderError
    from .queue import enqueue
    p = records(db).get(pid)
    if not p:
        raise HTTPException(404, "no such plan")
    if body.model not in ALL_MODELS:
        raise HTTPException(422, "unknown model")
    if p.get("status") != "ready":
        raise HTTPException(409, "the plan is not ready yet (its free preparation is still running or failed)")
    if (p["results"].get(body.model) or {}).get("status") in ("queued", "running", "done"):
        raise HTTPException(409, "already queued, running or done")
    est = estimate(body.model, p["seconds"], db)
    if body.model in GPU_MODELS:
        why = gpu_blocked(view(db, p), body.model)
        if why:
            raise HTTPException(409, f"{GPU_MODELS[body.model]['label']}: {why}")
        check_gpu(db)
    else:
        if not view(db, p).get("urls_ok"):
            raise HTTPException(409, "fal.ai fetches the first frame and the line audio from the studio: set PUBLIC_URL on the server first")
        check_cap(db, est["usd"])
    job = approve(db, pid, body.model, user)
    db.commit()
    return {"job_id": job.id, "estimate": est}


def pending_usd(db: Session) -> float:
    """Approved fal.ai runs not charged yet (queued or running): they count against fal.ai's cap. (Self-hosted clips
    are covered by the GPU session's reservation instead.)"""
    return round(sum(r.get("estimated_usd") or 0 for q in records(db).values() for k, r in (q.get("results") or {}).items()
                     if k in MODELS and r.get("status") in ("queued", "running")), 4)


def check_gpu(db: Session) -> dict:
    from . import gpu
    try:
        return gpu.check_can_run(db)
    except gpu.GpuUnavailable as e:
        raise HTTPException(409, f"Self-hosted GPU: {e}")


def check_cap(db: Session, usd: float) -> None:
    from . import fal
    from .providers import ProviderError
    pending = pending_usd(db)
    try:
        fal.check_budget(db, usd + pending)
    except ProviderError as e:
        raise HTTPException(409, str(e) + (f" (including ${pending:.2f} already approved and not yet run)" if pending else ""))


def approve(db: Session, pid: str, model: str, user: str):
    """Record the owner's approval of one clip and queue it (the caller checked the cap for everything it approves)."""
    from .queue import enqueue
    recs = records(db)
    p = recs[pid]
    est = estimate(model, p["seconds"], db)
    p["results"][model] = {"status": "queued", "estimated_usd": est["usd"], "approved_by": user}
    save(db, recs)
    job = enqueue(db, "shot_generate", episode_id=p["episode_id"],
                  payload={"pid": pid, "model": model, "backend": ALL_MODELS[model].get("backend", "fal")})
    db.add(Event(episode_id=p["episode_id"], kind="episode", message=f"Shot comparison: {ALL_MODELS[model]['label']} approved by {user} "
                                                                    f"(estimated ${est['usd']:.2f})"))
    return job


# ------------------------------------------------------------------ batch mode (one screen, one confirm)
def plan_for_line(db: Session, ep: Episode, sc: StoryboardScene, line: int) -> tuple[dict, bool]:
    """The episode line's plan: the existing one (not failed), else a new one with its free preparation queued."""
    from .queue import enqueue
    recs = records(db)
    for p in sorted(recs.values(), key=lambda p: -p.get("created", 0)):
        if p["episode_id"] == ep.id and p["scene_id"] == sc.id and p["line"] == line and p.get("status") != "failed":
            return p, False
    ln = sc.lines[line]
    if "start" not in ln:
        raise HTTPException(409, "the comparison uses recorded lines (an audio-first episode)")
    pid = uuid.uuid4().hex[:10]
    recs[pid] = {"id": pid, "episode_id": ep.id, "scene_id": sc.id, "line": line, "speaker": ln.get("speaker"),
                 "text": ln.get("text"), "start": float(ln["start"]), "end": float(ln["end"]),
                 "seconds": round(float(ln["end"]) - float(ln["start"]), 3), "action": action_from_notes(db, ep, ln),
                 "tone": tone_of(ln.get("text", ""), ln.get("expression"), None), "action_source": "phrase matcher",
                 "status": "preparing", "created": time.time(), "results": {}}
    save(db, recs)
    enqueue(db, "shot_prepare", episode_id=ep.id, payload={"pid": pid})
    return recs[pid], True


class LineRef(BaseModel):
    scene_id: int
    line: int = Field(ge=0)


class BatchPlanIn(BaseModel):
    episode_id: int
    lines: list[LineRef] = Field(default_factory=list, max_length=60)


@router.post("/motion/shot-batch/plan")
def batch_plan(body: BatchPlanIn, db: Session = Depends(get_db)):
    """Free and automatic: called as lines are ticked; one plan per line (an existing one is reused), its first frames,
    audio cut and rig render prepared by a local job. The action is filled in from the notes and the line itself."""
    ep = db.get(Episode, body.episode_id)
    if ep is None or ep.source != "audio":
        raise HTTPException(404, "an audio-first episode is needed")
    made = 0
    for x in body.lines:
        _, sc, _ = _episode_line(db, ep.id, x.scene_id, x.line)
        _, new = plan_for_line(db, ep, sc, x.line)
        made += new
    db.commit()
    return {"queued": made, **batch_view(db, ep.id)}


def batch_view(db: Session, eid: int) -> dict:
    """The episode's latest plan per line (progress, actions, first frames, results) and the budget."""
    from . import fal, gpu
    latest: dict[tuple, dict] = {}
    for p in sorted(records(db).values(), key=lambda p: p.get("created", 0)):
        if p["episode_id"] == eid:
            latest[(p["scene_id"], p["line"])] = p
    led = fal.spent(db)
    plans = [view(db, p) for p in latest.values()]
    return {"plans": plans, "ready": sum(1 for p in plans if p["status"] == "ready"),
            "preparing": sum(1 for p in plans if p["status"] == "preparing"),
            "spent_usd": round(led["total"], 4), "pending_usd": pending_usd(db), "budget_usd": fal.budget(db),
            "gpu": gpu.availability(db)}


@router.get("/motion/shot-batch")
def get_batch(episode_id: int, db: Session = Depends(get_db)):
    return batch_view(db, episode_id)


class ActionIn(BaseModel):
    action: str = Field(min_length=3, max_length=400)


@router.put("/motion/shot/{pid}/action")
def set_action(pid: str, body: ActionIn, db: Session = Depends(get_db)):
    """Free: the owner's edit of one line's action (used by every model's request for that line)."""
    recs = records(db)
    p = recs.get(pid)
    if not p:
        raise HTTPException(404, "no such plan")
    if any((r or {}).get("status") in ("queued", "running") for r in p["results"].values()):
        raise HTTPException(409, "not while a clip of this line is running")
    p["action"] = body.action.strip()
    p["action_source"] = "your edit"          # never overwritten by the writer
    save(db, recs)
    db.commit()
    return view(db, p)


class BatchIn(BaseModel):
    plan_ids: list[str] = Field(default_factory=list, max_length=60)
    models: list[str] = Field(default_factory=list, max_length=4)
    framing: dict[str, str] = Field(default_factory=dict)     # optional override per model, for every selected line
    confirm: bool = False
    expected_usd: float | None = None                          # the total the owner saw (refused if it changed)


def _batch_clips(db: Session, body: BatchIn) -> tuple[list[tuple[str, str, float]], list[str]]:
    recs = records(db)
    paid = [m for m in body.models if m in ALL_MODELS]
    bad = [m for m in body.models if m not in ALL_MODELS and m != "rig"]
    if bad:
        raise HTTPException(422, f"unknown model: {', '.join(bad)}")
    for m, f in body.framing.items():
        if m not in ALL_MODELS or f not in FRAMINGS:
            raise HTTPException(422, f"framing must be one of {', '.join(FRAMINGS)}")
    clips, skipped = [], []
    for pid in body.plan_ids:
        p = recs.get(pid)
        if not p:
            raise HTTPException(404, f"no such plan {pid}")
        for m in paid:
            r = p["results"].get(m) or {}
            if p.get("status") != "ready":
                skipped.append(f"line {p['line'] + 1} ({p['text'][:30]}): still preparing")
            elif r.get("status") in ("queued", "running", "done"):
                skipped.append(f"line {p['line'] + 1}, {ALL_MODELS[m]['label']}: already {r['status']}")
            elif m in GPU_MODELS and gpu_blocked(view(db, p), m):
                skipped.append(f"line {p['line'] + 1}, {GPU_MODELS[m]['label']}: {gpu_blocked(view(db, p), m)}")
            else:
                clips.append((pid, m, estimate(m, p["seconds"], db)["usd"]))
    return clips, skipped


@router.post("/motion/shot-batch/run")
def batch_run(body: BatchIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Without confirm: the ONE summary (exact clips, total estimate, budget and approved-but-uncharged runs against the
    cap). With confirm (and the total the owner saw): queue exactly those clips. The rig renders are free and already made."""
    from . import fal, gpu
    clips, skipped = _batch_clips(db, body)
    total = round(sum(c[2] for c in clips), 4)
    fal_total = round(sum(u for _, m, u in clips if m in MODELS), 4)
    gpu_clips = [c for c in clips if c[1] in GPU_MODELS]
    led = fal.spent(db)
    g = gpu.availability(db)
    summary = {"clips": len(clips), "total_usd": total, "spent_usd": round(led["total"], 4), "pending_usd": pending_usd(db),
               "budget_usd": fal.budget(db), "fal_usd": fal_total,
               "fits": led["total"] + pending_usd(db) + fal_total <= fal.budget(db) + 1e-9 and (not gpu_clips or g["ok"]),
               "gpu": {**g, "clips": len(gpu_clips), "estimate_usd": round(sum(c[2] for c in gpu_clips), 4)},
               "rig": "rig" in body.models, "skipped": skipped,
               "items": [{"plan_id": pid, "model": m, "usd": u} for pid, m, u in clips]}
    if not body.confirm:
        return summary
    if body.expected_usd is None or abs(body.expected_usd - total) > 1e-6:
        raise HTTPException(409, f"the selection changed since the summary (now {len(clips)} clip(s), ${total:.2f}): check it again")
    if not clips:
        raise HTTPException(409, "nothing to run")
    recs = records(db)
    if any(m in MODELS and not view(db, recs[pid]).get("urls_ok") for pid, m, _ in clips):
        raise HTTPException(409, "fal.ai fetches the first frames and the line audio from the studio: set PUBLIC_URL on the server first")
    if fal_total:
        check_cap(db, fal_total)
    if gpu_clips:
        check_gpu(db)
    for pid in {pid for pid, _, _ in clips}:
        if body.framing:
            recs = records(db)
            recs[pid]["framing"] = {**(recs[pid].get("framing") or {}), **body.framing}
            save(db, recs)
    jobs = [approve(db, pid, m, user).id for pid, m, _ in clips]
    db.add(Event(episode_id=recs[clips[0][0]]["episode_id"], kind="episode",
                 message=f"Shot comparison batch approved by {user}: {len(clips)} clip(s), estimated ${total:.2f}"))
    db.commit()
    return {**summary, "queued": len(jobs)}


# ------------------------------------------------------------------ media helpers
def _ff(args: list[str]) -> None:
    from .config import get_settings
    r = subprocess.run([get_settings().ffmpeg, "-v", "error", "-y", *args], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr.strip()[-300:]}")


def stream_seconds(path: Path) -> dict:
    """Duration of the video and the audio streams (FFprobe)."""
    from .config import get_settings
    r = subprocess.run([get_settings().ffprobe, "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=120)
    out = {}
    for s in json.loads(r.stdout or "{}").get("streams", []):
        try:
            out[s["codec_type"]] = float(s["duration"])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def finish(video: Path, wav: Path, seconds: float, out: Path) -> dict:
    """The model's (or the rig's) picture with OUR line audio: the picture is cut, or its last frame held, to exactly
    the line's length at 30 fps; any audio the model made is dropped. Returns the length check."""
    vs = stream_seconds(video).get("video") or 0.0
    pad = max(0.0, seconds - vs) + 0.5
    _ff(["-i", str(video), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
         "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
         "-t", f"{seconds:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)])
    got = stream_seconds(out)
    v, a = got.get("video") or 0.0, got.get("audio") or 0.0
    return {"model_seconds": round(vs, 3), "video_seconds": round(v, 3), "audio_seconds": round(a, 3),
            "line_seconds": round(seconds, 3), "held_last_frame": vs + 1e-3 < seconds,
            "length_ok": abs(v - seconds) <= 1.0 / FPS + 1e-3 and abs(a - seconds) <= 1.0 / FPS + 1e-3}


def compose(plate: Path, pose: Path, blocking: dict, plate_w: int, plate_h: int, out: Path, framing: str = "wide") -> Path:
    """The first frame: the approved set plate (cover-fit to 720x1280) and the approved neutral pose, centred. Our own
    art only. wide: the whole figure standing on the floor line. medium: closer on the same plate, the head and upper
    body filling most of the frame (the figure runs off the bottom edge, the plate is enlarged to match)."""
    from PIL import Image
    bg = Image.open(plate).convert("RGB")
    k = max(W / bg.width, H / bg.height)
    if framing == "medium":
        fig = Image.open(pose).convert("RGBA")
        box = fig.getchannel("A").getbbox() or (0, 0, fig.width, fig.height)
        fig = fig.crop(box)
        fh = round(H * 1.55)                          # the head and upper body fill the frame, legs below the edge
        fig = fig.resize((max(1, round(fig.width * fh / fig.height)), fh))
        k2 = k * 1.55 / 0.46                          # the plate enlarged as much as the figure (same apparent scale)
        bg = bg.resize((round(bg.width * k2), round(bg.height * k2)))
        head_top = round(H * 0.06)
        floor = round(blocking.get("floor_y", plate_h * 0.86) * k2)
        top = max(0, min(bg.height - H, floor - (head_top + fh)))
        left = (bg.width - W) // 2
        bg = bg.crop((left, top, left + W, top + H))
        bg.paste(fig, ((W - fig.width) // 2, head_top), fig)
        bg.save(out)
        return out
    bg = bg.resize((round(bg.width * k), round(bg.height * k)))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H))
    fig = Image.open(pose).convert("RGBA")
    box = fig.getchannel("A").getbbox() or (0, 0, fig.width, fig.height)
    fig = fig.crop(box)
    fh = round(H * 0.46)
    fig = fig.resize((max(1, round(fig.width * fh / fig.height)), fh))
    floor = round(blocking.get("floor_y", plate_h * 0.86) * k) - top
    bg.paste(fig, ((W - fig.width) // 2, min(H, floor) - fig.height), fig)
    bg.save(out)
    return out


# ------------------------------------------------------------------ jobs
from .tasks import Ctx, store_asset, task  # noqa: E402


@task
def shot_prepare(ctx: Ctx) -> dict:
    """Free and local: the first frame, the line's audio and the rig render of the same line."""
    from . import media, scene_sets
    from . import sets as studio_sets
    from .audio_production import source_audio
    from .storage import storage
    db, job = ctx.db, ctx.job
    pid = job.payload["pid"]
    p = records(db)[pid]
    ep = db.get(Episode, p["episode_id"])
    sc = db.get(StoryboardScene, p["scene_id"])
    folder = ctx.folder("shot-compare", pid)
    try:
        c = db.query(Character).filter_by(key=p["speaker"]).one()
        pid_pose = (c.expressions or {}).get("neutral")
        a = db.get(CharacterAsset, int(pid_pose[1:])) if pid_pose and pid_pose.startswith("p") else None
        if a is None or a.status != "approved":
            raise RuntimeError(f"{c.name} has no approved neutral pose")
        pose = storage().get_to_file(a.storage_key, folder / "pose.png")
        set_id = scene_sets.scene_set(ep, sc)
        spec = studio_sets.spec_for(db, set_id, folder / "set") if set_id else None
        if not spec:
            raise RuntimeError("the scene has no approved set")
        frame_assets = {}
        for f in FRAMINGS:
            frame = compose(Path(spec["plate"]), pose, spec, spec["width"], spec["height"], folder / f"first-frame-{f}.png", f)
            frame_assets[f] = store_asset(db, ep_id=ep.id, src=frame, key=f"episodes/{ep.id}/shot-compare/{pid}/first-frame-{f}.png",
                                          kind="scene-reference", label=f"Shot comparison first frame, {f} (approved set + approved neutral pose)",
                                          content_type="image/png", job_id=job.id).id
        src, _ = source_audio(db, ep, folder / "source")
        wav = media.cut_audio(src, folder / "line.wav", p["start"], p["end"])
        aa = store_asset(db, ep_id=ep.id, src=wav, key=f"episodes/{ep.id}/shot-compare/{pid}/line.wav", kind="audio",
                         label="Shot comparison: the line's recorded audio", content_type="audio/wav", job_id=job.id)
        write_action(db, pid, ep, sc, ctx.log)
        recs = records(db)
        recs[pid].update({"frame_asset_id": frame_assets["wide"], "frame_assets": frame_assets, "audio_asset_id": aa.id, "set_id": set_id, "status": "ready",
                          "audio_seconds": round(media.probe(wav)["duration"] or p["seconds"], 3)})
        save(db, recs)
        db.commit()
        # the rig render of the same line (free; a failure here does not block the AI comparison)
        try:
            from . import acting
            from .tasks import prepare_characters
            from .tasks_long import clip_map
            mp4, _, _ = acting.render(ctx, ep, [[(sc.id, p["line"])]], clip_map(db, ep), prepare_characters(ctx), folder / "rig")
            cut = folder / "rig-line.mp4"
            _ff(["-ss", f"{p['start']:.3f}", "-i", str(mp4), "-t", f"{p['seconds'] + 0.5:.3f}", "-an", "-c:v", "libx264", str(cut)])
            out = folder / "rig-final.mp4"
            check = finish(cut, wav, p["seconds"], out)
            ra = store_asset(db, ep_id=ep.id, src=out, key=f"episodes/{ep.id}/shot-compare/{pid}/rig.mp4", kind="video",
                             label="Shot comparison: the rig animator", content_type="video/mp4", job_id=job.id)
            recs = records(db)
            recs[pid].update({"rig_asset_id": ra.id, "rig_check": check})
        except Exception as e:   # noqa: BLE001
            recs = records(db)
            recs[pid]["rig_error"] = f"the rig render of this line is not available: {str(e)[:200]}"
            ctx.log(recs[pid]["rig_error"])
        save(db, recs)
        db.commit()
    except Exception as e:
        recs = records(db)
        recs[pid].update({"status": "failed", "error": str(e)[:300]})
        save(db, recs)
        db.commit()
        raise
    return {"pid": pid}


@task
def shot_generate(ctx: Ctx) -> dict:
    """ONE paid request the owner approved: send the shown request, then put our line audio under the result."""
    from . import fal
    from .comparison import public_url
    from .models import Asset
    from .storage import storage
    db, job = ctx.db, ctx.job
    pid, model = job.payload["pid"], job.payload["model"]
    p = records(db)[pid]
    if model in GPU_MODELS:
        return _generate_gpu(ctx, pid, model)
    m = MODELS[model]
    folder = ctx.folder("shot-compare", pid)
    framing = framing_of(p, model)
    img = public_url(storage().url(db.get(Asset, (p.get("frame_assets") or {}).get(framing) or p["frame_asset_id"]).storage_key, 7200))
    aud = public_url(storage().url(db.get(Asset, p["audio_asset_id"]).storage_key, 7200))
    body = request_for(model, p["action"], img, aud, p["seconds"])
    est = estimate(model, p["seconds"])

    def mark(**kw):
        recs = records(db)
        recs[pid]["results"][model] = {**recs[pid]["results"].get(model, {}), **kw}
        save(db, recs)
        db.commit()

    mark(status="running")
    try:
        raw = folder / f"{model}-raw.mp4"
        data, tm = fal.run(db, m["endpoint"], m["label"], body, est["usd"], f"shot {pid}: {p['text'][:60]}", raw, ctx.log,
                           lambda info: mark(progress=info))
        if m["kind"] == "avatar":
            # billed per second of OUR audio (the output follows it): the reported duration, else the audio's length
            billed = float(data.get("duration") or p.get("audio_seconds") or p["seconds"])
            actual = round(m["rate"] * billed, 4)
        else:
            actual = est["usd"]
        if abs(actual - est["usd"]) > 0.0001:
            fal.correct_spend(db, est["usd"], actual)
        wav = storage().get_to_file(db.get(Asset, p["audio_asset_id"]).storage_key, folder / "line.wav")
        out = folder / f"{model}.mp4"
        check = finish(raw, wav, p["seconds"], out)
        va = store_asset(db, ep_id=p["episode_id"], src=out, key=f"episodes/{p['episode_id']}/shot-compare/{pid}/{model}.mp4",
                         kind="video", label=f"Shot comparison: {m['label']}", content_type="video/mp4", job_id=job.id)
        mark(status="done", asset_id=va.id, actual_usd=actual, framing=framing, per_second_usd=round(actual / max(0.001, p["seconds"]), 4),
             check=check, seconds=tm["seconds"], request_id=tm["request_id"])
        return {"pid": pid, "model": model, "actual_usd": actual, "check": check}
    except Exception as e:
        mark(status="failed", error=str(e)[:300])
        raise


def _generate_gpu(ctx: Ctx, pid: str, model: str) -> dict:
    """ONE self-hosted clip the owner approved: the same first frame (or this line's Kling clip, for lip-sync) and OUR
    line audio go to our GPU worker as files; the worker's video gets our audio laid under it and the length check.
    The GPU session is launched (cap-checked) or reused; it is checked at every poll and the clip stops at the cap or
    the maximum lifetime. Cost = the clip's GPU seconds at the session's hourly price."""
    from . import gpu
    from .models import Asset
    from .storage import storage
    db, job = ctx.db, ctx.job
    p = records(db)[pid]
    m = GPU_MODELS[model]
    folder = ctx.folder("shot-compare", pid)

    def mark(**kw):
        recs = records(db)
        recs[pid]["results"][model] = {**recs[pid]["results"].get(model, {}), **kw}
        save(db, recs)
        db.commit()

    w = None
    # unique per submission: a long-lived worker (our own machine) may still hold an older job with the same studio job
    # id and attempt (another studio, a restored database), and an idempotent repeat must never return that job's result
    jid = f"j{job.id}-a{job.attempts}-{uuid.uuid4().hex[:10]}"
    submitted = False
    try:
        why = gpu_blocked(view(db, p), model)
        if why:
            raise gpu.GpuUnavailable(why)
        wf, wsha = workflow_of(model)
        wav = storage().get_to_file(db.get(Asset, p["audio_asset_id"]).storage_key, folder / "line.wav")
        if m["kind"] == "dub":
            src = storage().get_to_file(db.get(Asset, p["results"][m["needs"]]["asset_id"]).storage_key, folder / f"{model}-in.mp4")
            inputs = {"video.mp4": gpu.b64(src), "audio.wav": gpu.b64(wav)}
        else:
            framing = framing_of(p, model)
            img = storage().get_to_file(db.get(Asset, (p.get("frame_assets") or {}).get(framing) or p["frame_asset_id"]).storage_key,
                                        folder / f"{model}-frame.png")
            inputs = {"image.png": gpu.b64(img), "audio.wav": gpu.b64(wav)}
        mark(status="running", progress={"status": "starting the GPU worker"})
        w = gpu.ensure_worker(db, ctx.log)
        where = "our own machine" if w["session"] is None else f"GPU session {w['session']} (${w['price_per_hour']:.2f}/h)"
        mark(session=w["session"], worker=where, progress={"status": "submitted"})
        gpu.worker_submit(w["url"], w["token"], {"id": jid, "kind": "comfyui-workflow", "workflow": wf, "workflow_sha256": wsha,
                                                 "params": gpu_params(model, p), "inputs": inputs})
        submitted = True
        ctx.log(f"GPU: {m['label']} submitted to {where}")
        while True:
            if w["session"]:
                stop = gpu.check_session(db, w["session"])
                if stop:
                    gpu.worker_cancel(w["url"], w["token"], jid)
                    raise gpu.GpuUnavailable(f"Stopped: {stop}. Retry it after raising the cap or next month" if "cap" in stop
                                             else f"Stopped: {stop}. Retry it")
            st = gpu.worker_status(w["url"], w["token"], jid)
            mark(progress={"status": st["status"], "log_tail": (st.get("log_tail") or [])[-3:]})
            if st["status"] in ("done", "failed", "cancelled"):
                break
            gpu.sleep(gpu.POLL_S)
        if st["status"] != "done":
            raise ProviderErrorNT(f"the GPU worker: {st['status']}: {st.get('error') or ''}"[:300])
        out_meta = next((o for o in st.get("outputs") or [] if o["name"].startswith("video")), None)
        if out_meta is None:
            raise ProviderErrorNT("the GPU worker returned no video")
        raw = gpu.worker_fetch(w["url"], w["token"], jid, out_meta, folder / f"{model}-raw{Path(out_meta['name']).suffix}")
        out = folder / f"{model}.mp4"
        check = finish(raw, wav, p["seconds"], out)
        va = store_asset(db, ep_id=p["episode_id"], src=out, key=f"episodes/{p['episode_id']}/shot-compare/{pid}/{model}.mp4",
                         kind="video", label=f"Shot comparison: {m['label']}", content_type="video/mp4", job_id=job.id)
        gsec = float(st.get("gpu_seconds") or 0)
        actual = round(gsec * w["price_per_hour"] / 3600, 4)
        mark(status="done", asset_id=va.id, actual_usd=actual, per_second_usd=round(actual / max(0.001, p["seconds"]), 4),
             gpu_seconds=gsec, check=check, framing=framing_of(p, model), workflow_sha256=wsha, progress=None,
             cost_note="GPU time of this clip at the session's price; boot and idle time are on the session")
        gpu.worker_delete(w["url"], w["token"], jid)
        gpu.touch(db, w["session"], clips=1)
        return {"pid": pid, "model": model, "actual_usd": actual, "gpu_seconds": gsec, "check": check}
    except Exception as e:
        mark(status="failed", error=str(e)[:300], progress=None)
        if w is not None:
            if submitted:                      # the failed job's files do not stay on the worker
                gpu.worker_cancel(w["url"], w["token"], jid)
                gpu.worker_delete(w["url"], w["token"], jid)
            gpu.touch(db, w["session"])
        raise


class ProviderErrorNT(RuntimeError):
    """A self-hosted clip failed for a reason that is not worth an automatic retry."""
