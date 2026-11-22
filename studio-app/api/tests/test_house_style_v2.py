"""House style v2 behind Settings > creative.style_version: v1 stays the default and unchanged (rollback); v2 prompts carry
the adult minimal rules; white heads unless a character has its own skin tone; v2 poses are tagged and stored apart;
v2 anchors and style references never use v1 art; sets follow the selected version. Image calls are test stand-ins."""
import unittest

from helpers import Env, fake_pose_image

from oddstudio import house_style, providers


class HouseStyleRulesTest(unittest.TestCase):
    def test_v1_is_unchanged(self):
        self.assertIs(house_style.character_rules("v1"), house_style.CHARACTER_RULES)
        self.assertIn("big round expressive eyes", house_style.CHARACTER_RULES)
        self.assertIs(house_style.set_style("v1"), house_style.SET_STYLE)
        self.assertEqual(house_style.restyle_description("v1", "leo"), house_style.RESTYLE_DESCRIPTIONS["leo"])

    def test_v2_rules_remove_every_kids_cue(self):
        r = house_style.character_rules("v2")
        for must in ("ADULT", "about 30% of the total height", "SOLID BLACK vertical ovals with NO whites", "NO ears", "NO nose",
                     "HEAVY thick black wedges", "short thin black line", "CHUNKY solid black rounded blobs", "NO fingers drawn",
                     "clearly TAPERS", "clearly OPEN solid black oval", "HEAVY, confident black lines", "NO shoes", "flat WHITE",
                     "NOT a children's cartoon"):
            self.assertIn(must, r)
        for kid in ("mitten hands", "round expressive eyes", "rounded shoes", "small round ears", "natural skin tone"):
            self.assertNotIn(kid, r)
        s = house_style.set_style("v2")
        self.assertIn("warm interior lamp light against cool blue", s)
        self.assertIn("NO storybook look", s)
        self.assertIn("2D PAINTED ILLUSTRATION", s)
        self.assertIn("NOT photographic, NOT a photo, NOT a 3D render", s)
        self.assertIn("BRIGHT, readable mid-tones", s)
        for kid in ("cozy", "storybook texture", "rich but gentle"):
            self.assertNotIn(kid, s)
        self.assertNotIn("{", r + s)   # every placeholder filled

    def test_optional_skin_tone_replaces_white(self):
        r = house_style.character_rules("v2", "warm medium brown")
        self.assertIn("flat warm medium brown skin colour (no shading, no blush)", r)
        self.assertNotIn("flat WHITE", r)
        self.assertNotIn("{", r)


class ImageBackgroundTest(unittest.TestCase):
    """gpt-image-2 cannot draw transparency: the provider asks for a flat background. v1 keeps white (unchanged); v2
    poses ask for mid-grey (white heads would merge with white); v2 set plates ask for none."""
    def setUp(self):
        self.env = Env().login()
        self.env.client.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-bg"}})

    def tearDown(self):
        self.env.close()

    def prompt_for(self, cfg):
        import base64
        from pathlib import Path
        from unittest import mock
        sent = {}

        class R:
            status_code = 200
            def json(self):
                return {"data": [{"b64_json": base64.b64encode(b"png").decode()}]}

        def post(url, **kw):
            sent.update(kw.get("json") or kw.get("data") or {})
            return R()
        with mock.patch("oddstudio.providers.httpx.post", side_effect=post):
            providers._image_generate_one({"provider": "openai", **cfg}, "A figure.", Path(self.env.tmp) / "x.png")
        return sent["prompt"]

    def test_backgrounds(self):
        self.assertIn("flat white colour", self.prompt_for({}))
        grey = self.prompt_for({"background": "mid-grey (#808080)"})
        self.assertIn("flat mid-grey (#808080) colour", grey)
        self.assertNotIn("white colour", grey)
        self.assertNotIn("Background:", self.prompt_for({"background": None}))


