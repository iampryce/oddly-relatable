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


def estimate(model: str, seconds: float) -> dict:
    m = MODELS[model]
    if m["kind"] == "i2v":
        billed = 5 if seconds <= 5 else 10
        note = "" if seconds <= 10 else f"the line runs {seconds:.1f} s: the 10 s clip's last frame is held to the end"
    else:
        billed, note = math.ceil(seconds), ""
    return {"billed_seconds": billed, "usd": round(m["rate"] * billed, 4), "note": note}


def prompt_for(model: str, action: str) -> str:
    if MODELS[model]["kind"] == "i2v":
        return ("2D flat cartoon animation, static camera. The character in the image " + action.strip().rstrip(".") +
                ". Keep the character's design, colours and proportions and the background exactly as in the image; "
                "no new characters, no text, no camera move.")
    return (action.strip().rstrip(".") + ". Keep the character's flat 2D design and the background exactly as in the "
            "image; the mouth follows the audio.")


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
    led = fal.spent(db)
    return {"episode": {"id": ep.id, "title": ep.title, "set_id": ep.set_id}, "lines": lines,
            "models": [{"id": k, **{x: m[x] for x in ("label", "why", "price", "licence")}} for k, m in MODELS.items()],
            "spent_usd": round(led["total"], 2), "budget_usd": fal.budget(db)}


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
    return (p.get("framing") or {}).get(model) or MODELS[model]["framing"]


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
    if body.model not in MODELS or body.framing not in FRAMINGS:
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
    if body.model not in MODELS:
        raise HTTPException(422, "unknown model")
    if p.get("status") != "ready":
        raise HTTPException(409, "the plan is not ready yet (its free preparation is still running or failed)")
    if (p["results"].get(body.model) or {}).get("status") in ("queued", "running", "done"):
        raise HTTPException(409, "already queued, running or done")
    if not view(db, p).get("urls_ok"):
        raise HTTPException(409, "fal.ai fetches the first frame and the line audio from the studio: set PUBLIC_URL on the server first")
    est = estimate(body.model, p["seconds"])
    check_cap(db, est["usd"])
    job = approve(db, pid, body.model, user)
    db.commit()
    return {"job_id": job.id, "estimate": est}


def pending_usd(db: Session) -> float:
    """Approved runs not charged yet (queued or running): they count against the cap."""
    return round(sum(r.get("estimated_usd") or 0 for q in records(db).values() for r in (q.get("results") or {}).values()
                     if r.get("status") in ("queued", "running")), 4)


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
    est = estimate(model, p["seconds"])
    p["results"][model] = {"status": "queued", "estimated_usd": est["usd"], "approved_by": user}
    save(db, recs)
    job = enqueue(db, "shot_generate", episode_id=p["episode_id"], payload={"pid": pid, "model": model})
    db.add(Event(episode_id=p["episode_id"], kind="episode", message=f"Shot comparison: {MODELS[model]['label']} approved by {user} "
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
    from . import fal
    latest: dict[tuple, dict] = {}
    for p in sorted(records(db).values(), key=lambda p: p.get("created", 0)):
        if p["episode_id"] == eid:
            latest[(p["scene_id"], p["line"])] = p
    led = fal.spent(db)
    plans = [view(db, p) for p in latest.values()]
    return {"plans": plans, "ready": sum(1 for p in plans if p["status"] == "ready"),
            "preparing": sum(1 for p in plans if p["status"] == "preparing"),
            "spent_usd": round(led["total"], 4), "pending_usd": pending_usd(db), "budget_usd": fal.budget(db)}


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
    paid = [m for m in body.models if m in MODELS]
    bad = [m for m in body.models if m not in MODELS and m != "rig"]
    if bad:
        raise HTTPException(422, f"unknown model: {', '.join(bad)}")
    for m, f in body.framing.items():
        if m not in MODELS or f not in FRAMINGS:
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
                skipped.append(f"line {p['line'] + 1}, {MODELS[m]['label']}: already {r['status']}")
            else:
                clips.append((pid, m, estimate(m, p["seconds"])["usd"]))
    return clips, skipped


@router.post("/motion/shot-batch/run")
def batch_run(body: BatchIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Without confirm: the ONE summary (exact clips, total estimate, budget and approved-but-uncharged runs against the
    cap). With confirm (and the total the owner saw): queue exactly those clips. The rig renders are free and already made."""
    from . import fal
    clips, skipped = _batch_clips(db, body)
    total = round(sum(c[2] for c in clips), 4)
    led = fal.spent(db)
    summary = {"clips": len(clips), "total_usd": total, "spent_usd": round(led["total"], 4), "pending_usd": pending_usd(db),
               "budget_usd": fal.budget(db), "fits": led["total"] + pending_usd(db) + total <= fal.budget(db) + 1e-9,
               "rig": "rig" in body.models, "skipped": skipped,
               "items": [{"plan_id": pid, "model": m, "usd": u} for pid, m, u in clips]}
    if not body.confirm:
        return summary
    if body.expected_usd is None or abs(body.expected_usd - total) > 1e-6:
        raise HTTPException(409, f"the selection changed since the summary (now {len(clips)} clip(s), ${total:.2f}): check it again")
    if not clips:
        raise HTTPException(409, "nothing to run")
    recs = records(db)
    if any(not view(db, recs[pid]).get("urls_ok") for pid, _, _ in clips):
        raise HTTPException(409, "fal.ai fetches the first frames and the line audio from the studio: set PUBLIC_URL on the server first")
    check_cap(db, total)
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
