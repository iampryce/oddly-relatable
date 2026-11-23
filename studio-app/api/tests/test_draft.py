"""The first-draft assembly and the episode's Talking shots section: the timeline (script order with the recording's
pauses), placement (every head at one scale; the talking clip exactly over its pose), the "no clip yet" fallback, a
keyed clip in the draft, the draft labelled and never the episode's video, and the total cost shown before Run.
Nothing paid: WaveSpeed is never called here, and no text call is made."""
import subprocess
import unittest

import numpy as np
from PIL import Image

from test_shot_compare import ShotBase
import test_talking_shots  # noqa: F401  (ShotBase.ready / ShotBase.row)

from oddstudio import draft as D
from oddstudio import providers
from oddstudio import shot_compare as SC

IT = "wavespeed-infinitetalk-fast"


class TimelineTest(unittest.TestCase):
    def test_script_order_with_the_recordings_pauses(self):
        scenes = [{"lines": [{"start": 0.0, "end": 6.22}]},
                  {"lines": [{"start": 9.8, "end": 15.72}, {"start": 7.32, "end": 8.76}]},   # out of order in the list
                  {"lines": [{"start": 19.62, "end": 21.44}]}]
        segs = D.timeline(scenes, 25.0)
        self.assertEqual([(s["scene"], s["line"], s["start"], s["end"]) for s in segs], [
            (0, 0, 0.0, 6.22), (0, None, 6.22, 7.32),             # scene 1, then the pause before scene 2's first line
            (1, 1, 7.32, 8.76), (1, None, 8.76, 9.8), (1, 0, 9.8, 15.72), (1, None, 15.72, 19.62),
            (2, 0, 19.62, 21.44), (2, None, 21.44, 25.0)])
        self.assertEqual([s["start"] for s in segs][1:], [s["end"] for s in segs][:-1], "no gap and no overlap")
        self.assertEqual(D.scene_ranges(segs), [(0, 0.0, 7.32), (1, 7.32, 19.62), (2, 19.62, 25.0)])

    def test_a_late_first_line_starts_with_a_pause(self):
        segs = D.timeline([{"lines": [{"start": 1.0, "end": 4.0}, {"start": 4.2, "end": 5.8}]}], 6.0)
        self.assertEqual([s["line"] for s in segs], [None, 0, None, 1, None])


class PlacementTest(unittest.TestCase):
    def test_every_head_at_one_scale_and_the_clip_exactly_over_its_pose(self):
        fit = D.contain(1024, 1536)
        self.assertAlmostEqual(fit["s"], 1080 / 1024)
        self.assertAlmostEqual(fit["oy"], (1920 - 1536 * 1080 / 1024) / 2)
        mort = {"fig_h": 1400, "neck_x": 292, "hip_y": 840, "head_w": 586}
        ralph = {"fig_h": 1000, "neck_x": 200, "hip_y": 600, "head_w": 420}
        seat = {"x": 180, "hip_y": 773, "feet_y": 837}
        pm, pr = D.placement(mort, seat, 483, fit), D.placement(ralph, {"x": 530, "hip_y": 920, "feet_y": 1068}, 483, fit)
        self.assertAlmostEqual(pm["head_w"], 586 / 1400 * 483 * fit["s"], places=6, msg="the cast height and the pose's own head ratio")
        self.assertAlmostEqual(pr["head_w"], 420 / 1000 * 483 * fit["s"], places=6)
        self.assertAlmostEqual(pm["x"] + 292 * pm["scale"], fit["ox"] + 180 * fit["s"], places=6, msg="the neck over the seat")
        self.assertAlmostEqual(pm["y"] + 840 * pm["scale"], fit["oy"] + 773 * fit["s"], places=6, msg="the hips on the seat")
        self.assertAlmostEqual(pm["legs"] * 483 / 1400, 837 - 773, places=6, msg="the legs end on the seat's feet line")
        lay = {"scale": 1.13, "x": 30, "y": 36}
        cp = D.clip_placement(pm, lay)
        # the clip's head (the pose's head at lay.scale) lands at exactly the pose's head size and place
        self.assertAlmostEqual(586 * lay["scale"] * cp["scale"], pm["head_w"], places=6)
        self.assertAlmostEqual(cp["x"] + lay["x"] * cp["scale"], pm["x"], places=6)
        self.assertAlmostEqual(cp["y"] + lay["y"] * cp["scale"], pm["y"], places=6)
        self.assertEqual(D.placement(mort, {**seat, "behind_desk": True}, 483, fit)["legs"], 0.0, "behind a desk: no legs")
        stand = D.placement(ralph, {"x": 500, "floor_y": 1498}, 530, fit)
        self.assertAlmostEqual(stand["y"] + 1000 * stand["scale"], fit["oy"] + 1498 * fit["s"], places=6, msg="standing: feet on the floor")


