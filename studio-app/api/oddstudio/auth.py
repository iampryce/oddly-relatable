"""Owner authentication: one owner account from the environment, a signed httpOnly session cookie.

- The password is stored only as a PBKDF2-SHA256 hash (OWNER_PASSWORD_HASH). Make one with:
      python -m oddstudio.auth hash
- The session token is "<email>|<expiry>|<HMAC>", signed with SESSION_SECRET, sent as an httpOnly, SameSite=Strict
  cookie (Secure unless COOKIE_SECURE=false for a plain-HTTP SSH tunnel). It never reaches JavaScript.
- Failed logins are rate-limited per client address.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import sys
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from .config import get_settings

COOKIE = "odd_session"
ITERATIONS = 310_000


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(base64.b64encode(dk).decode(), digest)
    except (ValueError, TypeError):
        return False


def _secret() -> bytes:
    s = get_settings()
    if s.session_secret:
        return s.session_secret.encode()
    if s.env == "production":
        raise HTTPException(500, "SESSION_SECRET is not configured")
    return b"dev-only-secret-not-for-production"


def make_token(email: str) -> str:
    exp = int(time.time()) + get_settings().session_hours * 3600
    body = f"{email}|{exp}"
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def read_token(token: str | None) -> str | None:
    if not token or token.count("|") != 2:
        return None
    email, exp, sig = token.split("|")
    good = hmac.new(_secret(), f"{email}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig) or not exp.isdigit() or int(exp) < time.time():
        return None
    return email


_failures: dict[str, deque] = defaultdict(deque)
_all_failures: deque = deque()
PER_CLIENT, GLOBAL, WINDOW = 8, 30, 900


def _trim(q: deque, t: float) -> None:
    while q and q[0] < t - WINDOW:
        q.popleft()


def check_rate(client: str) -> None:
    """Per-client limit, plus a global cap: the client address comes from X-Forwarded-For behind the dashboard proxy,
    which a caller can influence, so the global cap bounds password guessing however addresses are presented."""
    t = time.time()
    q = _failures[client]
    _trim(q, t)
    _trim(_all_failures, t)
    if len(q) >= PER_CLIENT or len(_all_failures) >= GLOBAL:
        raise HTTPException(429, "Too many failed sign-in attempts. Wait 15 minutes.")


def record_failure(client: str) -> None:
    t = time.time()
    _failures[client].append(t)
    _all_failures.append(t)
    if len(_failures) > 10_000:      # bound memory under address spoofing
        _failures.clear()


def current_user(request: Request) -> str:
    s = get_settings()
    if s.auth_disabled:   # owner-chosen open mode: every visitor acts as the owner (see config.auth_disabled)
        return s.owner_email or "owner"
    email = read_token(request.cookies.get(COOKIE))
    if not email or email != get_settings().owner_email:
        raise HTTPException(401, "Sign in required")
    return email


User = Depends(current_user)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "hash":
    pw = getpass.getpass("Owner password: ")
    if len(pw) < 12:
        sys.exit("Use at least 12 characters.")
    if pw != getpass.getpass("Again: "):
        sys.exit("Passwords differ.")
    print(hash_password(pw))
