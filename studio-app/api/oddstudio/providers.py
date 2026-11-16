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
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import get_settings


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


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
        with tempfile.TemporaryDirectory(prefix="odd-codex-") as tmp:
            out = Path(tmp) / "answer.md"
            cmd = [exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-C", tmp, "-o", str(out)]
            if self.model:
                cmd += ["-m", self.model]
            full = f"{system}\n\n{prompt}\n\nReturn ONLY the JSON object, with no commentary."
            try:
                r = subprocess.run(cmd + ["-"], input=full, capture_output=True, text=True, encoding="utf-8",
                                   timeout=s.job_timeout_seconds)
            except subprocess.TimeoutExpired as e:
                raise ProviderError("codex-cli timed out") from e
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
        key = get_settings().openai_api_key
        if not key:
            raise ProviderNotConfigured("openai: OPENAI_API_KEY is not set on the server")
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=180,
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": self.model, "temperature": self.temperature,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        if r.status_code >= 400:
            raise ProviderError(f"openai: HTTP {r.status_code}: {r.text[:500]}")
        return extract_json(r.json()["choices"][0]["message"]["content"])


class AnthropicText(TextProvider):
    name = "anthropic"

    def __init__(self, model: str = "", temperature: float = 0.9):
        self.model = model or "claude-sonnet-5-5"
        self.temperature = temperature

    def complete_json(self, system: str, prompt: str) -> dict:
        key = get_settings().anthropic_api_key
        if not key:
            raise ProviderNotConfigured("anthropic: ANTHROPIC_API_KEY is not set on the server")
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=300,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": self.model, "max_tokens": 8000, "temperature": self.temperature, "system": system,
                             "messages": [{"role": "user", "content": prompt + "\n\nReturn ONLY the JSON object."}]})
        if r.status_code >= 400:
            raise ProviderError(f"anthropic: HTTP {r.status_code}: {r.text[:500]}")
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
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


def text_provider(cfg: dict) -> TextProvider:
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
def image_generate(cfg: dict, prompt: str, out_file: Path, reference: Path | None = None) -> Path:
    """Generate one PNG at out_file. Raises ProviderNotConfigured when image generation is off."""
    p = cfg.get("provider", "none")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    if s.env == "test" and _test_image is not None:
        return _test_image(prompt, out_file, reference)
    if p == "openai":
        if not s.openai_api_key:
            raise ProviderNotConfigured("openai images: OPENAI_API_KEY is not set on the server")
        body = {"model": cfg.get("model") or "gpt-image-1", "prompt": prompt, "size": cfg.get("size", "1024x1536"),
                "background": "transparent", "output_format": "png", "n": 1}
        r = httpx.post("https://api.openai.com/v1/images/generations", timeout=300,
                       headers={"Authorization": f"Bearer {s.openai_api_key}"}, json=body)
        if r.status_code >= 400:
            raise ProviderError(f"openai images: HTTP {r.status_code}: {r.text[:500]}")
        out_file.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
        return out_file
    if p == "codex-cli":
        exe = shutil.which(s.codex_bin)
        if not exe:
            raise ProviderNotConfigured("codex-cli images: the `codex` command is not installed on the worker machine")
        with tempfile.TemporaryDirectory(prefix="odd-img-") as tmp:
            cmd = [exe, "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "-C", tmp]
            if reference is not None:
                ref = Path(tmp) / ("reference" + reference.suffix)
                shutil.copyfile(reference, ref)
                cmd += ["-i", str(ref)]
            instruction = (f"Generate exactly one image with your image generation tool and save it as out.png in the current "
                           f"directory. Transparent background PNG. Image description:\n{prompt}")
            try:
                r = subprocess.run(cmd + ["-"], input=instruction, capture_output=True, text=True, encoding="utf-8",
                                   timeout=s.job_timeout_seconds)
            except subprocess.TimeoutExpired as e:
                raise ProviderError("codex-cli image generation timed out") from e
            made = Path(tmp) / "out.png"
            if r.returncode != 0 or not made.exists():
                raise ProviderError(f"codex-cli image generation produced no image (exit {r.returncode}): {(r.stderr or r.stdout)[-600:]}")
            shutil.copyfile(made, out_file)
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


def speak(cfg: dict, text: str, voice: str, out_file: Path, instructions: str = "") -> Path:
    p = cfg.get("provider", "none")
    s = get_settings()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if s.env == "test" and _test_voice is not None:
        return _test_voice(text, voice, instructions, out_file)
    if p == "openai":
        if not s.openai_api_key:
            raise ProviderNotConfigured("openai voice: OPENAI_API_KEY is not set on the server")
        body = {"model": cfg.get("model") or "gpt-4o-mini-tts", "voice": voice or cfg.get("default_voice") or "alloy",
                "input": text, "response_format": "wav"}
        if instructions and not body["model"].startswith("tts-1"):
            body["instructions"] = instructions[:1000]
        r = httpx.post("https://api.openai.com/v1/audio/speech", timeout=180, headers={"Authorization": f"Bearer {s.openai_api_key}"}, json=body)
        if r.status_code >= 400:
            raise ProviderError(f"openai voice: HTTP {r.status_code}: {r.text[:500]}")
        f = out_file.with_suffix(".wav")
        f.write_bytes(r.content)
        return f
    if p == "elevenlabs":
        if not s.elevenlabs_api_key:
            raise ProviderNotConfigured("elevenlabs: ELEVENLABS_API_KEY is not set on the server")
        vid = voice or cfg.get("default_voice")
        if not vid:
            raise ProviderNotConfigured("elevenlabs: assign a voice id to this character (Characters) or set a default voice")
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_128", timeout=180,
                       headers={"xi-api-key": s.elevenlabs_api_key},
                       json={"text": text, "model_id": cfg.get("model") or "eleven_multilingual_v2",
                             "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.5}})
        if r.status_code >= 400:
            raise ProviderError(f"elevenlabs: HTTP {r.status_code}: {r.text[:500]}")
        f = out_file.with_suffix(".mp3")
        f.write_bytes(r.content)
        return f
    if p == "piper":
        exe = shutil.which(s.piper_bin)
        model = voice or cfg.get("default_voice")
        if not exe:
            raise ProviderNotConfigured("piper: the `piper` command is not installed on the worker (PIPER_BIN)")
        if not model or not Path(model).exists():
            raise ProviderNotConfigured("piper: the character's voice must be the path of an installed Piper .onnx model")
        f = out_file.with_suffix(".wav")
        r = subprocess.run([exe, "--model", model, "--output_file", str(f)], input=text, capture_output=True, text=True,
                           encoding="utf-8", timeout=300)
        if r.returncode != 0 or not f.exists():
            raise ProviderError(f"piper failed: {(r.stderr or r.stdout)[-400:]}")
        return f
    raise ProviderNotConfigured("No voice provider is configured")


def audio_seconds(path: Path) -> float:
    """Duration of an audio file (FFprobe when available; WAV header otherwise)."""
    s = get_settings()
    if s.ffprobe:
        r = subprocess.run([s.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                           capture_output=True, text=True, timeout=60)
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
