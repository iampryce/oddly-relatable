"""Sets and seating masters, guided step 5 (room_sets.py, cutout_remote.py; the shared ComfyUI session).

Covered: the repaint mask math (box minus the people grown 17 px; the halo band = the wide outline minus the tight one,
inside the box; the people pasted back pixel-exact; nothing outside the box changes); straight-on wall prompts (no
"move/rotate the camera" wording: template, owner edit 422, GPT text replaced); walls and seating pictures with the
WaveSpeed calls stubbed (cost, 409 without the exact price, seat order and references, nothing approved by itself,
the seating master offered to the close-ups); the character check (heads counted, Gemini mocked: a missing character
is flagged, "Remake this picture" with the cast spelled out); the eyeline per side (default from the main speaker,
used by the seating and talking prompts); the repair job end to end with RunPod, ComfyUI and SSH mocked (the GPU
turned off, before/after kept, the owner's Approve makes it the still); the chat's new proposals and thread keys.
No network, no paid call: only fake credentials."""
import json
import subprocess
import unittest
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from oddstudio import comfy, gpu, runpod
from oddstudio import room_sets as RS
from oddstudio import shot_chat as SC

from test_reactions import ApiBase, FakeComfy, png
from test_talking_s2v import FakeRunPod

FAKE_GEMINI = "fake-gemini-credential-for-tests"
FAKE_OPENAI = "fake-openai-credential-for-tests"


# ================================================================== pure parts
def picture_and_alpha():
    """A 400x300 picture (a gradient room) with one 'person' (a white disc + body), and that person's alpha."""
    pic = Image.new("RGB", (400, 300))
    pic.putdata([((x * 3) % 256, (y * 5) % 256, (x + 2 * y) % 256) for y in range(300) for x in range(400)])
    alpha = Image.new("L", (400, 300), 0)
    d, da = ImageDraw.Draw(pic), ImageDraw.Draw(alpha)
    for dr in (d, da):
        dr.ellipse((170, 60, 230, 120), fill=255 if dr is da else (255, 255, 255))
        dr.rectangle((185, 120, 215, 260), fill=255 if dr is da else (200, 200, 200))
    return pic, alpha


class MaskTest(unittest.TestCase):
    def test_dilate_grows_by_r_pixels(self):
        import numpy as np
        m = np.zeros((50, 50), dtype=bool)
        m[25, 25] = True
        g = RS.dilate(m, 3)
        self.assertTrue(g[22, 22] and g[28, 28] and g[25, 22])
        self.assertFalse(g[21, 25] or g[25, 29])
        self.assertTrue((RS.dilate(m, 0) == m).all())

    def test_background_minus_dilated_people_band_and_tight(self):
        _pic, alpha = picture_and_alpha()
        box = {"x": 0, "y": 0, "w": 400, "h": 200}
        m = RS.repaint_masks(alpha, box)
        area, band, tight = (m[k].load() for k in ("area", "band", "tight"))
        # the person's own pixels and everything within 17 px of them are never repainted in pass 1
        self.assertEqual(area[200, 90], 0)
        self.assertEqual(area[170 - 10, 90], 0)                  # 10 px left of the head: protected
        self.assertEqual(area[170 - 20, 90], 255)                # 20 px away: background, repainted
        self.assertEqual(area[200, 250], 0)                      # below the box: never
        self.assertEqual(area[20, 20], 255)
        # the band: between the tight outline (3 px) and the wide one (21 px), inside the box only
        self.assertEqual(band[170 - 10, 90], 255)
        self.assertEqual(band[170 - 2, 90], 0)                   # inside the tight outline
        self.assertEqual(band[170 - 25, 90], 0)                  # beyond the wide outline
        self.assertEqual(band[185 - 10, 230], 0)                 # next to the body but below the box
        self.assertEqual(tight[170 - 2, 90], 255)
        self.assertEqual(tight[170 - 5, 90], 0)
        # band = wide minus tight inside the box, exactly
        import numpy as np
        a = np.asarray(alpha)
        wide = RS.dilate(a > RS.PEOPLE_ALPHA, RS.WIDE_DILATE)
        t = RS.dilate(a > RS.TIGHT_ALPHA, RS.TIGHT_DILATE)
        inbox = np.zeros_like(wide)
        inbox[0:200, 0:400] = True
        self.assertTrue((np.asarray(m["band"]) > 0).tolist() == (wide & ~t & inbox).tolist())

    def test_people_pasted_back_pixel_exact_and_nothing_outside_the_box_changes(self):
        pic, alpha = picture_and_alpha()
        box = {"x": 0, "y": 0, "w": 400, "h": 200}
        m = RS.repaint_masks(alpha, box)
        magenta = Image.new("RGB", (512, 384), (255, 0, 255))              # the edit model's own size
        cyan = Image.new("RGB", (512, 384), (0, 255, 255))
        p1 = RS.composite_through(pic, magenta, RS.inward(m["area"], RS.AREA_FEATHER))
        p2 = RS.composite_through(p1, cyan, m["band"])
        final = RS.paste_people(pic, p2, m["tight"])
        f, o, tight, band = final.load(), pic.load(), m["tight"].load(), m["band"].load()
        for y in range(0, 300, 3):
            for x in range(0, 400, 3):
                if tight[x, y]:
                    self.assertEqual(f[x, y], o[x, y], (x, y))               # the people: the original pixels
                if y >= 200:
                    self.assertEqual(f[x, y], o[x, y], (x, y))               # outside the box: unchanged
        self.assertEqual(f[30, 30], (255, 0, 255))                          # the repainted background
        self.assertEqual(f[160, 90], (0, 255, 255))                         # the halo band, cleaned in pass 2
        self.assertEqual(band[160, 90], 255)

    def test_default_box_and_oval(self):
        b = RS.default_box([{"x": 100, "y": 100, "r": 20}], (400, 300))
        self.assertEqual((b["x"], b["y"], b["w"], b["h"]), (0, 0, 400, 150))
        self.assertEqual(RS.default_box([], (400, 300))["h"], 180)
        self.assertEqual(RS.box_px({"x": -5, "y": 10, "w": 9999, "h": 20}, (400, 300)), (0, 10, 400, 30))
        o = RS.default_oval({"x": 50, "y": 60, "r": 10}, (400, 300))
        self.assertEqual((o["cx"], o["rx"]), (50, 7.8))


