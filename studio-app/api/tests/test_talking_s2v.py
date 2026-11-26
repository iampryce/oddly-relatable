"""Talking shots, guided step 9 (talking_s2v.py, comfy_session.py, comfy.py, pose_remote.py).

Covered: the voice-only audio (only the speaker's words, each cut to its natural length); pieces of 4k+1 frames and the
extend chain; the Speech-to-Video graph with settings B and the control-video wiring; the actor's coverage and the
head-only movement guide's geometry; the head found in a still; the cost estimate and the 409s (unconfirmed, the
monthly cap, the GPU mode); the GPU preference order and the "allow expensive GPUs" setting; the cap refusal before a
pod is created; and one whole render job with ComfyUI and RunPod mocked (the larger output kept, 2 frames to trim,
nothing approved, the GPU terminated at the end). No network, no paid call: RunPod and ComfyUI are fake transports and
only fake credentials are used."""
import json
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw

from helpers import Env

from oddstudio import comfy, comfy_session as CS, gpu, runpod
from oddstudio import talking_s2v as T

FAKE_RUNPOD = "fake-runpod-credential-for-tests"


# ================================================================== pure parts
class PiecesAndVoiceTest(unittest.TestCase):
    def test_pieces_are_4k_plus_1_and_chain_past_77(self):
        self.assertEqual(T.plen(31), 33)
        self.assertEqual(T.plen(77), 77)
        self.assertEqual(T.plen(2), 5)
        self.assertEqual(T.pieces(31), [33])
        self.assertEqual(T.pieces(64), [65])
        self.assertEqual(T.pieces(77), [77])
        self.assertEqual(T.pieces(100), [77, 25])
        self.assertEqual(T.pieces(200), [77, 77, 49])
        for n in (1, 17, 78, 154, 155, 300):
            ps = T.pieces(n)
            self.assertTrue(all((p - 1) % 4 == 0 and p <= 77 for p in ps), (n, ps))
            self.assertGreaterEqual(sum(ps), n)
            self.assertLess(sum(ps) - n, 5 * len(ps))
        self.assertEqual(T.frames_for(1.9), 31)          # ep15 shot 4: 1.9 s at 16 fps
        self.assertEqual(T.frames_for(4.0), 64)

    def test_voice_spans_keep_each_word_at_its_natural_length(self):
        words = [{"start": 10.2, "end": 10.5, "word": "I"},                 # natural: 0.17 s -> kept from 10.28
                 {"start": 10.6, "end": 12.6, "word": "leave"},             # stretched over a laugh: only 0.45 s kept
                 {"start": 13.5, "end": 13.9, "word": "outside"},           # after the shot: dropped
                 {"start": 9.0, "end": 9.5, "word": "before"}]              # before the shot: dropped
        spans = T.voice_spans(words, 10.0, 13.0)
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[0][0], 0.5 - 0.17 - 0.05, places=2)
        self.assertAlmostEqual(spans[0][1], 0.55, places=2)
        a, b = spans[1]
        self.assertAlmostEqual(b, 2.65, places=2)
        self.assertAlmostEqual(a, 2.6 - (0.07 * 5 + 0.10) - 0.05, places=2)   # the laugh before it is muted
        f = T.gate_filter(spans)
        self.assertTrue(f.startswith("volume=enable='not(between(t,0.28,0.55)+between(t,"))
        self.assertTrue(f.endswith(")':volume=0"))
        self.assertEqual(T.gate_filter([]), "volume=enable='not(0)':volume=0")   # nothing spoken: all muted

    def test_template_prompt_and_estimate(self):
        p = T.template_prompt("Mortimer", "round glasses.", [{"expression": "flat", "eyes_and_gaze": "down at the paper",
                                                              "head_and_body": "still"}, {"expression": "smirk"}])
        self.assertIn("Mortimer (round glasses)", p)
        self.assertIn("stays SMALL", p)
        self.assertIn("Acting in this shot: flat, down at the paper, still Then smirk.", p)
        self.assertNotIn("Acting in this shot", T.template_prompt("Ann", "", []))
        e = T.estimate([77], [1.09, 1.09], 120, poses=False)
        self.assertEqual((e["minutes"], e["sessions"]), (21.0, 1))               # 11 min + 10 min start-up
        self.assertEqual(e["usd_typical"], round(1.09 * 21 / 60, 2))
        self.assertEqual(e["usd_max"], round(1.09 * 21 * 1.25 / 60, 2))
        e = T.estimate([77, 31], [1.09, 1.09, 2.09], 120, poses=True)            # A100 allowed: "at most" uses it
        work = 11.0 + round(11 * 33 / 77, 2)
        self.assertEqual(e["minutes"], round(work + 10 + 4, 1))
        self.assertEqual(e["usd_max"], round(2.09 * e["minutes"] * 1.25 / 60, 2))
        many = T.estimate([77] * 12, [1.09], 120, poses=False)                    # 132 min of work in 105-min sessions
        self.assertEqual(many["sessions"], 2)
        self.assertEqual(many["minutes"], 132 + 20)
        self.assertTrue(T.estimate([77 * 12], [1.09], 120, False)["too_long"])
        self.assertEqual(T.estimate([], [1.09], 120, False)["usd_max"], 0)


