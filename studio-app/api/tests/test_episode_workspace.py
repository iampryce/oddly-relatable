"""feat/episode-workspace (owner request 2026-11-22): sets that follow their description (text only unless the owner
attaches their own reference; the layout leads the prompt; the exact request shown), richer set notes with the roles
layout, "Read the room from a video" (set notes only; the video deleted; the recording, lines, speakers and cast
untouched; cost and cap first), the set panel (candidates with pictures, suggested seats from a vision model, "N seats
for M people", Generate another), the workspace sections with their statuses and the blocking banner, and the
Reference plan counting only confirmed people."""
import json
import unittest
from pathlib import Path

from helpers import Env, fake_pose_image
from test_audio_stage1b import Base, make_media
from test_episode_sets import add_studio_set

from oddstudio import analysis, providers
from oddstudio import seat_suggest as SS
from oddstudio import set_notes as SN
from oddstudio import sets
from oddstudio import workspace as WS

LAYOUT_ANSWER = {"rooms": [
    {"room": 1, "setting": "office", "size": "medium", "feel": "roomy", "seats": 4, "arrangement": "behind a desk",
     "main": {"item": "desk", "place": "centre"},
     "furniture": [{"item": "desk", "shape": "long", "material": "dark wood", "colour": "dark brown", "place": "centre"},
                   {"item": "bookcase", "material": "wood", "colour": "brown", "place": "back wall"},
                   {"item": "window", "place": "left wall"}, {"item": "door", "place": "right wall"},
                   {"item": "portrait of the founder", "place": "back wall"}],
     "walls": "sage green", "floor": {"colour": "brown", "material": "parquet"}, "light": "soft daylight",
     "layout": [{"who": "the main speaker", "count": 1, "pose": "seated", "place": "behind the main furniture"},
                {"who": "the others", "count": 3, "pose": "seated", "place": "in a row facing the main furniture"},
                {"who": "the others", "count": 1, "pose": "standing", "place": "by the door", "hair": "grey"},
                {"who": "Mr Smith", "count": 1, "pose": "seated", "place": "by the window"}],
     "mood": ["tense"], "brand": "Acme"}]}
SEAT_ANSWER = {"speaker_seat": {"x": 500, "hip_y": 560, "feet_y": 640}, "desk_front": {"x0": 300, "y0": 600, "x1": 700, "y1": 700},
               "row": [{"x": 800, "hip_y": 780, "feet_y": 880}, {"x": 200, "hip_y": 780, "feet_y": 880},
                       {"x": 500, "hip_y": 780, "feet_y": 880}, {"x": 505, "hip_y": 782, "feet_y": 881},
                       {"x": 100, "hip_y": 900, "feet_y": 800}],
               "floor_y": 930, "stand_x0": 50, "stand_x1": 950, "label": "Acme"}


class SetPromptTest(unittest.TestCase):
    def test_the_layout_leads_and_the_style_is_short(self):
        desc = "An original medium office: a long dark wood desk in the centre, a bookcase by the back wall."
        parts = sets.prompt_parts(None, desc, 4, "Variety guard: ...")
        self.assertEqual([p["part"] for p in parts][:3], ["your description", "studio style", "studio rules"])
        self.assertTrue(parts[0]["text"].endswith(desc))
        self.assertLessEqual(len(sets.SET_STYLE_SHORT.split()), 45, "the style must not drown the layout")
        self.assertNotIn("open, flat floor", sets.prompt_for(None, desc, 4), "no style line that empties the room")
        self.assertNotIn("your reference image", [p["part"] for p in parts], "text only by default")
        self.assertEqual(sets.prompt_parts(None, desc, reference=True)[-1]["part"], "your reference image")

    def test_the_request_box_says_text_only_unless_an_own_reference_is_attached(self):
        env = Env().login()
        try:
            from oddstudio.db import new_session
            with new_session() as s:
                r = sets.request_view(s, "P")
                self.assertEqual((r["endpoint"], r["reference_image"], r["size"]), ("OpenAI images/generations", "none (text only)", "1024x1536"))
                self.assertIn("reference image: none (text only)\nprompt:\nP", sets.request_text(r))
                r = sets.request_view(s, "P", "your own picture (asset 3)")
                self.assertEqual(r["endpoint"], "OpenAI images/edits")
        finally:
            env.close()


