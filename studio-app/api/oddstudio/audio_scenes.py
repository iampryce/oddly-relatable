"""Audio-first Stage 2 (owner decision 2026-11-20): scenes built AROUND the recorded dialogue.

The transcript's timed lines (speaker = a character key, text, start/end in the audio) are fixed: they are what was
recorded. The writer only decides
  * where the scenes are: each scene is a run of CONSECUTIVE line ids (a cut can only fall between two lines, and
    every line belongs to exactly one scene, in order), with a heading, location, what we see, action and camera;
  * the acting per line: expression, gesture, look_at, shot, and silent reactions of the other characters on screen
    (including the silent cast: characters named in the audio who never speak).
The server builds the script from the writer's plan, copying speaker, text and timing from the transcript itself, and
validates it. If the writer is not configured, fails, or returns a plan that breaks the rules, a deterministic split
is used instead (new scene at a long pause, at most MAX_RUN lines per scene), so the episode can always move on.

The resulting script goes through the normal review: the owner approves it (and then the storyboard) in the
dashboard. Dialogue edits are refused on audio episodes everywhere (script edit, scene edit, regeneration).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import serialize as S
from .auth import current_user
from .db import get_db
from .models import Character, Episode, Event
from .queue import enqueue
from .script_schema import GESTURES, SHOTS, ScriptError, validate_script
from .workflow import set_stage

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

SCENE_GAP = 1.5          # a pause this long between two lines starts a new scene in the simple split
MAX_RUN = 6              # lines per scene in the simple split
DIALOGUE = ("line_id", "speaker", "text", "start", "end")
EXPRESSIONS = ("neutral", "happy", "laughing", "shocked", "worried", "annoyed", "deadpan", "sad", "angry", "confused",
               "embarrassed", "smug", "pleading")


# ------------------------------------------------------------------ pure functions
def simple_runs(lines: list[dict], gap: float = SCENE_GAP, max_run: int = MAX_RUN, max_scenes: int = 12) -> list[list[str]]:
    """The deterministic split: a new scene after a pause of `gap` seconds or after `max_run` lines; if that makes
    too many scenes, the shortest neighbouring scenes are joined until it fits."""
    runs: list[list[str]] = []
    for i, ln in enumerate(lines):
        if not runs or (ln["start"] - lines[i - 1]["end"] >= gap) or len(runs[-1]) >= max_run:
            runs.append([])
        runs[-1].append(ln["id"])
    while len(runs) > max_scenes:
        k = min(range(len(runs) - 1), key=lambda j: len(runs[j]) + len(runs[j + 1]))
        runs[k:k + 2] = [runs[k] + runs[k + 1]]
    return runs


def check_runs(runs: list[list[str]], line_ids: list[str]) -> None:
    """Every line exactly once, in order, each scene a non-empty run: cuts only between lines."""
    if any(not r for r in runs):
        raise ScriptError("a scene has no lines")
    flat = [x for r in runs for x in r]
    if flat != line_ids:
        missing = [x for x in line_ids if x not in flat]
        extra = [x for x in flat if x not in line_ids]
        dup = sorted({x for x in flat if flat.count(x) > 1})
        why = (f"missing {missing}" if missing else f"unknown {extra}" if extra else f"repeated {dup}" if dup
               else "out of order")
        raise ScriptError(f"the scenes must cover every line once, in order, cutting only between lines ({why})")


def _acting(raw: dict, keys: set[str]) -> dict:
    out = {}
    e = str((raw or {}).get("expression") or "neutral").strip().lower()[:40]
    out["expression"] = e or "neutral"
    shot = str((raw or {}).get("shot") or "").strip().lower()
    out["shot"] = shot if shot in SHOTS else "wide"   # the same default as a script-first line
    g = str((raw or {}).get("gesture") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if g in GESTURES and g != "none":
        out["gesture"] = g
    if (raw or {}).get("look_at") in keys:
        out["look_at"] = raw["look_at"]
    reacts = [r for r in (raw or {}).get("reactions") or [] if isinstance(r, dict) and r.get("character") in keys]
    if reacts:
        out["reactions"] = reacts[:3]
    return out


def notes_acting(lines: list[dict], notes: list[dict], silent: list[str], cast: list[str] | None = None) -> dict:
    """The simple split's use of the video notes: each line's shot from the note that covers it, the speaker looking
    at whom the note says they face, and reaction cutaways of the silent characters for the note's reactors. Never
    touches the dialogue."""
    from . import video_notes as VN
    from .reference_plan import role_map
    out = {}
    for ln in lines:
        r = VN.for_line(notes, ln)
        if not r:
            continue
        a = {}
        if r.get("shot"):
            a["shot"] = r["shot"]
        roles = role_map([ln], cast or [], silent, r)
        sp = next((ro for ro in r.get("roles", []) if ro.get("role") == "speaker"), None)
        if sp and roles.get(sp.get("facing", "")) and roles[sp["facing"]] != ln["speaker"]:
            a["look_at"] = roles[sp["facing"]]
        reactors = [ro for ro in r.get("roles", []) if ro["role"].startswith("reactor") and ro.get("react", True)]
        if silent and reactors:
            # each reactor's own character (confirmed people), else the N-th silent character; never wrapped around,
            # never the speaker, never twice; an unconfirmed or extra person gives no reaction
            order = [x["role"] for x in r.get("roles", []) if x.get("role", "").startswith("reactor")]

            def reactor(ro):
                if "who" in ro:
                    return roles.get(ro["role"])
                k = order.index(ro["role"])          # the k-th reactor present is the k-th silent character
                return silent[k] if k < len(silent) else None
            seen, reacts = {ln["speaker"]}, []
            for ro in reactors:
                k = reactor(ro)
                if k and k not in seen:
                    seen.add(k)
                    reacts.append({"character": k, "expression": VN.EMOTION_EXPRESSION.get(ro.get("emotion", ""), "neutral")})
            if reacts:
                a["reactions"] = reacts[:3]
        if a:
            out[ln["id"]] = a
    return out


def build_script(title: str, lines: list[dict], cast: list[str], silent: list[str], plan: dict | None, fmt: str = "short",
                 known: set[str] | None = None, notes: list[dict] | None = None, set_words: list | None = None,
                 view_split: bool = False, actions: list[dict] | None = None, set_views: list | None = None) -> dict:
    """The audio episode's script: the writer's plan (or the simple split when `plan` is None) around the transcript.
    The simple split uses the video notes (if any) for shots and silent reactions. Raises ScriptError when the plan
    breaks the rules."""
    ids = [ln["id"] for ln in lines]
    by_id = {ln["id"]: ln for ln in lines}
    keys = set(cast) | set(silent)
    if plan is None:
        runs0 = simple_runs(lines)
        if view_split and notes:
            # shot / reverse shot: a cut where the camera changes side (only when both sides have their own set)
            from . import video_notes as VN
            vof = {ln["id"]: (VN.for_line(notes, ln) or {}).get("view") for ln in lines}
            split = []
            for run in runs0:
                cur = [run[0]]
                for a, b in zip(run, run[1:]):
                    if vof.get(b) and vof.get(a) and vof[b] != vof[a]:
                        split.append(cur)
                        cur = []
                    cur.append(b)
                split.append(cur)
            runs0 = split
        scenes_in = [{"heading": f"Scene {i + 1}", "line_ids": r} for i, r in enumerate(runs0)]
        plan = {"scenes": scenes_in, "lines": notes_acting(lines, notes or [], silent, cast)}
    scenes_in = plan.get("scenes")
    if not isinstance(scenes_in, list) or not scenes_in:
        raise ScriptError("the plan has no scenes")
    runs = [[str(x) for x in (s.get("line_ids") or [])] if isinstance(s, dict) else [] for s in scenes_in]
    check_runs(runs, ids)
    acting = plan.get("lines") if isinstance(plan.get("lines"), dict) else {}
    scenes = []
    for i, (s, run) in enumerate(zip(scenes_in, runs)):
        sl = []
        for lid in run:
            ln = by_id[lid]
            sl.append({"line_id": lid, "speaker": ln["speaker"], "text": ln["text"], "start": ln["start"], "end": ln["end"],
                       **_acting(acting.get(lid) or {}, keys - {ln["speaker"]})})
        scenes.append({"id": f"s{i + 1}", "heading": str(s.get("heading") or f"Scene {i + 1}")[:200],
                       "location": str(s.get("location") or "")[:80], "description": str(s.get("description") or ""),
                       "action": str(s.get("action") or ""), "camera": str(s.get("camera") or "")[:400], "lines": sl})
        # how the scene starts: the writer's staging when valid, else the note covering its first line (speaker first)
        st = s.get("staging") if isinstance(s.get("staging"), dict) else None
        st = {k: v for k, v in (st or {}).items() if k in keys and v in ("seated", "standing")} or None
        if st is None and notes:
            from . import video_notes as VN
            from .reference_plan import staging_for
            st = staging_for([by_id[run[0]]], VN.for_line(notes, by_id[run[0]]), cast, silent) or None
        if st:
            scenes[-1]["staging"] = st
        if isinstance(s.get("set"), str) and s["set"].strip():
            scenes[-1]["set"] = s["set"].strip()[:80]
        if set_words is not None:
            from . import video_notes as VN
            r = VN.for_line(notes or [], by_id[run[0]])
            set_words.append((r or {}).get("setting"))
            if set_views is not None:
                set_views.append((r or {}).get("view"))
        if fmt == "long":   # a long episode's scenes belong to acts 1-3: the recording's order, split in thirds
            scenes[-1]["act"] = 1 + (i * 3) // len(runs)
    if notes:
        carry_staging(scenes, runs, by_id, notes, cast, silent, actions or [])
    # the video's beats as timed actions, each in the scene whose time span holds it (dialogue and timing untouched)
    if actions:
        starts = [by_id[run[0]]["start"] for run in runs]
        for a in actions:
            j = max([k for k, s0 in enumerate(starts) if s0 <= a["t"]] or [0])
            scenes[j].setdefault("actions", []).append(a)
    doc = {"title": str(plan.get("title") or title)[:100] or title[:100], "logline": str(plan.get("logline") or "")[:400],
           "hook": str(plan.get("hook") or "")[:90], "twist": "", "interactive": {"type": "none"},
           "characters": [{"key": k, "role": "silent" if k in silent else ""} for k in list(dict.fromkeys(cast + silent))],
           "scenes": scenes}
    return validate_script(doc, known, fmt=fmt)


def carry_staging(scenes: list[dict], runs: list[list[str]], by_id: dict, notes: list[dict], cast: list[str],
                  silent: list[str], actions: list[dict]) -> None:
    """Scene continuity (owner decision 2026-11-22, Episode 14): a cut to a close-up is the camera, not people leaving.
    - Scene 1 starts with its own staging plus everyone the notes show anywhere inside its time span (so a close-up
      first line does not leave the others out); a scene 1 without a staging of its own (Seating ignored) stays so.
    - Every later scene starts from the previous scene's staging, in the same seat order (nobody changes seats at a
      cut); its own first-line notes only update the people they show (e.g. someone now standing).
    - Someone leaves only when the accepted plan has an exit beat for them between the two scene starts (and no later
      enter); an accepted enter beat brings them back (standing, unless the notes seat them)."""
    from . import video_notes as VN
    from .reference_plan import staging_for
    if not scenes:
        return
    starts = [by_id[run[0]]["start"] for run in runs]
    ends = [by_id[run[-1]]["end"] for run in runs]
    # scene 1: its first line's staging, then anyone seated or standing in the notes inside its span (first seen first)
    first = dict(scenes[0].get("staging") or {})
    # only to complete a first-line staging that exists (a close-up): when the first range's Seating is ignored in the
    # plan (or empty), scene 1 stays without a starting arrangement, as before
    for r in sorted((r for r in notes if first and r["start"] < ends[0] and r["end"] > starts[0]), key=lambda r: r["start"]):
        ln = next((by_id[x] for x in runs[0] if by_id[x]["start"] < r["end"] and by_id[x]["end"] > r["start"]), by_id[runs[0][0]])
        for k, v in staging_for([ln], r, cast, silent).items():
            first.setdefault(k, v)
    if first:
        scenes[0]["staging"] = first
    prev = first
    events = sorted(a for a in ((x["t"], x["type"], x["character"]) for x in actions) if a[1] in ("enter", "exit"))
    for i in range(1, len(scenes)):
        st = dict(prev)
        for t, kind, k in events:
            if starts[i - 1] <= t < starts[i]:
                if kind == "exit":
                    st.pop(k, None)
                elif k not in st:
                    st[k] = "standing"
        for k, v in (scenes[i].get("staging") or {}).items():
            st[k] = v                        # the scene's own notes update the people they show (existing seats kept)
        if st:
            scenes[i]["staging"] = st
        prev = st


def dialogue_of(script_or_lines) -> list[tuple]:
    lines = script_or_lines if isinstance(script_or_lines, list) else [ln for s in script_or_lines["scenes"] for ln in s["lines"]]
    return [tuple(ln.get(k) for k in DIALOGUE) for ln in lines]


def guard_dialogue(before, after, where: str = "the script") -> None:
    """Refuse any change to the recorded dialogue (line ids, speakers, text, timing, order, lines added or removed)."""
    if dialogue_of(before) != dialogue_of(after):
        raise ScriptError(f"{where}: the dialogue comes from the audio and cannot be changed here (speaker, text, timing "
                          "and order are fixed; you can change expressions, gestures, looks, shots and the scene details)")


def transcript_dialogue(ep: Episode) -> list[dict]:
    return [{"line_id": ln["id"], **{k: ln.get(k) for k in ("speaker", "text", "start", "end")}}
            for ln in (ep.audio_transcript or {}).get("lines", [])]


# ------------------------------------------------------------------ the writer
SYSTEM = ("You direct an adult 2D animated comedy. The dialogue was RECORDED: you never change, add, remove or reorder a "
          "line. You only decide where the scenes are and how the characters act each line. Reply with one JSON object only.")


def beat_actions(beats: list[dict], person_map: dict, keys: set[str]) -> list[dict]:
    """The beats of CONFIRMED people as actions on character keys (unconfirmed people's beats are not acted; the
    builders already pass reference_plan.effective_beats, which leaves them out too)."""
    who = {int(v): k for k, v in (person_map or {}).items() if v and k in keys}
    out = []
    for b in beats:
        k = who.get(b["person"])
        if not k:
            continue
        a = {"t": b["t"], "character": k, "type": b["type"]}
        if b["type"] == "turn_to":
            tgt = who.get(int(b["target"].split()[1]))
            if not tgt:
                continue
            a["target"] = tgt
        elif b.get("target"):
            a["target"] = b["target"]
        if b.get("gesture"):
            a["gesture"] = b["gesture"]
        out.append(a)
    return out


def notes_text(lines: list[dict], notes: list[dict]) -> str:
    from . import video_notes as VN
    rows = []
    for ln in lines:
        r = VN.for_line(notes, ln)
        if r and VN.describe(r):
            rows.append(f"[{ln['id']}] {VN.describe(r)}")
    if not rows:
        return ""
    return ("\nVideo notes (from a reference video, text only, accepted by the owner in the Reference plan). Use them as "
            "STRONG suggestions: each line's shot and camera, who reacts, and how each scene starts (who is seated or "
            "standing, whom they face). Never change, add or remove dialogue or its timing; the characters and sets stay "
            "our own originals; roles are anonymous: 'speaker' is the line's speaker, 'reactor N' any of the others):\n"
            + "\n".join(rows) + "\n")


def prompt(lines: list[dict], cast: list[Character], silent: list[Character], hints: dict, environments: list[str],
           notes: list[dict] | None = None, sets_text: str = "") -> str:
    listing = "\n".join(f"[{ln['id']} | {ln['speaker']} | {ln['start']:.1f}-{ln['end']:.1f} s] {ln['text']}" for ln in lines)
    who = "\n".join(f"- {c.key}: {c.name}. {c.description[:160]}" for c in cast)
    quiet = "\n".join(f"- {c.key}: {c.name} (on screen, never speaks; can react)" for c in silent) or "(none)"
    hint = (f"The owner's video suggests: about {hints.get('people_count')} people, setting {hints.get('setting') or '?'}, "
            f"mood {hints.get('mood') or '?'}.\n" if hints else "")
    return (f"Recorded lines (id | speaker | time | text):\n{listing}\n\nSpeaking characters:\n{who}\n"
            f"Silent characters:\n{quiet}\n{hint}{notes_text(lines, notes or [])}{sets_text}Locations you may use: {', '.join(environments) or 'free text'}\n\n"
            "Group the lines into scenes (at most 12). A scene is a run of CONSECUTIVE line ids; cut only between lines; "
            "every line id appears exactly once, in order. For each line give the acting: expression (one of "
            f"{', '.join(EXPRESSIONS)}), gesture (one of {', '.join(g for g in GESTURES if g != 'none')} or none), look_at "
            "(a character key), shot (wide, medium or close), and optional silent reactions of other characters on "
            "screen. Also a title, a one-sentence logline and an on-screen hook starting with 'POV: ' (at most one emoji).\n"
            "For each scene, optionally give its starting staging: each on-screen character seated or standing, the "
            "speaker of its first line first (the order is the seat order).\n"
            'JSON: {"title": "", "logline": "", "hook": "POV: ...", "scenes": [{"heading": "", "location": "", '
            '"description": "", "action": "", "camera": "", "set": "", "staging": {"key": "seated"}, "line_ids": ["l1", "l2"]}], '
            '"lines": {"l1": {"expression": "neutral", "gesture": "none", "look_at": "", "shot": "medium", '
            '"reactions": [{"character": "", "expression": "", "gesture": ""}]}}}')


# ------------------------------------------------------------------ routes
def _gate(ep: Episode, action: str) -> None:
    from .workflow import GateError, require
    try:
        require(ep, action)
    except GateError as e:
        raise HTTPException(409, str(e))


class ScenesIn(BaseModel):
    mode: str = "writer"      # writer | simple


@router.post("/episodes/{eid}/audio/scenes")
def build_scenes(eid: int, body: ScenesIn, db: Session = Depends(get_db)):
    """Build the scenes around the recorded lines (job `audio_scenes`): with the AI writer (falls back to the simple
    split if it fails) or directly with the simple split. Every line needs a speaker that is a character."""
    from .audio_first import audio_episode
    ep = audio_episode(db, eid)
    _gate(ep, "build_audio_scenes")
    check_buildable(db, ep, body.mode)
    set_stage(ep, "script_generating")
    ep.last_error = ""
    db.commit()
    return S.job(enqueue(db, "audio_scenes", episode_id=ep.id, revision=ep.revision, payload={"mode": body.mode}))


def check_buildable(db: Session, ep: Episode, mode: str) -> None:
    """What building the scenes needs: an accepted Reference plan (when there are notes), a known mode, the
    transcript, and a cast character as every line's speaker."""
    from .reference_plan import needs_acceptance
    if needs_acceptance(ep.audio_transcript or {}):
        raise HTTPException(409, "accept the Reference plan first (Audio tab, Reference plan): it shows what the video "
                                 "notes will drive, and nothing is built from them until you accept it")
    if mode not in ("writer", "simple"):
        raise HTTPException(422, "mode must be writer or simple")
    lines = (ep.audio_transcript or {}).get("lines", [])
    keys = {c.key for c in db.query(Character).all()}
    if not lines:
        raise HTTPException(409, "transcribe the audio first")
    if any(ln.get("speaker") not in keys for ln in lines):
        raise HTTPException(409, "give every line a speaker and apply the cast first (each speaker must be a character)")


