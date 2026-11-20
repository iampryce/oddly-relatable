"""Audio-first Stage 1c (line quality): the rules-based line normaliser on the owner's real test transcript (the will
clip), its rules (beats, no dangling end words, speakers kept, no cross-speaker merges), the before/after proposal,
Apply with one-click Undo, cue phrases per episode, and the cut-off last line (end before it, or keep it)."""
import io
import json
import unittest
import wave
from pathlib import Path

from helpers import Env

from oddstudio import analysis
from oddstudio.audio_first import split_lines
from oddstudio.line_normaliser import propose_lines, punctuate, trailing_fragment

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "will_transcript.json").read_text())
DANGLING = {"and", "or", "but", "the", "a", "an", "to", "of", "my", "in", "on", "at", "for", "with", "that", "who"}


def current_lines(fx=FIXTURE):
    return split_lines({"words": fx["words"], "segments": []})


def texts(lines):
    return [ln["text"] for ln in lines]


class WillTranscriptTest(unittest.TestCase):
    """The owner's clip as transcribed: words without punctuation, and the punctuated text."""

    def setUp(self):
        self.before = current_lines()
        self.after = propose_lines(self.before, FIXTURE["text"])

    def test_the_problems_in_the_first_split(self):
        t = texts(self.before)
        self.assertIn("I leave nothing To my niece Winifred", t)          # two thoughts in one line
        self.assertIn("my solicitor Thank you ladies and", t)
        self.assertTrue(any(x.endswith("K Tel") for x in t))              # a phrase cut by the length cap

    def test_expected_beats(self):
        t = texts(self.after)
        expected = [
            "Being of sound mind and in the presence of witnesses, I hereby bequeath my estate as follows.",
            "To my nephew, Ralph,",                                       # a 0.94 s pause after "Ralph,"
            "the most bone-idle lentitudinous toad I've ever had the painful displeasure to know,",
            "I leave my yacht,",
            "the one I used to play with in the bath.",
            "To my mother-in-law, Sydney,",
            "I leave nothing.",
            "To my niece, Winifred,",
            "To my brother, Ronald,",
            "who frittered, nay, squandered every penny he managed to scrounge on cheap alcohol, loose women and K-Tel records,",
            "I leave the contents of my safe deposit box,",
            "To Mr. and Mrs. Crabtree, my next-door neighbours,",           # "Mr." is not a sentence end
            "I leave my house to a large family of Pakistanis.",
            "Failing this condition, the entire estate goes to the man who has helped me more than any other person in my life, my solicitor.",
            "Thank you, ladies and",
        ]
        for line in expected:
            self.assertIn(line, t)
        self.assertEqual(t[:5], expected[:5])

    def test_every_word_kept_once_in_order_with_original_timing(self):
        before_words = [(w["start"], w["end"]) for ln in self.before for w in ln["words"]]
        after_words = [(w["start"], w["end"]) for ln in self.after for w in ln["words"]]
        self.assertEqual(after_words, before_words)
        for ln in self.after:
            self.assertEqual((ln["start"], ln["end"]), (ln["words"][0]["start"], ln["words"][-1]["end"]))

    def test_no_line_holds_two_thoughts_or_ends_on_a_dangling_word(self):
        for ln in self.after[:-1]:                                           # the last line is the flagged fragment
            last = ln["text"].split()[-1].strip(",.").lower()
            self.assertNotIn(last, DANGLING, ln["text"])
            self.assertNotRegex(ln["text"], r"\w (To my|I leave) ", ln["text"])

    def test_trailing_fragment_is_flagged(self):
        frag = trailing_fragment(self.after, FIXTURE["text"], FIXTURE["duration"])
        self.assertEqual(frag["text"], "Thank you, ladies and")
        self.assertEqual(len(frag["reasons"]), 3)                          # "and", no final full stop, 4.5 s of audio after
        self.assertAlmostEqual(frag["audio_after"], 4.51, places=2)


