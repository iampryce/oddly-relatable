"""Audio-first Stage 3 core (owner decision 2026-11-20): `audio_slice` replaces `scene_voice` for audio episodes (the
recording is cut per line for lip sync), the absolute timeline, the original audio passed through unchanged, and the QA
(video length equals audio length; first mouth cue within +/-80 ms of the first word). FFmpeg cases find FFmpeg
themselves (`which`), so they run wherever it is installed (CI installs it). The full render runs in the end-to-end
setting (Node, rigs, Rhubarb) and in the server tests after merge."""
import io
import math
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from helpers import Env

from oddstudio import analysis
from oddstudio import audio_production as AP

FF, FFP = shutil.which("ffmpeg"), shutil.which("ffprobe")
WORDS = [{"start": 0.30, "end": 0.60, "word": "Who"}, {"start": 0.62, "end": 1.20, "word": "took it?"},
         {"start": 2.10, "end": 2.60, "word": "Not me."}, {"start": 4.70, "end": 5.30, "word": "Honest."}]
TRANSCRIPT = {"provider": "openai", "model": "whisper-1", "language": "en", "duration": 6.0,
              "text": "Who took it? Not me. Honest.", "segments": [], "words": WORDS}


def tone_wav(seconds=6.0, rate=48000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(int(8000 * math.sin(2 * math.pi * 220 * i / rate)).to_bytes(2, "little", signed=True)
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


class QaTest(unittest.TestCase):
    def test_length_within_one_frame_and_cue_within_80_ms(self):
        r = AP.qa(6.0167, 6.0, 30, first_cue=0.35, first_word=0.30)
        self.assertTrue(r["pass"], r)
        r = AP.qa(6.1, 6.0, 30, first_cue=0.35, first_word=0.30)
        self.assertFalse(r["pass"])
        self.assertIn("video 6.1 s vs audio 6.0 s", AP.qa_message(r))
        r = AP.qa(6.0, 6.0, 30, first_cue=0.39, first_word=0.30)
        self.assertFalse(r["pass"])
        self.assertIn("offset 90 ms", AP.qa_message(r))
        self.assertTrue(AP.qa(6.0, 6.0, 30, first_cue=0.22, first_word=0.30)["pass"], "early by 80 ms is inside")
        self.assertFalse(AP.qa(6.0, 6.0, 30, first_cue=None, first_word=0.30)["pass"])

    def test_first_mouth_cue_is_the_first_non_rest_shape_on_the_timeline(self):
        lines = [{"start": 2.1, "cues": [{"start": 0.0, "value": "X"}, {"start": 0.06, "value": "B"}]},
                 {"start": 0.3, "cues": [{"start": 0.0, "value": "X"}, {"start": 0.04, "value": "C"}]}]
        self.assertEqual(AP.first_mouth_cue(lines), 0.34)
        self.assertIsNone(AP.first_mouth_cue([{"start": 0, "cues": [{"start": 0, "value": "X"}]}]))

    def test_long_audio_scenes_get_acts_in_order(self):
        # fix for Stage 2: a long episode's script needs acts 1-3, which the scene builder did not set
        from oddstudio.audio_scenes import build_script
        lines = [{"id": f"l{i}", "start": i * 3.0, "end": i * 3.0 + 1, "speaker": "dan", "text": "x", "words": []} for i in range(1, 8)]
        s = build_script("Ep", lines, ["dan"], [], None, fmt="long")
        acts = [sc["act"] for sc in s["scenes"]]
        self.assertEqual(acts, sorted(acts))
        self.assertEqual((acts[0], acts[-1]), (1, 3))
        self.assertEqual([sc.get("act") for sc in build_script("Ep", lines[:2], ["dan"], [], None, fmt="long")["scenes"]], [1, 2])

    def test_recorded_lines_keep_their_place(self):
        self.assertEqual(AP.line_window({"start": 2.1004, "end": 2.6}), (2.1, 2.6))


class Flow(unittest.TestCase):
    with_ffmpeg = False

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("FFMPEG", "FFPROBE")}
        if self.with_ffmpeg:
            os.environ["FFMPEG"], os.environ["FFPROBE"] = FF, FFP
        self.env = Env().login()
        self.c = self.env.client
        analysis.set_test_analysis(transcriber=lambda cfg, audio: dict(TRANSCRIPT))

    def tearDown(self):
        analysis.set_test_analysis()
        self.env.close()
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def storyboard(self, fmt="short", approve=True):
        """An audio episode through Stage 2 to an approved storyboard (approvals here are test steps only)."""
        eid = self.c.post("/api/audio-episodes", json={"title": "Charger", "format": fmt, "rights_confirmed": True,
                                                       "rights_source": "own_recording"}).json()["id"]
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio", content=tone_wav(), headers={"Content-Type": "audio/wav"}).status_code, 200)
        self.env.run_jobs(["audio_transcribe"])
        lines = self.c.get(f"/api/episodes/{eid}/audio").json()["lines"]
        for ln in lines:
            ln["speaker"] = "character-01"
        self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": lines})
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/scenes", json={"mode": "simple"}).status_code, 200)
        self.env.run_jobs(["audio_scenes"])
        if approve:
            self.assertEqual(self.c.post(f"/api/episodes/{eid}/script/approve", json={}).status_code, 200)
            self.c.post(f"/api/episodes/{eid}/storyboard/generate")
            self.env.run_jobs(["generate_storyboard"])
            r = self.c.post(f"/api/episodes/{eid}/storyboard/approve", json={})
            self.assertEqual(r.status_code, 200, r.text)
        return eid

    def rig_motion(self, on=True):
        self.assertEqual(self.c.put("/api/settings/motion", json={"provider": "procedural-rig" if on else "none"}).status_code, 200)


class ProductionStartTest(Flow):
    def test_audio_episodes_slice_their_recording_instead_of_voicing(self):
        eid = self.storyboard()
        self.rig_motion(False)
        self.c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        r = self.c.post(f"/api/episodes/{eid}/production/start")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("rig animator", r.text)
        self.rig_motion(True)
        r = self.c.post(f"/api/episodes/{eid}/production/start")
        self.assertEqual(r.status_code, 200, r.text)
        kinds = sorted({j["kind"] for j in r.json()})
        self.assertEqual(kinds, ["audio_slice", "scene_prepare"], "no voice generation for a recording")

    def test_all_scene_jobs_done_starts_one_render_even_for_long_audio(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode, Job
        from oddstudio.tasks import after_job
        eid = self.storyboard(fmt="long")
        self.rig_motion(True)
        self.c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/production/start").status_code, 200)
        with new_session() as s:
            jobs = s.query(Job).filter(Job.episode_id == eid, Job.kind.in_(["scene_prepare", "audio_slice"])).all()
            for j in jobs:
                j.status = "succeeded"
            s.commit()
            for j in jobs:
                after_job(s, j)
            kinds = [j.kind for j in s.query(Job).filter(Job.episode_id == eid, Job.status == "queued",
                                                           Job.kind.in_(["render_episode", "plan_segments"]))]
            self.assertEqual(kinds, ["render_episode"], "one render on the recording's timeline, no segments")
            self.assertEqual(s.get(Episode, eid).stage, "producing")


@unittest.skipUnless(FF and FFP, "FFmpeg and FFprobe are not installed")
class MediaTest(Flow):
    with_ffmpeg = True

    def test_slices_follow_the_recorded_lines(self):
        eid = self.storyboard()
        self.rig_motion(True)
        self.c.put(f"/api/episodes/{eid}/set", json={"set_id": "living-room-empty-03"})   # a deliberate set choice (PR 1)
        self.c.post(f"/api/episodes/{eid}/production/start")
        ran = self.env.run_jobs(["audio_slice"])
        self.assertTrue(ran and all(r[1] == "succeeded" for r in ran), ran)
        from oddstudio.db import new_session
        from oddstudio.models import Episode, Job
        from oddstudio.tasks_long import clip_map
        with new_session() as s:
            ep = s.get(Episode, eid)
            clips = [c for sc in clip_map(s, ep).values() for c in sc.values()]
            self.assertEqual([(c["line_id"], c["start"], c["end"]) for c in sorted(clips, key=lambda c: c["start"])],
                             [("l1", 0.3, 1.2), ("l2", 2.1, 2.6), ("l3", 4.7, 5.3)])
            self.assertTrue(all(c["recorded"] for c in clips))
            self.assertEqual(s.query(Job).filter_by(episode_id=eid, kind="scene_voice").count(), 0)
        from oddstudio.storage import storage
        tmp = Path(tempfile.mkdtemp())
        f = storage().get_to_file(clips[0]["key"], tmp / "slice.wav")
        self.assertAlmostEqual(AP.probe(f)["duration"], clips[0]["end"] - clips[0]["start"], delta=0.02)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_the_original_audio_passes_through_and_the_lengths_match(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            video = tmp / "silent.mp4"
            subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x568:r=30:d=6", "-c:v", "mpeg4", str(video)], check=True)
            aac = tmp / "voice.m4a"
            subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=6:sample_rate=48000", "-c:a", "aac", "-b:a", "160k", str(aac)], check=True)
            out = AP.mux_original(video, aac, 6.0, tmp / "out.mp4")
            md5 = lambda f: subprocess.run([FF, "-v", "error", "-i", str(f), "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                                           capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(md5(out), md5(aac), "an AAC recording is copied bit for bit (no re-encode, gain or mix)")
            check = AP.qa(AP.probe(out, "v")["duration"], 6.0, 30, 0.33, 0.30)
            self.assertTrue(check["pass"], check)
            wav = tmp / "voice.wav"
            wav.write_bytes(tone_wav(6.0))
            out2 = AP.mux_original(video, wav, 6.0, tmp / "out2.mp4")
            self.assertEqual(AP.probe(out2, "a")["codec"], "aac", "a WAV recording is encoded once")
            self.assertAlmostEqual(AP.probe(out2)["duration"], 6.0, delta=0.05)
            # a cut-off last line removed (end_at): video AND audio end there (a copied AAC stream ends on its own
            # packet boundary, a few ms later; nothing of the recording runs on past it)
            for src in (aac, wav):
                cut = AP.mux_original(video, src, 4.0, tmp / f"cut-{src.name}.mp4")
                self.assertAlmostEqual(AP.probe(cut, "v")["duration"], 4.0, delta=1 / 30)
                self.assertAlmostEqual(AP.probe(cut, "a")["duration"], 4.0, delta=0.025)
            self.assertAlmostEqual(AP.probe(AP.as_wav(aac, 4.0, tmp / "end.wav"))["duration"], 4.0, delta=0.005)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