class PromptTest(unittest.TestCase):
    def test_wall_prompt_is_straight_on_and_never_moves_the_camera(self):
        t = RS.wall_template("family side wall", "a stone fireplace, a gold-framed portrait of a bearded man", True)
        self.assertIn("straight-on", t)
        self.assertIn("stone fireplace", t)
        self.assertIn("ONLY for the drawing style", t)
        self.assertIsNone(RS.straight_on_problem(t))
        self.assertNotRegex(t.lower(), r"(move|rotate|turn|orbit|pan)\b[^.]{0,30}camera")
        self.assertNotIn("camera", t.lower())
        for bad in ("Rotate the camera 180 degrees to show the family", "move the camera to the other side",
                    "the camera turns around", "a reverse angle of the room", "show the room from the opposite side",
                    "turn the view to face the window"):
            self.assertIsNotNone(RS.straight_on_problem(bad), bad)
        self.assertIsNone(RS.straight_on_problem("A turning globe on the shelf. A camera on the desk."))

    def test_seating_prompt_names_everyone_in_order(self):
        t = RS.seating_template([("Sidney", "thin pencil moustache"), ("Winifred", "grey bun")], True,
                                "The eyes look slightly to the LEFT of the viewer (screen-left), toward Mortimer, not at the camera.")
        self.assertLess(t.index("1. Sidney (image 2)"), t.index("2. Winifred (image 3)"))
        self.assertIn("never merge", t)
        self.assertIn("screen-left", t)
        g = RS.ensure_seats("Two people sit on chairs.", [("Sidney", ""), ("Winifred", "")])
        self.assertIn("Sidney (image 2), Winifred (image 3)", g)
        self.assertEqual(RS.ensure_seats("Sidney and Winifred sit.", [("Sidney", ""), ("Winifred", "")]), "Sidney and Winifred sit.")
        r = RS.remake_prompt("Base.", ["Ronald", "Sidney"])
        self.assertIn("exactly 2 different characters must be visible: Ronald, Sidney", r)