def writer_estimate(db: Session, ep: Episode) -> dict:
    """What one AI-writer scene build is expected to cost: the prompt it would send (about 4 characters per token) and
    about 120 output tokens per line, at list prices; with a fallback provider set, the higher of the two."""
    from . import scene_sets
    from .reference_plan import effective
    from .sets import writer_environments
    from .settings_store import get_section
    from .shot_compare import TEXT_PRICES
    cfg = get_section(db, "text")
    prov, fb = cfg.get("provider", "none"), cfg.get("fallback", "none")
    if prov in ("none", ""):
        return {"provider": "none", "usd": 0.0, "note": "no text provider in Settings: the simple split is used (free)"}
    tr = ep.audio_transcript or {}
    lines = tr.get("lines", [])
    chars = {c.key: c for c in db.query(Character).all()}
    cast = list(dict.fromkeys(ln["speaker"] for ln in lines))
    silent = [m["character_key"] for m in tr.get("silent_cast", []) if m["character_key"] in chars and m["character_key"] not in cast]
    p = prompt(lines, [chars[k] for k in cast if k in chars], [chars[k] for k in silent], tr.get("media_hints") or {},
               writer_environments(db, ep), effective(tr), scene_sets.sets_text(db, ep))
    tin, tout = round((len(SYSTEM) + len(p)) / 4), 300 + 120 * len(lines)
    price = lambda x: (tin * TEXT_PRICES[x][0] + tout * TEXT_PRICES[x][1]) / 1e6 if x in TEXT_PRICES else 0.0
    usd = max(price(prov), price(fb) if fb not in ("none", "", prov) else 0.0)
    note = "" if prov in TEXT_PRICES else f"no per-call API cost for {prov}"
    if fb not in ("none", "", prov):
        note = f"estimate covers {prov} or its fallback {fb}"
    return {"provider": prov, "usd": round(usd, 4), "input_tokens": tin, "output_tokens": tout, "note": note}


