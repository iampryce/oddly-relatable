"""The new-episode flow (2026-11-27, fix/new-episode-flow): what the owner hit creating "Breast Enlargement" from a video.

1. Cue phrases are per episode and EMPTY by default (no more Episode 15's will phrases); "Suggest from this episode"
   proposes up to five phrases from the episode's own transcript, free and local, and saves nothing.
2. Creating an episode from a video can keep a private copy as the guided steps' reference video, stored exactly where
   step 1 stores it (private/, never an asset); the audio is still extracted; step 1 sees it.
3. "Suggest speakers": Gemini (a mocked transport) watches the private reference video with its audio and suggests a
   label per line; without a video, the text model (a mocked HTTP client) guesses with capped confidence. Cost first
   (409), nothing saved until the owner accepts, labels mapped to the episode's characters, and Cast from video uses
   the labels as its character list.
No network, no paid call: only fake credentials."""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import wave

import httpx

from helpers import Env
from test_audio_stage1b import FF, FFP, make_media
from test_guided_generation import GeminiFake, gem_answer, openai_response

from oddstudio import acting_analysis as AA
from oddstudio import analysis
from oddstudio import cast_from_video as CV
from oddstudio import line_normaliser as LN
from oddstudio import local_describe as LD
from oddstudio import prompt_writer as PW
from oddstudio import speaker_suggest as SS

FAKE = {"gemini_api_key": "fake-gemini-credential-for-tests", "openai_api_key": "fake-openai-credential-for-tests"}
VIDEO = b"\x00\x00\x00\x18ftypmp42fake-reference-video-bytes"


def words(spec: str, t0=0.0, dur=0.3, gap=0.05):
    """ "Doctor so |0.8| Doctor so" -> timed words; |x| inserts a pause of x seconds."""
    out, t = [], t0
    for tok in spec.split():
        if tok.startswith("|"):
            t += float(tok.strip("|"))
            continue
        out.append({"start": round(t, 3), "end": round(t + dur, 3), "word": tok})
        t += dur + gap
    return out


def line(i, ws, speaker=""):
    return {"id": f"l{i}", "start": ws[0]["start"], "end": ws[-1]["end"], "text": " ".join(w["word"] for w in ws),
            "speaker": speaker, "words": ws}


