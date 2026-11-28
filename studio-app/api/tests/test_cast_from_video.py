"""Cast from video (2026-11-26, cast_from_video.py): the characters described from the reference video in WORDS
(Gemini over a mocked transport), the five style presets and their prompt assembly, style previews (cost first, 409,
never choosing the style), master candidates (cost first, 409), the owner's approval locking the master (a new version
needs new_version), "save to my cast library" vs "this episode only", reusing a saved character at no cost, removing it
from the library without touching any master, the chat proposals edit_description / new_candidates, head finding
falling back to the owner's clicks for non-stick styles, and the autopilot's cast step (describe -> candidates -> wait).

The owner's hard rule is asserted directly: no request to the image model ever carries the reference video or a frame
of it (only text and the studio's own style references), and a private file is refused as a reference. No network and
no paid call: Gemini is an httpx.MockTransport, WaveSpeed a stub, and only fake credentials are used."""
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image

from helpers import Env
from test_guided_generation import GeminiFake, gem_answer
from test_stick_pipeline import Stub, png_bytes, uninstall

from oddstudio import acting_analysis as AA
from oddstudio import autopilot as AP
from oddstudio import cast_from_video as CV
from oddstudio import cast_styles
from oddstudio import prompt_writer as PW
from oddstudio import shot_chat as SC

FAKE = {"gemini_api_key": "fake-gemini-credential-for-tests", "openai_api_key": "fake-openai-credential-for-tests",
        "wavespeed_api_key": "fake-wavespeed-credential-for-tests"}
SHOTS = [{"index": i, "t0": (i - 1) * 3.0, "t1": i * 3.0, "people": []} for i in range(1, 5)]
VIDEO = b"\x00\x00\x00\x18ftypmp42fake-reference-video-bytes"
ANSWER = {"characters": [
    {"name": "ann", "role": "the worried wife", "age": "about 40", "build": "slim",
     "hair": {"style": "long and wavy", "colour": "auburn"}, "clothing": [{"garment": "cardigan", "colour": "green"}, "jeans"],
     "accessory": "round glasses", "personality": "anxious, kind", "must_never": ["no hat"]},
    {"name": "Bob", "role": "the calm husband", "age": "about 45", "build": "stocky", "hair": "short grey",
     "clothing": [{"garment": "shirt", "color": "blue"}], "accessory": "a red bow tie", "personality": "dry"},
    {"name": "Person 1", "role": "the neighbour", "accessory": "a yellow cap"},
]}


