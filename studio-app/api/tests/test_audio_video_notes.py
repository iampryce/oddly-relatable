"""Video reference notes ("reference, not copy", owner decision 2026-11-21): frames only from the part of the video the
episode uses (the Short's window or the whole clip), at most 24, turned into TEXT-ONLY staging notes by the studio's API
vision provider; anything outside the notes' schema is removed; frames and video are deleted; the scene writer uses
the notes as soft suggestions and never changes the recorded dialogue."""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from test_audio_stage1b import FF, FFP, Base, make_media

from oddstudio import analysis, providers
from oddstudio import video_notes as VN

JUNK = {"summary": "a scene from a famous sitcom",
        "ranges": [{"start": 0, "end": 5, "shot": "medium", "camera": "pan", "setting": "Central Perk cafe",
                    "dialogue": "How you doin?",
                    "roles": [{"role": "speaker", "position": "left", "pose": "standing", "facing": "reactor 1",
                               "emotion": "annoyed", "name": "Rachel", "clothing": "red dress"},
                              {"role": "Joey", "position": "right"},
                              {"role": "reactor 1", "emotion": "seductive", "facing": "reactor 1", "pose": "seated"}]},
                   {"start": 5, "end": 99, "shot": "close", "setting": "office", "camera": "static",
                    "roles": [{"role": "reactor 2", "position": "right", "emotion": "shocked", "facing": "speaker"}]},
                   {"start": "soon", "end": 3}, {"start": 4, "end": 2}, "a frame with a logo"]}
FORBIDDEN = ("Rachel", "Joey", "red", "dress", "Central", "Perk", "doin", "sitcom", "logo", "seductive")


def junk_v2(n: int) -> dict:
    """A v2 answer (notes v2, per frame and per person) with the same kinds of junk as JUNK: frames 1-5 one staging,
    the rest another; names, clothing, dialogue and values off the lists must all be stripped."""
    first = {"shot": "medium", "camera": "pan", "setting": "Central Perk cafe", "dialogue": "How you doin?",
             "people": [{"person": 1, "position": "left", "pose": "standing", "facing": "person 2", "emotion": "annoyed",
                         "talking": True, "name": "Rachel", "clothing": "red dress"},
                        {"person": "Joey", "position": "right"},
                        {"person": 2, "emotion": "seductive", "facing": "person 2", "pose": "seated", "talking": "yes"}]}
    later = {"shot": "close", "setting": "office", "camera": "static",
             "people": [{"person": 1, "position": "left", "pose": "standing", "talking": True},
                        {"person": 2, "position": "right", "emotion": "shocked", "facing": "person 1", "gesture": "facepalm"}]}
    frames = [{"frame": k, **(first if k <= 5 else later)} for k in range(1, n + 1)]
    return {"summary": "a scene from a famous sitcom", "frames": frames + [{"frame": "soon"}, "a frame with a logo"]}


def leaks(text: str) -> list[str]:
    return [w for w in FORBIDDEN if re.search(rf"\b{w}\b", text, re.IGNORECASE)]