class SetNotesLayoutTest(unittest.TestCase):
    def test_layout_feel_and_positions_survive_names_and_looks_do_not(self):
        rooms, stripped = SN.clean_scan(LAYOUT_ANSWER)
        self.assertEqual(len(rooms), 1)
        e = rooms[0]
        self.assertEqual((e["room"], e["feel"]), ("office", "roomy"))
        self.assertEqual(e["layout"], [{"who": "the main speaker", "count": 1, "pose": "seated", "place": "behind the main furniture"},
                                       {"who": "the others", "count": 3, "pose": "seated", "place": "in a row facing the main furniture"},
                                       {"who": "the others", "count": 1, "pose": "standing", "place": "by the door"}])
        self.assertGreaterEqual(stripped, 4, "the portrait, the hair, the named person and the brand are removed and counted")
        text = SN.room_text(e)
        self.assertIn("Layout: the main speaker seated behind the desk; 3 others seated in a row facing the desk; "
                      "one other standing by the door.", text)
        self.assertIn("a brown wood bookcase by the back wall", text)
        self.assertIn("a window by the left wall", text)
        self.assertIn("a door by the right wall", text)
        self.assertIn("sage green walls", text)
        self.assertIn("feels roomy", text)
        for w in ("acme", "founder", "portrait", "smith", "grey"):
            self.assertNotIn(w, json.dumps(rooms).lower() + text.lower())

    def test_the_prompts_ask_for_the_layout_from_fixed_lists(self):
        for q in (SN.prompt([("office", 3)]), SN.scan_prompt(6)):
            self.assertIn("layout", q)
            self.assertIn("behind the main furniture", q)
            self.assertIn("never what anyone looks like", q)
        self.assertIn('"setting"', SN.scan_prompt(6))
        rooms, _ = SN.clean_scan({"rooms": [{"setting": "kitchen", "size": "small"}, {"setting": "kitchen", "size": "large"},
                                            {"setting": "Bob's den", "size": "small"}]})
        self.assertEqual([r["room"] for r in rooms], ["kitchen", "kitchen 2", "room"])


class SeatSuggestTest(unittest.TestCase):
    def test_per_mille_to_pixels_speaker_first_duplicates_and_bad_seats_dropped(self):
        blk, info = SS.clean(SEAT_ANSWER, 1000, 1500, {"floor_y": 1290, "stand_min_x": 80, "stand_max_x": 920})
        xs = [s["x"] for s in blk["seats"]]
        self.assertEqual(xs, [500, 200, 500, 800], "the speaker's seat first, then the row left to right")
        self.assertEqual(blk["seats"][0], {"x": 500, "hip_y": 840, "feet_y": 960})
        self.assertEqual(blk["table_front"], {"x0": 300, "y0": 900, "x1": 700, "y1": 1050})
        self.assertEqual((blk["floor_y"], blk["stand_min_x"], blk["stand_max_x"]), (1395, 50, 950))
        self.assertEqual(info, {"seats": 4, "speaker_seat": True, "desk_front": True, "row": 3, "stripped": 3})
        self.assertEqual(SS.summary(info, 5), "4 seat(s) for 5 people: the speaker's seat behind the desk (desk front marked), "
                                              "3 in the audience row")

    def test_garbage_keeps_the_floor_and_marks_nothing(self):
        base = {"floor_y": 1290, "stand_min_x": 80, "stand_max_x": 920}
        blk, info = SS.clean("no", 1000, 1500, base)
        self.assertEqual(blk, {**base, "seats": []})
        blk, info = SS.clean({"desk_front": {"x0": 1, "y0": 1, "x1": 2, "y1": 2}, "row": [{"x": "a"}]}, 1000, 1500, base)
        self.assertNotIn("table_front", blk, "a desk front without a seat behind it hides nobody")
        self.assertEqual(info["seats"], 0)


