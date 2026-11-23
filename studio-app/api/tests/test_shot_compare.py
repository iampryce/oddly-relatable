"""Shot comparison (owner request 2026-11-21): AI video models against the rig on one line of a real episode, from the
studio's own approved art only (approved set plate + the speaker's approved neutral pose) and the line's own recorded
audio. Preparation is free; nothing paid runs until the owner clicks Run for a model after seeing its exact request
and estimate; the experimental budget caps it; every result gets our original line audio and is exactly the line's
length (within one frame); costs are recorded per clip and per second. fal.ai is stubbed: no network, no cost."""
import os
import subprocess
from pathlib import Path

from PIL import Image

from test_audio_stage1b import Base
from test_rig_v2 import v2_figure

import unittest

from oddstudio import engine, fal, providers
from oddstudio import shot_compare as SC

LINE = {"line_id": "l1", "speaker": "mortimer", "text": "I leave everything to the cat.", "start": 1.0, "end": 4.0,
        "expression": "smug", "shot": "medium"}
LINE2 = {"line_id": "l2", "speaker": "mortimer", "text": "I, Mortimer the Magnificent, hereby leave Winifred nothing.",
         "start": 4.2, "end": 5.8, "expression": "neutral", "shot": "close"}


class ToneTest(unittest.TestCase):
    """The phrase matcher: whole words and phrases; sentence-start cues only at the start of a sentence."""

    def test_whole_words_and_sentence_starts(self):
        self.assertIn("pompous", SC.tone_of("I, Mortimer the Magnificent, hereby leave you this.", None, None))
        self.assertNotIn("pompous", SC.tone_of("Oh hi, Mortimer.", None, None), '"hi, " is not "I, "')
        self.assertIn("sarcastic", SC.tone_of("Sure, a lovely day for it.", None, None))
        self.assertNotIn("sarcastic", SC.tone_of("I'm not sure, honestly.", None, None), '"not sure," is not "Sure,"')
        self.assertIn("sarcastic", SC.tone_of("Lovely. Sure, why not.", None, None), "at the start of a later sentence")
        self.assertNotIn("insulting", SC.tone_of("He is a foolish man's foolproof friend.", None, None), "no part-word matches")
        self.assertIn("insulting", SC.tone_of("You fool.", None, None))

    def test_a_line_with_no_cue_gets_a_sensible_tone(self):
        self.assertEqual(SC.tone_of("The keys are on the table.", None, None), "matter-of-fact")
        self.assertEqual(SC.tone_of("Where did you put the keys?", None, None), "puzzled")
        self.assertEqual(SC.tone_of("We won the lottery!", None, None), "excited")
        self.assertEqual(SC.tone_of("The keys are on the table.", "worried", None), "nervous", "the line's mood when no cue")
        for t in SC.tone_of("The keys are on the table.", None, None).split(", "):
            self.assertIn(t, SC.TONES)