# ================================================================== pure parts
class PureTest(unittest.TestCase):
    def test_descriptions_are_parsed_and_normalised(self):
        d = CV.normalise_descriptions(ANSWER, ["Ann", "Bob"], {"Ann": {"traits": "nervous but warm"}})
        self.assertEqual([x["name"] for x in d], ["Ann", "Bob", "Person 1"])
        self.assertEqual([x["in_script"] for x in d], [True, True, False])
        ann, bob = d[0], d[1]
        self.assertEqual(ann["hair"], {"style": "long and wavy", "colour": "auburn"})
        self.assertEqual(ann["clothing"], [{"garment": "cardigan", "colour": "green"}, {"garment": "jeans", "colour": ""}])
        self.assertEqual(ann["personality"], "nervous but warm", "the personality comes from the acting analysis' traits")
        self.assertEqual(ann["personality_from"], "acting analysis")
        self.assertEqual(ann["must_never"], ["no hat"])
        self.assertEqual(bob["hair"], {"style": "short grey", "colour": ""})
        self.assertEqual(bob["clothing"], [{"garment": "shirt", "colour": "blue"}])
        self.assertEqual(bob["personality"], "dry")
        # other shapes seen in practice: a bare list, a dict of names; duplicates dropped; at most 8
        self.assertEqual([x["name"] for x in CV.normalise_descriptions([{"name": "Ann"}, {"name": "ANN"}, "junk"], ["Ann"])], ["Ann"])
        self.assertEqual(CV.normalise_descriptions({"characters": {"Bob": {"accessory": "a cap"}}}, [])[0]["accessory"], "a cap")
        many = [{"name": f"P{i}"} for i in range(12)]
        self.assertEqual(len(CV.normalise_descriptions(many, [])), 8)
        self.assertEqual(CV.normalise_descriptions("nonsense", []), [])
        self.assertLessEqual(len(CV.normalise_descriptions([{"name": "A", "role": "x" * 999}], [])[0]["role"]), 300)

    def test_name_matching(self):
        self.assertEqual(CV.match_name("ann", ["Ann", "Bob"]), "Ann")
        self.assertEqual(CV.match_name("Uncle Mortimer", ["Uncle Mortimer"]), "Uncle Mortimer")
        self.assertEqual(CV.match_name("Mortimer Smith", ["Mortimer"]), "Mortimer")
        self.assertIsNone(CV.match_name("Person 1", ["Ann"]))

    def test_prompt_assembly_per_style(self):
        d = CV.normalise_descriptions(ANSWER, ["Ann", "Bob"])[0]
        text = CV.description_text(d)
        for bit in ("Character: Ann (the worried wife).", "Age: about 40.", "Hair: long and wavy, auburn.",
                    "Clothing: green cardigan, jeans.", "Signature accessory", "round glasses", "Must never: no hat."):
            self.assertIn(bit, text)
        for sid in ("flat2d", "3d", "anime", "clay"):
            block = cast_styles.DEFAULT_STYLES[sid]["style_prompt"]
            p = CV.template_prompt(block, d, has_refs=False)
            self.assertTrue(p.startswith(block.strip()), "the style block comes first, unchanged")
            self.assertIn("round glasses", p)
            self.assertNotIn("reference image", p)
            self.assertIn("reference image", CV.template_prompt(block, d, has_refs=True))
        self.assertIn("no nose", cast_styles.FLAT_2D.lower())
        self.assertIn("hook-shaped hands", cast_styles.FLAT_2D)
        for t in (cast_styles.FLAT_2D, cast_styles.ANIMATED_3D, cast_styles.ANIME, cast_styles.CLAY):
            for brand in ("Pixar", "Disney", "Ghibli", "Aardman", "DreamWorks"):
                self.assertNotIn(brand, t, "no brand names in prompts")

    def test_image_request_has_text_and_our_references_only(self):
        prov = {"model": "google/nano-banana-2.1/edit", "t2i_model": "google/nano-banana-2.1/text-to-image"}
        ep, body = CV.image_request(prov, "a prompt", [])
        self.assertEqual(ep, "google/nano-banana-2.1/text-to-image")
        self.assertNotIn("images", body)
        ep, body = CV.image_request(prov, "a prompt", ["https://ws.example/up/1"])
        self.assertEqual((ep, body["images"]), ("google/nano-banana-2.1/edit", ["https://ws.example/up/1"]))

    def test_describe_request_and_estimate(self):
        b = CV.describe_body("https://g.example/files/abc", "video/mp4", "p", 8000)
        self.assertEqual(b["contents"][0]["parts"][0]["video_metadata"], {"fps": 1})
        self.assertEqual(b["generationConfig"]["maxOutputTokens"], 8000)
        e = CV.describe_estimate(30.0, ["Ann"], {"acting_model": "m", "acting_usd_in": 2.0, "acting_usd_out": 12.0}, 8000)
        self.assertGreaterEqual(e["input_tokens"], 30 * AA.TOKENS_PER_SECOND)
        self.assertAlmostEqual(e["usd_max"], round(e["input_tokens"] * 2 / 1e6 + 8000 * 12 / 1e6, 4))
        self.assertIn("Never describe the real person's face", CV.describe_prompt(["Ann"]))


