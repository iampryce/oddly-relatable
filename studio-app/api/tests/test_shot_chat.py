"""Chat under each shot (2026-11-26): threads per item kept per episode, the context built on the server (never a key,
never a reference frame), strict proposals (unknown types and fields refused), Apply through the step's own handler
(paid ones refused with 409 without the confirmed price), and an empty balance answered in plain English with nothing
saved. The provider SDKs talk to a mocked HTTP transport: no network, no cost, only fake credentials."""
import json
import unittest

from helpers import Env
from test_shot_frames_dashboard import FlowBase
from test_stick_pipeline import Stub, png_bytes, uninstall

from oddstudio import shot_chat as SC

FAKE = {"openai_api_key": "fake-openai-credential-for-tests", "anthropic_api_key": "fake-anthropic-credential-for-tests",
        "gemini_api_key": "fake-gemini-credential-for-tests", "wavespeed_api_key": "fake-wavespeed-credential-for-tests"}
ANALYSIS = {"characters": {}, "talking_style": {}, "shots": [
    {"shot": 1, "what_the_reference_shows": "a man at a desk", "beats": [
        {"t_start": 0.3, "t_end": 1.2, "character": "Uncle Mortimer", "on_word": "nephew", "expression": "smug",
         "eyes_and_gaze": "looks down at the paper", "head_and_body": "leans back", "hands": "taps the desk",
         "hold_or_move": "hold", "intensity": "clear"}]}]}


def openai_json(obj, tin=900, tout=120):
    return {"id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": "gpt-5.5",
            "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(obj), "annotations": []}]}],
            "usage": {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 10}},
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": []}


def install(status, body):
    seen = []

    def handler(url, headers, content):
        seen.append((url, headers, content))
        return status, body
    SC.set_test_handler(handler)
    return seen


# ------------------------------------------------------------------ pure
class ProposalTest(unittest.TestCase):
    def test_unknown_or_foreign_types_and_fields_are_refused(self):
        with self.assertRaises(ValueError):
            SC.validate_proposal("still", "1", {"type": "delete_episode"})
        with self.assertRaises(ValueError):
            SC.validate_proposal("still", "1", {"type": "update_prompt", "prompt": "x"})      # not a still change
        with self.assertRaises(ValueError):
            SC.validate_proposal("still", "1", {"type": "redo_still", "prompt": "x", "approve": True})   # extra field
        with self.assertRaises(ValueError):
            SC.validate_proposal("acting", "2", {"type": "edit_beat", "shot": 3, "beat_index": 0, "fields": {"hands": "x"}})
        with self.assertRaises(ValueError):
            SC.validate_proposal("acting", "2", {"type": "edit_beat", "shot": 2, "beat_index": 0, "fields": {"colour": "red"}})
        with self.assertRaises(ValueError):
            SC.validate_proposal("acting", "2", {"type": "edit_beat", "shot": 2, "beat_index": 0, "fields": {}})
        with self.assertRaises(ValueError):
            SC.validate_proposal("clip", "2", {"type": "rerender_shot", "settings": {"cfg": 5, "sampler": "euler"}})
        with self.assertRaises(ValueError):
            SC.validate_proposal("prompt", "abc", "update the prompt")

    def test_valid_proposals_and_queued_ones(self):
        p = SC.validate_proposal("acting", "2", {"type": "edit_beat", "shot": 2, "beat_index": 1, "fields": {"intensity": "big"}})
        self.assertEqual(p, {"type": "edit_beat", "shot": 2, "beat_index": 1, "fields": {"intensity": "big"}})
        self.assertEqual(SC.validate_proposal("prompt", "a1", {"type": "update_prompt", "prompt": "New"})["prompt"], "New")
        r = SC.validate_proposal("clip", "1", {"type": "rerender_shot", "settings": {"cfg": 4.5, "steps": 30}})
        self.assertIn("own-GPU", SC.queued_reason(r))
        r = SC.validate_proposal("clip", "1", {"type": "rerender_shot", "settings": {"prompt": "slower", "seconds": 5}})
        self.assertIsNone(SC.queued_reason(r))

    def test_parse_reply_leaves_out_an_invalid_proposal(self):
        text, p, why = SC.parse_reply("still", "1", json.dumps({"reply": "Sure.", "proposal": {"type": "publish"}}))
        self.assertEqual((text, p), ("Sure.", None))
        self.assertIn("not a change this step can make", why)
        text, p, why = SC.parse_reply("still", "1", "plain words, no JSON")
        self.assertEqual((text, p, why), ("plain words, no JSON", None, None))


