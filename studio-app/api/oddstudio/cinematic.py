"""Cinematic mode (owner direction 2026-11-27: "one will be cartoon and the other real cinematic"): realistic, INVENTED
human actors with real acting and lip-synced dialogue, side by side with the cartoon mode in the same dashboard.
Episodes carry episodes.mode = "cinematic" (migration 0017); every cartoon episode keeps today's flow unchanged.

The steps (the page /episodes/<id>/cinematic and the autopilot's cinematic order):
  1. Story: an idea / logline, a Bible passage reference + the owner's angle (scripture text only from a public-domain
     translation: scripture.py refuses or flags anything else), or the owner's own script.
  2. Screenplay: GPT (prompt_writer's model and prices, cost first, confirm_usd) writes scenes and shots (shot size,
     camera move, action, VFX notes) with dialogue lines (speaker + emotion). Without a key or credit a template is
     made (labelled "template"; the owner's script is parsed line by line). The owner edits and approves it.
  3. Cast: the screenplay's characters become this episode's characters (no reference video), described in words, in
     the "Cinematic realistic" preset (cast_styles.py: invented people, never a real likeness). Candidates, approval
     and the cast library are cast_from_video.py's, unchanged. A voice per character (cinematic_tts.py).
  4. Locations: room_sets.py walls, generalised: one realistic establishing picture per screenplay location (Nano
     Banana on WaveSpeed, its make/approve routes); the owner approves one take each.
  5. Shot stills: per shot, Nano Banana (WaveSpeed; location + every master as references) or Qwen-Image-Edit-2511 on
     the rented GPU (up to three references, masters first; free beyond GPU time). Optional END still per shot for
     first+last-frame motion. The owner approves each still.
  6. Voices: each dialogue line spoken by Kokoro on the studio server (free; licences checked) or the owner's own
     recording. The owner listens and approves; only approved takes drive the talking shots.
  7. Shots: motion shots = Wan 2.2 i2v 14B (4-step) from the approved still (cinematic_graphs.py); dialogue shots =
     Speech-to-Video "B" (talking_s2v.build_graph) from the approved still and the approved line. One GPU job, the
     rented ComfyUI session and gpu.py's monthly cap; cost first (confirm_usd, 409).
  8. Quality check: clip_qa.py with the realistic checklist (identity, extra fingers/limbs, face warping, VFX glitches,
     camera jumps, lip sync).
  9. Assembly: approved clips (or approved stills, held) in screenplay order, the approved voice takes at their shots,
     the owner's royalty-free music (optional upload; no music generation), captions optional. Free (FFmpeg).
 10. YouTube disclosure: the final cut and publish steps show "Contains realistic AI-generated people — tick 'Altered or
     synthetic content' when uploading"; the owner's tick is saved and the final cut can only be approved with it.

Rules kept: nothing is approved by itself (every approval is an owner's route); every paid action shows its cost and
the request must carry it (confirm_usd, 409 otherwise); GPU work respects the monthly cap; keys only through
secrets_store.secret(); no real person's likeness (INVENTED_PEOPLE_RULE in every picture and motion prompt).

Storage: settings row `cinema:<episode id>` (story, screenplay, characters, locations, shots, lines, music, disclosure,
cuts). Pictures, clips and voice takes are Asset rows of the episode.
"""
from __future__ import annotations

import json
import math
import random
import re
import secrets as pysecrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import cinematic_graphs as G
from . import cinematic_tts as TTS
from . import serialize as S
from .auth import current_user
from .cast_styles import CINEMATIC_STYLE, INVENTED_PEOPLE_RULE
from .db import get_db
from .models import Asset, Character, Episode, Event, Job, Review, Setting
from .queue import enqueue
from .secrets_store import secret
from .settings_store import get_section
from .storage import sha256_file, storage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

MODE = "cinematic"
JOB_STILL, JOB_GPU, JOB_VOICE, JOB_ASSEMBLY = "cinematic_still", "cinematic_gpu", "cinematic_voice", "cinematic_assembly"
JOBS = (JOB_STILL, JOB_GPU, JOB_VOICE, JOB_ASSEMBLY)
SOURCES = ("idea", "bible", "script")
STILL_PROVIDERS = {"nano": "Nano Banana 2.1 on WaveSpeed (paid per picture)",
                   "qwen": "Qwen-Image-Edit-2511 on the rented GPU (free beyond GPU time)"}
VOICE_SOURCES = {"tts": "Kokoro on the studio server (free)", "upload": "Your own recordings"}
MAX_CHARACTERS, MAX_LOCATIONS, MAX_SHOTS, MAX_LINE = 8, 8, 60, 300
SCREENPLAY_MAX_TOKENS = 8000
TEMPLATE_LABEL = "template (GPT unavailable): edit it before you approve"
DISCLOSURE = "Contains realistic AI-generated people — tick 'Altered or synthetic content' when uploading"
MAX_AUDIO_BYTES = 30 * 1024 * 1024
AUDIO_TYPES = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/mpeg": ".mp3",
               "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".m4a", "audio/ogg": ".ogg", "audio/flac": ".flac"}
POLL_S = 5.0


def key(eid: int) -> str:
    return f"cinema:{eid}"


def is_cinematic(ep: Episode | None) -> bool:
    return bool(ep is not None and (getattr(ep, "mode", None) or "cartoon") == MODE)


# ================================================================== settings (Settings > Cinematic)
def check_settings(v: dict) -> None:
    if v.get("still_provider", "nano") not in STILL_PROVIDERS:
        raise ValueError(f"cinematic.still_provider must be one of {', '.join(STILL_PROVIDERS)}")
    if v.get("voice_source", "tts") not in VOICE_SOURCES:
        raise ValueError(f"cinematic.voice_source must be one of {', '.join(VOICE_SOURCES)}")
    TTS.choose_engine(v.get("voice_engine", "kokoro"))
    mv = v.get("music_volume", 0.25)
    if not (isinstance(mv, (int, float)) and not isinstance(mv, bool) and 0.0 <= mv <= 1.0):
        raise ValueError("cinematic.music_volume must be between 0 and 1")
    if not isinstance(v.get("captions", False), bool):
        raise ValueError("cinematic.captions must be true or false")


# ================================================================== the story input (pure)
def check_story(src: str, idea: str = "", passage: str = "", translation: str = "", scripture_text: str = "",
                confirm_public_domain: bool = False, angle: str = "", script: str = "") -> dict:
    """The story input as stored, or ValueError (refused) / LookupError (flagged scripture text: needs the owner's
    confirmation). Only public-domain scripture text is ever kept."""
    from . import scripture
    if src not in SOURCES:
        raise ValueError("choose where the story comes from: an idea, a Bible passage or your own script")
    out: dict = {"source": src}
    if src == "idea":
        if len(idea.strip()) < 10:
            raise ValueError("write the idea or logline in at least a sentence")
        out["idea"] = idea.strip()[:4000]
    elif src == "script":
        if len(script.strip()) < 20:
            raise ValueError("paste your script (at least a few lines)")
        out["script"] = script.strip()[:30000]
    else:
        ref = scripture.parse_reference(passage)
        out.update(passage=ref["text"], reference=ref, angle=angle.strip()[:2000])
        t = scripture.normalise_translation(translation or "KJV")
        if scripture_text.strip():
            chk = scripture.check_text(scripture_text, t)
            if chk["status"] == "refused":
                raise ValueError("; ".join(chk["reasons"]))
            if chk["status"] == "flagged" and not confirm_public_domain:
                raise LookupError("; ".join(chk["reasons"]))
            out.update(scripture_text=scripture_text.strip(), check=chk, confirmed_public_domain=bool(confirm_public_domain))
        elif t not in scripture.PUBLIC_DOMAIN:
            raise ValueError(f"\"{translation}\" is not a public-domain translation ({', '.join(scripture.PUBLIC_DOMAIN)})")
        out["translation"] = t
    return out


# ================================================================== the screenplay (pure)
def _txt(x, n: int) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()[:n]


def _name_key(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(n or "").lower()).strip()


def parse_screenplay(raw) -> dict:
    """GPT's (or the owner's) screenplay checked and normalised: {title, logline, characters, locations, scenes,
    warnings}. Each shot: size (SIZES), camera (CAMERAS), action, characters (names of the cast), vfx, seconds (2-10)
    and at most ONE dialogue line {speaker, text, emotion}; a shot with several lines becomes one shot per line.
    ValueError (plain words) when it cannot be used."""
    if isinstance(raw, str):
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            raw = json.loads(m.group(0) if m else raw)
        except (ValueError, TypeError):
            raise ValueError("the screenplay is not readable JSON")
    if not isinstance(raw, dict):
        raise ValueError("the screenplay is not an object")
    warn: list[str] = []
    chars: list[dict] = []
    seen: dict[str, dict] = {}

    def add_char(c: dict | str) -> dict | None:
        c = {"name": c} if isinstance(c, str) else (c if isinstance(c, dict) else {})
        name = _txt(c.get("name"), 60)
        if not name:
            return None
        k = _name_key(name)
        if k in seen:
            return seen[k]
        if len(chars) >= MAX_CHARACTERS:
            warn.append(f"only {MAX_CHARACTERS} characters are kept; {name} was left out")
            return None
        d = {"name": name, "role": _txt(c.get("role"), 200), "age": _txt(c.get("age"), 40), "build": _txt(c.get("build"), 120),
             "hair": _txt(c.get("hair"), 160), "clothing": _txt(c.get("clothing") or c.get("costume"), 400),
             "distinctive": _txt(c.get("distinctive") or c.get("look") or c.get("accessory"), 300),
             "personality": _txt(c.get("personality"), 300), "voice": _txt(c.get("voice") or c.get("voice_hint"), 120)}
        chars.append(d)
        seen[k] = d
        return d

    for c in raw.get("characters") or []:
        add_char(c)
    locs: list[dict] = []
    lseen: dict[str, dict] = {}

    def add_loc(name: str, desc: str = "") -> dict | None:
        name = _txt(name, 80)
        if not name:
            return None
        k = _name_key(name)
        if k in lseen:
            if desc and not lseen[k]["description"]:
                lseen[k]["description"] = _txt(desc, 800)
            return lseen[k]
        if len(locs) >= MAX_LOCATIONS:
            warn.append(f"only {MAX_LOCATIONS} locations are kept; {name} was left out")
            return locs[-1] if locs else None
        d = {"name": name, "description": _txt(desc, 800)}
        locs.append(d)
        lseen[k] = d
        return d

    for loc in raw.get("locations") or []:
        if isinstance(loc, dict):
            add_loc(loc.get("name"), loc.get("description") or "")
        elif isinstance(loc, str):
            add_loc(loc)
    scenes = []
    total = 0
    for si, sc in enumerate(raw.get("scenes") or [], 1):
        if not isinstance(sc, dict):
            continue
        loc = add_loc(sc.get("location") or sc.get("heading") or f"Location {si}")
        shots = []
        for sh in sc.get("shots") or []:
            if not isinstance(sh, dict):
                continue
            size = G.norm_size(sh.get("size") or sh.get("shot_size") or "")
            cam, cam_note = G.norm_camera(sh.get("camera") or sh.get("camera_move") or "")
            people = []
            for nm in sh.get("characters") or []:
                c = seen.get(_name_key(nm if isinstance(nm, str) else (nm or {}).get("name", "")))
                if c is None and isinstance(nm, str) and nm.strip():
                    c = add_char(nm)
                    if c:
                        warn.append(f"{c['name']} appears in a shot but was not in the character list: added")
                if c and c["name"] not in people:
                    people.append(c["name"])
            lines = sh.get("dialogue") if isinstance(sh.get("dialogue"), list) else ([sh["line"]] if isinstance(sh.get("line"), dict) else [])
            base = {"size": size, "camera": cam, "camera_note": cam_note, "action": _txt(sh.get("action"), 600),
                    "vfx": _txt(sh.get("vfx"), 400), "characters": people}
            try:
                secs = float(sh.get("seconds") or 5)
            except (TypeError, ValueError):
                secs = 5.0
            base["seconds"] = round(min(10.0, max(2.0, secs)), 1)
            good = []
            for ln in lines:
                if not isinstance(ln, dict):
                    continue
                text = _txt(ln.get("text"), MAX_LINE)
                if not text:
                    continue
                sp = seen.get(_name_key(ln.get("speaker")))
                if sp is None:
                    sp = add_char(_txt(ln.get("speaker"), 60) or "Narrator")
                    if sp is None:
                        continue
                    warn.append(f"{sp['name']} speaks but was not in the character list: added")
                good.append({"speaker": sp["name"], "text": text, "emotion": _txt(ln.get("emotion"), 40) or "neutral"})
            for ln in good or [None]:
                if total >= MAX_SHOTS:
                    warn.append(f"only {MAX_SHOTS} shots are kept")
                    break
                s = dict(base, characters=list(people), line=ln)
                if ln and ln["speaker"] not in s["characters"]:
                    s["characters"].insert(0, ln["speaker"])
                shots.append(s)
                total += 1
        if shots:
            scenes.append({"id": f"s{len(scenes) + 1}", "heading": _txt(sc.get("heading"), 160) or (loc["name"] if loc else ""),
                           "location": loc["name"] if loc else "", "shots": shots})
    if not scenes:
        raise ValueError("the screenplay has no shots")
    return {"title": _txt(raw.get("title"), 120), "logline": _txt(raw.get("logline"), 400), "characters": chars,
            "locations": locs, "scenes": scenes, "warnings": warn}


