"""feat/set-views: camera angles read from the reference video in words only; up to four views of one set, each made
from the set's text plus the view's camera words with the set's own wide picture as the reference (never a video frame
or a third-party picture); each view's own staging; the view each shot uses (missing views fall back to wide)."""
import json
import unittest
from pathlib import Path

from helpers import Env, fake_pose_image
from test_audio_stage1b import Base, make_media
from test_episode_sets import add_studio_set

from oddstudio import analysis, providers, sets
from oddstudio import camera_angles as CA
from oddstudio import set_views as SV

ANGLES = [
    {"view": "wide", "camera": "in front, eye level", "shot": "wide", "in_frame": ["desk", "bookcase", "window", "a row of chairs"],
     "people": [{"who": "the main speaker", "count": 1, "pose": "seated", "where": "left of frame", "facing": "right", "face": "kind eyes"},
                {"who": "the others", "count": 3, "pose": "seated", "where": "right of frame", "facing": "towards the main speaker"}],
     "furniture": [{"item": "desk", "where": "left of frame"}, {"item": "bookcase", "where": "background"}]},
    {"view": "speaker", "camera": "behind the audience", "shot": "medium", "in_frame": ["desk", "bookcase", "Mortimer"],
     "people": [{"who": "Uncle Mortimer", "count": 1, "pose": "seated"}, {"who": "the main speaker", "pose": "seated", "where": "centre of frame",
                                                                          "facing": "towards the camera", "clothes": "green vest"}]},
    {"view": "speaker", "camera": "in front, low"},
    {"view": "audience", "camera": "behind the speaker", "shot": "medium",
     "people": [{"who": "the others", "count": 3, "pose": "seated", "where": "centre of frame", "facing": "towards the camera"}]},
]


class WordsTest(unittest.TestCase):
    def test_only_list_words_one_angle_per_view_and_no_person(self):
        got, stripped = CA.clean(ANGLES)
        self.assertEqual([a["view"] for a in got], ["wide", "speaker", "audience"], "the first angle per view")
        blob = json.dumps(got).lower()
        for w in ("mortimer", "kind eyes", "green vest", "uncle"):
            self.assertNotIn(w, blob)
        self.assertGreaterEqual(stripped, 5)
        t = CA.angle_text(got[0])
        self.assertEqual(t, "Camera in front, eye level, wide shot. In frame: desk, bookcase, window, a row of chairs. "
                            "The main speaker seated, left of frame, facing right. 3 others seated, right of frame, facing "
                            "towards the main speaker. Furniture: desk left of frame; bookcase background.")
        p = CA.prompt_addition()
        self.assertIn("never describe any person's face, appearance, clothing or name", p)
        self.assertIn("Only the set and the camera angles are wanted", p)