KEEPS = ("every script version (the current one stays in the history)", "the stills images (kept in storage)",
         "poses and their approvals", "sets and their approvals", "the episode's chosen set",
         "the Reference plan and its acceptance", "the recording, transcript, speakers and cast")


def sheet_counts(scenes) -> tuple[int, int]:
    """(reaction beats, shot lists) on the storyboard (reaction_sheet.py): a rebuild discards them with the scenes, so
    the owner confirms that separately (owner request 2026-11-24)."""
    beats = sum(len(r.get("beats") or []) for s in scenes for ln in (s.lines or []) if isinstance(ln, dict)
                for r in (ln.get("reactions") or []) if isinstance(r, dict))
    return beats, sum(1 for s in scenes if s.shots)


def rebuild_preview(db: Session, ep: Episode) -> dict:
    scenes = sorted(ep.scenes, key=lambda s: s.position)
    beats, shots = sheet_counts(scenes)
    return {"stage": ep.stage,
            "discards": {"storyboard_scenes": len(scenes), "reaction_beats": beats, "shot_lists": shots,
                         "stills_unlinked": sum(1 for s in scenes if s.reference_asset_id),
                         "script_approval": (f"the approval of script v{ep.approved_script_version}"
                                             if ep.approved_script_version else "the script approval"),
                         "scene_edits": "per-scene edits on the storyboard (headings, descriptions, per-scene sets, staging)"},
            "keeps": list(KEEPS), "cost": {"writer": writer_estimate(db, ep), "simple": {"usd": 0.0, "note": "free"}},
            "after": "the episode goes back to script review with the new scenes: approve the script, then generate the "
                     "storyboard and refresh the stills (free) as usual"}