# ------------------------------------------------------------------ API
class Base(FlowBase):
    def setUp(self):
        super().setUp()
        self.stub = Stub().install()
        from oddstudio.db import new_session
        from oddstudio.models import Setting
        from oddstudio.secrets_store import put_secrets
        with new_session() as db:
            put_secrets(db, dict(FAKE))
            db.add(Setting(key=f"acting:{self.eid}", value={"result": ANALYSIS, "model_used": ["gemini-x"],
                                                            "frames": {"1": [{"t": 0.5, "key": f"private/episodes/{self.eid}/acting/shot1-0.5s.jpg"}]}}))
            db.add(Setting(key=f"prompts:{self.eid}", value={"prompts": [
                {"id": "p1", "kind": "still", "character_id": None, "shot": 1, "notes": "he gloats", "text": "Old prompt",
                 "original": "Old prompt", "status": "approved", "model": "gpt-5.5", "usage": {"input_tokens": 1, "output_tokens": 1}, "usd": 0.0}]}))
            db.commit()
        self.cid = {}
        for key, name in (("mortimer", "Uncle Mortimer"), ("solicitor", "The Solicitor"), ("ralph", "Ralph"), ("sidney", "Sidney")):
            r = self.c.post("/api/characters", json={"key": key, "name": name, "visual_description": "a tweed cap"})
            self.cid[key] = r.json()["id"]

    def tearDown(self):
        SC.set_test_handler(None)
        uninstall()
        super().tearDown()

    def ref(self, step, item, **kw):
        return {"episode_id": self.eid, "step": step, "item": str(item), **kw}

    def send(self, step, item, text="Make him look more smug", answer=None, status=200):
        seen = install(status, answer if answer is not None else openai_json({"reply": "OK.", "proposal": None}))
        est = self.c.post("/api/shot-chat/estimate", json=self.ref(step, item, text=text)).json()
        r = self.c.post("/api/shot-chat/send", json=self.ref(step, item, text=text, confirm_usd=est["usd_max"]))
        return r, seen, est

    def thread(self, step, item):
        return self.c.get("/api/shot-chat/thread", params={"episode_id": self.eid, "step": step, "item": str(item)}).json()


