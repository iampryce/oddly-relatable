"""The episode workspace (feat/episode-workspace, owner request 2026-11-22): everything about an episode on one page,
in collapsible sections, each with a status badge, its own jobs (queued / running / failed with the message) and a note
in words; and a banner that says what is blocking the episode and where.

`facts(db, ep)` gathers plain data; `sections(f)` is a pure function of it (tested directly). Statuses:

    done        finished; the section starts collapsed
    action      needs the owner now: blocks the next step (expanded and flagged)
    failed      its last job failed (expanded and flagged; the message is shown)
    running     a job is queued or running
    todo        needed later, not blocking yet (expanded, not flagged)
    waiting     an earlier step comes first (collapsed)
    not_needed  nothing to do for this episode (collapsed)

Nothing here changes the episode: it only reads.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Character, Episode, Job
from .workflow import STAGES

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

# the page's order (owner's list), then review, publishing and history
ORDER = ("set", "people", "plan", "lines", "notes", "cast", "script", "storyboard", "production", "review", "publishing")
TITLES = {"set": "Set", "people": "People / who is who", "plan": "Reference plan", "lines": "Lines and speakers",
          "notes": "Video notes", "cast": "Cast and poses", "script": "Script", "storyboard": "Storyboard",
          "production": "Production", "review": "Review", "publishing": "Publishing"}
# the order the episode moves through (what blocks first)
FLOW = ("lines", "notes", "people", "plan", "cast", "script", "storyboard", "set", "production", "review", "publishing")
SECTION_JOBS = {
    "lines": ("audio_media_prepare", "audio_transcribe"),
    "notes": ("audio_video_notes",),
    "cast": ("audio_cast_suggest", "audio_voice_traits", "character_sheet", "character_pose"),
    "script": ("audio_scenes", "generate_script", "generate_act", "regenerate_section", "generate_outline"),
    "storyboard": ("generate_storyboard", "regenerate_scene", "scene_reference"),
    "production": ("scene_prepare", "scene_voice", "audio_slice", "render_episode", "plan_segments", "render_segment",
                   "join_segments"),
    "publishing": ("publish_youtube",),
    "set": ("set_candidate", "set_seat_suggest", "set_notes_read_video", "set_proposal"),
}
FLAGGED = ("action", "failed")
OPEN = ("action", "failed", "todo", "running")


def idx(stage: str) -> int:
    return STAGES.index(stage) if stage in STAGES else -1


def at_least(stage: str, other: str) -> bool:
    return idx(stage) >= idx(other)


# ------------------------------------------------------------------ jobs
def latest_jobs(jobs: list[dict]) -> list[dict]:
    """The jobs worth showing: every queued or running one, and the latest of each kind (per scene, per set) when it
    failed (a later success of the same kind clears it). `jobs` newest first."""
    seen, out = set(), []
    for j in jobs:
        key = (j["kind"], j.get("scene_id"), j.get("set_id"), j.get("character_id"))
        first = key not in seen
        seen.add(key)
        if j["status"] in ("queued", "running") or (first and j["status"] == "failed"):
            out.append(j)
    return out[:8]


# ------------------------------------------------------------------ the pure part
def _s(status: str, note: str, label: str | None = None) -> dict:
    return {"status": status, "note": note, "label": label or status.replace("_", " ")}


def section_lines(f: dict) -> dict:
    if not f["audio"]:
        return _s("not_needed", "A script-first episode has no recording.")
    st = f["stage"]
    if st == "audio_upload":
        return _s("action", "Choose the Short's window: it is transcribed after that." if f["needs_trim"]
                  else "Upload the recording (audio, or a video whose sound is used).", "upload")
    if st in ("audio_preparing", "audio_transcribing"):
        return _s("running", "Extracting the audio and transcribing the lines…", "working")
    if st == "audio_labelling":
        if not f["lines"]:
            return _s("action", "Transcribe the audio.", "transcribe")
        if f["unlabelled"]:
            return _s("action", f"{f['unlabelled']} line(s) have no speaker yet.", "speakers")
    return _s("done", f"{f['lines']} line(s), every line has a speaker.")


def section_notes(f: dict) -> dict:
    if not f["audio"]:
        return _s("not_needed", "Video notes come with an audio episode's video upload.")
    if f["notes_ranges"]:
        return _s("done", f"{f['notes_ranges']} range(s) from {f['notes_frames']} frame(s), words only (frames deleted).")
    if f["notes_requested"]:
        return _s("running", "The video notes are being made…", "working")
    return _s("not_needed", "No video notes (optional: upload a video with notes ticked).", "none")


def section_people(f: dict) -> dict:
    if not f["audio"] or not f["people_found"]:
        return _s("not_needed", "No people tracked in the video notes.", "none")
    if not f["person_map"]:
        return _s("todo", f"{f['people_found']} people found: confirm who is who so their seats and movements follow "
                          "the video (until then, the plan maps people by order and no movement is acted).", "confirm")
    off = f["people_found"] - f["confirmed"]
    return _s("done", f"{f['confirmed']} confirmed" + (f", {off} not on screen (their seats and beats are left out)" if off else "") + ".")


def section_plan(f: dict) -> dict:
    if not f["audio"] or not f["notes_ranges"]:
        return _s("not_needed", "No video notes, so no Reference plan.", "none")
    if f["plan_waiting"]:
        early = f["stage"] in ("audio_labelling", "script_review")
        return _s("action" if early else "todo", "Accept the Reference plan: nothing is built from the video notes until "
                                                 "you do." if early else "The notes changed: accept the plan again before "
                                                                         "rebuilding the scenes.", "accept")
    return _s("done", "Accepted.")


def section_cast(f: dict) -> dict:
    if f["audio"] and f["speakers_without_character"]:
        return _s("action", f"{len(f['speakers_without_character'])} speaker(s) are not a character yet: "
                            f"{', '.join(f['speakers_without_character'][:4])}.", "cast")
    if not f["cast_rows"]:
        return _s("waiting", "The cast comes from the speakers (audio) or the script.")
    missing = [r for r in f["cast_rows"] if r.get("missing") or (not r.get("locked") and (r.get("art_status") != "approved"
                                                                                          or r.get("missing_expressions")))]
    if missing:
        names = ", ".join(r.get("name") or r["key"] for r in missing[:4])
        waiting = sum(1 for r in missing if r.get("awaiting_review"))
        return _s("action" if f["script"] else "todo",
                  f"Poses still needed for {names}" + (f" ({waiting} with poses to review under Characters)" if waiting else "")
                  + ": production stays blocked until every character on screen has approved poses.", "poses")
    return _s("done", f"{len(f['cast_rows'])} character(s), all poses approved.")


def section_script(f: dict) -> dict:
    st = f["stage"]
    if st in ("script_generating", "outline_generating"):
        return _s("running", "The writer is working…", "writing")
    if st == "outline_review":
        return _s("action", "Review and approve the three-act outline.", "review")
    if st == "outline_approved":
        return _s("action", "Develop the scenes act by act.", "develop")
    if st == "script_pending":
        return _s("action", "Generate the script or write it yourself.", "write")
    if st == "script_review":
        return _s("action", "Review and approve the script (yours to approve).", "review")
    if f["audio"] and at_least("audio_labelling", st):
        if st == "audio_labelling" and f["lines"] and not f["unlabelled"] and not f["speakers_without_character"] \
                and not f["plan_waiting"]:
            return _s("action", "Build the scenes from the recorded lines.", "build")
        return _s("waiting", "Built from the recorded lines once the speakers, the cast and the Reference plan are ready.")
    if at_least(st, "script_approved"):
        return _s("done", f"Version {f['script']} approved." if f["script_approved"] else "Approved.")
    return _s("waiting", "Comes after the earlier steps.")


def section_storyboard(f: dict) -> dict:
    st = f["stage"]
    if not at_least(st, "script_approved") or st in ("audio_upload", "audio_preparing", "audio_transcribing", "audio_labelling"):
        return _s("waiting", "After the script is approved.")
    if st == "script_approved":
        return _s("action", "Build the storyboard from the approved script.", "build")
    if st == "storyboard_generating":
        return _s("running", "Building the storyboard and its stills…", "building")
    if st == "storyboard_review":
        return _s("action", "Review and approve the storyboard (yours to approve).", "review")
    return _s("done", f"{f['scenes']} scene(s), approved.")


def section_set(f: dict) -> dict:
    s = f["set"]
    if s["chosen"]:
        seats, people = s["seats"], s["people"]
        note = f"{s['label']}: {seats} seat(s) for {people} people." if people else f"{s['label']}: {seats} seat(s)."
        if people and seats < people:
            note += f" {people - seats} seated person(s) will stand: mark more seats on the picture, or keep it."
        return _s("done", note)
    waiting = s["candidates_waiting"]
    late = at_least(f["stage"], "storyboard_approved") and f["stage"] not in ("publishing", "published")
    note = ("Production cannot start until you choose an approved set (there is no default)." if late
            else "Choose or generate this episode's set before production.")
    if waiting:
        note += f" {waiting} candidate(s) wait for your decision below."
    return _s("action" if late else "todo", note, "choose")


def section_production(f: dict) -> dict:
    st = f["stage"]
    if st == "producing":
        return _s("running", "Rendering…", "rendering")
    if st == "production_failed":
        return _s("failed", "A production job failed: fix the cause (see its message), then retry only that job.")
    if at_least(st, "video_review") and st != "production_failed":
        return _s("done", "Rendered.")
    if st == "storyboard_approved":
        return _s("action" if f["set"]["chosen"] else "waiting",
                  "Start production." if f["set"]["chosen"] else "Choose the set first (Set section).", "start")
    return _s("waiting", "After the storyboard is approved.")


def section_review(f: dict) -> dict:
    st = f["stage"]
    if st == "video_review":
        return _s("action", "Watch the video and approve it or ask for a revision (yours to decide).", "review")
    if at_least(st, "final_approved"):
        return _s("done", "Final video approved.")
    return _s("waiting", "After production.")


def section_publishing(f: dict) -> dict:
    st = f["stage"]
    if st == "publishing":
        return _s("running", "Uploading…", "uploading")
    if st == "publish_failed":
        return _s("failed", "Publishing failed: see the message, fix and try again.")
    if st == "published":
        return _s("done", "Published.")
    if st == "final_approved":
        return _s("action", "Check the details and approve the publication (yours to approve).", "approve")
    return _s("waiting", "After the final video is approved.")


RULES = {"lines": section_lines, "notes": section_notes, "people": section_people, "plan": section_plan,
         "cast": section_cast, "script": section_script, "storyboard": section_storyboard, "set": section_set,
         "production": section_production, "review": section_review, "publishing": section_publishing}


def sections(f: dict) -> dict:
    """{sections: [...in page order], blocker: {...} | None, running: [...]} from the facts."""
    out = {}
    for key in ORDER:
        s = {"key": key, "title": TITLES[key], **RULES[key](f)}
        jobs = latest_jobs(f["jobs"].get(key, []))
        failed = [j for j in jobs if j["status"] == "failed"]
        active = [j for j in jobs if j["status"] in ("queued", "running")]
        base = s["status"]
        if failed and base != "done":
            s["status"], s["label"] = "failed", "failed"
            s["note"] = f"{failed[0]['kind'].replace('_', ' ')} failed: {(failed[0].get('error') or 'no message')[:300]}. " + s["note"]
        elif active and base not in FLAGGED:
            s["status"], s["label"] = "running", active[0]["status"]
        s["jobs"] = jobs
        # a failed job blocks only a step that is due (needs you now, or was in progress); an old failure in a step
        # that comes later (a set candidate long before production) shows red without blocking the episode
        s["blocking"] = base in FLAGGED or (bool(failed) and base == "running")
        s["open"] = s["status"] in OPEN
        out[key] = s
    blocker = next((out[k] for k in FLOW if out[k]["blocking"]), None)
    running = [out[k]["title"] for k in FLOW if out[k]["status"] == "running"]
    return {"sections": [out[k] for k in ORDER],
            "blocker": {"section": blocker["key"], "title": blocker["title"], "message": blocker["note"]} if blocker else None,
            "running": running}


# ------------------------------------------------------------------ the facts
def _job(j: Job) -> dict:
    from .serialize import ts
    p = j.payload or {}
    return {"id": j.id, "kind": j.kind, "status": j.status, "error": (j.error or "")[:500], "scene_id": j.scene_id,
            "character_id": j.character_id, "set_id": p.get("set_id"), "created_at": ts(j.created_at),
            "finished_at": ts(j.finished_at), "revision": j.revision}


def facts(db: Session, ep: Episode) -> dict:
    from . import sets
    from .casting import cast_status
    from .reference_plan import needs_acceptance
    from .set_proposals import cast_size, panel_jobs
    tr = ep.audio_transcript or {}
    audio = ep.source == "audio"
    lines = tr.get("lines", []) or []
    keys = {c.key for c in db.query(Character).all()}
    speakers = list(dict.fromkeys(ln.get("speaker") for ln in lines if ln.get("speaker")))
    vn = tr.get("video_notes") or {}
    frames = vn.get("people_frames") or []
    people = sorted({p["person"] for fr in frames for p in fr.get("people", []) if isinstance(p.get("person"), int)})
    pm = tr.get("person_map") or {}
    script = None
    if ep.script_version:
        from .models import ScriptVersion
        sv = db.query(ScriptVersion).filter_by(episode_id=ep.id, version=ep.script_version).one_or_none()
        script = sv.content if sv else None
    if script:
        rows = cast_status(db, script)
    elif audio and speakers:
        silent = [m.get("character_key") for m in tr.get("silent_cast", []) if m.get("character_key")]
        rows = cast_status(db, {"characters": [{"key": k} for k in dict.fromkeys(speakers + silent) if k in keys],
                                "scenes": []})
    else:
        rows = []
    recs = sets.records(db)
    chosen = recs.get(ep.set_id) if ep.set_id else None
    spec = sets.blocking_of(db, ep.set_id) if ep.set_id else None
    want = cast_size(ep) or 0
    # the jobs, newest first, by section
    own = db.query(Job).filter(Job.episode_id == ep.id).order_by(Job.id.desc()).limit(200).all()
    char_ids = [r["id"] for r in rows if r.get("id")]
    char_jobs = (db.query(Job).filter(Job.character_id.in_(char_ids), Job.kind.in_(SECTION_JOBS["cast"]))
                 .order_by(Job.id.desc()).limit(40).all()) if char_ids else []
    by = {k: [] for k in SECTION_JOBS}
    for j in sorted({j.id: j for j in own + char_jobs}.values(), key=lambda j: -j.id):
        if j.kind in SECTION_JOBS["production"] and j.revision != ep.revision:
            continue
        for sec, kinds in SECTION_JOBS.items():
            if j.kind in kinds and sec != "set":
                by[sec].append(_job(j))
    set_ids = {k for k, r in recs.items() if r.get("episode_id") == ep.id}
    by["set"] = [{**j, "scene_id": None, "character_id": None} for j in panel_jobs(db, ep, set_ids)]
    return {
        "audio": audio, "stage": ep.stage, "needs_trim": bool((tr.get("source_media") or {}).get("needs_trim")),
        "lines": len(lines), "unlabelled": sum(1 for ln in lines if not ln.get("speaker")),
        "speakers_without_character": [s for s in speakers if s not in keys] if audio else [],
        "notes_ranges": len(vn.get("ranges") or []), "notes_frames": vn.get("frames") or 0,
        "notes_requested": bool((tr.get("source_media") or {}).get("hints_requested")) and not vn,
        "people_found": len(people), "person_map": bool(pm),
        "confirmed": len({v for v in pm.values() if v not in (None, "")}),
        "plan_waiting": bool(audio and needs_acceptance(tr)),
        "cast_rows": rows, "script": ep.script_version, "script_approved": ep.approved_script_version == ep.script_version and ep.script_version,
        "scenes": len(ep.scenes),
        "set": {"chosen": bool(ep.set_id), "label": (chosen or {}).get("label") or ep.set_id or "",
                "seats": len(sets.seats_of(spec)) if spec else 0, "people": want,
                "candidates_waiting": sum(1 for r in recs.values() if r.get("episode_id") == ep.id and r.get("status") == "candidate")},
        "jobs": by,
    }


@router.get("/episodes/{eid}/workspace")
def workspace(eid: int, db: Session = Depends(get_db)):
    ep = db.get(Episode, eid)
    if ep is None:
        raise HTTPException(404, "episode not found")
    return {"episode_id": ep.id, "stage": ep.stage, **sections(facts(db, ep))}
