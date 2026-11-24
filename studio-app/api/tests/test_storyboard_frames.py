"""Storyboard frames from the dashboard: plan, references, cost confirmation, one-at-a-time job that stops on the first
failure (never retried), imports and the owner's own approvals. The image provider is a test stand-in; the routes,
storage, queue, worker and job code are the real code."""
import unittest

from helpers import Env

from oddstudio import providers

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
PROMPT = "A medium shot of the study with Uncle Mortimer at his desk."


def plan(*frames):
    return {"frames": [{"frame": f, "prompt": PROMPT, "references": refs, "size": "1536x1024",
                        "shots": [{"n": i + 1, "start": i * 2.0, "end": i * 2.0 + 2, "text": "line"}]}
                       for i, (f, refs) in enumerate(frames)]}


class StoryboardFramesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.calls = []

        def fake(prompt, out_file, reference):
            self.calls.append((prompt, [p.name for p in (reference or [])]))
            if "FAIL" in prompt:
                raise providers.ProviderError("plan limit reached", transient=False)
            out_file.write_bytes(PNG)
            return out_file
        providers.set_test_image(fake)
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            ep = Episode(title="Will", status="draft") if hasattr(Episode, "status") else Episode(title="Will")
            s.add(ep)
            s.commit()
            self.eid = ep.id

    def tearDown(self):
        providers.set_test_image(None)
        self.env.close()

    def url(self, tail=""):
        return f"/api/episodes/{self.eid}/storyboard-frames{tail}"

    def use(self, provider):
        r = self.c.put("/api/settings/image", json={"provider": provider, "fallback": "none"})
        self.assertEqual(r.status_code, 200, r.text)

    def setup_plan(self, *frames):
        r = self.c.put(self.url("/plan"), json=plan(*frames))
        self.assertEqual(r.status_code, 200, r.text)
        for name in sorted({x for _, refs in frames for x in refs}):
            r = self.c.put(self.url(f"/references/{name}"), content=PNG, headers={"Content-Type": "image/png"})
            self.assertEqual(r.status_code, 200, r.text)

    def test_codex_frames_made_one_at_a_time_free(self):
        self.use("codex-cli")
        self.setup_plan(("F01", ["room.png", "mortimer.png"]), ("F02", ["room.png"]))
        est = self.c.post(self.url("/estimate"), json={"frames": ["F01", "F02"]}).json()
        self.assertEqual(est["total"], 0.0)
        self.assertIn("ChatGPT plan", est["label"])
        r = self.c.post(self.url("/make"), json={"frames": ["F01", "F02"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.env.run_jobs(["storyboard_frames"])
        v = self.c.get(self.url()).json()
        self.assertEqual([f["latest"]["provider"] for f in v["frames"]], ["codex-cli", "codex-cli"])
        self.assertEqual(self.calls[0][1], ["room.png", "mortimer.png"])     # the plan's references, in order
        self.assertIsNone(v["frames"][0]["approved_asset_id"])                # never approved by the job
        self.assertIn("not for publishing", v["frames"][0]["latest"]["asset"]["label"])

    def test_paid_provider_needs_the_shown_total(self):
        self.use("openai")
        self.setup_plan(("F01", ["room.png", "mortimer.png"]))
        est = self.c.post(self.url("/estimate"), json={"frames": ["F01"]}).json()
        self.assertAlmostEqual(est["total"], 0.19)
        r = self.c.post(self.url("/make"), json={"frames": ["F01"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Confirm the cost", r.text)
        self.assertEqual(self.calls, [])
        r = self.c.post(self.url("/make"), json={"frames": ["F01"], "confirm_total": est["total"]})
        self.assertEqual(r.status_code, 200, r.text)

    def test_stops_at_first_failure_and_is_not_retried(self):
        self.use("codex-cli")
        body = plan(("F01", ["room.png"]), ("F02", ["room.png"]), ("F03", ["room.png"]))
        body["frames"][1]["prompt"] = "FAIL " + PROMPT
        self.c.put(self.url("/plan"), json=body)
        self.c.put(self.url("/references/room.png"), content=PNG)
        self.c.post(self.url("/make"), json={"frames": ["F01", "F02", "F03"]})
        self.env.run_jobs(["storyboard_frames"])
        self.assertEqual(len(self.calls), 2)                                  # F03 never attempted, F02 not retried
        v = self.c.get(self.url()).json()
        self.assertIsNotNone(v["frames"][0]["latest"])
        self.assertIsNone(v["frames"][1]["latest"])
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as s:
            j = s.query(Job).filter_by(kind="storyboard_frames").one()
            self.assertEqual(j.status, "failed")
            self.assertIn("F02 failed (made before it: F01)", j.error)

    def test_missing_reference_and_bad_names_refused(self):
        self.use("codex-cli")
        self.c.put(self.url("/plan"), json=plan(("F01", ["room.png"])))
        r = self.c.post(self.url("/make"), json={"frames": ["F01"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("room.png", r.text)
        self.assertNotEqual(self.c.put(self.url("/references/..%2Fx.png"), content=PNG).status_code, 200)
        self.assertEqual(self.c.put(self.url("/references/evil.sh"), content=PNG).status_code, 422)
        self.assertEqual(self.c.put(self.url("/references/ok.png"), content=b"not a png").status_code, 422)
        self.assertEqual(self.c.put(self.url("/plan"), json=plan(("bad id!", []))).status_code, 422)

    def test_import_is_a_draft_and_only_the_owner_approves(self):
        self.use("codex-cli")
        self.setup_plan(("F01", ["room.png"]))
        v = self.c.put(self.url("/frames/F01/import?source=codex%20local%20run"), content=PNG).json()
        made = v["frames"][0]["latest"]
        self.assertEqual(made["provider"], "imported")
        self.assertIsNone(v["frames"][0]["approved_asset_id"])
        v = self.c.post(self.url(f"/frames/F01/approve?asset_id={made['asset_id']}")).json()
        self.assertEqual(v["frames"][0]["approved_asset_id"], made["asset_id"])
        v = self.c.post(self.url("/frames/F01/unapprove")).json()
        self.assertIsNone(v["frames"][0]["approved_asset_id"])
        self.assertEqual(self.c.post(self.url("/frames/F01/approve?asset_id=999999")).status_code, 404)

    def test_routes_need_the_owner(self):
        from fastapi.testclient import TestClient
        from oddstudio.main import app
        anon = TestClient(app)
        self.assertIn(anon.get(self.url()).status_code, (401, 403))
        self.assertIn(anon.post(self.url("/make"), json={"frames": ["F01"]}).status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