class HouseStyleV2Test(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.prompts = []

        def image(prompt, out_file, reference):
            self.prompts.append((prompt, reference))
            return fake_pose_image(prompt, out_file, reference)
        providers.set_test_image(image)
        self.c.put("/api/settings/image", json={"provider": "openai"})

    def tearDown(self):
        providers.set_test_image(None)
        self.env.close()

    def new_char(self, **kw):
        body = {"key": "tess", "name": "Tess", "visual_description": "a flat olive cap shape", "scope": "recurring", **kw}
        r = self.c.post("/api/characters", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def sheet(self, cid, exps=("neutral", "deadpan")):
        self.assertEqual(self.c.post(f"/api/characters/{cid}/sheet", json={"expressions": list(exps)}).status_code, 200)
        ran = self.env.run_jobs(["character_sheet"])
        self.assertEqual(ran[-1][1], "succeeded", ran)

    def test_setting_defaults_to_v1_and_validates(self):
        self.assertEqual(self.c.get("/api/settings").json()["sections"]["creative"]["style_version"], "v1")
        self.assertEqual(self.c.put("/api/settings/creative", json={"style_version": "v3"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/creative", json={"style_version": "v2"}).status_code, 200)

    def test_writer_tone_is_adult_without_explicit_content(self):
        tone = self.c.get("/api/settings").json()["sections"]["creative"]["house_style"]
        self.assertIn("Adult-oriented, relatable humor", tone)
        self.assertIn("no explicit sexual content", tone)
        self.assertNotIn("Family-friendly", tone)

    def test_v1_generation_is_unchanged(self):
        c = self.new_char()
        self.sheet(c["id"], ("neutral",))
        prompt, _ = self.prompts[0]
        self.assertIn(house_style.CHARACTER_RULES, prompt)
        poses = [a for a in self.c.get("/api/characters").json() if a["key"] == "tess"][0]["assets"]
        self.assertEqual({a["style_version"] for a in poses if a["kind"] == "pose"}, {"v1"})

    def test_v2_generation_prompts_tags_and_storage(self):
        self.c.put("/api/settings/creative", json={"style_version": "v2"})
        c = self.new_char(skin_tone="deep brown")
        self.sheet(c["id"])
        neutral, deadpan = self.prompts[0], self.prompts[1]
        self.assertIn("HOUSE STYLE v2", neutral[0])
        self.assertIn("plain flat mid-grey (#808080) background", neutral[0])
        self.assertIn("flat deep brown skin colour", neutral[0])
        self.assertIn("shown with restraint", deadpan[0])
        self.assertIn("IMAGE 1 is THIS character", deadpan[0])          # the rest of the sheet anchors on the v2 neutral
        self.assertNotIn("exaggerated", neutral[0])
        ch = [a for a in self.c.get("/api/characters").json() if a["key"] == "tess"][0]
        self.assertEqual(ch["skin_tone"], "deep brown")
        poses = [a for a in ch["assets"] if a["kind"] == "pose"]
        self.assertEqual({a["style_version"] for a in poses}, {"v2"})
        from oddstudio.db import new_session
        from oddstudio.models import CharacterAsset
        with new_session() as s:
            keys = [a.storage_key for a in s.query(CharacterAsset).filter_by(kind="pose") if a.storage_key.startswith("characters/tess/")]
        self.assertEqual(len(keys), 2)
        self.assertTrue(all(k.startswith("characters/tess/poses/v2/") for k in keys), keys)

    def test_v2_never_anchors_on_v1_art(self):
        # Character 01's approved v1 art must not be attached as the v2 style reference
        self.c.put("/api/settings/creative", json={"style_version": "v2"})
        c = self.new_char()
        self.sheet(c["id"], ("neutral",))
        self.assertIsNone(self.prompts[0][1], "no style image until a v2 pose is approved: text only")
        self.assertNotIn("HOUSE STYLE v2 reference", self.prompts[0][0])
        # once a v2 neutral is approved it becomes the style reference for the next v2 character
        self.assertEqual(self.c.post(f"/api/characters/{c['id']}/sheet/decision", json={"decision": "approve"}).status_code, 200)
        c2 = self.new_char(key="omar", name="Omar")
        self.prompts.clear()
        self.sheet(c2["id"], ("neutral",))
        self.assertIn("HOUSE STYLE v2 reference", self.prompts[0][0])
        ref = self.prompts[0][1]
        refs = ref if isinstance(ref, list) else [ref]
        self.assertTrue(any("_style-v2" in str(r) for r in refs), refs)
        # an existing v1 pose does not satisfy (or skip) a v2 sheet
        self.c.put("/api/settings/creative", json={"style_version": "v1"})
        c3 = self.new_char(key="ivy", name="Ivy")
        self.sheet(c3["id"], ("neutral",))
        self.c.put("/api/settings/creative", json={"style_version": "v2"})
        self.prompts.clear()
        self.sheet(c3["id"], ("neutral",))
        self.assertEqual(len(self.prompts), 1, "the v2 sheet draws a new neutral even though a v1 neutral exists")
        self.assertIn("HOUSE STYLE v2", self.prompts[0][0])

    def test_v2_restyle_uses_v2_descriptions(self):
        from oddstudio.db import new_session
        from oddstudio.models import Character
        self.c.put("/api/settings/creative", json={"style_version": "v2"})
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})
        with new_session() as s:
            s.add(Character(key="leo", name="Leo", scope="recurring", engine_character="studio-leo", art_status="none"))
            s.commit()
            lid = s.query(Character).filter_by(key="leo").one().id
        r = self.c.post(f"/api/characters/{lid}/restyle", json={"from_current": False})
        self.assertEqual(r.status_code, 200, r.text)
        leo = [a for a in self.c.get("/api/characters").json() if a["key"] == "leo"][0]
        self.assertEqual(leo["visual_description"], house_style.RESTYLE_DESCRIPTIONS_V2["leo"])

    def test_sets_follow_the_style_version(self):
        self.c.put("/api/settings/credentials", json={"values": {"openai_api_key": "sk-test-x"}})
        from oddstudio import sets
        for version in ("v1", "v2"):
            self.c.put("/api/settings/creative", json={"style_version": version})
            self.prompts.clear()
            from oddstudio.queue import enqueue
            from oddstudio.db import new_session
            with new_session() as s:
                enqueue(s, "set_candidate", payload={"set_id": f"room-{version}", "label": "Room", "description": "a quiet flat at night"})
            ran = self.env.run_jobs(["set_candidate"])
            self.assertEqual(ran[0][1], "succeeded", ran)
            prompt, ref = self.prompts[0]
            # feat/episode-sets: one deliberate flat set style for every version, and no reference image (every set
            # used to be an edit of the same plate and came out alike)
            self.assertTrue(prompt.startswith(house_style.SET_STYLE_FLAT), prompt[:80])
            self.assertIsNone(ref, "text only: no style reference image")
            for biased in ("storybook", "cozy", "cosy", "warm painted", "painted gradients", "lamp light"):
                self.assertNotIn(biased, house_style.SET_STYLE_FLAT)
        from oddstudio.db import new_session
        with new_session() as s:
            self.assertEqual(sets.records(s)["room-v2"]["style_version"], "v2")


if __name__ == "__main__":
    unittest.main()