class GraphTest(unittest.TestCase):
    def test_single_piece_settings_b(self):
        g = T.build_graph("talk", "neg", "still.png", "voice.wav", None, 31, 7, "video/t")
        ks = g["k0"]["inputs"]
        self.assertEqual((ks["steps"], ks["cfg"], ks["sampler_name"], ks["scheduler"], ks["seed"]), (20, 4.5, "uni_pc", "simple", 7))
        self.assertEqual(g["ms"]["inputs"]["shift"], 8.0)
        s0 = g["s0"]["inputs"]
        self.assertEqual((s0["width"], s0["height"], s0["length"]), (1024, 576, 33))
        self.assertEqual(s0["ref_image"], ["im", 0])
        self.assertEqual(g["im"]["inputs"]["image"], "still.png")
        self.assertEqual(g["au"]["inputs"]["audio"], "voice.wav")
        self.assertEqual(g["cv"]["inputs"]["fps"], 16)
        self.assertEqual(g["d"]["inputs"]["samples"], ["k0", 0])
        self.assertNotIn("control_video", s0)
        self.assertNotIn("cvl", g)
        self.assertNotIn("e1", g)
        self.assertEqual(g["u"]["inputs"]["unet_name"], "wan2.2_s2v_14B_fp8_scaled.safetensors")
        self.assertEqual(g["ae"]["inputs"]["audio_encoder_name"], "wav2vec2_large_english_fp16.safetensors")

    def test_long_shot_chains_extend_pieces_and_control_video(self):
        g = T.build_graph("talk", "neg", "s.png", "v.wav", "pose.mp4", 200, 100, "video/t")
        self.assertEqual(g["s0"]["inputs"]["length"], 77)
        self.assertEqual(g["cvl"], {"class_type": "LoadVideo", "inputs": {"file": "pose.mp4"}})
        self.assertEqual(g["cvc"]["inputs"]["video"], ["cvl", 0])
        self.assertEqual(g["s0"]["inputs"]["control_video"], ["cvc", 0])
        for j, (L, prev) in enumerate([(77, ["k0", 0]), (49, ["c1", 0])], 1):
            e = g[f"e{j}"]
            self.assertEqual(e["class_type"], "WanSoundImageToVideoExtend")
            self.assertEqual((e["inputs"]["length"], e["inputs"]["video_latent"]), (L, prev))
            self.assertEqual(e["inputs"]["control_video"], ["cvc", 0])
            self.assertEqual(e["inputs"]["ref_image"], ["im", 0])
            k = g[f"k{j}"]["inputs"]
            self.assertEqual((k["positive"], k["negative"], k["latent_image"], k["seed"]), ([f"e{j}", 0], [f"e{j}", 1], [f"e{j}", 2], 100 + j))
            self.assertEqual((k["steps"], k["cfg"]), (20, 4.5))
            c = g[f"c{j}"]
            self.assertEqual(c["class_type"], "LatentConcat")
            self.assertEqual(c["inputs"], {"samples1": prev, "samples2": [f"k{j}", 0], "dim": "t"})
        self.assertNotIn("e3", g)
        self.assertEqual(g["d"]["inputs"]["samples"], ["c2", 0])


# ------------------------------------------------------------------ the actor and the guide
def pose(head_xy, ear=30.0, neck_drop=60.0, shoulder=80.0):
    """33 MediaPipe-style points: ears (7, 8) around the head centre, shoulders (11, 12) below, nose (0), eyes (2, 5)."""
    p = np.zeros((33, 3))
    hx, hy = head_xy
    p[:, 2] = 1.0
    p[7, :2], p[8, :2] = (hx + ear / 2, hy), (hx - ear / 2, hy)
    p[0, :2] = (hx, hy + 5)
    p[2, :2], p[5, :2] = (hx + 6, hy - 3), (hx - 6, hy - 3)
    p[11, :2], p[12, :2] = (hx + shoulder / 2, hy + neck_drop), (hx - shoulder / 2, hy + neck_drop)
    for k in (13, 14, 15, 16):
        p[k, :2] = (hx + (60 if k % 2 else -60), hy + 150)
    return p.tolist()


