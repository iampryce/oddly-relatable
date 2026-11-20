"""Audio-first Stage 1b: media upload (owner decision 2026-11-20). Any audio or video file; a video is only a carrier
for its audio (extracted, the original deleted, the picture never reused); optional casting and setting hints from a
few frames (people count, setting, mood only; the frames deleted after); a Short's 60 s window on a longer recording;
the 250 MB video cap and the free-space check. The FFmpeg tests find FFmpeg themselves (`which`), so they run wherever
it is installed (CI installs it); the rest needs nothing."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import Env

from oddstudio import analysis, providers

FF, FFP = shutil.which("ffmpeg"), shutil.which("ffprobe")
TRANSCRIPT = {"provider": "openai", "model": "whisper-1", "language": "en", "duration": 3.0, "text": "Hello there.",
              "segments": [{"start": 0.2, "end": 1.0, "text": "Hello there."}],
              "words": [{"start": 0.2, "end": 0.5, "word": "Hello"}, {"start": 0.55, "end": 1.0, "word": "there."}]}


def make_media(folder: Path, name: str, seconds: float, video=True, audio=True, rate=16000) -> Path:
    out = folder / name
    cmd = [FF, "-v", "error", "-y"]
    if video:
        cmd += ["-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate={rate}"]
    if video:
        cmd += ["-c:v", "mpeg4", "-q:v", "8"]
    if audio:
        cmd += ["-c:a", "aac" if video else "pcm_s16le"]
    subprocess.run(cmd + [str(out)], check=True, capture_output=True, timeout=120)
    return out


def seconds_of(path: Path) -> float:
    r = subprocess.run([FFP, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True, timeout=60)
    return float(r.stdout.strip())


class Base(unittest.TestCase):
    with_ffmpeg = False

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("FFMPEG", "FFPROBE")}
        if self.with_ffmpeg:
            os.environ["FFMPEG"], os.environ["FFPROBE"] = FF, FFP
        else:
            os.environ.pop("FFMPEG", None); os.environ.pop("FFPROBE", None)
        self.env = Env().login()
        self.c = self.env.client
        self.media = Path(tempfile.mkdtemp(prefix="oddstudio-media-"))
        analysis.set_test_analysis(transcriber=lambda cfg, audio: dict(TRANSCRIPT))

    def tearDown(self):
        analysis.set_test_analysis()
        providers.set_test_text_responder(None)
        self.env.close()
        shutil.rmtree(self.media, ignore_errors=True)
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def create(self, fmt="short"):
        return self.c.post("/api/audio-episodes", json={"title": "Media", "format": fmt, "rights_confirmed": True,
                                                        "rights_source": "own_recording"}).json()["id"]

    def upload(self, eid, path_or_bytes, ctype, hints=False):
        data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
        return self.c.put(f"/api/episodes/{eid}/audio" + ("?hints=true" if hints else ""), content=data, headers={"Content-Type": ctype})

    def state(self, eid):
        return self.c.get(f"/api/episodes/{eid}/audio").json()

    def uploads(self):
        d = self.env.tmp / "work" / "uploads"
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def assets(self, eid):
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        with new_session() as s:
            return [(a.kind, a.content_type, a.storage_key) for a in s.query(Asset).filter_by(episode_id=eid).order_by(Asset.id)]


class LimitsTest(Base):
    """No FFmpeg needed: the caps, the free-space check, the rights wording and the hint filter."""

    def test_video_cap_is_250_mb_and_audio_stays_60_mb(self):
        from oddstudio import audio_first
        self.assertEqual((audio_first.MAX_VIDEO_BYTES, audio_first.MAX_BYTES), (250 * 1024 * 1024, 60 * 1024 * 1024))
        eid = self.create()
        old = audio_first.MAX_VIDEO_BYTES
        audio_first.MAX_VIDEO_BYTES = 1000
        try:
            r = self.upload(eid, b"x" * 2000, "video/mp4")
            self.assertEqual(r.status_code, 413, r.text)
            self.assertIn("video file is larger than", r.text)
        finally:
            audio_first.MAX_VIDEO_BYTES = old
        self.assertEqual(self.uploads(), [], "nothing is left in work/uploads")

    def test_a_full_disk_refuses_the_upload_before_writing(self):
        from oddstudio import media
        old = media.free_bytes
        media.free_bytes = lambda folder: 10 * 1024 ** 2       # 10 MB free
        try:
            eid = self.create()
            r = self.upload(eid, b"RIFF" + b"\0" * 2000, "audio/wav")
            self.assertEqual(r.status_code, 507, r.text)
            self.assertIn("not enough free disk space", r.text)
        finally:
            media.free_bytes = old
        self.assertEqual(self.uploads(), [])
        self.assertEqual(self.state(eid)["stage"], "audio_upload")

    def test_rights_confirmation_covers_audio_and_video(self):
        eid = self.create()
        rights = [r for r in self.c.get(f"/api/episodes/{eid}").json()["reviews"] if r["gate"] == "audio_rights"]
        self.assertIn("its audio and any video", rights[0]["comment"])

    def test_hints_keep_only_people_setting_and_mood(self):
        from oddstudio.audio_first import HINTS_SYSTEM, clean_hints
        h = clean_hints({"people_count": "3", "setting": "Small office, daytime! <b>", "mood": "tense but funny really very",
                         "description": "a tall man with a beard", "names": ["Bob"]})
        self.assertEqual(h, {"people_count": 3, "setting": "Small office, daytime b", "mood": "tense but funny really"})
        self.assertEqual(clean_hints({"people_count": 99})["people_count"], None)
        self.assertEqual(clean_hints({})["people_count"], None)
        for rule in ("Never describe, identify or name anyone", "age, gender, ethnicity"):
            self.assertIn(rule, HINTS_SYSTEM)

    def test_trim_is_for_shorts_only(self):
        eid = self.create(fmt="long")
        r = self.c.post(f"/api/episodes/{eid}/audio/trim", json={"start": 0, "end": 30})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("Shorts only", r.text)
        from oddstudio.workflow import ALLOWED
        self.assertEqual(ALLOWED["trim_audio"], {"audio_upload", "audio_labelling"})


@unittest.skipUnless(FF and FFP, "FFmpeg and FFprobe are not installed")
class VideoTest(Base):
    with_ffmpeg = True

    def test_video_audio_is_extracted_and_the_original_deleted(self):
        eid = self.create()
        r = self.upload(eid, make_media(self.media, "clip.mp4", 3), "video/mp4")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["stage"], "audio_preparing")
        self.assertEqual(len(self.uploads()), 1, "the video waits in work/uploads for the worker")
        ran = self.env.run_jobs(["audio_media_prepare"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(self.uploads(), [], "the original video is deleted after extraction")
        st = self.state(eid)
        self.assertEqual(st["stage"], "audio_transcribing")
        self.assertEqual((st["source_media"]["type"], st["source_media"]["original_deleted"]), ("video", True))
        kinds = self.assets(eid)
        self.assertEqual([(k, c) for k, c, _ in kinds], [("source-audio", "audio/mp4")])
        self.assertTrue(all(not c.startswith("video/") for _, c, _ in kinds), "no video is ever stored")
        self.env.run_jobs(["audio_transcribe"])
        st = self.state(eid)
        self.assertEqual(st["stage"], "audio_labelling")
        self.assertEqual(st["source_media"]["type"], "video", "the upload facts survive the transcription")
        self.assertIsNone(st["media_hints"])

    def test_a_video_without_sound_is_refused(self):
        eid = self.create()
        r = self.upload(eid, make_media(self.media, "silent.mp4", 2, audio=False), "video/mp4")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("no audio track", r.text)
        self.assertEqual(self.uploads(), [])

    def test_hints_people_setting_mood_only_and_frames_deleted(self):
        providers.set_test_text_responder(lambda s, p: {"people_count": 2, "setting": "small office, daytime", "mood": "tense",
                                                        "description": "a tall man with a beard", "names": ["X"]})
        eid = self.create()
        self.assertEqual(self.upload(eid, make_media(self.media, "clip.mp4", 3), "video/mp4", hints=True).status_code, 200)
        self.env.run_jobs(["audio_media_prepare"])
        self.assertTrue(any(n.startswith("hints-") for n in self.uploads()), "frames wait for the hints job")
        ran = self.env.run_jobs(["audio_media_hints"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertEqual(len(providers.test_last_images), 6)
        self.assertTrue(all(n.endswith(".jpg") for n in providers.test_last_images))
        self.assertEqual(self.uploads(), [], "the frames are deleted after the hints")
        h = self.state(eid)["media_hints"]
        self.assertEqual({k: h[k] for k in ("people_count", "setting", "mood", "frames")},
                         {"people_count": 2, "setting": "small office, daytime", "mood": "tense", "frames": 6})
        self.assertNotIn("description", h)
        self.assertNotIn("names", h)
        self.env.run_jobs(["audio_transcribe"])
        self.assertEqual(self.state(eid)["media_hints"]["people_count"], 2, "hints survive the transcription")

    def test_frames_are_deleted_even_when_the_hints_fail(self):
        def boom(s, p):
            raise providers.ProviderError("model down")
        providers.set_test_text_responder(boom)
        eid = self.create()
        self.upload(eid, make_media(self.media, "clip.mp4", 3), "video/mp4", hints=True)
        self.env.run_jobs(["audio_media_prepare"])
        ran = self.env.run_jobs(["audio_media_hints"])
        self.assertEqual(ran[0][1], "failed", ran)
        self.assertEqual(self.uploads(), [], "frames deleted although the job failed")
        self.assertIsNone(self.state(eid)["media_hints"])

    def test_extraction_failure_deletes_the_video_and_returns_to_upload(self):
        from oddstudio import media
        old = media.extract_audio
        def broken(src, dst):
            raise media.MediaError("the audio track could not be read from this video")
        media.extract_audio = broken
        try:
            eid = self.create()
            self.upload(eid, make_media(self.media, "clip.mp4", 2), "video/mp4")
            self.env.run_jobs(["audio_media_prepare"])
        finally:
            media.extract_audio = old
        st = self.state(eid)
        self.assertEqual(st["stage"], "audio_upload")
        self.assertIn("could not be read", st["last_error"])
        self.assertEqual(self.uploads(), [])

    def test_a_long_recording_waits_for_the_shorts_60_s_window(self):
        eid = self.create()
        r = self.upload(eid, make_media(self.media, "long.wav", 70, video=False, rate=8000), "audio/wav")
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()
        self.assertEqual((st["stage"], st["needs_trim"], st["audio"]), ("audio_upload", True, None))
        self.assertIsNotNone(st["full_audio"])
        self.assertEqual(self.env.run_jobs(["audio_transcribe"]), [], "nothing is transcribed before the window")
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/transcribe").status_code, 409)
        trim = lambda a, b: self.c.post(f"/api/episodes/{eid}/audio/trim", json={"start": a, "end": b})
        self.assertEqual(trim(0, 61).status_code, 422)
        self.assertEqual(trim(20, 75).status_code, 422)          # ends after the recording
        self.assertEqual(trim(30, 20).status_code, 422)
        r = trim(5, 65)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["stage"], r.json()["trim"]), ("audio_transcribing", {"start": 5.0, "end": 65.0}))
        kinds = self.assets(eid)
        self.assertEqual([k for k, _, _ in kinds], ["source-audio-full", "source-audio"])
        from oddstudio.storage import storage
        local = storage().get_to_file(kinds[1][2], self.media / "window.wav")
        self.assertAlmostEqual(seconds_of(local), 60.0, delta=0.1)
        self.env.run_jobs(["audio_transcribe"])
        st = self.state(eid)
        self.assertEqual((st["stage"], st["trim"]["start"]), ("audio_labelling", 5.0))
        self.assertEqual(trim(0, 60).status_code, 200, "the window can be moved later (transcribed again)")
        self.assertEqual(self.uploads(), [], "trim scratch files are removed")

    def test_short_audio_needs_no_window_and_long_episodes_are_capped(self):
        eid = self.create()
        st = self.upload(eid, make_media(self.media, "ok.wav", 4, video=False, rate=8000), "audio/wav").json()
        self.assertEqual((st["stage"], st["needs_trim"]), ("audio_transcribing", False))
        long_id = self.create(fmt="long")
        r = self.upload(long_id, make_media(self.media, "too-long.wav", 452, video=False, rate=8000), "audio/wav")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("at most 450 s", r.text)


if __name__ == "__main__":
    unittest.main()
