"""The storyboard in the dashboard (2026-11-25): shot frames made without a mapping (the sides worked out from the
storyboard scenes' staging), every shot's takes kept (older plans migrated), a retake per shot (a new take, chosen, not
approved), choosing a take, the owner's approvals (never automatic), and the animatic (the chosen frames on the
recording, FFmpeg). The renderer is stubbed: these tests draw small PNGs."""
import json
import math
import os
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from helpers import Env
from test_episode_sets import add_studio_set

from oddstudio import shot_frames as SF

DESK, FAM = "desk-442", "family-444"
FF, FFP = shutil.which("ffmpeg"), shutil.which("ffprobe")


def scene(set_id, staging=None, characters=None):
    return {"set": set_id, "staging": staging or {}, "characters": characters or []}


class DeriveTest(unittest.TestCase):
    def test_sides_from_the_scenes_staging(self):
        scenes = [scene(DESK, {"mortimer": "seated", "solicitor": "standing"}),
                  scene(FAM, {"ralph": "seated", "sidney": "seated", "mortimer": "off"}),
                  scene(FAM, {"ralph": "seated", "winifred": "standing", "sidney": "seated"}),
                  scene("not-approved", {"ghost": "seated"})]
        d = SF.derive_sides(scenes, [DESK, FAM])
        self.assertEqual(d["sides"], {DESK: ["mortimer", "solicitor"], FAM: ["ralph", "sidney", "winifred"]})
        self.assertEqual(d["standing"], ["solicitor", "winifred"])
        self.assertEqual(d["listeners_side"], FAM, "the set with the most characters")

    def test_one_side_per_character_and_scenes_without_staging(self):
        scenes = [scene(DESK, {"a": "seated"}), scene(FAM, {"a": "seated", "b": "seated"}), scene(FAM, {"a": "standing"}),
                  scene(DESK, None, [{"key": "c"}, "d"])]
        d = SF.derive_sides(scenes, [DESK, FAM])
        self.assertEqual(d["sides"], {DESK: ["c", "d"], FAM: ["a", "b"]}, "a is staged on the family set most")
        self.assertEqual(d["standing"], [], "a is seated more often than standing")
        self.assertEqual(SF.derive_sides([], [DESK]), {"sides": {}, "standing": [], "listeners_side": None})

    def test_seats_versions_and_timeline(self):
        self.assertEqual(SF.seats({DESK: ["m", "s"], FAM: ["r", "w", "x"]}, {"s", "w"}), {"m": 0, "r": 0, "x": 1})
        old = SF.norm_shot({"index": 1, "asset_id": 7}, made=5.0)
        self.assertEqual(old["versions"], [{"asset_id": 7, "at": 5.0, "source": "first", "note": ""}])
        self.assertEqual((old["chosen"], old["approved"]), (7, False))
        kept = SF.norm_shot({"asset_id": 7, "versions": [{"asset_id": 7}, {"asset_id": 9}], "chosen": 9, "approved": True})
        self.assertEqual((kept["chosen"], kept["asset_id"], kept["approved"]), (9, 9, True))
        self.assertEqual(SF.norm_shot({"versions": [{"asset_id": 7}], "chosen": 3, "approved": True})["chosen"], 7)
        self.assertFalse(SF.norm_shot({"approved": True})["approved"], "no frame: nothing to approve")
        shots = [{"index": 1, "t0": 0.5, "t1": 2.0}, {"index": 2, "t0": 2.0, "t1": 4.0}, {"index": 3, "t0": 5.0, "t1": 6.0}]
        self.assertEqual(SF.animatic_timeline(shots, 8.0), [(1, 0.0, 2.0), (2, 2.0, 3.0), (3, 5.0, 3.0)])
        self.assertEqual(SF.animatic_timeline(shots, None)[-1], (3, 5.0, 1.0), "unknown length: the last shot's own end")
        self.assertEqual(SF.retake_note("medium", ["a"], DESK, {"a": "happy"}, {"shot": "close", "people": ["a"], "side": DESK}),
                         "medium shot; faces: a happy")


def png(path: Path, color=(200, 80, 40)) -> Path:
    from PIL import Image
    Image.new("RGB", (64, 36), color).save(path)
    return path


def tone(path: Path, seconds: float) -> Path:
    rate = 8000
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 330 * i / rate))) for i in range(int(seconds * rate))))
    return path


