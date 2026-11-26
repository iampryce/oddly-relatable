"""Reactions and close-ups, guided steps 6-8 (reactions.py, on the shared ComfyUI session of comfy_session.py).

Covered: the crop box math (16:9, inside the master, suggested from the head); the masked paste-back (every pixel outside
the oval unchanged); poses from the acting beats (overshoot, a hold at the start); the timeline (holds, eased moves,
living holds over 0.4 s) and ease-out; the background lock (outside the feathered box, the base's own pixels); the
eyeline in every face prompt (template, GPT text without one, "at the camera"); the ported graphs; the cost estimate
and the 409s (unconfirmed, the cap, the GPU mode, unapproved crop/poses); the chat's new proposals (redo_pose,
reanimate_shot) and the pose thread key; and both GPU jobs end to end with ComfyUI and RunPod mocked (nothing approved,
the GPU terminated). No network, no paid call: only fake credentials."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from helpers import Env

from oddstudio import comfy, gpu, runpod
from oddstudio import reactions as R
from oddstudio import shot_chat as SC

from test_talking_s2v import FakeRunPod, wav

FAKE_RUNPOD = "fake-runpod-credential-for-tests"
FAKE_OPENAI = "fake-openai-credential-for-tests"


# ================================================================== pure parts
class CropTest(unittest.TestCase):
    def test_box_is_169_inside_the_master(self):
        b = R.fit_169(-100, -50, 800, 300, 1920, 1080)
        self.assertAlmostEqual(b["w"] / b["h"], 16 / 9, places=3)
        self.assertEqual((b["x"], b["y"]), (0.0, 0.0))                   # moved inside, not shrunk
        self.assertEqual(b["w"], 800)
        b = R.fit_169(1800, 1000, 400, 225, 1920, 1080)                 # past the bottom-right corner
        self.assertEqual((b["x"] + b["w"], b["y"] + b["h"]), (1920, 1080))
        b = R.fit_169(0, 0, 5000, 5000, 1920, 1080)                     # bigger than the master: the whole master
        self.assertEqual((b["w"], b["h"]), (1920, 1080))
        b = R.fit_169(0, 0, 10, 10, 1920, 1080)                         # tiny: at least 64 px wide
        self.assertEqual(b["w"], 64)
        tall = R.fit_169(0, 0, 900, 900, 900, 1600)                     # portrait master: width limited by it
        self.assertEqual(tall["w"], 900)
        self.assertAlmostEqual(tall["h"], 506.25)
        o = R.box_from_owner(960, 540, 640, 1920, 1080)                 # centre + width
        self.assertEqual((o["x"], o["y"], o["w"], o["h"]), (640, 360, 640, 360))

    def test_suggested_crop_from_the_head(self):
        head = {"x": 1200.0, "y": 400.0, "r": 60.0}
        c = R.suggest_crop([head], 1920, 1080, close=True)
        self.assertAlmostEqual(c["h"], 2 * 60 / 0.30, places=1)        # the head is 30% of the crop's height
        self.assertAlmostEqual(c["x"] + c["w"] / 2, 1200, places=1)
        self.assertAlmostEqual(c["y"] + 0.38 * c["h"], 400, places=1)
        self.assertEqual(c["source"], "auto")
        hc = R.head_in_crop(head, c)
        self.assertAlmostEqual(hc["x"], 640, places=1)
        self.assertAlmostEqual(hc["y"], 0.38 * 720, places=1)
        self.assertAlmostEqual(hc["r"], 60 * 1280 / c["w"], places=3)
        g = R.suggest_crop([head, {"x": 600.0, "y": 420.0, "r": 55.0}], 1920, 1080, close=False)
        self.assertLessEqual(g["x"], 600 - 3 * 60)
        self.assertGreaterEqual(g["x"] + g["w"], 1200 + 3 * 60)
        full = R.suggest_crop([], 1920, 1080, close=True)
        self.assertEqual((full["x"], full["y"], full["w"], full["h"]), (0, 0, 1920, 1080))

    def test_crop_is_an_exact_zoom_upscaled_with_lanczos(self):
        m = Image.new("RGB", (1920, 1080), (10, 20, 30))
        ImageDraw.Draw(m).rectangle((960, 540, 1919, 1079), fill=(200, 0, 0))
        im = R.crop_image(m, {"x": 640, "y": 360, "w": 640, "h": 360})
        self.assertEqual(im.size, (1280, 720))
        self.assertEqual(im.getpixel((100, 100)), (10, 20, 30))
        self.assertEqual(im.getpixel((1200, 700)), (200, 0, 0))

    def test_heads_found_and_matched_by_seat(self):
        m = Image.new("RGB", (1920, 1080), (60, 100, 70))
        d = ImageDraw.Draw(m)
        for x in (500, 1300):
            d.ellipse((x - 70, 330, x + 70, 470), fill=(255, 255, 255), outline=(0, 0, 0), width=8)
            d.line((x - 30, 380, x - 10, 380), fill=(0, 0, 0), width=6)             # a face line inside the head
        heads = R.find_heads(m)
        self.assertGreaterEqual(len(heads), 2)
        hp = R.heads_for_people(heads, ["sid", "win"])
        self.assertLess(abs(hp["sid"]["x"] - 500), 20)
        self.assertLess(abs(hp["win"]["x"] - 1300), 20)
        self.assertLess(abs(hp["sid"]["r"] - 66), 12)
        self.assertEqual(R.heads_for_people(heads[:1], ["sid", "win"]), {})          # too few heads: nobody matched


class MaskTest(unittest.TestCase):
    def test_paste_back_changes_nothing_outside_the_oval(self):
        base = Image.new("RGB", (1280, 720))
        base.putdata([((x * 7) % 256, (y * 3) % 256, (x + y) % 256) for y in range(720) for x in range(1280)])
        edited = Image.new("RGB", (1392, 752), (255, 0, 255))                       # the edit model's own size
        o = {"cx": 640, "cy": 300, "rx": 90, "ry": 100}
        out = R.paste_back(base, edited, o)
        hard = R.oval_mask(o)
        changed_outside = 0
        a, b, m = out.load(), base.load(), hard.load()
        for y in range(0, 720, 2):
            for x in range(0, 1280, 2):
                if m[x, y] == 0 and a[x, y] != b[x, y]:
                    changed_outside += 1
        self.assertEqual(changed_outside, 0)
        self.assertEqual(out.getpixel((640, 300)), (255, 0, 255))                    # the centre is the edit
        self.assertNotEqual(out.getpixel((640 + 89, 300)), (255, 0, 255))            # the rim blends inward
        mask = R.oval_mask(o)
        self.assertEqual((mask.getpixel((640, 300)), mask.getpixel((10, 10))), (255, 0))

    def test_default_ovals(self):
        o = R.default_oval({"x": 640, "y": 270, "r": 200})
        self.assertEqual((o["cx"], o["cy"], o["rx"]), (640, 270, 156))
        a, b = R.default_oval(None, 0, 2), R.default_oval(None, 1, 2)
        self.assertLess(a["cx"], b["cx"])
        c = R.clamp_oval({"cx": -5, "cy": 9999, "rx": 2, "ry": 5000})
        self.assertEqual((c["cx"], c["cy"], c["rx"], c["ry"]), (0, 720, 8, 360))


def pose(label, t, faces, move_s=0.3):
    return R._pose(label, t, {k: {"want": v} for k, v in faces.items()}, move_s)


class TimelineTest(unittest.TestCase):
    def test_poses_from_beats_overshoot_and_opening_hold(self):
        beats = [{"t_start": 34.0, "character": "Sidney", "expression": "skeptical", "eyes_and_gaze": "narrowed",
                  "hold_or_move": "hold", "intensity": "subtle"},
                 {"t_start": 34.2, "character": "Sidney", "expression": "total shock", "hold_or_move": "move", "intensity": "big"},
                 {"t_start": 35.3, "character": "Sidney", "expression": "indignant glare", "hold_or_move": "move", "intensity": "clear"},
                 {"t_start": 35.0, "character": "Nobody", "expression": "ignored"}]
        ps = R.poses_from_beats(beats, 33.9, 2.0, {"sidney": "sid"})
        self.assertEqual([p["label"] for p in ps], ["skeptical", "total shock (overshoot)", "total shock", "indignant glare"])
        self.assertEqual(ps[0]["t"], 0.0)
        self.assertEqual(ps[0]["faces"], {"sid": {"want": "skeptical; narrowed"}})    # the opening hold is pose 0's face
        self.assertIn("EXTREME", ps[1]["faces"]["sid"]["want"])
        self.assertAlmostEqual(ps[1]["t"], 0.3, places=2)
        self.assertGreater(ps[2]["t"], ps[1]["t"])
        self.assertEqual(ps[3]["move_s"], R.MOVE_S["clear"])
        none = R.poses_from_beats([], 0, 2.0, {})
        self.assertEqual((len(none), none[0]["faces"]), (1, {}))

    def test_timeline_holds_moves_and_living_holds(self):
        ps = [pose("as is", 0, {}), pose("shock+", 0.25, {"s": "x"}, 0.23), pose("shock", 0.48, {"s": "y"}, 0.22),
              pose("glare", 1.25, {"s": "z"}, 0.35)]
        seg = R.timeline(ps, 2.0)
        self.assertEqual([(s["kind"], s["a"], s["b"]) for s in seg],
                         [("hold", 0, 0), ("move", 0, 1), ("move", 1, 2), ("live", 2, 2), ("move", 2, 3), ("live", 3, 3)])
        self.assertEqual((seg[0]["t0"], seg[0]["t1"]), (0.0, 0.25))                 # 0.25 s: a plain hold
        self.assertAlmostEqual(seg[1]["t1"], 0.48, places=3)                         # the owner's shot 13 timing
        self.assertEqual((seg[3]["t0"], seg[3]["t1"]), (0.7, 1.25))
        self.assertEqual((seg[5]["t0"], seg[5]["t1"]), (1.6, 2.0))                  # 0.4 s: a living hold
        short = R.timeline([pose("a", 0, {}), pose("b", 0.5, {"s": "x"}, 0.3), pose("c", 0.85, {"s": "y"}, 0.1)], 1.2)
        self.assertEqual([s["kind"] for s in short], ["live", "move", "move", "hold"])   # a 0.05 s hold goes to the move
        self.assertEqual(short[1]["t1"], 0.85)
        self.assertEqual(seg[-1]["t1"], 2.0)
        for a, b in zip(seg, seg[1:]):
            self.assertAlmostEqual(a["t1"], b["t0"], places=3)                       # no gap, no overlap
        self.assertEqual([R.clip_name(s) for s in R.clips_needed(seg)], ["mv-0-1", "mv-1-2", "hold-2", "mv-2-3", "hold-3"])
        same = R.timeline([pose("a", 0, {"s": "x"}), pose("b", 1.0, {"s": "x"})], 2.0)  # same face: no move
        self.assertEqual([s["kind"] for s in same], ["live"])

    def test_ease_out_and_natural_speed(self):
        fr = list(range(33))
        e = R.ease_out(fr, 6)
        self.assertEqual((e[0], e[-1]), (0, 32))
        steps = [b - a for a, b in zip(e, e[1:])]
        self.assertTrue(all(x >= y for x, y in zip(steps, steps[1:])), steps)          # fast start, settling end
        self.assertGreater(e[1], 32 / 5)
        n = R.natural(fr, 60)
        self.assertEqual(n[:3], [0, 1, 1])                                            # 16 fps clip on 25 fps frames
        self.assertEqual(n[52], round(52 * 16 / 25) % 33)                             # loops when the hold is longer

    def test_background_is_locked_outside_the_character_box(self):
        base = Image.new("RGB", (1280, 720), (20, 40, 60))
        still = Image.new("RGB", (1280, 720), (20, 40, 61))
        red = [Image.new("RGB", (1280, 720), (250, 0, 0))] * 33
        o = {"cx": 640, "cy": 300, "rx": 60, "ry": 60}
        lock = R.lock_mask([o])
        seg = [{"kind": "hold", "a": 0, "b": 0, "t0": 0.0, "t1": 0.2}, {"kind": "move", "a": 0, "b": 1, "t0": 0.2, "t1": 0.6}]
        frames = list(R.compose(seg, 15, lambda i: still, lambda n: red, base, lock))
        self.assertEqual(len(frames), 15)
        self.assertEqual(frames[0].getpixel((5, 5)), (20, 40, 61))                    # holds show the pose's still
        mv = frames[8]
        x0, y0, x1, y1 = R.lock_box([o])
        self.assertEqual(mv.getpixel((640, 400)), (250, 0, 0))                        # inside: the clip
        for p in ((5, 5), (x0 - 3 * R.LOCK_FEATHER, 400), (x1 + 3 * R.LOCK_FEATHER, 700), (640, max(0, y0 - 3 * R.LOCK_FEATHER))):
            self.assertEqual(mv.getpixel(p), (20, 40, 60), p)                          # outside: the base, exactly


class PromptTest(unittest.TestCase):
    def test_eyeline_in_every_face_prompt(self):
        left = R.eyeline_text("left", "Mortimer")
        self.assertIn("screen-left", left)
        self.assertIn("toward Mortimer", left)
        self.assertIn("not at the camera", left)
        self.assertIn("screen-right", R.eyeline_text("right", "the others"))
        self.assertIn("straight at the viewer", R.eyeline_text("left", "M", "glares straight into the camera"))
        t = R.face_template("Sidney", "thin pencil moustache.", "total shock", left)
        self.assertIn("Sidney (thin pencil moustache)", t)
        self.assertIn("screen-left", t)
        self.assertIn("Do not add glasses", t)
        self.assertIn("never a huge wide-open mouth", t)
        g = R.with_rules("Sidney gasps, eyes wide.", left)                           # GPT left the eyeline out
        self.assertIn("screen-left", g)
        self.assertIn("Do not add glasses", g)
        self.assertEqual(R.with_rules(g, left), g)                                     # not added twice

    def test_graphs_ported_from_the_owner_scripts(self):
        g = R.edit_graph("in.png", "mask.png", "shock", 5, "p")
        self.assertEqual(g["mk"], {"class_type": "LoadImageMask", "inputs": {"image": "mask.png", "channel": "red"}})
        self.assertEqual(g["nm2"]["inputs"], {"samples": ["le", 0], "mask": ["mk", 0]})
        self.assertEqual(g["k"]["inputs"]["latent_image"], ["nm2", 0])
        self.assertEqual((g["k"]["inputs"]["steps"], g["k"]["inputs"]["cfg"]), (40, 4.0))
        self.assertEqual(g["u"]["inputs"]["unet_name"], "qwen_image_edit_2511_fp8mixed.safetensors")
        f = R.flf_graph("a.png", "b.png", "moves", 9, "mv")
        w = f["w"]["inputs"]
        self.assertEqual((f["w"]["class_type"], w["width"], w["height"], w["length"]), ("WanFirstLastFrameToVideo", 1280, 720, 33))
        self.assertEqual((w["start_image"], w["end_image"]), (["a", 0], ["b", 0]))
        k1, k2 = f["k1"]["inputs"], f["k2"]["inputs"]
        self.assertEqual((k1["steps"], k1["cfg"], k1["start_at_step"], k1["end_at_step"], k1["model"]), (4, 1.0, 0, 2, ["sh", 0]))
        self.assertEqual((k2["start_at_step"], k2["end_at_step"], k2["latent_image"], k2["model"]), (2, 4, ["k1", 0], ["sl", 0]))
        self.assertEqual((f["sh"]["inputs"]["shift"], f["cv"]["inputs"]["fps"]), (5.0, 16))
        self.assertEqual(f["lh"]["inputs"]["lora_name"], "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors")
        self.assertEqual(f["ll"]["inputs"]["lora_name"], "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors")
        self.assertTrue(f["p"]["inputs"]["text"].endswith("Static locked-off camera, no zoom. Flat 2D cartoon, same drawing."))

    def test_estimate(self):
        e = R.estimate(3, 0, [1.09, 1.09])
        self.assertEqual((e["minutes"], e["minutes_max"]), (13.0, 14.5))
        self.assertEqual(e["usd_typical"], round(1.09 * 13 / 60, 2))
        self.assertEqual(e["usd_max"], round(1.09 * 14.5 * 1.25 / 60, 2))
        e = R.estimate(0, 4, [1.09, 1.09, 2.09])
        self.assertEqual(e["minutes"], 20.0)
        self.assertEqual(e["usd_max"], round(2.09 * 20 * 1.25 / 60, 2))
        self.assertEqual(R.estimate(0, 0, [1.09])["usd_max"], 0)


class ProposalTest(unittest.TestCase):
    def test_new_proposals_are_validated(self):
        p = SC.validate_proposal("pose", "2:1", {"type": "redo_pose", "prompt": "Shock, eyes screen-left."})
        self.assertEqual(p["type"], "redo_pose")
        with self.assertRaises(ValueError):
            SC.validate_proposal("pose", "2:1", {"type": "redo_pose"})                              # no prompt
        with self.assertRaises(ValueError):
            SC.validate_proposal("pose", "2:1", {"type": "redo_pose", "prompt": "x", "seed": 3})      # unknown field
        with self.assertRaises(ValueError):
            SC.validate_proposal("pose", "2:1", {"type": "redo_still", "prompt": "x"})               # not this step's
        e = SC.validate_proposal("pose", "2:1", {"type": "edit_beat", "shot": 2, "beat_index": 0, "fields": {"intensity": "big"}})
        self.assertEqual(e["shot"], 2)
        with self.assertRaises(ValueError):
            SC.validate_proposal("pose", "2:1", {"type": "edit_beat", "shot": 3, "beat_index": 0, "fields": {"intensity": "big"}})
        r = SC.validate_proposal("clip", "2", {"type": "reanimate_shot", "move_prompts": {"1": "snap", "hold-2": "tremble"}})
        self.assertEqual(r["move_prompts"], {"1": "snap", "hold-2": "tremble"})
        self.assertNotIn("move_prompts", SC.validate_proposal("clip", "2", {"type": "reanimate_shot"}))
        with self.assertRaises(ValueError):
            SC.validate_proposal("clip", "2", {"type": "reanimate_shot", "move_prompts": {"start": "x"}})
        with self.assertRaises(ValueError):
            SC.validate_proposal("still", "2", {"type": "reanimate_shot"})
        self.assertIn("only the face", SC.describe(p))
        self.assertIn("2 move prompt(s)", SC.describe(r))


# ================================================================== API and jobs
def png(path: Path, im: Image.Image) -> Path:
    im.save(path)
    return path


class FakeComfy:
    """ComfyUI for both graphs: a masked edit returns a flat magenta picture at the edit model's size; a Wan clip returns
    a real tiny MP4 (so the assembly can decode it)."""

    def __init__(self, clip: bytes = b""):
        self.have, self.installed, self.graphs, self.uploads, self.headers = set(), [], [], [], []
        self.clip = clip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(dict(request.headers))
        p = request.url.path
        if p == "/system_stats":
            return httpx.Response(200, json={})
        if p.startswith("/models/"):
            folder = p.split("/", 2)[2]
            return httpx.Response(200, json=[f for (fo, f) in self.have if fo == folder])
        if p == "/v2/manager/queue/install_model":
            self.installed.append(json.loads(request.content))
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
            g = self.graphs[int(pid[1:]) - 1]
            out = ({"s": {"images": [{"filename": f"edit{pid}_00001_.png", "subfolder": "", "type": "output"}]}} if "mk" in g else
                   {"sv": {"videos": [{"filename": f"flf{pid}_00001_.mp4", "subfolder": "video", "type": "output"}]}})
            return httpx.Response(200, json={pid: {"status": {"completed": True, "status_str": "success"}, "outputs": out}})
        if p == "/view":
            name = request.url.params["filename"]
            if name.startswith("edit"):
                b = io_png(Image.new("RGB", (1392, 752), (255, 0, 255)))
                return httpx.Response(200, content=b)
            return httpx.Response(200, content=self.clip)
        return httpx.Response(404)


def io_png(im: Image.Image) -> bytes:
    import io
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


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
                        Character(key="sid", name="Sidney", visual_description="thin pencil moustache"),
                        Character(key="win", name="Winifred", visual_description="grey bun")])
            # the family-side seating master: two white heads on a green room, Sidney left, Winifred right
            m = Image.new("RGB", (1920, 1080), (60, 100, 70))
            d = ImageDraw.Draw(m)
            for x in (600, 1300):
                d.ellipse((x - 70, 330, x + 70, 470), fill=(255, 255, 255), outline=(0, 0, 0), width=8)
                d.line((x - 30, 380, x - 10, 380), fill=(0, 0, 0), width=6)
            d.rectangle((0, 900, 1919, 1079), fill=(120, 60, 30))
            storage().put_file("episodes/x/fam.png", png(tmp / "fam.png", m), "image/png")
            storage().put_file("episodes/x/mort.png", png(tmp / "mort.png", Image.new("RGB", (1280, 720), (90, 90, 90))), "image/png")
            storage().put_file("episodes/x/audio.wav", wav(tmp / "a.wav", 8.0), "audio/wav")
            fam = Asset(kind="still", label="fam", storage_key="episodes/x/fam.png", content_type="image/png")
            mo = Asset(kind="still", label="mort", storage_key="episodes/x/mort.png", content_type="image/png")
            aa = Asset(kind="audio", label="voice", storage_key="episodes/x/audio.wav", content_type="audio/wav")
            db.add_all([fam, mo, aa])
            db.flush()
            tr = {"person_map": {"S1": "mort"}, "lines": [
                {"id": "l1", "start": 0.2, "end": 1.8, "text": "I leave it all", "speaker": "S1",
                 "words": [{"start": 0.2, "end": 0.5, "word": "I"}, {"start": 0.6, "end": 1.8, "word": "leave"}]}]}
            ep = Episode(title="Reacts", audio_asset_id=aa.id, audio_transcript=tr)
            db.add(ep)
            db.flush()
            self.eid, self.fam = ep.id, fam.id
            fv = {"asset_id": fam.id, "at": 0, "source": "still", "note": ""}
            mv = {"asset_id": mo.id, "at": 0, "source": "still", "note": ""}
            db.add(Setting(key=f"shotframes:{ep.id}", value={"sides": {"study": ["mort"], "family": ["sid", "win"]}, "shots": [
                {"index": 1, "t0": 0.0, "t1": 2.0, "side": "study", "people": ["mort"], "shot": "medium", "versions": [mv],
                 "chosen": mo.id, "approved": True},
                {"index": 2, "t0": 2.0, "t1": 4.0, "side": "family", "people": ["sid"], "shot": "close", "versions": [fv],
                 "chosen": fam.id, "approved": False},
                {"index": 3, "t0": 4.0, "t1": 6.0, "side": "family", "people": ["sid", "win"], "shot": "wide", "versions": [fv],
                 "chosen": fam.id, "approved": True}]}))
            db.add(Setting(key=f"acting:{ep.id}", value={"result": {"shots": [{"shot": 2, "beats": [
                {"t_start": 2.6, "t_end": 3.0, "character": "Sidney", "expression": "total shock", "eyes_and_gaze": "eyes snap wide",
                 "hold_or_move": "move", "intensity": "clear"},
                {"t_start": 3.2, "t_end": 4.0, "character": "Sidney", "expression": "indignant glare", "hold_or_move": "move",
                 "intensity": "clear"}]}]}}))
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
        return f"/api/episodes/{self.eid}/reactions{tail}"

    def shot(self, t, i):
        return next(s for s in t["shots"] if s["index"] == i)

    def ready_shot2(self):
        """The family master picked and shot 2's crop approved (both free, the owner's clicks)."""
        r = self.c.put(self.url("/masters"), json={"side": "family", "asset_id": self.fam})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post(self.url("/2/crop/approve"), json={"approved": True})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class ApiTest(ApiBase):
    def test_rows_masters_crop_and_poses(self):
        t = self.c.get(self.url()).json()
        self.assertEqual([s["index"] for s in t["shots"]], [2, 3])             # shot 1: Mortimer talks
        s2 = self.shot(t, 2)
        self.assertEqual((s2["kind"], s2["blocked"]), ("close", "pick the seating master for this side of the room first"))
        self.assertEqual(self.shot(t, 3)["kind"], "group")
        fam = next(m for m in t["masters"] if m["side"] == "family")
        self.assertIsNone(fam["chosen"])                                       # suggested, never used by itself
        self.assertEqual(fam["suggested"], self.fam)                           # the approved wide still of that side
        self.assertEqual(fam["eyeline_default"], "left")                        # listeners look screen-left
        self.assertEqual(next(m for m in t["masters"] if m["side"] == "study")["eyeline_default"], "right")
        # an unapproved still cannot be a master; the approved wide can
        self.assertEqual(self.c.put(self.url("/masters"), json={"side": "family", "asset_id": 9999}).status_code, 409)
        self.assertEqual(self.c.put(self.url("/masters"), json={"side": "../x", "eyeline": "left"}).status_code, 422)
        t = self.c.put(self.url("/masters"), json={"side": "family", "asset_id": self.fam}).json()
        s2 = self.shot(t, 2)
        self.assertEqual(s2["blocked"], "")
        c = s2["crop"]
        self.assertLess(abs(c["x"] + c["w"] / 2 - 600), 25)                     # centred on Sidney's head
        self.assertAlmostEqual(c["w"] / c["h"], 16 / 9, places=2)
        self.assertFalse(s2["crop_approved"])
        self.assertTrue(s2["base_url"])
        self.assertLess(abs(s2["ovals"]["sid"]["cx"] - 640), 40)
        s3 = self.shot(t, 3)
        self.assertLess(s3["ovals"]["sid"]["cx"], s3["ovals"]["win"]["cx"])
        # poses from the beats: as it is, shock, glare; each prompt carries the eyeline toward Mortimer
        self.assertEqual([p["label"] for p in s2["poses"]], ["as it is", "total shock", "indignant glare"])
        pr = s2["poses"][1]["faces"]["sid"]["prompt"]
        self.assertEqual((pr["source"], pr["label"]), ("template", R.TEMPLATE_LABEL))
        self.assertIn("screen-left", pr["text"])
        self.assertIn("toward Mortimer", pr["text"])
        self.assertEqual(s2["animate_blocked"], "approve the crop first")
        # 0-0.6 s living hold, move to shock (0.35 s), 0.25 s still hold, move to glare, living hold to the end
        self.assertEqual([m["name"] for m in s2["moves"]], ["hold-0", "mv-0-1", "mv-1-2", "hold-2"])
        self.assertEqual(s2["estimate_animate"]["clips"], 4)
        self.assertEqual(s2["estimate_poses"]["edits"], 2)
        # the owner moves the crop: kept 16:9 inside the master, approval and ovals start again
        t = self.c.put(self.url("/2/crop"), json={"cx": 1900, "cy": 100, "w": 800}).json()
        c = self.shot(t, 2)["crop"]
        self.assertEqual((c["x"] + c["w"], c["y"], c["source"]), (1920, 0, "owner"))
        t = self.c.put(self.url("/2/oval"), json={"character": "sid", "cx": 600, "cy": 300, "rx": 100, "ry": 110}).json()
        self.assertEqual(self.shot(t, 2)["ovals"]["sid"]["source"], "owner")
        self.assertEqual(self.c.put(self.url("/2/oval"), json={"character": "win", "cx": 1, "cy": 1, "rx": 9, "ry": 9}).status_code, 422)
        # pose edits (free): a changed face withdraws the approval; the eyeline is kept in an owner's prompt
        t = self.c.put(self.url("/2/poses/1"), json={"faces": {"sid": "smug grin"}, "prompts": {"sid": "Sidney grins."}}).json()
        p1 = self.shot(t, 2)["poses"][1]
        self.assertEqual(p1["faces"]["sid"]["want"], "smug grin")
        self.assertIn("screen-left", p1["faces"]["sid"]["prompt"]["text"])
        self.assertEqual(self.c.put(self.url("/2/poses/0"), json={"t": 1.0}).status_code, 422)
        t = self.c.post(self.url("/2/poses"), json={"after": 1}).json()
        self.assertEqual(len(self.shot(t, 2)["poses"]), 4)
        t = self.c.delete(self.url("/2/poses/2")).json()
        self.assertEqual(len(self.shot(t, 2)["poses"]), 3)
        self.assertEqual(self.c.delete(self.url("/2/poses/0")).status_code, 409)
        t = self.c.post(self.url("/2/poses/from-beats")).json()
        self.assertEqual(self.shot(t, 2)["poses"][1]["label"], "total shock")
        t = self.c.put(self.url("/2/moves"), json={"move_prompts": {"1": "Sidney recoils.", "hold-1": ""}}).json()
        mv = next(m for m in self.shot(t, 2)["moves"] if m["name"] == "mv-0-1")
        self.assertEqual((mv["text"], mv["source"]), ("Sidney recoils.", "owner"))
        self.assertEqual(self.c.put(self.url("/2/moves"), json={"move_prompts": {"start": "x"}}).status_code, 422)
        # the guide's steps 6-8
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]
        self.assertTrue(all(g[k]["available"] for k in ("closeups", "faces", "movement")))
        self.assertEqual(g["closeups"]["detail"], "0 of 2 reaction shots have an approved crop")
        self.assertEqual(g["faces"]["status"], "not_started")

    def test_write_prompt_with_and_without_gpt(self):
        self.ready_shot2()
        # no OpenAI key: the labelled template, nothing to confirm
        t = self.c.post(self.url("/2/poses/1/write-prompt"), json={}).json()
        self.assertEqual(self.shot(t, 2)["poses"][1]["faces"]["sid"]["prompt"]["label"], R.TEMPLATE_LABEL)
        from oddstudio import prompt_writer as PW
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        from test_guided_generation import openai_response
        with new_session() as db:
            put_secrets(db, {"openai_api_key": FAKE_OPENAI})
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=openai_response("Sidney's eyes pop wide, brows fly up, jaw drops."))
        PW.set_test_http_client(httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            self.assertEqual(self.c.post(self.url("/2/poses/1/write-prompt"), json={}).status_code, 409)
            self.assertEqual(seen, [])                                          # nothing sent without the price
            t = self.c.post(self.url("/2/poses/1/write-prompt"), json={"confirm_usd": 1}).json()
        finally:
            PW.set_test_http_client(None)
        self.assertEqual(len(seen), 1)
        self.assertIn("screen-left", seen[0]["input"])                          # GPT is told the eyeline
        pr = self.shot(t, 2)["poses"][1]["faces"]["sid"]["prompt"]
        self.assertEqual(pr["source"], "gpt")
        self.assertTrue(pr["text"].startswith("Sidney's eyes pop wide"))
        self.assertIn("screen-left", pr["text"])                                # made sure of, though GPT left it out
        self.assertNotIn(FAKE_OPENAI, json.dumps(t))

    def test_paid_runs_need_rented_mode_approvals_confirmation_and_cap_room(self):
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": 5})
        self.assertEqual(r.status_code, 409)                                     # no master, no crop yet
        self.c.put(self.url("/masters"), json={"side": "family", "asset_id": self.fam})
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": 5})
        self.assertIn("approve the crop", r.json()["detail"])
        t = self.c.post(self.url("/2/crop/approve"), json={"approved": True}).json()
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": 5})
        self.assertIn("Rented", r.json()["detail"])
        self.rented()
        r = self.c.post(self.url("/2/poses/generate"), json={})
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm that amount", r.json()["detail"])
        est = self.shot(self.c.get(self.url()).json(), 2)["estimate_poses"]
        self.assertEqual(est["edits"], 2)
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": est["usd_max"] - 0.01})
        self.assertEqual(r.status_code, 409)
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 0.1})
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("monthly GPU cap", r.json()["detail"])
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 50})
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        from oddstudio.db import new_session
        from oddstudio.models import Job
        with new_session() as db:
            j = db.get(Job, r.json()["id"])
            self.assertEqual((j.kind, j.payload["backend"], j.payload["poses"]), ("reaction_poses", "gpu", [1, 2]))
        self.assertIn("already going", self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": 5}).json()["detail"])
        r = self.c.post(self.url("/2/animate"), json={"confirm_usd": 5})
        self.assertEqual(r.status_code, 409)
        self.assertIn("approve pose(s) 1, 2 first", r.json()["detail"])
        self.assertEqual(self.c.post(self.url("/2/poses/1/approve"), json={"take_id": "nope"}).status_code, 404)

    def test_pose_and_clip_threads_offer_the_new_proposals(self):
        self.ready_shot2()
        r = self.c.get("/api/shot-chat/thread", params={"step": "pose", "item": "2:1", "episode_id": self.eid})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["proposals"], ["note_only", "redo_pose", "edit_beat"])
        self.assertEqual(self.c.get("/api/shot-chat/thread", params={"step": "pose", "item": "2-1", "episode_id": self.eid}).status_code, 422)
        r = self.c.get("/api/shot-chat/thread", params={"step": "clip", "item": "2", "episode_id": self.eid})
        self.assertEqual(r.json()["proposals"], ["note_only", "reanimate_shot"])     # a reaction shot's clip thread
        r = self.c.get("/api/shot-chat/thread", params={"step": "clip", "item": "1", "episode_id": self.eid})
        self.assertEqual(r.json()["proposals"], ["note_only", "rerender_shot"])      # other shots keep the stick clip
        _reply, prop, why = SC.parse_reply("clip", "2", json.dumps({"reply": "ok", "proposal": {"type": "rerender_shot", "settings": {}}}),
                                           ("note_only", "reanimate_shot"))
        self.assertIsNone(prop)
        self.assertIn("not a change this step can make", why)
        from oddstudio.db import new_session
        with new_session() as db:
            ref = SC.Ref(episode_id=self.eid, step="pose", item="2:1")
            cx = SC.build_context(db, ref)
            self.assertIn("reaction shot 2", cx["item"])
            self.assertIn("screen-left", cx["current_prompt"]["sid"])
            self.assertTrue(any("total shock" in b for b in cx["acting_beats"]))
            self.assertEqual(SC.thread_id(ref), "pose:2:1")
            cost = SC.proposal_cost(db, ref, {"type": "redo_pose", "prompt": "x"})
            self.assertGreater(cost["usd"], 0)
            cx = SC.build_context(db, SC.Ref(episode_id=self.eid, step="clip", item="2"))
            self.assertIn("1", cx["current_prompt"])
        # applying a paid redo_pose without the price is refused and starts nothing
        from oddstudio.db import new_session as ns
        with ns() as db:
            ref = SC.Ref(episode_id=self.eid, step="pose", item="2:1")
            SC.add_messages(db, ref, [{"id": "m1", "role": "assistant", "text": "redo", "at": 0,
                                       "proposal": {"type": "redo_pose", "prompt": "Sidney gapes, eyes screen-left."},
                                       "proposal_status": "pending"}])
            db.commit()
        body = {"step": "pose", "item": "2:1", "episode_id": self.eid, "message_id": "m1"}
        r = self.c.post("/api/shot-chat/apply", json=body)
        self.assertEqual(r.status_code, 409)
        self.rented()
        cost = self.c.get("/api/shot-chat/thread", params={"step": "pose", "item": "2:1", "episode_id": self.eid}).json()
        usd = cost["messages"][0]["cost"]["usd"]
        r = self.c.post("/api/shot-chat/apply", json={**body, "confirm_usd": usd})
        self.assertEqual(r.status_code, 200, r.text)
        t = self.c.get(self.url()).json()
        p1 = self.shot(t, 2)["poses"][1]
        self.assertEqual(p1["faces"]["sid"]["prompt"]["source"], "owner")
        self.assertEqual(self.shot(t, 2)["run"]["poses"], [1])


@unittest.skipUnless(Path("/usr/bin/ffmpeg").exists(), "needs FFmpeg")
class JobTest(ApiBase):
    ffmpeg = True

    def test_poses_then_animation_end_to_end(self):
        self.rented()
        clip = Path(tempfile.mkdtemp()) / "clip.mp4"
        subprocess.run(["/usr/bin/ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:size=1280x720:rate=16", "-frames:v", "33",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        rp, cf = FakeRunPod(), FakeComfy(clip.read_bytes())
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(cf))
        t = self.ready_shot2()
        s2 = self.shot(t, 2)
        r = self.c.post(self.url("/2/poses/generate"), json={"confirm_usd": s2["estimate_poses"]["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["reaction_poses"])
        self.assertEqual(ran[0][:2], ("reaction_poses", "succeeded"), ran)
        self.assertEqual({b["filename"] for b in cf.installed}, {m["filename"] for m in R.QWEN_MODELS})
        self.assertEqual(len(cf.graphs), 2)                                       # one masked edit per pose
        self.assertTrue(all("nm2" in g for g in cf.graphs))
        self.assertTrue(all(h.get("user-agent") == "curl/8.7.1" for h in cf.headers))
        self.assertTrue(all(h.get("authorization", "").startswith("Bearer ") for h in cf.headers))
        self.assertIn("screen-left", cf.graphs[0]["pe"]["inputs"]["prompt"])
        t = self.c.get(self.url()).json()
        s2 = self.shot(t, 2)
        p1 = s2["poses"][1]
        self.assertEqual(len(p1["takes"]), 1)
        self.assertIsNone(p1["approved_take"])                                    # nothing approves itself
        self.assertEqual(s2["run"]["status"], "done")
        # the pose picture: magenta only inside the oval, the crop's own pixels everywhere else
        from oddstudio.db import new_session
        from oddstudio.storage import storage
        with new_session() as db:
            sessions = list(gpu.ledger(db)["sessions"].values())
            self.assertEqual([x["status"] for x in sessions], ["ended"])          # the GPU was turned off
            st = R.stored(db, self.eid)["shots"]["2"]
            take = st["poses"][1]["takes"][0]
            pose_img = Image.open(storage().local_path(take["key"])).convert("RGB")
            base = Image.open(storage().local_path(st["base_key"])).convert("RGB")
            o = st["ovals"]["sid"]
            self.assertEqual(pose_img.getpixel((int(o["cx"]), int(o["cy"]))), (255, 0, 255))
            hard = R.oval_mask(o)
            for x in range(0, 1280, 16):
                for y in range(0, 720, 16):
                    if hard.getpixel((x, y)) == 0:
                        self.assertEqual(pose_img.getpixel((x, y)), base.getpixel((x, y)), (x, y))
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]
        self.assertEqual(g["faces"]["status"], "needs_approval")
        # the owner approves both poses (pose 0 is the approved crop itself), then animates
        for i in (1, 2):
            tid = self.shot(t, 2)["poses"][i]["takes"][0]["id"]
            t = self.c.post(self.url(f"/2/poses/{i}/approve"), json={"take_id": tid}).json()
        s2 = self.shot(t, 2)
        self.assertEqual(s2["animate_blocked"], "")
        est = s2["estimate_animate"]
        self.assertEqual(self.c.post(self.url("/2/animate"), json={}).status_code, 409)
        r = self.c.post(self.url("/2/animate"), json={"confirm_usd": est["usd_max"], "move_prompts": {"1": "Sidney recoils fast."}})
        self.assertEqual(r.status_code, 200, r.text)
        n_graphs = len(cf.graphs)
        ran = self.env.run_jobs(["reaction_animate"])
        self.assertEqual(ran[0][:2], ("reaction_animate", "succeeded"), ran)
        flf = cf.graphs[n_graphs:]
        self.assertEqual(len(flf), est["clips"])
        self.assertTrue(all(g["w"]["class_type"] == "WanFirstLastFrameToVideo" for g in flf))
        mv01 = next(g for g in flf if "-mv-0-1-" in g["sv"]["inputs"]["filename_prefix"])
        self.assertTrue(mv01["p"]["inputs"]["text"].startswith("Sidney recoils fast."))
        hold = next(g for g in flf if g["a"]["inputs"]["image"] == g["b"]["inputs"]["image"])   # a living hold
        self.assertIn("trembling", hold["p"]["inputs"]["text"])
        t = self.c.get(self.url()).json()
        s2 = self.shot(t, 2)
        c = s2["clips"][0]
        self.assertEqual((c["frames"], c["fps"]), (50, 25))
        self.assertTrue(c["preview_url"])                                         # review copy with the original audio
        self.assertIsNone(s2["approved"])
        with new_session() as db:
            from oddstudio.models import Asset
            a = db.get(Asset, c["asset_id"])
            p = storage().local_path(a.storage_key)
            probe = subprocess.run(["/usr/bin/ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                    "stream=nb_read_frames,width,height,r_frame_rate", "-of", "json", str(p)],
                                   capture_output=True, text=True)
            st = json.loads(probe.stdout)["streams"][0]
            self.assertEqual((st["width"], st["height"], st["r_frame_rate"], int(st["nb_read_frames"])), (1280, 720, "25/1", 50))
            self.assertEqual([x["status"] for x in gpu.ledger(db)["sessions"].values()], ["ended", "ended"])
        t = self.c.post(self.url("/2/approve"), json={"clip_id": c["id"]}).json()
        self.assertEqual(self.shot(t, 2)["approved"], c["id"])
        g = self.c.get(f"/api/episodes/{self.eid}/guide").json()["steps"]
        self.assertEqual(g["movement"]["detail"], "1 of 2 reaction shots approved")


if __name__ == "__main__":
    unittest.main()
