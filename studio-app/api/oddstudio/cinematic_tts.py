"""Voices for cinematic episodes: FREE text-to-speech on the studio server, or the owner's own recordings per line.

The engine: Kokoro-82M through kokoro-onnx (oddstudio/kokoro.py), already in the studio image:
  * code: kokoro-onnx 0.4.7 (MIT), pinned in studio-app/api/Dockerfile; it runs on onnxruntime, no PyTorch;
  * weights and voice pack: Kokoro-82M v1.0 (kokoro-v1.0.onnx, voices-v1.0.bin, release "model-files-v1.0"),
    Apache-2.0: commercial use allowed;
  * Python: the studio image runs Python 3.13 (Debian trixie) and kokoro-onnx 0.4.7 installs and runs there (it is
    used by Settings > Voice and the voice comparison today). The test image does not install it; tests replace the
    speak function (set_test_speak).
Only engines whose code AND weights allow commercial use can be chosen; the ones below in BLOCKED are refused by name
(non-commercial licences), and any engine not listed is refused too.

Each line is spoken with its character's voice (Character.voice "kokoro:<voice id>", chosen by the owner on the Cast
step; a suggestion per character is shown, never saved for the owner), its emotion only nudging the speed. A line's take
is never approved by itself: the owner listens and approves; only approved takes drive the talking shots.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path

ENGINES = {
    "kokoro": {"label": "Kokoro-82M on the studio server (free)", "code_licence": "MIT (kokoro-onnx 0.4.7)",
               "weights_licence": "Apache-2.0 (Kokoro-82M v1.0)", "commercial": True, "runs_on": "studio server CPU",
               "pinned": "kokoro-onnx==0.4.7; model-files-v1.0 (kokoro-v1.0.onnx, voices-v1.0.bin)", "usd": 0.0},
    "upload": {"label": "Your own recordings (one per line)", "code_licence": "", "weights_licence": "",
               "commercial": True, "runs_on": "", "pinned": "", "usd": 0.0},
}
# never offered: their weights or voices are licensed for non-commercial use only
BLOCKED = {
    "xtts-v2": "Coqui Public Model Licence: non-commercial use only",
    "f5-tts": "the released weights are CC BY-NC 4.0: non-commercial use only",
    "fish-speech": "the open weights are CC BY-NC-SA 4.0: non-commercial use only",
    "bark-voice-clones": "cloned voices of real people are never used",
    "piper-lessac": "trained on data licensed for non-commercial research only",
}

# Kokoro v1.0 English voices (all in the Apache-2.0 voice pack): id -> (label, gender, accent)
KOKORO_VOICES: dict[str, tuple[str, str, str]] = {
    "am_michael": ("Michael", "male", "American"), "am_adam": ("Adam", "male", "American"),
    "am_eric": ("Eric", "male", "American"), "am_fenrir": ("Fenrir", "male", "American"),
    "am_liam": ("Liam", "male", "American"), "am_onyx": ("Onyx (deep)", "male", "American"),
    "am_echo": ("Echo", "male", "American"), "am_puck": ("Puck", "male", "American"),
    "bm_george": ("George", "male", "British"), "bm_daniel": ("Daniel", "male", "British"),
    "bm_lewis": ("Lewis", "male", "British"), "bm_fable": ("Fable", "male", "British"),
    "af_heart": ("Heart", "female", "American"), "af_bella": ("Bella", "female", "American"),
    "af_nicole": ("Nicole", "female", "American"), "af_sarah": ("Sarah", "female", "American"),
    "af_aoede": ("Aoede", "female", "American"), "af_kore": ("Kore", "female", "American"),
    "af_nova": ("Nova", "female", "American"), "af_river": ("River", "female", "American"),
    "bf_emma": ("Emma", "female", "British"), "bf_isabella": ("Isabella", "female", "British"),
    "bf_alice": ("Alice", "female", "British"), "bf_lily": ("Lily", "female", "British"),
}
# for epic / period drama the British male voices first (a king's court), then the American ones
SUGGEST_ORDER = {"male": ["bm_george", "bm_daniel", "am_onyx", "bm_lewis", "am_michael", "am_adam", "am_eric", "bm_fable",
                          "am_fenrir", "am_liam", "am_echo", "am_puck"],
                 "female": ["bf_emma", "af_heart", "bf_isabella", "af_bella", "bf_alice", "af_nicole", "af_sarah",
                            "bf_lily", "af_aoede", "af_kore", "af_nova", "af_river"]}
SPEED = {"angry": 1.06, "furious": 1.08, "excited": 1.08, "urgent": 1.1, "afraid": 1.05, "scared": 1.05,
         "sad": 0.92, "grieving": 0.9, "tired": 0.92, "solemn": 0.94, "calm": 0.97, "whisper": 0.94}

_test_speak = None             # tests only: fn(text, voice_id, speed, out_file) -> wav path


def set_test_speak(fn) -> None:
    global _test_speak
    _test_speak = fn


def choose_engine(name: str) -> dict:
    """The engine by name, refused (ValueError, plain words) when blocked, not commercial or unknown."""
    n = str(name or "").strip().lower()
    if n in BLOCKED:
        raise ValueError(f"\"{name}\" cannot be used: {BLOCKED[n]}")
    e = ENGINES.get(n)
    if e is None:
        raise ValueError(f"\"{name}\" is not a voice engine the studio offers ({', '.join(ENGINES)})")
    if not e["commercial"]:
        raise ValueError(f"\"{name}\" is not licensed for commercial use")
    return {"id": n, **e}


def voice_id(voice: str | None) -> str | None:
    """"kokoro:bm_george" or "bm_george" -> "bm_george" when it is a Kokoro voice of the catalogue, else None."""
    v = str(voice or "").strip()
    if v.startswith("kokoro:"):
        v = v.split(":", 1)[1]
    return v if v in KOKORO_VOICES else None


def check_voice(voice: str) -> str:
    """The stored form "kokoro:<id>" of an allowed voice, or ValueError."""
    v = voice_id(voice)
    if v is None:
        raise ValueError(f"\"{voice}\" is not one of the free Kokoro voices")
    return f"kokoro:{v}"


def gender_of(hint: str) -> str:
    h = f" {str(hint or '').lower()} "
    if re.search(r"\b(woman|female|girl|queen|princess|mother|daughter|sister|wife|she|her|lady|widow|maid)\b", h):
        return "female"
    return "male"


def suggest(characters: list[dict], taken: set[str] | None = None) -> dict[str, str]:
    """{character name: voice id}: a different voice per character, by gender from the character's words (role, voice
    hint), in SUGGEST_ORDER. Only a suggestion: the owner saves the voice."""
    used = set(taken or ())
    out = {}
    for c in characters:
        g = gender_of(" ".join(str(c.get(k) or "") for k in ("voice", "role", "name", "personality")))
        pick = next((v for v in SUGGEST_ORDER[g] if v not in used), SUGGEST_ORDER[g][0])
        used.add(pick)
        out[c["name"]] = pick
    return out


def catalogue() -> list[dict]:
    return [{"id": k, "label": f"{lab} ({g}, {acc})", "gender": g, "accent": acc} for k, (lab, g, acc) in KOKORO_VOICES.items()]


def speed_for(emotion: str) -> float:
    e = str(emotion or "").lower()
    return next((s for k, s in SPEED.items() if k in e), 1.0)


def seconds_of(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        return round(w.getnframes() / float(w.getframerate() or 1), 3)


def speak(text: str, voice: str, emotion: str, out_file: Path) -> Path:
    """One line spoken on the studio server (free). Returns the WAV path."""
    v = voice_id(voice)
    if v is None:
        raise ValueError(f"choose a voice for this character first (\"{voice or 'none'}\" is not a free Kokoro voice)")
    sp = speed_for(emotion)
    if _test_speak is not None:
        return _test_speak(text, v, sp, out_file)
    from . import kokoro
    return kokoro.speak(text, v, out_file, speed=sp)
