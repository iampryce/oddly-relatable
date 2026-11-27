"""Narration voice for the narrated shorts (narrated_short.py, step 5): Gemini text-to-speech.

API (Google's Gemini speech generation docs; tested by the owner on 2026-11-27 with the "Charon" voice on the free tier):
  POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent
  header x-goog-api-key: <key>   (the key only ever goes in this header; never logged, returned or stored elsewhere)
  body   {"contents": [{"parts": [{"text": "<style instruction>: <narration>"}]}],
          "generationConfig": {"responseModalities": ["AUDIO"],
                               "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}}}}
  answer candidates[0].content.parts[*].inlineData.data = base64 raw PCM, 24 kHz, 16-bit signed little-endian, mono
         (mimeType "audio/L16;codec=pcm;rate=24000"). It is wrapped into a WAV file here.

Long narration (up to 10 minutes) is sent in pieces of at most MAX_WORDS words cut at sentence ends, and the pieces' PCM
is joined in order (with a short silence between), so no request runs into the model's length limit.

Tier rules (as every Gemini step: acting analysis, speaker suggestions, the quality check): the owner ticks "my key is on
a paid tier" (then the cost is shown at the paid prices below and must be confirmed), or ticks "use the free tier"
(then it costs nothing, but Google may use the text to improve its products: FREE_WARNING is shown). With neither
ticked nothing is sent (HTTP 409). Each request is sent ONCE, never retried (a 429 on the free tier is reported in plain
English).

Prices (Settings > Narrated shorts, defaults from Google's price list for gemini-2.5-flash-preview-tts): $0.50 per
million text tokens in, $10 per million audio tokens out; audio is 32 tokens per second.
"""
from __future__ import annotations

import base64
import io
import math
import re
import struct
import wave
from pathlib import Path

import httpx

from .providers import ProviderError, ProviderNotConfigured
from .secrets_store import secret

BASE = "https://generativelanguage.googleapis.com"
MODEL = "gemini-2.5-flash-preview-tts"
RATE, WIDTH, CHANNELS = 24000, 2, 1          # what the model returns: 24 kHz, 16-bit, mono
VOICES = ("Charon", "Kore", "Puck", "Fenrir", "Aoede", "Orus", "Leda", "Zephyr")
DEFAULT_VOICE = "Charon"
DEFAULT_STYLE = "warm, calm narrator"
AUDIO_TOKENS_PER_SECOND = 32
CHARS_PER_TOKEN = 3.5
WORDS_PER_SECOND = 3.7
MAX_WORDS = 450                # one request (about 2 minutes of speech)
GAP_S = 0.25                   # silence between the pieces of a long narration
MARGIN = 1.5                   # "at most": the speech may run 50% longer than the 3.7 words/s estimate
FREE_WARNING = ("Free tier: Google may use the narration text you send to improve its products. Tick \"my key is on a "
                "paid tier\" instead if that is not acceptable.")

_transport = None              # tests only: an httpx.MockTransport instead of the network


def set_test_transport(t) -> None:
    global _transport
    _transport = t


# ------------------------------------------------------------------ pure parts
def pcm_to_wav(pcm: bytes, rate: int = RATE, width: int = WIDTH, channels: int = CHANNELS) -> bytes:
    """Raw little-endian PCM -> a WAV file (an odd trailing byte is dropped: half a sample is not audio)."""
    frame = width * channels
    pcm = pcm[: len(pcm) - (len(pcm) % frame)]
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return b.getvalue()


def silence(seconds: float, rate: int = RATE) -> bytes:
    return b"\x00\x00" * int(round(seconds * rate))


def pcm_seconds(pcm: bytes, rate: int = RATE) -> float:
    return len(pcm) / (WIDTH * CHANNELS) / rate


