"""JSON shapes returned by the API. Media is always referenced by a short-lived signed URL, never by a path."""
from __future__ import annotations

from .models import Asset, Character, CharacterAsset, Episode, Idea, Job, PublishRecord, Review, StoryboardScene
from .storage import storage
from .workflow import NEXT_STEP, allowed_actions


def ts(d):
    return d.isoformat() if d else None


def asset(a: Asset | None) -> dict | None:
    if a is None:
        return None
    return {"id": a.id, "kind": a.kind, "label": a.label, "revision": a.revision, "content_type": a.content_type, "size": a.size,
            "sha256": a.sha256, "scene_id": a.scene_id, "job_id": a.job_id, "created_at": ts(a.created_at), "url": storage().url(a.storage_key)}


def idea(i: Idea) -> dict:
    return {"id": i.id, "title": i.title, "premise": i.premise, "notes": i.notes, "characters": i.characters,
            "target_seconds": i.target_seconds, "interactive": i.interactive, "status": i.status, "episode_id": i.episode_id,
            "format": i.format, "continues_episode_id": i.continues_episode_id,
            "created_at": ts(i.created_at), "updated_at": ts(i.updated_at)}


def episode_summary(e: Episode) -> dict:
    return {"id": e.id, "title": e.title, "stage": e.stage, "next_step": NEXT_STEP.get(e.stage, ""), "revision": e.revision,
            "format": e.format, "continues_episode_id": e.continues_episode_id, "outline_version": e.outline_version,
            "approved_outline_version": e.approved_outline_version, "source": e.source or "script",
            "dialogue_display": e.dialogue_display or "bubbles", "set_id": e.set_id, "scene_set_ids": e.scene_set_ids or [],
            "audio_rights_confirmed": bool(e.audio_rights_confirmed), "audio_rights_source": e.audio_rights_source or "",
            "idea_id": e.idea_id, "script_version": e.script_version, "approved_script_version": e.approved_script_version,
            "storyboard_version": e.storyboard_version, "approved_storyboard_version": e.approved_storyboard_version,
            "video_asset_id": e.video_asset_id, "created_at": ts(e.created_at), "updated_at": ts(e.updated_at),
            "allowed_actions": allowed_actions(e)}


def scene(s: StoryboardScene, ref: Asset | None) -> dict:
    return {"id": s.id, "position": s.position, "scene_key": s.scene_key, "heading": s.heading, "location": s.location,
            "description": s.description, "action": s.action, "camera": s.camera, "characters": s.characters, "lines": s.lines,
            "set_id": s.set_id, "staging": s.staging,
            "status": s.status, "production_status": s.production_status, "revision_note": s.revision_note,
            "reference": asset(ref), "updated_at": ts(s.updated_at)}


def job(j: Job, with_log: bool = False) -> dict:
    d = {"id": j.id, "kind": j.kind, "episode_id": j.episode_id, "scene_id": j.scene_id, "character_id": j.character_id,
         "revision": j.revision, "status": j.status, "attempts": j.attempts, "payload": j.payload, "result": j.result,
         "progress": j.progress, "error": j.error, "created_at": ts(j.created_at), "started_at": ts(j.started_at),
         "finished_at": ts(j.finished_at)}
    if with_log:
        d["log"] = j.log
    return d


def review(r: Review) -> dict:
    return {"id": r.id, "gate": r.gate, "decision": r.decision, "revision": r.revision, "target": r.target, "comment": r.comment,
            "actor": r.actor, "created_at": ts(r.created_at)}


def character(c: Character, assets: list[CharacterAsset], rig_checks: dict | None = None) -> dict:
    return {"id": c.id, "key": c.key, "name": c.name, "description": c.description, "visual_description": c.visual_description,
            "bubble_style": c.bubble_style, "scope": c.scope, "episode_id": c.episode_id, "engine_character": c.engine_character,
            "expressions": c.expressions, "default_expression": c.default_expression, "locked": c.locked, "art_status": c.art_status,
            "voice": c.voice, "voice_style": c.voice_style, "voice_speed": c.voice_speed, "skin_tone": c.skin_tone or "",
            "assets": [{"id": a.id, "kind": a.kind, "expression": a.expression, "status": a.status, "width": a.width, "height": a.height,
                        "style_version": a.style_version or "v1",
                        "rig_check": (rig_checks or {}).get(str(a.id)) if a.kind == "pose" and a.status == "approved" else None,
                        "url": storage().url(a.storage_key), "created_at": ts(a.created_at)} for a in assets]}


def publish(p: PublishRecord | None) -> dict | None:
    if p is None:
        return None
    return {"title": p.title, "description": p.description, "tags": p.tags, "category_id": p.category_id, "privacy": p.privacy,
            "made_for_kids": p.made_for_kids, "thumbnail_asset_id": p.thumbnail_asset_id, "status": p.status,
            "approved_by": p.approved_by, "approved_at": ts(p.approved_at), "approved_revision": p.approved_revision,
            "approved_video_asset_id": p.approved_video_asset_id, "youtube_video_id": p.youtube_video_id,
            "youtube_url": p.youtube_url, "error": p.error}