def wav_bytes(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


TEXT = "So doctor, what do you think? Well, the thing is we can. So doctor, how big? Well, the thing is about this big."
TRANSCRIPT = {"provider": "openai", "model": "whisper-1", "language": "en", "duration": 12.0, "text": TEXT, "segments": [],
              "words": words("So doctor what do you think |0.8| Well the thing is we can |0.8| So doctor how big "
                             "|0.8| Well the thing is about this big")}


# ================================================================== 1. cue phrases (pure)
class CuePhrasesTest(unittest.TestCase):
    def test_no_cue_phrases_by_default(self):
        self.assertEqual(LN.DEFAULT_CUES, [], "Episode 15's will phrases are not a default any more")
        ws = words("I said yes I leave tomorrow morning early")
        self.assertEqual(len(LN.propose_lines([line(1, ws)], " ".join(w["word"] for w in ws))), 1)
        # the old behaviour, only when the owner types the phrases
        self.assertEqual(len(LN.propose_lines([line(1, ws)], "", cues=["I leave"])), 2)

    def test_suggest_from_this_episode(self):
        a = words("So doctor what do you think |0.8| Look here thing is we can")
        b = words("So doctor how big |0.8| Look here thing is about this big |0.8| um so um so", t0=a[-1]["end"] + 1.0)
        got = LN.suggest_cues([line(1, a), line(2, b)], "")
        phrases = [g["phrase"] for g in got]
        self.assertIn("So doctor", phrases)
        self.assertIn("Look here", phrases, "openers after a pause count")
        self.assertEqual(next(g for g in got if g["phrase"] == "Look here")["after_pause"], 2)
        # with a punctuated transcript where "Look, here" has a comma, it is not a phrase
        punct = ("So doctor what do you think? Look, here thing is we can. So doctor how big? Look, here thing is about "
                 "this big. Um so um so.")
        self.assertNotIn("Look here", [g["phrase"] for g in LN.suggest_cues([line(1, a), line(2, b)], punct)])
        self.assertNotIn("Um so", phrases, "fillers are never suggested")
        self.assertTrue(all(g["starts"] >= 2 for g in got))
        self.assertLessEqual(len(got), 5)

    def test_suggestions_need_repeats_and_mostly_sentence_starts(self):
        ws = words("I think so and I think not and I think maybe")         # mid-sentence repeats only
        self.assertEqual(LN.suggest_cues([line(1, ws)], ""), [])
        self.assertEqual(LN.suggest_cues([], ""), [])
        many = [line(i, words(f"Alpha{i % 7} beta |0.5| Alpha{i % 7} beta", t0=i * 10.0)) for i in range(1, 15)]
        self.assertEqual(len(LN.suggest_cues(many, "")), 5, "at most five")

    def test_lines_without_word_timings(self):
        ls = [{"id": "l1", "start": 0, "end": 1, "text": "Right then, off we go", "speaker": "", "words": []},
              {"id": "l2", "start": 1, "end": 2, "text": "Right then, here we are", "speaker": "", "words": []}]
        self.assertEqual([g["phrase"] for g in LN.suggest_cues(ls, "")], ["Right then"])


# ================================================================== API base: an audio episode with lines
class AudioBase(unittest.TestCase):
    with_ffmpeg = False

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("FFMPEG", "FFPROBE")}
        if self.with_ffmpeg:
            os.environ["FFMPEG"], os.environ["FFPROBE"] = FF, FFP
        else:
            os.environ.pop("FFMPEG", None); os.environ.pop("FFPROBE", None)
        self.env = Env().login()
        self.c = self.env.client
        analysis.set_test_analysis(transcriber=lambda cfg, audio: json.loads(json.dumps(TRANSCRIPT)))
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        with new_session() as db:
            put_secrets(db, FAKE)
            db.commit()
        self.eid = self.c.post("/api/audio-episodes", json={"title": "Sketch", "format": "long", "rights_confirmed": True,
                                                             "rights_source": "own_recording"}).json()["id"]

    def tearDown(self):
        analysis.set_test_analysis()
        AA.set_test_transport(None)
        PW.set_test_http_client(None)
        self.env.close()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def transcribe(self):
        r = self.c.put(f"/api/episodes/{self.eid}/audio", content=wav_bytes(), headers={"Content-Type": "audio/wav"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.env.run_jobs(["audio_transcribe"])[0][1], "succeeded")
        return self.st()

    def st(self):
        return self.c.get(f"/api/episodes/{self.eid}/audio").json()


class CueApiTest(AudioBase):
    def test_suggest_saves_nothing_and_cues_start_empty(self):
        st = self.transcribe()
        self.assertEqual(st["cues"], [])
        r = self.c.post(f"/api/episodes/{self.eid}/audio/cues/suggest")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("So doctor", [g["phrase"] for g in r.json()["suggestions"]])
        self.assertEqual(self.st()["cues"], [], "a suggestion is never saved by itself")
        # the owner edits and applies: Propose stores them for this episode only
        self.c.post(f"/api/episodes/{self.eid}/audio/normalise", json={"cues": ["So doctor"]})
        self.assertEqual(self.st()["cues"], ["So doctor"])
        other = self.c.post("/api/audio-episodes", json={"title": "Other", "format": "long", "rights_confirmed": True,
                                                          "rights_source": "other"}).json()
        self.assertEqual(other["cues"], [], "cue phrases are per episode")


# ================================================================== 2. keep the video
@unittest.skipUnless(FF and FFP, "FFmpeg and FFprobe are not installed")
class KeepVideoTest(AudioBase):
    with_ffmpeg = True

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="oddstudio-keep-")

    def tearDown(self):
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def upload(self, name, ctype, keep):
        from pathlib import Path
        f = make_media(Path(self.media), name, 2)
        q = "?keep_video=true" if keep else ""
        return self.c.put(f"/api/episodes/{self.eid}/audio{q}", content=f.read_bytes(), headers={"Content-Type": ctype})

    def assets(self):
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        with new_session() as db:
            return [(a.kind, a.content_type, a.storage_key) for a in db.query(Asset).filter_by(episode_id=self.eid)]

    def test_kept_privately_where_step_1_keeps_it_and_the_audio_is_still_extracted(self):
        r = self.upload("clip.mp4", "video/mp4", keep=True)
        self.assertEqual(r.status_code, 200, r.text)
        ref = r.json()["reference_video"]
        self.assertTrue(ref and ref["from_episode_upload"])
        from oddstudio import guided
        from oddstudio.db import new_session
        from oddstudio.storage import storage
        with new_session() as db:
            stored = guided.reference_video(db, self.eid)
        self.assertTrue(stored["key"].startswith(f"private/episodes/{self.eid}/reference-video-"))
        self.assertEqual(stored["content_type"], "video/mp4")
        self.assertTrue(storage().local_path(stored["key"]).exists())
        # step 1 of the guide sees it at once (so steps 2 and 4 can use it)
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()
        item = g["steps"]["upload"]["items"]["reference_video"]
        self.assertTrue(item and item["from_episode_upload"])
        self.assertTrue(self.c.get(f"/api/episodes/{self.eid}/cast-video").json()["describe"]["reference_video"])
        # the audio is extracted as before; the video is never an asset
        ran = self.env.run_jobs(["audio_media_prepare"])
        self.assertEqual(ran[0][1], "succeeded", ran)
        st = self.st()
        self.assertEqual(st["source_media"]["reference_kept"], "kept")
        self.assertEqual(st["stage"], "audio_transcribing")
        assets = self.assets()
        self.assertEqual([k for k, _, _ in assets], ["source-audio"])
        self.assertTrue(all(not ct.startswith("video/") and not key.startswith("private/") for _, ct, key in assets),
                        "the reference video is never added to the asset list")
        with new_session() as db:
            self.assertIsNotNone(guided.reference_video(db, self.eid), "the worker deleting its upload leaves the private copy")

    def test_not_kept_unless_ticked(self):
        self.assertEqual(self.upload("clip.mp4", "video/mp4", keep=False).status_code, 200)
        self.assertIsNone(self.st()["reference_video"])
        self.assertIsNone(self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["upload"]["items"]["reference_video"])

    def test_a_type_the_guided_steps_cannot_read_is_not_kept(self):
        r = self.upload("clip.mkv", "video/x-matroska", keep=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["reference_video"])
        self.assertEqual(r.json()["source_media"]["reference_kept"], "unsupported type")


