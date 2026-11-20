"""Persistent workflow state. Everything the dashboard shows is read from these tables, so the owner can leave and come
back without losing progress. Approvals and revision requests are append-only (`reviews`), never overwritten."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Idea(Timestamps, Base):
    __tablename__ = "ideas"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    premise: Mapped[str] = mapped_column(Text)                       # the owner's idea, in their words
    notes: Mapped[str] = mapped_column(Text, default="")            # extra direction: twist, tone, references
    characters: Mapped[list] = mapped_column(JSON, default=list)    # character keys the owner wants in it (optional)
    target_seconds: Mapped[int] = mapped_column(Integer, default=45)
    interactive: Mapped[str] = mapped_column(String(40), default="none")  # none | viewer-choice | poll
    format: Mapped[str] = mapped_column(String(10), default="short")       # short | long (5–7 min, D-L3)
    continues_episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # D-L5: optional continuation of a Short
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft | submitted | in_production | archived
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)


class Episode(Timestamps, Base):
    __tablename__ = "episodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(40), default="script_pending")   # see workflow.STAGES
    revision: Mapped[int] = mapped_column(Integer, default=1)                    # bumps on each revision request
    script_version: Mapped[int | None] = mapped_column(Integer, nullable=True)   # current ScriptVersion.version
    approved_script_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storyboard_version: Mapped[int] = mapped_column(Integer, default=0)
    approved_storyboard_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(10), default="short")       # short | long
    continues_episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_outline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Audio-first episodes (audio_first.py): the owner's uploaded audio is the voice track. The rights confirmation is
    # required before any upload; the transcript holds the timed lines and their speakers.
    source: Mapped[str] = mapped_column(String(10), default="script")             # script | audio
    audio_rights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_rights_source: Mapped[str] = mapped_column(String(20), default="")     # own_recording | licensed | voice_actor | other
    audio_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_transcript: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    scenes: Mapped[list["StoryboardScene"]] = relationship(back_populates="episode", order_by="StoryboardScene.position", cascade="all, delete-orphan")


class ScriptVersion(Base):
    __tablename__ = "script_versions"
    __table_args__ = (UniqueConstraint("episode_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)                      # validated by script_schema.validate_script
    source: Mapped[str] = mapped_column(String(40))                  # generated | edited | section-regenerated
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutlineVersion(Base):
    """Long-form three-act outline (owner-approved before any scene is written)."""
    __tablename__ = "outline_versions"
    __table_args__ = (UniqueConstraint("episode_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Segment(Base):
    """A long-form render segment (at most 58 s): scene parts, its input fingerprint and its rendered video."""
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    parts: Mapped[list] = mapped_column(JSON)                         # [{"scene": scene_key, "lines": [a, b], "duration": s}]
    seconds: Mapped[float] = mapped_column(default=0.0)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | rendering | done | failed
    reused_from: Mapped[int | None] = mapped_column(Integer, nullable=True)   # segment id whose render is reused
    video_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_seconds: Mapped[float | None] = mapped_column(nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Character(Timestamps, Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)        # used in scripts ("speaker": key)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")       # who they are, personality, comic role
    visual_description: Mapped[str] = mapped_column(Text, default="")  # how they look (fed to image generation)
    bubble_style: Mapped[str] = mapped_column(String(20), default="neutral")  # him | her | neutral (engine styles)
    scope: Mapped[str] = mapped_column(String(20), default="recurring")       # recurring | episode
    episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # set when scope == episode
    # Link to the production engine: a pose registry (repo-relative for approved repo art, or absolute in the work dir
    # for generated art) and which pose to use for each expression a script may ask for.
    engine_character: Mapped[str | None] = mapped_column(String(80), nullable=True)
    registry_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expressions: Mapped[dict] = mapped_column(JSON, default=dict)    # {"neutral": "01", "shocked": "03", ...}
    default_expression: Mapped[str] = mapped_column(String(40), default="neutral")
    locked: Mapped[bool] = mapped_column(default=False)              # approved repo artwork: not editable here
    art_status: Mapped[str] = mapped_column(String(20), default="none")  # none | generating | review | approved
    # Voice: the voice id for the configured voice provider, and how this character speaks (fed to the voice model).
    voice: Mapped[str] = mapped_column(String(120), default="")
    voice_style: Mapped[str] = mapped_column(Text, default="")
    # Optional speaking speed (0.5-2.0; empty = the provider's normal speed). Used by Fish Audio (prosody.speed).
    voice_speed: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    # House style v2: heads are flat white unless the character has its own flat skin tone (e.g. "warm medium brown").
    skin_tone: Mapped[str] = mapped_column(String(40), default="")


class CharacterAsset(Base):
    __tablename__ = "character_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))                    # reference | pose | sheet | voice-sample
    expression: Mapped[str] = mapped_column(String(40), default="")
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    feet: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    figure_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="review")  # review | approved | rejected
    style_version: Mapped[str] = mapped_column(String(4), default="v1")   # house style the pose was drawn in (v1 | v2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StoryboardScene(Base):
    __tablename__ = "storyboard_scenes"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    scene_key: Mapped[str] = mapped_column(String(60))               # id of the script scene it came from
    heading: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(80), default="")    # engine environment id
    description: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text, default="")
    camera: Mapped[str] = mapped_column(Text, default="")
    characters: Mapped[list] = mapped_column(JSON, default=list)
    lines: Mapped[list] = mapped_column(JSON, default=list)          # [{speaker, text, expression, shot, duration}]
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft | needs_revision | ready
    production_status: Mapped[str] = mapped_column(String(30), default="pending")  # pending | running | done | failed
    reference_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    episode: Mapped[Episode] = relationship(back_populates="scenes")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))                    # see tasks.TASKS
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | succeeded | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)       # e.g. engine stages from production-run.json
    error: Mapped[str] = mapped_column(Text, default="")
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(40))                    # video | storyboard-sheet | scene-reference | audio | report | manifest | thumbnail
    label: Mapped[str] = mapped_column(String(200), default="")
    storage_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Review(Base):
    """Append-only audit of every human decision: approvals, rejections and revision requests."""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    gate: Mapped[str] = mapped_column(String(30))                    # script | storyboard | video | publish
    decision: Mapped[str] = mapped_column(String(30))                # approved | rejected | revision_requested
    revision: Mapped[int] = mapped_column(Integer)
    target: Mapped[dict] = mapped_column(JSON, default=dict)         # what a revision request covers
    comment: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PublishRecord(Timestamps, Base):
    __tablename__ = "publish_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    category_id: Mapped[str] = mapped_column(String(10), default="23")    # YouTube "Comedy"
    privacy: Mapped[str] = mapped_column(String(20), default="private")   # private | unlisted | public
    made_for_kids: Mapped[bool] = mapped_column(default=False)
    thumbnail_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")      # draft | approved | uploading | published | failed
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_video_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    youtube_video_id: Mapped[str] = mapped_column(String(40), default="")
    youtube_url: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    """Non-secret, owner-editable configuration (providers, models, voices, production options)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