class WorkspaceRulesTest(unittest.TestCase):
    def facts(self, **kw):
        f = {"audio": True, "stage": "audio_labelling", "needs_trim": False, "lines": 12, "unlabelled": 0,
             "speakers_without_character": [], "notes_ranges": 8, "notes_frames": 30, "notes_requested": False,
             "people_found": 4, "person_map": True, "confirmed": 3, "plan_waiting": False,
             "cast_rows": [{"key": "a", "name": "A", "art_status": "approved", "missing_expressions": []}],
             "script": None, "script_approved": None, "scenes": 0,
             "set": {"chosen": False, "label": "", "seats": 0, "people": 3, "candidates_waiting": 0}, "jobs": {}}
        f.update(kw)
        return f

    def by(self, out):
        return {s["key"]: s for s in out["sections"]}

    def test_the_plan_blocks_building_and_the_banner_says_where(self):
        out = WS.sections(self.facts(plan_waiting=True))
        s = self.by(out)
        self.assertEqual([x["key"] for x in out["sections"]][:10],
                         ["set", "people", "plan", "lines", "notes", "cast", "script", "storyboard", "talking", "production"])
        self.assertFalse(s["talking"]["blocking"], "Talking shots never block the episode")
        self.assertEqual((s["plan"]["status"], s["plan"]["blocking"], s["plan"]["open"]), ("action", True, True))
        self.assertEqual((s["lines"]["status"], s["lines"]["open"]), ("done", False), "finished: collapsed")
        self.assertEqual(s["script"]["status"], "waiting")
        self.assertEqual(s["set"]["status"], "todo", "needed before production, not blocking yet")
        self.assertFalse(s["set"]["blocking"])
        self.assertEqual(out["blocker"]["section"], "plan")
        self.assertIn("Accept the Reference plan", out["blocker"]["message"])
        self.assertEqual(s["people"]["note"], "3 confirmed, 1 not on screen (their seats and beats are left out).")

    def test_ready_to_build_then_review_then_the_set_blocks_production(self):
        s = self.by(WS.sections(self.facts()))
        self.assertEqual((s["script"]["status"], s["script"]["label"]), ("action", "build"))
        s = self.by(WS.sections(self.facts(stage="script_review", script=1)))
        self.assertIn("yours to approve", s["script"]["note"])
        out = WS.sections(self.facts(stage="storyboard_approved", script=1, script_approved=1, scenes=5))
        s = self.by(out)
        self.assertEqual((s["set"]["status"], s["production"]["status"]), ("action", "waiting"))
        self.assertEqual(out["blocker"]["section"], "set")
        out = WS.sections(self.facts(stage="storyboard_approved", script=1, script_approved=1, scenes=5,
                                     set={"chosen": True, "label": "Office", "seats": 4, "people": 5, "candidates_waiting": 0}))
        s = self.by(out)
        self.assertEqual(s["set"]["status"], "done")
        self.assertIn("Office: 4 seat(s) for 5 people. 1 seated person(s) will stand", s["set"]["note"])
        self.assertEqual(out["blocker"]["section"], "production")

    def test_jobs_show_on_their_section_failed_with_the_message(self):
        jobs = {"notes": [{"id": 9, "kind": "audio_video_notes", "status": "failed", "error": "vision: 401 bad key"}],
                "set": [{"id": 12, "kind": "set_candidate", "status": "running", "error": "", "set_id": "x"},
                        {"id": 11, "kind": "set_candidate", "status": "failed", "error": "old", "set_id": "y"}],
                "storyboard": [{"id": 5, "kind": "scene_reference", "status": "succeeded", "scene_id": 1},
                               {"id": 4, "kind": "scene_reference", "status": "failed", "scene_id": 1, "error": "old"}]}
        out = WS.sections(self.facts(notes_ranges=0, notes_requested=True, jobs=jobs))
        s = self.by(out)
        self.assertEqual(s["notes"]["status"], "failed")
        self.assertIn("audio video notes failed: vision: 401 bad key", s["notes"]["note"])
        self.assertEqual(out["blocker"]["section"], "notes")
        self.assertEqual(s["set"]["status"], "failed", "the latest failure of each set is shown")
        self.assertFalse(s["set"]["blocking"], "a failed candidate long before production shows red without blocking")
        self.assertEqual([j["id"] for j in s["set"]["jobs"]], [12, 11])
        self.assertEqual(s["storyboard"]["jobs"], [], "a later success clears an older failure")

    def test_only_the_current_step_is_open_and_only_the_blocker_is_flagged(self):
        """Quiet by default (2026-11-23): one open section, the current step; done steps are one collapsed line."""
        cases = [self.facts(plan_waiting=True), self.facts(), self.facts(stage="script_review", script=1),
                 self.facts(stage="storyboard_approved", script=1, script_approved=1, scenes=5),
                 self.facts(notes_ranges=0, notes_requested=True,
                            jobs={"notes": [{"id": 9, "kind": "audio_video_notes", "status": "failed", "error": "401"}],
                                  "set": [{"id": 11, "kind": "set_candidate", "status": "failed", "error": "old", "set_id": "y"}]})]
        for f in cases:
            out = WS.sections(f)
            opened = [x["key"] for x in out["sections"] if x["open"]]
            flagged = [x["key"] for x in out["sections"] if x["blocking"]]
            self.assertLessEqual(len(opened), 1, opened)
            self.assertEqual(opened, [out["current"]] if out["current"] else [])
            self.assertEqual(flagged, [out["blocker"]["section"]] if out["blocker"] else [])
            if out["blocker"]:
                self.assertEqual(out["current"], out["blocker"]["section"], "the blocker is the current step")
            self.assertFalse(any(x["open"] for x in out["sections"] if x["status"] == "done"), "done steps are collapsed")
        s = self.by(WS.sections(cases[-1]))
        self.assertEqual((s["set"]["status"], s["set"]["open"], s["set"]["blocking"]), ("failed", False, False),
                         "an old failure in a later step: red, one line, not open, not blocking")
        # nothing blocks: the first step still to do in the episode's order is current (Talking shots, before the set)
        f = self.facts(stage="storyboard_approved", script=1, script_approved=1, scenes=5,
                       set={"chosen": True, "label": "Office", "seats": 5, "people": 5, "candidates_waiting": 0},
                       talking={"lines": 4, "keyed": 1})
        f["stage"] = "producing"
        out = WS.sections(f)
        self.assertIsNone(out["blocker"])
        self.assertEqual((out["current"], self.by(out)["production"]["open"]), ("talking", False),
                         "while production renders, the next thing for you is the talking shots; nothing else is open")

    def test_the_now_box_is_the_single_next_action_with_its_cost(self):
        """The Now box (2026-11-23): a decision costs nothing; the talking shots show their own estimate; anything else
        says "cost shown before it starts"; the button never starts a paid run by itself."""
        nx = WS.sections(self.facts(plan_waiting=True))["next"]
        self.assertEqual((nx["section"], nx["kind"], nx["cost_text"], nx["button"]["action"]),
                         ("plan", "decision", "no cost: your decision", "open"))
        nx = WS.sections(self.facts(stage="script_review", script=1))["next"]
        self.assertEqual((nx["section"], nx["kind"]), ("script", "decision"))
        nx = WS.sections(self.facts())["next"]
        self.assertEqual((nx["section"], nx["kind"], nx["cost_text"], nx["cost_usd"]), ("script", "estimate", WS.NO_ESTIMATE, None),
                         "generating a script is a paid text call with no estimate here: never shown as free")
        f = self.facts(stage="storyboard_approved", script=1, script_approved=1, scenes=5,
                       set={"chosen": True, "label": "Office", "seats": 5, "people": 5, "candidates_waiting": 0},
                       talking={"lines": 4, "keyed": 1, "todo_lines": 3, "todo_usd": 0.135})
        f["stage"] = "producing"
        nx = WS.sections(f)["next"]
        self.assertEqual((nx["section"], nx["kind"], nx["cost_usd"], nx["button"]),
                         ("talking", "paid", 0.135, {"action": "run_talking", "label": "Run 3 line(s)"}))
        self.assertIn("shown again with the total before anything starts", nx["cost_text"])
        f["talking"] = {"lines": 4, "keyed": 1, "todo_lines": 0, "todo_usd": 0, "running": 3}
        nx = WS.sections(f)["next"]
        self.assertEqual((nx["kind"], nx["button"]), ("working", None), "running: nothing to press")
        jobs = {"notes": [{"id": 9, "kind": "audio_video_notes", "status": "failed", "error": "401"}]}
        nx = WS.sections(self.facts(notes_ranges=0, notes_requested=True, jobs=jobs))["next"]
        self.assertEqual((nx["section"], nx["cost_text"]), ("notes", WS.NO_ESTIMATE), "a retry may be paid again: no guess")

    def test_script_first_episodes_have_no_audio_sections(self):
        s = self.by(WS.sections(self.facts(audio=False, stage="script_pending", notes_ranges=0, people_found=0, person_map=False)))
        for k in ("lines", "notes", "people", "plan"):
            self.assertEqual(s[k]["status"], "not_needed", k)
        self.assertEqual(s["script"]["status"], "action")


