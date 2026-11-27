"""Character descriptions without Gemini (2026-11-27, owner request): who writes the words of the Cast step.

Providers (Settings > Cast styles "describer", or the choice on the Cast step; cast_from_video.DESCRIBERS):
  gemini  the default: Gemini watches the reference video (paid tier, or the free tier only when ticked, with its
          training warning) - cast_from_video.describe.
  local   FREE and PRIVATE: a small open-source vision-language model runs inside the API worker on the server's CPU.
          Model: SmolVLM-256M-Instruct by Hugging Face (Apache-2.0), pinned to revision MODEL_REVISION, run with
          transformers (pinned in the Dockerfile with the CPU build of torch; both have wheels for the image's Python
          3.13). The weights (about 1 GB) are downloaded ONCE into the models volume (LOCAL_VLM_DIR, /data/models/vlm)
          on first use; the job log says so. Only the weights come IN: no frame, no word of the episode leaves the
          server.
          For each speaker, ffmpeg takes up to FRAMES_PER_PERSON frames from the private reference video at the middle
          of that person's longest lines (the speaker labels' line times), into the job's own work folder. The model
          is asked for the outward look only (age range, build, hair, clothing colours, one signature accessory) in a
          fixed JSON shape; the answer is normalised like Gemini's (cast_from_video.normalise_descriptions), the
          personality comes from the acting analysis when there is one, and the folder (frames included) is deleted
          afterwards, also on failure. Results are marked "described on this server (free)"; the owner edits them.
  manual  the owner types: blank descriptions, one per name, to fill in (always available, free).
  gpu     NOT BUILT: the extension point for a larger open model (e.g. Qwen-VL) on the owner's own GPU / the GPU worker.
          It would implement the same run(images, prompt, log) -> str as LocalRunner and be chosen in runner().

When Gemini answers 429/503, when there is no Gemini key, or when the owner prefers it, the Cast step offers "Describe
on this server instead - free, private, a few minutes per character" (info()["offer"]).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event, Job
from .queue import enqueue

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

MODEL_ID = "HuggingFaceTB/SmolVLM-256M-Instruct"
MODEL_REVISION = "d039ab0d4b9311b617e8ffec1d06c8464364aeb3"
MODEL_LABEL = "SmolVLM-256M (Apache-2.0), on this server"
FRAMES_PER_PERSON = 2        # a CPU run takes minutes per picture batch: two frames per person keep it bearable
MAX_NEW_TOKENS = 200
MINUTES_NOTE = "free, private, a few minutes per character on the server's CPU"   # measured: ~3 min per picture batch on a laptop
LOCAL_NOTE = "described on this server (free)"
BUSY_MARKS = ("HTTP 429", "HTTP 503")

PROMPT = ("Look at the person who is talking in these pictures. We are designing an ORIGINAL cartoon character from "
          "their outward look only. Do not describe the face. Answer with JSON only, in exactly this shape:\n"
          '{"age": "approximate age range, e.g. 30s", "build": "slim, average, stocky, tall or short", '
          '"hair": {"style": "...", "colour": "..."}, "clothing": [{"garment": "...", "colour": "..."}], '
          '"accessory": "ONE signature accessory, e.g. glasses, a cap, a tie"}')

_runner = None            # tests only: a callable(images: list[Path], prompt: str, log) -> str instead of the model


def set_test_runner(r) -> None:
    global _runner
    _runner = r


def models_dir() -> Path:
    from .config import get_settings
    return Path(os.environ.get("LOCAL_VLM_DIR") or (get_settings().work_dir.parent / "models" / "vlm"))


def installed() -> bool:
    """The model's runtime (torch and transformers) is installed in this image."""
    return _runner is not None or (importlib.util.find_spec("torch") is not None
                                   and importlib.util.find_spec("transformers") is not None)


def downloaded() -> bool:
    return (models_dir() / ("models--" + MODEL_ID.replace("/", "--"))).exists()


