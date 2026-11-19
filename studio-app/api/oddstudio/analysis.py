"""Analysis and audio-driven providers: transcription, visual analysis, lip sync, sound effects.

Each function is the worker-side adapter for one capability (see capabilities.py). They follow the same conventions as
providers.py: ProviderNotConfigured when a credential/tool is missing, ProviderError (transient where retryable) on
provider failures, and nothing secret in any error text.

  transcribe(cfg, audio)          -> {"text", "language", "duration", "segments": [{start, end, text, words?}], "words": [...]}
  analyse_images(cfg, images, q)  -> dict (the model's JSON answer about the frames)
  lipsync(audio, text?)           -> {"cues": [{start, end, value}]} (Rhubarb visemes A-H, X)
  sound_effect(cfg, text, secs, out) -> audio file
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx

from .providers import ProviderError, ProviderNotConfigured, extract_json, http_error
from .secrets_store import secret


# Tests only (refused outside ODD_ENV=test, like the other provider stand-ins).
_test_transcriber = None
_test_vision = None


def set_test_analysis(transcriber=None, vision=None) -> None:
    global _test_transcriber, _test_vision
    _test_transcriber, _test_vision = transcriber, vision


def _testing() -> bool:
    from .config import get_settings
    return get_settings().env == "test"


# ---------------------------------------------------------------- transcription
def transcribe(cfg: dict, audio: Path) -> dict:
    if _testing() and _test_transcriber:
        return _test_transcriber(cfg, audio)
    p = cfg.get("provider", "none")
    fb = cfg.get("fallback", "none")
    try:
        return _transcribe_one(p, cfg, audio)
    except (ProviderError, ProviderNotConfigured):
        if not fb or fb in ("none", p):
            raise
        from .providers import fallback_log
        fallback_log(f"transcription: {p} failed; using fallback {fb}")
        return _transcribe_one(fb, {**cfg, "model": ""}, audio)


def _transcribe_one(p: str, cfg: dict, audio: Path) -> dict:
    if p == "openai":
        key = secret("openai_api_key")
        if not key:
            raise ProviderNotConfigured("openai transcription: set the OpenAI API key under Settings > Credentials")
        model = cfg.get("model") or "whisper-1"
        with open(audio, "rb") as f:
            r = httpx.post("https://api.openai.com/v1/audio/transcriptions", timeout=600,
                           headers={"Authorization": f"Bearer {key}"},
                           data={"model": model, "response_format": "verbose_json",
                                 "timestamp_granularities[]": ["segment", "word"]},
                           files={"file": (audio.name, f)})
        if r.status_code >= 400:
            raise http_error("openai transcription", r)
        d = r.json()
        return {"provider": "openai", "model": model, "text": d.get("text", ""), "language": d.get("language", ""),
                "duration": d.get("duration"), "speakers": "not identified by this provider",
                "segments": [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in d.get("segments", [])],
                "words": [{"start": w["start"], "end": w["end"], "word": w["word"]} for w in d.get("words", [])]}
    if p == "local-whisper":
        try:
            from faster_whisper import WhisperModel
        except Exception as e:
            raise ProviderNotConfigured("local-whisper: the faster-whisper package is not installed on the worker") from e
        model_name = cfg.get("model") or "base.en"
        cache = os.environ.get("WHISPER_CACHE") or None
        model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=cache)
        # decode with FFmpeg (16 kHz mono float) rather than faster-whisper's PyAV path, which breaks on newer PyAV
        import numpy as np
        from .config import get_settings
        pcm = subprocess.run([get_settings().ffmpeg or "ffmpeg", "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                             capture_output=True, check=True, timeout=600, stdin=subprocess.DEVNULL).stdout
        segs, info = model.transcribe(np.frombuffer(pcm, dtype=np.float32), language=cfg.get("language") or None,
                                      word_timestamps=True, vad_filter=False)
        segments, words = [], []
        for s in segs:
            segments.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()})
            for w in s.words or []:
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word})
        return {"provider": "local-whisper", "model": model_name, "text": " ".join(s["text"] for s in segments),
                "language": info.language, "duration": round(info.duration, 3), "speakers": "not identified by this provider",
                "segments": segments, "words": words}
    raise ProviderNotConfigured("No transcription provider is selected (Settings > Audio transcription)")


# ---------------------------------------------------------------- visual analysis
def analyse_images(cfg: dict, images: list[Path], question: str) -> dict:
    """Ask a vision model about one or more frames; returns its JSON answer."""
    if _testing() and _test_vision:
        return _test_vision(cfg, images, question)
    p = cfg.get("provider", "none")
    fb = cfg.get("fallback", "none")
    try:
        return _vision_one(p, cfg, images, question)
    except (ProviderError, ProviderNotConfigured):
        if not fb or fb in ("none", p):
            raise
        from .providers import fallback_log
        fallback_log(f"vision: {p} failed; using fallback {fb}")
        return _vision_one(fb, {**cfg, "model": ""}, images, question)


def _b64(p: Path) -> tuple[str, str]:
    mt = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return mt, base64.b64encode(p.read_bytes()).decode()


def _vision_one(p: str, cfg: dict, images: list[Path], question: str) -> dict:
    prompt = question + "\n\nAnswer with one JSON object only."
    if p == "openai":
        key = secret("openai_api_key")
        if not key:
            raise ProviderNotConfigured("openai vision: set the OpenAI API key under Settings > Credentials")
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b}"}} for mt, b in map(_b64, images)]
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=300, headers={"Authorization": f"Bearer {key}"},
                       json={"model": cfg.get("model") or "gpt-4.1-mini", "response_format": {"type": "json_object"},
                             "messages": [{"role": "user", "content": content}]})
        if r.status_code >= 400:
            raise http_error("openai vision", r)
        return extract_json(r.json()["choices"][0]["message"]["content"])
    if p == "anthropic":
        key = secret("anthropic_api_key")
        if not key:
            raise ProviderNotConfigured("anthropic vision: set the Anthropic API key under Settings > Credentials")
        content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b}} for mt, b in map(_b64, images)]
        content.append({"type": "text", "text": prompt})
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=300,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": cfg.get("model") or "claude-sonnet-5-5", "max_tokens": 16000,
                             "messages": [{"role": "user", "content": content}]})
        if r.status_code >= 400:
            raise http_error("anthropic vision", r)
        data = r.json()
        if data.get("stop_reason") == "refusal":
            raise ProviderError("anthropic vision: the model declined this request")
        return extract_json("".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"))
    raise ProviderNotConfigured("No visual analysis provider is selected (Settings > Video and visual analysis)")


# ---------------------------------------------------------------- lip sync
def rhubarb_bin() -> str | None:
    b = os.environ.get("RHUBARB_BIN") or shutil.which("rhubarb")
    return b if b and Path(b).exists() else None


def lipsync(audio: Path, text: str = "") -> dict:
    """Rhubarb Lip Sync: viseme cues (A-H mouth shapes, X = rest) from the audio, optionally guided by the text."""
    exe = rhubarb_bin()
    if not exe:
        raise ProviderNotConfigured("rhubarb: Rhubarb Lip Sync is not installed on the worker (RHUBARB_BIN)")
    wav = audio
    if audio.suffix.lower() != ".wav":   # Rhubarb reads WAV/OGG; convert anything else
        from .config import get_settings
        wav = audio.with_suffix(".lipsync.wav")
        subprocess.run([get_settings().ffmpeg or "ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ac", "1", "-ar", "22050", str(wav)],
                       check=True, timeout=300, stdin=subprocess.DEVNULL)
    cmd = [exe, "-q", "-f", "json", str(wav)]
    if text:
        dialog = wav.with_suffix(".dialog.txt")
        dialog.write_text(text, encoding="utf-8")
        cmd[1:1] = ["-d", str(dialog)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise ProviderError(f"rhubarb failed: {(r.stderr or r.stdout)[-400:]}")
    cues = json.loads(r.stdout).get("mouthCues", [])
    if not cues:
        raise ProviderError("rhubarb returned no mouth cues")
    return {"provider": "rhubarb", "cues": cues}


# ---------------------------------------------------------------- sound effects
def sound_effect(cfg: dict, text: str, seconds: float, out: Path) -> Path:
    p = cfg.get("provider", "none")
    if p == "elevenlabs":
        key = secret("elevenlabs_api_key")
        if not key:
            raise ProviderNotConfigured("elevenlabs sound effects: set the ElevenLabs API key under Settings > Credentials")
        r = httpx.post("https://api.elevenlabs.io/v1/sound-generation", timeout=180, headers={"xi-api-key": key},
                       json={"text": text, "duration_seconds": max(0.5, min(22.0, seconds))})
        if r.status_code >= 400:
            raise http_error("elevenlabs sound effects", r)
        f = out.with_suffix(".mp3")
        f.write_bytes(r.content)
        return f
    raise ProviderNotConfigured("No sound-effect provider is selected (Settings > Music and sound effects)")
