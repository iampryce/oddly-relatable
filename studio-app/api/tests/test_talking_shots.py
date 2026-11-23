"""Talking shots in the shot comparison (WaveSpeed InfiniteTalk fast by default; Kling v1 Avatar on WaveSpeed as a
fallback only): the price (the audio rounded up, 3 s minimum), the neutral prompt (attitude words refused), the seed,
the head-and-shoulders first frame cut from our approved art, a hard cap per plan on top of the experimental budget,
no automatic retry of a paid call, the provider's file stored at once with the exact request and its terms status,
and the WaveSpeed key in the credential store (never returned). WaveSpeed is stubbed: no network, no cost."""
import subprocess
import unittest

from PIL import Image

from test_shot_compare import ShotBase

from oddstudio import providers, wavespeed
from oddstudio import shot_compare as SC
from oddstudio import secrets_store
from oddstudio.secrets_store import SECRETS

IT, KL = "wavespeed-infinitetalk-fast", "wavespeed-kling-v1-avatar-standard"


class PriceTest(unittest.TestCase):
    def test_audio_seconds_rounded_up_with_a_3_s_minimum(self):
        self.assertEqual(SC.estimate(IT, 6.22), {"billed_seconds": 7, "usd": 0.105, "note": "6.22 s of audio billed as 7 s at $0.015/s"})
        self.assertEqual(SC.estimate(IT, 1.0)["usd"], 0.045, "3 s minimum")
        self.assertEqual(SC.estimate(IT, 3.0)["billed_seconds"], 3)
        self.assertEqual(SC.estimate(IT, 3.001)["billed_seconds"], 4)
        self.assertEqual(SC.estimate(IT, 3.0004)["billed_seconds"], 3, "measured to the millisecond")
        self.assertEqual(SC.estimate(KL, 6.22)["usd"], 0.35)
        self.assertEqual(SC.estimate(KL, 2.0)["usd"], 0.15, "3 s minimum")

    def test_the_registry_default_and_terms(self):
        from oddstudio.settings_store import DEFAULTS
        self.assertEqual(DEFAULTS["motion"]["talking_provider"], IT, "InfiniteTalk fast is the default; Kling never by itself")
        self.assertIn("commercial-use terms not yet confirmed in writing", SC.TALKING[IT]["terms"])
        self.assertEqual(SC.TALKING[KL]["terms"], "Kling terms not yet confirmed in writing: not for publishing")
        self.assertTrue(SC.TALKING[IT]["seed"])
        self.assertFalse(SC.TALKING[KL]["seed"], "Kling v1 on WaveSpeed takes no seed")


class PromptTest(unittest.TestCase):
    def test_neutral_wording_only(self):
        self.assertEqual(SC.attitude_words(SC.default_talking_prompt("Uncle Mortimer")), [])
        self.assertIn("formal, composed, neutral face, eyes wide open as in the image, small nods, no smile",
                      SC.default_talking_prompt("Uncle Mortimer"))
        self.assertEqual(SC.attitude_words("He reads the will, pompous, chin slightly raised, smiling"),
                         ["pompous", "smiling", "chin slightly raised"])
        self.assertEqual(SC.attitude_words("no smile, not smiling, without a grin"), [], "negated words are allowed")
        self.assertEqual(SC.attitude_words("a smug look"), ["smug"])
        self.assertEqual(SC.attitude_words("smugglers"), [], "whole words only")


class CropTest(unittest.TestCase):
    def test_head_near_the_top_and_the_frame_ends_at_the_vest(self):
        lay = SC.head_layout({"neck_x": 150, "neck_y": 300, "vest_y": 340, "head_w": 200})
        self.assertEqual(lay["fit"], "vest")
        self.assertEqual(lay["y"], 36, "4% head room")
        self.assertAlmostEqual(lay["vest_at"], 0.94 * 900, delta=1, msg="the vest top at the bottom of the frame")
        self.assertLessEqual(200 * lay["scale"], 0.92 * 720 + 1)
        wide = SC.head_layout({"neck_x": 300, "neck_y": 300, "vest_y": 340, "head_w": 600})
        self.assertEqual(wide["fit"], "head width", "a very wide head is fitted to the width")
        self.assertAlmostEqual(600 * wide["scale"], 0.92 * 720, delta=1)
        self.assertLess(wide["vest_at"], 0.94 * 900)
        self.assertEqual(SC.FRAME_SIZE["head"], (720, 900), "vertical")