class RulesTest(unittest.TestCase):
    def test_frames_only_inside_the_window_one_every_4_5_s(self):
        t = VN.frame_times(10.0, 40.0)
        self.assertEqual(len(t), 7)
        self.assertTrue(all(10.0 <= x < 40.0 for x in t), t)
        self.assertLessEqual(max(b - a for a, b in zip(t, t[1:])), 4.5)
        self.assertEqual(VN.frame_times(0, 2.0), [1.0])
        self.assertEqual(VN.frame_times(5, 5), [])

    def test_never_more_than_24_frames(self):
        t = VN.frame_times(0, 450.0)
        self.assertEqual(len(t), 24)
        self.assertTrue(all(0 <= x < 450 for x in t))

    def test_anything_outside_the_schema_is_removed(self):
        ranges, redacted = VN.clean_notes(JUNK, 30.0)
        self.assertEqual(len(ranges), 2)
        first, second = ranges
        self.assertEqual((first["start"], first["end"], first["shot"], first["camera"]), (0.0, 5.0, "medium", "pan"))
        self.assertNotIn("setting", first, "a named place is not a setting type")
        self.assertEqual(first["roles"], [{"role": "speaker", "position": "left", "pose": "standing", "facing": "reactor 1",
                                           "emotion": "annoyed"},
                                          {"role": "reactor 1", "pose": "seated"}])
        self.assertEqual((second["end"], second["setting"]), (30.0, "office"), "clamped to the clip")
        self.assertGreaterEqual(redacted, 10)
        self.assertFalse(leaks(json.dumps(ranges)))
        self.assertEqual(VN.clean_notes("not json", 10), ([], 1))

    def test_the_prompt_forbids_identities_and_text(self):
        p = VN.prompt([0.0, 4.5])
        for rule in ("Never output names of real people, actors or characters", "faces", "clothing", "brands or logos",
                     "on-screen text or dialogue", "ORIGINAL"):
            self.assertIn(rule, p)

    def test_cost_estimate(self):
        o = VN.estimate(60, "openai")
        self.assertEqual((o["frames"], o["model"]), (14, "gpt-4.1-mini"))
        self.assertLess(o["usd"], 0.01)
        a = VN.estimate(450, "anthropic", "claude-sonnet-5-5")
        self.assertEqual(a["frames"], 24)
        self.assertLess(a["usd"], 0.05)
        self.assertIn("may cost differently", VN.estimate(60, "openai", "gpt-5")["note"])
        self.assertFalse(VN.estimate(60, "none")["configured"])

    def test_alignment_window_moves_and_summary(self):
        ranges, _ = VN.clean_notes(JUNK, 30.0)
        lines = [{"id": "l1", "start": 0.2, "end": 1.0}, {"id": "l2", "start": 6.0, "end": 8.0}]
        self.assertEqual([r["line_ids"] for r in VN.align(ranges, lines)], [["l1"], ["l2"]])
        self.assertEqual(VN.for_line(ranges, lines[1])["shot"], "close")
        moved = VN.shift(ranges, 10.0, 20.0)       # window moved 10 s earlier, now 20 s long
        self.assertEqual([(r["start"], r["end"]) for r in moved], [(10.0, 15.0), (15.0, 20.0)])
        self.assertEqual(VN.shift(ranges, -40.0, 20.0), [], "notes outside the new window are dropped")
        self.assertEqual(VN.summary(ranges), {"people_count": 2, "setting": "office", "mood": "annoyed"})


class SceneWriterTest(unittest.TestCase):
    LINES = [{"id": "l1", "start": 0.2, "end": 1.0, "speaker": "dan", "text": "Who took my charger?", "words": []},
             {"id": "l2", "start": 6.0, "end": 8.0, "speaker": "dan", "text": "Not me.", "words": []}]

    def test_without_notes_the_simple_split_is_unchanged(self):
        from oddstudio.audio_scenes import build_script, notes_acting
        self.assertEqual(notes_acting(self.LINES, [], ["boss"]), {})
        self.assertEqual(build_script("Ep", self.LINES, ["dan"], ["boss"], None, notes=[]),
                         build_script("Ep", self.LINES, ["dan"], ["boss"], None))

    def test_notes_suggest_shots_and_silent_reactions_never_dialogue(self):
        from oddstudio.audio_scenes import build_script, notes_text
        ranges, _ = VN.clean_notes(JUNK, 30.0)
        s = build_script("Ep", self.LINES, ["dan"], ["boss"], None, known={"dan", "boss"}, notes=ranges)
        lines = [ln for sc in s["scenes"] for ln in sc["lines"]]
        self.assertEqual([(ln["line_id"], ln["text"], ln["start"]) for ln in lines],
                         [("l1", "Who took my charger?", 0.2), ("l2", "Not me.", 6.0)], "dialogue from the transcript")
        self.assertEqual([ln["shot"] for ln in lines], ["medium", "close"])
        self.assertEqual(lines[1]["reactions"], [{"character": "boss", "expression": "shocked"}])
        text = notes_text(self.LINES, ranges)
        self.assertIn("STRONG suggestions", text)   # owner decision 2026-11-21: the accepted plan drives the shots
        self.assertIn("Never change, add or remove dialogue", text)
        self.assertIn("[l1] shot medium; camera pan; speaker: left, standing, facing reactor 1, annoyed", text)
        self.assertEqual(notes_text(self.LINES, []), "")