class ShotBase(Base):
    """The episode, the speaker's approved art and the recording every shot comparison test starts from."""
    with_ffmpeg = True

    def setUp(self):
        super().setUp()
        os.environ["PUBLIC_URL"] = "https://studio.example"
        self.sent = []
        self.ff = os.environ["FFMPEG"]
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset, Episode, StoryboardScene
        from oddstudio.storage import storage
        from oddstudio.tasks import store_asset
        rec = self.media / "rec.m4a"
        subprocess.run([self.ff, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-c:a", "aac", str(rec)], check=True)
        pose = v2_figure(self.media / "neutral.png")
        engine.make_cutout(pose)
        storage().put_file("characters/mortimer/neutral.png", pose, "image/png")
        with new_session() as s:
            ep = Episode(title="The Will", stage="storyboard_review", source="audio", audio_rights_confirmed=True,
                         set_id="living-room-empty-03", audio_transcript={"lines": [{**LINE, "id": "l1", "words": []}]})
            s.add(ep)
            s.flush()
            a = store_asset(s, ep_id=ep.id, src=rec, key=f"episodes/{ep.id}/rec.m4a", kind="audio", label="rec", content_type="audio/mp4")
            ep.audio_asset_id = a.id
            c = Character(key="mortimer", name="Mortimer", scope="episode", art_status="approved", registry_path="generated")
            s.add(c)
            s.flush()
            ca = CharacterAsset(character_id=c.id, kind="pose", expression="neutral", storage_key="characters/mortimer/neutral.png",
                                width=600, height=1200, feet={"x": 300, "y": 1120}, status="approved", style_version="v2")
            s.add(ca)
            s.flush()
            c.expressions = {"neutral": f"p{ca.id}"}
            sc = StoryboardScene(episode_id=ep.id, position=1, scene_key="s1", heading="The will", location="", description="",
                                 action="", camera="", characters=["mortimer"], lines=[LINE, LINE2], status="draft")
            s.add(sc)
            s.commit()
            self.eid, self.sid = ep.id, sc.id

    def tearDown(self):
        fal.set_test_run(None)
        providers.set_test_text_responder(None)
        os.environ.pop("PUBLIC_URL", None)
        super().tearDown()

    def stub(self, seconds_by_kind):
        def run(endpoint, body, out):
            self.sent.append((endpoint, body))
            kind = "avatar" if "avatar" in endpoint else "i2v"
            dur = seconds_by_kind[kind]
            subprocess.run([self.ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=green:s=720x1280:d={dur}:r=24",
                            "-f", "lavfi", "-i", f"sine=frequency=880:duration={dur}", "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
            return {"video": {"url": "https://fal.example/out.mp4"}, **({"duration": dur} if kind == "avatar" else {})}
        fal.set_test_run(run)

    def plan(self):
        opts = self.c.get("/api/motion/shot/options", params={"episode_id": self.eid}).json()
        line = opts["lines"][0]
        self.assertTrue(line["ready"])
        self.assertEqual([m["id"] for m in opts["models"]], list(SC.MODELS))
        r = self.c.post("/api/motion/shot/plan", json={"episode_id": self.eid, "scene_id": self.sid, "line": 0, "action": line["action"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["shot_prepare"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        return self.c.get("/api/motion/shot").json()["plans"][0]

    def batch_ready(self):
        lines = [{"scene_id": self.sid, "line": 0}, {"scene_id": self.sid, "line": 1}]
        r = self.c.post("/api/motion/shot-batch/plan", json={"episode_id": self.eid, "lines": lines})
        self.assertEqual(r.json()["queued"], 2, "ticking lines plans them by themselves")
        self.assertEqual(self.c.post("/api/motion/shot-batch/plan", json={"episode_id": self.eid, "lines": lines}).json()["queued"], 0,
                         "ticking again reuses the plans")
        self.env.run_jobs(["shot_prepare"])
        b = self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()
        self.assertEqual((b["ready"], b["preparing"]), (2, 0))
        return b["plans"]


class ShotCompareTest(ShotBase):
    def test_batch_auto_planning_with_toned_actions(self):
        plans = {p["line"]: p for p in self.batch_ready()}
        self.assertEqual(self.sent, [], "planning sends nothing")
        a0, a1 = plans[0]["action"], plans[1]["action"]
        self.assertNotIn("talks (neutral)", a0 + a1)
        self.assertIn("smug", a0, "the line's mood")
        self.assertIn("pompous", a1, "a tone cue from the line's own words")
        self.assertIn("insulting", a1)
        self.assertIn("hereby leave Winifred nothing", a1)
        r = self.c.put(f"/api/motion/shot/{plans[1]['id']}/action", json={"action": "glares and says it slowly"})
        self.assertEqual(r.json()["action"], "glares and says it slowly")

    def test_the_writer_writes_tone_and_action_from_the_line_its_neighbours_and_the_notes(self):
        self.c.put("/api/settings/text", json={"provider": "anthropic"})
        seen = []

        def writer(system, prompt):
            seen.append(prompt)
            if "hereby" in prompt.split("Before it:")[0]:
                return {"tone": ["pompous", "mocking", "galactic"], "action": "lifts his chin, taps the will twice and smirks at the room"}
            raise providers.ProviderError("model down (test)")
        providers.set_test_text_responder(writer)
        plans = {p["line"]: p for p in self.batch_ready()}
        self.assertEqual(len(seen), 2, "one writer call per line, in the free preparation")
        self.assertIn("After it: mortimer: I, Mortimer the Magnificent", seen[0], "the line's neighbours")
        self.assertIn("Choose 1 to 3 tones", seen[0])
        p1 = plans[1]
        self.assertEqual((p1["tone"], p1["action_source"]), ("pompous, mocking", "writer"), "only tones from the list")
        self.assertIn("taps the will twice", p1["action"])
        self.assertGreater(p1["action_cost"]["usd"], 0)
        self.assertEqual(p1["action_cost"]["provider"], "anthropic")
        p0 = plans[0]
        self.assertEqual(p0["action_source"], "phrase matcher", "the writer failed: the phrase matcher is used")
        self.assertIn("could not be used", p0["action_note"])
        self.assertIn("smug", p0["action"])
        # the owner's edit is never overwritten by the writer
        self.c.put(f"/api/motion/shot/{p1['id']}/action", json={"action": "glares at the family"})
        from oddstudio.db import new_session
        from oddstudio.models import Episode, StoryboardScene
        with new_session() as s:
            SC.write_action(s, p1["id"], s.get(Episode, self.eid), s.get(StoryboardScene, self.sid))
        p1 = next(p for p in self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()["plans"] if p["id"] == p1["id"])
        self.assertEqual((p1["action"], p1["action_source"]), ("glares at the family", "your edit"))

    def test_an_edit_made_while_the_writer_works_is_kept_and_fallback_prices_are_covered(self):
        self.c.put("/api/settings/text", json={"provider": "openai", "fallback": "anthropic"})
        plans = self.batch_ready()          # no responder: the writer fails, the phrase matcher stays
        pid = plans[0]["id"]
        from oddstudio.db import new_session
        from oddstudio.models import Episode, StoryboardScene

        def writer(system, prompt):
            # the owner saves an edit while the writer is working
            self.c.put(f"/api/motion/shot/{pid}/action", json={"action": "sighs and looks away"})
            return {"tone": ["deadpan"], "action": "shrugs and speaks without looking up"}
        providers.set_test_text_responder(writer)
        with new_session() as s:
            SC.write_action(s, pid, s.get(Episode, self.eid), s.get(StoryboardScene, self.sid))
        p = next(x for x in self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()["plans"] if x["id"] == pid)
        self.assertEqual((p["action"], p["action_source"]), ("sighs and looks away", "your edit"))
        with new_session() as s:
            c = SC.writer_cost(s, "x" * 4000)
        self.assertIn("fallback anthropic", c["note"])
        self.assertGreater(c["usd"], 0.002, "the higher (fallback) price is used for the estimate")

    def test_no_writer_without_a_text_provider(self):
        providers.set_test_text_responder(lambda s, p: self.fail("no text call without a provider in Settings"))
        plans = self.batch_ready()
        self.assertTrue(all(p["action_source"] == "phrase matcher" and not p.get("action_cost") for p in plans))

    def test_one_summary_one_confirm_and_the_cap(self):
        plans = self.batch_ready()
        ids = [p["id"] for p in plans]
        body = {"plan_ids": ids, "models": ["rig", "kling-2.6-pro-i2v", "kling-avatar-v2-standard"]}
        s = self.c.post("/api/motion/shot-batch/run", json=body).json()
        self.assertEqual(s["clips"], 4, "2 lines x 2 paid models (the rig is free)")
        self.assertEqual(s["total_usd"], round(0.35 + 0.1686 + 0.35 + 0.1124, 4))
        self.assertTrue(s["fits"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.c.post("/api/motion/shot-batch/run", json={**body, "confirm": True}).status_code, 409,
                         "the confirm must carry the total the owner saw")
        self.assertEqual(self.c.post("/api/motion/shot-batch/run", json={**body, "confirm": True, "expected_usd": 0.5}).status_code, 409)
        self.c.put("/api/settings/motion", json={"budget_usd": 0.9})
        s = self.c.post("/api/motion/shot-batch/run", json=body).json()
        self.assertFalse(s["fits"])
        r = self.c.post("/api/motion/shot-batch/run", json={**body, "confirm": True, "expected_usd": s["total_usd"]})
        self.assertEqual(r.status_code, 409, "over the cap")
        self.c.put("/api/settings/motion", json={"budget_usd": 25})
        r = self.c.post("/api/motion/shot-batch/run", json={**body, "confirm": True, "expected_usd": s["total_usd"]})
        self.assertEqual(r.json()["queued"], 4, "ONE confirm queues exactly the summarised clips")
        self.assertEqual(self.c.post("/api/motion/shot-batch/run", json=body).json()["pending_usd"], s["total_usd"],
                         "approved but not yet charged: counted against the cap")
        self.assertEqual(self.c.post("/api/motion/shot-batch/run", json=body).json()["clips"], 0, "nothing runs twice")

    def test_result_grid_with_a_failed_clip_and_its_retry(self):
        plans = self.batch_ready()
        self.stub({"i2v": 5, "avatar": 3.04})
        broken = {"on": True}
        good = fal._test_run

        def run(endpoint, body, out):
            if "avatar" in endpoint and broken["on"]:
                raise RuntimeError("fal.ai: generation failed (test)")
            return good(endpoint, body, out)
        fal.set_test_run(run)
        body = {"plan_ids": [plans[0]["id"]], "models": ["kling-2.6-pro-i2v", "kling-avatar-v2-standard"],
                "framing": {"kling-2.6-pro-i2v": "medium"}}
        s = self.c.post("/api/motion/shot-batch/run", json=body).json()
        self.c.post("/api/motion/shot-batch/run", json={**body, "confirm": True, "expected_usd": s["total_usd"]})
        self.env.run_jobs(["shot_generate"])
        i2v = next(b for e, b in self.sent if "image-to-video" in e)
        self.assertIn("first-frame-medium", i2v["start_image_url"], "the confirmed framing override is the frame sent")
        row = next(p for p in self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()["plans"] if p["id"] == plans[0]["id"])
        self.assertEqual(row["results"]["kling-2.6-pro-i2v"]["status"], "done")
        self.assertTrue(row["results"]["kling-2.6-pro-i2v"]["url"])
        self.assertEqual(row["results"]["kling-avatar-v2-standard"]["status"], "failed")
        self.assertIn("generation failed", row["results"]["kling-avatar-v2-standard"]["error"])
        broken["on"] = False
        self.assertEqual(self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "kling-avatar-v2-standard"}).status_code, 200,
                         "a single retry for the failed clip")
        self.assertEqual(self.c.post(f"/api/motion/shot/{plans[0]['id']}/run", json={"model": "kling-2.6-pro-i2v"}).status_code, 409,
                         "a done clip is not run again")
        self.env.run_jobs(["shot_generate"])
        row = next(p for p in self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()["plans"] if p["id"] == plans[0]["id"])
        self.assertEqual(row["results"]["kling-avatar-v2-standard"]["status"], "done")
        self.assertTrue(row["results"]["kling-avatar-v2-standard"]["check"]["length_ok"])

    def test_free_preparation_from_our_own_art_and_audio(self):
        p = self.plan()
        self.assertEqual(p["status"], "ready")
        self.assertTrue(p["urls_ok"])
        self.assertEqual(self.sent, [], "nothing is sent to fal while planning")
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as s:
            frame = storage().get_to_file(s.get(Asset, p["frame_asset_id"]).storage_key, self.media / "f.png")
            wav = storage().get_to_file(s.get(Asset, p["audio_asset_id"]).storage_key, self.media / "l.wav")
        self.assertEqual(Image.open(frame).size, (720, 1280))
        self.assertAlmostEqual(SC.stream_seconds(wav)["audio"], 3.0, delta=1 / 30)
        self.assertIn("rig render of this line is not available", p["rig_error"], "no voice slices in this test: the rig is skipped, not faked")
        req = {r["model"]: r for r in p["requests"]}
        self.assertEqual(req["kling-2.6-pro-i2v"]["estimate"], {"billed_seconds": 5, "usd": 0.35, "note": ""})
        self.assertEqual(req["kling-avatar-v2-standard"]["estimate"]["usd"], 0.1686)
        self.assertFalse(req["kling-2.6-pro-i2v"]["body"]["generate_audio"])
        self.assertIn("the line's own recorded audio", req["kling-avatar-v2-standard"]["sends"])

    def test_the_avatar_gets_a_medium_shot_by_default_and_wide_is_an_option(self):
        p = self.plan()
        req = {r["model"]: r for r in p["requests"]}
        self.assertEqual((req["kling-avatar-v2-standard"]["framing"], req["kling-2.6-pro-i2v"]["framing"]), ("medium", "wide"))
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as s:
            for f, a in p["frame_assets"].items():
                self.assertEqual(Image.open(storage().get_to_file(s.get(Asset, a).storage_key, self.media / f"{f}.png")).size, (720, 1280))
        # the geometry, measured on a plain plate (a real plate has dark lines of its own)
        plain = self.media / "plain.png"
        Image.new("RGB", (941, 1672), (200, 180, 150)).save(plain)
        blk = {"floor_y": 1440}
        imgs = {f: Image.open(SC.compose(plain, self.media / "neutral.png", blk, 941, 1672, self.media / f"g-{f}.png", f)).convert("RGB")
                for f in SC.FRAMINGS}

        def figure_box(im):
            # the figure's bold black outline: dark pixels (the plate has none this dark at this size)
            px = im.load()
            ys = [y for y in range(0, im.height, 4) for x in range(0, im.width, 4) if sum(px[x, y]) < 90]
            xs = [x for y in range(0, im.height, 4) for x in range(0, im.width, 4) if sum(px[x, y]) < 90]
            return min(xs), min(ys), max(xs), max(ys)
        wx0, wy0, wx1, wy1 = figure_box(imgs["wide"])
        mx0, my0, mx1, my1 = figure_box(imgs["medium"])
        self.assertLess((wy1 - wy0) / 1280, 0.5, "wide: the whole figure, under half the frame")
        self.assertLess(my0 / 1280, 0.12, "medium: the head near the top")
        self.assertGreater((my1 - my0) / 1280, 0.85, "medium: head and upper body fill most of the frame")
        self.assertGreater((mx1 - mx0), 1.8 * (wx1 - wx0), "medium: the figure is much larger")
        self.stub({"i2v": 5, "avatar": 3.04})
        r = self.c.put(f"/api/motion/shot/{p['id']}/framing", json={"model": "kling-avatar-v2-standard", "framing": "wide"})
        self.assertEqual(r.json()["requests"][1]["framing"], "wide")
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/framing", json={"model": "kling-avatar-v2-standard", "framing": "close"}).status_code, 422)
        self.c.put(f"/api/motion/shot/{p['id']}/framing", json={"model": "kling-avatar-v2-standard", "framing": "medium"})
        for m in SC.MODELS:
            self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": m})
        self.env.run_jobs(["shot_generate"])
        sent = {("avatar" if "avatar" in e else "i2v"): b for e, b in self.sent}
        with new_session() as s:
            key = lambda f: s.get(Asset, p["frame_assets"][f]).storage_key
            self.assertIn(key("medium").split("/")[-1], sent["avatar"]["image_url"], "the avatar is sent the medium frame")
            self.assertIn(key("wide").split("/")[-1], sent["i2v"]["start_image_url"], "image-to-video keeps the wide frame")

    def test_nothing_runs_without_the_click_and_the_budget_caps_it(self):
        p = self.plan()
        self.c.put("/api/settings/motion", json={"budget_usd": 0.2})
        r = self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": "kling-2.6-pro-i2v"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("experimental budget", r.text)
        self.c.put("/api/settings/motion", json={"budget_usd": 0.4})
        self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": "kling-2.6-pro-i2v"}).status_code, 200)
        r = self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": "kling-avatar-v2-standard"})
        self.assertEqual(r.status_code, 409, "the first approval is counted before it runs: 0.35 + 0.17 > 0.40")
        self.assertIn("already approved and not yet run", r.text)
        self.assertEqual(self.sent, [], "approving queues; nothing is sent until the worker runs it")

    def own_png(self, w=1000, h=1000) -> bytes:
        import io
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        im.paste((20, 90, 40, 255), (w // 4, h // 4, 3 * w // 4, 3 * h // 4))
        b = io.BytesIO()
        im.save(b, "PNG")
        return b.getvalue()

    def upload_own(self, pid, data, ctype="image/png", own_art=True):
        return self.c.put(f"/api/motion/shot/{pid}/own-frame", params={"own_art": "true"} if own_art else {},
                          content=data, headers={"Content-Type": ctype})

    def test_my_own_first_frame_is_a_second_plan_beside_the_original(self):
        providers.set_test_text_responder(lambda s, p: self.fail("adding my own frame makes no text call"))
        p = self.plan()
        self.assertEqual(self.upload_own(p["id"], self.own_png(), own_art=False).status_code, 422, "the own-art confirmation")
        self.assertEqual(self.upload_own(p["id"], b"hello", ctype="text/plain").status_code, 415)
        self.assertEqual(self.upload_own(p["id"], b"not a png at all").status_code, 422)
        self.assertEqual(self.upload_own(p["id"], b"").status_code, 422)
        self.assertEqual(self.c.put(f"/api/motion/shot/{p['id']}/own-frame", params={"own_art": "true"}, content=b"x",
                                    headers={"Content-Type": "image/png", "Content-Length": str(SC.OWN_FRAME_MAX_BYTES + 1)}).status_code, 413)
        r = self.upload_own(p["id"], self.own_png())
        self.assertEqual(r.status_code, 200, r.text)
        own = r.json()
        self.assertEqual((own["base_plan"], own["status"]), (p["id"], "ready"))
        self.assertEqual("your 1000x1000 image, centre-cropped to 9:16, scaled to 720x1280", own["own_frame"]["note"])
        for k in ("line", "seconds", "action", "audio_asset_id", "rig_asset_id", "rig_error", "set_id"):
            self.assertEqual(own.get(k), p.get(k), f"{k}: the same line, audio, action and rig render as the original")
        self.assertTrue(own["audio_asset_id"])
        self.assertNotEqual(own["frame_asset_id"], p["frame_asset_id"])
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as s:
            f = storage().get_to_file(s.get(Asset, own["frame_asset_id"]).storage_key, self.media / "own.png")
        with Image.open(f) as im:
            self.assertEqual((im.size, im.mode, im.getpixel((5, 5))), ((720, 1280), "RGB", (255, 255, 255)), "flattened onto white")
        avatar = next(q for q in own["requests"] if q["model"] == "kling-avatar-v2-standard")
        self.assertTrue(avatar["sends"][0].startswith("your own first frame"))
        self.assertEqual(avatar["body"]["image_url"], "<your first frame shown>")
        self.assertEqual(avatar["estimate"], next(q for q in p["requests"] if q["model"] == "kling-avatar-v2-standard")["estimate"])
        self.assertEqual(self.upload_own(own["id"], self.own_png()).status_code, 409, "uploads go against the original-art plan")
        # the batch keeps the original as the line's plan and lists mine beside it
        b = self.c.get("/api/motion/shot-batch", params={"episode_id": self.eid}).json()
        self.assertEqual([x["id"] for x in b["plans"] if x["line"] == 0], [p["id"]])
        self.assertEqual([x["id"] for x in b["own_plans"]], [own["id"]])
        r = self.c.post("/api/motion/shot-batch/plan", json={"episode_id": self.eid, "lines": [{"scene_id": self.sid, "line": 0}]})
        self.assertEqual(r.json()["queued"], 0, "the original-art plan is reused, not replaced")
        # the same line twice, each by its own Run
        self.assertEqual(self.sent, [])
        self.stub({"i2v": 5, "avatar": 3.04})
        for pid in (p["id"], own["id"]):
            self.assertEqual(self.c.post(f"/api/motion/shot/{pid}/run", json={"model": "kling-avatar-v2-standard"}).status_code, 200)
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual([x[1] for x in ran], ["succeeded", "succeeded"], ran)
        imgs = [b["image_url"] for _, b in self.sent]
        self.assertIn("first-frame-medium.png", imgs[0])
        self.assertIn(f"{own['id']}/first-frame-own.png", imgs[1])
        self.assertEqual(self.sent[0][1]["audio_url"].split("?")[0], self.sent[1][1]["audio_url"].split("?")[0], "the same line audio")
        self.assertEqual(self.sent[0][1]["prompt"], self.sent[1][1]["prompt"], "the same action text")
        by_id = {x["id"]: x for x in self.c.get("/api/motion/shot").json()["plans"]}
        for pid in (p["id"], own["id"]):
            res = by_id[pid]["results"]["kling-avatar-v2-standard"]
            self.assertEqual(res["status"], "done")
            self.assertTrue(res["check"]["length_ok"])

    def test_own_frame_needs_a_ready_plan_and_a_real_image(self):
        self.assertEqual(self.upload_own("nope", self.own_png()).status_code, 404)
        with self.assertRaises(ValueError):
            SC.own_frame_image(self.media / "missing.png", self.media / "o.png")
        tall = self.media / "tall.png"
        Image.new("RGB", (720, 1280), (1, 2, 3)).save(tall)
        self.assertEqual(SC.own_frame_image(tall, self.media / "o.png"), "your 720x1280 image", "already 9:16 at size: untouched")

    def test_results_keep_our_audio_and_the_line_length(self):
        p = self.plan()
        self.stub({"i2v": 5, "avatar": 3.04})
        for m in SC.MODELS:
            self.assertEqual(self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": m}).status_code, 200)
        ran = self.env.run_jobs(["shot_generate"])
        self.assertEqual([x[1] for x in ran], ["succeeded", "succeeded"], ran)
        i2v_body = dict(self.sent[0][1])
        self.assertTrue(i2v_body.pop("start_image_url").startswith("https://studio.example/"))
        self.assertEqual(i2v_body, {k: v for k, v in SC.request_for("kling-2.6-pro-i2v", p["action"], "", "", 3.0).items() if k != "start_image_url"},
                         "exactly the request shown")
        self.assertTrue(self.sent[1][1]["audio_url"].startswith("https://studio.example/"), "the avatar gets OUR line audio")
        done = self.c.get("/api/motion/shot").json()["plans"][0]["results"]
        for m, r in done.items():
            self.assertEqual(r["status"], "done")
            self.assertTrue(r["check"]["length_ok"], r["check"])
            self.assertAlmostEqual(r["check"]["video_seconds"], 3.0, delta=1 / 30)
        self.assertEqual(done["kling-2.6-pro-i2v"]["actual_usd"], 0.35)
        self.assertEqual(done["kling-2.6-pro-i2v"]["per_second_usd"], round(0.35 / 3.0, 4))
        self.assertEqual(done["kling-avatar-v2-standard"]["actual_usd"], round(0.0562 * 3.04, 4))
        led = fal.spent
        from oddstudio.db import new_session
        with new_session() as s:
            self.assertAlmostEqual(led(s)["total"], 0.35 + round(0.0562 * 3.04, 4), places=3)