SCENE_HEAD = re.compile(r"^\s*(?:INT\.|EXT\.|INT/EXT\.|I/E\.)\s*(.+?)(?:\s+-\s+(.+))?\s*$", re.I)
LINE = re.compile(r"^\s*([A-Z][A-Za-z .'\-]{0,40}?)\s*(?:\(([^)]{1,40})\))?\s*:\s*(.+)$")
VFX = re.compile(r"^\s*\[(?:VFX|FX|EFFECT)\s*:\s*(.+?)\]\s*$", re.I)


def parse_script_text(text: str) -> dict:
    """The owner's plain script as a raw screenplay: "INT. THRONE ROOM - NIGHT" starts a scene at that location,
    "KING (angry): Kneel." is a dialogue shot, "[VFX: fire bursts from his hands]" adds a VFX note to the shot before,
    any other line is an action shot."""
    scenes: list[dict] = []
    cur = None
    for raw_line in str(text or "").splitlines():
        ln = raw_line.strip()
        if not ln:
            continue
        m = SCENE_HEAD.match(ln)
        if m:
            cur = {"location": m.group(1).strip().title(), "heading": ln, "shots": []}
            scenes.append(cur)
            continue
        if cur is None:
            cur = {"location": "Main location", "heading": "", "shots": []}
            scenes.append(cur)
        m = VFX.match(ln)
        if m:
            if cur["shots"]:
                cur["shots"][-1]["vfx"] = (cur["shots"][-1].get("vfx", "") + " " + m.group(1)).strip()
            else:
                cur["shots"].append({"size": "wide", "camera": "static", "action": "", "vfx": m.group(1)})
            continue
        m = LINE.match(ln)
        if m and not ln.lower().startswith(("note:", "http")):
            who = m.group(1).strip().title()
            cur["shots"].append({"size": "medium close", "camera": "static", "characters": [who],
                                 "line": {"speaker": who, "text": m.group(3).strip(), "emotion": (m.group(2) or "").strip()}})
            continue
        cur["shots"].append({"size": "wide", "camera": "static", "action": ln})
    names = []
    for sc in scenes:
        for sh in sc["shots"]:
            for n in sh.get("characters") or []:
                if n not in names:
                    names.append(n)
    return {"title": "", "logline": "", "characters": [{"name": n} for n in names],
            "locations": [{"name": sc["location"]} for sc in scenes], "scenes": scenes}


def template_screenplay(story: dict) -> dict:
    """A screenplay without GPT, labelled as a template: the owner's script parsed line by line, or a short outline of
    the idea / passage for the owner to fill in."""
    if story.get("source") == "script":
        return parse_script_text(story.get("script") or "")
    if story.get("source") == "bible":
        about = f"{story.get('passage')}" + (f": {story['angle']}" if story.get("angle") else "")
        loc = "The place where the passage happens"
    else:
        about = story.get("idea") or ""
        loc = "Main location"
    return {"title": "", "logline": about[:300], "characters": [{"name": "Protagonist", "role": "the main character"},
                                                                {"name": "Rival", "role": "the opposing character"}],
            "locations": [{"name": loc, "description": ""}],
            "scenes": [{"location": loc, "heading": "Opening", "shots": [
                {"size": "extreme wide", "camera": "crane down", "action": f"Establishing shot. {about[:300]}"},
                {"size": "medium", "camera": "push in", "characters": ["Protagonist"], "action": "The protagonist enters."},
                {"size": "close", "camera": "static", "characters": ["Rival"],
                 "line": {"speaker": "Rival", "text": "(Write the first line here.)", "emotion": "cold"}},
                {"size": "close", "camera": "static", "characters": ["Protagonist"],
                 "line": {"speaker": "Protagonist", "text": "(Write the answer here.)", "emotion": "defiant"}}]}]}


SCREENPLAY_SYSTEM = """You are a screenwriter and director for a small studio that makes short live-action-style films
with AI video models (realistic invented actors, real acting, lip-synced dialogue, short cinematic shots and visual
effects). Write ONE screenplay as JSON only, no explanation:
{"title": "...", "logline": "...",
 "characters": [{"name": "...", "role": "...", "age": "...", "build": "...", "hair": "...", "clothing": "...",
                 "distinctive": "one visual detail that tells them apart", "personality": "...", "voice": "male|female, timbre"}],
 "locations": [{"name": "...", "description": "what the place looks like, period, light"}],
 "scenes": [{"heading": "...", "location": "<a location name>",
             "shots": [{"size": "extreme wide|wide|medium|medium close|close|extreme close|over the shoulder|insert",
                        "camera": "static|push in|pull out|pan left|pan right|tilt up|tilt down|tracking|orbit|crane up|crane down|handheld",
                        "action": "what we see happen, in one or two sentences", "characters": ["<names in the shot>"],
                        "vfx": "visual effect, or empty", "seconds": 5,
                        "line": null or {"speaker": "<name>", "text": "<one spoken line, at most 25 words>", "emotion": "<one word>"}}]}]}
Rules: at most 8 characters, 4 locations and 24 shots; each shot is 3-8 seconds and has at most ONE spoken line;
dialogue shots are medium close or close so the face is clear; every character is an INVENTED person and must not be
or resemble a real person, celebrity or actor (Biblical figures are portrayed by invented actors, never by any real
actor's likeness); no brand names. Scripture: quote only from the King James Version or the World English Bible
(public domain), or paraphrase in your own words; never use the wording of any other translation."""


def screenplay_message(story: dict) -> str:
    if story.get("source") == "idea":
        return f"THE IDEA / LOGLINE FROM THE OWNER:\n{story['idea']}"
    if story.get("source") == "script":
        return ("THE OWNER'S SCRIPT (keep its story, its lines and their order; add shot sizes, camera moves, actions and "
                f"VFX notes):\n{story['script']}")
    parts = [f"BIBLE PASSAGE: {story['passage']} ({story.get('translation') or 'KJV'})"]
    if story.get("scripture_text"):
        parts.append(f"THE PASSAGE TEXT ({story.get('translation')}, public domain):\n{story['scripture_text']}")
    if story.get("angle"):
        parts.append(f"THE OWNER'S ANGLE:\n{story['angle']}")
    return "\n\n".join(parts)


def shots_of(sp: dict | None) -> list[dict]:
    """The screenplay's shots in order, numbered 1..N: {n, scene, location, size, camera, camera_note, action,
    characters, vfx, seconds, line, line_id}. A dialogue shot's line id is "L<n>"."""
    out = []
    for sc in (sp or {}).get("scenes") or []:
        for sh in sc.get("shots") or []:
            n = len(out) + 1
            out.append({**sh, "n": n, "scene": sc.get("id"), "location": sc.get("location") or "",
                        "kind": "talk" if sh.get("line") else "motion", "line_id": f"L{n}" if sh.get("line") else None})
    return out


def lines_of(sp: dict | None) -> list[dict]:
    return [{"id": s["line_id"], "n": s["n"], **s["line"]} for s in shots_of(sp) if s.get("line")]


def location_template(name: str, description: str) -> str:
    """A realistic establishing picture of one location (room_sets "wall" generalised). No people; it is passed as a
    reference to the shot stills for the place, its materials and its light."""
    d = description.strip().rstrip(".")
    return (f"A photorealistic establishing film still of an empty location: {name.strip().rstrip('.')}."
            + (f" {d}." if d else "") +
            " Eye-level wide framing, natural cinematic lighting, realistic materials and textures, atmospheric depth, "
            "16:9. Nobody in the picture: no people, no animals. No text, no watermark.")


# ================================================================== state
def stored(db: Session, eid: int) -> dict:
    row = db.get(Setting, key(eid))
    return json.loads(json.dumps(row.value)) if row else {}


def save(db: Session, eid: int, v: dict) -> None:
    row = db.get(Setting, key(eid))
    if row:
        row.value = dict(v)
    else:
        db.add(Setting(key=key(eid), value=dict(v)))


def _event(db: Session, eid: int, msg: str, kind: str = "episode") -> None:
    db.add(Event(episode_id=eid, kind=kind, message=msg))


def _episode(db: Session, eid: int) -> Episode:
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    if not is_cinematic(ep):
        raise HTTPException(409, "this is a cartoon episode: the cinematic steps are for cinematic episodes only")
    return ep


def config(db: Session, v: dict | None = None) -> dict:
    """Settings > Cinematic, with the episode's own choices over it."""
    c = get_section(db, "cinematic")
    for k in ("still_provider", "voice_source", "captions", "music_volume"):
        if v and k in (v.get("settings") or {}):
            c[k] = v["settings"][k]
    return c


def screenplay(v: dict) -> dict | None:
    return (v.get("screenplay") or {}).get("content")


def screenplay_approved(v: dict) -> bool:
    return bool((v.get("screenplay") or {}).get("approved"))


def _shot_state(v: dict, n: int) -> dict:
    return v.setdefault("shots", {}).setdefault(str(n), {})


def _line_state(v: dict, lid: str) -> dict:
    return v.setdefault("lines", {}).setdefault(lid, {})


def _take(takes: list, tid: str | None) -> dict | None:
    return next((t for t in takes or [] if t.get("id") == tid), None) if tid else None


def approved_still(v: dict, n: int, end: bool = False) -> dict | None:
    st = (v.get("shots") or {}).get(str(n)) or {}
    return _take(st.get("end_stills" if end else "stills"), st.get("end_approved" if end else "approved"))