class PickTest(unittest.TestCase):
    def test_the_shot_picks_the_view_and_missing_views_fall_back_to_wide(self):
        all_v = set(SV.EXTRA)
        self.assertEqual(SV.view_for({"shot": "wide"}, all_v), "wide")
        self.assertEqual(SV.view_for({"shot": "close"}, all_v), "speaker")
        self.assertEqual(SV.view_for({"shot": "medium", "look_at": "sidney"}, all_v), "two-shot")
        self.assertEqual(SV.view_for({"shot": "medium", "look_at": "sidney"}, {"speaker"}), "speaker")
        self.assertEqual(SV.view_for({"shot": "close"}, set()), "wide", "no view: wide")

    def test_cuts_seat_only_who_the_view_shows_and_come_back(self):
        st = {"plate": "wide.png", "seats": [{}, {}, {}, {}]}
        base = [{"t0": -1e9, "set_id": "room", "set": st, "starts": {"m": "seat:0", "r": "seat:1", "s": "seat:2", "w": "seat:3"}}]
        views = {"room": {"speaker": {"plate": "sp.png", "seats": [{}]}, "audience": {"plate": "au.png", "seats": [{}, {}, {}]}}}
        lines = [{"speaker": "m", "start": 0.0, "end": 6.0, "shot": "wide", "reactions": [{"character": "r"}]},
                 {"speaker": "m", "start": 7.0, "end": 9.0, "shot": "close", "look_at": "s"},
                 {"speaker": "m", "start": 9.5, "end": 11.0, "shot": "wide"}]
        out = SV.cut(lines, base, views)
        self.assertEqual([(x["t0"], x["view"]) for x in out], [(4.0, "audience"), (6.5, "speaker"), (9.25, "wide")])
        self.assertEqual(out[0]["starts"], {"r": "seat:0", "s": "seat:1", "w": "seat:2"}, "the listeners, the speaker off")
        self.assertEqual(out[1]["starts"], {"m": "seat:0"})
        self.assertEqual(out[2]["starts"], base[0]["starts"], "back to everyone's seats on the wide set")
        self.assertIsNone(SV.cut(lines, base, {}), "no views: the spec stays as before")

    def test_a_set_change_between_two_wide_lines_is_kept_and_cuts_fall_between_lines(self):
        a, b = {"plate": "a.png", "seats": [{}]}, {"plate": "b.png", "seats": [{}]}
        base = [{"t0": -1e9, "set_id": "a", "set": a, "starts": {"m": "seat:0"}},
                {"t0": 10.5, "set_id": "b", "set": b, "starts": {"m": "seat:0"}}]
        views = {"a": {"speaker": {"plate": "asp.png", "seats": [{}]}}}
        lines = [{"speaker": "m", "start": 0.0, "end": 4.0, "shot": "close"},
                 {"speaker": "m", "start": 5.0, "end": 10.0, "shot": "wide"},
                 {"speaker": "m", "start": 11.0, "end": 14.0, "shot": "wide"}]
        out = SV.cut(lines, base, views)
        self.assertEqual([(x["t0"], x["view"], x["set"]["plate"]) for x in out],
                         [(0.0, "speaker", "asp.png"), (4.5, "wide", "a.png"), (10.5, "wide", "b.png")],
                         "the scene's own set change stays, at the same moment between the lines")
        for x, ln in zip(out, lines):
            self.assertLessEqual(x["t0"], ln["start"], "every cut happens before its line starts")


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.calls = []

        def image(prompt, out_file, reference):
            self.calls.append((prompt, reference))
            return fake_pose_image(prompt, out_file, reference)
        providers.set_test_image(image)
        self.c.put("/api/settings/image", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})
        add_studio_set("office", status="approved", description="An original office with a desk on the left and a row of chairs.")

    def tearDown(self):
        providers.set_test_image(None)
        self.env.close()

    def episode(self):
        eid = self.c.post("/api/audio-episodes", json={"title": "Will", "format": "short", "rights_confirmed": True,
                                                       "rights_source": "own_recording"}).json()["id"]
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            ep = db.get(Episode, eid)
            got, _ = CA.clean(ANGLES)
            ep.set_proposal = {"camera_angles": [{"view": a["view"], "fields": a, "text": CA.angle_text(a), "edited": False} for a in got]}
            db.commit()
        return eid

    def test_a_view_is_drawn_from_the_words_with_our_own_wide_picture_and_approved_by_the_owner(self):
        eid = self.episode()
        v = self.c.get(f"/api/sets/office/views?episode={eid}").json()
        self.assertEqual([x["status"] for x in v["views"]], ["missing", "missing", "missing"])
        self.assertTrue(v["views"][0]["camera_words"].startswith("Camera behind the audience, medium shot."))
        r = self.c.post("/api/sets/office/views/speaker/generate", json={"episode_id": eid})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("reference image: our own generated set picture (office, the wide view)", r.json()["request_text"])
        self.assertEqual(self.c.post("/api/sets/office/views/speaker/generate", json={"episode_id": eid}).status_code, 409)
        self.assertEqual(self.env.run_jobs(["set_view_candidate"])[0][1], "succeeded")
        prompt, ref = self.calls[-1]
        self.assertEqual(Path(ref).name, "office.png", "the set's own wide picture is the reference")
        self.assertIn("Camera: Camera behind the audience, medium shot.", prompt)
        self.assertIn("THIS SAME ROOM from the wide camera angle", prompt)
        self.assertIn("An original office with a desk on the left", prompt)
        self.assertEqual(self.c.post("/api/sets/office/views/two-shot/generate", json={"episode_id": eid}).status_code, 422,
                         "no camera words for the two-shot")
        v = self.c.get(f"/api/sets/office/views?episode={eid}").json()
        self.assertEqual(v["views"][0]["status"], "candidate", "nothing approved by itself")
        b = {"floor_y": 700, "stand_min_x": 20, "stand_max_x": 490, "seats": [{"x": 256, "hip_y": 500, "feet_y": 600, "facing": "camera"}]}   # the stand-in picture is 512 x 768
        r = self.c.put("/api/sets/office/views/speaker/staging", json={"blocking": b})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["blocking"]["seats"][0]["facing"], "camera")
        self.assertEqual(self.c.post("/api/sets/office/views/speaker/decide", json={"decision": "approve"}).json()["status"], "approved")
        from oddstudio.db import new_session
        with new_session() as db:
            self.assertEqual(sorted(SV.approved_views(db, "office")), ["speaker"])

    def test_a_view_needs_the_approved_wide_picture_and_words_can_be_edited(self):
        add_studio_set("draft-room", status="candidate")
        eid = self.episode()
        r = self.c.post("/api/sets/draft-room/views/speaker/generate", json={"episode_id": eid})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.c.post("/api/sets/office/views/wide/generate", json={"episode_id": eid}).status_code, 404, "wide is the set itself")
        r = self.c.put(f"/api/episodes/{eid}/camera-angles", json={"view": "two-shot", "text": "Camera from the left side, medium shot."})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.post("/api/sets/office/views/two-shot/generate", json={"episode_id": eid}).status_code, 200)
        self.assertEqual(self.calls, [], "only queued: nothing drawn until the worker runs it")

    def test_the_view_plan_shows_the_view_per_shot(self):
        eid = self.episode()
        from oddstudio.db import new_session
        from oddstudio.models import Episode, StoryboardScene
        with new_session() as db:
            ep = db.get(Episode, eid)
            ep.set_id = "office"
            db.add(StoryboardScene(episode_id=eid, position=1, scene_key="s1", heading="Reading", characters=["m"],
                                   lines=[{"speaker": "m", "text": "Hello", "shot": "close", "line_id": "L1"}]))
            db.commit()
        rows = self.c.get(f"/api/episodes/{eid}/view-plan").json()["rows"]
        self.assertEqual((rows[0]["view"], rows[0]["note"]), ("wide", "speaker view missing: wide is used"))