MORT = {"fig_h": 1400, "fig_w": 586, "neck_x": 292, "neck_y": 542, "vest_y": 619, "hip_y": 957, "head_w": 586}
RALPH = {"fig_h": 1460, "fig_w": 590, "neck_x": 294, "neck_y": 560, "vest_y": 640, "hip_y": 1000, "head_w": 588}


def boxes_for(seats: dict, h: float = 481) -> dict:
    geo = {"m": MORT, "r": RALPH}
    return {k: D.char_box(geo[k], D.placement(geo[k], seat, h, D.IDENTITY)) for k, seat in seats.items()}


class CameraTest(unittest.TestCase):
    def test_everyone_inside_the_safe_margin_the_frame_filled_and_heads_a_third_down(self):
        boxes = boxes_for({"m": {"x": 180, "hip_y": 773, "feet_y": 837}, "r": {"x": 530, "hip_y": 920, "feet_y": 1068}})
        cam = D.camera(boxes, 1024, 1536)
        self.assertAlmostEqual(cam["w"] / cam["h"], 1080 / 1920, places=4, msg="9:16")
        m = D.SAFE_MARGIN * cam["w"]
        for k, b in boxes.items():
            self.assertGreaterEqual(b["left"], cam["x"] + m - 0.5, k)
            self.assertLessEqual(b["right"], cam["x"] + cam["w"] - m + 0.5, k)
        self.assertTrue(0 <= cam["x"] and cam["x"] + cam["w"] <= 1024 and 0 <= cam["y"] and cam["y"] + cam["h"] <= 1536, "inside the plate")
        fit = D.crop_fit(cam)
        # no bars: the plate covers the whole frame
        self.assertLessEqual(fit["ox"], 0.01)
        self.assertLessEqual(fit["oy"], 0.01)
        self.assertGreaterEqual(fit["ox"] + 1024 * fit["s"], 1080 - 0.01)
        self.assertGreaterEqual(fit["oy"] + 1536 * fit["s"], 1920 - 0.01)
        head = sum(b["head_y"] for b in boxes.values()) / 2
        self.assertAlmostEqual((head - cam["y"]) / cam["h"], 1 / 3, delta=0.01, msg="the head line a third of the way down")
        self.assertIn("scaled up", " ".join(cam["notes"]), "a crop narrower than 1080 plate px is upscaled, and said")
        self.assertNotIn("outside the safe margin", " ".join(cam["notes"]))

    def test_head_sizes_keep_their_ratio_through_the_crop_and_the_clip_still_matches(self):
        seat_m, seat_r = {"x": 180, "hip_y": 773, "feet_y": 837}, {"x": 530, "hip_y": 920, "feet_y": 1068}
        cam = D.camera(boxes_for({"m": seat_m, "r": seat_r}), 1024, 1536)
        before = [D.placement(g, s_, 481, D.contain(1024, 1536)) for g, s_ in ((MORT, seat_m), (RALPH, seat_r))]
        after = [D.placement(g, s_, 481, D.crop_fit(cam)) for g, s_ in ((MORT, seat_m), (RALPH, seat_r))]
        self.assertAlmostEqual(before[0]["head_w"] / before[1]["head_w"], after[0]["head_w"] / after[1]["head_w"], places=9)
        self.assertGreater(after[0]["head_w"], before[0]["head_w"], "the whole composition scales up with the crop")
        lay = {"scale": 1.13, "x": 30, "y": 36}
        cp = D.clip_placement(after[0], lay)
        self.assertAlmostEqual(586 * lay["scale"] * cp["scale"], after[0]["head_w"], places=6, msg="the talking clip's head still matches")

    def test_a_set_too_narrow_for_everyone_never_gets_bars_and_names_who_is_cut(self):
        boxes = boxes_for({"m": {"x": 180, "hip_y": 773, "feet_y": 837}, "r": {"x": 940, "hip_y": 925, "feet_y": 1068}})
        cam = D.camera(boxes, 1024, 1536)
        self.assertAlmostEqual(cam["w"], 864, places=1, msg="the widest 9:16 crop inside a 1024x1536 plate")
        self.assertAlmostEqual(cam["h"], 1536, places=1)
        self.assertTrue(0 <= cam["x"] <= 1024 - 864)
        self.assertIn("outside the safe margin", cam["notes"][0])
        self.assertIn("m", cam["notes"][0])

    def test_an_owners_crop_stays_inside_the_plate(self):
        self.assertEqual(D.check_crop({"x": 100, "y": 50, "w": 540}, 1024, 1536), {"x": 100.0, "y": 50.0, "w": 540.0, "h": 960.0})
        for bad in ({"x": 600, "y": 0, "w": 540}, {"x": 0, "y": 700, "w": 540}, {"x": 0, "y": 0, "w": 900}, {"x": -5, "y": 0, "w": 400}):
            with self.assertRaises(ValueError):
                D.check_crop(bad, 1024, 1536)


