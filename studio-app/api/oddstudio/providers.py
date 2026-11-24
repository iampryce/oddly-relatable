"""AI providers: text (scripts), images (character poses, scene references) and voice.

Each provider either does the real call or raises ProviderNotConfigured with what is missing. Nothing here ever
returns placeholder content as if it had succeeded. The only stand-in, `FakeText`, exists for automated tests and is
refused unless ODD_ENV=test.

- codex-cli: the `codex` CLI on the owner's ChatGPT subscription (no API spending). The API image installs it; it works
  once signed in with ChatGPT (login kept in CODEX_HOME on the data volume). OpenAI API keys are removed from its
  environment, and a Codex failure never falls back to a paid provider.
- openai / anthropic: HTTPS APIs with keys from the environment (paid per use; see README for cost notes).
"""
from __future__ import annotations

import base64
import contextlib
import uuid
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from .config import get_settings
from .secrets_store import secret


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """transient=True: worth retrying automatically (rate limit, server error, timeout, network)."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def http_error(name: str, r) -> ProviderError:
    return ProviderError(f"{name}: HTTP {r.status_code}: {r.text[:500]}", transient=r.status_code == 429 or r.status_code >= 500)


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model answer (models sometimes wrap it in prose or code fences)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise ProviderError("the model answer contained no JSON object")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as e:
                    raise ProviderError(f"the model answer was not valid JSON: {e}") from e
    raise ProviderError("the model answer's JSON object was not closed")


@contextlib.contextmanager
def codex_workdir(kind: str):
    """A normally-permissioned working folder for one Codex call.

    Not tempfile: since Python 3.13, tempfile.mkdtemp gives new folders an owner-only access list on Windows, and
    Codex's Windows sandbox writes as a separate restricted identity. A file it creates inside such a folder (the
    generated image) is then unreadable to the worker. A plain folder under the work directory inherits normal
    permissions. Removed afterwards (best effort)."""
    d = get_settings().work_dir / "codex" / f"{kind}-{uuid.uuid4().hex[:12]}"
    d.mkdir(parents=True)
    try:
        yield str(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def codex_env() -> dict:
    """Environment for a Codex subprocess: everything except OpenAI API credentials, so Codex can only use the ChatGPT
    sign-in (plan allowance) and never silently bill the API account."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("OPENAI_")}


_login_cache: dict = {}


def codex_login_state() -> str:
    """'chatgpt' (signed in with a ChatGPT plan), 'api-key' (signed in with an API key: refused here, it would bill
    the API), 'none' (installed, not signed in) or 'missing' (not installed). Cached for 60 s: Settings asks often."""
    s = get_settings()
    hit = _login_cache.get(s.codex_bin)
    if hit and time.time() - hit[1] < 60:
        return hit[0]
    exe = shutil.which(s.codex_bin)
    state = "missing"
    if exe:
        try:
            r = subprocess.run([exe, "login", "status"], capture_output=True, text=True, encoding="utf-8",
                               timeout=20, env=codex_env())
            out = f"{r.stdout}\n{r.stderr}".lower()
            state = "chatgpt" if "chatgpt" in out and "not logged in" not in out else (
                "api-key" if "api key" in out and "not logged in" not in out else "none")
        except (subprocess.TimeoutExpired, OSError):
            state = "none"
    _login_cache[s.codex_bin] = (state, time.time())
    return state


def codex_images_dir() -> Path:
    """Where Codex's image tool keeps every image it makes (one sub-folder per session)."""
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "generated_images"


def _codex_pngs() -> set[Path]:
    d = codex_images_dir()
    return set(d.glob("*/*.png")) if d.is_dir() else set()


# ---------------------------------------------------------------- text
class TextProvider:
    name = "none"

    def complete_json(self, system: str, prompt: str) -> dict:
        raise ProviderNotConfigured("No text provider is configured. Choose one in Settings > AI providers.")