# ================================================================== API
class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.stub = Stub().install()
        from oddstudio.models import Character, Episode, Setting
        from oddstudio.secrets_store import put_secrets
        with self.db() as db:
            ep = Episode(title="Cast")
            db.add(ep)
            db.commit()
            self.eid = ep.id
            db.add(Setting(key=f"shotframes:{ep.id}", value={"shots": SHOTS}))
            db.add_all([Character(key="ann", name="Ann", scope="episode", episode_id=ep.id),
                        Character(key="bob", name="Bob", scope="episode", episode_id=ep.id)])
            db.commit()
            self.ann = db.query(Character).filter_by(key="ann").one().id
            self.bob = db.query(Character).filter_by(key="bob").one().id
            put_secrets(db, FAKE)

    def tearDown(self):
        uninstall()
        AA.set_test_transport(None)
        PW.set_test_http_client(None)
        self.env.close()

    def db(self):
        from oddstudio.db import new_session
        return new_session()

    def url(self, tail=""):
        return f"/api/episodes/{self.eid}/cast-video{tail}"

    def upload_video(self):
        r = self.c.put(f"/api/episodes/{self.eid}/guide/reference-video", content=VIDEO, headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)

    def describe(self, answer=ANSWER):
        self.upload_video()
        fake = GeminiFake([gem_answer(answer)])
        AA.set_test_transport(httpx.MockTransport(fake))
        est = self.c.get(self.url()).json()["describe"]["estimate"]
        r = self.c.post(self.url("/describe"), json={"confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["cast_describe"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        return fake

    def jobs(self, kind=None):
        from oddstudio.models import Job
        with self.db() as db:
            q = db.query(Job)
            if kind:
                q = q.filter_by(kind=kind)
            return [(j.kind, j.status) for j in q.order_by(Job.id)]

    def ledger(self):
        from oddstudio.models import Setting
        with self.db() as db:
            row = db.query(Setting).filter(Setting.key.like("fal%")).all()
            return json.dumps([r.value for r in row])

    def set_style(self, style, **kw):
        r = self.c.put(self.url("/style"), json={"style": style, **kw})
        return r

    def candidates(self, cid, count=2, **kw):
        return self.c.post(self.url(f"/characters/{cid}/candidates"), json={"count": count, **kw})

    def make_candidates(self, cid, count=2, **kw):
        r = self.candidates(cid, count, confirm_usd=round(0.04 * count, 2), **kw)
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["cast_images"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        return next(c for c in self.c.get(self.url()).json()["characters"] if c["id"] == cid)["candidates"]


class DescribeTest(Base):
    def test_describe_needs_the_confirmed_price(self):
        self.upload_video()
        v = self.c.get(self.url()).json()["describe"]
        self.assertTrue(v["estimate"] and v["estimate"]["usd_max"] > 0)
        self.assertEqual(self.c.post(self.url("/describe"), json={}).status_code, 409)
        r = self.c.post(self.url("/describe"), json={"confirm_usd": v["estimate"]["usd_max"] / 2})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.jobs("cast_describe"), [])

    def test_descriptions_mapped_to_the_cast_editable_and_words_only(self):
        fake = self.describe()
        self.assertEqual(fake.deleted, ["files/abc"], "the uploaded video is deleted from Google")
        self.assertEqual([m for m, _ in fake.calls], ["gemini-3.1-pro-preview"], "the free tier only when ticked")
        v = self.c.get(self.url()).json()
        self.assertNotIn(FAKE["gemini_api_key"], json.dumps(v))
        ds = v["descriptions"]
        self.assertEqual([(d["name"], d["character_id"]) for d in ds], [("Ann", self.ann), ("Bob", self.bob), ("Person 1", None)])
        # the owner edits any field (free); a linked character without a master gets the new written look
        did = ds[0]["id"]
        r = self.c.put(self.url(f"/descriptions/{did}"), json={"accessory": "a pearl necklace",
                                                                "hair": {"style": "bun", "colour": "auburn"}})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()["descriptions"][0]
        self.assertEqual((d["accessory"], d["hair"]["style"]), ("a pearl necklace", "bun"))
        from oddstudio.models import Character
        with self.db() as db:
            self.assertIn("pearl necklace", db.get(Character, self.ann).visual_description)
        self.assertEqual(self.c.put(self.url(f"/descriptions/{did}"), json={"nose": "big"}).status_code, 422)
        # someone the script does not name becomes an episode-only character with one click
        r = self.c.post(self.url(f"/descriptions/{ds[2]['id']}/character"))
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIn("Person 1", [c["name"] for c in r.json()["characters"]])


class StyleAndPreviewTest(Base):
    def test_presets_in_settings_and_stick_uses_studio_style(self):
        st = self.c.get("/api/cast/styles").json()["styles"]
        # the five cartoon presets and the sixth, cinematic-only preset (feat/cinematic-mode)
        self.assertEqual([s["id"] for s in st], ["stick", "flat2d", "3d", "anime", "clay", "cinematic"])
        self.assertEqual([s["label"] for s in st], ["True stick man", "Flat 2D cartoon", "3D animated", "Anime", "Claymation",
                                                    "Cinematic realistic"])
        self.assertIn("TRUE STICK MAN", st[0]["style_prompt"], "the house style block from Settings > Studio style")
        # editable: a bad block or unknown style is refused, a good one is kept
        cur = self.c.get("/api/settings").json()["sections"]["cast"]["styles"]
        bad = {**cur, "anime": {**cur["anime"], "style_prompt": "short"}}
        self.assertEqual(self.c.put("/api/settings/cast", json={"styles": bad}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/cast", json={"styles": {**cur, "oil": cur["anime"]}}).status_code, 422)
        good = {**cur, "anime": {**cur["anime"], "style_prompt": "Clean 2D anime style, thin lines, flat cel shading, plain background."}}
        self.assertEqual(self.c.put("/api/settings/cast", json={"styles": good}).status_code, 200)
        self.assertEqual(CV.style_block(self.db(), "anime")[0], good["anime"]["style_prompt"])
        # a style example uploaded for one preset becomes its reference
        r = self.c.put("/api/cast/styles/clay/reference/upload", content=png_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 201, r.text)
        clay = next(s for s in r.json()["styles"] if s["id"] == "clay")
        self.assertTrue(clay["has_reference"] and clay["examples"])

    def test_previews_cost_409_and_never_choose_the_style(self):
        self.describe()
        r = self.c.post(self.url("/previews"), json={"styles": ["stick", "3d", "anime"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("$0.12", r.json()["detail"])
        self.assertEqual(self.c.post(self.url("/previews"), json={"styles": ["stick", "3d", "anime"], "confirm_usd": 0.08}).status_code, 409)
        self.assertEqual(self.jobs("cast_images"), [])
        r = self.c.post(self.url("/previews"), json={"confirm_usd": 0.20})        # all five, default: the main speaker
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["cast_images"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        v = self.c.get(self.url()).json()
        self.assertIsNone(v["style"], "a preview never chooses the style")
        self.assertEqual(sorted(v["previews"]["items"]), sorted(["stick", "flat2d", "3d", "anime", "clay"]))
        self.assertTrue(all(c["candidates"] == [] and c["master"] is None for c in v["characters"]),
                        "previews are not masters or candidates")
        self.assertEqual(len(self.stub.runs), 5)
        # the owner picks the style: that style's preview becomes one of the character's candidates
        r = self.set_style("3d")
        self.assertEqual(r.status_code, 200, r.text)
        v = r.json()
        self.assertEqual(v["style"], "3d")
        pc = v["previews"]["character_id"]
        cands = next(c for c in v["characters"] if c["id"] == pc)["candidates"]
        self.assertEqual([(c["style"], c["from_preview"], c["status"]) for c in cands], [("3d", True, "review")])
        g = self.c.get(f"/api/episodes/{self.eid}").json()
        self.assertEqual(g.get("style") or g.get("episode", {}).get("style"), "3d")

    def test_no_reference_video_data_ever_reaches_the_image_model(self):
        self.describe()
        self.c.put("/api/stick/style-reference/upload", content=png_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(self.c.post(self.url("/previews"), json={"styles": ["stick", "clay"], "confirm_usd": 0.08}).status_code, 200)
        self.env.run_jobs(["cast_images"])
        self.assertEqual(self.set_style("stick").status_code, 200)
        self.make_candidates(self.bob, 2)
        self.assertEqual(len(self.stub.runs), 4)
        from oddstudio import guided
        with self.db() as db:
            ref = guided.reference_video(db, self.eid)
        for endpoint, body in self.stub.runs:
            blob = json.dumps(body)
            self.assertEqual(set(body) - {"prompt", "images", "aspect_ratio", "resolution", "output_format"}, set())
            for bad in (ref["key"], "private/", "reference-video", "reference.mp4", "acting/", "fake-reference-video", "g.example/files"):
                self.assertNotIn(bad, blob, f"{bad!r} must never reach the image model")
            for u in body.get("images") or []:
                self.assertTrue(u.startswith("https://ws.example/up/"), u)
        self.assertTrue(self.stub.uploads and all(n.startswith("style-") for n in self.stub.uploads), self.stub.uploads)
        # and a private file is refused as a reference, whatever the caller passes
        from oddstudio.models import Asset
        with self.db() as db:
            a = Asset(kind="style-reference", label="x", storage_key=f"private/episodes/{self.eid}/acting/shot1-1.0s.jpg",
                      content_type="image/jpeg")
            db.add(a)
            db.commit()
            with self.assertRaises(ValueError):
                CV.safe_reference_files(db, [{"kind": "asset", "id": a.id}], Path(tempfile.mkdtemp()))

    def test_style_change_never_changes_approved_masters(self):
        self.describe()
        self.set_style("flat2d")
        cand = self.make_candidates(self.ann, 1)
        self.assertEqual(self.c.post(self.url(f"/characters/{self.ann}/approve"),
                                     json={"asset_id": cand[0]["id"], "keep": "episode"}).status_code, 200)
        r = self.set_style("anime")
        self.assertEqual(r.status_code, 409)
        self.assertIn("never change", r.json()["detail"])
        self.assertEqual(self.set_style("anime", allow_mixed=True).status_code, 200)
        a = next(c for c in self.c.get(self.url()).json()["characters"] if c["id"] == self.ann)
        self.assertEqual((a["master"]["id"], a["master_style"]), (cand[0]["id"], "flat2d"))


class CandidatesAndApprovalTest(Base):
    def test_candidate_cost_409_and_style_needed(self):
        self.describe()
        self.assertEqual(self.candidates(self.ann, 2, confirm_usd=0.08).status_code, 409)     # no style yet
        self.set_style("clay")
        r = self.candidates(self.ann, 3)
        self.assertEqual(r.status_code, 409)
        self.assertIn("$0.12", r.json()["detail"])
        self.assertEqual(self.candidates(self.ann, 3, confirm_usd=0.08).status_code, 409)
        self.assertEqual(self.jobs("cast_images"), [])
        cands = self.make_candidates(self.ann, 3)
        self.assertEqual([c["style"] for c in cands], ["clay"] * 3)
        endpoint, body = self.stub.runs[0]
        self.assertTrue(endpoint.endswith("text-to-image"), "claymation has no style example yet: text only")
        self.assertIn("claymation", body["prompt"].lower())
        self.assertIn("round glasses", body["prompt"])

    def test_approval_locks_the_master(self):
        self.describe()
        self.set_style("3d")
        cands = self.make_candidates(self.ann, 2)
        r = self.c.post(self.url(f"/characters/{self.ann}/approve"), json={"asset_id": cands[0]["id"]})
        self.assertEqual(r.status_code, 422, "the owner must choose: save to the library or this episode only")
        r = self.c.post(self.url(f"/characters/{self.ann}/approve"), json={"asset_id": cands[0]["id"], "keep": "episode"})
        self.assertEqual(r.status_code, 200, r.text)
        ann = next(c for c in r.json()["characters"] if c["id"] == self.ann)
        self.assertEqual((ann["master"]["id"], ann["master"]["status"]), (cands[0]["id"], "approved"))
        # locked: the other candidate cannot replace it, and no new candidates are drawn, without "new version"
        r = self.c.post(self.url(f"/characters/{self.ann}/approve"), json={"asset_id": cands[1]["id"], "keep": "episode"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.candidates(self.ann, 1, confirm_usd=0.04).status_code, 409)
        # editing the description never touches the approved master or its written look
        from oddstudio.models import Character, CharacterAsset
        with self.db() as db:
            look = db.get(Character, self.ann).visual_description
        did = next(d["id"] for d in self.c.get(self.url()).json()["descriptions"] if d["character_id"] == self.ann)
        self.c.put(self.url(f"/descriptions/{did}"), json={"accessory": "a monocle"})
        with self.db() as db:
            self.assertEqual(db.get(Character, self.ann).visual_description, look)
            self.assertEqual(db.get(CharacterAsset, cands[0]["id"]).status, "approved")
        # a new version, explicitly asked for and approved by the owner
        r = self.c.post(self.url(f"/characters/{self.ann}/approve"),
                        json={"asset_id": cands[1]["id"], "keep": "episode", "new_version": True})
        self.assertEqual(r.status_code, 200, r.text)
        with self.db() as db:
            self.assertEqual(db.get(CharacterAsset, cands[0]["id"]).status, "superseded")
            self.assertEqual(db.get(CharacterAsset, cands[1]["id"]).status, "approved")
        from oddstudio.models import Event
        with self.db() as db:
            msgs = [e.message for e in db.query(Event).filter_by(kind="approval")]
        self.assertEqual(len(msgs), 2)
        self.assertTrue(all("owner@example.com" in m for m in msgs), msgs)

    def test_save_to_library_or_episode_only(self):
        self.describe()
        self.set_style("anime")
        a = self.make_candidates(self.ann, 1)
        b = self.make_candidates(self.bob, 1)
        self.c.post(self.url(f"/characters/{self.ann}/approve"), json={"asset_id": a[0]["id"], "keep": "library"})
        self.c.post(self.url(f"/characters/{self.bob}/approve"), json={"asset_id": b[0]["id"], "keep": "episode"})
        lib = self.c.get("/api/cast/library").json()["entries"]
        self.assertEqual([(e["name"], e["style"], e["versions"]) for e in lib], [("Ann", "anime", 1)])
        self.assertEqual(lib[0]["description"]["accessory"], "round glasses")
        self.assertIn(self.eid, lib[0]["used_by"])

    def test_reuse_is_free_and_removal_keeps_the_master(self):
        self.describe()
        self.set_style("anime")
        a = self.make_candidates(self.ann, 1)
        self.c.post(self.url(f"/characters/{self.ann}/approve"), json={"asset_id": a[0]["id"], "keep": "library"})
        lid = self.c.get("/api/cast/library").json()["entries"][0]["id"]
        # a later episode in another style: refused unless the owner accepts a mixed cast
        from oddstudio.models import Episode
        with self.db() as db:
            ep2 = Episode(title="Next", style="3d")
            db.add(ep2)
            db.commit()
            e2 = ep2.id
        self.assertEqual(self.c.post(f"/api/episodes/{e2}/cast-video/library/{lid}/use", json={}).status_code, 409)
        with self.db() as db:
            db.get(Episode, e2).style = "anime"
            db.commit()
        jobs_before, runs_before, ledger_before = self.jobs(), len(self.stub.runs), self.ledger()
        r = self.c.post(f"/api/episodes/{e2}/cast-video/library/{lid}/use", json={})
        self.assertEqual(r.status_code, 200, r.text)
        ann = next(c for c in r.json()["characters"] if c["id"] == self.ann)
        self.assertEqual(ann["master"]["id"], a[0]["id"], "the locked master is used as it is")
        self.assertEqual((self.jobs(), len(self.stub.runs), self.ledger()), (jobs_before, runs_before, ledger_before),
                         "reusing a saved character costs nothing")
        g = self.c.get(f"/api/episodes/{e2}/guide").json()["steps"]["masters"]
        self.assertIn(self.ann, [c["id"] for c in g["characters"] if c["master"]])
        # rename, then remove from the library: the master and both episodes' casts are untouched
        r = self.c.put(f"/api/cast/library/{lid}", json={"name": "Annie"})
        self.assertEqual(r.json()["entries"][0]["name"], "Annie")
        r = self.c.delete(f"/api/cast/library/{lid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["master_kept"])
        self.assertEqual(sorted(r.json()["used_by"]), sorted([self.eid, e2]))
        self.assertEqual(self.c.get("/api/cast/library").json()["entries"], [])
        from oddstudio.models import CharacterAsset
        with self.db() as db:
            self.assertEqual(db.get(CharacterAsset, a[0]["id"]).status, "approved")
        for eid in (self.eid, e2):
            chars = self.c.get(f"/api/episodes/{eid}/cast-video").json()["characters"]
            self.assertEqual(next(c for c in chars if c["id"] == self.ann)["master"]["id"], a[0]["id"])


class ChatTest(Base):
    def test_master_thread_offers_the_cast_proposals(self):
        p = SC.validate_proposal("master", str(self.ann), {"type": "edit_description", "fields": {"accessory": "a monocle"}})
        self.assertEqual(p["fields"], {"accessory": "a monocle"})
        with self.assertRaises(ValueError):
            SC.validate_proposal("master", str(self.ann), {"type": "edit_description", "fields": {}})
        with self.assertRaises(ValueError):
            SC.validate_proposal("master", str(self.ann), {"type": "edit_description", "fields": {"nose": "big"}})
        p = SC.validate_proposal("master", str(self.ann), {"type": "new_candidates", "count": 3})
        self.assertEqual(p["count"], 3)
        self.describe()
        self.set_style("flat2d")
        with self.db() as db:
            ref = SC.Ref(episode_id=self.eid, step="master", item=str(self.ann))
            self.assertIsNone(SC.proposal_cost(db, ref, {"type": "edit_description", "fields": {"accessory": "x"}}))
            self.assertEqual(SC.proposal_cost(db, ref, {"type": "new_candidates", "count": 3})["usd"], 0.12)
            out = SC.route(db, ref, {"type": "edit_description", "fields": {"accessory": "a monocle"}}, None, "owner")
            self.assertIn("updated", out["done"])
            with self.assertRaises(Exception) as e:        # paid: refused without the confirmed price, nothing starts
                SC.route(db, ref, {"type": "new_candidates", "count": 2}, None, "owner")
            self.assertEqual(getattr(e.exception, "status_code", None), 409)
            cx = SC.build_context(db, ref)
            self.assertEqual(cx["description_from_video"]["accessory"], "a monocle")
            self.assertEqual(cx["episode_style"], "Flat 2D cartoon")
        self.assertEqual(self.jobs("cast_images"), [])


class HeadFallbackTest(Base):
    def seating_master(self):
        from oddstudio.tasks import store_asset
        f = Path(tempfile.mkdtemp()) / "m.png"
        Image.new("RGB", (400, 240), (120, 90, 60)).save(f)
        with self.db() as db:
            a = store_asset(db, ep_id=self.eid, src=f, key=f"episodes/{self.eid}/seat.png", kind="still", label="seat",
                            content_type="image/png")
            db.commit()
            return a.id

    def test_non_stick_styles_use_the_owners_clicks(self):
        from oddstudio import reactions as R
        from oddstudio import room_sets as RS
        from oddstudio import talking_s2v as T
        from oddstudio.models import Episode
        aid = self.seating_master()
        found = [{"x": 1, "y": 1, "r": 9, "score": 1.0}]
        old = R.find_heads
        R.find_heads = lambda im: list(found)
        try:
            with self.db() as db:                                   # no style chosen: the stick man, automatic
                self.assertTrue(CV.auto_heads(db, self.eid))
                self.assertEqual(R.master_info(db, {}, aid)["heads"], found)
                db.get(Episode, self.eid).style = "3d"
                db.commit()
            with self.db() as db:
                self.assertFalse(CV.auto_heads(db, self.eid))
                v = {}
                self.assertEqual(R.master_info(db, v, aid)["heads"], [], "no automatic head finding for 3D")
                self.assertIsNone(RS.picture_info({}, f"episodes/{self.eid}/seat.png", auto=False)["heads"])
                self.assertEqual(T.head_for(db, {}, aid, auto=False), {"source": "none", "click_needed": True})
                g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["masters"]["head_finding"]
                self.assertFalse(g["auto"])
                self.assertIn("click each head once", g["note"])
            r = self.c.put(f"/api/episodes/{self.eid}/owner-heads/{aid}", json={"heads": [{"x": 300, "y": 50, "r": 30},
                                                                                         {"x": 100, "y": 60, "r": 30}]})
            self.assertEqual(r.status_code, 200, r.text)
            with self.db() as db:
                heads = R.master_info(db, v, aid)["heads"]
                self.assertEqual([h["x"] for h in heads], [100, 300], "left to right")
                info = RS.picture_info({}, f"episodes/{self.eid}/seat.png", auto=False, owner=CV.owner_heads(db, self.eid, aid))
                self.assertEqual(len(info["heads"]), 2)
        finally:
            R.find_heads = old


class AutopilotCastTest(Base):
    def plan(self):
        with self.db() as db:
            from oddstudio.models import Episode
            ep = db.get(Episode, self.eid)
            return AP.plan_masters(db, ep, {"actions": []})

    def test_describe_then_style_gate_then_candidates_then_approval_gate(self):
        self.upload_video()
        p = self.plan()
        self.assertEqual([a["kind"] for a in p["actions"]], ["cast_describe"])
        AA.set_test_transport(httpx.MockTransport(GeminiFake([gem_answer(ANSWER)])))
        with self.db() as db:
            from oddstudio.models import Episode
            v = {"actions": [], "budget_usd": 1.0, "status": "running", "by": "owner"}
            AP.execute(db, db.get(Episode, self.eid), v, "masters", p["actions"])
            db.commit()
        self.env.run_jobs(["cast_describe"])
        p = self.plan()
        self.assertEqual(p["actions"], [])
        self.assertEqual([w["what"] for w in p["waiting"]],
                         ["Choose the episode's style (you can make a preview of each style first)"],
                         "the autopilot never chooses the style")
        self.set_style("clay")
        p = self.plan()
        kinds = [a["kind"] for a in p["actions"]]
        self.assertEqual(kinds, ["cast_prompt", "cast_candidates", "cast_prompt", "cast_candidates"])
        self.assertEqual(p["actions"][1]["usd"], 0.08)
        # without an OpenAI key: the template prompt, labelled
        from oddstudio.secrets_store import put_secrets
        with self.db() as db:
            put_secrets(db, {"openai_api_key": ""})
        p = self.plan()
        self.assertEqual([a["kind"] for a in p["actions"]], ["cast_candidates", "cast_candidates"])
        with self.db() as db:
            from oddstudio.models import Episode
            v = {"actions": [], "budget_usd": 1.0, "status": "running", "by": "owner"}
            AP.execute(db, db.get(Episode, self.eid), v, "masters", p["actions"])
            db.commit()
        self.env.run_jobs(["cast_images"])
        p = self.plan()
        self.assertEqual([w["what"] for w in p["waiting"]], ["Approve a master for Ann", "Approve a master for Bob"])
        self.assertEqual(p["actions"], [])
        cv = self.c.get(self.url()).json()
        self.assertEqual(cv["characters"][0]["prompt"]["source"], "template")
        self.assertIn("template", cv["characters"][0]["prompt"]["label"])
        from oddstudio.models import Event
        with self.db() as db:
            self.assertEqual(db.query(Event).filter_by(kind="approval").count(), 0, "it never approves")


if __name__ == "__main__":
    unittest.main()