# ================================================================== 3. suggested speakers
ANSWER = {"speakers": [{"line_id": "l1", "speaker": "Doctor", "confidence": 0.9},
                       {"line_id": "l2", "speaker": "ann", "confidence": "low"},
                       {"line_id": "l3", "speaker": "Doctor", "confidence": 85}]}


class SpeakerTest(AudioBase):
    def setUp(self):
        super().setUp()
        self.lines = self.transcribe()["lines"]
        from oddstudio.db import new_session
        from oddstudio.models import Character
        with new_session() as db:
            db.add(Character(key="ann", name="Ann", scope="episode", episode_id=self.eid))
            db.commit()

    def url(self, tail=""):
        return f"/api/episodes/{self.eid}/audio/speaker-suggestions{tail}"

    def add_video(self):
        r = self.c.put(f"/api/episodes/{self.eid}/guide/reference-video", content=VIDEO, headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)

    def jobs(self):
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as db:
            return [j.kind for j in db.query(Job).filter_by(kind=SS.JOB)]

    def suggest(self, answer=ANSWER, **kw):
        fake = GeminiFake([gem_answer(answer)])
        AA.set_test_transport(httpx.MockTransport(fake))
        est = self.c.get(self.url()).json()["video_estimate"]
        r = self.c.post(self.url("/video"), json={"confirm_usd": est["usd_max"], **kw})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs([SS.JOB])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        return fake

    def test_cost_first_409(self):
        self.add_video()
        v = self.c.get(self.url()).json()
        self.assertTrue(v["reference_video"] and v["video_estimate"]["usd_max"] > 0)
        self.assertEqual(self.c.post(self.url("/video"), json={}).status_code, 409)
        self.assertEqual(self.c.post(self.url("/video"), json={"confirm_usd": v["video_estimate"]["usd_max"] / 2}).status_code, 409)
        r = self.c.post(self.url("/video"), json={"confirm_usd": 5, "paid_tier": False, "use_free_tier": False})
        self.assertEqual(r.status_code, 409, "no tier ticked: nothing is sent")
        self.assertEqual(self.jobs(), [])

    def test_video_suggestion_is_reviewed_never_saved_and_mapped(self):
        self.add_video()
        fake = self.suggest()
        self.assertEqual(fake.deleted, ["files/abc"], "the uploaded video is deleted from Google")
        model, body = fake.calls[0]
        self.assertEqual(model, "gemini-3.1-pro-preview", "the paid model when the paid tier is ticked")
        parts = body["contents"][0]["parts"]
        self.assertEqual(parts[0]["file_data"]["file_uri"], "https://g.example/files/abc")
        prompt = parts[1]["text"]
        for ln in self.lines:
            self.assertIn(f'"id": "{ln["id"]}"', prompt)
        self.assertIn("LISTEN".lower(), prompt.lower())
        # nothing saved: the lines still have no speaker
        st = self.st()
        self.assertEqual(st["unlabelled_lines"], len(self.lines))
        sug = self.c.get(self.url()).json()["suggestion"]
        rows = {r["line_id"]: r for r in sug["rows"]}
        self.assertEqual((rows["l1"]["label"], rows["l1"]["confidence"], rows["l1"]["level"]), ("Doctor", 0.9, "high"))
        self.assertEqual((rows["l2"]["character_key"], rows["l2"]["character_name"]), ("ann", "Ann"), "mapped by name")
        self.assertEqual(rows["l2"]["level"], "low")
        self.assertEqual(rows["l3"]["confidence"], 0.85)
        self.assertEqual(rows["l4"]["label"], "", "a skipped line stays empty")
        self.assertFalse(sug["stale"])
        self.assertEqual(sug["source"], "video")
        # the owner accepts some rows (one edited); only those lines change
        r = self.c.post(self.url("/accept"), json={"rows": [{"line_id": "l1", "speaker": "Doctor"},
                                                            {"line_id": "l2", "speaker": "ann"}]})
        self.assertEqual(r.status_code, 200, r.text)
        got = {ln["id"]: ln["speaker"] for ln in r.json()["lines"]}
        self.assertEqual((got["l1"], got["l2"], got["l3"]), ("Doctor", "ann", ""))
        # Cast from video uses the labels as its character list
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            names = CV.cast_names(db, db.get(Episode, self.eid))
        self.assertIn("Doctor", names)
        self.assertEqual(sum(1 for n in names if n.lower() == "ann"), 1)
        self.assertIn("Doctor", self.c.get(f"/api/episodes/{self.eid}/cast-video").json()["describe"]["cast_names"])

    def test_pending_labels_feed_cast_and_a_stale_suggestion_is_refused(self):
        self.add_video()
        self.suggest()
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as db:
            self.assertIn("Doctor", CV.cast_names(db, db.get(Episode, self.eid)), "pending labels before any is saved")
        lines = self.st()["lines"]
        lines[0]["text"] = "So doctor, what do you think then?"
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": lines}).status_code, 200)
        self.assertTrue(self.c.get(self.url()).json()["suggestion"]["stale"])
        r = self.c.post(self.url("/accept"), json={"rows": [{"line_id": "l1", "speaker": "Doctor"}]})
        self.assertEqual(r.status_code, 409)

    def test_free_tier_only_when_ticked(self):
        self.add_video()
        fake = self.suggest(paid_tier=False, use_free_tier=True)
        self.assertEqual(fake.calls[0][0], "gemini-3.5-flash")
        self.assertEqual(self.c.get(self.url()).json()["suggestion"]["usd"], 0.0)

    def test_no_video_falls_back_to_the_text_model(self):
        v = self.c.get(self.url()).json()
        self.assertFalse(v["reference_video"])
        self.assertIsNone(v["video_estimate"])
        self.assertEqual(self.c.post(self.url("/video"), json={"confirm_usd": 5}).status_code, 409)
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=openai_response("```json\n" + json.dumps(ANSWER) + "\n```"))
        PW.set_test_http_client(httpx.Client(transport=httpx.MockTransport(handler)))
        est = v["text_estimate"]
        self.assertEqual(self.c.post(self.url("/text"), json={}).status_code, 409)
        self.assertEqual(seen, [], "nothing is sent without the confirmed cost")
        r = self.c.post(self.url("/text"), json={"confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(seen), 1)
        self.assertIn('"id": "l1"', seen[0]["input"])
        sug = r.json()["suggestion"]
        self.assertEqual(sug["source"], "text")
        self.assertTrue(all(row["confidence"] <= SS.TEXT_CAP for row in sug["rows"]), "lower confidence from text only")
        self.assertEqual(self.st()["unlabelled_lines"], len(self.lines), "never saved by itself")
        self.assertEqual(self.c.delete(self.url()).json()["suggestion"], None)


class SpeakerPureTest(unittest.TestCase):
    def test_confidence_and_mapping(self):
        self.assertEqual(SS.confidence_of("high"), 0.9)
        self.assertEqual(SS.confidence_of("70%"), 0.7)
        self.assertEqual(SS.confidence_of(None), 0.0)
        chars = [{"key": "jim-hacker", "name": "Jim Hacker"}, {"key": "doc", "name": "Doctor Who"}, {"key": "doc2", "name": "Doctor No"}]
        self.assertEqual(SS.map_label("Jim", chars)["key"], "jim-hacker")
        self.assertEqual(SS.map_label("doc", chars)["key"], "doc")
        self.assertIsNone(SS.map_label("Doctor", chars), "two characters share the first word: no guess")
        rows = SS.normalise({"l2": "Nurse"}, [{"id": "l1", "start": 0, "end": 1}, {"id": "l2", "start": 1, "end": 2}], [], cap=0.5)
        self.assertEqual([r["label"] for r in rows], ["", "Nurse"])
        self.assertEqual(SS.labels_of(rows), ["Nurse"])


# ================================================================== 4. Characters on the episode page
class SpeakerCastTest(AudioBase):
    """Speaker labels become characters on the episode page (speaker_cast.py), and the old "Cast and poses" blocker
    (now "Characters") clears once every speaking character has an approved master from the Cast step."""

    def setUp(self):
        super().setUp()
        lines = self.transcribe()["lines"]
        for ln, sp in zip(lines, ["Doctor", "Patient", "Doctor", "Ann"]):
            ln["speaker"] = sp
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": lines}).status_code, 200)
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset
        with new_session() as db:
            db.add(Character(key="ann", name="Ann", scope="episode", episode_id=self.eid))
            saved = Character(key="patient-saved", name="Patient", scope="recurring", art_status="approved")
            db.add(saved)
            db.flush()
            m = CharacterAsset(character_id=saved.id, kind="master", storage_key="characters/patient/master.png", status="approved")
            db.add(m)
            db.flush()
            CV._put(db, "cast_library", {"entries": {"lib1": {"id": "lib1", "character_id": saved.id, "name": "Patient",
                                                              "style": "stick", "master_asset_id": m.id, "versions": [m.id],
                                                              "saved_at": 0}}})
            db.commit()

    def cast_section(self):
        ws = self.c.get(f"/api/episodes/{self.eid}/workspace").json()
        return next(s for s in ws["sections"] if s["key"] == "cast")

    def apply_proposals(self):
        prop = {r["label"]: r["proposal"] for r in self.c.get(f"/api/episodes/{self.eid}/speaker-cast").json()["speakers"]}
        choices = [{"label": k, **p} for k, p in prop.items()]
        return prop, choices, self.c.post(f"/api/episodes/{self.eid}/speaker-cast", json={"choices": choices})

    def test_speakers_map_to_characters(self):
        self.assertIn("not a character yet", self.cast_section()["note"])
        prop, choices, r = self.apply_proposals()
        self.assertEqual(prop["Doctor"], {"kind": "new", "name": "Doctor"})
        self.assertEqual((prop["Patient"]["kind"], prop["Patient"]["library_id"]), ("library", "lib1"), "a saved character, free")
        self.assertEqual((prop["Ann"]["kind"], prop["Ann"]["character_key"]), ("existing", "ann"), "mapped by name")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["speakers"], [], "every label is a character now")
        speakers = [ln["speaker"] for ln in self.st()["lines"]]
        self.assertEqual(speakers, [f"doctor-ep{self.eid}", "patient-saved", f"doctor-ep{self.eid}", "ann"])
        cast = {c["name"] for c in self.c.get(f"/api/episodes/{self.eid}/cast-video").json()["characters"]}
        self.assertEqual(cast, {"Doctor", "Patient", "Ann"}, "the Cast step lists them")
        sec = self.cast_section()
        self.assertNotIn("not a character yet", sec["note"])
        self.assertIn("Doctor", sec["note"])
        self.assertNotIn("Patient", sec["note"], "the saved character's approved master counts")
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/speaker-cast", json={"choices": choices}).status_code, 422)

    def test_cast_step_is_unblocked_by_approved_masters(self):
        self.apply_proposals()
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset
        for key in (f"doctor-ep{self.eid}", "ann"):
            self.assertNotEqual(self.cast_section()["status"], "done")
            with new_session() as db:
                c = db.query(Character).filter_by(key=key).one()
                a = CharacterAsset(character_id=c.id, kind="master", storage_key=f"characters/{key}/cand.png", status="review")
                db.add(a)
                db.commit()
                cid, aid = c.id, a.id
            r = self.c.post(f"/api/episodes/{self.eid}/cast-video/characters/{cid}/approve", json={"asset_id": aid, "keep": "episode"})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.cast_section()["status"], "done")


