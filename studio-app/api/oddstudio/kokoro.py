"""Kokoro-82M text-to-speech on the CPU (kokoro-onnx, MIT; model weights Apache-2.0: commercial use allowed).

Runs on onnxruntime (already installed for Piper; no PyTorch). The model (kokoro-v1.0.onnx, 326 MB) and voice pack
(voices-v1.0.bin, 28 MB) are downloaded once into KOKORO_DIR (default <work_dir>/models/kokoro) and reused.
Voices are Kokoro voice ids such as am_michael, af_heart, bm_george, bf_emma (a = American, b = British English).
"""
from __future__ import annotations

import os
import threading
import wave
from pathlib import Path

import httpx

from .providers import ProviderError, ProviderNotConfigured

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"kokoro-v1.0.onnx": 326_000_000, "voices-v1.0.bin": 28_000_000}
DEFAULT_VOICE = "am_michael"
_engine = None
_lock = threading.Lock()


def model_dir() -> Path:
    from .config import get_settings
    return Path(os.environ.get("KOKORO_DIR") or get_settings().work_dir / "models" / "kokoro")


def installed() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except Exception:
        return False


def _ensure_files() -> Path:
    d = model_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name, approx in FILES.items():
        f = d / name
        if f.exists() and f.stat().st_size > approx * 0.9:
            continue
        tmp = f.with_suffix(f.suffix + ".part")
        with httpx.stream("GET", RELEASE + name, follow_redirects=True, timeout=600) as r:
            if r.status_code >= 400:
                raise ProviderError(f"kokoro: could not download {name}: HTTP {r.status_code}", transient=r.status_code >= 500)
            with open(tmp, "wb") as out:
                for chunk in r.iter_bytes(1 << 20):
                    out.write(chunk)
        tmp.replace(f)
    return d


def engine():
    global _engine
    if not installed():
        raise ProviderNotConfigured("kokoro: the kokoro-onnx package is not installed on the worker")
    with _lock:
        if _engine is None:
            from kokoro_onnx import Kokoro
            d = _ensure_files()
            _engine = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
    return _engine


def voices() -> list[str]:
    return sorted(engine().get_voices())


def speak(text: str, voice: str, out_file: Path, speed: float = 1.0) -> Path:
    k = engine()
    v = voice if voice and voice in k.get_voices() else DEFAULT_VOICE   # a Piper path or unknown id falls back
    lang = "en-gb" if v.startswith("b") else "en-us"
    samples, rate = k.create(text, voice=v, speed=speed, lang=lang)
    f = out_file.with_suffix(".wav")
    pcm = (samples.clip(-1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(f), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return f
