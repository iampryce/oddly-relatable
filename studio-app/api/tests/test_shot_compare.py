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

from oddstudio import engine, fal
from oddstudio import shot_compare as SC

LINE = {"line_id": "l1", "speaker": "mortimer", "text": "I leave everything to the cat.", "start": 1.0, "end": 4.0,
        "expression": "smug", "shot": "medium"}


class ShotCompareTest(Base):
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
                                 action="", camera="", characters=["mortimer"], lines=[LINE], status="draft")
            s.add(sc)
            s.commit()
            self.eid, self.sid = ep.id, sc.id

    def tearDown(self):
        fal.set_test_run(None)
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

    def test_nothing_runs_without_the_click_and_the_budget_caps_it(self):
        p = self.plan()
        self.c.put("/api/settings/motion", json={"budget_usd": 0.2})
        r = self.c.post(f"/api/motion/shot/{p['id']}/run", json={"model": "kling-2.6-pro-i2v"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("experimental budget", r.text)
        self.assertEqual(self.sent, [])

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