class RulesTest(unittest.TestCase):
    @staticmethod
    def words(spec, t0=0.0, gap=0.05, dur=0.3):
        """spec: 'Hello there|1.2|friend' — '|x|' inserts a pause of x seconds."""
        out, t = [], t0
        for tok in spec.split():
            if tok.startswith("|"):
                t += float(tok.strip("|")) - gap
                continue
            out.append({"start": round(t, 3), "end": round(t + dur, 3), "word": tok})
            t += dur + gap
        return out

    def line(self, i, ws, speaker=""):
        return {"id": f"l{i}", "start": ws[0]["start"], "end": ws[-1]["end"], "text": " ".join(w["word"] for w in ws),
                "speaker": speaker, "words": ws}

    def test_speakers_are_kept_and_never_merged(self):
        a = self.words("We need to talk about the")
        b = self.words("what now", t0=a[-1]["end"] + 0.05)
        out = propose_lines([self.line(1, a, "dan"), self.line(2, b, "kim")], "We need to talk about the. What now?")
        self.assertEqual([ln["speaker"] for ln in out], ["dan", "kim"])
        self.assertTrue(all(len({w for w in ln["from"]}) == 1 for ln in out))
        # dan's line keeps its (dangling) last word: words never move to another speaker's line
        self.assertEqual(out[0]["text"].split()[-1].strip(".").lower(), "the")
        # a one-word line of a different speaker is never merged into a neighbour
        c = self.words("Okay", t0=b[-1]["end"] + 0.05)
        out = propose_lines([self.line(1, a, "dan"), self.line(2, c, "kim"), self.line(3, b, "dan")], "")
        self.assertEqual([ln["speaker"] for ln in out], ["dan", "kim", "dan"])

    def test_dangling_words_move_to_the_next_line(self):
        ws = self.words("I went to the shop and |1.2| bought bread")
        out = propose_lines([self.line(1, ws)], "")
        self.assertEqual(texts(out), ["I went to the shop", "and bought bread"])

    def test_short_fragment_joins_its_neighbour(self):
        ws = self.words("Right |1.2| so we go now and never come back")
        out = propose_lines([self.line(1, ws)], "")
        self.assertEqual(texts(out), ["Right so we go now and never come back"])

    def test_pauses_split_at_punctuation_or_when_long_not_mid_phrase(self):
        ws = self.words("he managed to |0.5| scrounge some money")
        self.assertEqual(len(propose_lines([self.line(1, ws)], "he managed to scrounge some money")), 1)
        ws = self.words("To my nephew Ralph |0.6| the laziest toad alive")
        out = propose_lines([self.line(1, ws)], "To my nephew, Ralph, the laziest toad alive.", cues=[])
        self.assertEqual(texts(out), ["To my nephew, Ralph,", "the laziest toad alive."])
        ws = self.words("and then the cat |1.2| sat down quietly")
        self.assertEqual(len(propose_lines([self.line(1, ws)], "")), 2)

    def test_cue_phrases_are_editable(self):
        ws = self.words("I said yes I leave tomorrow morning early")
        text = "I said yes I leave tomorrow morning early"
        self.assertEqual(len(propose_lines([self.line(1, ws)], text)), 2)                    # default cue "I leave"
        self.assertEqual(len(propose_lines([self.line(1, ws)], text, cues=[])), 1)          # no cues
        self.assertEqual(texts(propose_lines([self.line(1, ws)], text, cues=["tomorrow"])),
                         ["I said yes I leave", "tomorrow morning early"])

    def test_long_line_is_split_at_its_comma(self):
        ws = self.words(" ".join(f"w{i}" for i in range(20)) + " " + " ".join(f"x{i}" for i in range(20)), dur=0.35)
        text = " ".join(f"w{i}" for i in range(20)) + ", " + " ".join(f"x{i}" for i in range(20)) + "."
        out = propose_lines([self.line(1, ws)], text)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["text"].endswith("w19,"))

    def test_punctuation_alignment_rejoins_hyphenated_words(self):
        ws = self.words("my mother in law and K Tel records")
        out = punctuate(ws, "My mother-in-law, and K-Tel records.")
        from oddstudio.line_normaliser import line_text
        self.assertEqual(line_text(out), "my mother-in-law, and K-Tel records.")

    def test_complete_endings_are_not_flagged(self):
        ws = self.words("Thank you all")
        ln = [self.line(1, ws)]
        self.assertIsNone(trailing_fragment(ln, "Thank you all.", ws[-1]["end"] + 0.3))
        self.assertIsNone(trailing_fragment(ln, "Thank you all.", ws[-1]["end"] + 5.0), "applause after a full stop")
        self.assertIsNotNone(trailing_fragment(ln, "Thank you all", ws[-1]["end"] + 0.3), "no final full stop")


