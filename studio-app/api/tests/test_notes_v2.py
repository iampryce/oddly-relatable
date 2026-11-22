"""Video notes v2 (owner decision 2026-11-21, video-first): persistent numbered people across frames, per-frame states
from fixed lists only (gesture, talking, kneeling added), denser sampling in batches with one frame of overlap that
carries the numbering, a cost cap checked before upload, the v1 ranges derived for everything downstream, and a quality
readout for judging the identity tracking."""
import re
import unittest

from test_audio_stage1b import Base, make_media

from oddstudio import analysis
from oddstudio import notes_v2 as NV
from oddstudio import video_notes as VN

FIXED = set(NV.GESTURES) | set(NV.POSES) | set(VN.POSITIONS) | set(VN.EMOTIONS) | set(VN.FACING_FIXED) | set(VN.SHOTS) | \
    set(VN.CAMERA) | set(VN.SETTINGS) | set(VN.FURNITURE) | set(VN.TIME_OF_DAY)


class SamplingTest(unittest.TestCase):
    def test_denser_frames_by_format_with_caps(self):
        self.assertEqual(len(NV.frame_times(0, 60, "short")), 60, "a Short: 1 frame per second")
        self.assertEqual(len(NV.frame_times(0, 200, "long")), 100, "a long episode: 1 frame every 2 s")
        self.assertEqual(len(NV.frame_times(0, 450, "long")), 150, "at most 150")

    def test_batches_of_50_with_one_frame_of_overlap(self):
        b = NV.batches(150)
        self.assertEqual([len(x) for x in b], [50, 50, 50, 3])
        self.assertEqual([x[0] for x in b[1:]], [b[0][-1], b[1][-1], b[2][-1]], "each batch starts with the previous last frame")
        self.assertEqual(NV.batches(30), [list(range(30))])

    def test_estimate_and_cap(self):
        short = NV.estimate(60, "short", "openai")
        self.assertEqual((short["frames"], short["calls"], short["within_cap"]), (60, 2, True))
        self.assertLess(short["usd"], 0.05)
        tight = NV.estimate(60, "short", "anthropic", cap_usd=0.01)
        self.assertFalse(tight["within_cap"])
        self.assertEqual((NV.clamp_cap("x"), NV.clamp_cap(-1), NV.clamp_cap(99)), (0.5, 0.5, 10.0))

    def test_actual_cost_from_reported_tokens(self):
        usd = NV.actual_usd([{"provider": "openai", "input_tokens": 1_000_000, "output_tokens": 0},
                             {"provider": "openai", "input_tokens": 0, "output_tokens": 1_000_000}])
        self.assertEqual(usd, 2.0)
        self.assertIsNone(NV.actual_usd([{"provider": "openai"}]))


