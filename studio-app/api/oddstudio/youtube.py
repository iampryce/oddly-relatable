"""YouTube Data API v3 upload (resumable), used only by the publish job, which runs only after the owner's explicit
publication approval for the exact video revision.

Credentials (server environment only): YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN for the
channel, with scope https://www.googleapis.com/auth/youtube.upload (README: "YouTube setup"). Uploads cost API quota,
not money. Videos default to "private" so the owner can still check them on YouTube before making them public.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx

from .config import get_settings
from .secrets_store import secret
from .providers import ProviderNotConfigured

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}"


def configured() -> bool:
    s = get_settings()
    return bool(secret("youtube_client_id") and secret("youtube_client_secret") and secret("youtube_refresh_token"))


def access_token() -> str:
    s = get_settings()
    if not configured():
        raise ProviderNotConfigured("YouTube is not connected: set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN on the server")
    r = httpx.post(TOKEN_URL, timeout=30, data={"client_id": secret("youtube_client_id"), "client_secret": secret("youtube_client_secret"),
                                                "refresh_token": secret("youtube_refresh_token"), "grant_type": "refresh_token"})
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube sign-in failed: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


def upload_video(path: Path, *, title: str, description: str, tags: list[str], category_id: str, privacy: str,
                 made_for_kids: bool, thumbnail: Path | None, log: Callable[[str], None],
                 synthetic: bool = False) -> str:
    if not title.strip():
        raise ValueError("a YouTube title is required")
    token = access_token()
    meta = {"snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30], "categoryId": category_id},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids}}
    if synthetic:   # cinematic episodes: realistic AI-generated people ("altered or synthetic content")
        meta["status"]["containsSyntheticMedia"] = True
    size = path.stat().st_size
    with httpx.Client(timeout=600) as c:
        init = c.post(UPLOAD_URL, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                                           "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      content=json.dumps(meta))
        if init.status_code >= 400:
            raise RuntimeError(f"YouTube upload could not start: HTTP {init.status_code}: {init.text[:300]}")
        session = init.headers["Location"]
        log(f"Uploading {size} bytes to YouTube")
        with open(path, "rb") as f:
            up = c.put(session, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}, content=f.read())
        if up.status_code >= 400:
            raise RuntimeError(f"YouTube upload failed: HTTP {up.status_code}: {up.text[:300]}")
        vid = up.json()["id"]
        log(f"Uploaded: video id {vid}")
        if thumbnail:
            t = c.post(THUMB_URL.format(vid=vid), headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
                       content=thumbnail.read_bytes())
            log("Thumbnail set" if t.status_code < 400 else f"Thumbnail not set: HTTP {t.status_code}: {t.text[:200]}")
    return vid