class GuideTest(unittest.TestCase):
    def setUp(self):
        actor = [pose((180 + i, 200)) for i in range(10)]
        other = [pose((300, 120), ear=50)] * 4                # someone else on screen for 4 frames
        self.seq = actor[:3] + other + actor[3:] + [None]   # and one frame with no pose
        self.sig = T.signature_of(actor)

    def test_coverage_and_automatic_signature(self):
        share, ok = T.coverage(self.seq, self.sig, 640)
        self.assertEqual(sum(ok), 10)
        self.assertAlmostEqual(share, round(10 / 15, 3))
        auto = T.auto_signature(self.seq, 640)
        self.assertEqual(auto["frames"], 10)                 # the person seen most is the actor
        self.assertLess(abs(auto["head"][0] - self.sig["head"][0]), 1)
        self.assertIsNone(T.auto_signature(self.seq[:3], 640))
        low, _ = T.coverage([pose((300, 120), ear=50)] * 6 + [pose((180, 200))] * 3, self.sig, 640)
        self.assertLess(low, T.MIN_COVERAGE)                  # such a shot gets no guide
        # the tolerance scales with the frame: 45 px at 640 px high
        self.assertTrue(T.is_actor(np.array(pose((220, 200)))[:, :2], self.sig, 640))
        self.assertFalse(T.is_actor(np.array(pose((240, 200)))[:, :2], self.sig, 640))
        self.assertTrue(T.is_actor(np.array(pose((240, 200)))[:, :2], self.sig, 1280))

    def test_gaps_are_filled_from_the_nearest_actor_frame(self):
        _share, ok = T.coverage(self.seq, self.sig, 640)
        A = T.fill_gaps(self.seq, ok, 20)
        self.assertEqual(len(A), 20)
        self.assertTrue(np.allclose(A[3], np.array(self.seq[2])[:, :2]))     # first gap frame: nearest is frame 2
        self.assertTrue(np.allclose(A[6], np.array(self.seq[7])[:, :2]))     # last gap frame: nearest is frame 7
        self.assertTrue(np.allclose(A[19], A[13]))                            # padded with the last frame

    def test_head_only_guide_lined_up_with_the_character(self):
        A = [np.array(pose((180, 200)))[:, :2], np.array(pose((190, 205)))[:, :2]]
        pts = T.guide_points(A, (524.0, 222.0), 78.0)
        self.assertEqual(set(pts[0]), {"neck", 0, 2, 5, 7, 8})                 # no shoulders, arms or hands
        hx = (pts[0][7][0] + pts[0][8][0]) / 2
        hy = (pts[0][7][1] + pts[0][8][1]) / 2
        self.assertAlmostEqual(hx, 524.0, places=0)
        self.assertAlmostEqual(hy, 222.0, places=0)
        self.assertEqual(pts[0]["neck"], (524.0, 300.0))                      # neck_len straight below the head
        sc = 78.0 / 60.0
        self.assertAlmostEqual((pts[1][7][0] + pts[1][8][0]) / 2 - hx, 10 * sc, places=0)   # only the change carries
        self.assertEqual({tuple(sorted(map(str, (a, b)))) for a, b, _c in T.HEAD_LIMBS},
                         {("0", "neck"), ("0", "5"), ("0", "2"), ("5", "8"), ("2", "7")})
        d = Path(tempfile.mkdtemp())
        files = T.draw_guide(pts, d)
        self.assertEqual(len(files), 2)
        with Image.open(files[0]) as im:
            self.assertEqual(im.size, (1024, 576))
            self.assertEqual(im.getpixel((10, 10)), (0, 0, 0))                # black background
            self.assertEqual(im.getpixel((900, 500)), (0, 0, 0))              # nothing drawn where shoulders were

    def test_head_found_in_a_still(self):
        f = Path(tempfile.mkdtemp()) / "still.png"
        im = Image.new("RGB", (1024, 576), (40, 90, 60))
        d = ImageDraw.Draw(im)
        d.ellipse((430, 130, 590, 290), fill=(255, 255, 255), outline=(0, 0, 0), width=6)   # head r=80 at (510, 210)
        d.line((470, 200, 550, 200), fill=(0, 0, 0), width=6)                                  # glasses line across it
        d.rectangle((460, 330, 560, 450), fill=(255, 255, 255))                                # a sheet of paper below
        im.save(f)
        h = T.detect_head(f)
        self.assertLess(abs(h["x"] - 510), 12)
        self.assertLess(abs(h["y"] - 210), 12)
        self.assertLess(abs(h["neck"] - 80), 12)
        Image.new("RGB", (1024, 576), (40, 90, 60)).save(f)
        self.assertIsNone(T.detect_head(f))