def frame_at(ff: str, video, t: float, out) -> np.ndarray:
    subprocess.run([ff, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(out)], check=True)
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def red_tag(f: np.ndarray) -> bool:
    """The "no clip yet" mark: a large block of its own red (200, 30, 30) near the top of the frame."""
    band = f[100:220]
    red = (abs(band[..., 0] - 200) < 25) & (band[..., 1] < 60) & (band[..., 2] < 60)
    return bool(red.sum() > 15000)


def cyan(f: np.ndarray) -> int:
    return int(((f[..., 0] < 90) & (f[..., 1] > 190) & (f[..., 2] > 190)).sum())


class DraftTest(ShotBase):
    def draft(self):
        r = self.c.post(f"/api/episodes/{self.eid}/draft")
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["episode_draft"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        d = self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()["draft"]
        from oddstudio.db import new_session
        from oddstudio.models import Asset, Job
        from oddstudio.storage import storage
        with new_session() as s:
            res = s.get(Job, d["job_id"]).result
            path = storage().get_to_file(s.get(Asset, res["asset_id"]).storage_key, self.media / "draft.mp4")
        return d, res, path

    def test_lines_without_a_clip_show_the_pose_and_a_mark_and_the_draft_is_never_the_episodes_video(self):
        providers.set_test_text_responder(lambda s, p: self.fail("no text call"))
        d, res, path = self.draft()
        self.assertEqual((res["with_clip"], len(res["lines"])), (0, 2))
        self.assertTrue(d["label"].startswith("Draft: not for publishing"))
        probe = subprocess.run([self.ff.replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                                "-of", "json", str(path)], capture_output=True, text=True).stdout
        import json
        info = json.loads(probe)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]), "the recording is the sound")
        self.assertAlmostEqual(float(info["format"]["duration"]), 6.0 + D.END_CARD_S, delta=0.15, msg="the recording, then the end card")
        self.assertTrue(red_tag(frame_at(self.ff, path, 2.0, self.media / "a.png")), "line 1: 'no clip yet'")
        self.assertFalse(red_tag(frame_at(self.ff, path, 0.5, self.media / "b.png")), "the pause before it: no mark")
        self.assertEqual(len(d["pieces"]), 1, "one scene, one piece")
        lib = self.c.get("/api/library").json()
        vids = [v for e in lib if e["id"] == self.eid for v in e["videos"]]
        self.assertTrue(all(v["draft"] for v in vids) and len(vids) == 2, "the draft and its scene piece, marked as drafts")
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            self.assertIsNone(s.get(Episode, self.eid).video_asset_id, "never the episode's video: never offered to publishing")

    def test_a_keyed_clip_plays_over_the_speakers_place_during_its_line(self):
        p = self.ready()
        # a keyed clip: a cyan square in the cutout's frame, transparent around it, as long as line 1 (3.0 s)
        webm = self.media / "k.webm"
        enc = subprocess.Popen([self.ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "720x900", "-r", "30", "-i", "-",
                                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(webm)], stdin=subprocess.PIPE)
        f = np.zeros((900, 720, 4), np.uint8)
        f[150:600, 200:520] = (0, 255, 255, 255)
        for _ in range(90):
            enc.stdin.write(f.tobytes())
        enc.stdin.close()
        self.assertEqual(enc.wait(), 0)
        from oddstudio.db import new_session
        from oddstudio.tasks import store_asset
        with new_session() as s:
            a = store_asset(s, ep_id=self.eid, src=webm, key=f"episodes/{self.eid}/shot-compare/{p['id']}/k.webm", kind="video",
                            label="keyed", content_type="video/webm")
            recs = SC.records(s)
            recs[p["id"]]["results"][IT] = {"status": "done", "key": {"status": "done", "keyed_asset_id": a.id}}
            SC.save(s, recs)
            s.commit()
        d, res, path = self.draft()
        self.assertEqual([r["clip"] for r in res["lines"]], [True, False])
        self.assertGreater(cyan(frame_at(self.ff, path, 2.5, self.media / "c.png")), 2000, "the clip over the speaker in line 1")
        self.assertFalse(red_tag(frame_at(self.ff, path, 2.5, self.media / "c2.png")))
        self.assertEqual(cyan(frame_at(self.ff, path, 4.1, self.media / "d.png")), 0, "not in the pause after it")
        self.assertTrue(red_tag(frame_at(self.ff, path, 5.0, self.media / "e.png")), "line 2 has no clip yet")
        rows = self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()["lines"]
        self.assertEqual([r["status"] for r in rows], ["keyed", "not run"])


