"""Guided generation (2026-11-26): the step list, the private reference video, the acting analysis (Gemini over HTTP,
mocked with httpx.MockTransport: no network, no cost) and the prompt writer (the OpenAI SDK over a mocked transport).
Paid starts are refused with HTTP 409 unless they carry the confirmed cost. Only fake credentials are used."""
import json
import unittest

import httpx

from helpers import Env

from oddstudio import acting_analysis as AA
from oddstudio import prompt_writer as PW

FAKE_GEMINI = "fake-gemini-credential-for-tests"
FAKE_OPENAI = "fake-openai-credential-for-tests"
SHOTS = [{"index": i, "t0": (i - 1) * 3.0, "t1": i * 3.0, "people": []} for i in range(1, 7)]


# ------------------------------------------------------------------ pure parts
class PureTest(unittest.TestCase):
    def test_batches_are_contiguous_and_padded(self):
        shots = [{"shot": i, "start": (i - 1) * 2.0, "end": i * 2.0} for i in range(1, 8)]
        b = AA.make_batches(shots)
        self.assertEqual([(x["a"], x["b"]) for x in b], [(1, 3), (4, 5), (6, 7)])
        self.assertEqual((b[0]["lo"], b[0]["hi"]), (0.0, 7.0))
        self.assertEqual((b[1]["lo"], b[1]["hi"]), (5.0, 11.0))
        self.assertEqual(len(AA.make_batches(shots[:2])), 2)
        self.assertEqual(AA.make_batches([]), [])

    def test_normalise_oddities(self):
        bare = AA.normalise([{"shot": 1, "beats": []}, {"shot": 2, "beats": []}])
        self.assertEqual([s["shot"] for s in bare["shots"]], [1, 2])
        wrapped = AA.normalise([{"characters": {"Ann": {"traits": "calm"}}, "shots": [{"shot": 3}], "talking_style": {"Ann": "slow"}}])
        self.assertEqual(wrapped["characters"]["Ann"]["traits"], "calm")
        self.assertEqual(wrapped["talking_style"], {"Ann": "slow"})
        self.assertEqual(wrapped["shots"], [{"shot": 3}])
        plain = AA.normalise({"characters": {}, "shots": [{"shot": 4}], "talking_style": {}})
        self.assertEqual(plain["shots"], [{"shot": 4}])
        self.assertEqual(AA.normalise("nonsense")["shots"], [])

    def test_merge_keeps_first_answer_per_shot(self):
        r = {"characters": {}, "shots": [], "talking_style": {}}
        AA.merge(r, AA.normalise([{"shot": 2, "x": 1}]))
        AA.merge(r, AA.normalise([{"shot": 1}, {"shot": 2, "x": 2}]))
        self.assertEqual([(s["shot"], s.get("x")) for s in r["shots"]], [(1, None), (2, 1)])

    def test_estimate_video_tokens_and_output_cap(self):
        cfg = {"acting_model": "m", "acting_usd_in": 2.0, "acting_usd_out": 12.0}
        shots = [{"shot": i, "start": (i - 1) * 10.0, "end": i * 10.0} for i in range(1, 4)]
        e = AA.estimate(shots, ["Ann"], cfg)
        self.assertEqual(e["batches"], 3)
        self.assertEqual(e["video_seconds"], 35.0)            # 0-11, 9-21, 19-31: 1 s padding each side, clipped at 0
        self.assertGreaterEqual(e["input_tokens"], 35 * 300)
        self.assertEqual(e["max_output_tokens"], 90000)
        self.assertAlmostEqual(e["usd_max"], round(e["input_tokens"] * 2 / 1e6 + 90000 * 12 / 1e6, 4))
        self.assertLess(e["usd_typical"], e["usd_max"])

    def test_request_body(self):
        b = AA.request_body("files/abc-uri", "video/mp4", {"lo": 2.0, "hi": 9.5}, "p")
        part = b["contents"][0]["parts"][0]
        self.assertEqual(part["video_metadata"], {"fps": 5, "start_offset": "2.0s", "end_offset": "9.5s"})
        g = b["generationConfig"]
        self.assertEqual((g["responseMimeType"], g["temperature"], g["maxOutputTokens"]), ("application/json", 0.4, 30000))
        self.assertEqual(g["thinkingConfig"], {"thinkingLevel": "low"})

    def test_prompt_writer_estimate_and_message(self):
        cfg = {"prompt_model": "gpt-5.5", "prompt_usd_in": 5.0, "prompt_usd_out": 30.0, "prompt_max_tokens": 4000}
        msg = PW.user_message("face_edit", "STYLE", "Ann. Round glasses.", "she gasps", "")
        self.assertIn("FACE-ONLY EDIT", msg)
        self.assertIn("STYLE", msg)
        self.assertIn("Round glasses", msg)
        e = PW.estimate(cfg, "sys", msg)
        self.assertEqual(e["usd_max"], round(e["input_tokens"] * 5 / 1e6 + 4000 * 30 / 1e6, 4))

    def test_acting_for_shot_filters_by_character(self):
        analysis = {"shots": [{"shot": 2, "what_the_reference_shows": "two people", "beats": [
            {"t_start": 1, "t_end": 2, "character": "Ann", "on_word": "no", "expression": "eyes wide"},
            {"t_start": 1, "t_end": 2, "character": "Bob", "expression": "smirk"}]}], "talking_style": {"Ann": "fast"}}
        text = PW.acting_for_shot(analysis, 2, "Ann")
        self.assertIn("eyes wide", text)
        self.assertNotIn("smirk", text)
        self.assertIn("Talking style: fast", text)
        self.assertEqual(PW.acting_for_shot(analysis, 9, "Ann"), "")


