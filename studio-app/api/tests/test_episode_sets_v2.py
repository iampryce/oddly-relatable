"""Every episode gets its own, distinct set (owner rule 2026-11-22, feat/episode-sets).

- Set notes from the reference video, per distinct room, in words from fixed lists only (no names, brands, logos,
  on-screen text, artwork or people; no frame ever goes to an image generator), editable, and used verbatim by
  "Propose from the video notes": one proposal per room.
- The exact text sent to the image API is shown as labelled parts (studio style / your description / studio rules /
  variety guard); the studio style is one flat house style with no warm, cosy, painted-wood bias; no reference image.
- The variety guard lists the recent sets' look and asks for a clearly different palette, floor, light and layout.
- Reuse is explicit: another episode's set is offered only once it is kept for future episodes.
- The set notes' cost is in the estimate and under the cap."""
import json
import re
import unittest

from helpers import Env, fake_pose_image
from test_audio_stage1b import Base, make_media
from test_episode_sets import add_studio_set

from oddstudio import analysis, house_style, providers
from oddstudio import set_notes as SN

SET_ANSWER = {"brand": "Apple", "rooms": [
    {"room": 1, "size": "medium", "seats": 3, "arrangement": "behind a desk", "main": {"item": "desk", "place": "centre"},
     "furniture": [{"item": "desk", "shape": "L-shaped", "material": "light wood", "colour": "white", "place": "centre"},
                   {"item": "window", "place": "back wall"}, {"item": "poster of Dwight", "place": "left wall"},
                   {"item": "screen", "colour": "black", "place": "left wall", "text": "QUARTERLY SALES"},
                   {"item": "plant", "colour": "green", "place": "front right"}],
     "walls": "navy", "floor": {"colour": "grey", "material": "carpet"}, "ceiling": "white", "light": "cool fluorescent light",
     "mood": ["corporate", "Dunder Mifflin"], "name": "Michael's office"},
    {"room": 2, "size": "large", "seats": 8, "arrangement": "around a table", "main": {"item": "meeting table", "place": "centre"},
     "walls": "white", "floor": {"colour": "dark brown", "material": "parquet"}, "light": "bright daylight", "logo": "Acme"},
    {"room": 7, "size": "small"}]}
FORBIDDEN = ("apple", "dwight", "quarterly", "sales", "dunder", "mifflin", "michael", "acme", "poster")


def staging(question: str) -> dict:
    """A 60 s Short: 40 s in an office, 20 s in a meeting room (both long enough to be rooms of their own), read from
    the frame times the notes prompt lists."""
    out = []
    for k, t in re.findall(r"frame (\d+) at ([\d.]+) s", question):
        k, t = int(k), float(t)
        room = "office" if t < 40 else "meeting room"
        out.append({"frame": k, "shot": "wide", "camera": "static", "setting": room, "furniture": "desk" if t < 40 else "long table",
                    "people": [{"person": 1, "position": "left", "pose": "seated", "talking": True},
                               {"person": 2, "position": "right", "pose": "standing"}]})
    return {"frames": out}


class RulesTest(unittest.TestCase):
    def test_only_list_words_survive(self):
        rooms, stripped = SN.clean(SET_ANSWER, ["office", "meeting room"])
        self.assertEqual([r["room"] for r in rooms], ["office", "meeting room"])
        self.assertGreaterEqual(stripped, 7, "the brand, the name, the poster, the screen's text, a mood and room 7")
        text = " ".join(SN.room_text(r) for r in rooms).lower()
        for w in FORBIDDEN:
            self.assertNotIn(w, text)
        self.assertIn("navy walls", text)
        self.assertIn("a blank dark screen", text, "screens are always drawn blank")
        self.assertIn("8 seats around a table", text)
        # every word is a list word or a fixed sentence word
        allowed = {w for phrase in SN.WORDS for w in re.split(r"[\s-]+", phrase)} | {
            "an", "a", "original", "walls", "floor", "ceiling", "at", "the", "seat", "seats", "furniture", "by", "in", "on",
            "mood", "3", "8"}
        words = {w for w in re.split(r"[^a-z0-9]+", text) if w}
        self.assertEqual(words - allowed, set(), "no free text in the sentence")

    def test_one_room_per_setting_and_frames_spread_with_wide_shots_first(self):
        ranges = [{"start": 0, "end": 40, "setting": "office", "roles": [{"role": "speaker", "pose": "seated"}]},
                  {"start": 40, "end": 60, "setting": "meeting room", "roles": [{"role": "speaker"}, {"role": "reactor 1"}]},
                  {"start": 60, "end": 62, "setting": "office"}]
        rs = SN.rooms(ranges)
        self.assertEqual([(r["room"], r["people"], r["seated"]) for r in rs], [("office", 1, 1), ("meeting room", 2, 0)])
        frames = [{"t": t + 0.5, "shot": "close" if t % 2 else "wide"} for t in range(62)]
        picked = SN.pick_frames(rs[0], frames)
        self.assertEqual(len(picked), 3)
        self.assertTrue(all(int(t) % 2 == 0 for t in picked), "wide shots first")
        self.assertTrue(picked[0] < 20 < picked[-1], "spread over the room's time")

    def test_the_studio_style_has_no_cosy_bias(self):
        for biased in ("warm", "cozy", "cosy", "painted", "wood", "lamp", "storybook", "evening"):
            self.assertNotIn(biased, house_style.SET_STYLE_FLAT.lower())
        self.assertIn("flat colour", house_style.SET_STYLE_FLAT.lower())