class FlowBase(unittest.TestCase):
    ffmpeg = False

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("FFMPEG", "FFPROBE")}
        if self.ffmpeg:
            os.environ["FFMPEG"], os.environ["FFPROBE"] = FF, FFP
        else:
            os.environ.pop("FFMPEG", None); os.environ.pop("FFPROBE", None)
        self.env = Env().login()
        self.c = self.env.client
        self.renders = []
        self.real_render = SF._render_one

        def fake_render(ctx, ep, shot, set_spec, chars, seat_of, standing, folder):
            self.renders.append({"index": shot["index"], "shot": shot["shot"], "people": list(shot["people"]),
                                 "side": shot["side"], "emotions": dict(shot["emotions"]),
                                 "seats": {k: seat_of.get(k) for k in shot["people"]}, "standing": sorted(standing)})
            return png(folder / f"shot-{shot['index']:03d}-{len(self.renders)}.png", (len(self.renders) * 20 % 255, 90, 120))
        SF._render_one = fake_render
        add_studio_set(DESK)
        add_studio_set(FAM)
        self.eid = self.episode()

    def tearDown(self):
        SF._render_one = self.real_render
        self.env.close()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def episode(self) -> int:
        from oddstudio.db import new_session
        from oddstudio.models import Episode, StoryboardScene
        from oddstudio.tasks import store_asset
        rec = tone(Path(tempfile.mkdtemp()) / "recording.wav", 6.0)
        lines = [{"id": "L1", "start": 0.3, "end": 2.0, "text": "To my nephew", "speaker": "sp1", "words": []},
                 {"id": "L2", "start": 2.0, "end": 4.0, "text": "Nothing", "speaker": "sp2", "words": []},
                 {"id": "L3", "start": 4.5, "end": 5.5, "text": "What?", "speaker": "sp2", "words": []}]
        with new_session() as db:
            ep = Episode(title="The Unkind Will", stage="storyboard_review", source="audio", audio_rights_confirmed=True,
                         audio_transcript={"lines": lines, "person_map": {}}, set_id=DESK, scene_set_ids=[FAM])
            db.add(ep)
            db.flush()
            a = store_asset(db, ep_id=ep.id, src=rec, key=f"episodes/{ep.id}/audio/recording.wav", kind="audio",
                            label="Recording", content_type="audio/wav")
            ep.audio_asset_id = a.id
            db.add(StoryboardScene(episode_id=ep.id, position=1, scene_key="s1", heading="The will", set_id=DESK,
                                   staging={"mortimer": "seated", "solicitor": "standing"},
                                   lines=[{"line_id": "L1", "shot": "close"}]))
            db.add(StoryboardScene(episode_id=ep.id, position=2, scene_key="s2", heading="The family", set_id=FAM,
                                   staging={"ralph": "seated", "sidney": "seated", "mortimer": "off"},
                                   lines=[{"line_id": "L2", "shot": "medium"}, {"line_id": "L3", "shot": "close"}]))
            db.commit()
            return ep.id

    def make(self):
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames")
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["shot_frames"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        return self.frames()

    def frames(self):
        r = self.c.get(f"/api/episodes/{self.eid}/shot-frames")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def events(self):
        from oddstudio.db import new_session
        from oddstudio.models import Event
        with new_session() as db:
            return [e.message for e in db.query(Event).filter_by(episode_id=self.eid, kind="storyboard").order_by(Event.id)]


class DashboardFlowTest(FlowBase):
    # ---------------------------------------------------------------- automatic sides
    def test_plan_defaults_and_make_without_a_body(self):
        d = self.c.get(f"/api/episodes/{self.eid}/shot-frames/plan-defaults").json()
        self.assertEqual(d, {"sides": {DESK: ["mortimer", "solicitor"], FAM: ["ralph", "sidney"]}, "standing": ["solicitor"],
                             "listeners_side": DESK})
        v = self.make()
        self.assertEqual(v["sides"], d["sides"])
        self.assertEqual([(s["index"], s["side"], s["people"], s["shot"]) for s in v["shots"]],
                         [(1, DESK, ["mortimer", "solicitor"], "medium"), (2, FAM, ["ralph", "sidney"], "medium"),
                          (3, FAM, ["ralph", "sidney"], "medium")])
        self.assertEqual(self.renders[0]["seats"], {"mortimer": 0, "solicitor": None}, "solicitor stands")
        for s in v["shots"]:
            self.assertEqual(len(s["versions"]), 1)
            self.assertEqual(s["versions"][0]["source"], "first")
            self.assertEqual((s["chosen"], s["asset_id"], s["approved"]), (s["versions"][0]["asset_id"],) * 2 + (False,))
            self.assertTrue(s["url"] and s["versions"][0]["url"])
        self.assertEqual(v["approved"], 0, "nothing is approved by making the frames")
        self.assertIsNone(v["animatic_url"])
        self.assertTrue(any(j["kind"] == "shot_frames" and j["status"] == "succeeded" for j in v["jobs"]))
        self.assertTrue(any("asked by" in m for m in self.events()))

    def test_an_explicit_mapping_still_works_and_nobody_staged_is_refused(self):
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames", json={"sides": {FAM: ["ralph"]}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["payload"]["sides"], {FAM: ["ralph"]})
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames").status_code, 409, "already being made")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames", json={"sides": {"nope": ["x"]}}).status_code, 422)
        from oddstudio.db import new_session
        from oddstudio.models import StoryboardScene
        with new_session() as db:
            db.query(StoryboardScene).filter_by(episode_id=self.eid).delete()
            db.commit()
        self.env.run_jobs(["shot_frames"])
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames")
        self.assertEqual(r.status_code, 422, r.text)

    # ---------------------------------------------------------------- versions: migration of older plans
    def test_older_plans_are_read_as_one_take_per_shot(self):
        from oddstudio.db import new_session
        self.make()
        with new_session() as db:
            v = SF.stored(db, self.eid)
            v["shots"] = [{k: x for k, x in s.items() if k not in ("versions", "chosen", "approved")} for s in v["shots"]]
            SF.save(db, self.eid, v)
            db.commit()
        s = self.frames()["shots"][0]
        self.assertEqual([x["source"] for x in s["versions"]], ["first"])
        self.assertEqual((s["chosen"], s["approved"]), (s["asset_id"], False))
        self.assertTrue(s["url"])

    # ---------------------------------------------------------------- retake, choose, approvals
    def test_retake_appends_a_take_chooses_it_and_resets_the_approval(self):
        v = self.make()
        first = v["shots"][1]["chosen"]
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/approve").status_code, 200)
        self.assertTrue(self.frames()["shots"][1]["approved"])
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/retake",
                        json={"shot": "close", "people": ["sidney"], "emotions": {"sidney": "shocked"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/retake").status_code, 409, "one retake at a time per shot")
        self.assertEqual(self.env.run_jobs(["shot_frame_retake"])[0][1], "succeeded")
        self.assertEqual(self.renders[-1], {"index": 2, "shot": "close", "people": ["sidney"], "side": FAM,
                                            "emotions": {"sidney": "shocked"}, "seats": {"sidney": 1}, "standing": ["solicitor"]})
        s = self.frames()["shots"][1]
        self.assertEqual([x["source"] for x in s["versions"]], ["first", "retake"])
        self.assertEqual(s["versions"][0]["asset_id"], first, "the first take is kept")
        self.assertEqual((s["chosen"], s["asset_id"]), (s["versions"][1]["asset_id"],) * 2)
        self.assertFalse(s["approved"], "a new take needs the owner's approval again")
        self.assertEqual((s["shot"], s["people"]), ("close", ["sidney"]))
        self.assertIn("close shot", s["versions"][1]["note"])
        # a second retake with no changes: a third take; the others stay
        self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/retake")
        self.env.run_jobs(["shot_frame_retake"])
        s = self.frames()["shots"][1]
        self.assertEqual(len(s["versions"]), 3)
        self.assertEqual(len({x["asset_id"] for x in s["versions"]}), 3)
        # choose the first take back: its own staging comes back, not approved
        self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/approve")
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/choose", json={"asset_id": first})
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()["shots"][1]
        self.assertEqual((s["chosen"], s["approved"], s["shot"], s["people"]), (first, False, "medium", ["ralph", "sidney"]))
        self.assertTrue(any("take 1 chosen" in m for m in self.events()))

    def test_retake_rules(self):
        self.make()
        bad = [({"people": ["mortimer"]}, 422),                     # not on the family side
               ({"side": "elsewhere"}, 422), ({"shot": "extreme"}, 422),
               ({"shot": "close"}, 422),                            # two people in a close shot
               ({"emotions": {"mortimer": "happy"}}, 422)]          # not in the shot
        for body, code in bad:
            self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/retake", json=body).status_code, code, body)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/9/retake").status_code, 404)
        # another side without people: everyone on that side; nobody: the room
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/2/retake", json={"side": DESK})
        self.assertEqual(r.json()["payload"]["people"], ["mortimer", "solicitor"])
        self.env.run_jobs(["shot_frame_retake"])
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/3/retake", json={"people": []})
        self.assertEqual(r.status_code, 200, r.text)
        n = len(self.renders)
        self.assertEqual(self.env.run_jobs(["shot_frame_retake"])[0][1], "succeeded")
        self.assertEqual(len(self.renders), n, "the room only: no character to render")
        self.assertEqual(self.frames()["shots"][2]["people"], [])

    def test_a_retake_asked_before_the_frames_were_made_again_fails(self):
        self.make()
        self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/retake", json={"shot": "wide"})
        from oddstudio.db import new_session
        with new_session() as db:
            v = SF.stored(db, self.eid)
            v["job_id"] = 999
            SF.save(db, self.eid, v)
            db.commit()
        ran = self.env.run_jobs(["shot_frame_retake"])
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("made again", ran[0][2])

    def test_choose_and_approval_rules(self):
        v = self.make()
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/choose", json={"asset_id": v["shots"][1]["chosen"]}).status_code,
                         422, "a take of another shot")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/4/approve").status_code, 404)
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/approve-all")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["approved"], 3)
        self.assertTrue(all(s["approved"] for s in r.json()["shots"]))
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/unapprove")
        self.assertEqual([s["approved"] for s in r.json()["shots"]], [False, True, True])
        msgs = self.events()
        self.assertTrue(any("all 3 approved by" in m for m in msgs) and any("Shot 1: approval withdrawn" in m for m in msgs))
        # no plan yet: nothing to approve
        from oddstudio.db import new_session
        from oddstudio.models import Setting
        with new_session() as db:
            db.delete(db.get(Setting, SF.key(self.eid)))
            db.commit()
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/approve-all").status_code, 404)
        self.assertEqual(self.frames()["shots"], [])

    def test_nothing_approves_by_itself(self):
        self.make()
        self.c.post(f"/api/episodes/{self.eid}/shot-frames/1/retake", json={"shot": "wide"})
        self.env.run_jobs()
        self.assertEqual(self.frames()["approved"], 0)

    def test_owner_only(self):
        from fastapi.testclient import TestClient
        from oddstudio.main import app
        anon = TestClient(app)
        base = f"/api/episodes/{self.eid}/shot-frames"
        for path in ("", "/1/retake", "/1/choose", "/1/approve", "/1/unapprove", "/approve-all", "/animatic"):
            self.assertEqual(anon.post(base + path, json={}).status_code, 401, path)
        for path in ("", "/plan-defaults"):
            self.assertEqual(anon.get(base + path).status_code, 401, path)

    def test_animatic_needs_ffmpeg(self):
        self.make()
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/animatic")
        self.assertEqual(r.status_code, 409)
        self.assertIn("FFmpeg", r.text)


