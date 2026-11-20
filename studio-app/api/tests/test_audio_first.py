"""Audio-first episodes, stage 1: the rights gate, upload, transcription into timed lines (test transcriber), speaker
labelling, the cast (manual and AI-suggested) and the additive migration. No network calls: the transcriber and the
text model are the test stand-ins, the settings, gates, queue and worker are the real code."""
import os
import tempfile
import unittest
from pathlib import Path

from helpers import Env

from oddstudio import analysis, providers
from oddstudio.audio_first import split_lines

WORDS = [  # "Who took my charger?" (A) ... pause ... "Not me. I swear." (B)
    {"start": 0.10, "end": 0.30, "word": " Who"}, {"start": 0.32, "end": 0.55, "word": " took"},
    {"start": 0.57, "end": 0.70, "word": " my"}, {"start": 0.72, "end": 1.20, "word": " charger?"},
    {"start": 2.10, "end": 2.30, "word": " Not"}, {"start": 2.32, "end": 2.60, "word": " me."},
    {"start": 2.70, "end": 2.80, "word": " I"}, {"start": 2.82, "end": 3.30, "word": " swear."},
]
TRANSCRIPT = {"provider": "openai", "model": "whisper-1", "language": "en", "duration": 3.6,
              "text": "Who took my charger? Not me. I swear.",
              "segments": [{"start": 0.1, "end": 1.2, "text": "Who took my charger?"}, {"start": 2.1, "end": 3.3, "text": "Not me. I swear."}],
              "words": WORDS}


def _wav(seconds=1.0, rate=16000) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


AUDIO = _wav()      # a real (silent) WAV, so the upload also passes when FFPROBE is set and the duration is probed


class SplitLinesTest(unittest.TestCase):
    def test_words_split_at_pauses_and_sentence_ends(self):
        lines = split_lines(TRANSCRIPT)
        self.assertEqual([ln["text"] for ln in lines], ["Who took my charger?", "Not me.", "I swear."])
        self.assertEqual([(ln["start"], ln["end"]) for ln in lines], [(0.1, 1.2), (2.1, 2.6), (2.7, 3.3)])
        self.assertEqual([ln["id"] for ln in lines], ["l1", "l2", "l3"])
        self.assertTrue(all(ln["speaker"] == "" for ln in lines))
        self.assertEqual([w["word"] for w in lines[0]["words"]], ["Who", "took", "my", "charger?"])

    def test_long_runs_are_capped(self):
        words = [{"start": i * 0.4, "end": i * 0.4 + 0.3, "word": f"w{i}"} for i in range(40)]   # 16 s, no pauses
        lines = split_lines({"words": words}, max_seconds=8.0, max_words=24)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(ln["end"] - ln["start"] <= 8.0 for ln in lines))
        self.assertEqual(sum(len(ln["words"]) for ln in lines), 40)

    def test_segments_are_used_without_word_timestamps(self):
        lines = split_lines({**TRANSCRIPT, "words": []})
        self.assertEqual([ln["text"] for ln in lines], ["Who took my charger?", "Not me. I swear."])
        self.assertEqual(lines[0]["words"], [])

    def test_empty_transcript_gives_no_lines(self):
        self.assertEqual(split_lines({"text": "", "segments": [], "words": []}), [])


class AudioFirstTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        analysis.set_test_analysis(transcriber=lambda cfg, audio: dict(TRANSCRIPT))

    def tearDown(self):
        analysis.set_test_analysis()
        providers.set_test_text_responder(None)
        self.env.close()

    def create(self, **kw):
        body = {"title": "Charger audio", "rights_confirmed": True, "rights_source": "own_recording", **kw}
        return self.c.post("/api/audio-episodes", json=body)

    def upload(self, eid, data=AUDIO, ctype="audio/wav"):
        return self.c.put(f"/api/episodes/{eid}/audio", content=data, headers={"Content-Type": ctype})

    def ready(self):
        """An audio episode transcribed and waiting for labels."""
        ep = self.create().json()
        self.assertEqual(self.upload(ep["id"]).status_code, 200)
        ran = self.env.run_jobs(["audio_transcribe"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        return ep["id"]

    # ------------------------------------------------------------------ rights gate
    def test_rights_checkbox_is_required(self):
        r = self.create(rights_confirmed=False)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("right to use this audio", r.text)
        r = self.create(rights_source=None)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(self.create(rights_source="found-online").status_code, 422)   # only the four labels
        self.assertEqual(self.c.get("/api/episodes").json(), [])                      # nothing was created

    def test_rights_are_stored_and_recorded(self):
        ep = self.create(rights_source="voice_actor").json()
        self.assertEqual((ep["source"], ep["stage"], ep["audio_rights_confirmed"], ep["audio_rights_source"]),
                         ("audio", "audio_upload", True, "voice_actor"))
        detail = self.c.get(f"/api/episodes/{ep['id']}").json()
        rights = [r for r in detail["reviews"] if r["gate"] == "audio_rights"]
        self.assertEqual(len(rights), 1)
        self.assertEqual(rights[0]["decision"], "confirmed")
        self.assertIn("voice actor", rights[0]["comment"])

    def test_upload_refused_for_script_episodes_and_without_rights(self):
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            script_ep = Episode(title="Script one", stage="script_pending")
            unconfirmed = Episode(title="No rights", stage="audio_upload", source="audio", audio_rights_confirmed=False)
            s.add_all([script_ep, unconfirmed])
            s.commit()
            ids = script_ep.id, unconfirmed.id
        self.assertEqual(self.upload(ids[0]).status_code, 409)
        r = self.upload(ids[1])
        self.assertEqual(r.status_code, 409)
        self.assertIn("right to use this audio", r.text)

    def test_upload_checks_type_and_size(self):
        eid = self.create().json()["id"]
        r = self.upload(eid, ctype="video/mp4")      # Stage 1b: video is accepted, but only with FFmpeg configured
        self.assertEqual(r.status_code, 503, r.text)
        self.assertIn("FFmpeg", r.text)
        self.assertEqual(self.upload(eid, ctype="text/html").status_code, 415)
        self.assertEqual(self.upload(eid, data=b"").status_code, 422)
        from oddstudio import audio_first
        old = audio_first.MAX_BYTES
        audio_first.MAX_BYTES = 10_000
        try:
            self.assertEqual(self.upload(eid).status_code, 413)
        finally:
            audio_first.MAX_BYTES = old
        self.assertEqual(self.c.get(f"/api/episodes/{eid}/audio").json()["stage"], "audio_upload")
        self.assertFalse(list((self.env.tmp / "work" / "uploads").glob("*")), "partial uploads are removed")

    # ------------------------------------------------------------------ transcription
    def test_upload_transcribes_into_timed_lines(self):
        eid = self.create().json()["id"]
        st = self.upload(eid).json()
        self.assertEqual(st["stage"], "audio_transcribing")
        self.assertEqual(st["audio"]["kind"], "source-audio")
        self.assertEqual(self.c.get(st["audio"]["url"]).content, AUDIO)
        ran = self.env.run_jobs(["audio_transcribe"])
        self.assertEqual(ran, [("audio_transcribe", "succeeded", "")])
        st = self.c.get(f"/api/episodes/{eid}/audio").json()
        self.assertEqual(st["stage"], "audio_labelling")
        self.assertEqual([ln["text"] for ln in st["lines"]], ["Who took my charger?", "Not me.", "I swear."])
        self.assertEqual(st["unlabelled_lines"], 3)
        self.assertEqual((st["transcript"]["provider"], st["transcript"]["duration"], st["transcript"]["words_available"]),
                         ("openai", 3.6, True))

    def test_transcription_failure_returns_to_upload(self):
        analysis.set_test_analysis(transcriber=lambda cfg, audio: (_ for _ in ()).throw(providers.ProviderNotConfigured("no transcription provider")))
        eid = self.create().json()["id"]
        self.upload(eid)
        ran = self.env.run_jobs(["audio_transcribe"])
        self.assertEqual(ran[0][1], "failed")
        detail = self.c.get(f"/api/episodes/{eid}/audio").json()
        self.assertEqual(detail["stage"], "audio_upload")
        self.assertIn("no transcription provider", detail["last_error"])
        analysis.set_test_analysis(transcriber=lambda cfg, audio: dict(TRANSCRIPT))
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/transcribe").status_code, 200)
        self.assertEqual(self.env.run_jobs(["audio_transcribe"])[0][1], "succeeded")
        self.assertEqual(self.c.get(f"/api/episodes/{eid}/audio").json()["stage"], "audio_labelling")

    def test_no_speech_is_an_error(self):
        analysis.set_test_analysis(transcriber=lambda cfg, audio: {"text": "", "segments": [], "words": []})
        eid = self.create().json()["id"]
        self.upload(eid)
        ran = self.env.run_jobs(["audio_transcribe"])
        self.assertEqual(ran[0][1], "failed")
        self.assertIn("no speech", ran[0][2])

    # ------------------------------------------------------------------ labelling
    def test_label_speakers_and_validation(self):
        eid = self.ready()
        lines = self.c.get(f"/api/episodes/{eid}/audio").json()["lines"]
        for ln, sp in zip(lines, ["Dan", "Kim", "Kim"]):
            ln["speaker"] = sp
        r = self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": lines})
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()
        self.assertEqual(st["speakers"], ["Dan", "Kim"])
        self.assertEqual(st["unlabelled_lines"], 0)
        self.assertEqual(st["speakers_without_character"], ["Dan", "Kim"])
        # merge two lines (owner edit) keeps the timing inside the audio
        merged = [lines[0], {**lines[1], "end": lines[2]["end"], "text": "Not me. I swear.", "words": lines[1]["words"] + lines[2]["words"]}]
        self.assertEqual(len(self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": merged}).json()["lines"]), 2)
        bad = [{**lines[0], "end": 5.0}]                                            # beyond the 3.6 s audio
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": bad}).status_code, 422)
        overlap = [lines[0], {**lines[1], "start": 0.5}]
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": overlap}).status_code, 422)
        backwards = [{**lines[0], "start": 1.0, "end": 0.5}]
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": backwards}).status_code, 422)
        stray = [{**lines[0], "words": [{"start": 3.0, "end": 3.2, "word": "x"}]}]
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": stray}).status_code, 422)

    def test_labelling_needs_the_labelling_stage(self):
        eid = self.create().json()["id"]
        r = self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": [{"start": 0, "end": 1, "text": "x"}]})
        self.assertEqual(r.status_code, 409)

    # ------------------------------------------------------------------ cast
    def label(self, eid, speakers):
        lines = self.c.get(f"/api/episodes/{eid}/audio").json()["lines"]
        for ln, sp in zip(lines, speakers):
            ln["speaker"] = sp
        return self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": lines}).json()

    def test_cast_from_speakers_creates_characters_and_relabels_lines(self):
        eid = self.ready()
        self.label(eid, ["Dan", "Kim", "Kim"])
        body = {"speakers": [
            {"label": "Dan", "character_key": "character-01"},
            {"label": "Kim", "new": {"key": "kim", "name": "Kim", "description": "Dry, unbothered flatmate",
                                     "voice_style": "late 20s, flat, slow", "bubble_style": "her"}}]}
        r = self.c.post(f"/api/episodes/{eid}/audio/cast", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()
        self.assertEqual([ln["speaker"] for ln in st["lines"]], ["character-01", "kim", "kim"])
        self.assertEqual(st["speakers_without_character"], [])
        kim = next(c for c in self.c.get("/api/characters").json() if c["key"] == "kim")
        self.assertEqual((kim["scope"], kim["episode_id"], kim["art_status"], kim["voice"], kim["voice_style"]),
                         ("episode", eid, "none", "", "late 20s, flat, slow"))
        # the same key cannot be created twice; unknown labels and ambiguous choices are refused
        self.label(eid, ["Dan", "Kim", "Kim"])
        dup = {"speakers": [{"label": "Kim", "new": {"key": "kim", "name": "Kim 2"}}]}
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/cast", json=dup).status_code, 409)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/cast", json={"speakers": [{"label": "Nobody", "character_key": "kim"}]}).status_code, 422)
        both = {"speakers": [{"label": "Dan", "character_key": "kim", "new": {"key": "dan", "name": "Dan"}}]}
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/cast", json=both).status_code, 422)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/cast", json={"speakers": [{"label": "Dan", "character_key": "ghost"}]}).status_code, 422)

    def test_ai_cast_suggestion_is_stored_and_sanitised(self):
        eid = self.ready()
        seen = {}

        def responder(system, prompt):
            seen["prompt"] = prompt
            return {"speakers": [
                {"label": "A", "reuse_key": None, "name": "Dan", "key": "Dan Smith!", "description": "Accuser",
                 "visual_description": "flat dark cap", "voice_style": "30s, fast, indignant", "bubble_style": "him"},
                {"label": "B", "reuse_key": "character-01", "name": "", "key": "", "bubble_style": "robot"},
                {"label": "", "name": "dropped"}],
                "line_speakers": {"l1": "A", "l2": "B", "l3": "B", "l99": "A", "l1x": "Z"}}
        providers.set_test_text_responder(responder)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/suggest-cast").status_code, 200)
        ran = self.env.run_jobs(["audio_cast_suggest"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        self.assertIn("[l1 | speaker: ? | 0.1-1.2 s] Who took my charger?", seen["prompt"])
        sug = self.c.get(f"/api/episodes/{eid}/audio").json()["cast_suggestion"]
        self.assertEqual([s["label"] for s in sug["speakers"]], ["A", "B"])
        self.assertEqual(sug["speakers"][0]["key"], "dan-smith")
        self.assertEqual((sug["speakers"][1]["reuse_key"], sug["speakers"][1]["bubble_style"]), ("character-01", "neutral"))
        self.assertEqual(sug["line_speakers"], {"l1": "A", "l2": "B", "l3": "B"})
        # a suggestion changes nothing until the owner applies it
        st = self.c.get(f"/api/episodes/{eid}/audio").json()
        self.assertEqual(st["unlabelled_lines"], 3)
        self.assertNotIn("dan-smith", [c["key"] for c in self.c.get("/api/characters").json()])

    def test_suggestion_needs_a_transcript_and_the_stage(self):
        eid = self.create().json()["id"]
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/suggest-cast").status_code, 409)


class MigrationTest(unittest.TestCase):
    def test_0005_is_additive_and_reversible(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        api = Path(__file__).resolve().parents[1]
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = Config(str(api / "alembic.ini"))
            cfg.set_main_option("script_location", str(api / "migrations"))
            command.upgrade(cfg, "0004")
            eng = create_engine(os.environ["DATABASE_URL"])
            with eng.begin() as conn:     # an episode written by the previous release
                conn.exec_driver_sql("insert into episodes (title, stage, revision, storyboard_version, last_error, format, created_at, updated_at) "
                                     "values ('old', 'script_pending', 1, 0, '', 'short', '2026-11-20', '2026-11-20')")
            command.upgrade(cfg, "head")
            cols = {c["name"] for c in inspect(eng).get_columns("episodes")}
            self.assertTrue({"source", "audio_rights_confirmed", "audio_rights_source", "audio_asset_id", "audio_transcript"} <= cols)
            with eng.connect() as conn:
                row = conn.exec_driver_sql("select source, audio_rights_confirmed, audio_rights_source, audio_asset_id from episodes").one()
            self.assertEqual(tuple(row), ("script", 0, "", None))       # existing episodes default to script, no rights
            command.downgrade(cfg, "0004")
            self.assertNotIn("source", {c["name"] for c in inspect(eng).get_columns("episodes")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


if __name__ == "__main__":
    unittest.main()