class CodexText(TextProvider):
    name = "codex-cli"

    def __init__(self, model: str = ""):
        self.model = model

    def complete_json(self, system: str, prompt: str) -> dict:
        s = get_settings()
        exe = shutil.which(s.codex_bin)
        if not exe:
            raise ProviderNotConfigured("codex-cli: the `codex` command is not installed or not on PATH on the worker machine")
        with codex_workdir("text") as tmp:
            out = Path(tmp) / "answer.md"
            cmd = [exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-C", tmp, "-o", str(out)]
            if self.model:
                cmd += ["-m", self.model]
            full = f"{system}\n\n{prompt}\n\nReturn ONLY the JSON object, with no commentary."
            try:
                r = subprocess.run(cmd + ["-"], input=full, capture_output=True, text=True, encoding="utf-8",
                                   timeout=s.job_timeout_seconds, env=codex_env())
            except subprocess.TimeoutExpired as e:
                raise ProviderError("codex-cli timed out", transient=True) from e
            if r.returncode != 0:
                raise ProviderError(f"codex-cli exited with {r.returncode}: {(r.stderr or r.stdout)[-800:]}")
            answer = out.read_text(encoding="utf-8") if out.exists() else r.stdout
            return extract_json(answer)


class OpenAIText(TextProvider):
    name = "openai"

    def __init__(self, model: str = "", temperature: float = 0.9):
        self.model = model or "gpt-4.1-mini"
        self.temperature = temperature

    def complete_json(self, system: str, prompt: str) -> dict:
        key = secret("openai_api_key")
        if not key:
            raise ProviderNotConfigured("openai: OPENAI_API_KEY is not set on the server")
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=180,
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": self.model, "temperature": self.temperature,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        if r.status_code >= 400:
            raise http_error("openai", r)
        return extract_json(r.json()["choices"][0]["message"]["content"])


class AnthropicText(TextProvider):
    name = "anthropic"

    def __init__(self, model: str = "", temperature: float = 0.9):
        self.model = model or "claude-sonnet-5-5"
        self.temperature = temperature

    # Models that still accept sampling parameters (temperature). Current models reject them with HTTP 400: Opus 5.5 / 5 /
    # 4.8 / 4.7, Sonnet 5, Fable and Mythos remove them; Sonnet 5.5 and Haiku 5.5 reject any non-default value. Anything
    # not listed here (including future models) is sent without temperature, so a new model id never breaks the writer.
    SAMPLING_MODELS = ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-5", "claude-sonnet-4-5",
                       "claude-opus-4-1", "claude-opus-4-0", "claude-sonnet-4-0", "claude-3")

    def payload(self, system: str, prompt: str) -> dict:
        body = {"model": self.model,
                # non-streaming request: ~16k leaves room for the script plus (adaptive) thinking, under HTTP timeouts
                "max_tokens": 16000, "system": system,
                "messages": [{"role": "user", "content": prompt + "\n\nReturn ONLY the JSON object."}]}
        if self.model.startswith(self.SAMPLING_MODELS):
            body["temperature"] = self.temperature
        return body

    def complete_json(self, system: str, prompt: str) -> dict:
        key = secret("anthropic_api_key")
        if not key:
            raise ProviderNotConfigured("anthropic: ANTHROPIC_API_KEY is not set on the server")
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=300,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, json=self.payload(system, prompt))
        if r.status_code >= 400:
            raise http_error("anthropic", r)
        data = r.json()
        if data.get("stop_reason") == "refusal":
            raise ProviderError(f"anthropic: the model declined this request ({(data.get('stop_details') or {}).get('category')})")
        if data.get("stop_reason") == "max_tokens":
            raise ProviderError("anthropic: the answer was cut off at max_tokens (shorten the request)")
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return extract_json(text)


class FakeText(TextProvider):
    """Deterministic stand-in for automated tests only."""
    name = "fake"

    def __init__(self, responder):
        if get_settings().env != "test":
            raise ProviderNotConfigured("the fake text provider exists only for automated tests")
        self.responder = responder

    def complete_json(self, system: str, prompt: str) -> dict:
        return self.responder(system, prompt)


_test_text_responder = None


def set_test_text_responder(fn) -> None:
    global _test_text_responder
    _test_text_responder = fn