# ================================================================== 5. descriptions on this server (free, private)
class LocalPureTest(unittest.TestCase):
    def test_frame_times_follow_each_speakers_longest_lines(self):
        lines = [{"start": 0, "end": 1, "speaker": "doc"}, {"start": 2, "end": 6, "speaker": "doc"},
                 {"start": 6, "end": 7, "speaker": "Patient"}, {"start": 8, "end": 9.5, "speaker": "doc"},
                 {"start": 10, "end": 10.4, "speaker": "doc"}, {"start": 11, "end": 12, "speaker": ""}]
        t = LD.frame_times(lines, {"doc": "Doctor"}, offset=30.0)
        self.assertEqual(t, {"Doctor": [34.0, 38.75], "Patient": [36.5]})

    def test_answers_are_parsed_or_left_empty(self):
        self.assertEqual(LD.parse_answer('Sure! ```json\n{"age": "40s", "hair": {"style": "short"}}\n```')["age"], "40s")
        self.assertEqual(LD.parse_answer("a tall man in a coat"), {})
        self.assertEqual(LD.parse_answer("{not json}"), {})
        d = CV.normalise_descriptions([{"name": "Doctor", "age": "40s", "hair": "short grey",
                                         "clothing": [{"garment": "coat", "colour": "white"}], "accessory": "a stethoscope",
                                         "face": "ignored"}], ["Doctor"], {"Doctor": {"traits": "calm"}})[0]
        self.assertEqual((d["hair"], d["clothing"], d["personality"]),
                         ({"style": "short grey", "colour": ""}, [{"garment": "coat", "colour": "white"}], "calm"))
        self.assertNotIn("face", d)


