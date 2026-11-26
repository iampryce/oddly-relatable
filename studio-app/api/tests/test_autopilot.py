"""Guided steps 10-11 and "Make whole episode" (assembly.py, clip_qa.py, autopilot.py, shot_chat final:/redo_shot).

Covered: frame-exact segment math (no drift over 41 shots, the owner's round(next*25) - round(start*25) rule), the
talking result's settle frames dropped before the hold/stretch, only APPROVED sources (an unapproved newer result is
never used; a shot without an approved clip falls back to its approved still, listed as "still, not animated"; a shot
with neither blocks the assembly), one real FFmpeg assembly with the exact frame count and the original audio, the final
cut waiting for the owner's click; the quality check's answer parsed into the chat's own proposals (unknown ones left
out), its provider choice (paid tier / ticked free tier / neither), its 409 without the confirmed price and its result
posted into the shot's thread; the autopilot's budget gate (pauses BEFORE an action that would pass the budget or the
monthly GPU cap; spent never above the budget), its approval gates (it waits and never approves: masters, the final
cut), a failed job pausing the run, the redo limit, the GPU kept between GPU steps and released while waiting, Stop
terminating the GPU, and the providers summary (plain notes, never a key value). No network and no paid call: Gemini is
a mocked transport, WaveSpeed a stub, RunPod untouched, and only fake credentials are used."""
import json
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from PIL import Image

from helpers import Env
from test_stick_pipeline import Stub, png_bytes, uninstall

from oddstudio import acting_analysis as AA
from oddstudio import assembly as A
from oddstudio import autopilot as AP
from oddstudio import clip_qa as Q
from oddstudio import comfy_session as CS
from oddstudio import shot_chat as SC

FFMPEG, FFPROBE = "/usr/bin/ffmpeg", "/usr/bin/ffprobe"
HAVE_FFMPEG = Path(FFMPEG).exists()
FAKE = {"gemini_api_key": "fake-gemini-credential-for-tests", "openai_api_key": "fake-openai-credential-for-tests",
        "wavespeed_api_key": "fake-wavespeed-credential-for-tests"}


def wav(path: Path, seconds: float) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))
    return path


def clip(path: Path, frames: int, fps: int, size=(320, 180)) -> Path:
    if HAVE_FFMPEG:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size[0]}x{size[1]}:rate={fps}",
                        "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)
    else:
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video")
    return path


def count_frames(path: Path) -> int:
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return int(r.stdout.strip())


# ================================================================== pure: frame-exact segments and clip fitting
class SegmentMathTest(unittest.TestCase):
    def test_41_shots_never_drift(self):
        # shot starts that land on half frames and odd fractions (the Episode 15 case)
        starts = [0.0] + [round(i * 1.37 + (0.02 if i % 3 else 0.06) + (0.0 if i % 2 else 0.02), 3) for i in range(1, 41)]
        end = 57.31
        segs = A.segment_frames(starts, end)
        self.assertEqual(len(segs), 41)
        self.assertEqual(segs[0][0], 0)                                   # the first shot starts at frame 0
        for i in range(1, 41):
            self.assertEqual(segs[i][0], round(starts[i] * 25), i)        # every shot starts on its own absolute frame
            self.assertEqual(segs[i][0], segs[i - 1][0] + segs[i - 1][1])  # contiguous: no gap, no overlap
        self.assertEqual(sum(n for _, n in segs), round(end * 25))        # the whole recording, to the frame
        # the naive way (each shot's own length rounded) drifts; the absolute way cannot
        naive = sum(round((b - a) * 25) for a, b in zip(starts, starts[1:] + [end]))
        self.assertNotEqual(naive, round(end * 25), "the test data must show the drift the rule prevents")

    def test_every_shot_gets_a_frame_and_the_last_runs_to_the_end(self):
        segs = A.segment_frames([0.0, 0.01, 0.015, 3.0], 2.0)              # tiny shots and an end before the last start
        self.assertTrue(all(n >= 1 for _, n in segs))
        self.assertEqual(segs[-1][0], 75)
        self.assertEqual(A.segment_frames([], 3.0), [])

    def test_trim_then_stretch_or_hold_or_cut(self):
        # a talking result: 33 frames at 16 fps, the first 2 dropped -> 31 frames = 1.9375 s
        f = A.fit_clip(33, 16, 2, 48)                                      # slot 1.92 s: a touch longer -> nothing to stretch
        self.assertEqual((f["stretch"], f["held_s"]), (1.0, 0.0))
        f = A.fit_clip(33, 16, 2, 60)                                      # slot 2.4 s: slowed (1.24x), no hold
        self.assertAlmostEqual(f["stretch"], round(2.4 / (31 / 16), 4))
        self.assertEqual(f["held_s"], 0.0)
        self.assertIn("slowed", f["warnings"][0])
        f = A.fit_clip(33, 16, 2, 100)                                     # slot 4 s: at most 1.4x, then the last frame held
        self.assertEqual(f["stretch"], 1.4)
        self.assertAlmostEqual(f["held_s"], round(4.0 - (31 / 16) * 1.4, 3))
        self.assertIn("held", f["warnings"][0])
        f = A.fit_clip(77, 16, 2, 25)                                      # longer than the shot: cut at the end
        self.assertGreater(f["cut_s"], 0)
        self.assertIn("cut", f["warnings"][0])
        vf = A.clip_filter(2, 1.24, 60, 1280, 720)
        self.assertTrue(vf.startswith("trim=start_frame=2,setpts=PTS-STARTPTS,setpts=1.2400*PTS,fps=25,"), vf)
        self.assertIn("tpad=stop_mode=clone", vf)
        self.assertNotIn("trim=", A.clip_filter(0, 1.0, 50, 1280, 720))

    def test_overlay_graph(self):
        g, last = A.overlay_graph([(0.2, 1.8), (2.0, 3.0)], True)
        self.assertEqual(last, "l1")
        self.assertIn("[0:v][2:v]overlay=0:0[b0]", g)
        self.assertIn("[b0][3:v]overlay=0:0:enable='between(t,0.200,1.800)'[l0]", g)
        self.assertIn("[l0][4:v]overlay", g)
        g, last = A.overlay_graph([(0.2, 1.8)], False)
        self.assertTrue(g.startswith("[0:v][2:v]overlay"))