class LocalRunner:
    """SmolVLM on the CPU with transformers, loaded once per worker process."""
    _model = None
    _processor = None

    def load(self, log) -> None:
        if LocalRunner._model is not None:
            return
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")      # nothing about the studio is sent to the hub
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        cache = models_dir()
        cache.mkdir(parents=True, exist_ok=True)
        if not downloaded():
            log(f"Downloading the describer model {MODEL_ID} once into {cache} (about 1 GB; later runs start at once)")
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        LocalRunner._processor = AutoProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache))
        LocalRunner._model = AutoModelForImageTextToText.from_pretrained(MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache),
                                                                         dtype=torch.float32).eval()
        log("Describer model loaded")

    def __call__(self, images: list[Path], prompt: str, log) -> str:
        import torch
        from PIL import Image
        self.load(log)
        p, m = LocalRunner._processor, LocalRunner._model
        msgs = [{"role": "user", "content": [*({"type": "image"} for _ in images), {"type": "text", "text": prompt}]}]
        text = p.apply_chat_template(msgs, add_generation_prompt=True)
        pics = [Image.open(f).convert("RGB") for f in images]
        inp = p(text=text, images=pics, return_tensors="pt")
        with torch.inference_mode():
            out = m.generate(**inp, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
        return p.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]


def runner():
    """The model that answers: the test stand-in, or SmolVLM on the CPU. (A future "gpu" provider plugs in here.)"""
    return _runner if _runner is not None else LocalRunner()


# ================================================================== pure parts
def frame_times(lines: list[dict], names: dict[str, str], offset: float = 0.0, n: int = FRAMES_PER_PERSON) -> dict[str, list[float]]:
    """Per person (a speaker label, or a character key shown as its name): the middle of their n longest lines, in time
    order, on the video's timeline (+ offset when the episode uses a window of it)."""
    by: dict[str, list[dict]] = {}
    for ln in lines:
        s = (ln.get("speaker") or "").strip()
        if s:
            by.setdefault(names.get(s, s), []).append(ln)
    out = {}
    for name, ls in by.items():
        longest = sorted(ls, key=lambda x: float(x["end"]) - float(x["start"]), reverse=True)[:n]
        out[name] = sorted(round((float(x["start"]) + float(x["end"])) / 2 + offset, 2) for x in longest)
    return out