class CheckTest(unittest.TestCase):
    def test_a_missing_or_merged_character_is_flagged(self):
        res = RS.parse_check('{"visible": ["ronald", "Ann"], "missing": [], "merged": [["Ronald", "Sidney"]], "extra_people": 0}',
                             ["Ronald", "Sidney", "Ann"])
        self.assertEqual(res["missing"], ["Sidney"])                         # not said to be visible: missing
        self.assertEqual(res["merged"], [["Ronald", "Sidney"]])
        f = RS.check_flags(["Ronald", "Sidney", "Ann"], 2, res)
        self.assertTrue(any("Only 2 head(s) found for 3 characters" in x for x in f))
        self.assertTrue(any("cannot see: Sidney" in x for x in f))
        self.assertTrue(any("Ronald and Sidney" in x for x in f))
        self.assertEqual(RS.check_flags(["A", "B"], 2, {"visible": ["A", "B"], "missing": [], "merged": []}), [])
        with self.assertRaises(ValueError):
            RS.parse_check("no json here", ["A"])

    def test_estimates(self):
        e = RS.repair_estimate("background", [1.0, 2.0])
        self.assertEqual(e["edits"], 2)
        self.assertGreater(e["usd_max"], e["usd_typical"])
        self.assertLess(RS.repair_estimate("face", [1.0])["minutes"], e["minutes"])
        g = RS.gemini_estimate({"acting_model": "m", "acting_usd_in": 2.0, "acting_usd_out": 12.0, "acting_free_models": ["f"]},
                               "x" * 350, True)
        self.assertEqual(g["free_models"], ["f"])
        self.assertAlmostEqual(g["usd_max"], round((1300 + 100) * 2 / 1e6 + 4000 * 12 / 1e6, 4))


class ProposalTest(unittest.TestCase):
    def test_new_proposals_are_validated(self):
        p = SC.validate_proposal("wall", "ab12", {"type": "remake_wall", "prompt": "The back wall, straight-on: bookcases."})
        self.assertEqual(p["type"], "remake_wall")
        with self.assertRaises(ValueError):          # the model cannot move the camera: refused
            SC.validate_proposal("wall", "ab12", {"type": "remake_wall", "prompt": "Rotate the camera to the family side."})
        with self.assertRaises(ValueError):
            SC.validate_proposal("wall", "ab12", {"type": "repaint_background", "prompt": "fireplace"})   # not this step's
        r = SC.validate_proposal("seating", "family", {"type": "repaint_background", "prompt": "the fireplace wall",
                                                       "box": {"x": 0, "y": 0, "w": 800, "h": 300}})
        self.assertEqual(r["box"]["w"], 800)
        self.assertNotIn("box", SC.validate_proposal("repair", "ab12", {"type": "repaint_background", "prompt": "the fireplace wall"}))
        for bad in ({"type": "repaint_background", "prompt": "x y z", "box": {"x": 0, "y": 0, "w": 2, "h": 300}},
                    {"type": "repaint_background", "prompt": "fireplace", "seed": 3},
                    {"type": "repaint_background"}):
            with self.assertRaises(ValueError):
                SC.validate_proposal("seating", "family", bad)
        self.assertIn("pasted back", SC.describe(r))
        self.assertIn("straight-on", SC.describe(p))


# ================================================================== API and jobs
class FakeWaveSpeed:
    def __init__(self):
        self.runs, self.uploads = [], []

    def upload(self, path):
        self.uploads.append(Path(path).name)
        return f"https://ws.example/up/{len(self.uploads)}"

    def run(self, endpoint, body, out):
        self.runs.append((endpoint, body))
        Image.new("RGB", (64, 36), (120, 60 + len(self.runs) * 20, 40)).save(out)
        return {"id": f"t{len(self.runs)}", "status": "completed", "outputs": ["https://ws.example/o"]}


class Base(ApiBase):
    def setUp(self):
        super().setUp()
        from oddstudio import wavespeed
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset
        from oddstudio.storage import storage
        self.ws = FakeWaveSpeed()
        wavespeed.set_test_run(self.ws.run)
        wavespeed.set_test_upload(self.ws.upload)
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        with new_session() as db:
            for c in db.query(Character).filter(Character.key.in_(["mort", "sid", "win"])):
                k = f"characters/{c.key}/master.png"
                storage().put_file(k, png(tmp / f"{c.key}.png", Image.new("RGB", (30, 40), (250, 250, 250))), "image/png")
                db.add(CharacterAsset(character_id=c.id, kind="master", status="approved", storage_key=k, style_version="v2"))
            db.commit()

    def tearDown(self):
        from oddstudio import wavespeed
        wavespeed.set_test_run(None)
        wavespeed.set_test_upload(None)
        super().tearDown()

    def u(self, tail=""):
        return f"/api/episodes/{self.eid}/room-sets{tail}"

    def wall(self, t, name):
        return next(w for w in t["walls"] if w["name"] == name)

    def seat(self, t, side):
        return next(s for s in t["seating"] if s["side"] == side)


