"""The stick pipeline (2026-11-25): Settings > Studio style, character masters (candidates to review, the owner's
approval, sheets from the approved master only), shot stills (set + masters as references, a new take, not approved),
animation (priced PER SECOND of video, approved stills only, Animate all with its total) and the costs shown and
confirmed before anything paid starts. WaveSpeed is stubbed: no network, no cost."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from helpers import Env
from test_shot_frames_dashboard import DESK, FAM, FlowBase

from oddstudio import stick_pipeline as SP
from oddstudio import stick_shots as SS
from oddstudio import wavespeed


def png_bytes(color=(250, 250, 250)) -> bytes:
    f = Path(tempfile.mkdtemp()) / "x.png"
    Image.new("RGB", (40, 60), color).save(f)
    return f.read_bytes()


class Stub:
    """Records every upload and paid run; writes a small PNG (images) or bytes (video) as the output."""

    def __init__(self, fail_on=None):
        self.uploads, self.runs, self.fail_on = [], [], fail_on

    def upload(self, path):
        self.uploads.append(Path(path).name)
        return f"https://ws.example/up/{len(self.uploads)}"

    def run(self, endpoint, body, out):
        self.runs.append((endpoint, body))
        if self.fail_on and len(self.runs) == self.fail_on:
            from oddstudio.providers import ProviderError
            raise ProviderError("WaveSpeed: task t failed: stub", transient=False)
        if endpoint.endswith("i2v-720p"):
            out.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video")
        else:
            Image.new("RGB", (30, 40), (len(self.runs) * 30 % 255, 80, 80)).save(out)
        return {"id": f"t{len(self.runs)}", "status": "completed", "outputs": ["https://ws.example/o"]}

    def install(self):
        wavespeed.set_test_run(self.run)
        wavespeed.set_test_upload(self.upload)
        return self


def uninstall():
    wavespeed.set_test_run(None)
    wavespeed.set_test_upload(None)
    wavespeed.set_test_balance(None)


class CostTest(unittest.TestCase):
    def test_images_per_image_and_video_per_second(self):
        self.assertEqual(SP.image_cost(2, 0.04)["usd"], 0.08)
        self.assertEqual(SP.image_cost(2, 0.04)["label"], "2 images x $0.04 = $0.08")
        v = SP.video_cost(5, 0.06)
        self.assertEqual((v["usd"], v["usd_each"]), (0.3, 0.3), "0.06/s for 5 s is $0.30, not $0.06")
        self.assertEqual(SP.video_cost(8, 0.06)["usd"], 0.48)
        self.assertEqual(SP.video_cost(5, 0.06, clips=3)["usd"], 0.9)
        self.assertIn("3 clips", SP.video_cost(5, 0.06, clips=3)["label"])

    def test_model_list_price_units(self):
        self.assertEqual(SP.price_from_model_list({"base_price": 0.06}, "video"), {"usd_per_second": 0.06})
        self.assertEqual(SP.price_from_model_list({"base_price": 0.04}, "image"), {"usd_per_image": 0.04})
        self.assertEqual(SP.VIDEO_PROVIDERS["wavespeed-wan-2.2-i2v-720p"]["usd_per_second"], 0.06)
        self.assertEqual(SP.IMAGE_PROVIDERS["wavespeed-nano-banana-2.1"]["usd_per_image"], 0.04)

    def test_bodies(self):
        self.assertEqual(SP.edit_body("p", ["u1", "u2"], "3:4"),
                         {"prompt": "p", "images": ["u1", "u2"], "aspect_ratio": "3:4", "resolution": "1k", "output_format": "png"})
        b = SS.i2v_body("img", "move", 5, 7)
        self.assertEqual(set(b), {"image", "prompt", "negative_prompt", "duration", "seed"})
        self.assertEqual(SS.i2v_body("img", "m", 5, 7, last_image_url="end")["last_image"], "end")


class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.stub = Stub().install()

    def tearDown(self):
        uninstall()
        self.env.close()

    def character(self, key="mortimer", name="Uncle Mortimer", look="small round glasses, stern expression"):
        r = self.c.post("/api/characters", json={"key": key, "name": name, "visual_description": look})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def style_reference(self):
        r = self.c.put("/api/stick/style-reference/upload", content=png_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def approve_master(self, cid):
        cost = self.c.get(f"/api/characters/{cid}/stick").json()["costs"]["master"]["usd"]
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": cost}).status_code, 200)
        ran = self.env.run_jobs(["stick_master"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        st = self.c.get(f"/api/characters/{cid}/stick").json()
        r = self.c.post(f"/api/characters/{cid}/stick/assets/{st['candidates'][0]['id']}/decision", json={"decision": "approve"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class SettingsTest(Base):
    def test_defaults_and_validation(self):
        s = self.c.get("/api/settings").json()["sections"]["stick"]
        self.assertIn("TRUE STICK MAN", s["style_prompt"], "the owner's master prompt is the default")
        self.assertEqual((s["image_provider"], s["video_provider"], s["style_reference"]),
                         ("wavespeed-nano-banana-2.1", "wavespeed-wan-2.2-i2v-720p", None))
        for bad in ({"video_provider": "gpu-self-hosted"}, {"image_provider": "x"}, {"style_reference": {"kind": "asset", "id": 999}},
                    {"video_seconds": 6}, {"style_prompt": "short"}):
            self.assertEqual(self.c.put("/api/settings/stick", json=bad).status_code, 422, bad)
        self.assertEqual(self.c.put("/api/settings/stick", json={"style_prompt": "A stick man in bold black lines, always."}).status_code, 200)

    def test_style_reference_upload_and_options(self):
        cfg = self.style_reference()
        self.assertEqual(cfg["style_reference"]["kind"], "asset")
        self.assertTrue(cfg["style_reference"]["url"])
        self.assertEqual((cfg["options"][0]["kind"], cfg["options"][0]["id"]), ("asset", cfg["style_reference"]["id"]))
        self.assertEqual(self.c.put("/api/stick/style-reference/upload", content=b"not an image").status_code, 422)

    def test_balance_is_a_stubbed_get(self):
        self.assertEqual(self.c.get("/api/stick/balance").status_code, 502, "no key and no stub: refused, no network")
        wavespeed.set_test_balance(lambda: 12.5)
        self.assertEqual(self.c.get("/api/stick/balance").json(), {"usd": 12.5})


class MasterTest(Base):
    def test_master_flow_cost_first_review_and_owner_approval(self):
        cid = self.character()
        st = self.c.get(f"/api/characters/{cid}/stick").json()
        self.assertEqual(st["costs"]["master"]["usd"], 0.08, "2 candidates x $0.04")
        self.assertEqual(st["costs"]["expressions"]["usd"], 0.04)
        self.assertIn("Uncle Mortimer", st["prompt"])
        self.assertIn("small round glasses", st["prompt"])
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.08}).status_code, 409,
                         "no style reference yet")
        self.style_reference()
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/master", json={}).status_code, 409, "cost not confirmed")
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.04}).status_code, 409,
                         "a different price than the real one")
        self.assertEqual(self.stub.runs, [], "nothing paid started")
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.08}).status_code, 200)
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.08}).status_code, 409,
                         "one at a time")
        ran = self.env.run_jobs(["stick_master"])
        self.assertEqual(ran, [("stick_master", "succeeded", "")])
        self.assertEqual(len(self.stub.runs), 2)
        self.assertEqual(self.stub.runs[0][0], "google/nano-banana-2.1/edit")
        self.assertEqual(self.stub.runs[0][1]["images"], ["https://ws.example/up/1"], "the style reference is image 1")
        self.assertEqual(len(self.stub.uploads), 1, "the reference is uploaded once")
        st = self.c.get(f"/api/characters/{cid}/stick").json()
        self.assertIsNone(st["master"], "nothing is approved by the job")
        self.assertEqual([c["status"] for c in st["candidates"]], ["review", "review"])
        # the budget ledger counts both images
        from oddstudio import fal
        from oddstudio.db import new_session
        with new_session() as db:
            self.assertAlmostEqual(fal.spent(db)["total"], 0.08)
        a, b = st["candidates"]
        st = self.c.post(f"/api/characters/{cid}/stick/assets/{a['id']}/decision", json={"decision": "approve"}).json()
        self.assertEqual(st["master"]["id"], a["id"])
        self.c.post(f"/api/characters/{cid}/stick/assets/{b['id']}/decision", json={"decision": "reject"})
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/assets/{b['id']}/decision", json={"decision": "approve"}).status_code,
                         409, "a rejected candidate is not approved later by accident")

    def test_sheets_only_from_the_approved_master(self):
        cid = self.character()
        self.style_reference()
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/expressions", json={"confirm_usd": 0.04}).status_code, 409,
                         "no approved master yet")
        master = self.approve_master(cid)["master"]
        self.stub.uploads.clear(); self.stub.runs.clear()
        self.assertEqual(self.c.post(f"/api/characters/{cid}/stick/turnaround", json={"confirm_usd": 0.04}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["stick_sheet"])[0][1], "succeeded")
        self.assertEqual(self.stub.uploads, ["master.png"], "the approved master is the ONLY reference")
        self.assertEqual(len(self.stub.runs[0][1]["images"]), 1)
        self.assertIn("EXACTLY the character in the reference image", self.stub.runs[0][1]["prompt"])
        st = self.c.get(f"/api/characters/{cid}/stick").json()
        self.assertEqual([(s["sheet"], s["status"]) for s in st["sheets"]], [("turnaround", "review")])
        self.assertEqual(st["master"]["id"], master["id"])

    def test_a_failure_keeps_the_finished_candidates_and_is_not_retried(self):
        uninstall()
        self.stub = Stub(fail_on=2).install()
        cid = self.character()
        self.style_reference()
        self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.08})
        ran = self.env.run_jobs(["stick_master"])
        self.assertEqual(len(ran), 1, "not retried by the worker")
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("1 of 2 candidates made", ran[0][2])
        self.assertEqual(len(self.stub.runs), 2)
        self.assertEqual(len(self.c.get(f"/api/characters/{cid}/stick").json()["candidates"]), 1)


class ShotTest(FlowBase):
    def setUp(self):
        super().setUp()
        self.stub = Stub().install()
        self.cid = {}
        for key, name in (("mortimer", "Uncle Mortimer"), ("solicitor", "The Solicitor"), ("ralph", "Ralph"), ("sidney", "Sidney")):
            r = self.c.post("/api/characters", json={"key": key, "name": name, "visual_description": "a cap"})
            self.cid[key] = r.json()["id"]
        r = self.c.put("/api/stick/style-reference/upload", content=png_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 201)

    def tearDown(self):
        uninstall()
        super().tearDown()

    def master(self, key):
        cid = self.cid[key]
        self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.08})
        self.env.run_jobs(["stick_master"])
        a = self.c.get(f"/api/characters/{cid}/stick").json()["candidates"][0]
        self.c.post(f"/api/characters/{cid}/stick/assets/{a['id']}/decision", json={"decision": "approve"})

    def test_still_then_animate(self):
        v = self.make()
        shot1 = v["shots"][0]
        self.assertEqual((shot1["side"], shot1["people"]), (DESK, ["mortimer", "solicitor"]))
        info = self.c.get(f"/api/episodes/{self.eid}/stick-shots").json()
        self.assertEqual(info["image"]["cost"]["usd"], 0.04)
        self.assertEqual(info["video"]["cost"]["usd"], 0.3, "5 s x $0.06 per second")
        self.assertEqual(info["shots"][0]["missing_masters"], ["mortimer", "solicitor"])
        p = info["shots"][0]["prompt"]
        self.assertIn("Uncle Mortimer (image 2): seated", p)
        self.assertIn("The Solicitor (image 3): standing", p)
        self.assertIn("9:16", p)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/still", json={"confirm_usd": 0.04}).status_code, 409,
                         "masters first")
        self.master("mortimer"); self.master("solicitor")
        self.stub.uploads.clear(); self.stub.runs.clear()
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/still", json={}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/still", json={"confirm_usd": 0.04}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["stick_shot_still"])[0][1], "succeeded")
        self.assertEqual(self.stub.uploads, [f"{DESK}.png", "master-mortimer.png", "master-solicitor.png"],
                         "the set first, then the masters of the people in the shot")
        self.assertEqual(self.stub.runs[0][1]["aspect_ratio"], "9:16")
        s = self.frames()["shots"][0]
        self.assertEqual([x["source"] for x in s["versions"]], ["first", "still"], "the earlier take is kept")
        self.assertEqual((s["chosen"], s["approved"]), (s["versions"][1]["asset_id"], False), "chosen, not approved")
        # animate: approved stills only, cost per second confirmed first
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/animate", json={"seconds": 5, "confirm_usd": 0.3}).status_code, 409)
        self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/approve")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/animate", json={"seconds": 5, "confirm_usd": 0.06}).status_code,
                         409, "the per-second price is not the clip's price")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/animate", json={"seconds": 6, "confirm_usd": 0.36}).status_code, 422)
        self.stub.runs.clear()
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/animate", json={"seconds": 5, "confirm_usd": 0.3}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["stick_shot_animate"])[0][1], "succeeded")
        endpoint, body = self.stub.runs[0]
        self.assertEqual(endpoint, "wavespeed-ai/wan-2.2/i2v-720p")
        self.assertEqual(body["duration"], 5)
        self.assertTrue(body["negative_prompt"])
        info = self.c.get(f"/api/episodes/{self.eid}/stick-shots").json()
        clip = info["shots"][0]["clips"][0]
        self.assertEqual((clip["seconds"], clip["usd"], info["shots"][0]["clip_approved"]), (5, 0.3, False))
        self.assertTrue(clip["url"])
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/clip/approve", json={"asset_id": clip["asset_id"]})
        self.assertTrue(r.json()["shots"][0]["clip_approved"])
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/clip/approve", json={"asset_id": 99999}).status_code, 422)

    def test_animate_all_total_first(self):
        self.make()
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/animate-all", json={"seconds": 5, "confirm_usd": 0}).status_code,
                         409, "nothing approved")
        self.c.post(f"/api/episodes/{self.eid}/shot-frames/approve-all")
        info = self.c.get(f"/api/episodes/{self.eid}/stick-shots").json()
        self.assertEqual(info["animate_all"]["shots"], [1, 2, 3])
        self.assertEqual(info["animate_all"]["cost"]["usd"], 0.9, "3 clips x 5 s x $0.06")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/animate-all", json={"seconds": 5, "confirm_usd": 0.3}).status_code, 409)
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/animate-all", json={"seconds": 5, "confirm_usd": 0.9})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["jobs"]), 3)
        self.assertEqual(self.stub.runs, [], "queued only: the worker makes each one paid call")
        ran = self.env.run_jobs(["stick_shot_animate"])
        self.assertEqual([x[1] for x in ran], ["succeeded"] * 3)
        info = self.c.get(f"/api/episodes/{self.eid}/stick-shots").json()
        self.assertEqual(info["animate_all"]["shots"], [], "every approved shot has a clip now")
        self.assertEqual([len(s["clips"]) for s in info["shots"]], [1, 1, 1])


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio import chat, secrets_store
        self.chat = chat
        secrets_store._cache = None
        self.calls = []

    def tearDown(self):
        self.chat.set_test_call(None)
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        self.env.close()

    def test_cost_math(self):
        self.assertEqual(self.chat.cost_usd("anthropic", 1_000_000, 0), 4.0)
        self.assertEqual(self.chat.cost_usd("anthropic", 0, 1_000_000), 20.0)
        e = self.chat.estimate("anthropic", "x" * 350, [{"role": "user", "content": "y" * 35}], 1000)
        self.assertEqual(e["input_tokens"], 100 + 10 + 4)
        self.assertAlmostEqual(e["usd_max"], round((114 * 4 + 1000 * 20) / 1e6, 4))

    def test_no_key_no_chat(self):
        sid = self.c.post("/api/chat/sessions").json()["id"]
        self.assertEqual(self.c.post("/api/chat/estimate", json={"session_id": sid, "text": "hi"}).status_code, 409)

    def test_send_with_confirmed_cost_and_history(self):
        secret = "sk-ant-test-SECRET-value"
        self.assertEqual(self.c.put("/api/settings/credentials", json={"values": {"anthropic_api_key": secret}}).status_code, 200)
        self.c.post("/api/characters", json={"key": "ralph", "name": "Ralph", "visual_description": "a cap"})

        def call(provider, model, system, messages, max_tokens):
            self.calls.append((provider, model, system, messages, max_tokens))
            return {"text": f"answer {len(self.calls)}", "input_tokens": 1200, "output_tokens": 300}
        self.chat.set_test_call(call)
        sid = self.c.post("/api/chat/sessions").json()["id"]
        est = self.c.post("/api/chat/estimate", json={"session_id": sid, "text": "Which characters need a master?"}).json()
        self.assertEqual((est["provider"], est["model"]), ("anthropic", "claude-opus-5-5"))
        self.assertGreater(est["usd_max"], est["usd_typical"])
        self.assertEqual(self.c.post("/api/chat/send", json={"session_id": sid, "text": "Which characters need a master?"}).status_code,
                         409, "the cost must be confirmed")
        self.assertEqual(self.calls, [])
        r = self.c.post("/api/chat/send", json={"session_id": sid, "text": "Which characters need a master?", "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        reply = r.json()["reply"]
        self.assertEqual(reply["usage"], {"input_tokens": 1200, "output_tokens": 300})
        self.assertAlmostEqual(reply["usd"], (1200 * 4 + 300 * 20) / 1e6)
        system = self.calls[0][2]
        self.assertIn("ralph (Ralph)", system)
        self.assertNotIn(secret, system, "no secret in the context")
        est2 = self.c.post("/api/chat/estimate", json={"session_id": sid, "text": "and then?"}).json()
        self.c.post("/api/chat/send", json={"session_id": sid, "text": "and then?", "confirm_usd": est2["usd_max"]})
        self.assertEqual([m["role"] for m in self.calls[1][3]], ["user", "assistant", "user"], "the history is sent")
        s = self.c.get(f"/api/chat/sessions/{sid}").json()
        self.assertEqual(len(s["messages"]), 4)
        self.assertNotIn(secret, str(s))
        self.assertEqual(self.c.get("/api/chat/sessions").json()[0]["messages"], 4)
        self.assertEqual(self.c.get("/api/chat/sessions/../x").status_code, 404)

    def test_openai_when_only_openai(self):
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-openai-test"}})
        sid = self.c.post("/api/chat/sessions").json()["id"]
        est = self.c.post("/api/chat/estimate", json={"session_id": sid, "text": "hi"}).json()
        self.assertEqual(est["provider"], "openai")
        r = self.c.post("/api/chat/send", json={"session_id": sid, "text": "hi", "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 500, "no stub in tests: refused, no network call")


if __name__ == "__main__":
    unittest.main()
