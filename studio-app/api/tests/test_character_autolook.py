"""New characters that can be rigged (owner decision 2026-11-21): a starting Look from the video notes' fixed lists only
(never names, never images), an optional AI-writer Look with names removed, the rig rules always appended by the
server, a first sheet limited to the expressions the story needs (neutral for a silent character) with its cost, body
pose candidates rig-checked with only passing ones shown and a cost cap, "replace the approved neutral", and a rig that
uses a clear arm's end as the hand when no hand is drawn. Synthetic figures; no paid calls."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from helpers import Env, sample_script
from test_rig_check import hidden_hands_figure
from test_rig_v2 import GREY, RIG, v2_figure

from oddstudio import engine, providers
from oddstudio import video_notes as VN
from oddstudio.character_looks import STYLE_CUES, look_from_notes

RANGES = [{"start": 0, "end": 4.5, "shot": "wide", "setting": "living room", "roles": [
    {"role": "speaker", "position": "left", "pose": "seated", "facing": "reactor 1", "emotion": "smug"},
    {"role": "reactor 1", "position": "center", "pose": "seated", "facing": "speaker", "emotion": "shocked"},
    {"role": "reactor 2", "position": "right", "pose": "standing", "facing": "speaker", "emotion": "shocked"}]}]


def armless_hands_figure(path: Path) -> Path:
    """Arms clearly drawn at the sides, but no hand at their ends (as if hidden in sleeves)."""
    v2_figure(path)
    im = Image.open(path).convert("RGBA")
    d = ImageDraw.Draw(im)
    for hx in (196, 404):
        d.ellipse((hx - 24, 628, hx + 24, 684), fill=GREY)
    im.save(path)
    return path


class LookTest(unittest.TestCase):
    def test_the_free_look_uses_only_fixed_lists_and_cues(self):
        speaker = look_from_notes(RANGES, True)
        silent = look_from_notes(RANGES, False)
        self.assertEqual(speaker, f"An adult who does the talking; usually seated; usual mood smug; one of 3 people in the scene. Design: {STYLE_CUES}.")
        self.assertIn("listens and reacts", silent)
        self.assertIn("usual mood shocked", silent)
        fixed = set(re.findall(r"[a-z]+", (speaker.split(". Design:")[0] + " " + silent.split(". Design:")[0]).lower()))
        allowed = {"an", "adult", "who", "does", "the", "talking", "listens", "and", "reacts", "without", "speaking", "usually",
                   "seated", "usual", "mood", "one", "of", "people", "in", "scene", "standing"} | set(VN.EMOTIONS)
        self.assertFalse(fixed - allowed, fixed - allowed)
        self.assertTrue(look_from_notes([], True).startswith("An adult who does the talking. Design:"))

    def test_rig_rules_are_always_appended(self):
        from types import SimpleNamespace
        from oddstudio import house_style
        from oddstudio.tasks import pose_prompt
        c = SimpleNamespace(name="Ralph", visual_description="a hoodie, hands deep in the pockets", skin_tone="")
        for v in ("v1", "v2"):
            p = pose_prompt(c, "neutral", False, False, version=v)
            self.assertIn(house_style.RIG_RULES, p)
            self.assertIn("both hands clearly visible", p)
            self.assertIn("sleeveless", p)
            self.assertIn("no pockets", p)


class RigToleranceTest(unittest.TestCase):
    def test_a_clear_arm_end_is_used_as_the_hand(self):
        tmp = Path(tempfile.mkdtemp())
        f = armless_hands_figure(tmp / "a.png")
        self.assertTrue(engine.make_cutout(f))
        r = subprocess.run([sys.executable, str(RIG), str(f), str(tmp / "rig")], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        body = json.loads((tmp / "rig" / "rig.json").read_text())["body"]
        self.assertEqual(body["hands_inferred"], ["l", "r"])
        self.assertLess(abs(body["hand_l"][0] - 200), 12)
        self.assertLess(abs(body["hand_l"][1] - 630), 20)
        self.assertGreater(body["hip_y"], 600, "the legs are still found below the hands")

    def test_hidden_arms_are_still_a_clear_error(self):
        tmp = Path(tempfile.mkdtemp())
        f = hidden_hands_figure(tmp / "h.png")
        self.assertTrue(engine.make_cutout(f))
        r = subprocess.run([sys.executable, str(RIG), str(f), str(tmp / "rig")], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 2)
        self.assertIn("hands not in pockets", r.stderr)


class CharacterFlowTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.drawn = []

        def image(prompt, out_file, reference):
            draw = [v2_figure, hidden_hands_figure][len(self.drawn) % 2]   # pass, fail, pass, ...
            self.drawn.append(prompt)
            return draw(Path(out_file))
        providers.set_test_image(image)
        self.c.put("/api/settings/image", json={"provider": "openai"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})

    def tearDown(self):
        providers.set_test_image(None)
        providers.set_test_text_responder(None)
        self.env.close()

    def audio_episode(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            ep = Episode(title="Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": [{"id": "l1", "start": 0, "end": 2, "text": "Mortimer leaves it all to the cat.",
                                                      "speaker": "Speaker 1", "words": []}],
                                           "video_notes": {"ranges": RANGES}})
            s.add(ep)
            s.commit()
            return ep.id

    def chars(self):
        return {c["key"]: c for c in self.c.get("/api/characters").json()}

    def test_new_audio_characters_get_a_look_and_the_writer_never_names_anyone(self):
        eid = self.audio_episode()
        r = self.c.post(f"/api/episodes/{eid}/audio/cast", json={"speakers": [
            {"label": "Speaker 1", "new": {"key": "mortimer", "name": "Mortimer"}}]})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.put(f"/api/episodes/{eid}/audio/silent-cast", json={"members": [
            {"name": "Ralph", "new": {"key": "ralph", "name": "Ralph"}}]})
        self.assertEqual(r.status_code, 200, r.text)
        ch = self.chars()
        self.assertTrue(ch["mortimer"]["visual_description"].startswith("An adult who does the talking"))
        self.assertTrue(ch["ralph"]["visual_description"].startswith("An adult who listens and reacts"))
        seen = []

        def writer(system, prompt):
            seen.append(prompt)
            return {"look": 'Mortimer has a grey quiff, a "mustard" sleeveless vest with a tie, hands on hips like Ralph.'}
        providers.set_test_text_responder(writer)
        self.c.post(f"/api/characters/{ch['mortimer']['id']}/look/write")
        ran = self.env.run_jobs(["character_look"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertIn("Mortimer leaves it all to the cat.", seen[0], "the character's own lines")
        self.assertIn("usual mood smug", seen[0], "the notes' fixed lists")
        self.assertIn(STYLE_CUES, seen[0], "the words-only style cues")
        look = self.chars()["mortimer"]["visual_description"]
        self.assertEqual(look, "the character has a grey quiff, a mustard sleeveless vest with a tie, hands on hips like the character.")

    def test_first_sheet_plan_and_cost(self):
        from oddstudio.db import new_session
        from oddstudio.models import Character
        script = sample_script()
        script["characters"].append({"key": "ralph", "role": "silent"})
        script["scenes"][0]["lines"][0]["reactions"] = [{"character": "ralph", "expression": "shocked"}]
        providers.set_test_text_responder(lambda s, p: script)
        with new_session() as s:
            s.add(Character(key="ralph", name="Ralph", scope="recurring", art_status="none", visual_description="a vest"))
            s.commit()
        i = self.c.post("/api/ideas", json={"title": "Card", "premise": "A card goes wrong.", "status": "submitted"}).json()
        self.c.post(f"/api/ideas/{i['id']}/start", json={"generate_script": True})
        self.env.run_jobs(["generate_script"])
        ch = self.chars()
        lead = self.c.get(f"/api/characters/{ch['character-01']['id']}/sheet-plan").json()
        self.assertEqual(lead["expressions"], ["neutral", "worried", "shocked", "deadpan"])
        self.assertEqual(lead["cost"]["text"], "4 image(s), about $0.20-$0.80")
        silent = self.c.get(f"/api/characters/{ch['ralph']['id']}/sheet-plan").json()
        self.assertEqual((silent["expressions"], silent["speaks"]), (["neutral"], False))

    def test_body_candidates_are_rig_checked_capped_and_replace_the_neutral(self):
        cid = self.c.post("/api/characters", json={"key": "nia", "name": "Nia", "visual_description": "a teal vest",
                                                    "scope": "recurring"}).json()["id"]
        r = self.c.post(f"/api/characters/{cid}/body-candidates", json={"n": 6, "max_usd": 1.0})
        self.assertEqual(r.status_code, 422, "6 images could cost $1.20: over the cap")
        self.assertEqual(self.drawn, [])
        r = self.c.post(f"/api/characters/{cid}/body-candidates", json={"n": 3, "max_usd": 1.0})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["body_candidates"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(len(self.drawn), 3)
        poses = [a for a in self.chars()["nia"]["assets"] if a["kind"] == "pose"]
        self.assertEqual(sorted(a["status"] for a in poses), ["review", "review", "rig_failed"],
                         "only passing candidates go to review")
        review = [a for a in poses if a["status"] == "review"]
        self.c.post(f"/api/character-assets/{review[0]['id']}/decision", json={"decision": "approve"})
        self.c.post(f"/api/character-assets/{review[1]['id']}/decision", json={"decision": "approve"})
        st = {a["id"]: a["status"] for a in self.chars()["nia"]["assets"] if a["kind"] == "pose"}
        self.assertEqual((st[review[0]["id"]], st[review[1]["id"]]), ("rejected", "approved"),
                         "approving a new neutral replaces the approved one (the old one is kept, retired)")
        self.assertEqual(self.chars()["nia"]["expressions"], {"neutral": f"p{review[1]['id']}"})


if __name__ == "__main__":
    unittest.main()