class WallsAndSeatingTest(Base):
    def test_wall_then_seating_master_then_close_ups(self):
        t = self.c.get(self.u()).json()
        self.assertEqual([s["side"] for s in t["seating"]], ["study", "family"])
        self.assertEqual(t["style_ref"]["source"], "suggested")                      # the first approved wide still
        self.assertEqual(t["style_ref"]["asset_id"], self.fam)
        cost = t["image_cost"]
        self.assertEqual(cost["usd"], 0.04)
        # a wall: added (free), its prompt straight-on; an owner prompt asking to move the camera is refused
        t = self.c.post(self.u("/walls"), json={"name": "family side wall", "side": "family",
                                                 "contents": "a stone fireplace, a gold-framed portrait of a bearded man"}).json()
        w = self.wall(t, "family side wall")
        self.assertEqual(w["prompt"]["source"], "template")
        self.assertIsNone(RS.straight_on_problem(w["prompt"]["text"]))
        r = self.c.put(self.u(f"/walls/{w['id']}"), json={"prompt": "Rotate the camera 180 degrees to face the family."})
        self.assertEqual(r.status_code, 422)
        self.assertIn("cannot move or turn the camera", r.json()["detail"])
        self.assertEqual(self.c.put(self.u(f"/walls/{w['id']}"), json={"side": "nowhere"}).status_code, 422)
        # paid: 409 without the exact price, nothing sent
        for bad in ({}, {"confirm_usd": 0.03}):
            r = self.c.post(self.u(f"/walls/{w['id']}/make"), json=bad)
            self.assertEqual(r.status_code, 409)
            self.assertIn("confirm that amount", r.json()["detail"])
        self.assertEqual(self.ws.runs, [])
        r = self.c.post(self.u(f"/walls/{w['id']}/make"), json={"confirm_usd": cost["usd"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["room_image"])
        self.assertEqual(ran[0][:2], ("room_image", "succeeded"), ran)
        endpoint, body = self.ws.runs[0]
        self.assertEqual(endpoint, "google/nano-banana-2.1/edit")
        self.assertEqual(len(body["images"]), 1)                                      # the wide shot: style only
        self.assertIn("ONLY for the drawing style", body["prompt"])
        self.assertNotIn("camera", body["prompt"].lower())
        w = self.wall(self.c.get(self.u()).json(), "family side wall")
        self.assertEqual(len(w["takes"]), 1)
        self.assertIsNone(w["approved"])                                              # nothing approves itself
        t = self.c.post(self.u(f"/walls/{w['id']}/approve"), json={"take_id": w["takes"][0]["id"]}).json()
        fam = self.seat(t, "family")
        self.assertTrue(fam["wall"]["url"])
        # the seating master: the approved wall as image 1, then each master in seat order
        self.assertIn("1. Sidney (image 2)", fam["prompt"]["text"])
        self.assertIn("2. Winifred (image 3)", fam["prompt"]["text"])
        self.assertIn("screen-left", fam["prompt"]["text"])                           # the family looks toward Mortimer
        self.assertEqual(fam["eyeline"]["default"], "left")
        self.assertEqual(self.c.post(self.u("/seating/family/make"), json={}).status_code, 409)
        r = self.c.post(self.u("/seating/family/make"), json={"confirm_usd": cost["usd"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.post(self.u("/seating/family/make"), json={"confirm_usd": cost["usd"]}).status_code, 409)  # busy
        self.env.run_jobs(["room_image"])
        endpoint, body = self.ws.runs[1]
        self.assertEqual(len(body["images"]), 3)
        self.assertEqual(self.ws.uploads[-3:], ["ref-0.png", "ref-1.png", "ref-2.png"])  # wall, Sidney, Winifred
        fam = self.seat(self.c.get(self.u()).json(), "family")
        self.assertIsNone(fam["approved"])
        t = self.c.post(self.u("/seating/family/approve"), json={"take_id": fam["takes"][0]["id"]}).json()
        fam = self.seat(t, "family")
        self.assertFalse(fam["used_for_closeups"])                                    # not picked for the owner
        # reactions offers it first (suggested), and only the owner's click uses it
        rv = self.c.get(f"/api/episodes/{self.eid}/reactions").json()
        m = next(x for x in rv["masters"] if x["side"] == "family")
        self.assertEqual(m["suggested"], fam["takes"][0]["asset_id"])
        self.assertIsNone(m["chosen"])
        t = self.c.post(self.u("/seating/family/use-for-closeups")).json()
        self.assertTrue(self.seat(t, "family")["used_for_closeups"])
        rv = self.c.get(f"/api/episodes/{self.eid}/reactions").json()
        self.assertEqual(next(x for x in rv["masters"] if x["side"] == "family")["chosen"], fam["takes"][0]["asset_id"])
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["sets"]
        self.assertIn("1 of 1 walls approved, 1 of 2 seating pictures approved", g["detail"])
        self.assertEqual(g["status"], "needs_approval")

    def test_gpt_wall_prompt_that_moves_the_camera_is_not_used(self):
        from oddstudio import prompt_writer as PW
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        from test_guided_generation import openai_response
        t = self.c.post(self.u("/walls"), json={"name": "back wall", "contents": "bookcases"}).json()
        wid = self.wall(t, "back wall")["id"]
        t = self.c.post(self.u(f"/walls/{wid}/write-prompt"), json={}).json()        # no key: the labelled template
        self.assertEqual(self.wall(t, "back wall")["prompt"]["label"], RS.TEMPLATE_LABEL)
        with new_session() as db:
            put_secrets(db, {"openai_api_key": FAKE_OPENAI})
        answers = ["Turn the camera around to show the back wall with bookcases.", "The back wall seen straight-on: tall bookcases."]
        PW.set_test_http_client(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=openai_response(answers.pop(0))))))
        try:
            self.assertEqual(self.c.post(self.u(f"/walls/{wid}/write-prompt"), json={}).status_code, 409)
            t = self.c.post(self.u(f"/walls/{wid}/write-prompt"), json={"confirm_usd": 1}).json()
            p = self.wall(t, "back wall")["prompt"]
            self.assertEqual(p["source"], "template")
            self.assertIn("GPT asked to move the camera", p["label"])
            t = self.c.post(self.u(f"/walls/{wid}/write-prompt"), json={"confirm_usd": 1}).json()
            self.assertEqual(self.wall(t, "back wall")["prompt"]["source"], "gpt")
        finally:
            PW.set_test_http_client(None)
        self.assertNotIn(FAKE_OPENAI, json.dumps(t))

    def test_eyeline_per_side_reaches_the_talking_prompt(self):
        from oddstudio import talking_s2v as T
        t = self.c.get(self.u()).json()
        self.assertEqual(self.seat(t, "study")["eyeline"]["direction"], "right")     # Mortimer, the main speaker
        tv = self.c.get(f"/api/episodes/{self.eid}/talking").json()
        p = next(s for s in tv["shots"] if s["index"] == 1)["prompt"]["text"]
        self.assertIn("screen-right", p)
        t = self.c.put(self.u("/seating/study/eyeline"), json={"eyeline": "left"}).json()
        self.assertEqual((self.seat(t, "study")["eyeline"]["direction"], self.seat(t, "study")["eyeline"]["owner"]), ("left", "left"))
        tv = self.c.get(f"/api/episodes/{self.eid}/talking").json()
        self.assertIn("screen-left", next(s for s in tv["shots"] if s["index"] == 1)["prompt"]["text"])
        rv = self.c.get(f"/api/episodes/{self.eid}/reactions").json()                 # the same storage as reactions
        self.assertEqual(next(m for m in rv["masters"] if m["side"] == "study")["eyeline"], "left")
        t = self.c.put(self.u("/seating/study/eyeline"), json={"eyeline": None}).json()
        self.assertEqual(self.seat(t, "study")["eyeline"]["direction"], "right")
        self.assertEqual(self.c.put(self.u("/seating/nowhere/eyeline"), json={"eyeline": "left"}).status_code, 404)
        self.assertIn("screen-left", T.template_prompt("Ann", "", [], eyeline="Eyes screen-left."))


class CharacterCheckTest(Base):
    def three_in_shot3(self):
        from oddstudio.db import new_session
        from oddstudio.models import Setting
        with new_session() as db:
            row = db.get(Setting, f"shotframes:{self.eid}")
            v = json.loads(json.dumps(row.value))
            v["shots"][2]["people"] = ["sid", "win", "mort"]
            row.value = v
            db.commit()

    def test_missing_character_flagged_by_heads_and_gemini_then_remade(self):
        from oddstudio import acting_analysis as AA
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        t = self.c.get(self.u()).json()
        c3 = next(c for c in t["checks"] if c["target"] == "still:3")
        self.assertEqual((c3["heads"], c3["flags"]), (2, []))                       # two heads, two characters
        self.three_in_shot3()
        t = self.c.get(self.u()).json()
        c3 = next(c for c in t["checks"] if c["target"] == "still:3")
        self.assertEqual(c3["names"], ["Sidney", "Winifred", "Mortimer"])
        self.assertIn("Only 2 head(s) found for 3 characters", c3["flags"][0])
        # Gemini: the key first, then the price; the free tier only when ticked
        body = {"target": "still:3"}
        self.assertIn("Gemini key", self.c.post(self.u("/checks/gemini"), json=body).json()["detail"])
        with new_session() as db:
            put_secrets(db, {"gemini_api_key": FAKE_GEMINI})
        seen = []

        def handler(request):
            seen.append((str(request.url), json.loads(request.content), dict(request.headers)))
            answer = {"visible": ["Sidney", "Winifred"], "missing": ["Mortimer"], "merged": [], "extra_people": 0,
                      "notes": "Only two people."}
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}],
                                             "usageMetadata": {"promptTokenCount": 1400, "candidatesTokenCount": 60}})
        AA.set_test_transport(httpx.MockTransport(handler))
        try:
            r = self.c.post(self.u("/checks/gemini"), json=body)
            self.assertEqual(r.status_code, 409)
            self.assertEqual(seen, [])
            est = t["gemini"]["estimate"]["usd_max"]
            t = self.c.post(self.u("/checks/gemini"), json={**body, "confirm_usd": 1}).json()
        finally:
            AA.set_test_transport(None)
        self.assertEqual(len(seen), 1)
        url, req, headers = seen[0]
        self.assertIn(":generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], FAKE_GEMINI)
        self.assertIn("inline_data", json.dumps(req))
        self.assertIn("- Mortimer: round wire glasses", req["contents"][0]["parts"][1]["text"])
        self.assertGreater(est, 0)
        c3 = next(c for c in t["checks"] if c["target"] == "still:3")
        self.assertEqual(c3["gemini"]["missing"], ["Mortimer"])
        self.assertTrue(any("cannot see: Mortimer" in f for f in c3["flags"]))
        self.assertNotIn(FAKE_GEMINI, json.dumps(t))
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["sets"]
        self.assertIn("may be missing a character", g["detail"])
        # "Remake this picture": one Nano still with the cast spelled out, confirmed first, not approved
        self.assertEqual(self.c.post(self.u("/checks/remake"), json=body).status_code, 409)
        r = self.c.post(self.u("/checks/remake"), json={**body, "confirm_usd": 0.04})
        self.assertEqual(r.status_code, 200, r.text)
        from oddstudio.models import Job
        with new_session() as db:
            j = db.get(Job, r.json()["id"])
            self.assertEqual(j.kind, "stick_shot_still")
            self.assertIn("exactly 3 different characters must be visible: Sidney, Winifred, Mortimer", j.payload["prompt"])
        self.assertEqual(self.c.post(self.u("/checks/remake"), json={"target": "still:99", "confirm_usd": 0.04}).status_code, 404)


def alpha_runner(alpha: Image.Image, calls: list):
    """SSH/scp to the pod, faked: the copy-back writes the people's alpha where the studio asked for it."""
    def fake(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "scp" and "@" not in cmd[-1]:
            alpha.save(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return fake


class RepairTest(Base):
    def test_repair_needs_rented_mode_confirmation_and_cap(self):
        body = {"target": "still:3", "tool": "background", "want": "the fireplace wall instead of the window"}
        self.assertEqual(self.c.post(self.u("/repairs"), json={**body, "target": "still:2"}).status_code, 409)   # not approved
        self.assertEqual(self.c.post(self.u("/repairs"), json={**body, "target": "nope"}).status_code, 422)
        r = self.c.post(self.u("/repairs"), json={**body, "confirm_usd": 5})
        self.assertIn("Rented", r.json()["detail"])
        self.rented()
        est = self.c.get(self.u()).json()["repair_estimates"]["background"]
        r = self.c.post(self.u("/repairs"), json={**body, "confirm_usd": est["usd_max"] - 0.01})
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm that amount", r.json()["detail"])
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 0.1})
        r = self.c.post(self.u("/repairs"), json={**body, "confirm_usd": est["usd_max"]})
        self.assertIn("monthly GPU cap", r.json()["detail"])
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 50})
        self.assertEqual(self.c.post(self.u("/repairs"), json={**body, "tool": "face", "character": "mort", "confirm_usd": 5}).status_code, 422)
        r = self.c.post(self.u("/repairs"), json={**body, "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("already running", self.c.post(self.u("/repairs"), json={**body, "confirm_usd": est["usd_max"]}).json()["detail"])
        rep = self.c.get(self.u()).json()["repairs"][0]
        self.assertEqual(rep["box"]["y"], 0)                                            # suggested above the people
        self.assertTrue(rep["before_url"])
        self.assertIsNone(rep["approved"])

    def test_background_repair_end_to_end(self):
        from oddstudio import cutout_remote as CR
        from oddstudio.db import new_session
        from oddstudio.storage import storage
        self.rented()
        rp, cf = FakeRunPod(), FakeComfy()
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(cf))
        # the people of the family still: two white heads (600, 400) and (1300, 400), radius 70, plus their bodies
        alpha = Image.new("L", (1920, 1080), 0)
        d = ImageDraw.Draw(alpha)
        for x in (600, 1300):
            d.ellipse((x - 72, 328, x + 72, 472), fill=255)
            d.rectangle((x - 40, 470, x + 40, 880), fill=255)
        calls = []
        old = CR.runner
        CR.runner = alpha_runner(alpha, calls)
        try:
            est = self.c.get(self.u()).json()["repair_estimates"]["background"]
            box = {"x": 0, "y": 0, "w": 1920, "h": 600}
            r = self.c.post(self.u("/repairs"), json={"target": "still:3", "tool": "background", "box": box,
                                                       "want": "the fireplace wall with a bearded portrait, no window",
                                                       "confirm_usd": est["usd_max"]})
            self.assertEqual(r.status_code, 200, r.text)
            ran = self.env.run_jobs(["room_repair"])
        finally:
            CR.runner = old
        self.assertEqual(ran[0][:2], ("room_repair", "succeeded"), ran)
        self.assertTrue(any(c[0] == "ssh" and "rembg[gpu]==2.0.67" in c[-1] and "birefnet-general" in c[-1] for c in calls))
        self.assertTrue(all("StrictHostKeyChecking=no" in c for c in calls))
        self.assertEqual(len(cf.graphs), 2)                                           # the repaint and the halo pass
        self.assertTrue(all("nm2" in g for g in cf.graphs))
        self.assertIn("fireplace wall", cf.graphs[0]["pe"]["inputs"]["prompt"])
        self.assertIn("thin area", cf.graphs[1]["pe"]["inputs"]["prompt"])
        rep = self.c.get(self.u()).json()["repairs"][0]
        self.assertEqual(rep["status"], "done")
        self.assertTrue(rep["after_url"] and rep["before_url"] and rep["mask_url"])
        self.assertIsNone(rep["approved"])                                            # nothing approves itself
        with new_session() as db:
            self.assertEqual([x["status"] for x in gpu.ledger(db)["sessions"].values()], ["ended"])   # GPU off
            v = RS.stored(db, self.eid)["repairs"][rep["id"]]
            after = Image.open(storage().local_path(v["result_key"])).convert("RGB")
            before = Image.open(storage().local_path(v["src_key"])).convert("RGB")
        masks = RS.repaint_masks(alpha, box)
        tight = masks["tight"].load()
        a, b = after.load(), before.load()
        for y in range(0, 1080, 12):
            for x in range(0, 1920, 12):
                if tight[x, y] or y >= 600:
                    self.assertEqual(a[x, y], b[x, y], (x, y))                        # people and below the box: exact
        self.assertEqual(a[100, 100], (255, 0, 255))                                  # the repainted wall
        # the owner approves: the result becomes shot 3's approved still (a new version)
        self.assertEqual(self.c.post(self.u(f"/repairs/{rep['id']}/approve"), json={"approved": True}).status_code, 200)
        f = self.c.get(f"/api/episodes/{self.eid}/shot-frames").json()
        s3 = next(s for s in f["shots"] if s["index"] == 3)
        self.assertEqual((s3["chosen"], s3["approved"]), (v["result_asset"], True))
        self.assertEqual(self.c.post(self.u(f"/repairs/{rep['id']}/approve"), json={"approved": True}).status_code, 409)

    def test_face_fix_on_a_seating_picture(self):
        from oddstudio.db import new_session
        from oddstudio.storage import storage
        self.rented()
        rp, cf = FakeRunPod(), FakeComfy()
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(cf))
        # an approved seating picture (the family still stored as a take, as the job would)
        with new_session() as db:
            from oddstudio.models import Asset
            a = db.get(Asset, self.fam)
            v = RS.stored(db, self.eid)
            v["seating"] = {"family": {"takes": [{"id": "t1", "key": a.storage_key, "asset_id": a.id, "at": 0}], "approved": "t1"}}
            RS.save(db, self.eid, v)
            db.commit()
        est = self.c.get(self.u()).json()["repair_estimates"]["face"]
        r = self.c.post(self.u("/repairs"), json={"target": "seating:family", "tool": "face", "character": "sid",
                                                   "want": "a small worried frown", "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["room_repair"])
        self.assertEqual(ran[0][:2], ("room_repair", "succeeded"), ran)
        self.assertEqual(len(cf.graphs), 1)
        prompt = cf.graphs[0]["pe"]["inputs"]["prompt"]
        self.assertIn("Sidney (thin pencil moustache)", prompt)
        self.assertIn("screen-left", prompt)
        self.assertIn("Do not add glasses", prompt)
        t = self.c.get(self.u()).json()
        rep = t["repairs"][0]
        self.assertLess(abs(rep["oval"]["cx"] - 600), 25)                            # on Sidney's head
        with new_session() as db:
            v = RS.stored(db, self.eid)["repairs"][rep["id"]]
            after = Image.open(storage().local_path(v["result_key"])).convert("RGB")
            before = Image.open(storage().local_path(v["src_key"])).convert("RGB")
        self.assertEqual(after.size, before.size)
        self.assertEqual(after.getpixel((1300, 400)), before.getpixel((1300, 400)))   # Winifred untouched
        self.assertEqual(after.getpixel((600, 400)), (255, 0, 255))
        t = self.c.post(self.u(f"/repairs/{rep['id']}/approve"), json={"approved": True}).json()
        fam = self.seat(t, "family")
        self.assertEqual(len(fam["takes"]), 2)
        self.assertEqual(fam["approved"], fam["takes"][1]["id"])


class ChatTest(Base):
    def test_threads_and_paid_proposals(self):
        t = self.c.post(self.u("/walls"), json={"name": "back wall", "contents": "bookcases"}).json()
        wid = self.wall(t, "back wall")["id"]
        for step, item, allowed in (("wall", wid, ["note_only", "remake_wall"]),
                                    ("seating", "family", ["note_only", "repaint_background"])):
            r = self.c.get("/api/shot-chat/thread", params={"step": step, "item": item, "episode_id": self.eid})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["proposals"], allowed)
        from oddstudio.db import new_session
        with new_session() as db:
            ref = SC.Ref(episode_id=self.eid, step="wall", item=wid)
            self.assertEqual(SC.thread_id(ref), f"wall:{wid}")
            cx = SC.build_context(db, ref)
            self.assertIn("straight-on", cx["current_prompt"])
            self.assertIn("cannot move or turn the camera", cx["settings"]["rules"])
            cx = SC.build_context(db, SC.Ref(episode_id=self.eid, step="seating", item="family"))
            self.assertEqual(cx["settings"]["seat_order"], ["Sidney", "Winifred"])
            self.assertTrue(any("Sidney" in c for c in cx["characters"]))
            self.assertEqual(SC.thread_id(SC.Ref(episode_id=self.eid, step="repair", item="ab12")), "repair:ab12")
            self.assertEqual(SC.proposal_cost(db, ref, {"type": "remake_wall", "prompt": "x"})["usd"], 0.04)
            SC.add_messages(db, ref, [{"id": "m1", "role": "assistant", "text": "remake", "at": 0,
                                       "proposal": {"type": "remake_wall", "prompt": "The back wall, straight-on: tall bookcases."},
                                       "proposal_status": "pending"}])
            db.commit()
        body = {"step": "wall", "item": wid, "episode_id": self.eid, "message_id": "m1"}
        self.assertEqual(self.c.post("/api/shot-chat/apply", json=body).status_code, 409)
        self.assertEqual(self.c.post("/api/shot-chat/apply", json={**body, "confirm_usd": 0.03}).status_code, 409)
        r = self.c.post("/api/shot-chat/apply", json={**body, "confirm_usd": 0.04})
        self.assertEqual(r.status_code, 200, r.text)
        w = self.wall(self.c.get(self.u()).json(), "back wall")
        self.assertEqual((w["prompt"]["source"], w["prompt"]["text"]), ("owner", "The back wall, straight-on: tall bookcases."))
        self.assertTrue(w["busy"])


if __name__ == "__main__":
    unittest.main()