def wav_bytes(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class Stage1cApiTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        analysis.set_test_analysis(transcriber=lambda cfg, audio: {
            "provider": FIXTURE["provider"], "model": FIXTURE["model"], "text": FIXTURE["text"], "duration": FIXTURE["duration"],
            "language": "en", "segments": [], "words": FIXTURE["words"]})
        ep = self.c.post("/api/audio-episodes", json={"title": "Will", "format": "long", "rights_confirmed": True,
                                                       "rights_source": "other"}).json()
        self.eid = ep["id"]
        self.assertEqual(self.c.put(f"/api/episodes/{self.eid}/audio", content=wav_bytes(),
                                    headers={"Content-Type": "audio/wav"}).status_code, 200)
        self.assertEqual(self.env.run_jobs(["audio_transcribe"])[0][1], "succeeded")

    def tearDown(self):
        analysis.set_test_analysis()
        self.env.close()

    def st(self):
        return self.c.get(f"/api/episodes/{self.eid}/audio").json()

    def test_proposal_saves_nothing_then_apply_and_undo(self):
        st = self.st()
        self.assertEqual(len(st["lines"]), 24)
        self.assertEqual(st["fragment"]["text"], "my solicitor Thank you ladies and")
        r = self.c.post(f"/api/episodes/{self.eid}/audio/normalise", json={})
        self.assertEqual(r.status_code, 200, r.text)
        prop = r.json()
        self.assertTrue(prop["changed"])
        self.assertEqual(len(prop["current"]), 24)
        self.assertIn("To my niece, Winifred,", texts(prop["proposal"]))
        self.assertEqual(prop["fragment"]["text"], "Thank you, ladies and")
        self.assertEqual(len(self.st()["lines"]), 24, "a proposal changes nothing")
        # the owner edits the proposal, then applies it
        lines = prop["proposal"]
        lines[0]["speaker"] = "testator"
        r = self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": lines, "keep_previous": True})
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()
        self.assertEqual(len(st["lines"]), len(lines))
        self.assertEqual(st["lines"][0]["speaker"], "testator")
        self.assertTrue(st["can_undo"])
        st = self.c.post(f"/api/episodes/{self.eid}/audio/lines/undo").json()
        self.assertEqual(len(st["lines"]), 24)
        self.assertFalse(st["can_undo"])
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/audio/lines/undo").status_code, 409)

    def test_an_ordinary_save_clears_undo(self):
        prop = self.c.post(f"/api/episodes/{self.eid}/audio/normalise", json={}).json()["proposal"]
        self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": prop, "keep_previous": True})
        lines = self.st()["lines"]
        for ln in lines:
            ln["speaker"] = "testator"                                     # bulk speaker, saved normally
        st = self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": lines}).json()
        self.assertFalse(st["can_undo"], "Undo would otherwise drop the speaker labels")
        self.assertEqual(st["unlabelled_lines"], 0)

    def test_cue_phrases_are_stored_per_episode(self):
        self.assertEqual(self.st()["cues"], ["To my", "I leave", "And finally", "Failing", "Thank you"])
        prop = self.c.post(f"/api/episodes/{self.eid}/audio/normalise", json={"cues": ["To my", " ", "To my"]}).json()
        self.assertEqual(prop["cues"], ["To my"])
        self.assertEqual(self.st()["cues"], ["To my"])
        # "…to know, | I leave my yacht" has only a 0.22 s pause: without the "I leave" cue it stays one line
        self.assertNotIn("I leave my yacht,", texts(prop["proposal"]))
        self.assertTrue(any("to know, I leave my yacht," in t for t in texts(prop["proposal"])))

    def test_fragment_end_before_and_undo(self):
        prop = self.c.post(f"/api/episodes/{self.eid}/audio/normalise", json={}).json()["proposal"]
        self.c.put(f"/api/episodes/{self.eid}/audio/lines", json={"lines": prop})
        st = self.st()
        self.assertEqual(st["fragment"]["text"], "Thank you, ladies and")
        st = self.c.post(f"/api/episodes/{self.eid}/audio/fragment", json={"action": "end_before"}).json()
        self.assertEqual(texts(st["lines"])[-1], "Failing this condition, the entire estate goes to the man who has helped me more than any other person in my life, my solicitor.")
        self.assertEqual(st["end_at"], 145.94)
        self.assertIsNone(st["fragment"])
        self.assertTrue(st["can_undo"])
        st = self.c.post(f"/api/episodes/{self.eid}/audio/lines/undo").json()
        self.assertEqual(texts(st["lines"])[-1], "Thank you, ladies and")
        self.assertIsNone(st["end_at"])

    def test_fragment_keep(self):
        st = self.c.post(f"/api/episodes/{self.eid}/audio/fragment", json={"action": "keep"}).json()
        self.assertIsNone(st["fragment"])
        self.assertEqual(len(st["lines"]), 24)
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/audio/fragment", json={"action": "keep"}).status_code, 409)

    def test_gates(self):
        self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/audio/fragment", json={"action": "delete"}).status_code, 422)
        from oddstudio.db import new_session
        from oddstudio.models import Episode
        with new_session() as s:
            s.get(Episode, self.eid).stage = "audio_transcribing"
            s.commit()
        for path in ("normalise", "lines/undo", "fragment"):
            body = {"action": "keep"} if path == "fragment" else {}
            self.assertEqual(self.c.post(f"/api/episodes/{self.eid}/audio/{path}", json=body).status_code, 409, path)


if __name__ == "__main__":
    unittest.main()
