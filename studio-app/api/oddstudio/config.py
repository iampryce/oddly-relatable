"""Runtime configuration, read once from environment variables.

Secrets (API keys, OAuth tokens, the session secret, the owner's password hash) come ONLY from the environment and are
never returned by any API route: routes report whether each one is configured, never its value. Non-secret choices
that the owner edits in the dashboard (provider names, models, voices, production options) live in the database
(see settings_store.py) and override the defaults here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(os.environ.get("ODD_REPO_ROOT", Path(__file__).resolve().parents[3]))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("ODD_ENV", "development"))          # development | production | test
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./studio-dev.db"))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", ""))              # empty: no queue (jobs stay "queued")
    session_secret: str = field(default_factory=lambda: _env("SESSION_SECRET"))
    owner_email: str = field(default_factory=lambda: _env("OWNER_EMAIL").lower())
    owner_password_hash: str = field(default_factory=lambda: _env("OWNER_PASSWORD_HASH"))
    session_hours: int = field(default_factory=lambda: int(_env("SESSION_HOURS", "12")))
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "true").lower() != "false")
    # Where the worker keeps working files (engine projects, renders, generated art) before upload to storage.
    work_dir: Path = field(default_factory=lambda: Path(_env("ODD_WORK_DIR", str(REPO_ROOT / "studio-work" / "studio-app"))))
    # Storage: "local" (files under work_dir/storage, served through HMAC-signed URLs) or "s3" (presigned URLs).
    storage_backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET"))
    s3_region: str = field(default_factory=lambda: _env("AWS_REGION", _env("AWS_DEFAULT_REGION")))
    s3_prefix: str = field(default_factory=lambda: _env("S3_PREFIX", "oddly-relatable/"))
    presign_seconds: int = field(default_factory=lambda: int(_env("PRESIGN_SECONDS", "3600")))
    # Production engine (the existing Node toolkit in production/).
    node_bin: str = field(default_factory=lambda: _env("NODE_BIN", "node"))
    ffmpeg: str = field(default_factory=lambda: _env("FFMPEG"))
    ffprobe: str = field(default_factory=lambda: _env("FFPROBE"))
    # Provider credentials (secrets): presence is reported, values never are.
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    codex_bin: str = field(default_factory=lambda: _env("CODEX_BIN", "codex"))
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    piper_bin: str = field(default_factory=lambda: _env("PIPER_BIN", "piper"))
    youtube_client_id: str = field(default_factory=lambda: _env("YOUTUBE_CLIENT_ID"))
    youtube_client_secret: str = field(default_factory=lambda: _env("YOUTUBE_CLIENT_SECRET"))
    youtube_refresh_token: str = field(default_factory=lambda: _env("YOUTUBE_REFRESH_TOKEN"))
    job_timeout_seconds: int = field(default_factory=lambda: int(_env("JOB_TIMEOUT_SECONDS", "1800")))
    max_job_attempts: int = field(default_factory=lambda: int(_env("MAX_JOB_ATTEMPTS", "3")))

    def check(self) -> list[str]:
        """Configuration problems that must stop the API from serving (production only)."""
        problems = []
        if len(self.session_secret) < 32:
            problems.append("SESSION_SECRET must be set (at least 32 characters)")
        if not self.owner_email or not self.owner_password_hash:
            problems.append("OWNER_EMAIL and OWNER_PASSWORD_HASH must be set (see README: make a hash with `python -m oddstudio.auth hash`)")
        if self.storage_backend == "s3" and not self.s3_bucket:
            problems.append("STORAGE_BACKEND=s3 needs S3_BUCKET")
        return problems


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Tests change environment variables and call this to re-read them."""
    global _settings
    _settings = None
