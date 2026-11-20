"""Casting hints (A), owner decision 2026-11-20: pitch, pace and energy per speaker MEASURED from the audio (editable
suggestions; gender and age are never inferred: the owner sets them), a cast suggestion that says it works from the
transcript text only, and silent reaction characters suggested from names in the transcript (existing characters
selectable)."""
import io
import math
import os
import shutil
import unittest
import wave

import numpy as np
from helpers import Env

from oddstudio import analysis, providers
from oddstudio import voice_traits as VT

WORDS = [  # l1 (0.1-1.2 s) "Who took my charger?"  l2 (2.1-2.6) "Not me."  l3 (2.7-3.3) "I swear."
    {"start": 0.10, "end": 0.30, "word": "Who"}, {"start": 0.32, "end": 0.55, "word": "took"},
    {"start": 0.57, "end": 0.70, "word": "my"}, {"start": 0.72, "end": 1.20, "word": "charger?"},
    {"start": 2.10, "end": 2.30, "word": "Not"}, {"start": 2.32, "end": 2.60, "word": "me."},
    {"start": 2.70, "end": 2.80, "word": "I"}, {"start": 2.82, "end": 3.30, "word": "swear."},
]
TRANSCRIPT = {"provider": "openai", "model": "whisper-1", "language": "en", "duration": 3.6,
              "text": "Who took my charger? Not me. I swear.", "segments": [], "words": WORDS}


def tone(rate, seconds, f0, amp):
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * math.pi * f0 * t)).astype(np.float32)


def two_voices(rate=16000) -> np.ndarray:
    """0.1-1.2 s a low, loud voice (120 Hz); 2.1-3.3 s a high, soft one (250 Hz); silence elsewhere."""
    x = np.zeros(int(rate * 3.6), np.float32)
    x[int(0.1 * rate):int(1.2 * rate)] = tone(rate, 1.1, 120, 0.3)[: int(1.2 * rate) - int(0.1 * rate)]
    x[int(2.1 * rate):int(3.3 * rate)] = tone(rate, 1.2, 250, 0.05)[: int(3.3 * rate) - int(2.1 * rate)]
    return x