class SetNotesFlowTest(Base):
    with_ffmpeg = True

    def setUp(self):
        super().setUp()
        self.calls, self.prompts = [], []

        def vision(cfg, images, question):
            self.calls.append({"images": len(images), "question": question})
            if "ORIGINAL, EMPTY 2D cartoon set" in question:
                return SET_ANSWER
            return staging(question)
        analysis.set_test_analysis(transcriber=lambda cfg, audio: {
            "provider": "openai", "model": "whisper-1", "language": "en", "duration": 60.0, "text": "Hello there.", "segments": [],
            "words": [{"start": 0.2, "end": 0.5, "word": "Hello"}, {"start": 6.0, "end": 8.0, "word": "there."}]}, vision=vision)

        def image(prompt, out_file, reference):
            self.prompts.append((prompt, reference))
            return fake_pose_image(prompt, out_file, reference)
        providers.set_test_image(image)
        self.c.put("/api/settings/vision", json={"provider": "openai"})
        self.c.put("/api/settings/image", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})

    def tearDown(self):
        providers.set_test_image(None)
        super().tearDown()

    def episode_with_set_notes(self):
        eid = self.create()
        clip = make_media(self.media, "clip.mp4", 60)
        r = self.c.put(f"/api/episodes/{eid}/audio?hints=true&start=0&end=60", content=clip.read_bytes(), headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["audio_media_prepare", "audio_video_notes", "audio_transcribe"])
        self.assertTrue(all(x[1] == "succeeded" for x in ran), ran)
        return eid

    def test_set_notes_per_room_words_only_and_inside_the_estimate(self):
        est = self.c.get("/api/audio/video-notes/estimate", params={"seconds": 60, "format": "short"}).json()
        self.assertIn("set_notes", est)
        self.assertAlmostEqual(est["usd"], round(est["staging_usd"] + est["set_notes"]["usd"], 4), places=4,
                               msg="the set notes' cost is shown and counted against the cap")
        eid = self.episode_with_set_notes()
        sn_call = self.calls[-1]
        self.assertIn("ORIGINAL, EMPTY 2D cartoon set", sn_call["question"])
        self.assertIn("room 1 (office)", sn_call["question"])
        self.assertIn("room 2 (meeting room)", sn_call["question"])
        self.assertLessEqual(sn_call["images"], 6, "three frames per room at most")
        v = self.c.get(f"/api/episodes/{eid}/set-proposal").json()
        sn = v["set_notes"]
        self.assertEqual([x["room"] for x in sn], ["office", "meeting room"])
        blob = json.dumps(sn).lower()
        for w in FORBIDDEN:
            self.assertNotIn(w, blob)
        self.assertEqual(sn[1]["seats"], 8)
        self.assertEqual(self.uploads(), [], "frames and video deleted")
        # editable, then used verbatim, one proposal per room
        mine = "An original large meeting room: white walls, a dark brown parquet floor, bright daylight. A long table, 8 seats."
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/set-notes", json={"room": 1, "text": mine}).status_code, 200)
        v = self.c.post(f"/api/episodes/{eid}/set-proposal/propose").json()
        self.assertEqual([r["room"] for r in v["rooms"]], ["office", "meeting room"], "two rooms, two proposals")
        self.assertEqual(v["rooms"][0]["text"], sn[0]["text"])
        self.assertEqual(v["rooms"][1]["text"], mine, "the edited set notes, verbatim")
        parts = {p["part"]: p["text"] for p in v["rooms"][1]["parts"]}
        self.assertEqual(parts["your description"], "Setting: " + mine)
        self.assertTrue(parts["studio style"].startswith(house_style.SET_STYLE_FLAT[:40]))
        self.assertIn("seating for at least 8 people", parts["studio rules"])
        self.assertIn("EMPTY room with no people", parts["studio rules"])
        shown = v["rooms"][1]["prompt"]
        g = self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"text": mine, "room": 1}).json()
        self.assertEqual(g["prompt"], shown)
        self.env.run_jobs(["set_candidate"])
        self.assertEqual(self.prompts, [(shown, None)], "exactly the prompt shown; no reference image")
        sets = {s["id"]: s for s in self.c.get("/api/sets").json()["sets"]}
        rec = sets[g["set_id"]]
        self.assertEqual((rec["kept"], rec["flat_style"], rec["prompt"]), (False, True, shown))
        self.assertIn("meeting room", g["set_id"] + rec["label"])


class VarietyAndReuseTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def audio_episode(self, title):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            ep = Episode(title=title, stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": [{"id": "l1", "speaker": "a", "text": "Hi.", "start": 0, "end": 1},
                                                     {"id": "l2", "speaker": "b", "text": "Hey.", "start": 1, "end": 2}]})
            s.add(ep)
            s.commit()
            return ep.id

    def test_the_variety_guard_lists_recent_sets_and_is_editable(self):
        add_studio_set("cosy-den", description="An original living room with an orange wood floor, cream walls, green curtains",
                       kept=False, episode_id=990)
        eid = self.audio_episode("Will Test")
        text = "An original office with a desk and three chairs."
        v = self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": text}).json()
        self.assertEqual(v["variety_source"], "recent sets")
        self.assertIn("Cosy-Den", v["recent_sets"][0])
        self.assertIn("cream", v["recent_sets"][0])
        self.assertIn("warm painted look", v["recent_sets"][0], "the old house style's look is part of the signature")
        guard = next(p["text"] for p in v["parts"] if p["part"] == "variety guard")
        self.assertIn("clearly different", guard)
        self.assertIn("Palette for this set:", guard, "no colour in the description: a palette is chosen")
        self.assertNotIn("cream walls", guard.split("Palette for this set:")[1])
        self.assertIn("seating for at least 2 people", v["prompt"], "enough seats for the cast")
        mine = "Variety guard: no wood at all, a cool grey and yellow palette."
        v = self.c.put(f"/api/episodes/{eid}/set-proposal/variety", json={"text": mine}).json()
        self.assertEqual((v["variety"], v["variety_source"]), (mine, "your edit"))
        self.assertTrue(v["prompt"].endswith(mine), "sent exactly as edited")
        v = self.c.put(f"/api/episodes/{eid}/set-proposal/variety", json={"text": ""}).json()
        self.assertEqual(v["variety_source"], "recent sets")
        # a description that fixes colours gets no palette (the reference's own colours win)
        v = self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": "An original office with navy walls and a grey carpet."}).json()
        self.assertNotIn("Palette for this set:", v["prompt"])

    def test_reuse_is_explicit_another_episodes_set_must_be_kept_first(self):
        e1, e2 = self.audio_episode("First"), self.audio_episode("Second")
        add_studio_set("first-office", kept=False, episode_id=e1, description="an office")
        opts = self.c.get(f"/api/episodes/{e1}/set-options").json()
        self.assertIn("first-office", [o["id"] for o in opts["options"]], "its own episode may use it")
        self.assertTrue(next(o for o in opts["options"] if o["id"] == "first-office")["own"])
        opts = self.c.get(f"/api/episodes/{e2}/set-options").json()
        self.assertNotIn("first-office", [o["id"] for o in opts["options"]], "never offered to another episode")
        self.assertEqual(opts["hidden_other_episodes"], 1)
        r = self.c.put(f"/api/episodes/{e2}/set", json={"set_id": "first-office"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Keep this set for future episodes", r.text)
        self.assertEqual(self.c.put(f"/api/episodes/{e2}/scene-sets", json={"set_ids": ["first-office"]}).status_code, 409)
        self.assertEqual(self.c.put(f"/api/episodes/{e1}/set", json={"set_id": "first-office"}).status_code, 200)
        self.assertEqual(self.c.post("/api/sets/first-office/keep", json={"keep": True}).json(), {"id": "first-office", "kept": True})
        opts = self.c.get(f"/api/episodes/{e2}/set-options").json()
        o = next(o for o in opts["options"] if o["id"] == "first-office")
        self.assertEqual((o["kept"], o["own"]), (True, False))
        self.assertEqual([u["id"] for u in o["used_in"]], [e1], "the picker shows where it is already used")
        self.assertEqual(self.c.put(f"/api/episodes/{e2}/set", json={"set_id": "first-office"}).status_code, 200, "reuse, chosen explicitly")
        # un-keeping it hides it from new episodes, but the episodes using it keep it
        self.c.post("/api/sets/first-office/keep", json={"keep": False})
        e3 = self.audio_episode("Third")
        self.assertNotIn("first-office", [o["id"] for o in self.c.get(f"/api/episodes/{e3}/set-options").json()["options"]])
        self.assertIn("first-office", [o["id"] for o in self.c.get(f"/api/episodes/{e2}/set-options").json()["options"]])
        self.assertEqual(self.c.post("/api/sets/nowhere/keep", json={"keep": True}).status_code, 404)

    def test_the_writer_is_offered_only_this_episodes_and_kept_sets(self):
        from oddstudio import acting, sets
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        e1, e2 = self.audio_episode("First"), self.audio_episode("Second")
        add_studio_set("first-office", kept=False, episode_id=e1)
        add_studio_set("library-kitchen", kept=True)
        real = acting.enabled
        acting.enabled = lambda db: True
        try:
            with new_session() as s:
                envs1 = sets.writer_environments(s, s.get(Episode, e1))
                envs2 = sets.writer_environments(s, s.get(Episode, e2))
        finally:
            acting.enabled = real
        self.assertIn("first-office", envs1)
        self.assertNotIn("first-office", envs2)
        self.assertIn("library-kitchen", envs2)


if __name__ == "__main__":
    unittest.main()
