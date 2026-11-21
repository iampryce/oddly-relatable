"""Media storage behind one interface.

- S3Storage: objects in S3 under S3_PREFIX; the browser gets short-lived presigned GET URLs (credentials stay on the
  server: an IAM role or AWS_* environment variables read by boto3).
- LocalStorage: files under <work_dir>/storage; the browser gets an HMAC-signed, expiring URL served by the API.
Keys are always relative ("episodes/12/r1/video.mp4"); paths are never exposed.
"""
from __future__ import annotations

import hashlib
import hmac
import mimetypes
import shutil
import time
from pathlib import Path

from .config import get_settings

SAFE_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./")


def check_key(key: str) -> str:
    if not key or key.startswith("/") or ".." in key.split("/") or not set(key) <= SAFE_KEY_CHARS:
        raise ValueError(f"invalid storage key {key!r}")
    return key


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LocalStorage:
    kind = "local"

    def __init__(self):
        self.root = get_settings().work_dir / "storage"
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, key: str, src: Path, content_type: str | None = None) -> None:
        dst = self.root / check_key(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def get_to_file(self, key: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.root / check_key(key), dst)
        return dst

    def local_path(self, key: str) -> Path:
        return self.root / check_key(key)

    def delete(self, key: str) -> None:
        """Remove one stored file (only ever inside the storage folder)."""
        p = (self.root / check_key(key)).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise ValueError(f"refusing to delete outside storage: {key!r}")
        p.unlink(missing_ok=True)

    def url(self, key: str, seconds: int | None = None) -> str:
        s = get_settings()
        exp = int(time.time()) + (seconds or s.presign_seconds)
        sig = sign_local(key, exp)
        return f"/api/media/{check_key(key)}?exp={exp}&sig={sig}"


def sign_local(key: str, exp: int) -> str:
    secret = (get_settings().session_secret or "dev-only-secret").encode()
    return hmac.new(secret, f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()


def verify_local(key: str, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(sign_local(key, exp), sig)


class S3Storage:
    """New media goes to S3. Media saved on the server volume before the switch to S3 is still read and served from
    there (a key that exists locally wins), so switching backends never breaks existing episodes."""
    kind = "s3"

    def __init__(self, cfg: dict):
        import boto3  # imported lazily: only needed when S3 is configured
        from .secrets_store import secret
        self.bucket, self.prefix = cfg["bucket"], cfg["prefix"]
        kid, sec = secret("aws_access_key_id"), secret("aws_secret_access_key")
        creds = {"aws_access_key_id": kid, "aws_secret_access_key": sec} if kid and sec else {}  # else IAM role / env
        from botocore.config import Config
        self.client = boto3.client("s3", region_name=cfg["region"] or None,
                                   config=Config(retries={"max_attempts": 5, "mode": "standard"}, connect_timeout=10,
                                                 read_timeout=120), **creds)
        self.local = LocalStorage()

    def _k(self, key: str) -> str:
        return self.prefix + check_key(key)

    def put_file(self, key: str, src: Path, content_type: str | None = None) -> None:
        ct = content_type or mimetypes.guess_type(str(src))[0] or "application/octet-stream"
        self.client.upload_file(str(src), self.bucket, self._k(key), ExtraArgs={"ContentType": ct, "ServerSideEncryption": "AES256"})

    def get_to_file(self, key: str, dst: Path) -> Path:
        if self.local.local_path(key).exists():
            return self.local.get_to_file(key, dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, self._k(key), str(dst))
        return dst

    def local_path(self, key: str) -> Path | None:
        p = self.local.local_path(key)
        return p if p.exists() else None

    def delete(self, key: str) -> None:
        self.local.delete(key)
        self.client.delete_object(Bucket=self.bucket, Key=self._k(key))

    def url(self, key: str, seconds: int | None = None) -> str:
        if self.local.local_path(key).exists():
            return self.local.url(key, seconds)
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": self._k(key)},
                                                  ExpiresIn=seconds or get_settings().presign_seconds)

    def check(self) -> dict:
        """Real round trip: upload, read back and delete a small object."""
        import uuid
        k = self._k(f"_connection-test/{uuid.uuid4().hex}.txt")
        body = b"oddly relatable connection test"
        self.client.put_object(Bucket=self.bucket, Key=k, Body=body, ServerSideEncryption="AES256")
        got = self.client.get_object(Bucket=self.bucket, Key=k)["Body"].read()
        self.client.delete_object(Bucket=self.bucket, Key=k)
        if got != body:
            raise RuntimeError("S3 returned different bytes than were written")
        return {"bucket": self.bucket, "prefix": self.prefix, "round_trip_bytes": len(body)}


_storage = None
_storage_cfg: tuple | None = None
_cfg_cache: tuple[float, dict] | None = None


def storage_config() -> dict:
    """Storage settings: the Settings page's "storage" section when saved there, otherwise the environment."""
    global _cfg_cache
    if _cfg_cache and time.time() - _cfg_cache[0] < 5:
        return _cfg_cache[1]
    s = get_settings()
    cfg = {"backend": s.storage_backend, "bucket": s.s3_bucket, "region": s.s3_region, "prefix": s.s3_prefix}
    try:
        from .db import new_session
        from .models import Setting
        with new_session() as db:
            row = db.get(Setting, "storage")
            saved = dict(row.value) if row else {}
        cfg.update({k: v for k, v in saved.items() if v})
    except Exception:  # database not ready: environment only
        pass
    if cfg["prefix"] and not cfg["prefix"].endswith("/"):
        cfg["prefix"] += "/"
    _cfg_cache = (time.time(), cfg)
    return cfg


def storage():
    global _storage, _storage_cfg
    cfg = storage_config()
    key = tuple(sorted(cfg.items()))
    if _storage is None or key != _storage_cfg:
        _storage = S3Storage(cfg) if cfg["backend"] == "s3" else LocalStorage()
        _storage_cfg = key
    return _storage


def reset_storage() -> None:
    global _storage, _storage_cfg, _cfg_cache
    _storage = _storage_cfg = _cfg_cache = None
