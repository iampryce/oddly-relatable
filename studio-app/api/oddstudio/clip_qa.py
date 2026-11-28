"""Quality check of the finished clips (guided flow, step 10): Gemini watches each talking-shot and reaction-shot
result and lists problems with their time in the clip, each with a suggested fix in the form the chat under that shot
already offers (talking shot: rerender_talking_shot; reaction shot: reanimate_shot), so the owner's "Apply" goes
through the step's own paid route with its price confirmed (confirm_usd). The answer is posted in the shot's chat
thread as a message from "Quality check".

Which clip: per shot, the approved result, else the newest one. What Gemini gets: each on-screen character's approved
master picture and description, up to 8 frames of the clip (JPEG, with their times), the whole clip when it is at most
Settings > Quality check "send the whole clip" MB, when the speaker talks (Whisper word times) and the shot's acting
notes as text. It is asked: same characters as the masters? anyone missing, merged or extra? style breaks (a nose,
teeth, realistic hands, glasses or hair added)? camera zoom or pan? a mouth moving while that character is silent?
Each problem is rated "clear" or "possible". The reference video's pictures are never sent anywhere.

Model: Settings > Quality check. When the owner says the Gemini key is on a paid tier, the paid model at its price;
otherwise the free-tier model ONLY when "use the free tier" is ticked (Google may use free-tier uploads to improve its
models), at no cost; with neither the check is unavailable. Cost: input tokens (258 per picture, 300 per second of a
whole clip, the prompt) plus at most 4000 output tokens per clip, at the model's price; shown first, and the request
must carry it (confirm_usd, 409 otherwise). The job stops before a clip that would pass the confirmed amount. One call
per clip, never retried.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import secrets as pysecrets
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Asset, Character, Episode, Event, Job, Setting
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

JOB = "clip_qa"
MAX_FRAMES = 8
TOKENS_PER_IMAGE = 258
TOKENS_PER_VIDEO_SECOND = 300
CHARS_PER_TOKEN = 3.5
MAX_OUT = 4000
AUTHOR = "Quality check"
KINDS = ("identity", "missing", "merged", "extra", "style", "camera", "mouth", "anatomy", "face", "vfx", "other")
FREE_NOTE = "free tier: Google may use the clips to improve its models"


def key(eid: int) -> str:
    return f"quality:{eid}"


# ================================================================== settings (which model)
def provider(db: Session) -> dict:
    """{ready, model, usd_in, usd_out, free, label, note}: the paid model when the key is on a paid tier, the free-tier
    model only when ticked, else not ready (with the reason in plain words)."""
    q = get_section(db, "quality")
    has_key = bool(secret("gemini_api_key", db))
    base = {"ready": False, "model": "", "usd_in": 0.0, "usd_out": 0.0, "free": False, "label": "Gemini", "note": ""}
    if not has_key:
        return {**base, "note": "Gemini: no key saved (Settings > Credentials): the quality check is skipped"}
    if q.get("qa_paid_tier"):
        return {**base, "ready": True, "model": q["qa_model"], "usd_in": float(q["qa_usd_in"]), "usd_out": float(q["qa_usd_out"]),
                "label": f"Gemini {q['qa_model']} (paid tier)"}
    if q.get("qa_use_free_tier"):
        return {**base, "ready": True, "model": q["qa_free_model"], "free": True,
                "label": f"Gemini {q['qa_free_model']} ({FREE_NOTE})", "note": f"Gemini: {FREE_NOTE}"}
    return {**base, "note": "Gemini: the key is on the free tier. Tick \"my key is on a paid tier\" or \"use the free tier\" "
                            "in Settings > Quality check; until then the quality check is skipped"}


# ================================================================== pure parts
def frame_times(seconds: float, n: int = MAX_FRAMES) -> list[float]:
    """Evenly spread frame times inside the clip (never the very first or last instant)."""
    if seconds <= 0:
        return [0.0]
    n = max(1, min(n, int(seconds * 4) or 1))
    return [round(seconds * (i + 0.5) / n, 2) for i in range(n)]


def estimate(prov: dict, pictures: int, video_seconds: float, prompt: str, clips: int = 1) -> dict:
    tin = pictures * TOKENS_PER_IMAGE + int(video_seconds * TOKENS_PER_VIDEO_SECOND) + math.ceil(len(prompt) / CHARS_PER_TOKEN)
    if prov.get("free"):
        return {"model": prov["model"], "input_tokens": tin, "usd_typical": 0.0, "usd_max": 0.0, "clips": clips,
                "label": f"{prov['model']}: free ({FREE_NOTE})"}
    typ = round(tin * prov["usd_in"] / 1e6 + 800 * prov["usd_out"] / 1e6, 4)
    mx = round(tin * prov["usd_in"] / 1e6 + MAX_OUT * prov["usd_out"] / 1e6, 4)
    return {"model": prov["model"], "input_tokens": tin, "usd_typical": typ, "usd_max": mx, "clips": clips,
            "label": f"{prov['model']}: about ${typ:.4f}, at most ${mx:.4f}"}


def sum_estimates(ests: list[dict], prov: dict) -> dict:
    typ = round(sum(e["usd_typical"] for e in ests), 4)
    mx = round(sum(e["usd_max"] for e in ests), 4)
    label = (f"{len(ests)} clip(s) with {prov['model']}: free ({FREE_NOTE})" if prov.get("free") else
             f"{len(ests)} clip(s) with {prov['model']}: about ${typ:.4f}, at most ${mx:.4f}")
    return {"usd_typical": typ, "usd_max": mx, "clips": len(ests), "label": label, "model": prov.get("model")}


REALISTIC_CHECKS = """Check (this is REALISTIC live-action-style footage of invented actors):
1. Identity consistency: is each person the same as their approved master (face, hair, build, costume) for the whole
   clip? Does a face drift into someone else?