class ReadTheRoomTest(Base):
    with_ffmpeg = True

    def setUp(self):
        super().setUp()
        analysis.set_test_analysis(vision=lambda cfg, images, q: {"rooms": [{"setting": "office", "size": "medium"}], "angles": ANGLES})
        self.c.put("/api/settings/vision", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})

    def test_the_angles_come_with_the_set_notes_in_words_only(self):
        eid = self.c.post("/api/audio-episodes", json={"title": "Will", "format": "short", "rights_confirmed": True,
                                                       "rights_source": "own_recording"}).json()["id"]
        est = self.c.get(f"/api/episodes/{eid}/set-notes/read-video/estimate", params={"seconds": 20}).json()
        self.assertGreater(est["output_tokens"], 600)
        clip = make_media(self.media, "room.mp4", 20)
        r = self.c.put(f"/api/episodes/{eid}/set-notes/read-video", content=clip.read_bytes(), headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.env.run_jobs(["set_notes_read_video"])[0][1], "succeeded")
        self.assertEqual(self.uploads(), [], "the video and frames are deleted")
        plan = self.c.get(f"/api/episodes/{eid}/view-plan").json()
        self.assertEqual([a["view"] for a in plan["camera_angles"]], ["wide", "speaker", "audience"])
        self.assertNotIn("mortimer", json.dumps(plan["camera_angles"]).lower())


if __name__ == "__main__":
    unittest.main()