# ================================================================== the episode fixture
class Base(unittest.TestCase):
    def setUp(self):
        os.environ["FFMPEG"], os.environ["FFPROBE"] = (FFMPEG, FFPROBE) if HAVE_FFMPEG else ("", "")
        self.env = Env().login()
        self.c = self.env.client
        from oddstudio.db import new_session
        from oddstudio.models import Asset, Character, Episode, Setting
        from oddstudio.storage import storage
        tmp = Path(tempfile.mkdtemp())
        with new_session() as db:
            db.add_all([Character(key="mort", name="Mortimer", visual_description="round wire glasses"),
                        Character(key="sid", name="Sidney", visual_description="thin pencil moustache"),
                        Character(key="win", name="Winifred", visual_description="grey bun")])

            def asset(name, src, kind, ctype):
                storage().put_file(f"episodes/x/{name}", src, ctype)
                a = Asset(kind=kind, label=name, storage_key=f"episodes/x/{name}", content_type=ctype, size=src.stat().st_size)
                db.add(a)
                db.flush()
                return a
            still_p = tmp / "still.png"
            Image.new("RGB", (1280, 720), (90, 120, 90)).save(still_p)
            still = asset("still.png", still_p, "still", "image/png")
            audio = asset("audio.wav", wav(tmp / "a.wav", 8.0), "audio", "audio/wav")
            t_old = asset("talk-old.mp4", clip(tmp / "t1.mp4", 33, 16), "video", "video/mp4")
            t_new = asset("talk-new.mp4", clip(tmp / "t2.mp4", 33, 16), "video", "video/mp4")
            r2 = asset("react2.mp4", clip(tmp / "r2.mp4", 52, 25, (1280, 720)), "video", "video/mp4")
            r3 = asset("react3.mp4", clip(tmp / "r3.mp4", 60, 25, (1280, 720)), "video", "video/mp4")
            tr = {"person_map": {"S1": "mort"}, "lines": [
                {"id": "l1", "start": 0.2, "end": 1.8, "text": "I leave it all", "speaker": "S1",
                 "words": [{"start": 0.2, "end": 0.5, "word": "I"}, {"start": 0.6, "end": 1.8, "word": "leave"}]}]}
            ep = Episode(title="Assemble me", audio_asset_id=audio.id, audio_transcript=tr, dialogue_display="none")
            db.add(ep)
            db.flush()
            self.eid, self.still, self.audio = ep.id, still.id, audio.id
            v = {"asset_id": still.id, "at": 0, "source": "still", "note": ""}
            # 1: Mortimer talks (approved still); 2: Sidney close-up; 3: the family wide; 4: the room only
            db.add(Setting(key=f"shotframes:{ep.id}", value={"sides": {"study": ["mort"], "family": ["sid", "win"]}, "shots": [
                {"index": 1, "t0": 0.0, "t1": 1.98, "side": "study", "people": ["mort"], "shot": "medium", "versions": [v],
                 "chosen": still.id, "approved": True},
                {"index": 2, "t0": 1.98, "t1": 4.02, "side": "family", "people": ["sid"], "shot": "close", "versions": [v],
                 "chosen": still.id, "approved": True},
                {"index": 3, "t0": 4.02, "t1": 6.5, "side": "family", "people": ["sid", "win"], "shot": "wide", "versions": [v],
                 "chosen": still.id, "approved": True},
                {"index": 4, "t0": 6.5, "t1": 8.0, "side": "study", "people": [], "shot": "wide", "versions": [v],
                 "chosen": still.id, "approved": True}]}))
            rec = lambda rid, a: {"id": rid, "asset_id": a.id, "frames": 31, "pieces": [33], "trim_start_frames": 2, "at": 0}  # noqa: E731
            db.add(Setting(key=f"talkshots:{ep.id}", value={"shots": {"1": {"renders": [rec("new", t_new), rec("old", t_old)],
                                                                             "approved": "old"}}}))
            db.add(Setting(key=f"reactions:{ep.id}", value={"shots": {
                "2": {"clips": [{"id": "c2", "asset_id": r2.id, "frames": 52, "fps": 25}], "approved": "c2"},
                "3": {"clips": [{"id": "c3", "asset_id": r3.id, "frames": 60, "fps": 25}], "approved": None}}}))
            db.commit()

    def tearDown(self):
        AA.set_test_transport(None)
        uninstall()
        self.env.close()
        os.environ.pop("FFMPEG", None)
        os.environ.pop("FFPROBE", None)

    def db(self):
        from oddstudio.db import new_session
        return new_session()

    def ep(self, db):
        from oddstudio.models import Episode
        return db.get(Episode, self.eid)

    def secrets(self, **vals):
        from oddstudio.secrets_store import put_secrets
        with self.db() as db:
            put_secrets(db, vals)

    def settings(self, section, **vals):
        r = self.c.put(f"/api/settings/{section}", json=vals)
        self.assertEqual(r.status_code, 200, r.text)