class PoseRemoteTest(unittest.TestCase):
    def test_points_read_over_ssh_with_a_throwaway_key(self):
        from oddstudio import pose_remote as PR
        priv, pub = PR.new_keypair()
        self.assertIn("OPENSSH PRIVATE KEY", priv)
        self.assertTrue(pub.startswith("ssh-ed25519 "))
        calls, keys = [], []

        def fake(cmd, **kw):
            calls.append(cmd)
            kf = Path(cmd[cmd.index("-i") + 1])
            keys.append(kf)
            self.assertEqual(kf.stat().st_mode & 0o777, 0o600)
            if cmd[0] == "scp" and cmd[-1].endswith("poses.json"):
                Path(cmd[-1]).write_text(json.dumps({"s1-0.00-2": {"size": [480, 640], "seq": [None, pose((1, 2))]}}))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        old = PR.runner
        PR.runner = fake
        try:
            tar = Path(tempfile.mkdtemp()) / "frames.tar"
            tar.write_bytes(b"x")
            got = PR.read_poses("1.2.3.4", 40022, priv, tar, log=lambda m: None)
        finally:
            PR.runner = old
        self.assertEqual(got["s1-0.00-2"]["size"], [480, 640])
        self.assertTrue(all("StrictHostKeyChecking=no" in c for c in calls))
        self.assertTrue(any("mediapipe==0.10.14" in " ".join(c) for c in calls))
        self.assertIn("40022", calls[0])
        self.assertFalse(any(k.exists() for k in keys))              # the private key file is gone afterwards


class GpuOrderTest(unittest.TestCase):
    def test_preference_and_expensive_setting(self):
        self.assertEqual(CS.gpu_order({}), ["NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"])
        self.assertEqual(CS.gpu_order({"allow_expensive_gpus": False}), ["NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"])
        self.assertEqual(CS.gpu_order({"allow_expensive_gpus": True}),
                         ["NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation", "NVIDIA A100 80GB PCIe"])
        self.assertEqual(CS.list_prices({}), [1.09, 1.09])


# ================================================================== API, sessions and the job (mocked)
def wav(path: Path, seconds: float) -> Path:
    import math, struct
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i / 8))) for i in range(int(seconds * 16000))))
    return path


class FakeRunPod:
    """RunPod's REST API v2 as runpod.py uses it. `busy`: GPU types that answer 400 (none free)."""

    def __init__(self, busy=()):
        self.busy, self.pods, self.calls = set(busy), {}, []

    def __call__(self, method, path, json=None, params=None):
        self.calls.append((method, path, json))
        if path.startswith("/v2/catalog/gpus/"):
            return 404, {"detail": "not in the test catalog"}            # list prices are used
        if method == "POST" and path == "/v2/pods":
            if json["gpu"]["id"] in self.busy:
                return 400, {"detail": "There are no instances currently available"}
            pid = f"pod{len(self.pods) + 1}"
            self.pods[pid] = {"id": pid, "name": json["name"], "status": "RUNNING", "cost": 0, "publicIp": "203.0.113.7",
                              "portMappings": {"22": 40022}, **json}
            return 201, self.pods[pid]
        if method == "GET" and path == "/v2/pods":
            return 200, {"pods": [p for p in self.pods.values() if p["status"] != "TERMINATED"], "pagination": {}}
        if path.startswith("/v2/pods/"):
            p = self.pods.get(path.rsplit("/", 1)[1])
            if method == "GET":
                return (200, p) if p and p["status"] != "TERMINATED" else (404, {})
            if method == "DELETE":
                if not p or p["status"] == "TERMINATED":
                    return 404, {}
                p["status"] = "TERMINATED"
                return 204, {}
        return 404, {"detail": "no such route"}

    def created(self):
        return [j for m, p, j in self.calls if m == "POST" and p == "/v2/pods"]


class FakeComfy:
    """ComfyUI behind the RunPod proxy: models missing until ComfyUI-Manager installs them; one graph per submit that
    finishes at once with the control passthrough (small) and the result (large)."""

    def __init__(self, result: bytes = b"\x00\x00\x00\x18ftypmp42" + b"R" * 4000):
        self.have, self.installed, self.graphs, self.uploads, self.headers = set(), [], [], [], []
        self.result = result

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(dict(request.headers))
        p = request.url.path
        if p == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        if p.startswith("/models/"):
            folder = p.split("/", 2)[2]
            return httpx.Response(200, json=[f for (fo, f) in self.have if fo == folder])
        if p == "/v2/manager/queue/install_model":
            b = json.loads(request.content)
            assert request.headers.get("sec-fetch-site") == "same-origin" and request.headers.get("origin")
            self.installed.append(b)
            return httpx.Response(200, json={})
        if p == "/v2/manager/queue/start":
            for b in self.installed:
                self.have.add((b["save_path"], b["filename"]))
            return httpx.Response(200, json={})
        if p == "/v2/manager/queue/status":
            return httpx.Response(200, json={"is_processing": False, "pending_count": 0})
        if p == "/upload/image":
            name = request.content.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            self.uploads.append(name)
            return httpx.Response(200, json={"name": name})
        if p == "/prompt":
            self.graphs.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": f"p{len(self.graphs)}", "node_errors": {}})
        if p.startswith("/history/"):
            pid = p.rsplit("/", 1)[1]
            return httpx.Response(200, json={pid: {"status": {"completed": True, "status_str": "success"}, "outputs": {
                "cvl": {"videos": [{"filename": "ctl_00001_.mp4", "subfolder": "video", "type": "output"}]},
                "sv": {"videos": [{"filename": "talk_00001_.mp4", "subfolder": "video", "type": "output"}]}}}})
        if p == "/view":
            name = request.url.params["filename"]
            return httpx.Response(200, content=self.result if name.startswith("talk") else b"\x00\x00\x00\x18ftypmp42ctl")
        return httpx.Response(404)