class RebuildIn(BaseModel):
    mode: str = "writer"      # writer | simple
    confirm: bool = False
    discard_reactions: bool = False   # required as well when the storyboard has reaction beats or shot lists


@router.get("/episodes/{eid}/audio/rebuild-scenes")
def rebuild_scenes_preview(eid: int, db: Session = Depends(get_db)):
    """What "Rebuild scenes from audio" would discard and keep, and the AI writer's estimated cost (nothing changes)."""
    from .audio_first import audio_episode
    ep = audio_episode(db, eid)
    _gate(ep, "rebuild_audio_scenes")
    return rebuild_preview(db, ep)


@router.post("/episodes/{eid}/audio/rebuild-scenes")
def rebuild_scenes(eid: int, body: RebuildIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    """After the script was approved (script approved, storyboard review or approved): discard the storyboard and the
    script approval and build the scenes again from the recording (the current scene continuity applies). Without
    confirm: the preview only. Poses, sets, the episode's set, the Reference plan and its acceptance, the recording,
    transcript and cast are not touched; nothing is approved."""
    from .audio_first import audio_episode
    ep = audio_episode(db, eid)
    _gate(ep, "rebuild_audio_scenes")
    check_buildable(db, ep, body.mode)
    preview = rebuild_preview(db, ep)
    if not body.confirm:
        return preview
    d = preview["discards"]
    if (d["reaction_beats"] or d["shot_lists"]) and not body.discard_reactions:
        raise HTTPException(409, f"this would also discard {d['reaction_beats']} reaction beat(s) and {d['shot_lists']} shot "
                                 "list(s) on the storyboard: confirm discarding them too (nothing was changed)")
    n = len(ep.scenes)
    for sc in list(ep.scenes):
        db.delete(sc)
    db.flush()
    was = ep.stage
    # the approvals of the discarded script and storyboard are withdrawn (as a script revision request does), so
    # nothing downstream keeps reading the old version as approved
    ep.approved_script_version = None
    ep.approved_storyboard_version = None
    set_stage(ep, "script_generating")
    ep.last_error = ""
    db.add(Event(episode_id=ep.id, kind="script",
                 message=f"Scenes rebuilt from the audio by {user} (from {was}): {n} storyboard scene(s) and "
                         f"{preview['discards']['script_approval']} discarded; {'AI writer' if body.mode == 'writer' else 'simple split'}"))
    db.commit()
    job = enqueue(db, "audio_scenes", episode_id=ep.id, revision=ep.revision, payload={"mode": body.mode})
    return {**preview, "job": S.job(job)}


@router.post("/episodes/{eid}/audio/reopen-labels")
def reopen_labels(eid: int, db: Session = Depends(get_db)):
    """Back from script review to the labels and cast (the scenes are then built again)."""
    from .audio_first import audio_episode, state
    ep = audio_episode(db, eid)
    _gate(ep, "reopen_audio_labels")
    set_stage(ep, "audio_labelling")
    db.add(Event(episode_id=ep.id, kind="episode", message="Back to the labels and cast (build the scenes again afterwards)"))
    db.commit()
    return state(db, ep)


# ------------------------------------------------------------------ the job
from .tasks import Ctx, save_script, task  # noqa: E402


@task
def audio_scenes(ctx: Ctx) -> dict:
    from .providers import ProviderError, ProviderNotConfigured, text_provider
    from .sets import writer_environments
    from .settings_store import get_section
    db, job = ctx.db, ctx.job
    ep = db.get(Episode, job.episode_id)
    tr = ep.audio_transcript or {}
    lines = tr.get("lines", [])
    chars = {c.key: c for c in db.query(Character).all()}
    cast = list(dict.fromkeys(ln["speaker"] for ln in lines))
    silent = [m["character_key"] for m in tr.get("silent_cast", []) if m["character_key"] in chars and m["character_key"] not in cast]
    from . import scene_sets
    from .reference_plan import effective
    notes = effective(tr)    # the notes as accepted in the Reference plan (edits applied, ignored items left out)
    plan, how = None, "simple split"
    if (job.payload or {}).get("mode") == "writer":
        try:
            ans = text_provider(get_section(db, "text")).complete_json(
                SYSTEM, prompt(lines, [chars[k] for k in cast], [chars[k] for k in silent], tr.get("media_hints") or {},
                               writer_environments(db, ep), notes, scene_sets.sets_text(db, ep)))
            build_script(ep.title, lines, cast, silent, ans, ep.format, set(chars))   # validate the plan first
            plan, how = ans, "AI writer"
        except (ProviderError, ProviderNotConfigured, ScriptError, ValueError, TypeError, KeyError) as e:
            ctx.log(f"The writer's scenes could not be used ({str(e)[:300]}); using the simple split")
            db.add(Event(episode_id=ep.id, kind="script", message=f"Writer not used ({str(e)[:200]}): simple split instead"))
    words, views = [], []
    allowed = scene_sets.episode_sets(db, ep)
    vsets = scene_sets.view_sets(db, allowed)
    from .reference_plan import effective_beats
    acts = beat_actions(effective_beats(tr), tr.get("person_map") or {}, set(chars))
    script = build_script(ep.title, lines, cast, silent, plan, ep.format, set(chars), notes, words,
                          view_split={"main side", "reverse side"} <= set(vsets), actions=acts, set_views=views)
    if plan is None and len(allowed) > 1:
        scene_sets.from_notes(db, script["scenes"], words, allowed)   # the notes' setting changes, matched to the episode's sets
    scene_sets.from_views(script["scenes"], views, vsets, ep.set_id)   # shot / reverse shot: each side its own set
    for note in scene_sets.continuity(script["scenes"], allowed):
        ctx.log(note)
        db.add(Event(episode_id=ep.id, kind="script", message=f"Scene set: {note}"))
    if notes:
        how += " with video notes as suggestions"
    sv = save_script(db, ep, script, "audio-scenes" if plan else "audio-simple-split", how)
    set_stage(ep, "script_review")
    db.add(Event(episode_id=ep.id, kind="script", message=f"Script v{sv.version}: {len(script['scenes'])} scenes around "
                                                           f"{len(lines)} recorded lines ({how})"))
    db.commit()
    return {"script_version": sv.version, "scenes": len(script["scenes"]), "how": how}