def parse_answer(text: str) -> dict:
    """The model's JSON (the first {...} in the answer), or {} when it cannot be read."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def made_by(describe: dict) -> str | None:
    p = (describe or {}).get("provider")
    return LOCAL_NOTE if p == "local" else "typed by you" if p == "manual" else "Gemini" if describe else None


def info(db: Session, ep: Episode, last_job: Job | None) -> dict:
    """What the Cast step shows about the free describer, and whether to offer it now."""
    from .secrets_store import secret
    from .settings_store import get_section
    provider = get_section(db, "cast").get("describer") or "gemini"
    gemini_busy = bool(last_job and last_job.kind == "cast_describe" and last_job.status == "failed"
                       and any(m in (last_job.error or "") for m in BUSY_MARKS))
    reason = ("Gemini is busy or out of quota" if gemini_busy else "there is no Gemini key" if not secret("gemini_api_key", db)
              else "you chose this server" if provider == "local" else "")
    return {"installed": installed(), "downloaded": downloaded(), "model": MODEL_LABEL, "note": MINUTES_NOTE,
            "offer": bool(reason), "reason": reason}


# ================================================================== routes
class DescriberIn(BaseModel):
    provider: str


@router.put("/cast/describer")
def set_describer(body: DescriberIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from .cast_from_video import DESCRIBERS
    from .settings_store import put_section
    if body.provider not in DESCRIBERS:
        raise HTTPException(422, f"choose one of {', '.join(DESCRIBERS)}")
    put_section(db, "cast", {"describer": body.provider})
    db.add(Event(kind="character", message=f"Character descriptions: {body.provider} (chosen by {user})"))
    db.commit()
    return {"provider": body.provider}


@router.post("/episodes/{eid}/cast-video/describe-local")
def describe_local(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Free and private: describe each speaker from a few frames of the reference video, on this server's CPU."""
    from . import cast_from_video as CV
    from . import guided
    ep = CV._episode(db, eid)
    if not guided.reference_video(db, ep.id):
        raise HTTPException(409, "upload the reference video first (step 1)")
    if not installed():
        raise HTTPException(409, "the describer model's runtime (torch and transformers) is not installed on this server: "
                                 "rebuild the API image, or describe with Gemini or by hand")
    if not frame_times((ep.audio_transcript or {}).get("lines") or [], {}):
        raise HTTPException(409, "give the lines their speakers first (Lines and speakers): the frames are taken where each person talks")
    if CV._describe_active(db, ep.id):
        raise HTTPException(409, "the characters are already being described")
    job = enqueue(db, CV.JOB_DESCRIBE_LOCAL, episode_id=ep.id, payload={"by": user})
    db.add(Event(episode_id=ep.id, kind="episode", message=f"Characters described on this server asked by {user} (free)"))
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/cast-video/describe-manual")
def describe_manual(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Free: one blank description per name (the cast and the speaker labels) for the owner to type. Descriptions that
    already exist are kept."""
    from . import cast_from_video as CV
    ep = CV._episode(db, eid)
    names = CV.cast_names(db, ep)
    if not names:
        raise HTTPException(409, "there are no names yet: give the lines their speakers first")
    have = {d["name"].lower(): d for d in CV.stored(db, ep.id).get("characters") or []}
    blank = CV.normalise_descriptions([{"name": n} for n in names if n.lower() not in have], names)
    descs = list(have.values()) + blank
    CV.store_descriptions(db, ep, descs, {"made": time.time(), "model_used": "you", "usd": 0.0, "provider": "manual"},
                          f"Blank descriptions to type added by {user} ({len(blank)})")
    return CV.view(db, ep)


# ================================================================== the job
from .tasks import Ctx, task  # noqa: E402


@task
def cast_describe_local(ctx: Ctx) -> dict:
    from . import acting_analysis as AA
    from . import cast_from_video as CV
    from . import guided, media
    from .speaker_suggest import _offset
    from .storage import storage
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    ref = guided.reference_video(db, ep.id)
    if not ref:
        raise ValueError("the reference video was removed: upload it again")
    names = {c.key: c.name for c in db.query(Character)}
    times = frame_times((ep.audio_transcript or {}).get("lines") or [], names, _offset(ref))
    if not times:
        raise ValueError("give the lines their speakers first: the frames are taken where each person talks")
    cast = CV.cast_names(db, ep)
    traits = (AA.stored(db, ep.id).get("result") or {}).get("characters") or {}
    folder = ctx.folder("episodes", ep.id, f"cast-local-job{job.id}")       # the server's own work folder
    run = runner()
    raw = []
    t0 = time.time()
    try:
        video = storage().get_to_file(ref["key"], folder / f"reference{Path(ref['key']).suffix or '.mp4'}")
        for i, (name, ts) in enumerate(times.items()):
            frames = [f for f, _t in media.sample_frames_at(video, folder / f"person{i + 1}", ts)]
            if not frames:
                ctx.log(f"{name}: no frame could be read; left for you to fill in")
                raw.append({"name": name})
                continue
            text = run(frames, PROMPT, ctx.log)
            answer = parse_answer(text)
            if not answer and text.strip():
                # a small model often answers in a plain sentence ("The person is wearing a beige dress."): kept as a
                # note in the role field for the owner to sort into the right fields
                answer = {"role": f"Seen on this server: {text.strip()}"}
                ctx.log(f"{name}: the model answered in words, not the JSON shape; kept as a note to edit")
            elif not answer:
                ctx.log(f"{name}: the model gave no answer; left for you to fill in")
            raw.append({**{k: v for k, v in answer.items() if k != "name"}, "name": name})
            ctx.log(f"{name}: described from {len(frames)} frame(s)")
    finally:
        shutil.rmtree(folder, ignore_errors=True)                   # frames and the video copy never stay
    descs = CV.normalise_descriptions(raw, cast, traits)
    for d in descs:
        d["described_by"] = LOCAL_NOTE
    CV.store_descriptions(db, ep, descs, {"made": time.time(), "model_used": MODEL_LABEL, "usd": 0.0, "provider": "local",
                                          "seconds": round(time.time() - t0, 1)},
                          f"Characters from the video: {len(descs)} {LOCAL_NOTE}")
    return {"characters": len(descs), "usd": 0.0}
