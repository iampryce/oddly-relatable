"""The scene-build estimate (clean dashboard, 2026-11-25): before the first scene build of an audio episode the
dashboard shows what each way costs, so its Generate button only ever starts the free path by itself and a paid
AI-writer build is the owner's own click with the cost shown. The endpoint is read-only: no stage change, no job."""
import unittest

from helpers import Env
from test_seating_and_plan import LINES


class ScenesEstimateTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Character, Episode
        with new_session() as s:
            for k in ("mortimer", "winnie"):
                s.add(Character(key=k, name=k.title(), scope="episode", art_status="approved"))
            ep = Episode(title="The Will", stage="audio_labelling", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": LINES})
            s.add(ep)
            s.add(Episode(title="Script first", stage="script_pending"))
            s.commit()
            self.eid = ep.id

    def tearDown(self):
        self.env.close()

    def jobs(self):
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as s:
            return s.query(Job).count()

    def test_estimate_is_free_without_a_text_provider_and_changes_nothing(self):
        before = self.jobs()
        r = self.c.get(f"/api/episodes/{self.eid}/audio/scenes/estimate")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["simple"]["usd"], 0.0)
        self.assertEqual(body["writer"]["provider"], "none", "no text provider here: the writer path is the free split")
        self.assertEqual(body["writer"]["usd"], 0.0)
        self.assertTrue(body["allowed"])
        self.assertEqual(self.c.get(f"/api/episodes/{self.eid}").json()["stage"], "audio_labelling")
        self.assertEqual(self.jobs(), before, "an estimate never queues anything")

    def test_estimate_with_a_paid_text_provider_shows_its_cost(self):
        from oddstudio.db import new_session
        from oddstudio.settings_store import get_section, put_section
        from oddstudio.shot_compare import TEXT_PRICES
        provider = next(iter(TEXT_PRICES))
        with new_session() as s:
            put_section(s, "text", {**get_section(s, "text"), "provider": provider})
            s.commit()
        body = self.c.get(f"/api/episodes/{self.eid}/audio/scenes/estimate").json()
        self.assertEqual(body["writer"]["provider"], provider)
        self.assertGreater(body["writer"]["usd"], 0)

    def test_not_allowed_outside_the_build_stages_and_only_for_audio_episodes(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            s.get(Episode, self.eid).stage = "storyboard_review"
            other = s.query(Episode).filter_by(title="Script first").one().id
            s.commit()
        self.assertFalse(self.c.get(f"/api/episodes/{self.eid}/audio/scenes/estimate").json()["allowed"])
        self.assertNotEqual(self.c.get(f"/api/episodes/{other}/audio/scenes/estimate").status_code, 200)


if __name__ == "__main__":
    unittest.main()
