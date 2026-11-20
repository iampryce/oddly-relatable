"""Casting hints (A): pitch, pace and energy per speaker, MEASURED from the uploaded audio (owner decision 2026-11-20).

Plain signal measurements (no AI model): pitch is the median fundamental frequency of the speaker's voiced frames,
pace is words per second of their lines, energy is their loudness relative to the other speakers in the same recording.
Each is reported as a band (low/medium/high, slow/medium/fast, soft/medium/loud) with the number behind it. They are
suggestions the owner edits. Gender and age are never inferred from them (or from anything else): the owner sets those.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .config import get_settings

RATE = 16000
FRAME = 640                     # 40 ms
F0_MIN, F0_MAX = 70.0, 400.0
PITCH_BANDS = (140.0, 210.0)    # Hz: below -> low, above the second -> high
PACE_BANDS = (2.0, 3.2)         # words per second
ENERGY_DB = 3.0                 # dB away from the recording's average speaker -> soft / loud
PITCH = ("low", "medium", "high")
PACE = ("slow", "medium", "fast")
ENERGY = ("soft", "medium", "loud")


def decode(path: Path) -> np.ndarray | None:
    """Mono float samples at 16 kHz (None without FFmpeg)."""
    ff = get_settings().ffmpeg
    if not ff:
        return None
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                       capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise ValueError("the audio could not be decoded")
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0


def frame_f0(frame: np.ndarray, rate: int = RATE) -> float | None:
    """Fundamental frequency of one frame by normalised autocorrelation; None for unvoiced or silent frames."""
    x = frame - frame.mean()
    if np.sqrt(np.mean(x ** 2)) < 0.01:
        return None
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    lo, hi = int(rate / F0_MAX), min(int(rate / F0_MIN), len(ac) - 1)
    if hi <= lo:
        return None
    lag = lo + int(np.argmax(ac[lo:hi]))
    return rate / lag if ac[lag] > 0.45 else None


def segment(samples: np.ndarray, start: float, end: float, rate: int = RATE) -> np.ndarray:
    return samples[max(0, int(start * rate)):max(0, int(end * rate))]


def band(value: float, edges: tuple[float, float], names: tuple[str, str, str]) -> str:
    return names[0] if value < edges[0] else names[2] if value > edges[1] else names[1]


def measure(samples: np.ndarray, lines: list[dict], rate: int = RATE) -> dict[str, dict]:
    """{speaker label: {pitch, pitch_hz, pace, wps, energy, db, seconds}} for every labelled speaker."""
    raw: dict[str, dict] = {}
    for sp in dict.fromkeys(ln.get("speaker") for ln in lines if ln.get("speaker")):
        own = [ln for ln in lines if ln.get("speaker") == sp]
        audio = np.concatenate([segment(samples, ln["start"], ln["end"], rate) for ln in own] or [np.zeros(0, np.float32)])
        seconds = sum(max(0.0, ln["end"] - ln["start"]) for ln in own)
        words = sum(len(ln.get("words") or []) or len(str(ln.get("text", "")).split()) for ln in own)
        f0s = [f for k in range(0, len(audio) - FRAME, FRAME) if (f := frame_f0(audio[k:k + FRAME], rate))]
        rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
        raw[sp] = {"pitch_hz": round(float(np.median(f0s))) if f0s else None, "wps": round(words / seconds, 2) if seconds else None,
                   "db": round(20 * np.log10(rms), 1) if rms > 0 else None, "seconds": round(seconds, 2)}
    dbs = [v["db"] for v in raw.values() if v["db"] is not None]
    mean_db = float(np.mean(dbs)) if dbs else 0.0
    out = {}
    for sp, v in raw.items():
        rel = (v["db"] - mean_db) if v["db"] is not None and len(dbs) > 1 else 0.0
        out[sp] = {**v,
                   "pitch": band(v["pitch_hz"], PITCH_BANDS, PITCH) if v["pitch_hz"] else "medium",
                   "pace": band(v["wps"], PACE_BANDS, PACE) if v["wps"] else "medium",
                   "energy": ENERGY[0] if rel < -ENERGY_DB else ENERGY[2] if rel > ENERGY_DB else ENERGY[1]}
    return out


def describe(traits: dict) -> str:
    """The voice style text for a character: the (owner-edited) traits."""
    return f"pitch {traits.get('pitch', 'medium')}, pace {traits.get('pace', 'medium')}, energy {traits.get('energy', 'medium')}"
