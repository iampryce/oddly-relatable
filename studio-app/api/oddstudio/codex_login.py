"""Codex sign-in from Settings: the owner signs the server's Codex CLI in to their ChatGPT plan without a terminal.

Flow (OpenAI device code login, `codex login --device-auth`):
  1. start()  runs the CLI in the background on the API container and returns the link and one-time code it prints;
  2. the owner opens the link, signs in to ChatGPT and enters the code;
  3. the CLI saves its login in CODEX_HOME (/data/codex on the data volume shared with the worker) and exits;
  4. status() then reports "chatgpt". logout() runs `codex logout`.

Security: the login file (CODEX_HOME/auth.json) is never read, returned or logged here; only the CLI touches it. The
one-time code is useless without the owner's ChatGPT sign-in and expires after 15 minutes. One sign-in at a time.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .config import get_settings
from .providers import ProviderNotConfigured, _login_cache, codex_env, codex_login_state

CODE_TTL = 15 * 60
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_URL = re.compile(r"https://auth\.openai\.com/\S+")
_CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,6}\b")
_lock = threading.Lock()
_proc: subprocess.Popen | None = None


def _files() -> tuple[Path, Path]:
    d = get_settings().work_dir / "codex-login"
    d.mkdir(parents=True, exist_ok=True)
    return d / "login.log", d / "state.json"


def _read_state() -> dict:
    _, st = _files()
    try:
        return json.loads(st.read_text())
    except (OSError, ValueError):
        return {}


def _write_state(v: dict) -> None:
    _, st = _files()
    st.write_text(json.dumps(v))


def _log_text() -> str:
    log, _ = _files()
    try:
        return _ANSI.sub("", log.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def _pending() -> bool:
    return _proc is not None and _proc.poll() is None


def _waiter(p: subprocess.Popen) -> None:
    """Reap the CLI when it exits and record how it ended (it exits after a sign-in, a refusal or the code expiring)."""
    try:
        rc = p.wait(timeout=CODE_TTL + 60)
    except subprocess.TimeoutExpired:
        p.kill()
        rc = p.wait()
    text = _log_text()
    st = _read_state()
    if st.get("finished") and not st.get("code"):
        _login_cache.clear()
        return
    st.update({"finished": time.time(), "exit": rc,
               "result": "signed in" if rc == 0 and "success" in text.lower() else "not signed in"})
    st.pop("code", None)            # the one-time code is no longer useful: not kept
    _write_state(st)
    _login_cache.clear()


def start() -> dict:
    """Begin a device-code sign-in (or return the one already waiting). Returns {url, code, expires_at}."""
    global _proc
    exe = shutil.which(get_settings().codex_bin)
    if not exe:
        raise ProviderNotConfigured("the `codex` command is not installed on the server")
    with _lock:
        st = _read_state()
        if _pending() and st.get("code"):
            return {"url": st["url"], "code": st["code"], "expires_at": st["expires_at"]}
        log, _ = _files()
        fh = open(log, "w", encoding="utf-8")
        os.chmod(log, 0o600)
        # argument list, no shell; API keys removed so the CLI can only sign in to ChatGPT
        _proc = subprocess.Popen([exe, "login", "--device-auth"], stdout=fh, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, env=codex_env(), start_new_session=True)
        fh.close()
        deadline = time.time() + 30
        url = code = None
        while time.time() < deadline and (url is None or code is None):
            text = _log_text()
            m_url, m_code = _URL.search(text), _CODE.search(text)
            url = m_url.group(0) if m_url else None
            code = m_code.group(0) if m_code else None
            if _proc.poll() is not None:
                break
            time.sleep(0.3)
        if not (url and code):
            if _proc.poll() is None:
                _proc.kill()
            _proc.wait()
            tail = _log_text().strip()[-300:]
            if "device" in tail.lower() and "enable" in tail.lower():
                raise RuntimeError("Codex could not start a device-code sign-in. Turn on device code login in ChatGPT > "
                                   "Settings > Security, then try again.")
            raise RuntimeError(f"Codex did not show a sign-in code: {tail or 'no output'}")
        st = {"started": time.time(), "expires_at": time.time() + CODE_TTL, "url": url, "code": code}
        _write_state(st)
        threading.Thread(target=_waiter, args=(_proc,), daemon=True).start()
        return {"url": url, "code": code, "expires_at": st["expires_at"]}


def cancel() -> None:
    with _lock:
        if _pending():
            _proc.kill()


def _record_if_finished() -> None:
    """The sign-in CLI has exited but its waiter thread has not written the result yet: write it now (same result), so
    a status read right after the sign-in never shows neither pending nor finished."""
    st = _read_state()
    if _proc is not None and _proc.poll() is not None and st.get("code") and not st.get("finished"):
        text = _log_text()
        st.update({"finished": time.time(), "exit": _proc.returncode,
                   "result": "signed in" if _proc.returncode == 0 and "success" in text.lower() else "not signed in"})
        st.pop("code", None)
        _write_state(st)


def status() -> dict:
    with _lock:
        _record_if_finished()
    _login_cache.clear()
    state = codex_login_state()
    st = _read_state()
    out = {"installed": state != "missing", "login": state, "pending": None, "last": None}
    if _pending() and st.get("code") and st.get("expires_at", 0) > time.time():
        out["pending"] = {"url": st["url"], "code": st["code"], "expires_at": st["expires_at"]}
    elif st.get("finished"):
        out["last"] = {"result": st.get("result"), "at": st["finished"]}
    return out


def logout() -> dict:
    exe = shutil.which(get_settings().codex_bin)
    if not exe:
        raise ProviderNotConfigured("the `codex` command is not installed on the server")
    cancel()
    subprocess.run([exe, "logout"], capture_output=True, text=True, timeout=30, env=codex_env())
    return status()