class CameraFlowTest(ShotBase):
    def test_the_workspace_shows_the_crop_and_the_owners_crop_is_used(self):
        cams = self.c.get(f"/api/episodes/{self.eid}/draft/cameras").json()["scenes"]
        self.assertEqual(len(cams), 1)
        sc = cams[0]
        self.assertTrue(sc["boxes"] and sc["computed"]["w"] > 0 and sc["own"] is None)
        pw, ph = sc["plate"]["w"], sc["plate"]["h"]
        r = self.c.put(f"/api/episodes/{self.eid}/draft/cameras", json={"scene_id": sc["scene_id"], "crop": {"x": 0, "y": 0, "w": pw + 50}})
        self.assertEqual(r.status_code, 422, "never wider than the plate: that would leave bars")
        own = {"x": 10, "y": 20, "w": round(pw * 0.6)}
        r = self.c.put(f"/api/episodes/{self.eid}/draft/cameras", json={"scene_id": sc["scene_id"], "crop": own})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["scenes"][0]["own"]["w"], own["w"])
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/draft").status_code, 200)
        self.assertEqual(self.env.run_jobs(["episode_draft"])[0][1], "succeeded")
        from oddstudio.db import new_session
        from oddstudio.models import Job
        d = self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()["draft"]
        with new_session() as s:
            res = s.get(Job, d["job_id"]).result
        self.assertEqual(res["crops"]["1"]["w"], own["w"], "the draft used the owner's crop")
        self.assertIsInstance(d["notes"], list)
        r = self.c.put(f"/api/episodes/{self.eid}/draft/cameras", json={"scene_id": sc["scene_id"], "crop": None})
        self.assertIsNone(r.json()["scenes"][0]["own"], "back to the computed crop")


class TalkingSectionTest(ShotBase):
    def test_the_total_estimate_caps_and_budget_before_run(self):
        providers.set_test_text_responder(lambda s, p: self.fail("preparing for talking shots makes no text call"))
        t = self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()
        self.assertEqual([(r["status"], r["seconds"], r["estimate_usd"]) for r in t["lines"]],
                         [("not run", 3.0, 0.045), ("not run", 1.6, 0.045)], "audio rounded up per line, 3 s minimum, $0.015/s")
        self.assertIn("budget_usd", t)
        lines = [{"scene_id": r["scene_id"], "line": r["line"]} for r in t["lines"]]
        r = self.c.post(f"/api/episodes/{self.eid}/talking-shots/prepare", json={"lines": lines})
        self.assertEqual(r.json()["queued"], 2)
        ran = self.env.run_jobs(["shot_prepare"])
        self.assertEqual([x[1] for x in ran], ["succeeded", "succeeded"])
        rows = self.c.get(f"/api/episodes/{self.eid}/talking-shots").json()["lines"]
        self.assertTrue(all(r["plan_ready"] and r["blocked"] == "" and r["cap_usd"] == 0.5 for r in rows))
        plans = {x["id"]: x for x in self.c.get("/api/motion/shot").json()["plans"]}
        self.assertTrue(all("rig_asset_id" not in plans[r["plan_id"]] and "rig_error" not in plans[r["plan_id"]] for r in rows),
                        "no rig render for talking-only plans")
        s = self.c.post("/api/motion/shot-batch/run", json={"plan_ids": [r["plan_id"] for r in rows], "models": [IT]}).json()
        self.assertEqual((s["clips"], s["total_usd"]), (2, round(sum(r["estimate_usd"] for r in rows), 4)), "the total shown first")
        self.assertTrue(s["fits"])
        self.assertNotIn("queued", s, "nothing starts without the confirm")
        ws = self.c.get(f"/api/episodes/{self.eid}/workspace").json()
        sec = next(x for x in ws["sections"] if x["key"] == "talking")
        self.assertEqual(sec["title"], "Talking shots")
        self.assertIn("0 of 2 lines", sec["note"])
        self.assertFalse(sec["blocking"])


if __name__ == "__main__":
    unittest.main()