def wav_bytes(x: np.ndarray, rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


LINES = [{"id": "l1", "start": 0.1, "end": 1.2, "text": "Who took my charger?", "speaker": "Dan", "words": WORDS[:4]},
         {"id": "l2", "start": 2.1, "end": 2.6, "text": "Not me.", "speaker": "Kim", "words": WORDS[4:6]},
         {"id": "l3", "start": 2.7, "end": 3.3, "text": "I swear.", "speaker": "Kim", "words": WORDS[6:]}]


class MeasureTest(unittest.TestCase):
    """The measurements themselves (no FFmpeg, no server)."""

    def test_pitch_of_a_frame(self):
        for f0 in (110, 180, 260):
            got = VT.frame_f0(tone(16000, 0.04, f0, 0.3))
            self.assertAlmostEqual(got, f0, delta=f0 * 0.05)
        self.assertIsNone(VT.frame_f0(np.zeros(640, np.float32)), "silence has no pitch")

    def test_pitch_pace_and_energy_per_speaker(self):
        t = VT.measure(two_voices(), LINES)
        self.assertEqual(set(t), {"Dan", "Kim"})
        self.assertEqual((t["Dan"]["pitch"], t["Kim"]["pitch"]), ("low", "high"))
        self.assertAlmostEqual(t["Dan"]["pitch_hz"], 120, delta=6)
        self.assertEqual((t["Dan"]["energy"], t["Kim"]["energy"]), ("loud", "soft"))
        self.assertEqual(t["Dan"]["wps"], round(4 / 1.1, 2))
        self.assertEqual(t["Kim"]["pace"], "fast")            # 4 words in 1.1 s
        self.assertNotIn("gender", str(t).lower())
        self.assertNotIn("age", " ".join(t["Dan"]))

    def test_one_speaker_has_medium_energy(self):
        one = [dict(ln, speaker="Dan") for ln in LINES]
        self.assertEqual(VT.measure(two_voices(), one)["Dan"]["energy"], "medium")

    def test_describe(self):
        self.assertEqual(VT.describe({"pitch": "low", "pace": "fast", "energy": "soft"}), "pitch low, pace fast, energy soft")


class CastingHintsTest(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("FFMPEG", "FFPROBE")}
        ff = shutil.which("ffmpeg")
        if ff:
            os.environ["FFMPEG"], os.environ["FFPROBE"] = ff, shutil.which("ffprobe") or ""
        self.env = Env().login()
        self.c = self.env.client
        analysis.set_test_analysis(transcriber=lambda cfg, audio: dict(TRANSCRIPT))

    def tearDown(self):
        analysis.set_test_analysis()
        providers.set_test_text_responder(None)
        self.env.close()
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def ready(self, labels=("Dan", "Kim", "Kim")):
        eid = self.c.post("/api/audio-episodes", json={"title": "Charger", "rights_confirmed": True, "rights_source": "own_recording"}).json()["id"]
        r = self.c.put(f"/api/episodes/{eid}/audio", content=wav_bytes(two_voices()), headers={"Content-Type": "audio/wav"})
        self.assertEqual(r.status_code, 200, r.text)
        self.env.run_jobs(["audio_transcribe"])
        lines = self.c.get(f"/api/episodes/{eid}/audio").json()["lines"]
        for ln, sp in zip(lines, labels):
            ln["speaker"] = sp
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": lines}).status_code, 200)
        return eid

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
    def test_voices_are_measured_from_the_audio(self):
        eid = self.ready()
        r = self.c.post(f"/api/episodes/{eid}/audio/voice-traits")
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["audio_voice_traits"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        vt = self.c.get(f"/api/episodes/{eid}/audio").json()["voice_traits"]
        self.assertEqual(vt["source"], "measured from the audio")
        self.assertEqual((vt["speakers"]["Dan"]["pitch"], vt["speakers"]["Kim"]["pitch"]), ("low", "high"))
        self.assertEqual((vt["speakers"]["Dan"]["energy"], vt["speakers"]["Kim"]["energy"]), ("loud", "soft"))

    def test_measuring_needs_labelled_speakers(self):
        eid = self.ready(labels=("", "", ""))
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/voice-traits").status_code, 409)

    def test_new_characters_take_the_owners_traits_and_age(self):
        eid = self.ready()
        new = lambda key, **kw: {"key": key, "name": key.title(), **kw}
        body = {"speakers": [
            {"label": "Dan", "new": new("dan", voice_traits={"pitch": "low", "pace": "fast", "energy": "loud"}, age_range="30s",
                                        voice_style="dry, flat delivery", bubble_style="him")},
            {"label": "Kim", "new": new("kim")}]}
        r = self.c.post(f"/api/episodes/{eid}/audio/cast", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        chars = {c["key"]: c for c in self.c.get("/api/characters").json()}
        self.assertEqual(chars["dan"]["voice_style"], "pitch low, pace fast, energy loud; age range 30s (set by the owner); dry, flat delivery")
        self.assertEqual(chars["dan"]["bubble_style"], "him", "the owner's choice")
        self.assertEqual(chars["kim"]["voice_style"], "")
        bad = {"speakers": [{"label": "Dan", "new": new("dan2", voice_traits={"pitch": "male"})}]}
        self.assertEqual(self.c.post(f"/api/episodes/{self.ready()}/audio/cast", json=bad).status_code, 422)

    def test_the_suggestion_reads_text_only_and_never_sets_gender_or_age(self):
        seen = {}
        def responder(system, prompt):
            seen["system"], seen["prompt"] = system, prompt
            return {"speakers": [{"label": "Dan", "name": "Dan", "key": "dan", "description": "a nervous accountant",
                                  "visual_description": "short dark hair, grey jumper", "voice_style": "young woman",
                                  "bubble_style": "her"}],
                    "line_speakers": {"l1": "Dan"},
                    "mentioned": [{"name": "charger"}, {"name": "Winifred"}, {"name": "Dan"}]}
        providers.set_test_text_responder(responder)
        eid = self.ready()
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/suggest-cast").status_code, 200)
        self.env.run_jobs(["audio_cast_suggest"])
        s = self.c.get(f"/api/episodes/{eid}/audio").json()["cast_suggestion"]
        self.assertEqual(s["source"], "text")
        self.assertIn("you cannot hear the audio", seen["system"])
        self.assertIn("never guess anyone's gender or age", seen["system"])
        self.assertIn("Do not state or imply gender or age", seen["prompt"])
        sp = s["speakers"][0]
        self.assertEqual(sp["bubble_style"], "neutral", "him/her from the model is dropped")
        self.assertNotIn("voice_style", sp)
        # only names that appear in the transcript and do not already speak
        self.assertEqual(s["mentioned"], [{"name": "charger", "line_ids": ["l1"]}])

    def test_silent_characters_existing_or_new(self):
        eid = self.ready()
        put = lambda members: self.c.put(f"/api/episodes/{eid}/audio/silent-cast", json={"members": members})
        r = put([{"name": "The boss", "character_key": "character-01"},
                 {"name": "Winifred", "new": {"key": "winifred", "name": "Winifred"}}])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["silent_cast"], [{"name": "The boss", "character_key": "character-01"},
                                                  {"name": "Winifred", "character_key": "winifred"}])
        chars = {c["key"]: c for c in self.c.get("/api/characters").json()}
        self.assertEqual((chars["winifred"]["scope"], chars["winifred"]["voice_style"]), ("episode", ""))
        self.assertEqual(put([{"name": "Ghost", "character_key": "nobody"}]).status_code, 422)
        self.assertEqual(put([{"name": "X", "character_key": "character-01", "new": {"key": "x", "name": "X"}}]).status_code, 422)
        self.assertEqual(put([]).json()["silent_cast"], [], "an empty list removes them")
        # a character who already speaks cannot also be silent
        self.c.post(f"/api/episodes/{eid}/audio/cast", json={"speakers": [{"label": "Dan", "character_key": "character-01"},
                                                                          {"label": "Kim", "new": {"key": "kim", "name": "Kim"}}]})
        self.assertEqual(put([{"name": "The boss", "character_key": "character-01"}]).status_code, 422)


if __name__ == "__main__":
    unittest.main()