# ------------------------------------------------------------------ API with mocked HTTP
class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Episode, Setting
        from oddstudio.secrets_store import put_secrets
        with new_session() as db:
            ep = Episode(title="Guided")
            db.add(ep)
            db.commit()
            self.eid = ep.id
            db.add(Setting(key=f"shotframes:{ep.id}", value={"shots": SHOTS}))
            db.commit()
            put_secrets(db, {"gemini_api_key": FAKE_GEMINI, "openai_api_key": FAKE_OPENAI})

    def tearDown(self):
        AA.set_test_transport(None)
        PW.set_test_http_client(None)
        self.env.close()

    def upload_video(self):
        r = self.c.put(f"/api/episodes/{self.eid}/guide/reference-video", content=b"\x00\x00\x00\x18ftypmp42fake-video",
                       headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class GuideTest(Base):
    def test_steps_and_private_reference_video(self):
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()
        self.assertEqual(len(g["steps"]), 11)
        self.assertEqual(g["steps"]["upload"]["detail"], "0 of 3 uploaded")
        for k in ("closeups", "faces", "movement", "quality", "assembly"):
            self.assertFalse(g["steps"][k]["available"])
        self.assertTrue(g["steps"]["talking"]["available"])          # step 9 is in the dashboard (talking_s2v.py)
        self.assertEqual(list(g["steps"])[8], "talking")
        self.assertEqual(g["keys"], {"gemini": True, "openai": True})
        g = self.upload_video()
        ref = g["steps"]["upload"]["items"]["reference_video"]
        self.assertTrue(ref and "/api/media/private/episodes/" in ref["url"])
        self.assertNotIn("key", ref)
        self.assertIsNotNone(g["steps"]["acting"]["cost"])
        self.assertNotIn(FAKE_GEMINI, json.dumps(g))
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/guide/reference-video", content=b"x",
                                    headers={"Content-Type": "text/plain"}).status_code, 415)
        g = self.c.delete(f"/api/episodes/{self.eid}/guide/reference-video").json()
        self.assertIsNone(g["steps"]["upload"]["items"]["reference_video"])

    def test_guide_settings_validation(self):
        r = self.c.put("/api/settings/guide", json={"prompt_model": "gpt 5; rm"})
        self.assertEqual(r.status_code, 422, r.text)
        r = self.c.put("/api/settings/guide", json={"prompt_model": "gpt-5.5-mini", "prompt_usd_in": 1.0})
        self.assertEqual(r.status_code, 200, r.text)


class GeminiFake:
    """The Files API and generateContent, as seen over HTTP. answers: one per generateContent call (status, json)."""

    def __init__(self, answers):
        self.answers, self.calls, self.deleted, self.keys = list(answers), [], [], set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.keys.add(request.headers.get("x-goog-api-key"))
        url = str(request.url)
        if url.endswith("/upload/v1beta/files"):
            return httpx.Response(200, headers={"x-goog-upload-url": "https://upload.example/session/1"}, json={})
        if url.startswith("https://upload.example/session/1"):
            assert request.headers["X-Goog-Upload-Command"] == "upload, finalize"
            return httpx.Response(200, json={"file": {"name": "files/abc", "uri": "https://g.example/files/abc", "state": "PROCESSING"}})
        if url.endswith("/v1beta/files/abc") and request.method == "GET":
            return httpx.Response(200, json={"name": "files/abc", "uri": "https://g.example/files/abc", "state": "ACTIVE"})
        if url.endswith("/v1beta/files/abc") and request.method == "DELETE":
            self.deleted.append("files/abc")
            return httpx.Response(200, json={})
        if ":generateContent" in url:
            model = url.split("/models/")[1].split(":")[0]
            self.calls.append((model, json.loads(request.content)))
            status, body = self.answers.pop(0)
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={})