class CleanTest(unittest.TestCase):
    RAW = {"frames": [
        {"frame": 1, "shot": "wide", "setting": "Central Perk", "camera": "static", "logo": "x",
         "people": [{"person": 1, "position": "left", "pose": "kneeling", "gesture": "phone to ear", "facing": "person 2",
                     "emotion": "smug", "talking": True, "name": "Rachel", "hair": "blonde"},
                    {"person": "person 2", "position": "right", "facing": "person 2", "talking": "yes", "gesture": "moonwalk"},
                    {"person": 9, "position": "center"}, {"person": 1, "pose": "standing"}]},
        {"frame": 7}, {"frame": 1}, "text on a sign"]}

    def test_only_the_fixed_lists_survive(self):
        frames, stripped = NV.clean_frames(self.RAW, [0.5, 1.5])
        self.assertEqual(frames, [{"t": 0.5, "shot": "wide", "camera": "static", "people": [
            {"person": 1, "position": "left", "pose": "kneeling", "gesture": "phone_to_ear", "emotion": "smug",
             "facing": "person 2", "talking": True},
            {"person": 2, "position": "right"}]}])
        self.assertGreaterEqual(stripped, 12)
        words = set(re.findall(r"[a-z_]+", str(frames).lower())) - {"t", "shot", "camera", "people", "person", "position",
                                                                    "pose", "gesture", "emotion", "facing", "talking", "true"}
        self.assertLessEqual(words, FIXED, words - FIXED)

    def test_the_overlap_frame_maps_renumbered_people_back(self):
        prev = {"t": 49.5, "people": [{"person": 1, "position": "left", "pose": "seated"},
                                      {"person": 2, "position": "right", "pose": "standing"}]}
        batch = [{"t": 49.5, "people": [{"person": 1, "position": "right", "pose": "standing"},
                                         {"person": 2, "position": "left", "pose": "seated"}]},
                 {"t": 50.5, "people": [{"person": 1, "position": "right", "pose": "standing", "facing": "person 2"},
                                        {"person": 3, "position": "center", "pose": "standing"}]}]
        rest, m = NV.renumber(prev, batch)
        self.assertEqual(m[1], 2)
        self.assertEqual(m[2], 1)
        self.assertEqual(len(rest), 1, "the overlap frame is not kept twice")
        self.assertEqual([(p["person"], p.get("facing")) for p in rest[0]["people"]], [(2, "person 1"), (3, None)])
        kept, m2 = NV.renumber(prev, batch[1:])
        self.assertEqual((len(kept), m2), (1, {}), "no overlap frame returned: nothing dropped, numbers as given")

    def test_the_v1_view_speaker_is_the_one_talking(self):
        frames = [{"t": t, "shot": "medium", "setting": "kitchen",
                   "people": [{"person": 1, "pose": "seated", "talking": t < 2, "facing": "person 2"},
                              {"person": 2, "pose": "standing", "talking": t >= 2, "facing": "person 1"}]}
                  for t in (0.5, 1.5, 2.5, 3.5)]
        ranges, _ = NV.to_ranges(frames, 4.0, 1.0)
        self.assertEqual([(r["start"], r["end"]) for r in ranges], [(0.0, 2.0), (2.0, 4.0)], "merged while unchanged")
        self.assertEqual(ranges[0]["roles"][0], {"role": "speaker", "pose": "seated", "facing": "reactor 1", "person": 1},
                         "each role keeps its anonymous person number (for who is who)")
        self.assertEqual(ranges[1]["roles"][1], {"role": "speaker", "pose": "standing", "facing": "reactor 1", "person": 2})

    def test_quality_readout(self):
        frames = [{"t": 0.5, "people": [{"person": 1, "talking": True}, {"person": 2}]}, {"t": 1.5, "people": [{"person": 1}]},
                  {"t": 2.5, "people": []}]
        q = NV.quality(frames, 4, 3, [{"provider": "openai", "input_tokens": 10000, "output_tokens": 1000}], 0.02, [{"1": 2, "2": 1}])
        self.assertEqual((q["people"], q["appearances"], q["frames_sent"], q["frames_used"], q["frames_with_people"],
                          q["talking_frames"], q["stripped"], q["calls"]), (2, {"1": 2, "2": 1}, 4, 3, 2, 1, 3, 1))
        self.assertEqual(q["actual_usd"], 0.0056)
        self.assertEqual(q["renumbered"], [{"1": 2, "2": 1}])


class CapAtUploadTest(Base):
    with_ffmpeg = True

    def notes_upload(self, eid, clip):
        return self.c.put(f"/api/episodes/{eid}/audio?hints=true", content=clip.read_bytes(), headers={"Content-Type": "video/mp4"})

    def test_the_cap_is_shown_before_and_enforced_at_upload(self):
        self.assertEqual(self.c.put("/api/settings/vision", json={"provider": "openai", "notes_cap_usd": 0.001}).status_code, 200)
        est = self.c.get("/api/audio/video-notes/estimate", params={"seconds": 30, "format": "short"}).json()
        self.assertEqual((est["frames"], est["cap_usd"], est["within_cap"]), (30, 0.001, False))
        analysis.set_test_analysis(vision=lambda cfg, images, q: {"frames": []})
        eid = self.create()
        r = self.notes_upload(eid, make_media(self.media, "clip.mp4", 20))
        self.assertEqual(r.status_code, 409)
        self.assertIn("over the $0.00 cap", r.text)
        self.assertEqual(self.c.put("/api/settings/vision", json={"notes_cap_usd": 0.5}).status_code, 200)
        self.assertEqual(self.notes_upload(eid, make_media(self.media, "clip2.mp4", 20)).status_code, 200)


if __name__ == "__main__":
    unittest.main()
