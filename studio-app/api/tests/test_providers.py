"""Provider integration: credentials saved in Settings (encrypted, never returned), provider test jobs run by the
worker, fallback providers and automatic retry of transient failures. Provider calls are test stand-ins; the
settings, secrets, queue, worker and retry code are the real code."""
import unittest

from helpers import Env, fake_pose_image, fake_voice

from oddstudio import providers


class ProvidersTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_voice(fake_voice)
        providers.set_test_image(fake_pose_image)
        providers.set_test_text_responder(lambda s, p: {"ok": True, "joke": "the chat muted itself"})

    def tearDown(self):
        providers.set_test_voice(None)
        providers.set_test_image(None)
        providers.set_test_text_responder(None)
        self.env.close()

    def test_credentials_are_write_only_and_used_by_workers(self):
        r = self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-SECRET-123"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("SECRET", r.text)
        page = self.c.get("/api/settings")
        self.assertNotIn("SECRET", page.text)
        self.assertEqual(page.json()["credentials"]["openai_api_key"], {"set": True, "source": "settings"})
        self.assertTrue(page.json()["integrations"]["openai_api_key"])
        from oddstudio.secrets_store import secret
        self.assertEqual(secret("openai_api_key"), "sk-test-SECRET-123")
        from oddstudio.db import new_session
        from oddstudio.models import Setting
        with new_session() as s:   # encrypted at rest
            self.assertNotIn("SECRET", str(s.get(Setting, "_secrets").value))
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": None}})
        self.assertFalse(self.c.get("/api/settings").json()["credentials"]["openai_api_key"]["set"])
        self.assertEqual(self.c.put("/api/settings/credentials", json={"values": {"nope": "x"}}).status_code, 422)

    def test_provider_tests_run_as_worker_jobs(self):
        for target in ("voice:piper", "image:openai", "text:anthropic", "storage:local"):
            self.assertEqual(self.c.post("/api/settings/test", json={"target": target}).status_code, 200)
        self.assertEqual(self.c.post("/api/settings/test", json={"target": "voice:nope"}).status_code, 422)
        ran = self.env.run_jobs(["provider_test"])
        self.assertEqual([x[1] for x in ran], ["succeeded"] * 4, ran)
        tests = self.c.get("/api/settings").json()["tests"]
        self.assertTrue(tests["voice:piper"]["url"])
        self.assertTrue(tests["voice:piper"]["content_type"].startswith("audio"))
        self.assertTrue(tests["image:openai"]["content_type"].startswith("image"))
        self.assertEqual(tests["text:anthropic"]["result"]["answer"]["ok"], True)
        self.assertEqual(self.c.get(tests["voice:piper"]["url"]).status_code, 200)

    def test_unconfigured_provider_test_fails_visibly(self):
        providers.set_test_text_responder(None)
        self.c.post("/api/settings/test", json={"target": "youtube:youtube"})
        ran = self.env.run_jobs(["provider_test"])
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("Not configured", ran[0][2])
        self.assertEqual(self.c.get("/api/settings").json()["tests"]["youtube:youtube"]["status"], "failed")

    def test_fallback_text_provider(self):
        class Broken(providers.TextProvider):
            name = "broken"

            def complete_json(self, system, prompt):
                raise providers.ProviderError("down")

        class Good(providers.TextProvider):
            name = "good"

            def complete_json(self, system, prompt):
                return {"ok": 1}

        notes = []
        providers.set_fallback_logger(notes.append)
        try:
            fb = providers.FallbackText(Broken(), Good())
            self.assertEqual(fb.complete_json("s", "p"), {"ok": 1})
            self.assertEqual(fb.used, "good")
            self.assertIn("fallback good", notes[0])
        finally:
            providers.set_fallback_logger(None)
        self.assertEqual(self.c.put("/api/settings/text", json={"fallback": "nope"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/text", json={"provider": "codex-cli", "fallback": "openai"}).json()["fallback"], "openai")

    def test_anthropic_request_payload(self):
        """Current models reject temperature (HTTP 400 "temperature is deprecated for this model"): never send it to
        them; older models that accept it keep it. The real request is captured at the HTTP layer."""
        A = providers.AnthropicText
        for model in ("", "claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                      "claude-sonnet-5", "claude-haiku-5-5", "claude-fable-5-2", "claude-some-future-model"):
            body = A(model, 0.9).payload("sys", "write")
            self.assertNotIn("temperature", body, model)
            self.assertNotIn("top_p", body); self.assertNotIn("top_k", body)
            self.assertEqual(body["max_tokens"], 16000)
            self.assertEqual(body["model"], model or "claude-sonnet-5-5")
        for model in ("claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"):
            self.assertEqual(A(model, 0.7).payload("s", "p")["temperature"], 0.7, model)

        sent = {}

        class Resp:
            def __init__(self, data, status=200):
                self.status_code, self._d, self.text = status, data, str(data)

            def json(self):
                return self._d

        def fake_post(url, **kw):
            sent.update(url=url, **kw)
            return Resp({"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""},
                                                                 {"type": "text", "text": '{"ok": true}'}]})
        self.c.put("/api/settings/credentials", json={"values": {"anthropic_api_key": "sk-ant-test"}})
        orig = providers.httpx.post
        providers.httpx.post = fake_post
        try:
            self.assertEqual(A("claude-sonnet-5-5").complete_json("sys", "p"), {"ok": True})
            self.assertEqual(sent["url"], "https://api.anthropic.com/v1/messages")
            self.assertNotIn("temperature", sent["json"])
            self.assertEqual(sent["headers"]["x-api-key"], "sk-ant-test")
            providers.httpx.post = lambda url, **kw: Resp({"stop_reason": "refusal", "stop_details": {"category": "cyber"}, "content": []})
            with self.assertRaises(providers.ProviderError):
                A("claude-sonnet-5-5").complete_json("sys", "p")
            providers.httpx.post = lambda url, **kw: Resp({"type": "error"}, 529)
            with self.assertRaises(providers.ProviderError) as cm:
                A("claude-sonnet-5-5").complete_json("sys", "p")
            self.assertTrue(cm.exception.transient)   # overloaded: retried automatically
        finally:
            providers.httpx.post = orig

    def test_capability_registry_and_new_provider_tests(self):
        from oddstudio import analysis
        from helpers import PASSWORD  # noqa: F401
        analysis.set_test_analysis(
            transcriber=lambda cfg, audio: {"provider": cfg["provider"], "model": "m", "text": "Okay. The party is in the other room, and nobody is allowed to know.",
                                            "segments": [{"start": 0, "end": 2, "text": "x"}], "words": [{"start": 0, "end": 0.3, "word": "Okay"}]},
            vision=lambda cfg, images, q: {"figures": 2, "raising": "right"})
        try:
            caps = self.c.get("/api/settings").json()["capabilities"]
            self.assertEqual(set(caps), {"script", "transcription", "vision", "image", "voice", "motion", "lipsync", "sound", "storage", "publishing"})
            # nothing is verified before a real test; unintegrated providers are marked and cannot be selected
            self.assertFalse(any(p["verified"] for c in caps.values() for p in c["providers"].values()))
            self.assertFalse(caps["motion"]["providers"]["runway"]["implemented"])
            r = self.c.put("/api/settings/motion", json={"provider": "runway"})
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn("not integrated", r.text)
            self.assertEqual(self.c.put("/api/settings/transcription", json={"provider": "local-whisper", "fallback": "openai"}).status_code, 200)
            for t in ("transcription:openai", "vision:anthropic"):
                self.assertEqual(self.c.post("/api/settings/test", json={"target": t}).status_code, 200)
            ran = self.env.run_jobs(["provider_test"])
            self.assertEqual([x[1] for x in ran], ["succeeded", "succeeded"], ran)
            caps = self.c.get("/api/settings").json()["capabilities"]
            self.assertTrue(caps["transcription"]["providers"]["openai"]["verified"])
            self.assertTrue(caps["vision"]["providers"]["anthropic"]["verified"])
            self.assertFalse(caps["vision"]["providers"]["openai"]["verified"])
            # a transcript that does not match the spoken line fails the test (a key check alone never passes)
            analysis.set_test_analysis(transcriber=lambda cfg, audio: {"provider": "openai", "model": "m", "text": "something else entirely", "segments": [], "words": []})
            self.c.post("/api/settings/test", json={"target": "transcription:openai"})
            ran = self.env.run_jobs(["provider_test"])
            self.assertEqual(ran[0][1], "failed")
            self.assertFalse(self.c.get("/api/settings").json()["capabilities"]["transcription"]["providers"]["openai"]["verified"])
        finally:
            analysis.set_test_analysis()

    def test_fal_budget_and_confirmation(self):
        """Paid generation never starts without a key, an estimate and confirmation, and never exceeds the budget."""
        from oddstudio import fal
        self.assertEqual(fal.estimate("wan-2.2-a14b", {}), 0.405)          # $0.08/s x 81 frames / 16 fps
        self.assertEqual(fal.estimate("ltx-2-19b", {}), 0.2016)            # 112 MP x $0.0018
        plan = self.c.post("/api/motion/compare", json={"confirm": False}).json()
        self.assertFalse(plan["key_configured"])
        self.assertAlmostEqual(plan["estimated_total_usd"], 1.51, places=2)
        self.assertEqual(self.c.post("/api/motion/compare", json={"confirm": True}).status_code, 409)   # no key
        self.c.put("/api/settings/credentials", json={"values": {"fal_key": "fal-test"}})
        self.c.put("/api/settings/motion", json={"budget_usd": 1.0})
        r = self.c.post("/api/motion/compare", json={"confirm": True})
        self.assertEqual(r.status_code, 409, r.text)                                                  # over budget
        from oddstudio.db import new_session
        with new_session() as s:
            fal.reserve(s, "wan-2.2-5b", 0.15, "t")
            with self.assertRaises(providers.ProviderError):
                fal.reserve(s, "wan-2.2-a14b", 0.9, "t")                  # 0.15 + 0.9 > 1.0
            self.assertEqual(fal.spent(s)["total"], 0.15)
        r = self.c.post("/api/motion/compare", json={"confirm": True, "models": ["wan-2.2-5b"], "attempts": 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["job"]["kind"], "motion_compare")

    def test_set_candidates_need_approval(self):
        """A generated set is a candidate until the owner approves it; only then can the writer pick it."""
        def fake_plate(prompt, out_file, reference):
            from PIL import Image
            Image.new("RGB", (1024, 1536), (200, 150, 100)).save(out_file)
            return out_file
        providers.set_test_image(fake_plate)
        r = self.c.post("/api/sets/generate", json={"label": "Office", "description": "a small cozy open-plan office"})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["set_candidate"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        s = self.c.get("/api/sets").json()["sets"][0]
        self.assertEqual((s["id"], s["status"], s["width"], s["height"]), ("office", "candidate", 1024, 1536))
        self.assertTrue(s["url"] and s["preview_url"])
        from oddstudio import sets
        from oddstudio.db import new_session
        self.c.put("/api/settings/motion", json={"provider": "procedural-rig"})
        with new_session() as db:
            self.assertNotIn("office", sets.writer_environments(db))          # not before approval
        r = self.c.post("/api/sets/office/decide", json={"decision": "approve", "blocking": {"floor_y": 1300}})
        self.assertEqual(r.json()["status"], "approved")
        with new_session() as db:
            self.assertIn("office", sets.writer_environments(db))
            self.assertEqual(sets.approved(db)["office"]["blocking"]["floor_y"], 1300)
        self.c.put("/api/settings/motion", json={"provider": "none"})
        with new_session() as db:
            self.assertNotIn("office", sets.writer_environments(db))          # pose engine cannot stage it

    def test_transient_failures_retry_automatically(self):
        from oddstudio import tasks
        calls = []

        @tasks.task
        def flaky_test_task(ctx):
            calls.append(1)
            if len(calls) < 3:
                raise providers.ProviderError("openai: HTTP 429: slow down", transient=True)
            return {"ok": True}

        @tasks.task
        def broken_test_task(ctx):
            raise providers.ProviderError("openai: HTTP 400: bad request")

        from oddstudio.db import new_session
        from oddstudio.models import Job
        from oddstudio.queue import enqueue
        with new_session() as s:
            a = enqueue(s, "flaky_test_task").id
            b = enqueue(s, "broken_test_task").id
        self.env.run_jobs(["flaky_test_task", "broken_test_task"])
        with new_session() as s:
            ja, jb = s.get(Job, a), s.get(Job, b)
            self.assertEqual((ja.status, ja.attempts), ("succeeded", 3))
            self.assertIn("Retrying automatically", ja.log)
            self.assertEqual((jb.status, jb.attempts), ("failed", 1))   # not transient: no automatic retry
        tasks.TASKS.pop("flaky_test_task"); tasks.TASKS.pop("broken_test_task")


if __name__ == "__main__":
    unittest.main()
