"""AI providers: text (scripts), images (character poses, scene references) and voice.

Each provider either does the real call or raises ProviderNotConfigured with what is missing. Nothing here ever
returns placeholder content as if it had succeeded. The only stand-in, `FakeText`, exists for automated tests and is
refused unless ODD_ENV=test.

- codex-cli: the local `codex` CLI on the owner's ChatGPT subscription (no API spending). Only works where Codex is
  installed and logged in (the owner's workstation), not inside the server containers.
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
                                   timeout=s.job_timeout_seconds)
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
            # asked for "transparent", gpt-image-2 paints a fake checkerboard that the cut-out cannot remove
            body["prompt"] = (prompt.replace("transparent (or flat white)", "flat white").replace("transparent", "flat white")
                              + "\nBackground: one plain, solid, flat white colour. No checkerboard or transparency pattern.")
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
        with codex_workdir("image") as tmp:
            cmd = [exe, "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "-C", tmp]
            refs = [] if reference is None else ([reference] if isinstance(reference, Path) else list(reference))
            for k, r in enumerate(refs):
                ref = Path(tmp) / (f"reference-{k + 1}" + Path(r).suffix)
                shutil.copyfile(r, ref)
                cmd += ["-i", str(ref)]
            instruction = (f"Generate exactly one image with your image generation tool and save it as out.png in the current "
                           f"directory. Transparent background PNG. Image description:\n{prompt}")
            try:
                r = subprocess.run(cmd + ["-"], input=instruction, capture_output=True, text=True, encoding="utf-8",
                                   timeout=s.job_timeout_seconds)
            except subprocess.TimeoutExpired as e:
                raise ProviderError("codex-cli image generation timed out", transient=True) from e
            made = Path(tmp) / "out.png"
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


def speak(cfg: dict, text: str, voice: str, out_file: Path, instructions: str = "") -> Path:
    """Speak with the selected provider; on failure use the fallback provider with its default voice.
    A character voice of the form "<engine>:<voice id>" (e.g. kokoro:bm_george, piper:en_GB-alan-medium.onnx) always
    uses that engine: each character keeps one fixed voice and engine in every episode (owner decision 2026-11-17)."""
    m = re.match(r"^(kokoro|piper|openai|elevenlabs):(.+)$", voice or "")
    if m:
        cfg, voice = {**cfg, "provider": m.group(1), "model": "" if m.group(1) != cfg.get("provider") else cfg.get("model", "")}, m.group(2)
    fb = cfg.get("fallback", "none")
    try:
        return _speak_one(cfg, text, voice, out_file, instructions)
    except (ProviderError, ProviderNotConfigured) as e:
        if not fb or fb == "none" or fb == cfg.get("provider"):
            raise
        fallback_log(f"voice: {cfg.get('provider')} failed ({str(e)[:200]}); using fallback {fb}")
        fv = VOICE_DEFAULTS.get(fb, "")
        if fb == "piper":
            vs = piper_voices()
            fv = str(vs[0]) if vs else ""
        return _speak_one({**cfg, "provider": fb, "model": "", "default_voice": fv}, text, fv, out_file, instructions)


def _speak_one(cfg: dict, text: str, voice: str, out_file: Path, instructions: str = "") -> Path:
    p = cfg.get("provider", "none")
    s = get_settings()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if s.env == "test" and _test_voice is not None:
        return _test_voice(text, voice, instructions, out_file)
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
