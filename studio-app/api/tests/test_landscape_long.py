"""Landscape long episodes (16:9, YouTube) and sets drawn for the whole cast (owner rules 2026-11-25): the episode
layout "landscape" renders 1920x1080; long episodes hold up to 10 characters; a set prompt asks for seats for the
people who sit (side by side, one distance from the camera) and open floor for the people who stand, in the episode's
shape (landscape 3:2 for a landscape episode) and style (flat or painted); Codex draws sets when Settings selects it."""
import unittest
from types import SimpleNamespace

from helpers import Env

from oddstudio import acting, sets
from oddstudio.script_schema import LIMITS


class FrameTest(unittest.TestCase):
    def test_frame_size_follows_the_layout(self):
        self.assertEqual(acting.frame_size(SimpleNamespace(layout="landscape")), (1920, 1080))
        self.assertEqual(acting.frame_size(SimpleNamespace(layout=None)), (1080, 1920))
        self.assertEqual(acting.frame_size(SimpleNamespace(layout="band")), (1080, 1920))

    def test_long_episodes_hold_ten_characters(self):
        self.assertEqual(LIMITS["long"]["characters"], 10)
        self.assertEqual(LIMITS["short"]["characters"], 4)


class SetPromptTest(unittest.TestCase):
    def test_rules_carry_seated_and_standing_people(self):
        t = sets.rules_text(6, 3)
        self.assertIn("seating for at least 6 people", t)
        self.assertIn("same distance from the camera", t)
        self.assertIn("3 people stand", t)
        self.assertNotIn("stand", sets.rules_text(4, 0))

    def test_shape_and_style(self):
        self.assertIn("vertical 2:3", sets.set_style())
        self.assertIn("horizontal 3:2", sets.set_style("landscape"))
        self.assertIn("hand-painted", sets.set_style("landscape", "painted"))
        self.assertIn("horizontal 3:2", sets.set_style("landscape", "painted"))
        self.assertEqual(sets.SET_SIZES["landscape"], "1536x1024")


class EpisodeSetsTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def episode(self, transcript, layout=None):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            ep = Episode(title="The Unkind Will", format="long", source="audio", audio_transcript=transcript, layout=layout)
            s.add(ep)
            s.commit()
            return ep.id

    def test_whole_cast_split_into_seated_and_standing(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        from oddstudio import set_proposals as SP
        tr = {"lines": [{"id": "l1", "speaker": "uncle-mortimer", "text": "x", "start": 0, "end": 1}],
              "silent_cast": [{"name": n, "character_key": n} for n in
                              ("ralph", "sidney", "winifred", "ronald", "young-wife", "solicitor", "mr-crabtree", "mrs-crabtree")],
              "video_notes": {"ranges": [{"start": 0, "end": 5, "roles": [{"person": i, "pose": "seated"} for i in range(6)]},
                                         {"start": 5, "end": 9, "roles": [{"person": 7, "pose": "standing"}, {"person": 8, "pose": "standing"}]}]}}
        eid = self.episode(tr, layout="landscape")
        with new_session() as s:
            ep = s.get(Episode, eid)
            self.assertEqual(SP.cast_staging(ep), {"total": 9, "seated": 6, "standing": 3})
            self.assertEqual(SP.set_shape(ep), "landscape")
            self.assertEqual(SP.cast_size(ep), 9)

    def test_no_notes_everyone_sits(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        from oddstudio import set_proposals as SP
        eid = self.episode({"lines": [{"id": "l1", "speaker": "a", "text": "x", "start": 0, "end": 1},
                                      {"id": "l2", "speaker": "b", "text": "y", "start": 1, "end": 2}]})
        with new_session() as s:
            self.assertEqual(SP.cast_staging(s.get(Episode, eid)), {"total": 2, "seated": 2, "standing": 0})
            self.assertEqual(SP.set_shape(s.get(Episode, eid)), "portrait")

    def test_layout_landscape_is_accepted(self):
        eid = self.episode({"lines": []})
        r = self.c.put(f"/api/episodes/{eid}/layout", json={"value": "landscape"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/layout", json={"value": "square"}).status_code, 422)

    def test_library_set_request_carries_shape_style_and_staging(self):
        r = self.c.post("/api/sets/generate", json={"label": "Study wide", "description": "A wood-panelled study with a desk.",
                                                    "orientation": "landscape", "style": "painted", "seats": 6, "standing": 3})
        self.assertEqual(r.status_code, 200, r.text)
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as s:
            p = s.query(Job).filter_by(kind="set_candidate").one().payload
        self.assertEqual((p["orientation"], p["style"], p["seats"], p["standing"]), ("landscape", "painted", 6, 3))

    def test_sets_use_codex_when_selected(self):
        from oddstudio.db import new_session
        self.assertEqual(self.c.put("/api/settings/image", json={"provider": "codex-cli", "fallback": "none"}).status_code, 200)
        with new_session() as s:
            self.assertEqual(sets.set_provider(s), "codex-cli")
            self.assertEqual(sets.request_view(s, "p", None, "1536x1024")["endpoint"], "Codex (ChatGPT plan)")
        self.c.put("/api/settings/image", json={"provider": "openai", "fallback": "none"})
        with new_session() as s:
            self.assertEqual(sets.set_provider(s), "openai")


if __name__ == "__main__":
    unittest.main()