@unittest.skipUnless(FF and FFP, "FFmpeg is not installed")
class AnimaticTest(FlowBase):
    ffmpeg = True

    def test_animatic_is_an_mp4_on_the_recording(self):
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/animatic").status_code, 404, "no frames yet")
        self.make()
        r = self.c.post(f"/api/episodes/{self.eid}/shot-frames/animatic")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/shot-frames/animatic").status_code, 409)
        ran = self.env.run_jobs(["shot_animatic"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        v = self.frames()
        self.assertTrue(v["animatic_url"])
        self.assertEqual(v["approved"], 0)
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as db:
            a = db.get(Asset, v["animatic_asset_id"])
            self.assertEqual((a.kind, a.label, a.content_type), ("animatic", SF.ANIMATIC_LABEL, "video/mp4"))
            path = storage().local_path(a.storage_key)
        import subprocess
        info = json.loads(subprocess.run([FFP, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout)
        kinds = sorted(s["codec_type"] for s in info["streams"])
        self.assertEqual(kinds, ["audio", "video"])
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (1080, 1920), "the episode frame size")
        self.assertAlmostEqual(float(info["format"]["duration"]), 6.0, delta=0.3)
        self.assertTrue(any("Animatic:" in m for m in self.events()))


if __name__ == "__main__":
    unittest.main()