# ================================================================== assembly
class AssemblyTest(Base):
    def test_only_approved_sources_and_still_holds(self):
        p = self.c.get(f"/api/episodes/{self.eid}/assembly").json()
        rows = {r["index"]: r for r in p["rows"]}
        self.assertEqual(rows[1]["source"], "talking")
        self.assertEqual(rows[1]["clip_id"], "old")                       # the approved result, not the newer one
        self.assertEqual(rows[1]["trim_start_frames"], 2)
        self.assertEqual(rows[2]["source"], "reaction")
        self.assertEqual(rows[3]["source"], "still")                       # its clip waits for approval: the still holds
        self.assertEqual(rows[3]["label"], "still, not animated")
        self.assertIn("waiting for your approval", rows[3]["warnings"][0])
        self.assertEqual(rows[4]["source"], "still")
        self.assertEqual([r["start_frame"] for r in p["rows"]], [0, round(1.98 * 25), round(4.02 * 25), round(6.5 * 25)])
        self.assertEqual(p["size"], [720, 1280])                           # a 9:16 episode
        self.assertEqual(p["missing"], [])
        self.assertEqual(p["cost"]["label"], "Free (made on the studio server with FFmpeg)")

    def test_a_shot_without_an_approved_source_blocks(self):
        from oddstudio import shot_frames as SF
        with self.db() as db:
            v = SF.stored(db, self.eid)
            v["shots"][3]["approved"] = False
            SF.save(db, self.eid, v)
            db.commit()
        p = self.c.get(f"/api/episodes/{self.eid}/assembly").json()
        self.assertEqual(p["missing"], [4])
        r = self.c.post(f"/api/episodes/{self.eid}/assembly")
        self.assertEqual(r.status_code, 409)
        self.assertIn("shot(s) 4", r.json()["detail"])

    @unittest.skipUnless(HAVE_FFMPEG, "needs FFmpeg")
    def test_real_assembly_is_frame_exact_and_waits_for_the_owner(self):
        r = self.c.post(f"/api/episodes/{self.eid}/assembly")
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["episode_assembly"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        v = self.c.get(f"/api/episodes/{self.eid}/assembly").json()
        cut = v["cuts"][0]
        self.assertEqual(cut["frames"], 200)                               # 8.0 s of recording at 25 fps
        self.assertIsNone(v["approved"])                                   # never approved by itself
        self.assertFalse(cut["approved"])
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as db:
            a = db.get(Asset, cut["asset_id"])
            out = storage().get_to_file(a.storage_key, Path(tempfile.mkdtemp()) / "final.mp4")
        self.assertEqual(count_frames(out), 200)
        streams = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(out)],
                                 capture_output=True, text=True).stdout
        s = json.loads(streams)["streams"]
        self.assertIn("audio", [x["codec_type"] for x in s])               # the original recording
        vid = next(x for x in s if x["codec_type"] == "video")
        self.assertEqual((vid["width"], vid["height"]), (720, 1280))
        r = self.c.post(f"/api/episodes/{self.eid}/assembly/approve", json={"cut_id": cut["id"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["approved"], cut["id"])


# ================================================================== quality check
GOOD = {"issues": [
    {"t": 1.2, "kind": "style", "severity": "clear", "what": "A nose appears on Mortimer.",
     "fix": {"type": "rerender_talking_shot", "prompt": "Mortimer speaks; no nose, small mouth."}},
    {"t": 0.4, "kind": "camera", "severity": "possible", "what": "A slight zoom.", "fix": {"type": "redo_still"}},
    {"t": 9.0, "kind": "weird", "severity": "big", "what": "Odd blink.", "fix": None},
    {"t": 1.0, "kind": "mouth", "severity": "possible", "what": "", "fix": None}],
    "summary": "One clear problem."}


class QualityParseTest(unittest.TestCase):
    def test_issues_become_chat_proposals(self):
        res = Q.parse(json.dumps(GOOD), "talk", "1", SC.ALLOWED["talk"], 2.0)
        self.assertEqual(len(res["issues"]), 3)                            # the one without words is dropped
        first = res["issues"][0]
        self.assertEqual((first["severity"], first["kind"], first["t"]), ("clear", "style", 1.2))
        self.assertEqual(first["fix"], {"type": "rerender_talking_shot", "prompt": "Mortimer speaks; no nose, small mouth."})
        cam = next(i for i in res["issues"] if i["kind"] == "camera")
        self.assertIsNone(cam["fix"])                                      # not a change a talking shot's chat can make
        self.assertIn("not a change this step can make", cam["fix_left_out"])
        odd = next(i for i in res["issues"] if i["what"] == "Odd blink.")
        self.assertEqual((odd["kind"], odd["severity"], odd["t"]), ("other", "possible", 2.0))   # clamped, normalised
        self.assertEqual(Q.best_fix(res)["type"], "rerender_talking_shot")
        self.assertEqual(Q.clear_fix(res)["type"], "rerender_talking_shot")
        only_possible = Q.parse(json.dumps({"issues": [dict(GOOD["issues"][0], severity="possible")]}), "talk", "1",
                                SC.ALLOWED["talk"], 2.0)
        self.assertIsNone(Q.clear_fix(only_possible))                      # the autopilot redoes only clear problems
        self.assertIsNotNone(Q.best_fix(only_possible))                    # the owner still gets the proposal
        self.assertIn("1.2 s [clear] style", Q.message_text(res))
        with self.assertRaises(ValueError):
            Q.parse("no json here", "talk", "1", SC.ALLOWED["talk"], 2.0)
        react = Q.parse(json.dumps({"issues": [{"t": 1, "kind": "mouth", "severity": "clear", "what": "mouth moves",
                                                "fix": {"type": "reanimate_shot"}}]}), "clip", "2",
                        ("note_only", "reanimate_shot"), 2.0)
        self.assertEqual(react["issues"][0]["fix"], {"type": "reanimate_shot"})

    def test_frames_and_estimate(self):
        self.assertEqual(Q.frame_times(2.0), [0.12, 0.38, 0.62, 0.88, 1.12, 1.38, 1.62, 1.88])
        self.assertEqual(Q.frame_times(0.5), [0.12, 0.38])
        prov = {"model": "m", "usd_in": 2.0, "usd_out": 12.0, "free": False}
        e = Q.estimate(prov, 9, 2.0, "x" * 350)
        self.assertEqual(e["input_tokens"], 9 * 258 + 600 + 100)
        self.assertEqual(e["usd_max"], round(e["input_tokens"] * 2 / 1e6 + 4000 * 12 / 1e6, 4))
        self.assertEqual(Q.estimate({**prov, "free": True}, 9, 2.0, "x")["usd_max"], 0.0)


class QualityApiTest(Base):
    def test_provider_choice(self):
        with self.db() as db:
            self.assertFalse(Q.provider(db)["ready"])
            self.assertIn("no key", Q.provider(db)["note"])
        self.secrets(gemini_api_key=FAKE["gemini_api_key"])
        with self.db() as db:
            p = Q.provider(db)
            self.assertFalse(p["ready"])
            self.assertIn("free tier", p["note"])
        self.settings("quality", qa_use_free_tier=True)
        with self.db() as db:
            p = Q.provider(db)
            self.assertEqual((p["ready"], p["free"], p["model"]), (True, True, "gemini-3.5-flash"))
            self.assertIn("improve its models", p["label"])
        self.settings("quality", qa_paid_tier=True)
        with self.db() as db:
            p = Q.provider(db)
            self.assertEqual((p["ready"], p["free"], p["model"]), (True, False, "gemini-3.1-pro-preview"))
        r = self.c.put("/api/settings/quality", json={"max_redos_per_shot": 9})
        self.assertEqual(r.status_code, 422, r.text)

    @unittest.skipUnless(HAVE_FFMPEG, "needs FFmpeg for the frames")
    def test_check_posts_into_the_shots_thread(self):
        self.secrets(gemini_api_key=FAKE["gemini_api_key"])
        self.settings("quality", qa_paid_tier=True)
        sent = []

        def handler(request):
            body = json.loads(request.content)
            sent.append((str(request.url), dict(request.headers), body))
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}],
                                             "usageMetadata": {"promptTokenCount": 3000, "candidatesTokenCount": 200}})
        AA.set_test_transport(httpx.MockTransport(handler))
        q = self.c.get(f"/api/episodes/{self.eid}/quality").json()
        self.assertEqual([(c["shot"], c["step"], c["clip_id"]) for c in q["clips"]], [(1, "talk", "old"), (2, "clip", "c2"), (3, "clip", "c3")])
        est = q["estimate_unchecked"]
        r = self.c.post(f"/api/episodes/{self.eid}/quality/check", json={"shots": [1]})
        self.assertEqual(r.status_code, 409)                               # the price must be confirmed
        self.assertEqual(sent, [])
        one = next(c for c in q["clips"] if c["shot"] == 1)["estimate"]["usd_max"]
        r = self.c.post(f"/api/episodes/{self.eid}/quality/check", json={"shots": [1], "confirm_usd": one})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["clip_qa"])
        self.assertEqual(ran[-1][1], "succeeded", ran)
        self.assertEqual(len(sent), 1)
        url, headers, body = sent[0]
        self.assertIn("gemini-3.1-pro-preview:generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], FAKE["gemini_api_key"])
        kinds = [p.get("inline_data", {}).get("mime_type") for p in body["contents"][0]["parts"] if "inline_data" in p]
        self.assertIn("video/mp4", kinds)                                  # small clip: sent whole
        self.assertGreaterEqual(kinds.count("image/jpeg"), 4)              # and its frames
        self.assertIn("Mortimer speaks at", body["contents"][0]["parts"][-1]["text"])
        t = self.c.get("/api/shot-chat/thread", params={"step": "talk", "item": "1", "episode_id": self.eid}).json()
        m = t["messages"][-1]
        self.assertEqual((m["role"], m["author"]), ("assistant", "Quality check"))
        self.assertIn("[clear] style", m["text"])
        self.assertEqual(m["proposal"]["type"], "rerender_talking_shot")
        self.assertEqual(m["proposal_status"], "pending")                  # the owner applies it (with its price)
        self.assertIsNotNone(m["cost"]["usd"])
        q = self.c.get(f"/api/episodes/{self.eid}/quality").json()
        self.assertEqual(len(next(c for c in q["clips"] if c["shot"] == 1)["check"]["issues"]), 3)
        self.assertNotIn(FAKE["gemini_api_key"], json.dumps(q))
        self.assertIsNotNone(est)


# ================================================================== the final cut's chat
class FinalChatTest(Base):
    def test_final_thread_and_redo_shot(self):
        t = self.c.get("/api/shot-chat/thread", params={"step": "final", "item": str(self.eid), "episode_id": self.eid})
        self.assertEqual(t.status_code, 200, t.text)
        self.assertEqual(t.json()["proposals"], ["note_only", "redo_shot"])
        bad = self.c.get("/api/shot-chat/thread", params={"step": "final", "item": "999", "episode_id": self.eid})
        self.assertEqual(bad.status_code, 422)
        p = SC.validate_proposal("final", str(self.eid), {"type": "redo_shot", "shot": 4, "prompt": "brighter room"})
        self.assertEqual(p, {"type": "redo_shot", "shot": 4, "prompt": "brighter room"})
        with self.assertRaises(ValueError):
            SC.validate_proposal("final", str(self.eid), {"type": "rerender_talking_shot"})
        with self.db() as db:
            ep = self.ep(db)
            self.assertEqual([SC.shot_kind(db, ep, n) for n in (1, 2, 3, 4)], ["talking", "reaction", "reaction", "still"])
            cx = SC.build_context(db, SC.Ref(episode_id=self.eid, step="final", item=str(self.eid)))
            self.assertEqual([s["shot"] for s in cx["settings"]["shots"]], [1, 2, 3, 4])
            self.assertEqual(SC.redo_shot_cost(db, self.eid, 4)["usd"], 0.04)        # a new still: one image


# ================================================================== the autopilot
class AutopilotBase(Base):
    def setUp(self):
        super().setUp()
        self.stub = Stub().install()
        self.stops = []
        self._stop = CS.stop
        CS.stop = lambda db, reason: self.stops.append(reason) or []
        self.secrets(wavespeed_api_key=FAKE["wavespeed_api_key"])
        self.set_c3(True)            # every clip approved: no GPU work left unless a test says otherwise

    def tearDown(self):
        CS.stop = self._stop
        super().tearDown()

    def set_c3(self, approved: bool):
        from oddstudio import reactions as R
        with self.db() as db:
            rv = R.stored(db, self.eid)
            rv["shots"]["3"]["approved"] = "c3" if approved else None
            R.save(db, self.eid, rv)
            db.commit()

    def state(self):
        return self.c.get(f"/api/episodes/{self.eid}/autopilot").json()

    def start(self, budget, confirm=None, **kw):
        return self.c.post(f"/api/episodes/{self.eid}/autopilot/start",
                           json={"budget_usd": budget, "confirm_usd": budget if confirm is None else confirm, **kw})

    def only_masters_left(self):
        """Two episode characters without masters, a style reference: every other step has nothing to do."""
        from oddstudio.models import Character
        r = self.c.put("/api/stick/style-reference/upload", content=png_bytes(), headers={"Content-Type": "image/png"})
        self.assertEqual(r.status_code, 201, r.text)
        with self.db() as db:
            db.add_all([Character(key="ann", name="Ann", visual_description="a red cap", scope="episode", episode_id=self.eid),
                         Character(key="bob", name="Bob", visual_description="a green bow tie", scope="episode", episode_id=self.eid)])
            db.commit()

    def jobs(self, kind=None):
        from oddstudio.models import Job
        with self.db() as db:
            q = db.query(Job)
            if kind:
                q = q.filter_by(kind=kind)
            return [(j.kind, j.status, (j.payload or {}).get("by")) for j in q.order_by(Job.id)]

    def approvals(self):
        from oddstudio.models import Event
        with self.db() as db:
            return [e.message for e in db.query(Event).filter_by(kind="approval")]


class AutopilotBudgetTest(AutopilotBase):
    def test_start_needs_the_budget_confirmed(self):
        self.only_masters_left()
        r = self.start(1.0, confirm=0.5)
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm your budget of $1.00", r.json()["detail"])
        r = self.c.post(f"/api/episodes/{self.eid}/autopilot/start", json={"budget_usd": 1.0})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.jobs(), [])

    def test_pauses_before_passing_the_budget_and_never_passes_it(self):
        self.only_masters_left()
        r = self.start(0.10)                                               # one master run is 2 x $0.04 = $0.08
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        self.assertEqual(s["status"], "paused")
        self.assertEqual(len(self.jobs("stick_master")), 1)                 # Ann's started, Bob's would pass the budget
        self.assertIn("Paused before \"Master candidates for Bob\"", s["message"])
        self.assertIn("$0.02 of your $0.10 budget is left", s["message"])
        self.assertAlmostEqual(s["spent_usd"], 0.08)
        self.assertLessEqual(s["spent_usd"], s["budget_usd"])
        self.assertTrue(self.jobs("stick_master")[0][2].startswith("Autopilot"))
        # a resume without a bigger budget pauses again at once and starts nothing
        self.env.run_jobs(["stick_master"])
        r = self.c.post(f"/api/episodes/{self.eid}/autopilot/resume", json={})
        self.assertEqual(r.json()["status"], "paused")
        self.assertEqual(len(self.jobs("stick_master")), 1)
        # a bigger budget (confirmed) lets Bob's start; then it waits for the owner's approvals
        r = self.c.post(f"/api/episodes/{self.eid}/autopilot/resume", json={"budget_usd": 0.5})
        self.assertEqual(r.status_code, 409)                               # not confirmed
        r = self.c.post(f"/api/episodes/{self.eid}/autopilot/resume", json={"budget_usd": 0.5, "confirm_usd": 0.5})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.jobs("stick_master")), 2)
        self.env.run_jobs(["stick_master"])
        from oddstudio.db import new_session
        with new_session() as db:
            v = AP.tick(db, self.eid)
        self.assertEqual(v["status"], "waiting")
        self.assertEqual([w["what"] for w in v["waiting_for"]], ["Approve a master for Ann", "Approve a master for Bob"])
        self.assertLessEqual(AP.spent(v), 0.5)
        self.assertEqual(self.approvals(), [])                             # it never approves

    def test_gpu_action_pauses_at_the_monthly_cap_and_nothing_runs(self):
        called = []
        old = AP.RUN["talk_render"]
        AP.RUN["talk_render"] = lambda *a: called.append(a) or {"job_id": 1}
        try:
            with self.db() as db:
                ep = self.ep(db)
                v = {"status": "running", "budget_usd": 100.0, "actions": []}
                n = AP.execute(db, ep, v, "talking", [AP._act("talk_render", "Render talking shot(s) 1", 60.0, shots=[1])])
            self.assertEqual(n, 0)
            self.assertEqual(called, [])
            self.assertEqual(v["status"], "paused")
            self.assertIn("monthly GPU cap", v["message"])
            with self.db() as db:                                           # within the cap and the budget: it runs
                v = {"status": "running", "budget_usd": 100.0, "actions": []}
                AP.execute(db, self.ep(db), v, "talking", [AP._act("talk_render", "Render", 2.0, shots=[1])])
            self.assertEqual(len(called), 1)
            self.assertTrue(v["keep_gpu"])
        finally:
            AP.RUN["talk_render"] = old

    def test_reported_cost_replaces_the_estimate_and_failures_pause(self):
        from oddstudio.models import Job
        with self.db() as db:
            ok = Job(kind="talking_render", episode_id=self.eid, status="succeeded", result={"usd": 0.7}, payload={})
            bad = Job(kind="reaction_animate", episode_id=self.eid, status="failed", error="ComfyError: boom", payload={})
            db.add_all([ok, bad])
            db.commit()
            v = {"status": "running", "budget_usd": 5.0, "actions": [
                {"what": "Render", "usd_max": 2.0, "usd": None, "job_id": ok.id, "state": "running"},
                {"what": "Animate reaction shot 2", "usd_max": 1.0, "usd": None, "job_id": bad.id, "state": "running"}]}
            AP.save(db, self.eid, v)
            db.commit()
            v = AP.tick(db, self.eid)
        self.assertEqual(v["status"], "paused")
        self.assertIn("Animate reaction shot 2 failed: ComfyError: boom", v["message"])
        self.assertAlmostEqual(AP.spent(v), 0.7 + 1.0)                     # the real cost; the failed one at its "at most"