def gem_answer(obj, tin=1000, tout=500):
    return (200, {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": json.dumps(obj)}]}}],
                  "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout, "thoughtsTokenCount": 100}})


class ActingAnalysisTest(Base):
    def start(self, **kw):
        return self.c.post(f"/api/episodes/{self.eid}/acting-analysis", json=kw)

    def test_confirm_usd_rule_409(self):
        self.upload_video()
        est = self.c.get(f"/api/episodes/{self.eid}/acting-analysis").json()["estimate"]
        self.assertEqual(self.start().status_code, 409)
        r = self.start(confirm_usd=round(est["usd_max"] - 0.01, 2))
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm", r.json()["detail"])
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as db:
            self.assertEqual(db.query(Job).filter_by(kind="acting_analysis").count(), 0)

    def test_needs_reference_video(self):
        r = self.start(confirm_usd=10)
        self.assertEqual(r.status_code, 409)
        self.assertIn("reference video", r.json()["detail"])

    def test_full_run_merges_batches_and_deletes_upload(self):
        self.upload_video()
        fake = GeminiFake([
            gem_answer({"characters": {"Ann": {"traits": "dry"}}, "shots": [{"shot": 1, "beats": [], "key_frame_times": [1.0]},
                                                                           {"shot": 2, "beats": []}],
                        "talking_style": {"Ann": "slow"}}),
            gem_answer([{"shot": 3, "beats": []}, {"shot": 4, "beats": []}]),                    # a bare list
            gem_answer([{"characters": {}, "shots": [{"shot": 5}, {"shot": 6}], "talking_style": {}}]),   # a wrapped object
        ])
        AA.set_test_transport(httpx.MockTransport(fake))
        est = self.c.get(f"/api/episodes/{self.eid}/acting-analysis").json()["estimate"]
        r = self.start(confirm_usd=est["usd_max"])
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["acting_analysis"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual({m for m, _ in fake.calls}, {"gemini-3.1-pro-preview"})
        offsets = [b["contents"][0]["parts"][0]["video_metadata"] for _, b in fake.calls]
        self.assertEqual(offsets[0], {"fps": 5, "start_offset": "0.0s", "end_offset": "7.0s"})
        self.assertEqual(fake.deleted, ["files/abc"])
        self.assertEqual(fake.keys - {None}, {FAKE_GEMINI})
        v = self.c.get(f"/api/episodes/{self.eid}/acting-analysis").json()
        self.assertEqual([s["shot"] for s in v["result"]["shots"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(v["result"]["talking_style"], {"Ann": "slow"})
        self.assertEqual(v["usage"], {"input_tokens": 3000, "output_tokens": 1800})
        self.assertAlmostEqual(v["usd"], round(3000 * 2 / 1e6 + 1800 * 12 / 1e6, 4))
        self.assertFalse(v["accepted"])
        self.assertNotIn(FAKE_GEMINI, json.dumps(v))
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()
        self.assertEqual(g["steps"]["acting"]["status"], "needs_approval")
        self.c.post(f"/api/episodes/{self.eid}/acting-analysis/accept")
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["acting"]["status"], "done")
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as db:
            self.assertNotIn(FAKE_GEMINI, db.query(Job).filter_by(kind="acting_analysis").one().log)

    def test_free_tier_only_when_ticked(self):
        self.upload_video()
        busy = (429, {"error": {"code": 429}})
        est = self.c.get(f"/api/episodes/{self.eid}/acting-analysis").json()["estimate"]
        fake = GeminiFake([busy])
        AA.set_test_transport(httpx.MockTransport(fake))
        self.assertEqual(self.start(confirm_usd=est["usd_max"]).status_code, 200)
        ran = self.env.run_jobs(["acting_analysis"])
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("quota", ran[0][2])
        self.assertEqual([m for m, _ in fake.calls], ["gemini-3.1-pro-preview"])
        self.assertEqual(fake.deleted, ["files/abc"], "the upload is deleted even when the analysis fails")

        ok = [{"shot": i} for i in range(1, 7)]
        fake = GeminiFake([busy, gem_answer(ok[:2]), gem_answer(ok[2:4]), gem_answer(ok[4:])])
        AA.set_test_transport(httpx.MockTransport(fake))
        self.assertEqual(self.start(confirm_usd=est["usd_max"], use_free_tier=True).status_code, 200)
        ran = self.env.run_jobs(["acting_analysis"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual([m for m, _ in fake.calls][:2], ["gemini-3.1-pro-preview", "gemini-3.5-flash"])
        v = self.c.get(f"/api/episodes/{self.eid}/acting-analysis").json()
        self.assertIn("gemini-3.5-flash", v["model_used"])


def openai_response(text="A tall stick man gasps, eyes wide.", tin=420, tout=95):
    return {"id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": "gpt-5.5",
            "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 20}},
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": []}


class PromptWriterTest(Base):
    def install(self, status, body):
        seen = []

        def handler(request: httpx.Request):
            seen.append((str(request.url), request.headers.get("authorization"), json.loads(request.content)))
            return httpx.Response(status, json=body)
        PW.set_test_http_client(httpx.Client(transport=httpx.MockTransport(handler)))
        return seen

    def body(self, **kw):
        return {"kind": "still", "notes": "Ann gasps at the letter", **kw}

    def test_confirm_usd_rule_409(self):
        seen = self.install(200, openai_response())
        est = self.c.post(f"/api/episodes/{self.eid}/prompts/estimate", json=self.body()).json()
        self.assertEqual(est["model"], "gpt-5.5")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/prompts/write", json=self.body()).status_code, 409)
        r = self.c.post(f"/api/episodes/{self.eid}/prompts/write", json=self.body(confirm_usd=est["usd_max"] / 2))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(seen, [], "nothing is sent without the confirmed cost")

    def test_write_edit_approve(self):
        seen = self.install(200, openai_response())
        est = self.c.post(f"/api/episodes/{self.eid}/prompts/estimate", json=self.body()).json()
        r = self.c.post(f"/api/episodes/{self.eid}/prompts/write", json=self.body(confirm_usd=est["usd_max"]))
        self.assertEqual(r.status_code, 200, r.text)
        item = r.json()
        self.assertEqual((item["status"], item["text"]), ("draft", "A tall stick man gasps, eyes wide."))
        self.assertEqual(item["usage"], {"input_tokens": 420, "output_tokens": 95})
        self.assertAlmostEqual(item["usd"], 420 * 5 / 1e6 + 95 * 30 / 1e6)
        url, auth, sent = seen[0]
        self.assertTrue(url.endswith("/responses"))
        self.assertEqual(auth, f"Bearer {FAKE_OPENAI}")
        self.assertEqual((sent["model"], sent["max_output_tokens"]), ("gpt-5.5", 4000))
        self.assertIn("SHOT STILL", sent["input"])
        self.assertIn("TRUE STICK MAN", sent["input"], "the house style text is part of the request")
        self.assertNotIn(FAKE_OPENAI, json.dumps(item))
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["prompts"]["status"], "needs_approval")
        r = self.c.put(f"/api/episodes/{self.eid}/prompts/{item['id']}", json={"text": "Edited prompt", "approve": True})
        self.assertEqual((r.json()["status"], r.json()["text"], r.json()["edited"]), ("approved", "Edited prompt", True))
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["prompts"]["status"], "done")
        r = self.c.put(f"/api/episodes/{self.eid}/prompts/{item['id']}", json={"text": "Changed again"})
        self.assertEqual(r.json()["status"], "draft", "an edit after approval needs approving again")

    def test_empty_balance_in_plain_english(self):
        self.install(429, {"error": {"message": "You exceeded your current quota", "type": "insufficient_quota",
                                     "code": "insufficient_quota", "param": None}})
        est = self.c.post(f"/api/episodes/{self.eid}/prompts/estimate", json=self.body()).json()
        r = self.c.post(f"/api/episodes/{self.eid}/prompts/write", json=self.body(confirm_usd=est["usd_max"]))
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["detail"], PW.NO_CREDIT)

    def test_master_needs_character(self):
        self.install(200, openai_response())
        r = self.c.post(f"/api/episodes/{self.eid}/prompts/estimate", json={"kind": "master", "notes": "x"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