2. Anatomy: extra or missing fingers, extra limbs, merged or duplicated bodies, broken hands.
3. Face warping: melting, morphing or flickering faces, eyes or teeth.
4. VFX glitches: smears, flicker, effects that appear or vanish unnaturally, effects that cover a face.
5. Camera jumps: sudden jumps, warps or cuts inside the clip (a planned slow camera move is fine).
6. Lip sync: for a talking clip, does the mouth follow the speech, and is it closed when silent?

For each problem give the time in seconds, the kind (identity, anatomy, face, vfx, camera, mouth, missing, extra or
other), the severity"""


def prompt_for(people: list[tuple[str, str]], seconds: float, speaking: str, acting: list[str], frames: list[float],
               whole: bool, schemas: list[str], realistic: bool = False) -> str:
    who = "\n".join(f"- {n}: {d.strip().rstrip('.') or 'no description'}" for n, d in people) or "- (nobody: the room only)"
    shapes = "\n".join(f"  {s}" for s in schemas)
    shown = (("The whole clip is attached, and " if whole else "") +
             f"{len(frames)} frames of it at {', '.join(f'{t:.2f}' for t in frames)} s.")
    act = ("\nWhat should happen (acting notes):\n" + "\n".join(f"- {a}" for a in acting)) if acting else ""
    if realistic:
        return f"""You check one clip ({seconds:.2f} s) of a realistic short film made with AI video models, before it goes
into the episode. The approved master picture of each person on screen comes first, in this order:
{who}
{shown}
Sound: {speaking}{act}

{REALISTIC_CHECKS} ("clear" when you are sure, "possible" otherwise), one short sentence, and a fix in one of these
shapes (or null when no change of the clip would help):
{shapes}

Reply with JSON only: {{"issues": [{{"t": <seconds>, "kind": "<kind>", "severity": "clear|possible", "what": "<sentence>",
"fix": <one shape or null>}}], "summary": "<one short sentence for the owner>"}}. No problems: an empty list."""
    return f"""You check one animated clip ({seconds:.2f} s) of a 2D stick-figure cartoon for problems before it goes into the
episode. The approved master picture of each character on screen comes first, in this order:
{who}
{shown}
Sound: {speaking}{act}