@unittest.skipUnless(FF and FFP, "FFmpeg and FFprobe are not installed")
class VideoNotesFlowTest(Base):
    with_ffmpeg = True

    def vision(self, answer=None, provider="openai", fail=False):
        self.assertEqual(self.c.put("/api/settings/vision", json={"provider": provider}).status_code, 200)
        self.calls = []
        def stub(cfg, images, question):
            self.calls.append({"provider": cfg["provider"], "images": [Path(i).name for i in images], "question": question})
            if fail:
                raise providers.ProviderError("model down")
            return answer if answer is not None else junk_v2(len(images))
        analysis.set_test_analysis(transcriber=lambda cfg, audio: {
            "provider": "openai", "model": "whisper-1", "language": "en", "duration": 30.0, "text": "Hello there.",
            "segments": [], "words": [{"start": 0.2, "end": 0.5, "word": "Hello"}, {"start": 6.0, "end": 8.0, "word": "there."}]},
            vision=stub)

    def notes_upload(self, eid, clip, **window):
        q = "?hints=true" + "".join(f"&{k}={v}" for k, v in window.items())
        return self.c.put(f"/api/episodes/{eid}/audio{q}", content=clip.read_bytes(), headers={"Content-Type": "video/mp4"})

    def no_media_left(self):
        """No image or video bytes from the upload anywhere: work/uploads is empty, and the episodes' stored files and
        work folders (what the backups contain for them) hold no image or video. The studio's own character art lives
        elsewhere in storage and is not part of this."""
        work = self.env.tmp / "work"
        files = [f for root in (work / "storage" / "episodes", work / "episodes", work / "uploads") if root.exists()
                 for f in root.rglob("*")]
        self.assertTrue(any(f.is_file() for f in files), "the episode's audio is there to be checked")
        for f in files:
            if not f.is_file():
                continue
            head = f.read_bytes()[:12]
            self.assertFalse(head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG"), f"image left: {f}")
            if head[4:8] == b"ftyp" or f.suffix in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
                r = subprocess.run([FFP, "-v", "error", "-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0", str(f)],
                                   capture_output=True, text=True)
                self.assertEqual(r.stdout.strip(), "", f"video stream left in {f}")
        self.assertEqual(self.uploads(), [])

    def test_short_notes_come_only_from_the_window_and_nothing_visual_remains(self):
        self.vision()
        eid = self.create()
        clip = make_media(self.media, "clip.mp4", 70)
        r = self.notes_upload(eid, clip)
        self.assertEqual(r.status_code, 422, "a long Short needs its window with the upload")
        self.assertIn("choose the Short's 60 s window", r.text)
        self.assertEqual(self.notes_upload(eid, clip, start=10, end=40).status_code, 200)
        ran = self.env.run_jobs(["audio_media_prepare", "audio_video_notes", "audio_transcribe"])
        self.assertTrue(all(x[1] == "succeeded" for x in ran), ran)
        call = self.calls[0]
        self.assertEqual(call["provider"], "openai")
        self.assertEqual(len(call["images"]), 30, "notes v2: one frame per second of the 30 s window")
        self.assertIn("frame 1 at 0.5 s", call["question"], "times are the window's (the audio's)")
        self.assertIn("SAME number in every frame", call["question"])
        st = self.state(eid)
        self.assertEqual((st["trim"], st["stage"]), ({"start": 10.0, "end": 40.0}, "audio_labelling"))
        notes = st["video_notes"]
        self.assertEqual((notes["base"], notes["length"], notes["frames"], notes["version"]), (10.0, 30.0, 30, 2))
        q = notes["quality"]
        self.assertEqual((q["people"], q["appearances"], q["frames_sent"], q["frames_used"], q["calls"]),
                         (2, {"1": 30, "2": 30}, 30, 30, 1), "the quality readout")
        self.assertGreaterEqual(q["stripped"], 10)
        self.assertNotIn("people_frames", notes, "the per-person frames stay on the server")
        self.assertGreaterEqual(notes["redacted"], 10)
        self.assertEqual([r["line_ids"] for r in notes["ranges"]], [["l1"], ["l2"]], "aligned to the recorded lines")
        self.assertFalse(leaks(json.dumps(notes)))
        self.assertEqual(st["media_hints"]["people_count"], 2)
        self.no_media_left()

    def test_long_episodes_use_the_whole_clip_in_batches(self):
        self.vision()
        eid = self.create(fmt="long")
        self.assertEqual(self.notes_upload(eid, make_media(self.media, "long.mp4", 120)).status_code, 200)
        self.env.run_jobs(["audio_media_prepare", "audio_video_notes"])
        self.assertEqual([len(c["images"]) for c in self.calls][:2], [50, 11], "1 frame every 2 s; batches of 50, one frame of overlap")
        self.assertLessEqual(len(self.calls), 3, "then at most one set-notes call")
        if len(self.calls) == 3:
            self.assertIn("ORIGINAL, EMPTY 2D cartoon set", self.calls[2]["question"])
            self.assertLessEqual(len(self.calls[2]["images"]), 3 * 4, "a few frames per room")
        self.assertIn("Frame 1 repeats the last frame of the previous batch", self.calls[1]["question"])
        self.assertNotIn("Frame 1 repeats", self.calls[0]["question"])
        self.no_media_left()

    def test_frames_are_deleted_when_the_call_fails_and_no_vision_means_no_upload(self):
        eid = self.create()
        r = self.notes_upload(eid, make_media(self.media, "clip.mp4", 20))
        self.assertEqual(r.status_code, 409, "no API vision provider configured")
        self.assertIn("Codex login is never used", r.text)
        self.vision(fail=True)
        self.assertEqual(self.notes_upload(eid, make_media(self.media, "clip.mp4", 20)).status_code, 200)
        ran = dict((k, s) for k, s, _ in self.env.run_jobs(["audio_media_prepare", "audio_video_notes"]))
        self.assertEqual(ran["audio_video_notes"], "failed")
        self.assertIsNone(self.state(eid)["video_notes"])
        self.no_media_left()

    def test_the_owner_edits_or_clears_the_notes_and_they_follow_the_window(self):
        self.vision()
        eid = self.create()
        self.notes_upload(eid, make_media(self.media, "clip.mp4", 70), start=10, end=40)
        self.env.run_jobs(["audio_media_prepare", "audio_video_notes", "audio_transcribe"])
        ranges = self.state(eid)["video_notes"]["ranges"]
        edited = [{**ranges[0], "shot": "wide"}, ranges[1]]
        r = self.c.put(f"/api/episodes/{eid}/audio/video-notes", json={"ranges": edited})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["video_notes"]["ranges"][0]["shot"], r.json()["video_notes"]["edited"]), ("wide", True))
        bad = [{**ranges[0], "setting": "Central Perk"}]
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/audio/video-notes", json={"ranges": bad}).status_code, 422)
        # the window moves 10 s earlier: the notes move with it, those past the new end are dropped
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/trim", json={"start": 0, "end": 20}).status_code, 200)
        self.env.run_jobs(["audio_transcribe"])
        moved = self.state(eid)["video_notes"]
        self.assertEqual((moved["base"], [(x["start"], x["end"]) for x in moved["ranges"]]), (0.0, [(10.0, 15.0), (15.0, 20.0)]))
        r = self.c.delete(f"/api/episodes/{eid}/audio/video-notes")
        self.assertEqual((r.status_code, r.json()["video_notes"], r.json()["media_hints"]), (200, None, None))

    def test_scenes_use_the_notes_as_suggestions(self):
        self.vision()
        eid = self.create()
        self.notes_upload(eid, make_media(self.media, "clip.mp4", 70), start=10, end=40)
        self.env.run_jobs(["audio_media_prepare", "audio_video_notes", "audio_transcribe"])
        lines = self.state(eid)["lines"]
        for ln in lines:
            ln["speaker"] = "Dan"
        self.c.put(f"/api/episodes/{eid}/audio/lines", json={"lines": lines})
        self.c.post(f"/api/episodes/{eid}/audio/cast", json={"speakers": [{"label": "Dan", "new": {"key": "dan", "name": "Dan"}}]})
        self.c.put(f"/api/episodes/{eid}/audio/silent-cast", json={"members": [{"name": "The boss", "character_key": "character-01"}]})
        r = self.c.post(f"/api/episodes/{eid}/audio/scenes", json={"mode": "simple"})
        self.assertEqual(r.status_code, 409, "nothing is built from the notes before the Reference plan is accepted")
        self.assertIn("Reference plan", r.text)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/reference-plan/accept").status_code, 200)
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/audio/scenes", json={"mode": "simple"}).status_code, 200)
        self.env.run_jobs(["audio_scenes"])
        ep = self.c.get(f"/api/episodes/{eid}").json()
        self.assertIn("with video notes as suggestions", ep["script"]["note"] if "note" in ep["script"] else
                      " ".join(e["message"] for e in ep["events"]) + ep["script"].get("source", ""))
        got = [ln for sc in ep["script"]["content"]["scenes"] for ln in sc["lines"]]
        self.assertEqual([(ln["text"], ln["shot"]) for ln in got], [(lines[0]["text"], "medium"), (lines[1]["text"], "close")])
        self.assertEqual(got[1]["reactions"][0]["character"], "character-01")


if __name__ == "__main__":
    unittest.main()