def chunk_text(text: str, max_words: int = MAX_WORDS) -> list[str]:
    """The narration cut into pieces of at most max_words words, at sentence ends (a single longer sentence is kept
    whole: cutting it would change how it is spoken)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", (text or "").strip()) if s.strip()]
    out, cur = [], []
    for s in sentences:
        n = len(s.split())
        if cur and sum(len(x.split()) for x in cur) + n > max_words:
            out.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def spoken_text(text: str, style: str) -> str:
    """The text sent to the model: the style instruction, then the narration (Google's documented way to steer it)."""
    style = (style or "").strip().rstrip(":.")
    return f"Read this in a {style} voice: {text.strip()}" if style else text.strip()


def request_body(text: str, voice: str, style: str) -> dict:
    return {"contents": [{"parts": [{"text": spoken_text(text, style)}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}


def estimate(text: str, cfg: dict, paid_tier: bool, use_free_tier: bool) -> dict:
    """What the narration can cost. Raises ValueError when neither tier is ticked (nothing may be sent then)."""
    if not paid_tier and not use_free_tier:
        raise ValueError("tick \"my key is on a paid tier\" or \"use the free tier\" first (nothing was sent)")
    words = len((text or "").split())
    seconds = words / WORDS_PER_SECOND
    pieces = max(1, len(chunk_text(text)))
    tin = math.ceil(len(spoken_text(text, "x" * 40)) / CHARS_PER_TOKEN) + 10 * pieces
    tout_typ = math.ceil(seconds * AUDIO_TOKENS_PER_SECOND)
    tout_max = math.ceil(seconds * MARGIN * AUDIO_TOKENS_PER_SECOND) + 200 * pieces
    p_in, p_out = float(cfg.get("tts_usd_in", 0.5)), float(cfg.get("tts_usd_out", 10.0))
    usd = lambda o: round(tin * p_in / 1e6 + o * p_out / 1e6, 4)
    tier = "paid" if paid_tier else "free"
    typ, mx = (usd(tout_typ), usd(tout_max)) if tier == "paid" else (0.0, 0.0)
    return {"model": cfg.get("tts_model") or MODEL, "tier": tier, "words": words, "seconds": round(seconds, 1),
            "requests": pieces, "usd_typical": typ, "usd_max": mx, "warning": FREE_WARNING if tier == "free" else "",
            "label": (f"{pieces} request(s), about {seconds:.0f} s of speech: about ${typ:.4f}, at most ${mx:.4f} (paid tier)"
                      if tier == "paid" else f"{pieces} request(s), about {seconds:.0f} s of speech: free (free tier)")}


def audio_of(answer: dict) -> bytes:
    """The PCM bytes of one answer (every inline audio part, in order)."""
    out = b""
    for c in (answer.get("candidates") or [])[:1]:
        for p in ((c.get("content") or {}).get("parts") or []):
            d = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
            if d:
                out += base64.b64decode(d)
    return out


def plain_error(status: int, free: bool) -> str:
    if status == 429:
        return ("Gemini's free-tier limit for speech was reached: wait (it resets daily) or use a paid-tier key; not retried"
                if free else "Gemini is busy (rate limit): try again in a minute; not retried")
    if status in (401, 403):
        return "Gemini did not accept the API key saved in Settings > Credentials"
    if status == 404:
        return "Gemini does not offer this speech model to this key: check Settings > Narrated shorts"
    if status == 400:
        return "Gemini refused the narration request (HTTP 400): check the voice name and the text; not retried"
    return f"Gemini returned an error (HTTP {status}); not retried"


# ------------------------------------------------------------------ the call
def synthesize(text: str, voice: str, style: str, cfg: dict, out: Path, free: bool = False, log=print) -> dict:
    """One request per piece (never retried); the joined PCM is written to `out` as a WAV. Returns
    {seconds, requests, usage: {input_tokens, output_tokens}}."""
    from .config import get_settings
    if voice not in VOICES:
        raise ValueError(f"the voice must be one of {', '.join(VOICES)}")
    if _transport is None and get_settings().env == "test":
        raise ProviderError("Gemini speech: no network calls in tests (set a test transport)", transient=False)
    key = secret("gemini_api_key")
    if not key:
        raise ProviderNotConfigured("Gemini: save the Gemini API key under Settings > Credentials")
    model = cfg.get("tts_model") or MODEL
    pieces = chunk_text(text)
    if not pieces:
        raise ValueError("there is no narration to read")
    pcm, tin, tout = b"", 0, 0
    with httpx.Client(transport=_transport, timeout=600) as c:
        for i, piece in enumerate(pieces, 1):
            try:
                r = c.post(f"{BASE}/v1beta/models/{model}:generateContent", headers={"x-goog-api-key": key},
                           json=request_body(piece, voice, style))
            except httpx.HTTPError as e:
                raise ProviderError(f"Gemini could not be reached ({type(e).__name__}); not retried", transient=False)
            if r.status_code >= 400:
                raise ProviderError(plain_error(r.status_code, free), transient=False)
            d = r.json() or {}
            got = audio_of(d)
            if not got:
                raise ProviderError("Gemini returned no audio (the answer had no sound in it); not retried", transient=False)
            u = d.get("usageMetadata") or {}
            tin += int(u.get("promptTokenCount") or 0)
            tout += int(u.get("candidatesTokenCount") or 0)
            pcm += (silence(GAP_S) if i > 1 else b"") + got
            log(f"Narration piece {i} of {len(pieces)}: {pcm_seconds(got):.1f} s")
    out.write_bytes(pcm_to_wav(pcm))
    return {"seconds": round(pcm_seconds(pcm), 3), "requests": len(pieces),
            "usage": {"input_tokens": tin, "output_tokens": tout}}


def cost_of(usage: dict, cfg: dict, free: bool) -> float:
    if free:
        return 0.0
    return round(int(usage.get("input_tokens") or 0) * float(cfg.get("tts_usd_in", 0.5)) / 1e6
                 + int(usage.get("output_tokens") or 0) * float(cfg.get("tts_usd_out", 10.0)) / 1e6, 6)


def wav_samples(path: Path) -> tuple[list[int], int]:
    """(mono 16-bit samples, rate) of a WAV written by pcm_to_wav (tests and level checks)."""
    with wave.open(str(path), "rb") as w:
        n, rate, width, ch = w.getnframes(), w.getframerate(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError("only 16-bit WAV is read here")
    vals = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    return list(vals[::ch]), rate