def approved_line(v: dict, lid: str | None) -> dict | None:
    if not lid:
        return None
    st = (v.get("lines") or {}).get(lid) or {}
    return _take(st.get("takes"), st.get("approved"))


def approved_render(v: dict, n: int) -> dict | None:
    st = (v.get("shots") or {}).get(str(n)) or {}
    return _take(st.get("renders"), st.get("approved_render"))


def _url(k: str | None) -> str | None:
    return storage().url(k) if k else None


def _chars(db: Session, v: dict) -> dict[str, Character]:
    """{screenplay name: Character} of the characters made from the screenplay."""
    ids = {n: int(i) for n, i in (v.get("characters") or {}).items()}
    found = {c.id: c for c in db.query(Character).filter(Character.id.in_(list(ids.values())))} if ids else {}
    return {n: found[i] for n, i in ids.items() if i in found}


def _location_wall(db: Session, ep: Episode, v: dict, name: str) -> dict | None:
    from . import room_sets as RS
    wid = (v.get("locations") or {}).get(name)
    return ((RS.stored(db, ep.id).get("walls") or {}).get(wid)) if wid else None


# ================================================================== episode creation and the story
class StoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["idea", "bible", "script"]
    idea: str = Field(default="", max_length=4000)
    passage: str = Field(default="", max_length=80)
    translation: str = Field(default="KJV", max_length=40)
    scripture_text: str = Field(default="", max_length=20000)
    confirm_public_domain: bool = False
    angle: str = Field(default="", max_length=2000)
    script: str = Field(default="", max_length=30000)


def _story(body: StoryIn) -> dict:
    try:
        return check_story(body.source, body.idea, body.passage, body.translation, body.scripture_text,
                           body.confirm_public_domain, body.angle, body.script)
    except LookupError as e:
        raise HTTPException(409, f"{e} (tick \"I copied it from a public-domain source\" to use it)")
    except ValueError as e:
        raise HTTPException(422, str(e))


class CreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    story: StoryIn