class FallbackText(TextProvider):
    """Try the selected provider; on failure (or when it is not configured) use the fallback provider."""

    def __init__(self, primary: TextProvider, fallback: TextProvider):
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}>{fallback.name}"
        self.used = primary.name

    def complete_json(self, system: str, prompt: str) -> dict:
        try:
            out = self.primary.complete_json(system, prompt)
            self.used = self.primary.name
            return out
        except (ProviderError, ProviderNotConfigured) as e:
            fallback_log(f"text: {self.primary.name} failed ({str(e)[:200]}); using fallback {self.fallback.name}")
            out = self.fallback.complete_json(system, prompt)
            self.used = self.fallback.name
            return out


_fallback_logger = None


def set_fallback_logger(fn) -> None:
    """The worker routes fallback notices into the running job's log."""
    global _fallback_logger
    _fallback_logger = fn


def fallback_log(msg: str) -> None:
    if _fallback_logger:
        _fallback_logger(msg)


def text_provider(cfg: dict) -> TextProvider:
    fb = cfg.get("fallback", "none")
    primary = _one_text_provider(cfg)
    if fb and fb != "none" and fb != cfg.get("provider") and not isinstance(primary, FakeText):
        return FallbackText(primary, _one_text_provider({**cfg, "provider": fb, "model": cfg.get("fallback_model", "")}))
    return primary


def _one_text_provider(cfg: dict) -> TextProvider:
    p = cfg.get("provider", "none")
    if get_settings().env == "test" and _test_text_responder is not None:
        return FakeText(_test_text_responder)
    if p == "codex-cli":
        return CodexText(cfg.get("model", ""))
    if p == "openai":
        return OpenAIText(cfg.get("model", ""), cfg.get("temperature", 0.9))
    if p == "anthropic":
        return AnthropicText(cfg.get("model", ""), cfg.get("temperature", 0.9))
    return TextProvider()


# ---------------------------------------------------------------- images
def image_generate(cfg: dict, prompt: str, out_file: Path, reference: Path | list[Path] | None = None) -> Path:
    """Generate with the selected provider; on failure use the fallback provider (Settings > image fallback)."""
    fb = cfg.get("fallback", "none")
    try:
        return _image_generate_one(cfg, prompt, out_file, reference)
    except (ProviderError, ProviderNotConfigured) as e:
        if not fb or fb == "none" or fb == cfg.get("provider"):
            raise
        if cfg.get("provider") == "codex-cli":
            # Codex runs on the ChatGPT plan ($0 per image). Switching to a paid API on failure would spend money the
            # owner never saw a price for, so a Codex failure stops the job instead.
            raise
        fallback_log(f"image: {cfg.get('provider')} failed ({str(e)[:200]}); using fallback {fb}")
        return _image_generate_one({**cfg, "provider": fb, "model": ""}, prompt, out_file, reference)


