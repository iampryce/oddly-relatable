"""Sample episode through the REAL production engine: idea -> script -> storyboard (renderer stills) -> production
(MP4, QA) -> video review -> scene revision -> re-render -> final approval -> publishing stays blocked until the owner
approves it (and YouTube is connected). Needs FFMPEG and FFPROBE (skipped otherwise). The script text comes from the
test responder; everything after it is real work by the engine and the unmodified renderer."""
import os
import unittest

from helpers import Env, sample_script

from oddstudio import providers


@unittest.skipUnless(os.environ.get("FFMPEG") and os.environ.get("FFPROBE"), "set FFMPEG and FFPROBE to run the engine end to end")
class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(lambda s, p: sample_script())

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.text)
        return r.json()

    def test_sample_episode(self):
        c, run = self.c, self.env.run_jobs
        idea = self.ok(c.post("/api/ideas", json={"title": "Group chat", "premise": "A man panics over a text from 'unknown'.",
                                                  "characters": ["character-01"], "interactive": "viewer-choice", "status": "submitted"}), 201)
        eid = self.ok(c.post(f"/api/ideas/{idea['id']}/start", json={}), 201)["id"]
        run(["generate_script"])
        self.ok(c.post(f"/api/episodes/{eid}/script/approve", json={"comment": "Funny."}))
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/generate"))
        ran = run(["generate_storyboard", "scene_reference"])
        self.assertTrue(all(s == "succeeded" for _, s, _ in ran), ran)
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertTrue(all(s["reference"] and s["reference"]["url"] for s in d["scenes"]), "every scene has renderer stills")
        self.assertEqual(c.get(d["scenes"][0]["reference"]["url"]).headers["content-type"], "image/png")
        self.ok(c.post(f"/api/episodes/{eid}/storyboard/approve", json={}))

        c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        jobs = self.ok(c.post(f"/api/episodes/{eid}/production/start"))
        self.assertEqual(sorted(j["kind"] for j in jobs), ["scene_prepare", "scene_prepare", "scene_voice", "scene_voice"])
        ran = run()
        self.assertEqual([k for k, s, e in ran if s != "succeeded"], [], ran)
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["stage"], "video_review")
        self.assertEqual(d["video"]["content_type"], "video/mp4")
        self.assertGreater(d["video"]["size"], 50_000)
        render = next(j for j in d["jobs"] if j["kind"] == "render_episode")
        self.assertTrue(render["progress"]["stages"], "engine stage progress was recorded")
        voice = [j for j in d["jobs"] if j["kind"] == "scene_voice"]
        self.assertTrue(all(j["result"].get("skipped") for j in voice), "no voice provider: reported as skipped, not faked")
        kinds = {a["kind"] for a in d["assets"]}
        self.assertTrue({"video", "storyboard-sheet", "report", "manifest", "scene-frames"} <= kinds, kinds)
        first_video = d["video"]["id"]

        # Publishing is blocked before final approval.
        self.assertEqual(c.post(f"/api/episodes/{eid}/publish/approve", json={"confirm": "PUBLISH"}).status_code, 409)

        # Targeted revision: re-produce scene 2 only.
        s2 = d["scenes"][1]["id"]
        self.ok(c.post(f"/api/episodes/{eid}/video/request-revision", json={"target": "scenes", "scene_ids": [s2], "comment": "Hold the twist longer"}))
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual((d["stage"], d["revision"]), ("producing", 2))
        ran = run()
        self.assertEqual(sorted(k for k, _, _ in ran), ["render_episode", "scene_prepare", "scene_voice"], "only scene 2 re-ran")
        d = self.ok(c.get(f"/api/episodes/{eid}"))
        self.assertEqual(d["stage"], "video_review")
        self.assertNotEqual(d["video"]["id"], first_video)

        self.ok(c.post(f"/api/episodes/{eid}/video/approve", json={"comment": "Ship it"}))
        pub = self.ok(c.get(f"/api/episodes/{eid}"))["publish"]
        self.assertEqual(pub["status"], "draft")
        # Not approved for publication yet: blocked.
        self.assertEqual(c.post(f"/api/episodes/{eid}/publish/start").status_code, 409)
        self.assertEqual(c.post(f"/api/episodes/{eid}/publish/approve", json={"confirm": "yes"}).status_code, 422)
        self.ok(c.post(f"/api/episodes/{eid}/publish/approve", json={"confirm": "PUBLISH"}))
        # Changing the details withdraws the approval.
        self.ok(c.put(f"/api/episodes/{eid}/publish", json={"title": "Group chat panic", "privacy": "private"}))
        self.assertEqual(c.post(f"/api/episodes/{eid}/publish/start").status_code, 409)
        self.ok(c.post(f"/api/episodes/{eid}/publish/approve", json={"confirm": "PUBLISH"}))
        # Approved, but YouTube is not connected in this environment: refused, nothing is uploaded or faked.
        r = c.post(f"/api/episodes/{eid}/publish/start")
        self.assertEqual(r.status_code, 409)
        self.assertIn("YouTube is not connected", r.text)


if __name__ == "__main__":
    unittest.main()