@unittest.skipUnless(FF and FFP, "FFmpeg and FFprobe are not installed")
class LocalDescribeTest(AudioBase):
    with_ffmpeg = True

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="oddstudio-local-")
        lines = self.transcribe()["lines"]
        for ln, sp in zip(lines, ["Doctor", "Patient", "Doctor", "Patient"]):
            ln["speaker"] = sp
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": lines}).status_code, 200)
        from pathlib import Path
        video = make_media(Path(self.media), "ref.mp4", 12).read_bytes()
        r = self.c.put(f"/api/episodes/{self.eid}/guide/reference-video", content=video, headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)
        self.external = []           # any request that would leave the server

        def refuse(request):
            self.external.append(str(request.url))
            return httpx.Response(500, json={})
        AA.set_test_transport(httpx.MockTransport(refuse))
        PW.set_test_http_client(httpx.Client(transport=httpx.MockTransport(refuse)))
        self.seen = []

        def model(images, prompt, log):
            self.seen.append(([Path(p) for p in images], prompt))
            return ('```json {"age": "40s", "build": "tall", "hair": {"style": "short", "colour": "grey"}, '
                    '"clothing": [{"garment": "coat", "colour": "white"}], "accessory": "a stethoscope"} ```'
                    if len(self.seen) == 1 else "I cannot tell.")
        LD.set_test_runner(model)

    def tearDown(self):
        LD.set_test_runner(None)
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def cast(self):
        return self.c.get(f"/api/episodes/{self.eid}/cast-video").json()

    def test_described_on_this_server_frames_stay_and_are_deleted(self):
        r = self.c.post(f"/api/episodes/{self.eid}/cast-video/describe-local")
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["cast_describe_local"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        self.assertEqual(self.external, [], "nothing leaves the server")
        self.assertEqual(len(self.seen), 2, "one call per speaker")
        from oddstudio.config import get_settings
        work = get_settings().work_dir.resolve()
        for frames, prompt in self.seen:
            self.assertTrue(1 <= len(frames) <= LD.FRAMES_PER_PERSON)
            for f in frames:
                self.assertTrue(f.resolve().is_relative_to(work), "frames are taken in the server's own work folder")
                self.assertFalse(f.exists(), "frames are deleted afterwards")
            self.assertIn("Do not describe the face", prompt)
        v = self.cast()
        d = {x["name"]: x for x in v["descriptions"]}
        self.assertEqual((d["Doctor"]["accessory"], d["Doctor"]["age"]), ("a stethoscope", "40s"))
        self.assertEqual(d["Doctor"]["described_by"], LD.LOCAL_NOTE)
        self.assertEqual(d["Patient"]["accessory"], "", "a plain-words answer fills no field by guess")
        self.assertEqual(d["Patient"]["role"], "Seen on this server: I cannot tell.", "it is kept as a note to edit")
        self.assertEqual((v["describe"]["made_by"], v["describe"]["usd"]), (LD.LOCAL_NOTE, 0.0))
        # the owner edits it like any description
        r = self.c.put(f"/api/episodes/{self.eid}/cast-video/descriptions/{d['Patient']['id']}", json={"accessory": "a sling"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_provider_choice_and_the_offer_after_gemini_429(self):
        self.assertEqual(self.c.put("/api/cast/describer", json={"provider": "cloud"}).status_code, 422)
        info = self.cast()["describe"]
        self.assertEqual(info["provider"], "gemini")
        self.assertFalse(info["local"]["offer"])
        # Gemini busy (paid model only, no free tier): the free describer is offered
        fake = GeminiFake([(429, {"error": {"code": 429}})])
        AA.set_test_transport(httpx.MockTransport(fake))
        est = info["estimate"]
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/cast-video/describe", json={"confirm_usd": est["usd_max"]}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["cast_describe"])[-1][1], "failed")
        info = self.cast()["describe"]
        self.assertTrue(info["local"]["offer"])
        self.assertIn("busy", info["local"]["reason"])
        self.assertEqual(self.c.put("/api/cast/describer", json={"provider": "local"}).status_code, 200)
        info = self.cast()["describe"]
        self.assertEqual(info["provider"], "local")

    def test_manual_descriptions_to_type(self):
        r = self.c.post(f"/api/episodes/{self.eid}/cast-video/describe-manual")
        self.assertEqual(r.status_code, 200, r.text)
        v = r.json()
        self.assertEqual(sorted(x["name"] for x in v["descriptions"]), ["Doctor", "Patient"])
        self.assertEqual(v["describe"]["made_by"], "typed by you")
        self.assertEqual(self.seen, [])

    @unittest.skipIf(importlib.util.find_spec("torch") is not None, "the runtime is installed here")
    def test_refused_when_the_runtime_is_not_installed(self):
        LD.set_test_runner(None)
        r = self.c.post(f"/api/episodes/{self.eid}/cast-video/describe-local")
        self.assertEqual(r.status_code, 409)
        self.assertIn("not installed", r.text)