def _image_generate_one(cfg: dict, prompt: str, out_file: Path, reference: Path | list[Path] | None = None) -> Path:
    """reference: one image or a list (for example the character's own neutral pose for identity, then the house-style
    reference). Codex attaches them all; the OpenAI generations endpoint takes none (prompt only)."""
    """Generate one PNG at out_file. Raises ProviderNotConfigured when image generation is off."""
    p = cfg.get("provider", "none")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    if s.env == "test" and _test_image is not None:
        return _test_image(prompt, out_file, reference)
    if p == "openai":
        if not secret("openai_api_key"):
            raise ProviderNotConfigured("openai images: OPENAI_API_KEY is not set on the server")
        body = {"model": cfg.get("model") or "gpt-image-2", "prompt": prompt, "size": cfg.get("size", "1024x1536"),
                "output_format": "png", "n": 1}
        # gpt-image-1 models accept a transparent background; gpt-image-2 rejects it (HTTP 400). Without it the figure
        # comes on a flat background, which the cut-out step (engine.make_cutout) removes, as with Codex images.
        if body["model"].startswith("gpt-image-1"):
            body["background"] = "transparent"
        else:
            # asked for "transparent", gpt-image-2 paints a fake checkerboard that the cut-out cannot remove. cfg
            # "background": the flat colour to ask for (default white, as before); None for images with their own scenery
            # (set plates). House style v2 poses use mid-grey: white heads would merge with a white background.
            bg = cfg.get("background", "white")
            body["prompt"] = prompt.replace("transparent (or flat white)", "flat white").replace("transparent", "flat white")
            if bg:
                body["prompt"] += f"\nBackground: one plain, solid, flat {bg} colour. No checkerboard or transparency pattern."
        refs = [] if reference is None else ([reference] if isinstance(reference, Path) else list(reference))
        if cfg.get("use_reference") and refs:
            # style reference (sets): the image-edit endpoint takes reference images with the prompt
            files = [("image[]", (Path(f).name, Path(f).read_bytes(), "image/png")) for f in refs]
            data = {k: str(v) for k, v in body.items() if k in ("model", "prompt", "size", "n", "output_format")}
            r = httpx.post("https://api.openai.com/v1/images/edits", timeout=300,
                           headers={"Authorization": f"Bearer {secret('openai_api_key')}"}, data=data, files=files)
        else:
            r = httpx.post("https://api.openai.com/v1/images/generations", timeout=300,
                           headers={"Authorization": f"Bearer {secret('openai_api_key')}"}, json=body)
        if r.status_code >= 400:
            raise http_error("openai images", r)
        out_file.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
        return out_file
    if p == "codex-cli":
        exe = shutil.which(s.codex_bin)
        if not exe:
            raise ProviderNotConfigured("codex-cli images: the `codex` command is not installed on the worker machine")
        state = codex_login_state()
        if state != "chatgpt":
            raise ProviderNotConfigured(
                "codex-cli images: Codex is not signed in with a ChatGPT plan on the worker "
                + ("(it is signed in with an API key, which would bill the API; sign out and sign in with ChatGPT)"
                   if state == "api-key" else "(sign in once: see README, 'Codex on the ChatGPT plan')"))
        with codex_workdir("image") as tmp:
            cmd = [exe, "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "-C", tmp]
            refs = [] if reference is None else ([reference] if isinstance(reference, Path) else list(reference))
            for k, r in enumerate(refs):
                ref = Path(tmp) / (f"reference-{k + 1}" + Path(r).suffix)
                shutil.copyfile(r, ref)
                cmd += ["-i", str(ref)]
            # Background: poses default to transparent (the cut-out step expects it); cfg "background": None for images
            # with their own scenery (sets, storyboard frames), or a flat colour name, as for the OpenAI provider.
            bg = cfg.get("background", "transparent")
            if bg is None:
                bg_line = "The image has its own full scenery (no transparent or plain background)."
            elif bg == "transparent":
                bg_line = "Transparent background PNG."
            else:
                bg_line = f"Background: one plain, solid, flat {bg} colour. No checkerboard or transparency pattern."
            size = cfg.get("size") or ""
            size_line = f" Image size {size} pixels (or the nearest size your tool makes, same orientation)." if size else ""
            instruction = (f"Generate exactly one image with your image generation tool and save it as out.png in the current "
                           f"directory. Do not retry and do not make variants. {bg_line}{size_line} Image description:\n{prompt}")
            before = _codex_pngs()
            try:
                r = subprocess.run(cmd + ["-"], input=instruction, capture_output=True, text=True, encoding="utf-8",
                                   timeout=s.job_timeout_seconds, env=codex_env())
            except subprocess.TimeoutExpired as e:
                # not transient: an automatic retry would spend plan allowance the owner did not ask for
                raise ProviderError("codex-cli image generation timed out", transient=False) from e
            made = Path(tmp) / "out.png"
            if not made.exists():
                # Codex sometimes makes the image but fails to copy it out of its sandbox: take the image its tool
                # saved in this call (the newest new file in its own images folder), never an older one.
                new = sorted(_codex_pngs() - before, key=lambda f: f.stat().st_mtime)
                if new:
                    made = new[-1]
            if r.returncode != 0 or not made.exists():
                raise ProviderError(f"codex-cli image generation produced no image (exit {r.returncode}): {(r.stderr or r.stdout)[-600:]}")
            # On Windows a Codex helper process can keep the new image open for a moment after Codex exits:
            # retry the copy for up to 30 s instead of failing the job.
            for attempt in range(30):
                try:
                    shutil.copyfile(made, out_file)
                    break
                except PermissionError:
                    if attempt == 29:
                        raise
                    time.sleep(1)
            return out_file
    raise ProviderNotConfigured("Image generation is off. Choose an image provider in Settings > AI providers "
                                "(each generation is started by the owner from the dashboard).")


# ---------------------------------------------------------------- voice
# Voice providers. Each returns the written audio file (WAV or MP3; the engine accepts any format FFmpeg reads).
#   openai     gpt-4o-mini-tts (default model): accepts acting "instructions" (character voice style + line delivery).
#   elevenlabs ElevenLabs text-to-speech: `voice` is an ElevenLabs voice id; strongest character voices.
#   piper      local, free, CPU: `voice` is the path of a Piper .onnx voice model on the worker (PIPER_BIN).
#   fish       Fish Audio (default model s2-pro): `voice` is a Fish voice model id (reference_id); optional speed.
_test_voice = None
_test_image = None


def set_test_voice(fn) -> None:
    """Tests only: fn(text, voice, instructions, out_file) -> out_file."""
    global _test_voice
    _test_voice = fn


def set_test_image(fn) -> None:
    """Tests only: fn(prompt, out_file, reference) -> out_file."""
    global _test_image
    _test_image = fn


VOICE_DEFAULTS = {"openai": "alloy", "kokoro": "am_michael"}   # fallback voice when a character's voice belongs to another provider


def piper_voices() -> list[Path]:
    d = Path(os.environ.get("PIPER_VOICES_DIR", "")) if os.environ.get("PIPER_VOICES_DIR") else None
    return sorted(d.glob("*.onnx")) if d and d.is_dir() else []


def resolve_piper_voice(voice: str) -> str:
    """A character's Piper voice is a model path. On another machine (the server) the same model is found by file
    name in PIPER_VOICES_DIR, so voices chosen on the workstation keep working after migration."""
    if voice and Path(voice).exists():
        return voice
    name = Path(voice.replace("\\", "/")).name if voice else ""
    for v in piper_voices():
        if v.name == name:
            return str(v)
    return voice


def looks_like_piper_path(voice: str | None) -> bool:
    v = (voice or "").strip()
    return bool(v) and ("/" in v or "\\" in v or v.lower().endswith(".onnx"))


FISH_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def speak(cfg: dict, text: str, voice: str, out_file: Path, instructions: str = "", speed: float | None = None) -> Path:
    """Speak with the selected provider; on failure use the fallback provider with its default voice.
    A character voice of the form "<engine>:<voice id>" (e.g. kokoro:bm_george, piper:en_GB-alan-medium.onnx,
    fish:<reference_id>) always uses that engine: each character keeps one fixed voice and engine in every episode
    (owner decision 2026-11-17). `speed` is the character's optional voice speed (used by Fish Audio).
    A bare voice that looks like a file path (contains / or \\, or ends in .onnx) is a Piper model chosen before engine
    prefixes existed: it always uses Piper, whatever the selected provider (owner decision 2026-11-20)."""
    m = re.match(r"^(kokoro|piper|openai|elevenlabs|fish):(.+)$", voice or "")
    if m:
        cfg, voice = {**cfg, "provider": m.group(1), "model": "" if m.group(1) != cfg.get("provider") else cfg.get("model", "")}, m.group(2)
    elif looks_like_piper_path(voice):
        cfg = {**cfg, "provider": "piper", "model": "" if cfg.get("provider") != "piper" else cfg.get("model", "")}
    fb = cfg.get("fallback", "none")
    try:
        return _speak_one(cfg, text, voice, out_file, instructions, speed)
    except (ProviderError, ProviderNotConfigured) as e:
        if not fb or fb == "none" or fb == cfg.get("provider"):
            raise
        fallback_log(f"voice: {cfg.get('provider')} failed ({str(e)[:200]}); using fallback {fb}")
        fv = VOICE_DEFAULTS.get(fb, "")
        if fb == "piper":
            vs = piper_voices()
            fv = str(vs[0]) if vs else ""
        elif fb == "fish":
            fv = re.sub(r"^fish:", "", cfg.get("fish_default_voice") or "")
        return _speak_one({**cfg, "provider": fb, "model": "", "default_voice": fv}, text, fv, out_file, instructions)


def _speak_one(cfg: dict, text: str, voice: str, out_file: Path, instructions: str = "", speed: float | None = None) -> Path:
    p = cfg.get("provider", "none")
    s = get_settings()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if s.env == "test" and _test_voice is not None:
        return _test_voice(text, voice, instructions, out_file)
    if p == "fish":
        # Fish Audio has no separate acting-direction field: emotion tags such as [whisper] go inline in the line text.
        return fish_speak(text, voice or cfg.get("default_voice") or "", out_file, model=cfg.get("model") or "", speed=speed)
    if p == "openai":
        if not secret("openai_api_key"):
            raise ProviderNotConfigured("openai voice: OPENAI_API_KEY is not set on the server")
        body = {"model": cfg.get("model") or "gpt-4o-mini-tts", "voice": voice or cfg.get("default_voice") or "alloy",
                "input": text, "response_format": "wav"}
        if instructions and not body["model"].startswith("tts-1"):
            body["instructions"] = instructions[:1000]
        r = httpx.post("https://api.openai.com/v1/audio/speech", timeout=180, headers={"Authorization": f"Bearer {secret("openai_api_key")}"}, json=body)
        if r.status_code >= 400:
            raise http_error("openai voice", r)
        f = out_file.with_suffix(".wav")
        f.write_bytes(r.content)
        return f
    if p == "elevenlabs":
        if not secret("elevenlabs_api_key"):
            raise ProviderNotConfigured("elevenlabs: ELEVENLABS_API_KEY is not set on the server")
        vid = voice or cfg.get("default_voice")
        if not vid:
            raise ProviderNotConfigured("elevenlabs: assign a voice id to this character (Characters) or set a default voice")
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_128", timeout=180,
                       headers={"xi-api-key": secret("elevenlabs_api_key")},
                       json={"text": text, "model_id": cfg.get("model") or "eleven_multilingual_v2",
                             "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.5}})
        if r.status_code >= 400:
            raise http_error("elevenlabs", r)
        f = out_file.with_suffix(".mp3")
        f.write_bytes(r.content)
        return f
    if p == "piper":
        exe = shutil.which(s.piper_bin)
        model = resolve_piper_voice(voice or cfg.get("default_voice") or "")
        if not exe:
            raise ProviderNotConfigured("piper: the `piper` command is not installed on the worker (PIPER_BIN)")
        if not model or not Path(model).exists():
            raise ProviderNotConfigured("piper: the character's voice must be the path of an installed Piper .onnx model")
        f = out_file.with_suffix(".wav")
        # Piper (Python) must read stdin as UTF-8: under a Windows code page, typographic quotes (U+201D contains the
        # byte 0x9D, undefined in cp1252) break decoding and Piper writes an empty WAV.
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        r = subprocess.run([exe, "--model", model, "--output_file", str(f)], input=text, capture_output=True, text=True,
                           encoding="utf-8", timeout=300, env=env)
        if r.returncode != 0 or not f.exists():
            raise ProviderError(f"piper failed: {(r.stderr or r.stdout)[-400:]}")
        return f
    if p == "kokoro":
        # Kokoro-82M on the CPU (oddstudio/kokoro.py); `voice` is a Kokoro voice id (am_michael, bf_emma, ...)
        from . import kokoro
        return kokoro.speak(text, voice or cfg.get("default_voice") or "", out_file)
    raise ProviderNotConfigured("No voice provider is configured")


FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_CREDIT_URL = "https://api.fish.audio/wallet/self/api-credit"
FISH_DEFAULT_MODEL = "s2-pro"
FISH_SAMPLE_RATE = 44100
FISH_RETRIES = 2                 # 429 / 5xx / network errors: at most two retries, with backoff
FISH_BACKOFF = (1.0, 3.0)
_sleep = time.sleep              # tests replace this so retries do not wait


def _redact(msg: str, key: str) -> str:
    """Error text never carries the API key (nor any bearer token echoed back by a proxy)."""
    if key:
        msg = msg.replace(key, "***")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", msg)


def fish_cache_file(model: str, voice: str, speed: float, sample_rate: int, text: str) -> Path:
    import hashlib
    h = hashlib.sha256(json.dumps({"model": model, "voice": voice, "speed": speed, "sample_rate": sample_rate, "text": text},
                                  sort_keys=True).encode()).hexdigest()
    return get_settings().work_dir / "voice-cache" / "fish" / f"{h}.wav"


def fish_speak(text: str, voice: str, out_file: Path, model: str = "", speed: float | None = None, use_cache: bool = True) -> Path:
    """Fish Audio TTS (docs.fish.audio, POST /v1/tts). `voice` is a Fish voice model id (reference_id). Writes a 44.1 kHz
    WAV, the same kind of file Piper and Kokoro produce, so Rhubarb lip sync and the audio bed take it unchanged.
    Clips are cached by (model, voice, speed, sample rate, text): re-running a scene does not pay for the same line twice.
    use_cache=False (the provider test) always calls the API, so a passing test proves synthesis works now."""
    key = secret("fish_api_key")
    if not key:
        raise ProviderNotConfigured("fish: no Fish Audio API key (Settings > Credentials, or FISH_API_KEY on the server)")
    if not voice:
        raise ProviderNotConfigured("fish: assign a Fish voice to this character (Characters: fish:<voice id>) or set the Fish default voice")
    if not FISH_ID.match(voice):
        # checked before any request: the API would answer HTTP 400, and the voice is not something Fish can use
        shown = voice if len(voice) <= 60 else voice[:57] + "..."
        raise ProviderNotConfigured(f"fish: {shown!r} is not a Fish voice id (letters, digits, _ and -, up to 128 characters). "
                                    "Set the character's voice to fish:<voice id> from the voice's page on fish.audio")
    model = model or FISH_DEFAULT_MODEL
    speed = float(speed) if speed else 1.0
    if not 0.5 <= speed <= 2.0:
        raise ProviderError(f"fish: speed {speed} is outside 0.5-2.0")
    f = out_file.with_suffix(".wav")
    cached = fish_cache_file(model, voice, speed, FISH_SAMPLE_RATE, text)
    if use_cache and cached.exists() and cached.stat().st_size > 44:
        fix_streaming_wav(cached)   # clips cached before this fix carry the streaming header
        shutil.copyfile(cached, f)
        return f
    body = {"text": text, "reference_id": voice, "format": "wav", "sample_rate": FISH_SAMPLE_RATE, "latency": "normal",
            "prosody": {"speed": speed}}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "model": model}
    last: ProviderError | None = None
    for attempt in range(FISH_RETRIES + 1):
        if attempt:
            _sleep(FISH_BACKOFF[min(attempt - 1, len(FISH_BACKOFF) - 1)])
        try:
            r = httpx.post(FISH_TTS_URL, headers=headers, json=body, timeout=180)
        except httpx.HTTPError as e:
            last = ProviderError(_redact(f"fish: network error: {type(e).__name__}: {e}", key), transient=True)
            continue
        if r.status_code == 401:
            raise ProviderError("fish: HTTP 401: the Fish Audio API key was rejected (check Settings > Credentials)")
        if r.status_code == 402:
            raise ProviderError(f"fish: HTTP 402: no API credit for model {model} (s2-pro needs paid credit; "
                                f"set Model to s2.1-pro-free for the free tier)")
        if r.status_code == 429 or r.status_code >= 500:
            last = ProviderError(_redact(f"fish: HTTP {r.status_code}: {r.text[:300]}", key), transient=True)
            continue
        if r.status_code >= 400:
            raise ProviderError(_redact(f"fish: HTTP {r.status_code}: {r.text[:500]}", key))
        if not r.content.startswith(b"RIFF"):
            raise ProviderError(f"fish: the answer was not WAV audio ({r.headers.get('content-type', 'unknown type')}, {len(r.content)} bytes)")
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(f".{uuid.uuid4().hex[:8]}.part")
        tmp.write_bytes(r.content)
        fix_streaming_wav(tmp)
        try:
            _ensure_pcm16_wav(tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(cached)
        shutil.copyfile(cached, f)
        return f
    raise last or ProviderError("fish: request failed", transient=True)


def fix_streaming_wav(path: Path, write: bool = True) -> bool:
    """Fish Audio streams its WAV answer, so the header carries placeholder sizes (RIFF and data size 0xFFFFFFxx):
    FFprobe and Python's wave module read past them, but Rhubarb refuses the file (\"Could not open sound file\").
    Rewrites both sizes from the real file length, in place. Returns True if the header was (or, with write=False,
    would be) changed."""
    import struct
    with open(path, "r+b" if write else "rb") as f:
        data = f.read()
        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return False
        changed = False
        if struct.unpack("<I", data[4:8])[0] != len(data) - 8:
            if write:
                f.seek(4); f.write(struct.pack("<I", len(data) - 8))
            changed = True
        off = 12
        while off + 8 <= len(data):
            cid, size = data[off:off + 4], struct.unpack("<I", data[off + 4:off + 8])[0]
            if cid == b"data":
                real = len(data) - (off + 8)
                if size != real:
                    if write:
                        f.seek(off + 4); f.write(struct.pack("<I", real))
                    changed = True
                break
            off += 8 + size + (size & 1)
        return changed


def _ensure_pcm16_wav(path: Path) -> None:
    """Rhubarb and the WAV reader expect integer PCM, as Piper and Kokoro write. Anything else (e.g. float WAV) is
    converted in place to 16-bit PCM with FFmpeg."""
    import wave
    try:
        with wave.open(str(path)) as w:
            if w.getsampwidth() == 2 and w.getnframes() > 0:
                return
    except (wave.Error, EOFError):
        pass
    s = get_settings()
    if not s.ffmpeg:
        raise ProviderError("fish: the WAV answer is not 16-bit PCM and FFmpeg is not available to convert it")
    conv = path.with_suffix(".pcm16.wav")
    r = subprocess.run([s.ffmpeg, "-v", "error", "-y", "-i", str(path), "-c:a", "pcm_s16le", str(conv)],
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not conv.exists():
        raise ProviderError(f"fish: could not convert the WAV answer to 16-bit PCM: {(r.stderr or r.stdout)[-300:]}")
    conv.replace(path)


def fish_credit() -> str:
    """No-cost key check: the account's API credit balance (GET /wallet/self/api-credit)."""
    key = secret("fish_api_key")
    if not key:
        raise ProviderNotConfigured("fish: no Fish Audio API key (Settings > Credentials, or FISH_API_KEY on the server)")
    r = httpx.get(FISH_CREDIT_URL, headers={"Authorization": f"Bearer {key}"}, timeout=30)
    if r.status_code == 401:
        raise ProviderError("fish: HTTP 401: the Fish Audio API key was rejected (check Settings > Credentials)")
    if r.status_code >= 400:
        raise ProviderError(_redact(f"fish: HTTP {r.status_code}: {r.text[:300]}", key), transient=r.status_code == 429 or r.status_code >= 500)
    return str(r.json().get("credit", ""))


def audio_seconds(path: Path) -> float:
    """Duration of an audio file (FFprobe when available; WAV header otherwise)."""
    s = get_settings()
    if s.ffprobe:
        r = subprocess.run([s.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    import wave
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def env_for_node() -> dict:
    env = dict(os.environ)
    s = get_settings()
    if s.ffmpeg:
        env["FFMPEG"] = s.ffmpeg
    if s.ffprobe:
        env["FFPROBE"] = s.ffprobe
    return env