Check:
1. Are these the same characters as the masters (face, accessory, colours)? Has anyone changed?
2. Is anyone missing, merged into another character, or is there an extra person?
3. Style breaks: a nose, teeth or a tongue, realistic hands, glasses or hair added, 3D or realistic shading.
4. Does the camera zoom, pan or shake? (It must stay locked.)
5. Does a mouth move while that character is silent?

For each problem give the time in seconds, the kind (identity, missing, merged, extra, style, camera, mouth or other),
the severity ("clear" when you are sure, "possible" otherwise), one short sentence, and a fix in one of these shapes
(or null when no change of the clip would help):
{shapes}

Reply with JSON only: {{"issues": [{{"t": <seconds>, "kind": "<kind>", "severity": "clear|possible", "what": "<sentence>",
"fix": <one shape or null>}}], "summary": "<one short sentence for the owner>"}}. No problems: an empty list."""


def parse(text: str, step: str, item: str, allowed: tuple, seconds: float) -> dict:
    """Gemini's answer as {issues: [{t, kind, severity, what, fix, fix_left_out}], summary}; each fix checked with the
    chat's own proposal rules (a fix the shot's chat cannot make is left out, so nothing unknown can be applied)."""
    from .shot_chat import validate_proposal
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0) if m else text)
    except (ValueError, TypeError):
        raise ValueError("Gemini's answer was not readable")
    if not isinstance(d, dict):
        raise ValueError("Gemini's answer was not readable")
    out = []
    for x in d.get("issues") or []:
        if not isinstance(x, dict):
            continue
        try:
            t = round(min(max(float(x.get("t") or 0), 0.0), max(seconds, 0.0)), 2)
        except (TypeError, ValueError):
            t = 0.0
        kind = str(x.get("kind") or "other").lower()
        kind = kind if kind in KINDS else "other"
        sev = "clear" if str(x.get("severity") or "").lower() == "clear" else "possible"
        what = str(x.get("what") or "").strip()[:300]
        if not what:
            continue
        fix, left = None, None
        if isinstance(x.get("fix"), dict):
            try:
                fix = validate_proposal(step, item, x["fix"], allowed)
            except ValueError as e:
                left = str(e)
        out.append({"t": t, "kind": kind, "severity": sev, "what": what, "fix": fix, "fix_left_out": left})
    out.sort(key=lambda i: (i["severity"] != "clear", i["t"]))
    return {"issues": out, "summary": str(d.get("summary") or "").strip()[:400]}


def best_fix(res: dict) -> dict | None:
    """The one proposal posted with the message: the first clear problem's fix, else the first possible one's."""
    for i in res["issues"]:
        if i["fix"] and i["fix"]["type"] != "note_only":
            return i["fix"]
    return None


def clear_fix(res: dict) -> dict | None:
    """A fix the autopilot may apply by itself: only for a problem the check rates "clear"."""
    for i in res["issues"]:
        if i["severity"] == "clear" and i["fix"] and i["fix"]["type"] != "note_only":
            return i["fix"]
    return None


def message_text(res: dict) -> str:
    if not res["issues"]:
        return "Quality check: no problems found. " + (res["summary"] or "")
    lines = [f"Quality check: {len(res['issues'])} problem(s). {res['summary']}".strip()]
    for i in res["issues"]:
        lines.append(f"- {i['t']:.1f} s [{i['severity']}] {i['kind']}: {i['what']}")
    return "\n".join(lines)


# ================================================================== the clips
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


def clips(db: Session, ep: Episode) -> list[dict]:
    """Per talking / reaction shot with a result: the approved result, else the newest. [{shot, step, kind, clip_id,
    asset_id, seconds, people, approved, speaker, words, t0}] (step: the chat thread's step, talk | clip)."""
    from . import reactions as R
    from . import talking_s2v as T
    from . import cinematic as CIN
    if CIN.is_cinematic(ep):
        return cinematic_clips(db, ep)
    out = []
    tv = T.stored(db, ep.id)
    for r in T.talking_rows(db, ep):
        st = (tv.get("shots") or {}).get(str(r["index"])) or {}
        renders = st.get("renders") or []
        if not renders:
            continue
        rec = next((x for x in renders if x["id"] == st.get("approved")), None) or renders[0]
        frames = sum(rec.get("pieces") or []) or int(rec.get("frames") or 0)
        out.append({"shot": r["index"], "step": "talk", "kind": "talking", "clip_id": rec["id"], "asset_id": rec.get("asset_id"),
                    "seconds": round(frames / T.FPS, 2), "people": [r["speaker"]] if r["speaker"] else [],
                    "approved": st.get("approved") == rec["id"], "speaker": r["name"], "words": r["words"], "t0": r["t0"],
                    "t1": r["t1"]})
    rv = R.stored(db, ep.id)
    for r in R.reaction_rows(db, ep):
        st = (rv.get("shots") or {}).get(str(r["index"])) or {}
        cl = st.get("clips") or []
        if not cl:
            continue
        rec = next((x for x in cl if x["id"] == st.get("approved")), None) or cl[0]
        out.append({"shot": r["index"], "step": "clip", "kind": "reaction", "clip_id": rec["id"], "asset_id": rec.get("asset_id"),
                    "seconds": round(int(rec.get("frames") or 0) / int(rec.get("fps") or 25), 2), "people": r["people"],
                    "approved": st.get("approved") == rec["id"], "speaker": "", "words": [], "t0": r["t0"], "t1": r["t1"]})
    return sorted(out, key=lambda c: c["shot"])


def cinematic_clips(db: Session, ep: Episode) -> list[dict]:
    """A cinematic episode's shots with a result (cinematic.py): the approved result, else the newest (step cine_shot)."""
    from . import cinematic as CIN
    v = CIN.stored(db, ep.id)
    chars = CIN._chars(db, v)
    out = []
    for s in CIN.shots_of(CIN.screenplay(v)):
        st = (v.get("shots") or {}).get(str(s["n"])) or {}
        renders = st.get("renders") or []
        if not renders:
            continue
        rec = next((x for x in renders if x["id"] == st.get("approved_render")), None) or renders[0]
        out.append({"shot": s["n"], "step": "cine_shot", "kind": "talking" if rec.get("kind") == "talk" else "motion",
                    "clip_id": rec["id"], "asset_id": rec.get("asset_id"), "seconds": round(int(rec.get("frames") or 0) / 16, 2),
                    "people": [chars[n].key for n in s.get("characters") or [] if n in chars],
                    "approved": st.get("approved_render") == rec["id"], "speaker": (s.get("line") or {}).get("speaker", ""),
                    "words": [], "t0": 0.0, "t1": 0.0, "realistic": True, "line_text": (s.get("line") or {}).get("text", ""),
                    "action": s.get("action") or "", "vfx": s.get("vfx") or "", "camera": s.get("camera") or "static"})
    return out


def check_key(c: dict) -> str:
    return f"{c['step']}:{c['shot']}:{c['clip_id']}"


def speaking_text(c: dict) -> str:
    from .talking_s2v import voice_spans
    if c.get("realistic"):
        if c["kind"] == "talking":
            return f"{c['speaker']} speaks for most of the clip: \"{c.get('line_text', '')}\"; the others listen."
        return ("nobody speaks in this clip. Planned: " + (c.get("action") or "the action of the shot") +
                (f"; visual effect: {c['vfx']}" if c.get("vfx") else "") + f"; camera: {c.get('camera')}.")
    if c["kind"] != "talking":
        return "nobody on screen speaks in this shot: mouths stay closed unless the acting notes say otherwise."
    spans = voice_spans(c["words"], c["t0"], c["t1"])
    if not spans:
        return f"{c['speaker']} is silent the whole clip."
    return (f"{c['speaker']} speaks at " + ", ".join(f"{a:.2f}-{b:.2f} s" for a, b in spans)
            + "; silent the rest of the time (the mouth should be closed then).")


def acting_notes(db: Session, eid: int, shot: int) -> list[str]:
    from . import acting_analysis as AA
    res = AA.stored(db, eid).get("result") or {}
    s = next((x for x in res.get("shots") or [] if x.get("shot") == shot), None)
    out = []
    for b in (s or {}).get("beats") or []:
        bits = "; ".join(str(b[k]) for k in ("expression", "eyes_and_gaze", "head_and_body") if b.get(k))
        out.append(f"{b.get('t_start')}-{b.get('t_end')} s {b.get('character', '')}: {bits}")
    return out[:12]


def people_of(db: Session, keys: list[str]) -> list[Character]:
    chars = {c.key: c for c in db.query(Character).filter(Character.key.in_(keys))} if keys else {}
    return [chars[k] for k in keys if k in chars]


def allowed_for(db: Session, ep: Episode, c: dict) -> tuple:
    from .shot_chat import ALLOWED, Ref, allowed_for as chat_allowed
    if c["step"] in ("talk", "cine_shot"):
        return ALLOWED[c["step"]]
    return chat_allowed(db, Ref(episode_id=ep.id, step="clip", item=str(c["shot"])))


def schemas_for(allowed: tuple, step: str = "") -> list[str]:
    from .shot_chat import schema_for
    return [schema_for(step, t) for t in allowed if t != "note_only"]


def clip_estimate(db: Session, ep: Episode, c: dict, prov: dict, inline_mb: float) -> dict:
    """The cost of checking one clip (whole clip counted when its size allows it)."""
    a = db.get(Asset, c["asset_id"]) if c.get("asset_id") else None
    whole = bool(a and a.size and a.size <= inline_mb * 1024 * 1024)
    people = people_of(db, c["people"])
    frames = frame_times(c["seconds"])
    prompt = prompt_for([(p.name, p.visual_description or "") for p in people], c["seconds"], speaking_text(c),
                        acting_notes(db, ep.id, c["shot"]), frames, whole, schemas_for(allowed_for(db, ep, c), c["step"]),
                        bool(c.get("realistic")))
    return estimate(prov, len(people) + len(frames), c["seconds"] if whole else 0.0, prompt)


def view(db: Session, ep: Episode) -> dict:
    prov = provider(db)
    q = get_section(db, "quality")
    v = stored(db, ep.id)
    cl = clips(db, ep)
    ids = [c["asset_id"] for c in cl if c.get("asset_id")]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids))} if ids else {}
    out, todo = [], []
    for c in cl:
        res = (v.get("checks") or {}).get(check_key(c))
        a = assets.get(c["asset_id"])
        row = {k: c[k] for k in ("shot", "step", "kind", "clip_id", "seconds", "approved")}
        row["url"] = storage().url(a.storage_key) if a else None
        row["check"] = res
        if prov["ready"]:
            row["estimate"] = clip_estimate(db, ep, c, prov, float(q["qa_inline_mb"]))
            if not res:
                todo.append(row["estimate"])
        out.append(row)
    job = db.query(Job).filter_by(kind=JOB, episode_id=ep.id).order_by(Job.id.desc()).first()
    busy = db.query(Job).filter(Job.kind == JOB, Job.episode_id == ep.id, Job.status.in_(("queued", "running"))).first() is not None
    return {"provider": {k: prov[k] for k in ("ready", "model", "free", "label", "note")}, "clips": out,
            "estimate_unchecked": sum_estimates(todo, prov) if prov["ready"] and todo else None,
            "usd": round(v.get("usd") or 0.0, 4), "busy": busy, "job": S.job(job) if job else None}


