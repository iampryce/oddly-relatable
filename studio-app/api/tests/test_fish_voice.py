"""Fish Audio voice provider: request shape, key handling (Settings first, FISH_API_KEY as fallback, never in errors),
retries, the clip cache, per-character voice and speed, and the worker's provider test. HTTP is mocked: these tests
make no network calls."""
import io
import os
import unittest
import wave
from pathlib import Path
from unittest import mock

from helpers import Env

from oddstudio import providers, secrets_store

KEY = "fish-test-KEY-0123456789abcdef"


def wav_bytes(seconds=1.0, rate=44100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class Resp:
    def __init__(self, status=200, content=b"", text="", payload=None):
        self.status_code, self.content, self.text, self._payload = status, content, text, payload
        self.headers = {"content-type": "audio/wav" if content.startswith(b"RIFF") else "application/json"}

    def json(self):
        return self._payload


class FishVoiceTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FISH_API_KEY", None)
        secrets_store._cache = None
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_voice(None)          # the real provider code runs; only HTTP is replaced
        self.sleeps = []
        self._sleep = providers._sleep
        providers._sleep = self.sleeps.append
        self.calls = []
        self.answers = []
        p = mock.patch("oddstudio.providers.httpx.post", side_effect=self._post)
        p.start()
        self.addCleanup(p.stop)
        self.out = self.env.tmp / "out" / "line-1"

    def tearDown(self):
        providers._sleep = self._sleep
        os.environ.pop("FISH_API_KEY", None)
        secrets_store._cache = None
        self.env.close()

    def _post(self, url, headers=None, json=None, timeout=None, **kw):
        self.calls.append({"url": url, "headers": headers, "json": json})
        a = self.answers.pop(0) if self.answers else Resp(200, wav_bytes())
        if isinstance(a, Exception):
            raise a
        return a

    def save_key(self):
        r = self.c.put("/api/settings/credentials", json={"values": {"fish_api_key": KEY}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(KEY, r.text)

    # ------------------------------------------------------------------ request
    def test_request_shape_default_model_and_wav_output(self):
        self.save_key()
        f = providers.speak({"provider": "fish"}, "Wait. [laughing] You did WHAT?", "voice123", self.out, "ignored direction", speed=1.2)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["url"], "https://api.fish.audio/v1/tts")
        self.assertEqual(call["headers"], {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "model": "s2-pro"})
        self.assertEqual(call["json"], {"text": "Wait. [laughing] You did WHAT?", "reference_id": "voice123", "format": "wav",
                                        "sample_rate": 44100, "latency": "normal", "prosody": {"speed": 1.2}})
        self.assertEqual(f.suffix, ".wav")
        self.assertTrue(f.read_bytes().startswith(b"RIFF"))
        self.assertAlmostEqual(providers.audio_seconds(f), 1.0, places=2)

    def test_model_field_overrides_default_and_character_prefix_selects_fish(self):
        self.save_key()
        providers.speak({"provider": "fish", "model": "s2.1-pro-free"}, "One.", "v1", self.out)
        self.assertEqual(self.calls[-1]["headers"]["model"], "s2.1-pro-free")
        self.assertEqual(self.calls[-1]["json"]["prosody"], {"speed": 1.0})
        # a character voice "fish:<id>" uses Fish even when another provider is selected (that provider's model is not sent)
        providers.speak({"provider": "kokoro", "model": "kokoro-model"}, "Two.", "fish:v2", self.out)
        self.assertEqual(self.calls[-1]["headers"]["model"], "s2-pro")
        self.assertEqual(self.calls[-1]["json"]["reference_id"], "v2")

    # ------------------------------------------------------------------ routing (owner decision 2026-11-20)
    def test_bare_path_voices_use_piper_whatever_the_provider(self):
        routed = []

        def fake_one(cfg, text, voice, out_file, instructions="", speed=None):
            routed.append((cfg["provider"], cfg.get("model", ""), voice))
            return out_file.with_suffix(".wav")

        with mock.patch.object(providers, "_speak_one", side_effect=fake_one):
            for v in ("C:/Users/PC/Desktop/studio-work/voices/en_US-lessac-medium.onnx",   # the server's stored values
                      "voices\\en_GB-alan-medium.onnx", "/app/voices/en_US-joe-medium.onnx", "en_US-ryan-medium.onnx"):
                providers.speak({"provider": "fish", "model": "s2.1-pro-free", "fallback": "none"}, "Hi.", v, self.out)
            providers.speak({"provider": "piper", "model": "m"}, "Hi.", "voices/x.onnx", self.out)          # piper keeps its model
            providers.speak({"provider": "fish", "model": "s2.1-pro-free"}, "Hi.", "fish:abc_123-X", self.out)
            providers.speak({"provider": "fish", "model": "s2.1-pro-free"}, "Hi.", "abc123", self.out)          # bare id: selected provider
        self.assertEqual([r[0] for r in routed], ["piper"] * 5 + ["fish", "fish"])
        self.assertEqual(routed[0], ("piper", "", "C:/Users/PC/Desktop/studio-work/voices/en_US-lessac-medium.onnx"))
        self.assertEqual(routed[4][1], "m")
        self.assertEqual(routed[5], ("fish", "s2.1-pro-free", "abc_123-X"))
        self.assertEqual(self.calls, [])

    def test_invalid_fish_id_is_a_clear_error_without_a_request(self):
        self.save_key()
        for bad in ("fish:not a voice!", "fish:" + "x" * 129, "fish:voice.id"):
            with self.assertRaises(providers.ProviderNotConfigured) as e:
                providers.speak({"provider": "kokoro"}, "Hi.", bad, self.out)
            self.assertIn("is not a Fish voice id", str(e.exception))
            self.assertIn("fish:<voice id>", str(e.exception))
        with self.assertRaises(providers.ProviderNotConfigured):
            providers.speak({"provider": "fish", "default_voice": "Ben's voice"}, "Hi.", "", self.out)
        self.assertEqual(self.calls, [])

    def test_scene_with_old_piper_voice_no_longer_reaches_fish(self):
        """Episode 5's failure: Fish selected, a character still on a bare Piper path."""
        self.save_key()
        self.c.put("/api/settings/voice", json={"provider": "fish", "model": "s2.1-pro-free"})
        ch = self.char01()
        self.c.put(f"/api/characters/{ch['id']}", json={**self.char_body(ch), "voice": "C:/Users/PC/voices/en_US-lessac-medium.onnx"})
        self.c.post(f"/api/characters/{ch['id']}/voice/preview", json={})
        ran = self.env.run_jobs(["voice_preview"])
        self.assertEqual(self.calls, [], "the path was not sent to Fish")
        if ran[0][1] == "failed":   # no Piper on this machine: the error names Piper, not a Fish HTTP 400
            self.assertIn("piper", ran[0][2].lower())

    # ------------------------------------------------------------------ keys
    def test_missing_key_is_not_configured(self):
        with self.assertRaises(providers.ProviderNotConfigured) as e:
            providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        self.assertIn("FISH_API_KEY", str(e.exception))
        self.assertEqual(self.calls, [])

    def test_environment_key_is_the_fallback(self):
        os.environ["FISH_API_KEY"] = "env-" + KEY
        secrets_store._cache = None
        providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        self.assertEqual(self.calls[0]["headers"]["Authorization"], f"Bearer env-{KEY}")
        self.save_key()                         # a key saved in Settings wins over the environment
        providers.speak({"provider": "fish"}, "Hi again.", "v1", self.out)
        self.assertEqual(self.calls[1]["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(self.c.get("/api/settings").json()["credentials"]["fish_api_key"], {"set": True, "source": "settings"})

    def test_key_never_appears_in_errors(self):
        self.save_key()
        self.answers = [Resp(400, text=f'{{"message": "bad request", "echo": "Authorization: Bearer {KEY}", "key": "{KEY}"}}')]
        with self.assertRaises(providers.ProviderError) as e:
            providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        self.assertNotIn(KEY, str(e.exception))
        self.assertIn("HTTP 400", str(e.exception))
        self.assertFalse(e.exception.transient)
        self.answers = [Resp(401, text=f"invalid token {KEY}")]
        with self.assertRaises(providers.ProviderError) as e:
            providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        self.assertIn("rejected", str(e.exception))
        self.assertNotIn(KEY, str(e.exception))
        self.answers = [Resp(402, text="no credit")]
        with self.assertRaises(providers.ProviderError) as e:
            providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        self.assertIn("no API credit", str(e.exception))
        self.assertEqual(len(self.calls), 3)    # 400 / 401 / 402 are not retried

    # ------------------------------------------------------------------ retries
    def test_429_and_5xx_are_retried_at_most_twice(self):
        self.save_key()
        self.answers = [Resp(429, text="slow down"), Resp(503, text="busy"), Resp(200, wav_bytes())]
        f = providers.speak({"provider": "fish"}, "Retry me.", "v1", self.out)
        self.assertTrue(f.exists())
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.sleeps, [1.0, 3.0])
        self.calls.clear()
        self.answers = [Resp(500, text=f"oops {KEY}")] * 4
        with self.assertRaises(providers.ProviderError) as e:
            providers.speak({"provider": "fish"}, "Still failing.", "v1", self.out)
        self.assertEqual(len(self.calls), 3)    # one try plus two retries
        self.assertTrue(e.exception.transient)  # the job queue may retry the whole job later
        self.assertNotIn(KEY, str(e.exception))

    def test_network_errors_are_retried(self):
        import httpx
        self.save_key()
        self.answers = [httpx.ConnectError("connection reset"), Resp(200, wav_bytes())]
        providers.speak({"provider": "fish"}, "Flaky network.", "v1", self.out)
        self.assertEqual(len(self.calls), 2)

    def test_non_audio_answer_is_an_error(self):
        self.save_key()
        self.answers = [Resp(200, content=b'{"status": "ok"}')]
        with self.assertRaises(providers.ProviderError):
            providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)

    def test_wav_that_is_not_16_bit_pcm_is_converted_or_refused(self):
        self.save_key()
        bad = bytearray(wav_bytes())
        bad[20:22] = (3).to_bytes(2, "little")  # WAVE_FORMAT_IEEE_FLOAT: Rhubarb's reader would not take it as is
        self.answers = [Resp(200, bytes(bad))]
        from oddstudio.config import get_settings
        if get_settings().ffmpeg:
            self.skipTest("FFmpeg is installed here: the refusal path applies only without it")
        with self.assertRaises(providers.ProviderError) as e:
            providers.speak({"provider": "fish"}, "Float audio.", "v1", self.out)
        self.assertIn("16-bit PCM", str(e.exception))
        self.assertEqual(list((self.env.tmp / "work" / "voice-cache" / "fish").glob("*")), [])   # nothing half-written cached

    # ------------------------------------------------------------------ cache
    def test_clip_cache_hit_and_miss(self):
        self.save_key()
        a = providers.speak({"provider": "fish"}, "Same line.", "v1", self.out, speed=1.1)
        b = providers.speak({"provider": "fish"}, "Same line.", "v1", self.env.tmp / "out" / "line-2", speed=1.1)
        self.assertEqual(len(self.calls), 1, "identical model, voice, speed, rate and text: served from the cache")
        self.assertEqual(a.read_bytes(), b.read_bytes())
        providers.speak({"provider": "fish"}, "Same line.", "v1", self.out, speed=1.2)                  # speed changed
        providers.speak({"provider": "fish"}, "Other line.", "v1", self.out, speed=1.1)                 # text changed
        providers.speak({"provider": "fish"}, "Same line.", "v2", self.out, speed=1.1)                  # voice changed
        providers.speak({"provider": "fish", "model": "s2.1-pro-free"}, "Same line.", "v1", self.out, speed=1.1)  # model changed
        self.assertEqual(len(self.calls), 5)
        cache = self.env.tmp / "work" / "voice-cache" / "fish"
        self.assertEqual(len(list(cache.glob("*.wav"))), 5)
        self.assertEqual(list(cache.glob("*.part")), [])

    def test_failed_request_is_not_cached(self):
        self.save_key()
        self.answers = [Resp(400, text="bad")]
        with self.assertRaises(providers.ProviderError):
            providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        providers.speak({"provider": "fish"}, "Hi.", "v1", self.out)
        self.assertEqual(len(self.calls), 2)

    # ------------------------------------------------------------------ settings, characters, worker
    def test_settings_accept_fish_and_validate_speed(self):
        r = self.c.put("/api/settings/voice", json={"provider": "fish", "model": "s2.1-pro-free", "fallback": "piper"})
        self.assertEqual(r.status_code, 200, r.text)
        caps = self.c.get("/api/settings").json()["capabilities"]["voice"]["providers"]["fish"]
        self.assertEqual((caps["label"], caps["default_model"], caps["configured"]), ("Fish Audio", "s2-pro", False))
        self.save_key()
        self.assertTrue(self.c.get("/api/settings").json()["capabilities"]["voice"]["providers"]["fish"]["configured"])
        ch = self.char01()
        self.assertEqual(self.c.put(f"/api/characters/{ch['id']}", json={**self.char_body(ch), "voice_speed": 3}).status_code, 422)

    def char01(self):
        return next(c for c in self.c.get("/api/characters").json() if c["key"] == "character-01")

    @staticmethod
    def char_body(ch):
        return {k: ch[k] for k in ("key", "name", "description", "visual_description", "bubble_style", "scope", "episode_id",
                                   "default_expression", "voice", "voice_style")}

    def test_character_voice_and_speed_reach_the_request(self):
        self.save_key()
        ch = self.char01()
        r = self.c.put(f"/api/characters/{ch['id']}", json={**self.char_body(ch), "voice": "fish:charvoice", "voice_speed": 0.9})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["voice"], r.json()["voice_speed"]), ("fish:charvoice", 0.9))
        self.c.put("/api/settings/voice", json={"provider": "piper"})
        self.assertEqual(self.c.post(f"/api/characters/{ch['id']}/voice/preview", json={}).status_code, 200)
        ran = self.env.run_jobs(["voice_preview"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(self.calls[0]["json"]["reference_id"], "charvoice")
        self.assertEqual(self.calls[0]["json"]["prosody"], {"speed": 0.9})

    def test_fish_as_fallback_uses_the_fish_default_voice(self):
        self.save_key()
        f = providers.speak({"provider": "openai", "fallback": "fish", "fish_default_voice": "fish:fbvoice"}, "Hi.", "alloy", self.out)
        self.assertTrue(f.exists())             # openai has no key: Fish took over
        self.assertEqual(self.calls[0]["json"]["reference_id"], "fbvoice")

    def test_worker_provider_test_checks_credit_then_voices_a_character(self):
        self.save_key()
        ch = self.char01()
        self.c.put(f"/api/characters/{ch['id']}", json={**self.char_body(ch), "voice": "fish:charvoice", "voice_speed": 1.1})
        gets = []

        def fake_get(url, headers=None, timeout=None, **kw):
            gets.append((url, headers))
            return Resp(200, payload={"credit": "12.50", "has_free_credit": False})

        with mock.patch("oddstudio.providers.httpx.get", side_effect=fake_get):
            self.assertEqual(self.c.post("/api/settings/test", json={"target": "voice:fish"}).status_code, 200)
            ran = self.env.run_jobs(["provider_test"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(gets, [("https://api.fish.audio/wallet/self/api-credit", {"Authorization": f"Bearer {KEY}"})])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["headers"]["model"], "s2-pro")
        self.assertEqual(self.calls[0]["json"]["prosody"], {"speed": 1.1})
        t = self.c.get("/api/settings").json()["tests"]["voice:fish"]
        self.assertEqual(t["status"], "succeeded")
        self.assertEqual((t["result"]["credit"], t["result"]["voice"], t["result"]["seconds"]), ("12.50", "charvoice", 1.0))
        self.assertEqual(t["result"]["model"], "s2-pro")
        # a second test calls the API again (the clip cache is bypassed), with the Model field once Fish is selected
        self.c.put("/api/settings/voice", json={"provider": "fish", "model": "s2.1-pro-free"})
        with mock.patch("oddstudio.providers.httpx.get", side_effect=fake_get):
            self.c.post("/api/settings/test", json={"target": "voice:fish"})
            self.assertEqual(self.env.run_jobs(["provider_test"])[0][1], "succeeded")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1]["headers"]["model"], "s2.1-pro-free")
        self.assertTrue(t["content_type"].startswith("audio"))
        self.assertNotIn(KEY, self.c.get("/api/settings").text)

    def test_worker_provider_test_without_any_fish_voice_fails_before_spending(self):
        self.save_key()
        with mock.patch("oddstudio.providers.httpx.get") as g:
            self.c.post("/api/settings/test", json={"target": "voice:fish"})
            ran = self.env.run_jobs(["provider_test"])
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("Fish voice", ran[0][2])
        g.assert_not_called()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
