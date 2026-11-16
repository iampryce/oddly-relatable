"""Episode workflow: stages, the actions allowed in each, and the approval gates.

Every route that changes an episode calls `require(episode, action)` first, so a gate cannot be skipped by calling the
API directly: the dashboard only hides buttons, the server is what refuses. Stages:

  script_pending -> script_generating -> script_review --approve--> script_approved
  script_approved -> storyboard_generating -> storyboard_review --approve--> storyboard_approved
  storyboard_approved -> producing -> video_review          (or production_failed: retry failed jobs only)
  video_review --request revision--> script_review | storyboard_review | producing (targeted scenes)
  video_review --approve--> final_approved -> (publish details approved by the owner) -> publishing -> published
"""
from __future__ import annotations

from dataclasses import dataclass

STAGES = [
    "script_pending", "script_generating", "script_review", "script_approved",
    "storyboard_generating", "storyboard_review", "storyboard_approved",
    "producing", "production_failed", "video_review",
    "final_approved", "publishing", "published", "publish_failed",
]

# Which stages each action may start from. Anything else is refused with 409.
ALLOWED: dict[str, set[str]] = {
    "generate_script": {"script_pending", "script_review"},
    "edit_script": {"script_pending", "script_review"},
    "regenerate_section": {"script_review"},
    "approve_script": {"script_review"},
    "reject_script": {"script_review"},
    "generate_storyboard": {"script_approved", "storyboard_review"},
    "edit_scene": {"storyboard_review"},
    "regenerate_scene": {"storyboard_review"},
    "scene_reference": {"storyboard_review", "storyboard_approved", "video_review"},
    "approve_storyboard": {"storyboard_review"},
    "reject_storyboard": {"storyboard_review"},
    "start_production": {"storyboard_approved"},
    "retry_job": {"producing", "production_failed"},
    "rerun_scene": {"production_failed", "video_review"},
    "request_revision": {"video_review"},
    "approve_video": {"video_review"},
    "edit_publish": {"final_approved", "publish_failed"},
    "approve_publish": {"final_approved", "publish_failed"},
    "publish": {"final_approved", "publish_failed"},
}

# Stage label for the dashboard and the "what can I do next" hint.
NEXT_STEP = {
    "script_pending": "Generate or write the script",
    "script_generating": "Script is being generated",
    "script_review": "Review, edit and approve the script",
    "script_approved": "Generate the storyboard",
    "storyboard_generating": "Storyboard is being generated",
    "storyboard_review": "Review scenes and approve the storyboard",
    "storyboard_approved": "Start production",
    "producing": "Production is running",
    "production_failed": "Fix the failed jobs and retry them",
    "video_review": "Review the video: approve it or request a revision",
    "final_approved": "Prepare publishing details and approve publication",
    "publishing": "Uploading to YouTube",
    "published": "Published",
    "publish_failed": "Publishing failed: check the error and retry",
}


@dataclass
class GateError(Exception):
    action: str
    stage: str
    detail: str = ""

    def __str__(self) -> str:
        base = f'"{self.action}" is not allowed while the episode is in stage "{self.stage}"'
        return f"{base}: {self.detail}" if self.detail else f"{base} ({NEXT_STEP.get(self.stage, '')})"


def require(episode, action: str) -> None:
    if action not in ALLOWED:
        raise ValueError(f"unknown workflow action {action}")
    if episode.stage not in ALLOWED[action]:
        raise GateError(action, episode.stage)


def allowed_actions(episode) -> list[str]:
    return sorted(a for a, stages in ALLOWED.items() if episode.stage in stages)


def set_stage(episode, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage}")
    episode.stage = stage


REVISION_TARGETS = {"script", "storyboard", "scenes"}
