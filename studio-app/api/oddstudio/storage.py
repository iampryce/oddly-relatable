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
    kind = "s3"

    def __init__(self):
        import boto3  # imported lazily: only needed when S3 is configured
        s = get_settings()
        self.bucket, self.prefix = s.s3_bucket, s.s3_prefix
        self.client = boto3.client("s3", region_name=s.s3_region or None)

    def _k(self, key: str) -> str:
        return self.prefix + check_key(key)

    def put_file(self, key: str, src: Path, content_type: str | None = None) -> None:
        ct = content_type or mimetypes.guess_type(str(src))[0] or "application/octet-stream"
        self.client.upload_file(str(src), self.bucket, self._k(key), ExtraArgs={"ContentType": ct, "ServerSideEncryption": "AES256"})

    def get_to_file(self, key: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, self._k(key), str(dst))
        return dst

    def local_path(self, key: str) -> Path | None:
        return None

    def url(self, key: str, seconds: int | None = None) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": self._k(key)},
                                                  ExpiresIn=seconds or get_settings().presign_seconds)


_storage = None


def storage():
    global _storage
    if _storage is None:
        _storage = S3Storage() if get_settings().storage_backend == "s3" else LocalStorage()
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