@router.post("/cinematic-episodes", status_code=201)
def create_episode(body: CreateIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """A new cinematic episode (free): 16:9, the "Cinematic realistic" style, the story input checked (public-domain
    scripture only)."""
    story = _story(body.story)
    ep = Episode(title=body.title.strip(), stage="script_pending", format="long", source="script", mode=MODE,
                 style=CINEMATIC_STYLE, layout="landscape", dialogue_display="none")
    db.add(ep)
    db.flush()
    story.update(by=user, at=time.time())
    save(db, ep.id, {"story": story})
    if story.get("confirmed_public_domain"):
        db.add(Review(episode_id=ep.id, gate="scripture", decision="confirmed", revision=ep.revision, target={},
                      comment=f"Scripture text confirmed as public domain ({story.get('translation')})", actor=user))
    _event(db, ep.id, f"Cinematic episode created by {user} (story from {story['source']})")
    db.commit()
    return view(db, ep)


@router.put("/episodes/{eid}/cinematic/story")
def edit_story(eid: int, body: StoryIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    story = _story(body)
    story.update(by=user, at=time.time())
    v["story"] = story
    save(db, eid, v)
    db.commit()
    return view(db, ep)


# ================================================================== the screenplay
def screenplay_estimate(db: Session, v: dict) -> dict | None:
    from . import prompt_writer as PW
    story = v.get("story")
    if not story:
        return None
    cfg = {**PW.config(db), "prompt_max_tokens": SCREENPLAY_MAX_TOKENS}
    return PW.estimate(cfg, SCREENPLAY_SYSTEM, screenplay_message(story))


def _set_screenplay(v: dict, content: dict, source: str, label: str, user: str, usd: float = 0.0) -> None:
    old = v.get("screenplay") or {}
    hist = ([{k: old.get(k) for k in ("content", "source", "label", "at")}] if old.get("content") else []) + (old.get("history") or [])
    v["screenplay"] = {"content": content, "source": source, "label": label, "approved": False, "by": user, "at": time.time(),
                       "usd": round(float(old.get("usd") or 0.0) + usd, 6), "history": hist[:5]}


def write_screenplay(db: Session, ep: Episode, confirm_usd: float | None, user: str, use_template: bool = False) -> dict:
    """GPT writes the screenplay (paid: cost first, confirm_usd), or the template when there is no key, no credit or
    the owner asks for it. Returns {"source", "usd"}. The screenplay waits for the owner's approval."""
    from . import prompt_writer as PW
    v = stored(db, ep.id)
    story = v.get("story")
    if not story:
        raise HTTPException(409, "write the story input first (an idea, a Bible passage or your script)")
    api_key = secret("openai_api_key", db)
    src, label, usd, content = "template", TEMPLATE_LABEL, 0.0, None
    if api_key and not use_template:
        est = screenplay_estimate(db, v)
        if confirm_usd is None or confirm_usd + 1e-9 < est["usd_max"]:
            raise HTTPException(409, f"writing the screenplay can cost up to ${est['usd_max']:.4f}: confirm that amount "
                                     "to start (nothing was sent)")
        cfg = PW.config(db)
        try:
            out = PW.call_openai(api_key, cfg["prompt_model"], SCREENPLAY_SYSTEM, screenplay_message(story), SCREENPLAY_MAX_TOKENS)
        except HTTPException as e:
            if e.status_code != 402:
                raise
            out, label = None, "template (OpenAI has no credit): edit it before you approve"
        if out:
            usd = PW.cost_usd(out["input_tokens"], out["output_tokens"], cfg)
            try:
                content = parse_screenplay(out["text"])
                src, label = "gpt", f"written by {cfg['prompt_model']}"
            except ValueError as e:
                label = f"template (GPT's answer was not usable: {e}): edit it before you approve"
    if content is None:
        content = parse_screenplay(template_screenplay(story))
    v = stored(db, ep.id)
    _set_screenplay(v, content, src, label, user, usd)
    save(db, ep.id, v)
    _event(db, ep.id, f"Screenplay {label} for {user}" + (f" (${usd:.4f})" if usd else " (free)"))
    db.commit()
    return {"source": src, "usd": usd}


class ScreenplayWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_usd: float | None = Field(default=None, ge=0, le=20)
    template: bool = False


@router.post("/episodes/{eid}/cinematic/screenplay/write")
def write_route(eid: int, body: ScreenplayWriteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    write_screenplay(db, ep, body.confirm_usd, user, body.template)
    return view(db, ep)


class ScreenplayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    screenplay: dict


@router.put("/episodes/{eid}/cinematic/screenplay")
def edit_screenplay(eid: int, body: ScreenplayIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's edit (free). It is checked like GPT's and waits for approval again."""
    ep = _episode(db, eid)
    try:
        content = parse_screenplay(body.screenplay)
    except ValueError as e:
        raise HTTPException(422, str(e))
    v = stored(db, eid)
    _set_screenplay(v, content, "owner", "edited by you", user)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class ApproveScreenplayIn(BaseModel):
    approve: bool = True


@router.post("/episodes/{eid}/cinematic/screenplay/approve")
def approve_screenplay(eid: int, body: ApproveScreenplayIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's approval (only this click approves the screenplay)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if not screenplay(v):
        raise HTTPException(409, "write the screenplay first")
    v["screenplay"].update(approved=body.approve, approved_by=user if body.approve else None, approved_at=time.time())
    save(db, eid, v)
    _event(db, eid, f"Screenplay {'approved' if body.approve else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


# ================================================================== cast (cast_from_video's candidates and approval)
def cast_from_screenplay(db: Session, ep: Episode, user: str) -> dict:
    """The screenplay's characters as this episode's characters (free), with their written descriptions linked in the
    Cast step's storage, so cast_from_video draws, approves and saves them as it does for the cartoon mode."""
    from . import cast_from_video as CV
    v = stored(db, ep.id)
    sp = screenplay(v)
    if not sp or not screenplay_approved(v):
        raise HTTPException(409, "approve the screenplay first")
    cv = CV.stored(db, ep.id)
    have = v.setdefault("characters", {})
    made = []
    for d in sp["characters"]:
        if d["name"] in have and db.get(Character, int(have[d["name"]])) is not None:
            continue
        base = re.sub(r"[^a-z0-9]+", "-", d["name"].lower()).strip("-")[:40] or "character"
        k, i = f"{base}-ep{ep.id}", 2
        while db.query(Character).filter_by(key=k).first() is not None:
            k, i = f"{base}-ep{ep.id}-{i}", i + 1
        desc = {"id": pysecrets.token_hex(4), "name": d["name"], "role": d.get("role") or "", "age": d.get("age") or "",
                "build": d.get("build") or "", "hair": {"style": d.get("hair") or "", "colour": ""},
                "clothing": [{"garment": d["clothing"], "colour": ""}] if d.get("clothing") else [],
                "accessory": d.get("distinctive") or "", "personality": d.get("personality") or "",
                "must_never": ["resemble any real person, celebrity or actor"], "from": "screenplay"}
        c = Character(key=k, name=d["name"], description=d.get("role") or "", scope="episode", episode_id=ep.id,
                      visual_description=CV.description_text(desc)[:4000])
        db.add(c)
        db.flush()
        desc["character_id"] = c.id
        cv.setdefault("characters", []).append(desc)
        have[d["name"]] = c.id
        made.append(c.name)
    CV.save(db, ep.id, cv)
    if ep.style != CINEMATIC_STYLE:
        ep.style = CINEMATIC_STYLE
    save(db, ep.id, v)
    if made:
        _event(db, ep.id, f"Cast from the screenplay by {user}: {', '.join(made)}", "character")
    db.commit()
    return {"made": made}


@router.post("/episodes/{eid}/cinematic/cast")
def cast_route(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    cast_from_screenplay(db, ep, user)
    return view(db, ep)


class VoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: int
    voice: str = Field(min_length=2, max_length=60)


@router.put("/episodes/{eid}/cinematic/voices")
def set_voice(eid: int, body: VoiceIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's voice for one character (free Kokoro voices only)."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.character_id not in [int(i) for i in (v.get("characters") or {}).values()]:
        raise HTTPException(404, "this character is not in the episode's cast")
    try:
        voice = TTS.check_voice(body.voice)
    except ValueError as e:
        raise HTTPException(422, str(e))
    c = db.get(Character, body.character_id)
    c.voice = voice
    _event(db, eid, f"{c.name}: voice set to {voice} by {user}", "character")
    db.commit()
    return view(db, ep)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    still_provider: Literal["nano", "qwen"] | None = None
    voice_source: Literal["tts", "upload"] | None = None
    captions: bool | None = None
    music_volume: float | None = Field(default=None, ge=0, le=1)


@router.put("/episodes/{eid}/cinematic/settings")
def set_settings(eid: int, body: SettingsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    v.setdefault("settings", {}).update(body.model_dump(exclude_none=True))
    save(db, eid, v)
    db.commit()
    return view(db, ep)


# ================================================================== locations (room_sets walls, generalised)
def locations_from_screenplay(db: Session, ep: Episode, user: str) -> dict:
    """One room_sets wall per screenplay location, with the realistic location prompt (free). The pictures are made
    and approved with room_sets' own routes (make: paid, confirm_usd; approve: the owner)."""
    from . import room_sets as RS
    v = stored(db, ep.id)
    sp = screenplay(v)
    if not sp or not screenplay_approved(v):
        raise HTTPException(409, "approve the screenplay first")
    rv = RS.stored(db, ep.id)
    have = v.setdefault("locations", {})
    made = []
    for loc in sp["locations"]:
        if have.get(loc["name"]) in (rv.get("walls") or {}):
            continue
        wid = pysecrets.token_hex(4)
        text = location_template(loc["name"], loc.get("description") or "")
        rv.setdefault("walls", {})[wid] = {"id": wid, "name": loc["name"][:80], "side": "", "kind": "location",
                                           "contents": (loc.get("description") or "")[:1500], "takes": [], "approved": None,
                                           "at": time.time(), "by": user,
                                           "prompt": {"text": text, "source": "template", "label": "realistic location template"}}
        have[loc["name"]] = wid
        made.append(loc["name"])
    RS.save(db, ep.id, rv)
    save(db, ep.id, v)
    if made:
        _event(db, ep.id, f"Locations from the screenplay by {user}: {', '.join(made)}")
    db.commit()
    return {"made": made}


@router.post("/episodes/{eid}/cinematic/locations")
def locations_route(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    locations_from_screenplay(db, ep, user)
    return view(db, ep)


# ================================================================== shot stills
def _image_each(db: Session) -> float:
    from .stick_pipeline import IMAGE_PROVIDERS
    p = IMAGE_PROVIDERS.get(get_section(db, "stick").get("image_provider"))
    return p["usd_per_image"] if p else 0.0


def _prices(db: Session) -> list[float]:
    from . import comfy_session as CS
    return CS.list_prices(get_section(db, "gpu"))


def gpu_estimate(db: Session, tasks: list[dict]) -> dict:
    return G.estimate(tasks, _prices(db), int(get_section(db, "gpu")["max_lifetime_minutes"]))


def still_inputs(db: Session, ep: Episode, v: dict, shot: dict, provider: str) -> dict:
    """{refs: [storage keys], ref_people: [names], has_location, prompt, missing: [what to approve first]}."""
    from .stick_pipeline import approved_master
    from . import room_sets as RS
    chars = _chars(db, v)
    missing, people_refs = [], []
    for name in shot.get("characters") or []:
        c = chars.get(name)
        m = approved_master(db, c.id) if c else None
        if m is None:
            missing.append(f"approve a master for {name}")
        else:
            people_refs.append((name, m.storage_key))
    loc_key = None
    w = _location_wall(db, ep, v, shot.get("location") or "")
    if w is not None:
        t = RS.approved_take(w)
        if t:
            loc_key = t["key"]
        else:
            missing.append(f"approve a picture of the location \"{shot['location']}\"")
    if provider == "qwen":
        people_refs = people_refs[:G.MAX_REFS_QWEN]
        refs = [k for _, k in people_refs]
        has_loc = bool(loc_key) and len(refs) < G.MAX_REFS_QWEN
        if has_loc:
            refs.append(loc_key)
    else:
        has_loc = bool(loc_key)
        refs = ([loc_key] if loc_key else []) + [k for _, k in people_refs]
    names = [n for n, _ in people_refs]
    own = ((v.get("shots") or {}).get(str(shot["n"])) or {}).get("still_prompt")
    prompt = own or G.still_prompt(shot, shot.get("characters") or [], shot.get("location"), names, has_loc, provider)
    return {"refs": refs, "ref_people": names, "has_location": has_loc, "prompt": prompt, "missing": missing,
            "prompt_source": "owner" if own else "template"}


def still_cost(db: Session, ep: Episode, n: int) -> dict:
    """The price of one new still with the episode's still provider (the chat's Apply and the button)."""
    from .stick_pipeline import image_cost
    v = stored(db, ep.id)
    if config(db, v)["still_provider"] == "qwen":
        e = gpu_estimate(db, [{"kind": "still"}])
        return {"usd": e["usd_max"], "label": f"up to ${e['usd_max']:.2f} on the rented GPU ({e['label']})", "gpu": True}
    return {**image_cost(1, _image_each(db)), "gpu": False}


def _shot_or_404(v: dict, n: int) -> dict:
    s = next((x for x in shots_of(screenplay(v)) if x["n"] == n), None)
    if s is None:
        raise HTTPException(404, f"the screenplay has no shot {n}")
    return s


def _busy(db: Session, eid: int, kinds=JOBS) -> bool:
    return db.query(Job).filter(Job.kind.in_(kinds), Job.episode_id == eid, Job.status.in_(("queued", "running"))).first() is not None


def _gpu_checks(db: Session, est: dict, confirm: float | None, what: str) -> None:
    from . import comfy_session as CS
    from . import gpu
    a = CS.availability(db)
    if not a["ok"]:
        raise HTTPException(409, a["reason"])
    if est["too_long"]:
        raise HTTPException(409, "a shot is too long for the maximum GPU session length: raise it in Settings > GPU worker")
    if confirm is None or confirm + 1e-9 < est["usd_max"]:
        raise HTTPException(409, f"{what} can cost up to ${est['usd_max']:.2f}: confirm that amount to start (nothing was started)")
    fig = gpu.month_figures(db)
    cap = float(get_section(db, "gpu")["monthly_cap_usd"])
    if fig["committed_usd"] + est["usd_max"] > cap + 1e-9:
        raise HTTPException(409, f"Paused: {what} (up to ${est['usd_max']:.2f}) would pass the monthly GPU cap "
                                 f"(${fig['committed_usd']:.2f} committed of ${cap:.2f}). Raise the cap or wait for next month")


class StillIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_usd: float | None = Field(default=None, ge=0, le=100)
    end: bool = False
    prompt: str | None = Field(default=None, min_length=10, max_length=4000)


def _still_busy(db: Session, eid: int, n: int) -> bool:
    return any((j.payload or {}).get("shot") == n for j in db.query(Job).filter(
        Job.kind == JOB_STILL, Job.episode_id == eid, Job.status.in_(("queued", "running"))))


def make_still(db: Session, ep: Episode, n: int, body: StillIn, user: str) -> dict:
    """Paid: one new still (a take, not approved) with the episode's still provider."""
    from .stick_pipeline import image_provider, require_confirmed
    v = stored(db, ep.id)
    if not screenplay_approved(v):
        raise HTTPException(409, "approve the screenplay first")
    shot = _shot_or_404(v, n)
    prov = config(db, v)["still_provider"]
    if body.prompt:
        _shot_state(v, n)["still_prompt"] = body.prompt.strip()
    inp = still_inputs(db, ep, v, shot, prov)
    if inp["missing"]:
        raise HTTPException(409, "; ".join(inp["missing"]) + " first")
    if _still_busy(db, ep.id, n):
        raise HTTPException(409, f"a still of shot {n} is already being made")
    if prov == "qwen":
        task = {"kind": "still", "shot": n, "end": body.end, "prompt": inp["prompt"], "refs": inp["refs"]}
        return start_gpu(db, ep, [task], body.confirm_usd, user, f"a new still of shot {n}", v)
    pv = image_provider(db)
    cost = still_cost(db, ep, n)
    require_confirmed(cost["usd"], body.confirm_usd)
    job = enqueue(db, JOB_STILL, episode_id=ep.id, payload={"shot": n, "end": body.end, "prompt": inp["prompt"], "refs": inp["refs"],
                                                            "provider": pv["id"], "usd": cost["usd"], "by": user})
    _shot_state(v, n)["still_run"] = {"status": "queued", "job_id": job.id, "at": time.time()}
    save(db, ep.id, v)
    _event(db, ep.id, f"Shot {n}: a new {'end ' if body.end else ''}still asked by {user} ({cost['label']})")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/cinematic/shots/{n}/still")
def still_route(eid: int, n: int, body: StillIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return make_still(db, _episode(db, eid), n, body, user)


class StillsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shots: list[int] = Field(min_length=1, max_length=MAX_SHOTS)
    confirm_usd: float | None = Field(default=None, ge=0, le=200)


def gpu_still_tasks(db: Session, ep: Episode, v: dict, shots: list[int]) -> tuple[list[dict], list[str]]:
    tasks, problems = [], []
    for n in shots:
        shot = _shot_or_404(v, n)
        inp = still_inputs(db, ep, v, shot, "qwen")
        if inp["missing"]:
            problems.append(f"shot {n}: " + "; ".join(inp["missing"]))
        tasks.append({"kind": "still", "shot": n, "end": False, "prompt": inp["prompt"], "refs": inp["refs"]})
    return tasks, problems


def make_stills_gpu(db: Session, ep: Episode, shots: list[int], confirm: float | None, user: str) -> dict:
    """Paid (GPU): stills of several shots in one rented session (Qwen); each a take, none approved."""
    v = stored(db, ep.id)
    tasks, problems = gpu_still_tasks(db, ep, v, shots)
    if problems:
        raise HTTPException(409, "; ".join(problems))
    return start_gpu(db, ep, tasks, confirm, user, f"stills of shot(s) {', '.join(map(str, shots))}", v)


@router.post("/episodes/{eid}/cinematic/stills")
def stills_route(eid: int, body: StillsIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return make_stills_gpu(db, _episode(db, eid), body.shots, body.confirm_usd, user)


class TakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_id: str | None = Field(default=None, max_length=20)
    end: bool = False


@router.post("/episodes/{eid}/cinematic/shots/{n}/still/approve")
def approve_still(eid: int, n: int, body: TakeIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's approval of one still take (null withdraws it). Only this click approves a still."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    _shot_or_404(v, n)
    st = _shot_state(v, n)
    field = "end_stills" if body.end else "stills"
    if body.take_id is not None and _take(st.get(field), body.take_id) is None:
        raise HTTPException(404, "no such still of this shot")
    st["end_approved" if body.end else "approved"] = body.take_id
    save(db, eid, v)
    _event(db, eid, f"Shot {n}: {'end ' if body.end else ''}still {'approved' if body.take_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


class ShotEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    still_prompt: str | None = Field(default=None, max_length=4000)        # "" back to the template
    motion_prompt: str | None = Field(default=None, max_length=4000)
    camera: str | None = Field(default=None, max_length=40)
    use_end: bool | None = None


@router.put("/episodes/{eid}/cinematic/shots/{n}")
def edit_shot(eid: int, n: int, body: ShotEditIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    _shot_or_404(v, n)
    st = _shot_state(v, n)
    for f in ("still_prompt", "motion_prompt"):
        val = getattr(body, f)
        if val is not None:
            if val.strip():
                st[f] = val.strip()
            else:
                st.pop(f, None)
    if body.camera is not None:
        if body.camera not in G.CAMERAS:
            raise HTTPException(422, f"the camera move must be one of {', '.join(G.CAMERAS)}")
        st["camera"] = body.camera
    if body.use_end is not None:
        st["use_end"] = body.use_end
    save(db, eid, v)
    db.commit()
    return view(db, ep)


# ================================================================== voices (lines)
class LinesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[str] | None = Field(default=None, max_length=MAX_SHOTS)


def generate_lines(db: Session, ep: Episode, ids: list[str] | None, user: str, overrides: dict | None = None) -> dict:
    """Free: the lines spoken by Kokoro on the studio server (one job). Each take waits for the owner's approval."""
    try:
        TTS.choose_engine(get_section(db, "cinematic").get("voice_engine") or "kokoro")
    except ValueError as e:
        raise HTTPException(409, str(e))
    v = stored(db, ep.id)
    if not screenplay_approved(v):
        raise HTTPException(409, "approve the screenplay first")
    lines = {ln["id"]: ln for ln in lines_of(screenplay(v))}
    want = ids or [lid for lid in lines if not ((v.get("lines") or {}).get(lid) or {}).get("takes")]
    chars = _chars(db, v)
    problems = []
    for lid in want:
        ln = lines.get(lid)
        if ln is None:
            problems.append(f"{lid} is not a line of the screenplay")
            continue
        c = chars.get(ln["speaker"])
        voice = (overrides or {}).get("voice") or (c.voice if c else "")
        if c is None:
            problems.append(f"{ln['speaker']} is not in the cast yet (make the cast from the screenplay)")
        elif TTS.voice_id(voice) is None:
            problems.append(f"choose a voice for {ln['speaker']}")
    if problems:
        raise HTTPException(409, "; ".join(problems))
    if not want:
        raise HTTPException(409, "every line already has a take: choose the lines to speak again")
    if _busy(db, ep.id, (JOB_VOICE,)):
        raise HTTPException(409, "lines are already being spoken")
    job = enqueue(db, JOB_VOICE, episode_id=ep.id, payload={"lines": want, "by": user, "overrides": overrides or {}})
    _event(db, ep.id, f"{len(want)} line(s) to speak with Kokoro asked by {user} (free)")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/cinematic/lines/generate")
def lines_route(eid: int, body: LinesIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return generate_lines(db, _episode(db, eid), body.lines, user)


@router.put("/episodes/{eid}/cinematic/lines/{lid}/upload")
async def upload_line(eid: int, lid: str, request: Request, rights: str = "", db: Session = Depends(get_db),
                      user: str = Depends(current_user)):
    """The owner's own recording of one line (the request body; WAV, MP3, M4A, OGG or FLAC, up to 30 MB). It is a take
    like any other and waits for approval. rights=own|licensed confirms the owner may use the recording."""
    import tempfile
    from .tasks import store_asset
    ep = _episode(db, eid)
    if rights not in ("own", "licensed"):
        raise HTTPException(422, "confirm the recording is your own or licensed to you (rights=own or rights=licensed)")
    v = stored(db, eid)
    if lid not in {ln["id"] for ln in lines_of(screenplay(v))}:
        raise HTTPException(404, "no such line in the screenplay")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in AUDIO_TYPES:
        raise HTTPException(415, "upload a WAV, MP3, M4A, OGG or FLAC recording")
    raw = await request.body()
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "the recording must be between 1 byte and 30 MB")
    tid = pysecrets.token_hex(4)
    ext = AUDIO_TYPES[ctype]
    k = f"episodes/{ep.id}/cinematic/line-{lid}-{tid}{ext}"
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"take{ext}"
        f.write_bytes(raw)
        secs = None
        try:
            secs = TTS.seconds_of(f) if ext == ".wav" else None
        except Exception:   # noqa: BLE001
            secs = None
        if secs is None:
            try:
                from . import media
                secs = media.probe(f).get("duration")
            except Exception:   # noqa: BLE001 -- unknown length: the shot asks for a WAV
                secs = None
        a = store_asset(db, ep_id=ep.id, src=f, key=k, kind="audio", label=f"Line {lid} (your recording)", content_type=ctype)
    st = _line_state(v, lid)
    st.setdefault("takes", []).insert(0, {"id": tid, "asset_id": a.id, "key": k, "source": "upload", "rights": rights,
                                          "seconds": round(float(secs), 3) if secs else None, "at": time.time(), "by": user})
    save(db, eid, v)
    _event(db, eid, f"Line {lid}: recording uploaded by {user} (not approved)")
    db.commit()
    return view(db, ep)


class LineApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_id: str | None = Field(default=None, max_length=20)


@router.post("/episodes/{eid}/cinematic/lines/{lid}/approve")
def approve_line(eid: int, lid: str, body: LineApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner listened and approves this take (null withdraws it). Only approved takes drive the talking shots."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if lid not in {ln["id"] for ln in lines_of(screenplay(v))}:
        raise HTTPException(404, "no such line in the screenplay")
    st = _line_state(v, lid)
    if body.take_id is not None and _take(st.get("takes"), body.take_id) is None:
        raise HTTPException(404, "no such take of this line")
    st["approved"] = body.take_id
    save(db, eid, v)
    _event(db, eid, f"Line {lid}: take {'approved' if body.take_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


def regenerate_line(db: Session, ep: Episode, lid: str, text: str | None, voice: str | None, user: str) -> dict:
    """The chat's regenerate_line (free): optionally new words for this line and/or a voice for this take, then the
    line is spoken again (a new take, not approved)."""
    v = stored(db, ep.id)
    lines = {ln["id"]: ln for ln in lines_of(screenplay(v))}
    if lid not in lines:
        raise HTTPException(404, "no such line in the screenplay")
    if voice is not None:
        try:
            voice = TTS.check_voice(voice)
        except ValueError as e:
            raise HTTPException(422, str(e))
    if text:
        n, k = lines[lid]["n"], 0
        for sc in v["screenplay"]["content"]["scenes"]:
            for sh in sc["shots"]:
                k += 1
                if k == n and sh.get("line"):
                    sh["line"]["text"] = _txt(text, MAX_LINE)
        save(db, ep.id, v)
        db.flush()
    return generate_lines(db, ep, [lid], user, {"voice": voice} if voice else None)


# ================================================================== motion and dialogue shots (the rented GPU)
def render_task(db: Session, ep: Episode, v: dict, shot: dict) -> tuple[dict | None, str]:
    """(the GPU task of one shot, why it cannot be made yet)."""
    n = shot["n"]
    st = (v.get("shots") or {}).get(str(n)) or {}
    still = approved_still(v, n)
    if still is None:
        return None, "approve its still first"
    s2 = {**shot, "camera": st.get("camera") or shot.get("camera") or "static"}
    if shot["kind"] == "talk":
        take = approved_line(v, shot["line_id"])
        if take is None:
            return None, "approve its line's voice take first"
        if not take.get("seconds"):
            return None, "the length of its approved voice take is unknown: upload it as WAV or speak it again"
        name = shot["line"]["speaker"]
        return {"kind": "talk", "shot": n, "still": still["key"], "voice": take["key"], "voice_take": take["id"],
                "frames": G.talk_frames(take["seconds"]), "prompt": st.get("motion_prompt") or G.talk_prompt(s2, name)}, ""
    end = approved_still(v, n, end=True) if st.get("use_end") else None
    return {"kind": "motion", "shot": n, "still": still["key"], "end": end["key"] if end else None,
            "pieces": G.motion_pieces(shot.get("seconds") or 5), "prompt": st.get("motion_prompt") or G.motion_prompt(s2)}, ""


def render_cost(db: Session, ep: Episode, n: int) -> dict:
    v = stored(db, ep.id)
    t, why = render_task(db, ep, v, _shot_or_404(v, n))
    if t is None:
        return {"usd": None, "label": f"shot {n}: {why}"}
    e = gpu_estimate(db, [t])
    return {"usd": e["usd_max"], "label": f"up to ${e['usd_max']:.2f} on the rented GPU ({e['label']})"}


def start_gpu(db: Session, ep: Episode, tasks: list[dict], confirm: float | None, user: str, what: str,
              v: dict | None = None) -> dict:
    """The one paid GPU entry: cost first (confirm_usd = "at most"), the GPU mode, the monthly cap, one run at a time."""
    est = gpu_estimate(db, tasks)
    _gpu_checks(db, est, confirm, what)
    if _busy(db, ep.id, (JOB_GPU,)):
        raise HTTPException(409, "a cinematic GPU run is already going for this episode")
    job = enqueue(db, JOB_GPU, episode_id=ep.id, payload={"tasks": tasks, "confirm_usd": float(confirm), "estimate": est,
                                                          "by": user, "backend": "gpu"})
    v = v if v is not None else stored(db, ep.id)
    for t in tasks:
        _shot_state(v, t["shot"])["run"] = {"status": "queued", "job_id": job.id, "kind": t["kind"], "at": time.time()}
    save(db, ep.id, v)
    _event(db, ep.id, f"Cinematic GPU run: {what} asked by {user} (up to ${est['usd_max']:.2f})")
    db.commit()
    return S.job(job)


class RenderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shots: list[int] | None = Field(default=None, max_length=MAX_SHOTS)
    confirm_usd: float | None = Field(default=None, ge=0, le=500)


def render_tasks(db: Session, ep: Episode, v: dict, shots: list[int] | None) -> tuple[list[dict], list[str]]:
    all_shots = {s["n"]: s for s in shots_of(screenplay(v))}
    want = shots or [n for n in all_shots if not ((v.get("shots") or {}).get(str(n)) or {}).get("renders")]
    tasks, problems = [], []
    for n in want:
        if n not in all_shots:
            problems.append(f"shot {n} is not in the screenplay")
            continue
        t, why = render_task(db, ep, v, all_shots[n])
        if t is None:
            problems.append(f"shot {n}: {why}")
        else:
            tasks.append(t)
    return tasks, problems


def render(db: Session, ep: Episode, shots: list[int] | None, confirm: float | None, user: str) -> dict:
    v = stored(db, ep.id)
    if not screenplay_approved(v):
        raise HTTPException(409, "approve the screenplay first")
    tasks, problems = render_tasks(db, ep, v, shots)
    if problems:
        raise HTTPException(409, "; ".join(problems))
    if not tasks:
        raise HTTPException(409, "no shot to make: every shot has a result (choose shots to make again)")
    return start_gpu(db, ep, tasks, confirm, user, f"shot(s) {', '.join(str(t['shot']) for t in tasks)}", v)


@router.post("/episodes/{eid}/cinematic/render/estimate")
def render_estimate_route(eid: int, body: RenderIn, db: Session = Depends(get_db)):
    """Free: what making these shots (all ready ones when empty) can cost; the shots that cannot be made yet and why."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    tasks, problems = render_tasks(db, ep, v, body.shots)
    return {**gpu_estimate(db, tasks), "shots": [t["shot"] for t in tasks], "problems": problems}


@router.post("/episodes/{eid}/cinematic/render")
def render_route(eid: int, body: RenderIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return render(db, _episode(db, eid), body.shots, body.confirm_usd, user)


def rerender_from_chat(db: Session, ep: Episode, n: int, prompt: str, camera: str | None, confirm: float | None,
                       user: str) -> dict:
    """The chat's rerender_shot: the shot's motion prompt (and camera) changed, then the render route with all its
    checks; a refused render keeps nothing."""
    v = stored(db, ep.id)
    _shot_or_404(v, n)
    st = _shot_state(v, n)
    st["motion_prompt"] = prompt.strip()
    if camera:
        st["camera"] = camera
    save(db, ep.id, v)
    db.flush()
    try:
        return render(db, ep, [n], confirm, user)
    except HTTPException:
        db.rollback()
        raise


class RenderApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    render_id: str | None = Field(default=None, max_length=20)


@router.post("/episodes/{eid}/cinematic/shots/{n}/render/approve")
def approve_render(eid: int, n: int, body: RenderApproveIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    _shot_or_404(v, n)
    st = _shot_state(v, n)
    if body.render_id is not None and _take(st.get("renders"), body.render_id) is None:
        raise HTTPException(404, "no such result of this shot")
    st["approved_render"] = body.render_id
    save(db, eid, v)
    _event(db, eid, f"Shot {n}: result {'approved' if body.render_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


@router.post("/episodes/{eid}/cinematic/stop")
def stop_gpu(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from . import comfy_session as CS
    _episode(db, eid)
    try:
        return {"terminated": CS.stop(db, f"stopped by {user}")}
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f"RunPod could not be reached; the session is still open: {str(e)[:200]}")


# ================================================================== music, disclosure
@router.put("/episodes/{eid}/cinematic/music")
async def upload_music(eid: int, request: Request, rights: str = "", name: str = "", db: Session = Depends(get_db),
                       user: str = Depends(current_user)):
    """The owner's royalty-free music track (optional; the studio never generates music). rights=royalty_free confirms
    the owner may use it in a published video."""
    import tempfile
    from .tasks import store_asset
    ep = _episode(db, eid)
    if rights != "royalty_free":
        raise HTTPException(422, "confirm the music is royalty-free or licensed for your videos (rights=royalty_free)")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in AUDIO_TYPES:
        raise HTTPException(415, "upload a WAV, MP3, M4A, OGG or FLAC file")
    raw = await request.body()
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "the music file must be between 1 byte and 30 MB")
    ext = AUDIO_TYPES[ctype]
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / f"music{ext}"
        f.write_bytes(raw)
        a = store_asset(db, ep_id=ep.id, src=f, key=f"episodes/{ep.id}/cinematic/music-{pysecrets.token_hex(4)}{ext}",
                        kind="audio", label="Music (royalty-free, uploaded)", content_type=ctype)
    v = stored(db, eid)
    v["music"] = {"asset_id": a.id, "key": a.storage_key, "name": name[:120], "rights": rights, "by": user, "at": time.time()}
    save(db, eid, v)
    _event(db, eid, f"Music uploaded by {user} (royalty-free confirmed)")
    db.commit()
    return view(db, ep)


@router.delete("/episodes/{eid}/cinematic/music")
def remove_music(eid: int, db: Session = Depends(get_db)):
    ep = _episode(db, eid)
    v = stored(db, eid)
    v.pop("music", None)
    save(db, eid, v)
    db.commit()
    return view(db, ep)


class DisclosureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: bool


def disclosure(v: dict) -> dict:
    d = v.get("disclosure") or {}
    return {"text": DISCLOSURE, "acknowledged": bool(d.get("acknowledged")), "by": d.get("by"), "at": d.get("at")}


def disclosure_ok(db: Session, ep: Episode) -> bool:
    return not is_cinematic(ep) or disclosure(stored(db, ep.id))["acknowledged"]


@router.put("/episodes/{eid}/cinematic/disclosure")
def set_disclosure(eid: int, body: DisclosureIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's tick: they will mark the upload as altered or synthetic content on YouTube. Saved on the episode."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    v["disclosure"] = {"acknowledged": body.acknowledged, "by": user, "at": time.time()}
    save(db, eid, v)
    _event(db, eid, f"YouTube synthetic-content disclosure {'ticked' if body.acknowledged else 'unticked'} by {user}")
    db.commit()
    return view(db, ep)


# ================================================================== assembly
def plan_rows(db: Session, ep: Episode) -> dict:
    """The cut in screenplay order: an approved clip, else an approved still held for the shot's length, else missing.
    Each dialogue shot's approved voice take plays from the shot's start."""
    import hashlib
    from .assembly import FPS, segment_frames
    v = stored(db, ep.id)
    rows, missing, t = [], [], 0.0
    for s in shots_of(screenplay(v)):
        n = s["n"]
        rec, still = approved_render(v, n), approved_still(v, n)
        take = approved_line(v, s.get("line_id"))
        row = {"index": n, "start": round(t, 3), "source": "missing", "asset_id": None, "key": None, "label": "",
               "trim_start_frames": 0, "stretch": 1.0, "warnings": [], "line": None}
        if rec:
            secs = rec["frames"] / G.FPS
            row.update(source=rec["kind"], asset_id=rec["asset_id"], key=rec["key"], label=f"{rec['kind']} shot (approved)",
                       src_frames=rec["frames"], src_fps=G.FPS)
        elif still:
            secs = (float(take["seconds"]) + 0.5) if take and take.get("seconds") else float(s.get("seconds") or 5)
            row.update(source="still", asset_id=still["asset_id"], key=still["key"], label="still, not animated")
            if ((v.get("shots") or {}).get(str(n)) or {}).get("renders"):
                row["warnings"].append("a clip is waiting for your approval: the still is used until you approve it")
        else:
            secs = float(s.get("seconds") or 5)
            row["warnings"].append("approve this shot's still or clip first")
            missing.append(n)
        if take:
            row["line"] = {"key": take["key"], "seconds": take.get("seconds"), "text": s["line"]["text"],
                           "speaker": s["line"]["speaker"]}
        elif s.get("line"):
            row["warnings"].append("its line has no approved voice take: the shot is silent")
        row["seconds"] = round(secs, 3)
        rows.append(row)
        t += secs
    segs = segment_frames([r["start"] for r in rows], t)
    for r, (f0, nf) in zip(rows, segs):
        r["start_frame"], r["frames"] = f0, nf
    sig = [[r["index"], r["source"], r["asset_id"], r["frames"], (r["line"] or {}).get("key")] for r in rows]
    sig += [(v.get("music") or {}).get("asset_id"), bool(config(db, v)["captions"])]
    h = hashlib.sha256(json.dumps(sig).encode()).hexdigest()[:12]
    return {"rows": rows, "size": [1280, 720], "fps": FPS, "seconds": round(t, 3), "frames": sum(r["frames"] for r in rows),
            "missing": missing, "hash": h if rows else ""}


def assemble(db: Session, ep: Episode, user: str) -> dict:
    from .config import get_settings
    if not get_settings().ffmpeg:
        raise HTTPException(409, "FFmpeg is not configured on the studio server (FFMPEG), so the episode cannot be put together")
    p = plan_rows(db, ep)
    if not p["rows"]:
        raise HTTPException(409, "write and approve the screenplay first: there are no shots")
    if p["missing"]:
        raise HTTPException(409, "approve a still or a clip for shot(s) " + ", ".join(map(str, p["missing"])) + " first")
    if _busy(db, ep.id, (JOB_ASSEMBLY,)):
        raise HTTPException(409, "the episode is already being put together")
    job = enqueue(db, JOB_ASSEMBLY, episode_id=ep.id, payload={"by": user, "hash": p["hash"]})
    _event(db, ep.id, f"Cinematic assembly asked by {user} ({len(p['rows'])} shots, free)")
    db.commit()
    return S.job(job)


@router.post("/episodes/{eid}/cinematic/assemble")
def assemble_route(eid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return assemble(db, _episode(db, eid), user)


class CutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cut_id: str | None = Field(default=None, max_length=20)


@router.post("/episodes/{eid}/cinematic/cut/approve")
def approve_cut(eid: int, body: CutIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """The owner's approval of the final cut (null withdraws it). Needs the synthetic-content disclosure ticked."""
    ep = _episode(db, eid)
    v = stored(db, eid)
    if body.cut_id is not None:
        if not any(c["id"] == body.cut_id for c in v.get("cuts") or []):
            raise HTTPException(404, "no such cut")
        if not disclosure(v)["acknowledged"]:
            raise HTTPException(409, f"tick the YouTube notice first: {DISCLOSURE}")
    v["approved_cut"], v["approved_cut_by"] = body.cut_id, (user if body.cut_id else None)
    save(db, eid, v)
    _event(db, eid, f"Cinematic final cut {'approved' if body.cut_id else 'approval withdrawn'} by {user}", "approval")
    db.commit()
    return view(db, ep)


# ================================================================== the view
def _asset_url(db: Session, aid) -> str | None:
    a = db.get(Asset, aid) if aid else None
    return storage().url(a.storage_key) if a else None


def _kokoro_installed() -> bool:
    if TTS._test_speak is not None:
        return True
    from . import kokoro
    return kokoro.installed()


def view(db: Session, ep: Episode) -> dict:
    from .stick_pipeline import approved_master, image_cost
    from . import comfy_session as CS
    from . import room_sets as RS
    v = stored(db, ep.id)
    sp = screenplay(v)
    cfg = config(db, v)
    chars = _chars(db, v)
    out_shots = []
    for s in shots_of(sp):
        st = (v.get("shots") or {}).get(str(s["n"])) or {}
        t, why = render_task(db, ep, v, s)
        out_shots.append({**s, "camera": st.get("camera") or s.get("camera"), "still_prompt": st.get("still_prompt"),
                          "motion_prompt": st.get("motion_prompt"), "use_end": bool(st.get("use_end")),
                          "stills": [{**x, "url": _url(x.get("key"))} for x in st.get("stills") or []],
                          "end_stills": [{**x, "url": _url(x.get("key"))} for x in st.get("end_stills") or []],
                          "approved": st.get("approved"), "end_approved": st.get("end_approved"),
                          "renders": [{**x, "url": _url(x.get("key"))} for x in st.get("renders") or []],
                          "approved_render": st.get("approved_render"), "run": st.get("run"), "still_run": st.get("still_run"),
                          "render_ready": t is not None, "render_blocked": why,
                          "render_estimate": gpu_estimate(db, [t]) if t else None})
    lines = []
    for ln in lines_of(sp):
        st = (v.get("lines") or {}).get(ln["id"]) or {}
        lines.append({**ln, "takes": [{**x, "url": _url(x.get("key"))} for x in st.get("takes") or []],
                      "approved": st.get("approved")})
    suggested = TTS.suggest(list((sp or {}).get("characters") or [])) if sp else {}
    cast = []
    for name, c in chars.items():
        m = approved_master(db, c.id)
        cast.append({"id": c.id, "name": name, "voice": TTS.voice_id(c.voice), "suggested_voice": suggested.get(name),
                     "master": {"id": m.id, "url": storage().url(m.storage_key)} if m else None})
    rv = RS.stored(db, ep.id)
    locs = []
    for name, wid in (v.get("locations") or {}).items():
        w = (rv.get("walls") or {}).get(wid)
        if w:
            locs.append({"name": name, "wall_id": wid, "prompt": (w.get("prompt") or {}).get("text"),
                         "takes": [RS._take(x) for x in w.get("takes") or []], "approved": w.get("approved"),
                         "busy": RS._busy(db, ep.id, "wall", wid)})
    p = plan_rows(db, ep)
    cuts = [{**c, "url": _asset_url(db, c.get("asset_id")), "approved": v.get("approved_cut") == c["id"],
             "current": c.get("hash") == p["hash"]} for c in v.get("cuts") or []]
    jobs = db.query(Job).filter(Job.kind.in_(JOBS), Job.episode_id == ep.id).order_by(Job.id.desc()).limit(8).all()
    music = v.get("music")
    return {"episode": {"id": ep.id, "title": ep.title, "mode": MODE, "style": ep.style},
            "story": v.get("story"),
            "screenplay": ({**{k: (v.get("screenplay") or {}).get(k) for k in ("source", "label", "approved", "approved_by", "usd")},
                            "content": sp, "estimate": screenplay_estimate(db, v)} if v.get("story") else None),
            "settings": {k: cfg[k] for k in ("still_provider", "voice_source", "captions", "music_volume")},
            "still_providers": STILL_PROVIDERS, "voice_sources": VOICE_SOURCES,
            "cast": cast, "cast_made": bool(chars), "voices": TTS.catalogue(), "voice_engine": TTS.choose_engine("kokoro"),
            "locations": locs, "locations_made": bool(v.get("locations")), "location_cost": image_cost(1, _image_each(db)),
            "shots": out_shots, "lines": lines, "still_cost": still_cost(db, ep, 1) if out_shots else None,
            "music": ({"name": music.get("name"), "asset_id": music.get("asset_id"), "url": _asset_url(db, music.get("asset_id"))}
                      if music else None),
            "disclosure": disclosure(v), "plan": p, "cuts": cuts, "approved_cut": v.get("approved_cut"),
            "availability": CS.availability(db), "busy": _busy(db, ep.id), "jobs": [S.job(j) for j in jobs],
            "keys": {"openai": bool(secret("openai_api_key", db)), "wavespeed": bool(secret("wavespeed_api_key", db))},
            "kokoro_installed": _kokoro_installed()}


@router.get("/episodes/{eid}/cinematic")
def get_view(eid: int, db: Session = Depends(get_db)):
    return view(db, _episode(db, eid))


class ScriptureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translation: str = Field(default="KJV", max_length=40)
    text: str = Field(default="", max_length=20000)
    passage: str = Field(default="", max_length=80)


@router.post("/cinematic/scripture/check")
def scripture_check(body: ScriptureIn):
    """Free: the guard's verdict on pasted scripture text and the passage reference (nothing is saved)."""
    from . import scripture
    out = scripture.check_text(body.text, body.translation) if body.text.strip() else {"status": "ok", "reasons": []}
    if body.passage:
        try:
            out["passage"] = scripture.parse_reference(body.passage)["text"]
        except ValueError as e:
            out["passage_error"] = str(e)
    return out


# ================================================================== the shot chat (shot_chat.py)
def chat_context(db: Session, ep: Episode, step: str, item: str) -> dict:
    v = stored(db, ep.id)
    if step == "cine_line":
        ln = next((x for x in lines_of(screenplay(v)) if x["id"] == item), None)
        if ln is None:
            raise HTTPException(404, "no such line")
        c = _chars(db, v).get(ln["speaker"])
        return {"item": f"Dialogue line {item} (shot {ln['n']})", "line": f"{ln['speaker']} ({ln['emotion']}): \"{ln['text']}\"",
                "settings": {"voice": c.voice if c else None, "voices": [x["id"] for x in TTS.catalogue()],
                             "engine": "Kokoro-82M (free, on the studio server)"}}
    n = int(item)
    s = _shot_or_404(v, n)
    st = (v.get("shots") or {}).get(str(n)) or {}
    cx = {"item": f"Shot {n} ({s['size']}, {s['camera']}) at {s['location']}", "action": s.get("action"), "vfx": s.get("vfx"),
          "people": s.get("characters"), "line": s.get("line"), "rule": INVENTED_PEOPLE_RULE}
    if step == "cine_still":
        prov = config(db, v)["still_provider"]
        inp = still_inputs(db, ep, v, s, prov)
        cx.update(current_prompt=inp["prompt"], settings={"provider": STILL_PROVIDERS[prov],
                                                          "takes": len(st.get("stills") or []), "approved": bool(st.get("approved"))})
    else:
        t, why = render_task(db, ep, v, s)
        cx.update(current_prompt=(t or {}).get("prompt") or st.get("motion_prompt") or "",
                  settings={"model": "Wan 2.2 i2v 14B (4-step)" if s["kind"] == "motion" else "Wan 2.2 Speech-to-Video B",
                            "camera_moves": list(G.CAMERAS), "results": len(st.get("renders") or []), "blocked": why})
    return cx


# ================================================================== the jobs
from .tasks import Ctx, task  # noqa: E402


def _put_take(db: Session, eid: int, n: int, field: str, rec: dict, run_field: str = "run") -> None:
    db.expire_all()
    v = stored(db, eid)
    st = _shot_state(v, n)
    st[field] = [rec] + (st.get(field) or [])
    st[run_field] = {**(st.get(run_field) or {}), "status": "done", "finished": time.time(), "stage": ""}
    save(db, eid, v)
    db.commit()


def _set_run(db: Session, eid: int, n: int, field: str = "run", **run) -> None:
    db.expire_all()
    v = stored(db, eid)
    st = _shot_state(v, n)
    st[field] = {**(st.get(field) or {}), **run}
    save(db, eid, v)
    db.commit()


@task
def cinematic_still(ctx: Ctx) -> dict:
    """One Nano Banana still (paid, one image, never retried): the location picture and the masters as references."""
    from .stick_pipeline import run_images
    from .tasks import store_asset
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    n = int(p["shot"])
    folder = ctx.folder("episodes", ep.id, "cinematic", f"still-job{job.id}")
    _set_run(db, ep.id, n, "still_run", status="running", started=time.time(), error="")
    asset = None
    try:
        refs = [storage().get_to_file(k, folder / f"ref-{i}{Path(k).suffix or '.png'}") for i, k in enumerate(p.get("refs") or [])]
        for _i, f in run_images(ctx, p["provider"], p["prompt"], refs, 1, float(p["usd"]), "16:9", folder, f"episode {ep.id} shot {n}"):
            tid = pysecrets.token_hex(4)
            k = f"episodes/{ep.id}/cinematic/still-{n:03d}-{tid}.png"
            asset = store_asset(db, ep_id=ep.id, src=f, key=k, kind="image", label=f"Cinematic shot {n} still",
                                content_type="image/png", job_id=job.id)
            db.commit()
            _put_take(db, ep.id, n, "end_stills" if p.get("end") else "stills",
                      {"id": tid, "asset_id": asset.id, "key": k, "at": time.time(), "usd": float(p["usd"]), "provider": "nano",
                       "prompt": p["prompt"], "job_id": job.id}, "still_run")
        _event(db, ep.id, f"Shot {n}: still made (not approved)")
        db.commit()
    except Exception as e:
        _set_run(db, ep.id, n, "still_run", status="failed", error=str(e)[:300])
        raise
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {"shot": n, "asset_id": asset.id if asset else None, "usd": float(p["usd"])}


@task
def cinematic_voice(ctx: Ctx) -> dict:
    """Lines spoken by Kokoro on the studio server (free). Every take waits for the owner's approval."""
    from .tasks import store_asset
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    v = stored(db, ep.id)
    lines = {ln["id"]: ln for ln in lines_of(screenplay(v))}
    chars = _chars(db, v)
    folder = ctx.folder("episodes", ep.id, "cinematic", f"voice-job{job.id}")
    done = []
    try:
        for lid in p.get("lines") or []:
            ln = lines.get(lid)
            if ln is None:
                continue
            c = chars.get(ln["speaker"])
            voice = (p.get("overrides") or {}).get("voice") or (c.voice if c else "")
            out = TTS.speak(ln["text"], voice, ln.get("emotion") or "", folder / f"{lid}.wav")
            secs = TTS.seconds_of(out)
            tid = pysecrets.token_hex(4)
            k = f"episodes/{ep.id}/cinematic/line-{lid}-{tid}.wav"
            a = store_asset(db, ep_id=ep.id, src=out, key=k, kind="audio", label=f"Line {lid} ({TTS.voice_id(voice)})",
                            content_type="audio/wav", job_id=job.id)
            db.commit()
            db.expire_all()
            v = stored(db, ep.id)
            st = _line_state(v, lid)
            st.setdefault("takes", []).insert(0, {"id": tid, "asset_id": a.id, "key": k, "source": "kokoro",
                                                  "voice": TTS.voice_id(voice), "seconds": secs, "at": time.time(),
                                                  "text": ln["text"], "job_id": job.id})
            save(db, ep.id, v)
            db.commit()
            done.append(lid)
            ctx.log(f"{lid}: {secs:.1f} s with {voice}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    _event(db, ep.id, f"{len(done)} line(s) spoken with Kokoro (free; waiting for your approval)")
    db.commit()
    return {"done": done, "usd": 0.0}


def _ffmpeg() -> str:
    from .config import get_settings
    ff = get_settings().ffmpeg
    if not ff:
        raise RuntimeError("FFmpeg is not configured on this server (FFMPEG)")
    return ff


def _run_ff(cmd: list[str], what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg could not {what}: {(r.stderr or r.stdout or '')[-400:]}")


def pad_voice(src: Path, dst: Path, seconds: float = 1.0) -> Path:
    """The voice take with 1 s of silence after it (the last S2V piece never runs short), mono 16 kHz WAV."""
    _run_ff([_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-af", f"apad=pad_dur={seconds}", "-ac", "1", "-ar", "16000",
             str(dst)], "pad the voice")
    return dst


def last_frame(video: Path, dst: Path) -> Path:
    _run_ff([_ffmpeg(), "-v", "error", "-y", "-sseof", "-0.2", "-i", str(video), "-update", "1", "-q:v", "1", str(dst)],
            "take the last frame")
    return dst


def join_pieces(pieces: list[Path], dst: Path) -> Path:
    """Pieces joined; every later piece starts with the previous piece's last frame, so its first frame is dropped."""
    if len(pieces) == 1:
        shutil.copy(pieces[0], dst)
        return dst
    ins, parts = [], []
    for i, p in enumerate(pieces):
        ins += ["-i", str(p)]
        parts.append(f"[{i}:v]{'trim=start_frame=1,' if i else ''}setpts=PTS-STARTPTS[p{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=1:a=0[out]"
    _run_ff([_ffmpeg(), "-v", "error", "-y", *ins, "-filter_complex", graph, "-map", "[out]", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-r", str(G.FPS), str(dst)], "join the pieces")
    return dst


def _fit(src: Path, dst: Path, size: tuple[int, int]) -> Path:
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        ImageOps.fit(im.convert("RGB"), size, method=Image.LANCZOS).save(dst)
    return dst


def models_for(tasks: list[dict]) -> list[dict]:
    """The model files one run needs (each once): Qwen (+ 2512 for a still with no reference), Wan i2v, S2V."""
    from . import reactions as R
    from . import talking_s2v as T
    out: list[dict] = []

    def add(ms):
        for m in ms:
            if m["filename"] not in {x["filename"] for x in out}:
                out.append(m)
    kinds = {t["kind"] for t in tasks}
    if "still" in kinds:
        add(R.QWEN_MODELS)
        if any(not t.get("refs") for t in tasks if t["kind"] == "still"):
            add([G.QWEN_IMAGE_2512])
    if "motion" in kinds:
        add(R.WAN_MODELS)
    if "talk" in kinds:
        add(T.MODELS)
    return out


from .reactions import _Run as _ReactRun  # noqa: E402


class _CineRun(_ReactRun):
    """reactions' GPU run (session, spend, confirmed limit, graph polling, turn-off), reporting into the shot."""

    def __init__(self, ctx: Ctx, eid: int, confirm: float):
        super().__init__(ctx, eid, 0, confirm)
        self.shot = 0

    def stage(self, text: str) -> None:
        self.ctx.log(text)
        if self.shot:
            _set_run(self.db, self.eid, self.shot, stage=text)


def _video_result(cl, outs: dict, folder: Path, name: str) -> Path:
    from .comfy import ComfyError, video_outputs
    files = [f for f in video_outputs(outs) if f.get("type", "output") == "output"]
    if not files:
        raise ComfyError("the GPU returned no video")
    got = [cl.download(f, folder / f"{name}-{k}{Path(f['filename']).suffix}") for k, f in enumerate(files)]
    return max(got, key=lambda x: x.stat().st_size)


def _gpu_task(run: "_CineRun", sess: dict, ep: Episode, job: Job, t: dict, inp: dict, folder: Path, mins: float) -> None:
    from . import gpu
    from . import reactions as R
    from . import talking_s2v as T
    from .comfy import ComfyError
    from .tasks import store_asset
    db, n, cl = run.db, t["shot"], sess["client"]
    rid = uuid.uuid4().hex[:8]
    seed = random.randint(1, 2**31 - 1)
    t0 = gpu.clock()
    if t["kind"] == "still":
        names = [cl.upload(f) for f in inp["refs"]]
        outs = run.run_graph(G.qwen_still_graph(names, t["prompt"], seed, f"ep{ep.id}-still{n:03d}-{rid}", R.QWEN_MODELS), mins)
        files = [f for f in R.image_outputs(outs) if f.get("type", "output") == "output"]
        if not files:
            raise ComfyError("the GPU returned no picture")
        res = cl.download(files[0], folder / f"still{n:03d}-{rid}.png")
        k = f"episodes/{ep.id}/cinematic/still-{n:03d}-{rid}.png"
        a = store_asset(db, ep_id=ep.id, src=res, key=k, kind="image", label=f"Cinematic shot {n} still (Qwen)",
                        content_type="image/png", job_id=job.id)
        db.commit()
        usd = round(float(sess["price_per_hour"]) * (gpu.clock() - t0) / 3600, 3)
        _put_take(db, ep.id, n, "end_stills" if t.get("end") else "stills",
                  {"id": rid, "asset_id": a.id, "key": k, "at": time.time(), "usd": usd, "provider": "qwen",
                   "prompt": t["prompt"], "seed": seed, "job_id": job.id})
        return
    if t["kind"] == "motion":
        lens = t.get("pieces") or [G.PIECE]
        pieces, start = [], cl.upload(inp["still"])
        for j, L in enumerate(lens):
            end = cl.upload(inp["end"]) if inp.get("end") and j == len(lens) - 1 else None
            outs = run.run_graph(G.i2v_graph(start, end, t["prompt"], seed + j, f"ep{ep.id}-shot{n:03d}-{rid}-{j}",
                                             R.WAN_MODELS, L), G.PIECE_MIN)
            pv = _video_result(cl, outs, folder, f"shot{n:03d}-{rid}-{j}")
            pieces.append(pv)
            if j + 1 < len(lens):
                start = cl.upload(last_frame(pv, folder / f"ep{ep.id}-s{n}-{rid}-last{j}.png"))
        result = join_pieces(pieces, folder / f"shot{n:03d}-{rid}.mp4")
        frames = len(lens) * G.PIECE - (len(lens) - 1)
    else:
        img, aud = cl.upload(inp["still"]), cl.upload(inp["voice"])
        outs = run.run_graph(T.build_graph(t["prompt"], G.TALK_NEG, img, aud, None, int(t["frames"]), seed,
                                           f"video/ep{ep.id}-talk{n:03d}-{rid}"), mins)
        result = _video_result(cl, outs, folder, f"talk{n:03d}-{rid}")
        frames = sum(T.pieces(int(t["frames"])))
    k = f"episodes/{ep.id}/cinematic/shot-{n:03d}-{rid}.mp4"
    a = store_asset(db, ep_id=ep.id, src=result, key=k, kind="video", label=f"Cinematic shot {n} ({t['kind']})",
                    content_type="video/mp4", job_id=job.id)
    db.commit()
    usd = round(float(sess["price_per_hour"]) * (gpu.clock() - t0) / 3600, 3)
    _put_take(db, ep.id, n, "renders",
              {"id": rid, "asset_id": a.id, "key": k, "kind": t["kind"], "frames": frames, "fps": G.FPS,
               "prompt": t["prompt"], "seed": seed, "gpu": sess["gpu_type"], "usd": usd, "job_id": job.id,
               "voice_take": t.get("voice_take"), "first_last": bool(t.get("end")), "at": time.time()})


@task
def cinematic_gpu(ctx: Ctx) -> dict:
    """Stills (Qwen), motion shots (Wan i2v) and dialogue shots (S2V B) on one rented ComfyUI session. Stops before a
    task that would pass the confirmed amount. Every result waits for the owner's approval."""
    from . import gpu
    from . import talking_s2v as T
    from .comfy import ComfyError
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    p = job.payload or {}
    tasks = list(p.get("tasks") or [])
    run = _CineRun(ctx, ep.id, float(p.get("confirm_usd") or 0))
    folder = ctx.folder("episodes", ep.id, "cinematic", f"gpu-job{job.id}")
    models = models_for(tasks)
    done, failed, skipped = [], [], []
    try:
        local = {}
        for i, t in enumerate(tasks):            # inputs made on the studio server first (free)
            d = folder / f"t{i:02d}"
            d.mkdir(parents=True, exist_ok=True)
            got: dict = {}
            if t["kind"] == "still":
                got["refs"] = [_fit(storage().get_to_file(k, d / f"ref{j}{Path(k).suffix or '.png'}"),
                                    d / f"ep{ep.id}-s{t['shot']}-ref{j}.png", (1024, 1024)) for j, k in enumerate(t.get("refs") or [])]
            else:
                size = (T.W, T.H) if t["kind"] == "talk" else (G.W, G.H)
                got["still"] = _fit(storage().get_to_file(t["still"], d / "still-src.png"), d / f"ep{ep.id}-s{t['shot']}-start.png", size)
                if t.get("end"):
                    got["end"] = _fit(storage().get_to_file(t["end"], d / "end-src.png"), d / f"ep{ep.id}-s{t['shot']}-end.png", size)
                if t["kind"] == "talk":
                    src = storage().get_to_file(t["voice"], d / f"voice-src{Path(t['voice']).suffix or '.wav'}")
                    got["voice"] = pad_voice(src, d / f"ep{ep.id}-s{t['shot']}-voice.wav")
            local[i] = got
        run.shot = tasks[0]["shot"] if tasks else 0
        sess = run.session(models)
        for i, t in enumerate(tasks):
            n = t["shot"]
            run.shot = n
            mins = G.task_minutes(t)[1]
            if not run.room_for(mins):
                _set_run(db, ep.id, n, status="skipped", error=f"not started: it would pass the confirmed ${run.confirm:.2f}")
                skipped.append(n)
                continue
            left = int(get_section(db, "gpu")["max_lifetime_minutes"]) * 60 - (gpu.clock() - sess["launched_at"])
            if left < mins * 60 * 1.3 + 60:
                gpu.terminate_session(db, sess["session"], "replaced: the next shot would pass the maximum session length")
                sess = run.session(models)
            _set_run(db, ep.id, n, status="running", started=time.time(), est_s=int(mins * 60), error="",
                     stage=f"Making shot {n} on {sess['gpu_type']}")
            try:
                _gpu_task(run, sess, ep, job, t, local[i], folder, mins)
                _event(db, ep.id, f"Shot {n}: {t['kind']} made on {sess['gpu_type']} (not approved)")
                db.commit()
                done.append(n)
            except ComfyError as e:
                _set_run(db, ep.id, n, status="failed", error=str(e)[:300], stage="")
                failed.append(n)
                ctx.log(f"shot {n}: {e}")
    except Exception as e:
        for t in tasks:
            if t["shot"] not in done + failed + skipped:
                _set_run(db, ep.id, t["shot"], status="failed", error=str(e)[:300], stage="")
        raise
    finally:
        run.finish(job.id)
        shutil.rmtree(folder, ignore_errors=True)
    if failed and not done:
        raise ComfyError(f"shot(s) {', '.join(map(str, failed))} failed on the GPU; see the log")
    return {"done": done, "failed": failed, "skipped": skipped, "usd": round(run.spent(), 3)}


@task
def cinematic_assembly(ctx: Ctx) -> dict:
    """The final cut (free, FFmpeg): approved clips / held stills in order, the approved voice takes at their shots,
    the optional music under them, captions when on. It waits for the owner's approval."""
    from . import assembly as A
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    ff = _ffmpeg()
    p = plan_rows(db, ep)
    if p["missing"]:
        raise ValueError("shot(s) " + ", ".join(map(str, p["missing"])) + " have no approved still or clip any more")
    v = stored(db, ep.id)
    cfg = config(db, v)
    w, h = p["size"]
    folder = ctx.folder("episodes", ep.id, f"cinematic-assembly-job{job.id}")
    try:
        listing = []
        for r in p["rows"]:
            src = storage().get_to_file(r["key"], folder / f"src{r['index']:03d}{Path(r['key']).suffix or '.bin'}")
            seg = folder / f"seg{r['index']:03d}.mp4"
            _run_ff(A.segment_command(ff, r, src, seg, w, h), f"make shot {r['index']}")
            listing.append(f"file '{seg.resolve().as_posix()}'")
        (folder / "list.txt").write_text("\n".join(listing) + "\n")
        total = p["frames"] / A.FPS
        lines = [r for r in p["rows"] if r.get("line")]
        pics = []
        if cfg["captions"] and lines:
            ov = A.render_overlays(db, ep, (w, h), folder, ctx.log, lines=[
                {"start": r["start"], "end": r["start"] + float(r["line"]["seconds"] or r["seconds"]), "text": r["line"]["text"]}
                for r in lines], mode="captions", hook="")
            pics = ov["lines"]
            if ov["warning"]:
                ctx.log(ov["warning"])
        video = folder / "video.mp4"
        cmd = [ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(folder / "list.txt"),
               "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        for _a, _b, pic in pics:
            cmd += ["-i", str(pic)]
        if pics:
            graph, last = A.overlay_graph([(a_, b_) for a_, b_, _ in pics], False)
            cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
        else:
            cmd += ["-map", "0:v"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(A.FPS),
                "-t", f"{total:.3f}", "-an", str(video)]
        _run_ff(cmd, "join the shots")
        cmd = [ff, "-v", "error", "-y", "-i", str(video)]
        for r in lines:
            cmd += ["-i", str(storage().get_to_file(r["line"]["key"], folder / f"line{r['index']:03d}{Path(r['line']['key']).suffix or '.wav'}"))]
        music = v.get("music")
        if music:
            cmd += ["-i", str(storage().get_to_file(music["key"], folder / f"music{Path(music['key']).suffix or '.mp3'}"))]
        graph = G.voice_audio_graph([r["start"] for r in lines], bool(music), total, float(cfg["music_volume"]))
        out = folder / "final.mp4"
        cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        _run_ff(cmd, "mix the voices and the music")
        cid = uuid.uuid4().hex[:8]
        k = f"episodes/{ep.id}/cinematic/final-{cid}.mp4"
        storage().put_file(k, out, "video/mp4")
        a = Asset(episode_id=ep.id, job_id=job.id, kind="video", label="Cinematic final cut (waiting for your approval)",
                  storage_key=k, content_type="video/mp4", size=out.stat().st_size, sha256=sha256_file(out))
        db.add(a)
        db.flush()
        cut = {"id": cid, "asset_id": a.id, "at": time.time(), "by": (job.payload or {}).get("by"), "hash": p["hash"],
               "seconds": round(total, 3), "frames": p["frames"], "music": bool(music), "captions": bool(pics),
               "stills": sum(1 for r in p["rows"] if r["source"] == "still"),
               "rows": [{k2: r[k2] for k2 in ("index", "start", "seconds", "frames", "source", "label", "warnings")} for r in p["rows"]]}
        db.commit()
        db.expire_all()
        v = stored(db, ep.id)
        v["cuts"] = ([cut] + (v.get("cuts") or []))[:10]
        save(db, ep.id, v)
        _event(db, ep.id, f"Cinematic final cut made: {len(p['rows'])} shots, {total:.1f} s (not approved)")
        db.commit()
        return {"cut": cid, "seconds": round(total, 3), "usd": 0.0}
    finally:
        shutil.rmtree(folder, ignore_errors=True)