class ApiBase(unittest.TestCase):
    ffmpeg = False

    def setUp(self):
        if self.ffmpeg:
            os.environ["FFMPEG"] = "/usr/bin/ffmpeg"
        self.env = Env().login()
        self.c = self.env.client
        self.sleep = gpu.sleep
        gpu.sleep = lambda s: None
        from oddstudio.db import new_session
        from oddstudio.models import Asset, Character, Episode, Setting
        from oddstudio.storage import storage
        tmp = Path(tempfile.mkdtemp())
        with new_session() as db:
            db.add_all([Character(key="mort", name="Mortimer", visual_description="round wire glasses"),
                        Character(key="win", name="Winifred")])
            still = tmp / "still.png"
            im = Image.new("RGB", (1024, 576), (40, 90, 60))
            ImageDraw.Draw(im).ellipse((430, 130, 590, 290), fill=(255, 255, 255), outline=(0, 0, 0), width=6)
            im.save(still)
            storage().put_file("episodes/x/still.png", still, "image/png")
            storage().put_file("episodes/x/audio.wav", wav(tmp / "a.wav", 8.0), "audio/wav")
            sa = Asset(kind="still", label="still", storage_key="episodes/x/still.png", content_type="image/png")
            aa = Asset(kind="audio", label="voice", storage_key="episodes/x/audio.wav", content_type="audio/wav")
            db.add_all([sa, aa])
            db.flush()
            tr = {"person_map": {"S1": "mort", "S2": "win"}, "lines": [
                {"id": "l1", "start": 0.4, "end": 3.6, "text": "I leave it all", "speaker": "S1",
                 "words": [{"start": 0.4, "end": 0.6, "word": "I"}, {"start": 0.7, "end": 1.0, "word": "leave"},
                           {"start": 1.1, "end": 3.6, "word": "all"}]},
                {"id": "l2", "start": 4.2, "end": 5.5, "text": "To whom?", "speaker": "S2",
                 "words": [{"start": 4.2, "end": 4.6, "word": "To"}, {"start": 4.7, "end": 5.5, "word": "whom?"}]}]}
            ep = Episode(title="Talk", audio_asset_id=aa.id, audio_transcript=tr)
            db.add(ep)
            db.flush()
            self.eid, self.still_id = ep.id, sa.id
            v = {"asset_id": sa.id, "at": 0, "source": "still", "note": ""}
            db.add(Setting(key=f"shotframes:{ep.id}", value={"shots": [
                {"index": 1, "t0": 0.0, "t1": 4.6, "people": ["mort"], "versions": [v], "chosen": sa.id, "approved": True},
                {"index": 2, "t0": 4.6, "t1": 6.0, "people": ["mort"], "versions": [v], "chosen": sa.id, "approved": True},
                {"index": 3, "t0": 6.0, "t1": 7.0, "people": ["win"], "versions": [v], "chosen": sa.id, "approved": False,
                 "kind": "talk", "speaker": "win"}]}))
            db.commit()

    def tearDown(self):
        gpu.sleep = self.sleep
        runpod.set_test_transport(None)
        comfy.set_test_transport(None)
        self.env.close()
        os.environ.pop("FFMPEG", None)

    def rented(self, **extra):
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        with new_session() as db:
            put_secrets(db, {"runpod_api_key": FAKE_RUNPOD})
        r = self.c.put("/api/settings/gpu", json={"mode": "rented", **extra})
        self.assertEqual(r.status_code, 200, r.text)

    def url(self, tail=""):
        return f"/api/episodes/{self.eid}/talking{tail}"