class CredentialTest(ShotBase):
    def setUp(self):
        super().setUp()
        secrets_store._cache = None      # no credential cached from another test

    def tearDown(self):
        secrets_store._cache = None
        super().tearDown()

    def test_the_key_is_stored_and_never_returned(self):
        self.assertEqual(SECRETS["wavespeed_api_key"], "WAVESPEED_API_KEY")
        r = self.c.put("/api/settings/credentials", json={"values": {"wavespeed_api_key": "ws-test-secret-123"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("ws-test-secret-123", r.text)
        g = self.c.get("/api/settings")
        self.assertNotIn("ws-test-secret-123", g.text)
        self.assertTrue(g.json()["credentials"]["wavespeed_api_key"])
        from oddstudio.secrets_store import secret
        self.assertEqual(wavespeed._key(), secret("wavespeed_api_key"))

    def test_without_a_key_nothing_is_sent(self):
        p = self.ready()
        self.assertEqual(wavespeed.secret("wavespeed_api_key"), "", "no key stored in this test")
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT}).status_code, 200)
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual(ran[0][1], "failed")
        res = self.row(p["id"])["results"][IT]
        self.assertIn("save the WaveSpeed API key under Settings > Credentials", res["error"])


class TalkingFlowTest(ShotBase):
    def setUp(self):
        super().setUp()
        secrets_store._cache = None
        self.calls = []

    def tearDown(self):
        wavespeed.set_test_run(None)
        super().tearDown()

    def ws_stub(self, fail: Exception | None = None, size="352x640"):
        def run(endpoint, body, out):
            self.calls.append((endpoint, body))
            if fail:
                raise fail
            w, h = size.split("x")
            subprocess.run([self.ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={w}x{h}:d=3.0:r=25", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(out)], check=True)
            return {"id": "task-1", "status": "completed", "outputs": ["https://ws.example/out.mp4"]}
        wavespeed.set_test_run(run)

    def test_a_talking_shot_from_the_head_frame_with_the_neutral_prompt_stored_with_its_request(self):
        providers.set_test_text_responder(lambda s, p: self.fail("no text call"))
        p = self.ready()
        self.assertIn("head", p["frame_assets"], "made in the free preparation")
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as s:
            f = storage().get_to_file(s.get(Asset, p["frame_assets"]["head"]).storage_key, self.media / "head.png")
        with Image.open(f) as im:
            self.assertEqual(im.size, (720, 900))
        req = next(r for r in p["requests"] if r["model"] == IT)
        self.assertEqual(req["framing"], "head", "head and shoulders by default for InfiniteTalk")
        self.assertEqual(req["estimate"]["usd"], 0.045, "a 3.0 s line: the 3 s minimum")
        self.assertEqual(set(req["body"]), {"image", "audio", "prompt", "seed"})
        self.assertEqual(SC.attitude_words(req["body"]["prompt"]), [], "the neutral default, not the action text")
        self.assertIn("smug", p["action"], "the action (for the other models) keeps its tone")
        self.assertIn("commercial-use terms not yet confirmed", req["terms"])
        kl = next(r for r in p["requests"] if r["model"] == KL)
        self.assertEqual((kl["framing"], set(kl["body"]), kl["estimate"]["usd"]), ("medium", {"image", "audio", "prompt"}, 0.15))
        # the seed is the owner's to set, and saved with the clip
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/seed", json={"model": KL, "seed": 5}).status_code, 422)
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/seed", json={"model": IT, "seed": 4242}).status_code, 200)
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/talking-prompt", json={"prompt": "He reads it, smug and pompous"}).status_code, 422)
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/talking-prompt",
                                    json={"prompt": "Mortimer reads calmly, neutral face, small nods, no smile."}).status_code, 200)
        self.assertEqual(self.calls, [], "nothing is sent until Run")
        self.ws_stub()
        spent0 = self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()["spent_usd"]
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT}).status_code, 200)
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        endpoint, body = self.calls[0]
        self.assertEqual(endpoint, "wavespeed-ai/infinitetalk-fast")
        self.assertIn("first-frame-head.png", body["image"])
        self.assertTrue(body["audio"].startswith("https://studio.example/"))
        self.assertEqual((body["prompt"], body["seed"]), ("Mortimer reads calmly, neutral face, small nods, no smile.", 4242))
        res = self.row(p["id"])["results"][IT]
        self.assertEqual((res["status"], res["provider"], res["endpoint"], res["seed"], res["actual_usd"], res["publishable"]),
                         ("done", "wavespeed", "wavespeed-ai/infinitetalk-fast", 4242, 0.045, False))
        self.assertEqual(res["prompt"], body["prompt"])
        self.assertIn("not yet confirmed in writing", res["terms"])
        self.assertEqual(res["output_size"], "352x640", "the provider's size as delivered")
        self.assertTrue(res["check"]["length_ok"])
        with new_session() as s:
            raw = s.get(Asset, res["raw_asset_id"])
            self.assertIn("as delivered", raw.label)
            fin = storage().get_to_file(s.get(Asset, res["asset_id"]).storage_key, self.media / "fin.mp4")
        size = subprocess.run([self.ff.replace("ffmpeg", "ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=width,height", "-of", "csv=p=0:s=x", str(fin)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(size, "720x900", "kept vertical at the head frame's size")
        b = self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()
        self.assertAlmostEqual(b["spent_usd"], spent0 + 0.045, places=4, msg="on the experimental budget")
        self.assertEqual(self.row(p["id"])["spend"][0]["usd"], 0.045, "on the plan's own cap")

    def test_the_plan_cap_and_the_experimental_budget(self):
        p = self.ready()
        self.ws_stub()
        r = self.c.put(f"/api/motion/shot/{p['id']}/talking-cap", json={"cap_usd": 0.10})
        self.assertEqual(r.json()["talking"]["cap_usd"], 0.10)
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT}).status_code, 200)
        r = self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": KL})
        self.assertEqual(r.status_code, 409, "0.045 approved + 0.15 > 0.10")
        self.assertIn("over this plan's cap", r.text)
        s = self.c.post("/api/motion/shot-batch/run", json={"plan_ids": [p["id"]], "models": [KL]}).json()
        self.assertEqual(s["clips"], 0)
        self.assertIn("over this plan's cap", " ".join(s["skipped"]))
        self.env.run_jobs(["shot_generate"])
        self.c.put(f"/api/motion/shot/{p['id']}/talking-cap", json={"cap_usd": 1.0})
        self.c.put("/api/settings/motion", json={"budget_usd": 0.1})
        r = self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": KL})
        self.assertEqual(r.status_code, 409)
        self.assertIn("experimental budget", r.text)
        self.assertEqual(self.c.put("/api/settings/motion", json={"talking_provider": "something-else"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/motion", json={"talking_plan_cap_usd": 0}).status_code, 422)

    def test_a_failed_paid_call_is_not_retried_by_itself(self):
        p = self.ready()
        self.ws_stub(fail=providers.ProviderError("WaveSpeed result: HTTP 503", transient=True))
        self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT})
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual([x[1] for x in ran], ["failed"], "failed, not queued again")
        self.assertEqual(len(self.calls), 1, "sent once")
        res = self.row(p["id"])["results"][IT]
        self.assertEqual(res["status"], "failed")
        self.assertIn("503", res["error"])
        self.assertEqual(self.row(p["id"])["spend"][0]["request_id"], "test-task", "an accepted task still counts on the cap")

    def test_a_plan_from_before_gets_its_head_frame_on_request(self):
        p = self.ready()
        recs = None
        from oddstudio.db import new_session
        with new_session() as s:
            recs = SC.records(s)
            recs[p["id"]]["frame_assets"].pop("head")
            SC.save(s, recs)
            s.commit()
        r = self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT})
        self.assertEqual(r.status_code, 409)
        self.assertIn("make the head-and-shoulders first frame first", r.text)
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/framing", json={"model": "kling-avatar-v2-standard", "framing": "head"}).status_code, 409,
                         "never silently another frame")
        r = self.c.post(f"/api/motion/shot/{p['id']}/frame", json={"framing": "head"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("head", r.json()["frame_assets"])
        self.ws_stub()
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": IT}).status_code, 200)


def _ready(self):
    r = self.c.post("/api/motion/shot/plan", json={"episode_id": self.eid, "scene_id": self.sid, "line": 0, "action": "says it, smug"})
    assert r.status_code == 200, r.text
    ran = self.env.run_jobs(["shot_prepare"])
    assert ran[0][1] == "succeeded", ran
    return self.row(r.json()["plan"]["id"])


def _row(self, pid):
    return next(x for x in self.c.get("/api/motion/shot").json()["plans"] if x["id"] == pid)


ShotBase.ready = _ready
ShotBase.row = _row

if __name__ == "__main__":
    unittest.main()
