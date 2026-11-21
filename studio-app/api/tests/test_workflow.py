"""Workflow and approval gates through the HTTP API (no engine rendering; runs in seconds)."""
import unittest

from helpers import Env, sample_script

from oddstudio import providers


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        providers.set_test_text_responder(lambda system, prompt: sample_script())

    def tearDown(self):
        providers.set_test_text_responder(None)
        self.env.close()

    def idea(self, **kw):
        body = {"title": "Group chat", "premise": "A man panics over a text.", "characters": ["character-01"], "status": "submitted", **kw}
        r = self.c.post("/api/ideas", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_auth_is_required(self):
        anon = Env()
        try:
            self.assertEqual(anon.client.get("/api/episodes").status_code, 401)
            self.assertEqual(anon.client.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope"}).status_code, 401)
            self.assertEqual(anon.client.get("/api/health").status_code, 200)
        finally:
            anon.close()

    def test_idea_drafts_edit_and_start(self):
        i = self.idea(status="draft")
        r = self.c.put(f"/api/ideas/{i['id']}", json={"title": "Better title", "premise": "x", "status": "draft"})
        self.assertEqual(r.json()["title"], "Better title")
        self.assertEqual(self.c.post("/api/ideas", json={"title": "t", "premise": "p", "characters": ["nobody"]}).status_code, 422)
        ep = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": False}).json()
        self.assertEqual(ep["stage"], "script_pending")
        self.assertEqual(self.c.put(f"/api/ideas/{i['id']}", json={"title": "t", "premise": "p"}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/ideas/{i['id']}/start", json={}).status_code, 409)

    def test_gates_cannot_be_skipped(self):
        i = self.idea()
        ep = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()
        eid = ep["id"]
        self.assertEqual(ep["stage"], "script_generating")
        # Nothing downstream is possible before the script exists and is approved.
        for path in ("storyboard/generate", "production/start", "video/approve", "script/approve"):
            self.assertEqual(self.c.post(f"/api/episodes/{eid}/{path}", json={}).status_code, 409, path)
        self.assertEqual(self.env.run_jobs(["generate_script"]), [("generate_script", "succeeded", "")])
        d = self.c.get(f"/api/episodes/{eid}").json()
        self.assertEqual(d["stage"], "script_review")
        self.assertEqual(d["script"]["version"], 1)
        # Edits are validated, and saved as new versions.
        bad = sample_script(); bad["scenes"][0]["lines"][0]["speaker"] = "ghost"
        r = self.c.put(f"/api/episodes/{eid}/script", json={"content": bad})
        self.assertEqual(r.status_code, 422)
        self.assertIn("ghost", r.text)
        good = sample_script("Edited title")
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/script", json={"content": good, "note": "tightened"}).json()["version"], 2)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/storyboard/generate").status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/script/approve", json={"comment": "ok"}).status_code, 200)
        # Once approved, the script cannot be edited outside a revision.
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/script", json={"content": good}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/production/start").status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/storyboard/generate").status_code, 200)
        self.env.run_jobs(["generate_storyboard"])
        d = self.c.get(f"/api/episodes/{eid}").json()
        self.assertEqual(d["stage"], "storyboard_review")
        self.assertEqual([s["heading"] for s in d["scenes"]], ["The text", "The twist"])
        # A scene marked for revision blocks storyboard approval until it is edited.
        s1 = d["scenes"][0]["id"]
        self.c.post(f"/api/episodes/{eid}/storyboard/reject", json={"comment": "funnier", "scene_ids": [s1]})
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={}).status_code, 409)
        scene = d["scenes"][0]
        r = self.c.put(f"/api/episodes/{eid}/scenes/{s1}", json={**{k: scene[k] for k in ("heading", "location", "description", "action", "camera")},
                                                                   "lines": scene["lines"] + [{"speaker": "character-01", "text": "Oh no.", "expression": "pleading"}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={}).status_code, 200)
        # Publishing is impossible before a final approved video.
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/publish/approve", json={"confirm": "PUBLISH"}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/publish/start").status_code, 409)
        reviews = self.c.get(f"/api/episodes/{eid}").json()["reviews"]
        self.assertEqual([r["decision"] for r in reviews], ["approved", "rejected", "approved"])

    def test_provider_not_configured_is_a_clear_failure(self):
        providers.set_test_text_responder(None)
        i = self.idea()
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True}).json()["id"]
        [(kind, status, error)] = self.env.run_jobs()
        self.assertEqual(status, "failed")
        self.assertIn("Not configured", error)
        self.assertEqual(self.c.get(f"/api/episodes/{eid}").json()["stage"], "script_pending")

    def test_character_without_art_blocks_production(self):
        r = self.c.post("/api/characters", json={"key": "dad", "name": "Dad", "visual_description": "tall, moustache", "bubble_style": "him"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post(f"/api/characters/{r.json()['id']}/poses/generate", json={"expressions": ["angry"]}).status_code, 409)
        providers.set_test_text_responder(lambda s, p: sample_script(speaker="dad"))
        i = self.idea(characters=["dad"])
        eid = self.c.post(f"/api/ideas/{i['id']}/start", json={}).json()["id"]
        self.env.run_jobs(["generate_script"])
        self.c.post(f"/api/episodes/{eid}/script/approve", json={})
        self.c.post(f"/api/episodes/{eid}/storyboard/generate")
        self.env.run_jobs(["generate_storyboard"])
        self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={})
        self.c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        r = self.c.post(f"/api/episodes/{eid}/production/start")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Dad", r.text)

    def test_settings_never_return_secrets(self):
        import os
        os.environ["OPENAI_API_KEY"] = "sk-secret-value"
        from oddstudio.config import reset_settings
        reset_settings()
        try:
            body = self.c.get("/api/settings").text
            self.assertNotIn("sk-secret-value", body)
            self.assertIn('"openai_api_key":true', body.replace(" ", ""))
            self.assertEqual(self.c.put("/api/settings/text", json={"provider": "mystery"}).status_code, 422)
            self.assertEqual(self.c.put("/api/settings/text", json={"provider": "openai", "model": "x"}).json()["provider"], "openai")
        finally:
            del os.environ["OPENAI_API_KEY"]
            reset_settings()

    def test_signed_media_urls(self):
        chars = self.c.get("/api/characters").json()
        url = chars[0]["assets"][0]["url"]
        self.assertEqual(self.c.get(url).status_code, 200)
        self.assertEqual(self.c.get(url.replace("sig=", "sig=0")).status_code, 403)
        self.assertEqual(self.c.get("/api/media/../../secret?exp=9999999999&sig=x").status_code, 404)


if __name__ == "__main__":
    unittest.main()