class ApiTest(ApiBase):
    def test_rows_voice_head_and_prompt(self):
        t = self.c.get(self.url()).json()
        rows = {s["index"]: s for s in t["shots"]}
        self.assertEqual(set(rows), {1, 3})               # shot 2: Winifred speaks off screen, Mortimer only listens
        r1 = rows[1]
        self.assertEqual((r1["speaker"], r1["name"], r1["frames"], r1["blocked"]), ("mort", "Mortimer", 74, ""))
        self.assertEqual(r1["text"], "I leave it all")
        self.assertEqual(len(r1["voice_spans"]), 3)        # only Mortimer's words, not Winifred's "To" at 4.2 s
        self.assertLess(r1["voice_spans"][-1][0], 3.6)
        self.assertGreater(r1["voice_spans"][-1][0], 3.0)  # "all" stretched over 2.5 s: only its natural length kept
        self.assertEqual(rows[3]["blocked"], "approve this shot's still first")
        head = r1["still"]["head"]
        self.assertEqual(head["source"], "auto")
        self.assertLess(abs(head["x"] - 510), 12)
        self.assertEqual(r1["prompt"]["source"], "template")
        self.assertEqual(r1["prompt"]["label"], T.TEMPLATE_LABEL)         # no OpenAI key saved
        self.assertIsNone(r1["voice_url"])                               # FFmpeg not configured here
        self.assertEqual(r1["guide"]["state"], "no_reference")
        self.assertEqual(r1["estimate"]["minutes"], round(T.shot_minutes(74) + 10, 1))
        self.assertFalse(t["availability"]["ok"])
        self.assertIn("Rented", t["availability"]["reason"])
        # the owner's edits (free): prompt, guide off, the head clicked
        t = self.c.put(self.url("/1"), json={"prompt": "Mortimer reads.", "guide": False, "head": {"x": 520, "y": 225}}).json()
        r1 = next(s for s in t["shots"] if s["index"] == 1)
        self.assertEqual((r1["prompt"]["text"], r1["prompt"]["edited"]), ("Mortimer reads.", True))
        self.assertEqual(r1["guide"]["state"], "off")
        self.assertEqual((r1["still"]["head"]["x"], r1["still"]["head"]["source"]), (520, "owner"))
        # without an OpenAI key "write with GPT" keeps the labelled template (no call, nothing to confirm)
        t = self.c.post(self.url("/1/write-prompt"), json={}).json()
        r1 = next(s for s in t["shots"] if s["index"] == 1)
        self.assertEqual((r1["prompt"]["source"], r1["prompt"]["label"]), ("template", T.TEMPLATE_LABEL))
        self.assertIn("Mortimer (round wire glasses)", r1["prompt"]["text"])
        self.assertEqual(self.c.post(self.url("/2/write-prompt"), json={}).status_code, 404)
        # the guide's step list
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["talking"]
        self.assertEqual((g["status"], g["available"]), ("not_started", True))
        self.assertEqual(g["detail"], "0 of 2 talking shots approved")

    def test_render_needs_rented_mode_confirmed_cost_and_room_under_the_cap(self):
        r = self.c.post(self.url("/render"), json={"shots": [1], "confirm_usd": 5})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Rented", r.json()["detail"])
        self.rented()
        r = self.c.post(self.url("/render"), json={"shots": [3], "confirm_usd": 5})
        self.assertEqual(r.status_code, 409)
        self.assertIn("approve its still", r.json()["detail"])
        r = self.c.post(self.url("/render"), json={"shots": [1]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm that amount", r.json()["detail"])
        est = next(s for s in self.c.get(self.url()).json()["shots"] if s["index"] == 1)["estimate"]
        r = self.c.post(self.url("/render"), json={"shots": [1], "confirm_usd": est["usd_max"] - 0.01})
        self.assertEqual(r.status_code, 409)
        # the monthly cap: this render alone would pass it
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 0.2})
        r = self.c.post(self.url("/render"), json={"shots": [1], "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("monthly GPU cap", r.json()["detail"])
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 50})
        r = self.c.post(self.url("/render"), json={"shots": [1], "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as db:
            j = db.get(Job, r.json()["id"])
            self.assertEqual((j.kind, j.payload["backend"], j.payload["shots"]), ("talking_render", "gpu", [1]))
        r = self.c.post(self.url("/render"), json={"shots": [1], "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("already running", r.json()["detail"])
        t = self.c.get(self.url()).json()
        self.assertEqual(next(s for s in t["shots"] if s["index"] == 1)["run"]["status"], "queued")
        self.assertEqual(self.c.post(self.url("/1/approve"), json={"render_id": "nope"}).status_code, 404)

    def test_settings_check_the_expensive_gpu_flag(self):
        self.assertEqual(self.c.put("/api/settings/gpu", json={"allow_expensive_gpus": "yes"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings/gpu", json={"allow_expensive_gpus": True}).status_code, 200)


class SessionTest(ApiBase):
    def launch(self, rp):
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(FakeComfy()))
        from oddstudio.db import new_session
        with new_session() as db:
            return CS.launch(db, log=lambda m: None)

    def test_l40s_then_6000_ada_and_the_pod_spec(self):
        self.rented()
        rp = FakeRunPod(busy={"NVIDIA L40S"})
        s = self.launch(rp)
        tried = [j["gpu"]["id"] for j in rp.created()]
        self.assertEqual(tried, ["NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"])
        self.assertEqual(s["gpu_type"], "NVIDIA RTX 6000 Ada Generation")
        body = rp.created()[-1]
        self.assertTrue(body["name"].startswith(runpod.NAME_PREFIX))        # the orphan sweep covers it
        self.assertEqual((body["cloud"], body["image"], body["disk"], body["ports"]),
                         ("SECURE", "runpod/comfyui:2.5.0-comfyuiv0.45.0-cuda13.2", 120, ["8188/http", "22/tcp"]))
        self.assertEqual(set(body["env"]), {"COMFYUI_PASSWORD", "PUBLIC_KEY"})
        self.assertTrue(body["env"]["PUBLIC_KEY"].startswith("ssh-ed25519 "))
        self.assertEqual(s["client"].base, f"https://{s['pod_id']}-8188.proxy.runpod.net")
        g = self.c.get("/api/gpu").json()
        live = [x for x in g["sessions"] if x["status"] == "ready"]
        self.assertEqual((live[0]["kind"], live[0]["gpu_type"]), ("comfyui", "NVIDIA RTX 6000 Ada Generation"))
        self.assertNotIn(body["env"]["COMFYUI_PASSWORD"], json.dumps(g))
        self.assertNotIn("password", json.dumps(g))
        # a second launch reuses the ready session
        from oddstudio.db import new_session
        with new_session() as db:
            self.assertEqual(CS.launch(db, log=lambda m: None)["session"], s["session"])
        self.assertEqual(len(rp.created()), 2)
        # stopping terminates the pod and drops the session's secrets
        self.assertEqual(self.c.post(self.url("/stop")).json()["terminated"], [s["session"]])
        self.assertEqual(rp.pods[s["pod_id"]]["status"], "TERMINATED")
        with new_session() as db:
            led = gpu.ledger(db)["sessions"][s["session"]]
            self.assertEqual(led["status"], "ended")
            self.assertNotIn("password", led)
            self.assertNotIn("ssh_key", led)

    def test_a100_only_when_expensive_gpus_are_allowed(self):
        self.rented()
        busy = {"NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"}
        rp = FakeRunPod(busy=busy)
        with self.assertRaises(gpu.GpuUnavailable) as e:
            self.launch(rp)
        self.assertIn("allow expensive GPUs", str(e.exception))
        self.assertNotIn("NVIDIA A100 80GB PCIe", [j["gpu"]["id"] for j in rp.created()])
        from oddstudio.db import new_session
        with new_session() as db:
            ended = list(gpu.ledger(db)["sessions"].values())
            self.assertEqual([(x["status"], x["cost_usd"]) for x in ended], [("ended", 0.0)])     # nothing billed
        self.c.put("/api/settings/gpu", json={"allow_expensive_gpus": True})
        rp = FakeRunPod(busy=busy)
        s = self.launch(rp)
        self.assertEqual([j["gpu"]["id"] for j in rp.created()],
                         ["NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation", "NVIDIA A100 80GB PCIe"])
        self.assertEqual((s["gpu_type"], s["price_per_hour"]), ("NVIDIA A100 80GB PCIe", 2.09))

    def test_cap_refused_before_any_pod_is_created(self):
        self.rented(monthly_cap_usd=1.0)                 # an L40S session reserves $1.09 x (120 + 5) min = $2.27
        rp = FakeRunPod()
        with self.assertRaises(gpu.GpuUnavailable) as e:
            self.launch(rp)
        self.assertIn("monthly GPU cap", str(e.exception))
        self.assertEqual(rp.created(), [])


@unittest.skipUnless(Path("/usr/bin/ffmpeg").exists(), "needs FFmpeg")
class JobTest(ApiBase):
    ffmpeg = True

    def test_render_job_end_to_end(self):
        self.rented()
        clip = Path(tempfile.mkdtemp()) / "clip.mp4"              # a real (tiny) video, so the review copy can be muxed
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=16", "-t", "1",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        rp, cf = FakeRunPod(), FakeComfy(clip.read_bytes())
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(cf))
        t = self.c.get(self.url()).json()
        r1 = next(s for s in t["shots"] if s["index"] == 1)
        self.assertTrue(r1["voice_url"])                             # the voice-only preview was made (free)
        r = self.c.post(self.url("/render"), json={"shots": None, "confirm_usd": t["total"]["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["talking_render"])
        self.assertEqual(ran[0][:2], ("talking_render", "succeeded"), ran)
        # the models were downloaded through ComfyUI-Manager, then one graph per shot
        self.assertEqual({b["filename"] for b in cf.installed}, {m["filename"] for m in T.MODELS})
        self.assertEqual(len(cf.graphs), 1)
        g = cf.graphs[0]
        self.assertEqual(g["s0"]["inputs"]["length"], 77)            # 74 frames -> one piece of 77
        self.assertNotIn("cvl", g)                                   # no reference video: no movement guide
        self.assertTrue(all(h.get("user-agent") == "curl/8.7.1" for h in cf.headers))
        self.assertTrue(all(h.get("authorization", "").startswith("Bearer ") for h in cf.headers))
        self.assertTrue(any(u.endswith("-voice.wav") for u in cf.uploads))
        t = self.c.get(self.url()).json()
        r1 = next(s for s in t["shots"] if s["index"] == 1)
        rec = r1["renders"][0]
        self.assertEqual((rec["trim_start_frames"], rec["frames"], rec["settings"]), (2, 74, "B"))
        self.assertIsNone(r1["approved"])                            # nothing approves itself
        self.assertEqual(r1["run"]["status"], "done")
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as db:
            a = db.get(Asset, rec["asset_id"])
            self.assertEqual(a.size, len(cf.result))                 # the result, not the control passthrough
            self.assertTrue(storage().local_path(a.storage_key).exists())
            sess = list(gpu.ledger(db)["sessions"].values())
            self.assertEqual([x["status"] for x in sess], ["ended"])  # the GPU was turned off at the end
            self.assertEqual(sess[0]["reason"], "talking shots finished")
        self.assertTrue(rec["preview_url"])                          # review copy with the original audio
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]["talking"]
        self.assertEqual(g["status"], "needs_approval")
        t = self.c.post(self.url("/1/approve"), json={"render_id": rec["id"]}).json()
        self.assertEqual(next(s for s in t["shots"] if s["index"] == 1)["approved"], rec["id"])

    def test_movement_guide_from_the_reference_reaches_control_video(self):
        from oddstudio import pose_remote as PR
        self.rented()
        ref = Path(tempfile.mkdtemp()) / "ref.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25", "-t", "5",
                        "-pix_fmt", "yuv420p", str(ref)], check=True)
        r = self.c.put(f"/api/episodes/{self.eid}/guide/reference-video", content=ref.read_bytes(), headers={"Content-Type": "video/mp4"})
        self.assertEqual(r.status_code, 200, r.text)
        rp, cf = FakeRunPod(), FakeComfy()
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(cf))
        sent = []

        def fake(cmd, **kw):
            if cmd[0] not in ("ssh", "scp"):
                return subprocess.run(cmd, **kw)                     # FFmpeg cutting the frames runs for real
            sent.append(cmd)
            if cmd[0] == "scp" and cmd[-1].endswith("poses.json"):
                # the actor (head near 240, 320) on screen in every frame but two, which show someone else
                seq = [pose((240 + i % 3, 320)) for i in range(74)]
                seq[10] = seq[11] = pose((60, 100), ear=60)
                Path(cmd[-1]).write_text(json.dumps({"s1-0.00-74": {"size": [480, 640], "seq": seq}}))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        old = PR.runner
        PR.runner = fake
        try:
            t = self.c.get(self.url()).json()
            r1 = next(s for s in t["shots"] if s["index"] == 1)
            self.assertEqual(r1["guide"]["state"], "not_read")
            self.assertGreater(t["total"]["minutes"], r1["estimate"]["minutes"])   # reading the poses is in the total
            r = self.c.post(self.url("/render"), json={"shots": [1], "confirm_usd": t["total"]["usd_max"]})
            self.assertEqual(r.status_code, 200, r.text)
            ran = self.env.run_jobs(["talking_render"])
        finally:
            PR.runner = old
        self.assertEqual(ran[0][:2], ("talking_render", "succeeded"), ran)
        self.assertTrue(any(c[0] == "scp" and c[-1].endswith(":/root/oddpose/") for c in sent))
        self.assertTrue(any("203.0.113.7" in " ".join(c) and "40022" in c for c in sent))
        g = cf.graphs[0]
        self.assertEqual(g["s0"]["inputs"]["control_video"], ["cvc", 0])
        self.assertTrue(g["cvl"]["inputs"]["file"].endswith("-pose.mp4"))
        self.assertTrue(any(u.endswith("-pose.mp4") for u in cf.uploads))
        t = self.c.get(self.url()).json()
        r1 = next(s for s in t["shots"] if s["index"] == 1)
        guide = r1["renders"][0]["guide"]
        self.assertTrue(guide["used"])
        self.assertAlmostEqual(guide["coverage"], round(72 / 74, 3))
        self.assertIn("automatic", guide["signature"])
        self.assertEqual(r1["guide"]["state"], "ok")
        self.assertEqual(r1["guide"]["text"], "follows the actor 97% of the shot")


if __name__ == "__main__":
    unittest.main()