class AutopilotGateTest(AutopilotBase):
    def test_waits_for_the_final_cut_and_never_approves_it(self):
        with self.db() as db:
            av = A.stored(db, self.eid)
            av["cuts"] = [{"id": "cut1", "asset_id": self.still, "hash": A.plan_rows(db, self.ep(db))["hash"], "seconds": 8.0}]
            A.save(db, self.eid, av)
            AP.save(db, self.eid, {"status": "running", "budget_usd": 1.0, "actions": [], "keep_gpu": True})
            db.commit()
        old = dict(AP.PLANNERS)
        for k in AP.STEPS[:-1]:
            AP.PLANNERS[k] = lambda db, ep, v: AP._plan()
        try:
            with self.db() as db:
                v = AP.tick(db, self.eid)
            self.assertEqual(v["status"], "waiting")
            self.assertEqual(v["waiting_for"], [{"what": "Watch the final cut and approve it", "where": "step 11"}])
            self.assertFalse(v["keep_gpu"])                                 # waiting: the GPU is released
            with self.db() as db:
                self.assertIsNone(A.stored(db, self.eid).get("approved"))
                self.assertFalse(CS.others_waiting(db, 0))
            self.assertEqual(self.approvals(), [])
            r = self.c.post(f"/api/episodes/{self.eid}/assembly/approve", json={"cut_id": "cut1"})   # the owner's click
            self.assertEqual(r.status_code, 200)
            with self.db() as db:
                v = AP.tick(db, self.eid)
            self.assertEqual(v["status"], "finished")
        finally:
            AP.PLANNERS.update(old)

    def test_talking_results_wait_for_the_owner(self):
        from oddstudio import talking_s2v as T
        self.set_c3(False)
        with self.db() as db:
            tv = T.stored(db, self.eid)
            tv["shots"]["1"]["approved"] = None
            T.save(db, self.eid, tv)
            db.commit()
            plan = AP.plan_approvals(db, self.ep(db), {})
        self.assertIn({"what": "Watch talking shot 1 and approve the result you want", "where": "step 9"}, plan["waiting"])
        self.assertIn({"what": "Watch reaction shot 3 and approve the result you want", "where": "step 8"}, plan["waiting"])

    def test_gpu_is_held_only_while_running_gpu_work(self):
        with self.db() as db:
            AP.save(db, self.eid, {"status": "running", "keep_gpu": True})
            db.commit()
            self.assertTrue(AP.holds_gpu(db))
            self.assertTrue(CS.others_waiting(db, 0))
            AP.save(db, self.eid, {"status": "paused", "keep_gpu": True})
            db.commit()
            self.assertFalse(AP.holds_gpu(db))

    def test_stop_terminates_the_gpu(self):
        with self.db() as db:
            AP.save(db, self.eid, {"status": "running", "keep_gpu": True, "budget_usd": 1.0})
            db.commit()
        r = self.c.post(f"/api/episodes/{self.eid}/autopilot/stop")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "stopped")
        self.assertEqual(len(self.stops), 1)
        self.assertIn("autopilot stopped by", self.stops[0])

    def test_redo_only_for_clear_problems_and_at_most_n_per_shot(self):
        from oddstudio import talking_s2v as T
        self.secrets(gemini_api_key=FAKE["gemini_api_key"])
        self.settings("quality", qa_paid_tier=True)
        with self.db() as db:
            ep = self.ep(db)
            tv = T.stored(db, self.eid)
            tv["shots"]["1"]["approved"] = None                            # the newest result, not approved
            T.save(db, self.eid, tv)
            db.commit()
            c = next(x for x in Q.clips(db, ep) if x["shot"] == 1)
            qv = {"checks": {}}
            for cc in Q.clips(db, ep):                                     # every clip already checked
                res = Q.parse(json.dumps({"issues": []}), cc["step"], str(cc["shot"]), Q.allowed_for(db, ep, cc), cc["seconds"])
                qv["checks"][Q.check_key(cc)] = {**res, "message_id": "x"}
            res = Q.parse(json.dumps(GOOD), "talk", "1", SC.ALLOWED["talk"], c["seconds"])
            mid = Q.post_to_thread(db, ep, c, res, "m", 0.01)
            qv["checks"][Q.check_key(c)] = {**res, "message_id": mid}
            Q.save(db, self.eid, qv)
            db.commit()
            plan = AP.plan_quality(db, ep, {"redos": {}})
            self.assertEqual([a["kind"] for a in plan["actions"]], ["redo"])
            self.assertTrue(plan["actions"][0]["gpu"])
            self.assertEqual(AP.plan_quality(db, ep, {"redos": {"talk:1": 1}})["actions"], [])   # N = 1 used up
            self.settings("quality", max_redos_per_shot=0)
            db.expire_all()
            self.assertEqual(AP.plan_quality(db, ep, {"redos": {}})["actions"], [])