class PlanCountsConfirmedPeopleTest(unittest.TestCase):
    def test_the_stand_note_and_the_beats_count_only_confirmed_people(self):
        from oddstudio.reference_plan import beat_confirmed, confirmed_persons, effective_beats
        tr = {"person_map": {"mortimer": 1, "sidney": 2, "nobody": None},
              "video_notes": {"ranges": [{"start": 0.0, "end": 4.0}],
                              "beats": [{"id": "a", "t": 1.0, "type": "nod", "person": 1},
                                        {"id": "b", "t": 1.5, "type": "nod", "person": 3},
                                        {"id": "c", "t": 2.0, "type": "turn_to", "person": 2, "target": "person 3"},
                                        {"id": "d", "t": 2.5, "type": "turn_to", "person": 2, "target": "person 1"}]}}
        self.assertEqual(confirmed_persons(tr), {1, 2})
        self.assertFalse(beat_confirmed({"person": 2, "type": "turn_to", "target": "person 3"}, {1, 2}))
        self.assertEqual([b["id"] for b in effective_beats(tr)], ["a", "d"], "person 3 is nobody's: their beats and turns to them are skipped")
        self.assertEqual(effective_beats({**tr, "person_map": {}}), [], "nobody confirmed: no beat is acted")


class EpisodeFlowTest(Base):
    with_ffmpeg = True

    def setUp(self):
        super().setUp()
        self.calls, self.prompts = [], []

        def vision(cfg, images, question):
            self.calls.append({"images": [Path(i).name for i in images], "question": question})
            if "Mark where the characters go" in question:
                return SEAT_ANSWER
            if "Group them into the distinct rooms" in question:
                return LAYOUT_ANSWER
            return {}
        analysis.set_test_analysis(vision=vision)

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

    def audio_ep(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            ep = Episode(title="The Unkind Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": [{"id": "L1", "start": 0.0, "end": 2.0, "text": "To my nephew", "speaker": "sp1",
                                                      "words": []}], "person_map": {}})
            db.add(ep)
            db.commit()
            return ep.id

    def transcript(self, eid):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            return json.dumps(db.get(Episode, eid).audio_transcript, sort_keys=True)

    def test_read_the_room_writes_set_notes_only_and_deletes_the_video(self):
        eid = self.audio_ep()
        before = self.transcript(eid)
        est = self.c.get(f"/api/episodes/{eid}/set-notes/read-video/estimate", params={"seconds": 20}).json()
        self.assertTrue(est["configured"] and est["within_cap"], est)
        self.assertEqual(est["frames"], 4)
        self.assertGreater(est["usd"], 0)
        clip = make_media(self.media, "room.mp4", 20)
        r = self.c.put(f"/api/episodes/{eid}/set-notes/read-video", content=clip.read_bytes(), headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["set_notes_read_video"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(self.uploads(), [], "the video and the frames are deleted")
        self.assertEqual(self.transcript(eid), before, "the recording, lines, speakers and cast are not touched")
        v = self.c.get(f"/api/episodes/{eid}/set-proposal").json()
        self.assertEqual([n["room"] for n in v["set_notes"]], ["office"])
        self.assertEqual(v["set_notes_from"], "a video read for the room (deleted)")
        self.assertEqual((v["set_notes"][0]["seats"], v["set_notes"][0]["people"]), (4, 5))
        self.assertIn("Layout: the main speaker seated behind the desk", v["set_notes"][0]["text"])
        mine = v["set_notes"][0]["text"] + " Mood: calm."
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/set-notes", json={"room": 0, "text": mine}).status_code, 200)
        v = self.c.post(f"/api/episodes/{eid}/set-proposal/propose").json()
        self.assertEqual(v["rooms"][0]["text"], mine, "used verbatim for the proposal")
        self.assertIn("reference image: none (text only)", v["rooms"][0]["request_text"])
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("Mark where", self.calls[0]["question"])

    def test_read_the_room_refuses_over_the_cap(self):
        eid = self.audio_ep()
        self.c.put("/api/settings/vision", json={"provider": "openai", "notes_cap_usd": 0.0001})
        clip = make_media(self.media, "room.mp4", 8)
        r = self.c.put(f"/api/episodes/{eid}/set-notes/read-video", content=clip.read_bytes(), headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("over the", r.json()["detail"])
        self.assertEqual(self.uploads(), [], "the refused video is deleted at once")

    def test_generate_suggests_seats_and_the_panel_shows_them_and_another_uses_the_same_request(self):
        eid = self.audio_ep()
        text = "An original medium office: a long dark wood desk in the centre, 4 seats behind a desk."
        self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": text})
        r = self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"text": text})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["set_candidate"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        prompt, ref = self.prompts[0]
        self.assertIsNone(ref, "text only")
        self.assertTrue(prompt.startswith(sets.LAYOUT_LEAD + text))
        self.assertIn("Mark where the characters go", self.calls[-1]["question"])
        self.assertTrue(self.calls[-1]["images"][0].endswith(".png"), "our own generated picture, nothing else")
        p = self.c.get(f"/api/episodes/{eid}/set-panel").json()
        self.assertEqual(len(p["sets"]), 1)
        x = p["sets"][0]
        self.assertEqual((x["status"], x["seats"]), ("candidate", 4))
        self.assertEqual(x["blocking"]["seats"][0]["x"], round(500 * x["width"] / 1000), "the speaker's seat first")
        self.assertIn("table_front", x["blocking"])
        self.assertTrue(x["suggested"]["summary"].startswith("4 seat(s)"))
        self.assertIn("reference image: none (text only)", x["request_text"])
        self.assertTrue(x["url"] and x["preview_url"])
        self.assertIn("usd", p["suggest_cost"])
        # Generate another: exactly the same request, whatever the box says now
        self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": "An original kitchen with a round table."})
        r = self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"again_of": x["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.env.run_jobs(["set_candidate"])
        self.assertEqual(self.prompts[1][0], self.prompts[0][0])
        # suggest seats again: a job, cost-capped
        r = self.c.post(f"/api/sets/{x['id']}/suggest-seats")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.env.run_jobs(["set_seat_suggest"])[0][1], "succeeded")
        # nothing was approved by any of this
        self.assertTrue(all(s["status"] == "candidate" for s in self.c.get(f"/api/episodes/{eid}/set-panel").json()["sets"]))

    def test_an_own_reference_is_the_only_image_ever_attached(self):
        eid = self.audio_ep()
        from PIL import Image
        png = self.media / "mine.png"
        Image.new("RGB", (40, 60), (10, 120, 80)).save(png)
        r = self.c.put(f"/api/episodes/{eid}/set-proposal/reference", content=png.read_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 422, "the owner confirms it is their own")
        r = self.c.put(f"/api/episodes/{eid}/set-proposal/reference?own=true", content=png.read_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 200, r.text)
        text = "An original small kitchen with a round table and two stools."
        v = self.c.put(f"/api/episodes/{eid}/set-proposal", json={"text": text}).json()
        self.assertIn("reference image: your own picture", v["rooms"][0]["request_text"])
        self.assertEqual(v["rooms"][0]["parts"][-1]["part"], "your reference image")
        self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"text": text})
        self.env.run_jobs(["set_candidate"])
        prompt, ref = self.prompts[-1]
        self.assertIsNotNone(ref)
        self.assertEqual(Path(ref).suffix, ".png")
        self.c.delete(f"/api/episodes/{eid}/set-proposal/reference")
        self.c.post(f"/api/episodes/{eid}/set-proposal/generate", json={"text": text})
        self.env.run_jobs(["set_candidate"])
        self.assertIsNone(self.prompts[-1][1], "removed: text only again")

    def test_the_workspace_endpoint(self):
        eid = self.audio_ep()
        w = self.c.get(f"/api/episodes/{eid}/workspace").json()
        s = {x["key"]: x for x in w["sections"]}
        self.assertEqual(s["cast"]["status"], "action", "sp1 is not a character yet")
        self.assertEqual(w["blocker"]["section"], "cast")
        self.assertEqual(s["lines"]["status"], "done")
        add_studio_set("office-ep", status="candidate", kept=False, episode_id=eid)
        s = {x["key"]: x for x in self.c.get(f"/api/episodes/{eid}/workspace").json()["sections"]}
        self.assertIn("1 candidate(s) wait for your decision", s["set"]["note"])


if __name__ == "__main__":
    unittest.main()