class ThreadAndContextTest(Base):
    def test_thread_storage_per_item(self):
        self.make()
        r, seen, est = self.send("still", 1, answer=openai_json({"reply": "Try a wider grin.", "proposal": {"type": "redo_still", "prompt": "Mortimer grins"}}))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(est["model"], "gpt-5.5")
        self.assertEqual(est["usd_per_mtok"], {"input": 5.0, "output": 30.0})
        t = self.thread("still", 1)
        self.assertEqual([m["role"] for m in t["messages"]], ["user", "assistant"])
        a = t["messages"][1]
        self.assertEqual((a["text"], a["proposal_status"]), ("Try a wider grin.", "pending"))
        self.assertEqual(a["cost"]["usd"], 0.04)
        self.assertAlmostEqual(a["usd"], 900 * 5 / 1e6 + 120 * 30 / 1e6)
        self.assertIn("new still", a["what_will_change"])
        self.assertEqual(self.thread("still", 2)["messages"], [], "each shot has its own thread")
        from oddstudio.db import new_session
        from oddstudio.models import Setting
        with new_session() as db:
            self.assertIn("still:1", db.get(Setting, f"threads:{self.eid}").value["threads"])
        # a master thread is studio-wide
        install(200, openai_json({"reply": "Noted.", "proposal": {"type": "note_only"}}))
        body = {"step": "master", "item": str(self.cid["mortimer"]), "text": "Keep the cap"}
        est = self.c.post("/api/shot-chat/estimate", json=body).json()
        r = self.c.post("/api/shot-chat/send", json={**body, "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["reply"]["proposal_status"], "note")
        with new_session() as db:
            self.assertIn(f"master:{self.cid['mortimer']}", db.get(Setting, "threads:characters").value["threads"])

    def test_context_never_has_keys_or_frames(self):
        self.make()
        from oddstudio.db import new_session
        with new_session() as db:
            ref = SC.Ref(episode_id=self.eid, step="still", item="1")
            cx = SC.build_context(db, ref)
            system = SC.system_prompt(ref, cx)
        self.assertEqual(cx["episode"], "The Unkind Will")
        self.assertEqual(cx["shot"], 1)
        self.assertRegex(cx["time_range"], r"^\d+\.\d-\d+\.\d s$")
        self.assertIn("Uncle Mortimer (image 2)", cx["current_prompt"])
        self.assertTrue(any("smug" in b and "[beat_index 0]" in b for b in cx["acting_beats"]))
        self.assertIn("TRUE STICK MAN", cx["house_style"])
        self.assertTrue(any("tweed cap" in c for c in cx["characters"]))
        self.assertEqual(cx["settings"]["image_model"], "google/nano-banana-2.1/edit")
        for v in FAKE.values():
            self.assertNotIn(v, system)
        self.assertNotIn("private/episodes", system, "reference frames are described by their beats only")
        r, seen, _ = self.send("still", 1)
        self.assertEqual(r.status_code, 200)
        url, headers, sent = seen[0]
        self.assertTrue(url.endswith("/responses"))
        self.assertEqual(headers["authorization"], f"Bearer {FAKE['openai_api_key']}")
        for v in FAKE.values():
            self.assertNotIn(v, sent)
            self.assertNotIn(v, json.dumps(self.thread("still", 1)))
        body = json.loads(sent)
        self.assertEqual((body["model"], body["max_output_tokens"]), ("gpt-5.5", 2000))
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertEqual(body["input"][-1], {"role": "user", "content": "Make him look more smug"})
        # the history goes with the next message (the last 10 at most)
        r, seen, _ = self.send("still", 1, text="And slower")
        body = json.loads(seen[0][2])
        self.assertEqual([m["content"] for m in body["input"]], ["Make him look more smug", "OK.", "And slower"])

    def test_send_needs_the_confirmed_cost(self):
        seen = install(200, openai_json({"reply": "x", "proposal": None}))
        r = self.c.post("/api/shot-chat/send", json=self.ref("acting", 1, text="hi"))
        self.assertEqual(r.status_code, 409)
        r = self.c.post("/api/shot-chat/send", json=self.ref("acting", 1, text="hi", confirm_usd=0.0001))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(seen, [], "nothing is sent without the confirmed cost")
        self.assertEqual(self.thread("acting", 1)["messages"], [])

    def test_settings_validation(self):
        self.assertEqual(self.c.put("/api/settings/shot_chat", json={"provider": "gemini"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/shot_chat", json={"model": "gpt 5; rm"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/shot_chat", json={"provider": "anthropic"}).status_code, 200)
        est = self.c.post("/api/shot-chat/estimate", json=self.ref("acting", 1, text="hi")).json()
        self.assertEqual(est["provider"], "anthropic")


class ApplyTest(Base):
    def test_update_prompt_goes_through_the_prompt_writer(self):
        r, _, _ = self.send("prompt", "p1", answer=openai_json({"reply": "Here.", "proposal": {"type": "update_prompt", "prompt": "New prompt"}}))
        mid = r.json()["reply"]["id"]
        self.assertIsNone(r.json()["reply"].get("cost"), "free change")
        r = self.c.post("/api/shot-chat/apply", json=self.ref("prompt", "p1", message_id=mid))
        self.assertEqual(r.status_code, 200, r.text)
        p = self.c.get(f"/api/episodes/{self.eid}/prompts").json()["prompts"][0]
        self.assertEqual((p["text"], p["status"]), ("New prompt", "draft"), "an applied change needs the owner's approval again")
        self.assertEqual(r.json()["thread"]["messages"][1]["proposal_status"], "applied")
        self.assertEqual(self.c.post("/api/shot-chat/apply", json=self.ref("prompt", "p1", message_id=mid)).status_code, 409)

    def test_edit_beat_goes_through_the_acting_notes(self):
        r, _, _ = self.send("acting", 1, answer=openai_json({"reply": "Bigger.", "proposal": {
            "type": "edit_beat", "shot": 1, "beat_index": 0, "fields": {"intensity": "big", "hands": "slams the desk"}}}))
        mid = r.json()["reply"]["id"]
        r = self.c.post("/api/shot-chat/apply", json=self.ref("acting", 1, message_id=mid))
        self.assertEqual(r.status_code, 200, r.text)
        b = self.c.get(f"/api/episodes/{self.eid}/acting-analysis").json()["result"]["shots"][0]["beats"][0]
        self.assertEqual((b["intensity"], b["hands"], b["expression"]), ("big", "slams the desk", "smug"))

    def test_paid_apply_409_without_confirm_usd(self):
        self.make()
        for k in ("mortimer", "solicitor"):
            cid = self.cid[k]
            self.c.put("/api/stick/style-reference/upload", content=png_bytes(), headers={"Content-Type": "image/png"})
            self.c.post(f"/api/characters/{cid}/stick/master", json={"confirm_usd": 0.08})
            self.env.run_jobs(["stick_master"])
            a = self.c.get(f"/api/characters/{cid}/stick").json()["candidates"][0]
            self.c.post(f"/api/characters/{cid}/stick/assets/{a['id']}/decision", json={"decision": "approve"})
        r, _, _ = self.send("still", 1, answer=openai_json({"reply": "Redo.", "proposal": {"type": "redo_still", "prompt": "Mortimer grins widely"}}))
        mid = r.json()["reply"]["id"]
        from oddstudio.db import new_session
        from oddstudio.models import Job
        def count():
            with new_session() as db:
                return db.query(Job).filter_by(kind="stick_shot_still").count()
        r = self.c.post("/api/shot-chat/apply", json=self.ref("still", 1, message_id=mid))
        self.assertEqual(r.status_code, 409)
        r = self.c.post("/api/shot-chat/apply", json=self.ref("still", 1, message_id=mid, confirm_usd=0.01))
        self.assertEqual(r.status_code, 409, "the still handler refuses another price")
        self.assertEqual(count(), 0, "nothing paid started")
        self.assertEqual(self.thread("still", 1)["messages"][1]["proposal_status"], "pending")
        r = self.c.post("/api/shot-chat/apply", json=self.ref("still", 1, message_id=mid, confirm_usd=0.04))
        self.assertEqual(r.status_code, 200, r.text)
        with new_session() as db:
            j = db.query(Job).filter_by(kind="stick_shot_still").one()
            self.assertEqual(j.payload["prompt"], "Mortimer grins widely")

    def test_rerender_with_cfg_is_queued_not_applied(self):
        r, _, _ = self.send("clip", 1, answer=openai_json({"reply": "Lower cfg.", "proposal": {
            "type": "rerender_shot", "settings": {"cfg": 3.5, "steps": 30}}}))
        m = r.json()["reply"]
        self.assertEqual(m["proposal_status"], "queued")
        self.assertIn("own-GPU", m["proposal_note"])
        r = self.c.post("/api/shot-chat/apply", json=self.ref("clip", 1, message_id=m["id"], confirm_usd=0.3))
        self.assertEqual(r.status_code, 409)

    def test_dismiss(self):
        r, _, _ = self.send("prompt", "p1", answer=openai_json({"reply": "Here.", "proposal": {"type": "update_prompt", "prompt": "Nope"}}))
        mid = r.json()["reply"]["id"]
        r = self.c.post("/api/shot-chat/dismiss", json=self.ref("prompt", "p1", message_id=mid))
        self.assertEqual(r.json()["thread"]["messages"][1]["proposal_status"], "dismissed")
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}/prompts").json()["prompts"][0]["text"], "Old prompt")


class NoCreditTest(Base):
    def test_empty_balance_in_plain_english_and_nothing_saved(self):
        r, seen, _ = self.send("acting", 1, status=429, answer={"error": {
            "message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota", "param": None}})
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["detail"], SC.NO_CREDIT["openai"])
        self.assertIn("platform.openai.com > Billing", r.json()["detail"])
        self.assertIn("switch the assistant in Settings", r.json()["detail"])
        self.assertEqual(self.thread("acting", 1)["messages"], [], "a failed send saves nothing")

    def test_no_key(self):
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        with new_session() as db:
            put_secrets(db, {"openai_api_key": ""})
        r, seen, _ = self.send("acting", 1)
        self.assertEqual(r.status_code, 409)
        self.assertIn("switch the assistant in Settings", r.json()["detail"])
        self.assertEqual(seen, [])

    def test_anthropic_empty_balance(self):
        self.assertEqual(self.c.put("/api/settings/shot_chat", json={"provider": "anthropic"}).status_code, 200)
        r, _, _ = self.send("acting", 1, status=400, answer={"type": "error", "error": {
            "type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API."}})
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["detail"], SC.NO_CREDIT["anthropic"])


if __name__ == "__main__":
    unittest.main()