def summary(db: Session, ep: Episode) -> dict:
    vw = view(db, ep)
    cl = vw["clips"]
    checked = [c for c in cl if c["check"]]
    problems = sum(1 for c in checked if c["check"]["issues"])
    if not vw["provider"]["ready"]:
        return {"status": "not_started", "cost": None, "detail": vw["provider"]["note"]}
    status = ("running" if vw["busy"] else "done" if cl and len(checked) == len(cl) and not problems else
              "needs_approval" if problems else "not_started")
    detail = (f"{len(checked)} of {len(cl)} clips checked" + (f"; {problems} with problems to look at" if problems else "")
              if cl else "no finished clips yet")
    return {"status": status, "cost": vw["estimate_unchecked"], "detail": detail}


# ================================================================== routes
def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return ep


@router.get("/episodes/{eid}/quality")
def get_quality(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shots: list[int] | None = Field(default=None, max_length=200)
    again: bool = False                          # check clips that already have a check
    confirm_usd: float | None = Field(default=None, ge=0, le=50)


def selection(db: Session, ep: Episode, shots: list[int] | None, again: bool) -> list[dict]:
    v = stored(db, ep.id)
    out = []
    for c in clips(db, ep):
        if shots and c["shot"] not in shots:
            continue
        if not again and check_key(c) in (v.get("checks") or {}):
            continue
        out.append(c)
    return out


def start(db: Session, ep: Episode, shots: list[int] | None, again: bool, confirm: float | None, user: str) -> dict:
    """Paid (the free tier only when ticked in Settings): queue the check of these clips."""
    prov = provider(db)
    if not prov["ready"]:
        raise HTTPException(409, prov["note"])
    sel = selection(db, ep, shots, again)
    if not sel:
        raise HTTPException(409, "no clip to check: every finished clip already has a check")
    q = get_section(db, "quality")
    est = sum_estimates([clip_estimate(db, ep, c, prov, float(q["qa_inline_mb"])) for c in sel], prov)
    if confirm is None or confirm + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"checking {len(sel)} clip(s) can cost up to ${est['usd_max']:.4f}: confirm that amount to start (nothing was sent)")
    if db.query(Job).filter(Job.kind == JOB, Job.episode_id == ep.id, Job.status.in_(("queued", "running"))).first():
        raise HTTPException(409, "a quality check is already running for this episode")
    job = enqueue(db, JOB, episode_id=ep.id, payload={"keys": [check_key(c) for c in sel], "confirm_usd": float(confirm),
                                                      "estimate": est, "by": user})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Quality check of {len(sel)} clip(s) asked by {user} ({est['label']})"))
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/quality/check")
def check(eid: int, body: CheckIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return start(db, _episode(db, eid), body.shots, body.again, body.confirm_usd, user)


# ================================================================== the job
from .tasks import Ctx, task  # noqa: E402


def _jpeg(path: Path, side: int = 768) -> str:
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def extract_frames(ff: str, video: Path, times: list[float], folder: Path) -> list[tuple[float, Path]]:
    out = []
    for t in times:
        f = folder / f"f{int(t * 100):05d}.jpg"
        r = subprocess.run([ff, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(f)],
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and f.exists():
            out.append((t, f))
    return out


def request_for(db: Session, ep: Episode, c: dict, video: Path, folder: Path, inline_mb: float, ff: str) -> tuple[dict, int, bool]:
    """(the Gemini request, pictures sent, whole clip sent). Only the studio's own pictures: the masters and the clip."""
    from .stick_pipeline import approved_master
    parts = []
    people = people_of(db, c["people"])
    for p in people:
        m = approved_master(db, p.id)
        if m:
            src = storage().get_to_file(m.storage_key, folder / f"master-{p.id}{Path(m.storage_key).suffix or '.png'}")
            parts += [{"text": f"Approved master of {p.name}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": _jpeg(src)}}]
    whole = video.stat().st_size <= inline_mb * 1024 * 1024
    if whole:
        parts.append({"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(video.read_bytes()).decode()}})
    frames = extract_frames(ff, video, frame_times(c["seconds"]), folder) if ff else []
    for t, f in frames:
        parts += [{"text": f"Frame at {t:.2f} s:"}, {"inline_data": {"mime_type": "image/jpeg", "data": _jpeg(f, 640)}}]
    if not whole and not frames:
        raise ValueError("the clip is too large to send whole and FFmpeg is not configured to take frames from it")
    prompt = prompt_for([(p.name, p.visual_description or "") for p in people], c["seconds"], speaking_text(c),
                        acting_notes(db, ep.id, c["shot"]), [t for t, _ in frames], whole,
                        schemas_for(allowed_for(db, ep, c), c["step"]), bool(c.get("realistic")))
    parts.append({"text": prompt})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2, "maxOutputTokens": MAX_OUT}}
    return body, len([p for p in people if approved_master(db, p.id)]) + len(frames), whole


def post_to_thread(db: Session, ep: Episode, c: dict, res: dict, model: str, usd: float) -> str:
    """The result as an assistant message in the shot's chat thread, with one proposal (pending: the owner applies)."""
    from . import shot_chat as SC
    ref = SC.Ref(episode_id=ep.id, step=c["step"], item=str(c["shot"]))
    msg = {"id": pysecrets.token_hex(5), "role": "assistant", "text": message_text(res), "at": time.time(),
           "model": f"{AUTHOR} · {model}", "author": AUTHOR, "usd": usd, "clip_id": c["clip_id"],
           "issues": res["issues"]}
    p = best_fix(res)
    if p:
        msg["proposal"] = p
        msg["proposal_status"] = "pending"
    SC.add_messages(db, ref, [msg], usd)
    return msg["id"]


@task
def clip_qa(ctx: Ctx) -> dict:
    from . import acting_analysis as AA
    from .config import get_settings
    from .providers import ProviderError
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    want = set(p.get("keys") or [])
    confirm = float(p.get("confirm_usd") or 0)
    prov = provider(db)
    if not prov["ready"]:
        raise ProviderError(prov["note"])
    api_key = secret("gemini_api_key", db)
    q = get_section(db, "quality")
    ff = get_settings().ffmpeg
    folder = ctx.folder("episodes", ep.id, f"quality-job{job.id}")
    done, failed, skipped, spent = [], [], [], 0.0
    try:
        for c in [c for c in clips(db, ep) if check_key(c) in want]:
            est = clip_estimate(db, ep, c, prov, float(q["qa_inline_mb"]))
            if spent + est["usd_max"] > confirm + 1e-9:
                skipped.append(c["shot"])
                ctx.log(f"shot {c['shot']}: not checked, it would pass the confirmed ${confirm:.4f}")
                continue
            d = folder / f"shot{c['shot']:03d}"
            d.mkdir(parents=True, exist_ok=True)
            try:
                a = db.get(Asset, c["asset_id"])
                if a is None:
                    raise ValueError("the clip is missing from storage")
                video = storage().get_to_file(a.storage_key, d / "clip.mp4")
                body, _pics, _whole = request_for(db, ep, c, video, d, float(q["qa_inline_mb"]), ff)
                with AA.client() as cl:
                    model, resp = AA.generate(cl, api_key, [prov["model"]], body, ctx.log)
                res = parse(AA.answer_text(resp), c["step"], str(c["shot"]), allowed_for(db, ep, c), c["seconds"])
                u = resp.get("usageMetadata") or {}
                usd = 0.0 if prov["free"] else round(int(u.get("promptTokenCount") or 0) * prov["usd_in"] / 1e6 +
                                                     (int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0))
                                                     * prov["usd_out"] / 1e6, 6)
                spent += max(usd, 0.0) if not prov["free"] else 0.0
                db.expire_all()
                v = stored(db, ep.id)
                mid = post_to_thread(db, ep, c, res, model, usd)
                v.setdefault("checks", {})[check_key(c)] = {**res, "model": model, "usd": usd, "at": time.time(),
                                                           "free_tier": prov["free"], "message_id": mid, "shot": c["shot"],
                                                           "step": c["step"], "clip_id": c["clip_id"]}
                v["usd"] = round((v.get("usd") or 0.0) + usd, 6)
                save(db, ep.id, v)
                db.add(Event(episode_id=ep.id, kind="episode", message=f"Quality check of shot {c['shot']} by {model}: "
                             f"{len(res['issues'])} problem(s) (${usd:.4f})"))
                db.commit()
                done.append(c["shot"])
            except (ProviderError, ValueError) as e:
                db.rollback()
                failed.append(c["shot"])
                ctx.log(f"shot {c['shot']}: {str(e)[:300]}")
                # a paid call that failed may still have been billed: count its "at most" against the confirmed amount
                spent += est["usd_max"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if failed and not done:
        raise ProviderError(f"the quality check failed for shot(s) {', '.join(map(str, failed))}; see the log")
    return {"done": done, "failed": failed, "skipped": skipped, "usd": round(spent, 6)}