class ProvidersTest(AutopilotBase):
    def test_summary_in_plain_words_without_keys(self):
        from oddstudio import wavespeed
        wavespeed.set_test_balance(lambda: 0.03)
        self.set_c3(False)                                                 # reaction shot 3 still needs the GPU
        with self.db() as db:
            items = {p["step"]: p for p in AP.providers(db, self.ep(db))}
        self.assertEqual(items["prompts"]["note"], "OpenAI: no key, so prompts will use the built-in templates")
        self.assertFalse(items["prompts"]["essential"])
        self.assertEqual(items["pictures"]["note"], "WaveSpeed: low balance ($0.03)")
        self.assertIn("no key", items["acting"]["note"])
        self.assertFalse(items["gpu"]["ready"])                            # GPU mode off
        self.assertTrue(items["gpu"]["essential"])                          # reaction shot 3 is not approved yet
        self.assertEqual(items["assembly"]["ready"], HAVE_FFMPEG)
        self.secrets(openai_api_key=FAKE["openai_api_key"], gemini_api_key=FAKE["gemini_api_key"])
        s = self.state()
        text = json.dumps(s)
        for v in FAKE.values():
            self.assertNotIn(v, text)
        self.assertTrue(any("Talking shots, reaction shots" in b for b in s["blockers"]))
        r = self.start(5.0)                                                 # an essential provider is missing: refused
        self.assertEqual(r.status_code, 409)
        self.assertIn("Cannot start", r.json()["detail"])
        self.assertEqual(self.jobs(), [])
