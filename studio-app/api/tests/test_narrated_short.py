"""Narrated shorts (the New short wizard, 2026-11-27): scene splitting and frame-exact timing, Gemini TTS (PCM -> WAV and
the tier rules), the prompt templates (characters as references, the house look), cost confirmation (409), the approval
gates (the autopilot waits and never approves), the Wan 2.2 graph for 9:16 and 16:9, captions, the music level, and the
chat proposals. Every provider is mocked (OpenAI SDK transport, Gemini httpx transport, WaveSpeed stubs, RunPod and
ComfyUI transports, the transcriber): no network, no cost. Only fake credentials are used."""
import base64
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from PIL import Image

from helpers import Env

from oddstudio import narrated_short as NS
from oddstudio import tts

FAKE_OPENAI = "fake-openai-credential-for-tests"
FAKE_GEMINI = "fake-gemini-credential-for-tests"
FAKE_WAVESPEED = "fake-wavespeed-credential-for-tests"
FAKE_RUNPOD = "fake-runpod-credential-for-tests"
FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
HAVE_FFMPEG = os.path.exists(FFMPEG)

SCRIPT = ("What if every lie made you smaller? Tom told his first lie on a Monday. By Tuesday, his chair felt huge. "
          "By Friday, he needed a ladder to reach the sofa. His cat started looking at him like lunch. "
          "But here's the thing. The truth made him grow back. So he told his boss the truth, and got fired, but tall.")


def openai_response(text, tin=400, tout=120):
    return {"id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": "gpt-5.5",
            "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 10}},
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": []}


def words_for(text, wps=3.0, lead=0.4):
    """Fake transcription words of `text`, evenly spaced (with a small lead-in silence)."""
    out, t = [], lead
    for w in text.split():
        out.append({"word": w, "start": round(t, 3), "end": round(t + 0.8 / wps, 3)})
        t += 1 / wps
    return out


# ================================================================== pure parts
class SceneSplitTest(unittest.TestCase):
    def test_one_scene_per_sentence_short_ones_merged(self):
        scenes = NS.split_scenes(SCRIPT)
        self.assertTrue(scenes[0].startswith("What if every lie"))
        self.assertTrue(" ".join(scenes) == " ".join(SCRIPT.split()))           # nothing lost or reordered
        # "But here's the thing." (4 words, ~1 s) is merged with the next sentence
        self.assertFalse(any(s == "But here's the thing." for s in scenes))
        for s in scenes[:-1]:
            self.assertLessEqual(NS.seconds_of(s), NS.SCENE_MAX_S + 0.01, s)

    def test_long_sentence_cut_at_commas(self):
        long = ("He walked into the office, holding a coffee the size of his head, nodding at everyone he passed, "
                "and sat down at the desk that was now taller than him.")
        parts = NS.split_scenes(long)
        self.assertGreater(len(parts), 1)
        self.assertEqual(" ".join(parts), long)

    def test_sentences_keep_their_quotes(self):
        self.assertEqual(NS.split_sentences('He said "No!" Then left.'), ['He said "No!"', "Then left."])


class TimingTest(unittest.TestCase):
    def test_scene_starts_are_the_first_words(self):
        scenes = NS.split_scenes(SCRIPT)
        words = words_for(" ".join(scenes))
        starts = NS.scene_starts(scenes, words, words[-1]["end"] + 0.5)
        self.assertEqual(starts[0], 0.0)                                         # the first scene covers the lead-in
        idx = 0
        for i, s in enumerate(scenes):
            if i:
                self.assertAlmostEqual(starts[i], words[idx]["start"], places=3)
            idx += len(s.split())
        self.assertEqual(starts, sorted(starts))

    def test_missed_words_are_interpolated_and_misheard_ones_aligned(self):
        scenes = ["One two three four five six seven.", "Eight nine ten eleven twelve.", "Thirteen fourteen fifteen."]
        words = words_for(" ".join(scenes), wps=2.0, lead=0.0)
        heard = [w for w in words if w["word"] not in ("Eight", "nine", "ten")]   # scene 2's first words were lost
        heard[0] = {**heard[0], "word": "Won"}                                     # and one word misheard
        starts = NS.scene_starts(scenes, heard, 10.0)
        self.assertEqual(starts[0], 0.0)
        self.assertGreater(starts[1], words[6]["start"])
        self.assertLess(starts[1], starts[2])
        self.assertAlmostEqual(starts[2], words[12]["start"], places=3)

    def test_no_words_spreads_by_word_count(self):
        starts = NS.scene_starts(["a b c d", "e f g h"], [], 8.0)
        self.assertEqual(starts, [0.0, 4.0])

    def test_frame_exact_and_no_drift(self):
        # 40 scenes whose starts fall between frames: counts come from absolute positions, so they never drift
        starts = [0.0] + [round(i * 3.013, 3) for i in range(1, 40)]
        end = 40 * 3.013 + 0.37
        rows = NS.timing_rows(starts, end)
        self.assertEqual(sum(r["frames"] for r in rows), round(end * 25))
        for i, r in enumerate(rows):
            self.assertEqual(r["first_frame"], round(starts[i] * 25) if i else 0)
        self.assertEqual(rows[-1]["first_frame"] + rows[-1]["frames"], round(end * 25))

    def test_clip_fit_never_speeds_up(self):
        cut = NS.fit_short(81, 16, 100)                         # 5.06 s clip, 4 s scene: the end is cut
        self.assertEqual(cut["stretch"], 1.0)
        self.assertGreater(cut["cut_s"], 1.0)
        hold = NS.fit_short(81, 16, 140)                        # 5.6 s scene: 0.54 s short: only held
        self.assertEqual(hold["stretch"], 1.0)
        self.assertAlmostEqual(hold["held_s"], 5.6 - 81 / 16, places=2)
        slow = NS.fit_short(81, 16, 160)                        # 6.4 s scene: slowed (at most 1.25x), rest held
        self.assertGreater(slow["stretch"], 1.0)
        self.assertLessEqual(slow["stretch"], NS.MAX_SLOW)
        very = NS.fit_short(33, 16, 200)                        # 8 s scene from a 2 s clip: 1.25x, then held
        self.assertEqual(very["stretch"], NS.MAX_SLOW)
        self.assertAlmostEqual(very["held_s"], 8 - 33 / 16 * 1.25, places=2)
        for f in (cut, hold, slow, very):
            self.assertGreaterEqual(f["stretch"], 1.0)

    def test_wan_length_covers_the_scene(self):
        for sec in (1.0, 2.0, 3.3, 4.0, 5.0, 9.0):
            n = NS.wan_length(sec)
            self.assertEqual((n - 1) % 4, 0)
            self.assertTrue(33 <= n <= 81)
            if sec <= 5.0:
                self.assertGreaterEqual(n / 16, sec - 1e-9)
        self.assertEqual(NS.wan_length(9.0), 81)


class CaptionAndMusicTest(unittest.TestCase):
    def test_caption_chunks(self):
        words = words_for("What if every lie made you smaller? Tom told his first lie.")
        ch = NS.caption_chunks(words)
        self.assertTrue(all(len(c["text"].split()) <= 3 for c in ch))
        self.assertTrue(all(c["text"] == c["text"].upper() for c in ch))
        self.assertTrue(any(c["text"].endswith("SMALLER?") for c in ch))          # a chunk ends with the sentence
        self.assertTrue(all(a["end"] <= b["start"] + 1e-9 for a, b in zip(ch, ch[1:])))

    def test_caption_pictures_are_drawn_in_the_short_style(self):
        from unittest import mock
        from oddstudio import config
        seen = {}

        def fake_run(cmd, **kw):
            spec = json.loads(Path(cmd[-1]).read_text())
            seen.update(spec)
            pics = [str(Path(spec["out"]) / f"line-{i:04d}.png") for i in range(len(spec["lines"]))]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"banner": None, "lines": pics}) + "\n", stderr="")
        os.environ["NODE_BIN"] = "node"
        config.reset_settings()
        try:
            with mock.patch.object(NS.shutil, "which", return_value="/usr/bin/node"), mock.patch.object(NS.subprocess, "run", fake_run):
                chunks = NS.caption_chunks(words_for("One two three four five."))
                out, warn = NS.render_captions(chunks, (720, 1280), Path(tempfile.mkdtemp()), print)
        finally:
            os.environ.pop("NODE_BIN", None)
            config.reset_settings()
        self.assertEqual(warn, "")
        self.assertEqual(seen["mode"], "short_captions")
        self.assertTrue(seen["caption_font"].endswith("Anton-Regular.ttf"))
        self.assertEqual([x["text"] for x in seen["lines"]], ["ONE TWO THREE", "FOUR FIVE."])
        self.assertEqual([(a, b) for a, b, _ in out], [(c["start"], c["end"]) for c in chunks])
        self.assertEqual(NS.render_captions([], (720, 1280), Path(tempfile.mkdtemp()), print), ([], ""))   # captions off

    def test_gated_rms_and_music_gain(self):
        import numpy as np
        rate = 16000
        t = np.arange(rate) / rate
        tone = 0.5 * np.sin(2 * math.pi * 220 * t)
        x = np.concatenate([tone, np.zeros(rate * 3)])                            # 1 s of tone, 3 s of silence
        db = NS.gated_rms_db(x, rate)
        self.assertAlmostEqual(db, 20 * math.log10(0.5 / math.sqrt(2)), places=1)   # the silence does not count
        self.assertIsNone(NS.gated_rms_db(np.zeros(rate), rate))
        self.assertEqual(NS.music_gain_db(-20.0, -10.0), -16.0)                    # -10 -> -26 = 6 dB under -20
        self.assertEqual(NS.music_gain_db(-18.0, -30.0), 6.0)
        g = NS.mix_graph(-16.0)
        self.assertIn("volume=-16.000dB", g)
        self.assertIn("normalize=0", g)
        self.assertNotIn("sidechain", g)                                           # no ducking
        self.assertNotIn("[2:a]", NS.mix_graph(None))


class PromptTest(unittest.TestCase):
    def test_every_picture_request_carries_the_references_and_the_look(self):
        full = NS.picture_request("Tom stares at a huge chair.", ["Tom", "Ann"], "9:16")
        self.assertIn("image 1 is Tom", full)
        self.assertIn("image 2 is Ann", full)
        self.assertIn("never redesign", full)
        self.assertIn("3D-style background", full)
        self.assertIn("bright readable colours", full)
        self.assertIn("9:16", full)
        t = NS.picture_template("Tom told his first lie.", ["Tom"])
        self.assertIn("reference image 1", t)
        self.assertIn("3D-style background", t)
        self.assertIn("reference image N", NS.PROMPTS_SYSTEM)
        self.assertIn("never describe or redesign", NS.PROMPTS_SYSTEM)
        self.assertIn("static camera", NS.animation_template("x").lower())

    def test_script_template_and_word_target(self):
        for part in ("Hook", "Setup", "Escalation", "Pivot", "Payoff", "LAST words", "3.7"):
            self.assertIn(part, NS.SCRIPT_SYSTEM)
        self.assertEqual(NS.target_words(30), 111)
        msg = NS.script_message({"title": "T", "hook": "H", "twist": "X", "label": "legend"}, "history", ["Tom"], 60)
        self.assertIn("about 222 words", msg)

    def test_model_json_is_read_with_fences_and_bare_lists(self):
        self.assertEqual(NS.parse_json('```json\n{"ideas": [1]}\n```')["ideas"], [1])
        self.assertEqual(NS.parse_json('Here: [{"scene": 1}]', "scenes")["scenes"], [{"scene": 1}])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            NS.parse_json("no json at all")
        with self.assertRaises(HTTPException):
            NS.parse_json("[1, 2]")                      # a list only when the caller names its key

    def test_ideas_true_ones_are_flagged(self):
        raw = [{"title": "A", "label": "true"}, {"title": "B", "label": "legend"}, {"title": "C", "label": "weird"}, {"hook": "no title"}]
        ideas = NS.clean_ideas(raw)
        self.assertEqual([(i["title"], i["label"], i["check"]) for i in ideas],
                         [("A", "true", True), ("B", "legend", False), ("C", "fiction", False)])


class TtsTest(unittest.TestCase):
    def test_pcm_to_wav(self):
        pcm = struct.pack("<" + "h" * 2400, *([1000, -1000] * 1200)) + b"\x01"     # 0.1 s + an odd byte
        w = tts.pcm_to_wav(pcm)
        f = Path(tempfile.mkdtemp()) / "x.wav"
        f.write_bytes(w)
        with wave.open(str(f), "rb") as r:
            self.assertEqual((r.getframerate(), r.getsampwidth(), r.getnchannels(), r.getnframes()), (24000, 2, 1, 2400))
        self.assertAlmostEqual(tts.pcm_seconds(pcm[:-1]), 0.1)

    def test_tier_rules(self):
        cfg = {"tts_usd_in": 0.5, "tts_usd_out": 10.0}
        with self.assertRaises(ValueError):
            tts.estimate(SCRIPT, cfg, paid_tier=False, use_free_tier=False)
        free = tts.estimate(SCRIPT, cfg, paid_tier=False, use_free_tier=True)
        self.assertEqual((free["tier"], free["usd_max"]), ("free", 0.0))
        self.assertIn("Google may use", free["warning"])
        paid = tts.estimate(SCRIPT, cfg, paid_tier=True, use_free_tier=False)
        self.assertEqual(paid["tier"], "paid")
        self.assertGreater(paid["usd_max"], paid["usd_typical"])
        self.assertEqual(paid["warning"], "")
        both = tts.estimate(SCRIPT, cfg, paid_tier=True, use_free_tier=True)
        self.assertEqual(both["usd_max"], paid["usd_max"])                        # priced at the paid tier

    def test_long_text_in_pieces_and_request_body(self):
        long = " ".join(["This is one sentence of narration."] * 200)
        pieces = tts.chunk_text(long, 100)
        self.assertTrue(all(len(p.split()) <= 100 for p in pieces))
        self.assertEqual(" ".join(pieces), long)
        b = tts.request_body("Hello.", "Charon", "warm, calm narrator")
        self.assertEqual(b["generationConfig"]["responseModalities"], ["AUDIO"])
        self.assertEqual(b["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Charon")
        self.assertTrue(b["contents"][0]["parts"][0]["text"].startswith("Read this in a warm, calm narrator voice"))


class WanGraphTest(unittest.TestCase):
    def test_graph_for_vertical_and_landscape(self):
        from oddstudio.reactions import WAN_MODELS
        for fmt, (w, h) in (("9:16", (720, 1280)), ("16:9", (1280, 720))):
            self.assertEqual(NS.WAN_SIZES[fmt], (w, h))
            g = NS.wan_i2v_graph("in.png", "He waves.", 7, "pfx", w, h, 81)
            wi = g["w"]["inputs"]
            self.assertEqual(g["w"]["class_type"], "WanImageToVideo")
            self.assertEqual((wi["width"], wi["height"], wi["length"]), (w, h, 81))
            self.assertEqual(wi["start_image"], ["i", 0])
            self.assertEqual(g["uh"]["inputs"]["unet_name"], "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors")
            self.assertEqual(g["ul"]["inputs"]["unet_name"], "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors")
            self.assertIn("lightx2v_4steps_lora_v1_high_noise", g["lh"]["inputs"]["lora_name"])
            self.assertIn("lightx2v_4steps_lora_v1_low_noise", g["ll"]["inputs"]["lora_name"])
            self.assertEqual(g["sh"]["inputs"]["shift"], 5.0)
            k1, k2 = g["k1"]["inputs"], g["k2"]["inputs"]
            self.assertEqual((k1["steps"], k1["cfg"], k1["start_at_step"], k1["end_at_step"]), (4, 1.0, 0, 2))
            self.assertEqual((k2["start_at_step"], k2["end_at_step"], k2["add_noise"]), (2, 4, "disable"))
            self.assertEqual(k1["model"], ["sh", 0])
            self.assertEqual(k2["latent_image"], ["k1", 0])
            self.assertEqual(g["cv"]["inputs"]["fps"], 16)
            used = {g[n]["inputs"].get(k) for n in g for k in ("unet_name", "lora_name", "clip_name", "vae_name")}
            self.assertTrue({m["filename"] for m in WAN_MODELS} <= used)


# ================================================================== API
class WaveSpeedStub:
    def __init__(self):
        self.runs, self.uploads = [], []

    def upload(self, path):
        self.uploads.append(Path(path).name)
        return f"https://ws.example/up/{len(self.uploads)}"

    def run(self, endpoint, body, out):
        self.runs.append((endpoint, body))
        Image.new("RGB", (72, 128), (40, 160, 220)).save(out)
        return {"id": f"t{len(self.runs)}", "status": "completed", "outputs": ["https://ws.example/o"]}


class Base(unittest.TestCase):
    def setUp(self):
        from oddstudio import gpu, wavespeed
        self.env = Env().login()
        self.c = self.env.client
        self.sleep = gpu.sleep
        gpu.sleep = lambda s: None
        self.ws = WaveSpeedStub()
        wavespeed.set_test_run(self.ws.run)
        wavespeed.set_test_upload(self.ws.upload)
        from oddstudio.db import new_session
        from oddstudio.models import Character, CharacterAsset
        from oddstudio.storage import storage
        tmp = Path(tempfile.mkdtemp())
        with new_session() as db:
            c = Character(key="tom", name="Tom", visual_description="white round head, red cap")
            n = Character(key="nomaster", name="Nomaster")
            db.add_all([c, n])
            db.flush()
            f = tmp / "m.png"
            Image.new("RGB", (60, 80), (255, 255, 255)).save(f)
            storage().put_file("characters/tom/stick/master.png", f, "image/png")
            db.add(CharacterAsset(character_id=c.id, kind="master", storage_key="characters/tom/stick/master.png",
                                  status="approved", width=60, height=80))
            db.commit()
            self.tom, self.nomaster = c.id, n.id
        self.calls = []

    def tearDown(self):
        from oddstudio import analysis, comfy, gpu, prompt_writer, runpod, wavespeed
        gpu.sleep = self.sleep
        wavespeed.set_test_run(None)
        wavespeed.set_test_upload(None)
        prompt_writer.set_test_http_client(None)
        tts.set_test_transport(None)
        analysis.set_test_analysis(None, None)
        runpod.set_test_transport(None)
        comfy.set_test_transport(None)
        self.env.close()
        os.environ.pop("FFMPEG", None)

    def keys(self, **k):
        from oddstudio.db import new_session
        from oddstudio.secrets_store import put_secrets
        with new_session() as db:
            put_secrets(db, k)

    def gpt(self, answers):
        """The OpenAI SDK over a mock transport answering `answers` in order."""
        from oddstudio import prompt_writer as PW
        it = iter(answers)

        def handler(request):
            self.calls.append(json.loads(request.content))
            return httpx.Response(200, json=openai_response(next(it)))
        PW.set_test_http_client(httpx.Client(transport=httpx.MockTransport(handler)))

    def new(self, **kw):
        r = self.c.post("/api/shorts", json={"niche": "what_if", "characters": [self.tom], "format": "9:16", "seconds": 30, **kw})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def url(self, eid, tail=""):
        return f"/api/shorts/{eid}{tail}"

    def approved_script(self, eid, text=SCRIPT):
        v = self.c.put(self.url(eid, "/script"), json={"text": text}).json()
        ver = v["script"]["versions"][-1]["v"]
        r = self.c.post(self.url(eid, "/script/approve"), json={"version": ver})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def gemini(self, seconds=2.0):
        """Gemini speech over a mock transport: a tone of `seconds` as base64 PCM."""
        seen = []

        def handler(request):
            seen.append({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
            n = int(24000 * seconds)
            pcm = struct.pack("<" + "h" * n, *[int(6000 * math.sin(2 * math.pi * 200 * i / 24000)) for i in range(n)])
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": int(seconds * 32)}})
        tts.set_test_transport(httpx.MockTransport(handler))
        return seen

    def transcriber(self, text):
        from oddstudio import analysis
        analysis.set_test_analysis(transcriber=lambda cfg, audio: {"provider": "fake", "words": words_for(text),
                                                                   "duration": len(text.split()) / 3.0 + 1.0})
        r = self.c.put("/api/settings/transcription", json={"provider": "local-whisper"})
        self.assertEqual(r.status_code, 200, r.text)


class WizardTest(Base):
    def test_choose_validation(self):
        bad = [{"seconds": 31}, {"niche": "custom"}, {"characters": [self.tom, self.tom]}, {"format": "4:3"},
               {"characters": [999999]}]
        for b in bad:
            r = self.c.post("/api/shorts", json={"niche": "what_if", "characters": [self.tom], "seconds": 30, **b})
            self.assertIn(r.status_code, (404, 422), b)
        v = self.new()
        self.assertEqual(v["kind"], "narrated_short")
        self.assertEqual(v["choose"]["format"], "9:16")
        self.assertTrue(v["captions"])                                              # captions on by default
        self.assertTrue(any(o["character_id"] == self.tom for o in v["cast"]))
        self.assertEqual(v["motion"]["engines"]["code_kit"]["ready"], False)       # shown as coming soon
        ep = self.c.get(f"/api/episodes/{v['id']}").json()
        self.assertEqual(ep["episode"]["kind"] if "episode" in ep else ep.get("kind"), "narrated_short")

    def test_ideas_and_script_need_the_confirmed_price(self):
        v = self.new()
        eid = v["id"]
        self.assertEqual(self.c.post(self.url(eid, "/ideas"), json={"confirm_usd": 5}).status_code, 409)   # no key
        self.keys(openai_api_key=FAKE_OPENAI)
        ideas = {"ideas": [{"title": f"Idea {i}", "hook": "What if?", "twist": "t", "why_it_animates": "w",
                            "label": "true" if i == 0 else "fiction"} for i in range(10)]}
        self.gpt([json.dumps(ideas), SCRIPT])
        est = self.c.get(self.url(eid)).json()["estimates"]["ideas"]
        self.assertEqual(self.c.post(self.url(eid, "/ideas"), json={}).status_code, 409)
        self.assertEqual(self.c.post(self.url(eid, "/ideas"), json={"confirm_usd": est["usd_max"] / 2}).status_code, 409)
        self.assertEqual(self.calls, [])                                           # nothing sent without the price
        v = self.c.post(self.url(eid, "/ideas"), json={"confirm_usd": est["usd_max"]}).json()
        self.assertEqual(len(v["ideas"]["items"]), 10)
        self.assertTrue(v["ideas"]["items"][0]["check"])                           # true facts: check before publishing
        self.assertFalse(v["ideas"]["items"][1]["check"])
        self.assertEqual(self.c.post(self.url(eid, "/script/write"), json={"confirm_usd": 1}).status_code, 409)  # no idea yet
        v = self.c.put(self.url(eid, "/idea"), json={"idea_id": v["ideas"]["items"][0]["id"]}).json()
        self.assertEqual(v["title"], "Idea 0")
        est = v["estimates"]["script"]
        v = self.c.post(self.url(eid, "/script/write"), json={"confirm_usd": est["usd_max"]}).json()
        self.assertEqual(v["script"]["versions"][-1]["source"], "gpt")
        self.assertIsNone(v["script"]["approved"])                                 # nothing approves itself
        self.assertEqual(v["scenes"]["items"], [])
        self.assertIn("Hook", self.calls[1]["instructions"])
        # the owner approves: scenes split (free); an edit after that is a new version waiting for approval
        v = self.c.post(self.url(eid, "/script/approve"), json={"version": v["script"]["versions"][-1]["v"]}).json()
        self.assertEqual(len(v["scenes"]["items"]), len(NS.split_scenes(SCRIPT)))
        v2 = self.c.put(self.url(eid, "/script"), json={"text": SCRIPT + " The end."}).json()
        self.assertEqual(v2["script"]["approved"], v["script"]["approved"])
        self.assertEqual(self.c.post(self.url(eid, "/script/approve"), json={"version": 1}).status_code, 409)

    def test_prompts_template_free_and_gpt_priced(self):
        eid = self.new()["id"]
        self.approved_script(eid)
        v = self.c.post(self.url(eid, "/scenes/prompts"), json={"use_template": True}).json()
        s1 = v["scenes"]["items"][0]
        self.assertEqual(s1["prompt_source"], NS.TEMPLATE_LABEL)
        self.assertIn("reference image 1 (Tom)", s1["picture_prompt"])
        self.keys(openai_api_key=FAKE_OPENAI)
        n = len(v["scenes"]["items"])
        self.gpt([json.dumps({"scenes": [{"scene": i + 1, "picture": f"P{i + 1}: the character in reference image 1",
                                          "animation": f"A{i + 1}"} for i in range(n)]})])
        est = v["estimates"]["prompts"]
        self.assertEqual(self.c.post(self.url(eid, "/scenes/prompts"), json={}).status_code, 409)
        v = self.c.post(self.url(eid, "/scenes/prompts"), json={"confirm_usd": est["usd_max"]}).json()
        self.assertEqual(v["scenes"]["items"][1]["picture_prompt"], "P2: the character in reference image 1")
        self.assertIn("reference image 1 (Tom)", self.calls[0]["input"])
        self.assertIn("3D-style background", self.calls[0]["input"])
        v = self.c.put(self.url(eid, "/scenes/2"), json={"animation_prompt": "He jumps."}).json()
        self.assertEqual(v["scenes"]["items"][1]["animation_prompt"], "He jumps.")

    def test_voice_tiers_take_and_timing(self):
        eid = self.new()["id"]
        self.keys(gemini_api_key=FAKE_GEMINI)
        self.assertEqual(self.c.post(self.url(eid, "/voice"), json={"use_free_tier": True, "confirm_usd": 0}).status_code, 409)  # no script
        self.approved_script(eid)
        r = self.c.post(self.url(eid, "/voice"), json={"confirm_usd": 1})
        self.assertEqual(r.status_code, 409)                                       # neither tier ticked
        self.assertIn("tier", r.json()["detail"])
        self.assertEqual(self.c.post(self.url(eid, "/voice"), json={"voice": "Nobody", "use_free_tier": True,
                                                                     "confirm_usd": 0}).status_code, 422)
        seen = self.gemini(2.0)
        self.transcriber(" ".join(NS.split_scenes(SCRIPT)))
        r = self.c.post(self.url(eid, "/voice"), json={"voice": "Charon", "style": "warm, calm narrator", "use_free_tier": True,
                                                        "confirm_usd": 0})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["short_voice"])
        self.assertEqual(ran[0][:2], ("short_voice", "succeeded"), ran)
        self.assertTrue(seen[0]["url"].endswith("/models/gemini-2.5-flash-preview-tts:generateContent"))
        self.assertEqual(seen[0]["headers"]["x-goog-api-key"], FAKE_GEMINI)        # the key only in its header
        self.assertNotIn(FAKE_GEMINI, json.dumps(seen[0]["body"]))
        v = self.c.get(self.url(eid)).json()
        take = v["voice"]["takes"][0]
        self.assertNotIn(FAKE_GEMINI, json.dumps(v))
        self.assertEqual((take["free_tier"], take["usd"], take["fits"]), (True, 0.0, True))
        self.assertIsNone(v["voice"].get("approved"))                              # waits for the owner
        self.assertIsNone(v["timing"])
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        with new_session() as db:
            with wave.open(str(storage().local_path(db.get(Asset, take["asset_id"]).storage_key)), "rb") as w:
                self.assertEqual((w.getframerate(), w.getsampwidth(), w.getnchannels()), (24000, 2, 1))
        v = self.c.post(self.url(eid, "/voice/approve"), json={"take_id": take["id"]}).json()
        tm = v["timing"]
        self.assertEqual(tm["starts"][0], 0.0)
        self.assertEqual(len(tm["rows"]), len(v["scenes"]["items"]))
        self.assertEqual(sum(r["frames"] for r in tm["rows"]), round(tm["end"] * 25))
        # a rewritten line: the script waits for approval again and the old take no longer fits
        v = self.c.put(self.url(eid, "/scenes/2"), json={"text": "By Tuesday, his chair felt enormous."}).json()
        self.assertIsNone(v["script"]["approved"])
        self.assertEqual(len(v["scenes"]["items"][1]["pictures"]), 0)
        v = self.c.post(self.url(eid, "/script/approve"), json={"version": v["script"]["versions"][-1]["v"]}).json()
        self.assertEqual(v["scenes"]["items"][1]["text"], "By Tuesday, his chair felt enormous.")  # kept, not re-split
        self.assertFalse(v["voice"]["takes"][0]["fits"])
        self.assertIsNone(v["timing"])

    def test_paid_tier_price_must_be_confirmed(self):
        eid = self.new()["id"]
        self.keys(gemini_api_key=FAKE_GEMINI)
        self.approved_script(eid)
        self.assertEqual(self.c.put("/api/settings/short", json={"tts_paid_tier": True}).status_code, 200)
        self.assertEqual(self.c.put("/api/settings/short", json={"voice": "Nobody"}).status_code, 422)
        est = self.c.get(self.url(eid)).json()["estimates"]["voice"]
        self.assertGreater(est["usd_max"], 0)
        self.assertEqual(self.c.post(self.url(eid, "/voice"), json={"confirm_usd": 0}).status_code, 409)
        self.assertEqual(self.env.run_jobs(["short_voice"]), [])

    def test_pictures_masters_as_references_cost_and_approval(self):
        eid = self.new()["id"]
        self.approved_script(eid)
        self.keys(wavespeed_api_key=FAKE_WAVESPEED)
        self.assertEqual(self.c.post(self.url(eid, "/scenes/1/picture"), json={}).status_code, 409)
        self.assertEqual(self.c.post(self.url(eid, "/scenes/1/picture"), json={"confirm_usd": 0.03}).status_code, 409)
        r = self.c.post(self.url(eid, "/scenes/1/picture"), json={"confirm_usd": 0.04})
        self.assertEqual(r.status_code, 200, r.text)
        ran = self.env.run_jobs(["short_picture"])
        self.assertEqual(ran[0][:2], ("short_picture", "succeeded"), ran)
        endpoint, body = self.ws.runs[0]
        self.assertEqual(endpoint, "google/nano-banana-2.1/edit")
        self.assertEqual(body["images"], ["https://ws.example/up/1"])               # Tom's approved master
        self.assertEqual(self.ws.uploads, [f"master-{self.tom}.png"])
        self.assertIn("image 1 is Tom", body["prompt"])
        self.assertIn("never redesign", body["prompt"])
        self.assertEqual(body["aspect_ratio"], "9:16")
        v = self.c.get(self.url(eid)).json()
        s1 = v["scenes"]["items"][0]
        self.assertEqual(len(s1["pictures"]), 1)
        self.assertFalse(s1["picture_approved"])                                   # waits for the owner
        # all the others: the total is confirmed first
        n = len(v["scenes"]["items"]) - 1
        self.assertEqual(self.c.post(self.url(eid, "/pictures/all"), json={"confirm_usd": 0.04}).status_code, 409)
        self.assertEqual(self.c.post(self.url(eid, "/pictures/all"), json={"confirm_usd": round(0.04 * n, 4)}).status_code, 200)
        self.env.run_jobs(["short_picture"])
        v = self.c.get(self.url(eid)).json()
        self.assertTrue(all(len(s["pictures"]) == 1 and not s["picture_approved"] for s in v["scenes"]["items"]))
        aid = s1["pictures"][0]["asset_id"]
        v = self.c.post(self.url(eid, "/scenes/1/picture/approve"), json={"asset_id": aid}).json()
        self.assertTrue(v["scenes"]["items"][0]["picture_approved"])
        # a character without an approved master: nothing can be drawn
        self.c.put(self.url(eid, "/choose"), json={"niche": "what_if", "characters": [self.tom, self.nomaster], "seconds": 30})
        r = self.c.post(self.url(eid, "/scenes/2/picture"), json={"confirm_usd": 0.04})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Nomaster", r.json()["detail"])

    def test_motion_needs_rented_gpu_and_confirmation(self):
        eid = self.new()["id"]
        self.approved_script(eid)
        self.assertEqual(self.c.post(self.url(eid, "/motion"), json={"engine": "code_kit", "confirm_usd": 5}).status_code, 409)
        self.assertEqual(self.c.post(self.url(eid, "/motion"), json={"confirm_usd": 5}).status_code, 409)   # nothing approved
        v = self.c.get(self.url(eid)).json()
        self.assertEqual(v["estimates"]["motion"]["scenes"], [])

    def test_assembly_refused_until_voice_and_pictures(self):
        os.environ["FFMPEG"] = FFMPEG
        from oddstudio import config
        config.reset_settings()
        eid = self.new()["id"]
        self.approved_script(eid)
        r = self.c.post(self.url(eid, "/assemble"))
        self.assertEqual(r.status_code, 409)
        self.assertIn("narration", r.json()["detail"])


class FakeRunPod:
    def __init__(self):
        self.pods, self.calls = {}, []

    def __call__(self, method, path, json=None, params=None):
        self.calls.append((method, path, json))
        if path.startswith("/v2/catalog/gpus/"):
            return 404, {}
        if method == "POST" and path == "/v2/pods":
            pid = f"pod{len(self.pods) + 1}"
            self.pods[pid] = {"id": pid, "name": json["name"], "status": "RUNNING", "cost": 0, **json}
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
        return 404, {}


class FakeComfy:
    def __init__(self, clip: bytes):
        self.have, self.installed, self.graphs, self.clip = set(), [], [], clip

    def __call__(self, request):
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
            return httpx.Response(200, json={"name": name})
        if p == "/prompt":
            self.graphs.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": f"p{len(self.graphs)}", "node_errors": {}})
        if p.startswith("/history/"):
            pid = p.rsplit("/", 1)[1]
            return httpx.Response(200, json={pid: {"status": {"completed": True, "status_str": "success"},
                                                   "outputs": {"sv": {"videos": [{"filename": f"c{pid}.mp4", "subfolder": "video", "type": "output"}]}}}})
        if p == "/view":
            return httpx.Response(200, content=self.clip)
        return httpx.Response(404)


@unittest.skipUnless(HAVE_FFMPEG, "needs FFmpeg")
class EndToEndTest(Base):
    """Script -> voice (free tier) -> pictures -> Wan clips on one rented session -> assembly (captions off / music on)
    -> the owner approves the final video. Every provider mocked."""

    def setUp(self):
        super().setUp()
        os.environ["FFMPEG"] = FFMPEG
        os.environ["FFPROBE"] = shutil.which("ffprobe") or "/usr/bin/ffprobe"
        from oddstudio import config
        config.reset_settings()

    def tearDown(self):
        os.environ.pop("FFPROBE", None)
        super().tearDown()

    def clip(self, frames=81, size="72x128"):
        f = Path(tempfile.mkdtemp()) / "clip.mp4"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:size={size}:rate=16", "-frames:v",
                        str(frames), "-pix_fmt", "yuv420p", str(f)], check=True)
        return f.read_bytes()

    def music(self):
        f = Path(tempfile.mkdtemp()) / "m.wav"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-ar", "24000",
                        "-ac", "1", str(f)], check=True)
        return f.read_bytes()

    def test_whole_short(self):
        from oddstudio import comfy, runpod
        text = "What if lies made you small? Tom lied once on Monday. He woke up tiny. Then he told the truth, and grew."
        eid = self.new()["id"]
        self.approved_script(eid, text)
        self.keys(gemini_api_key=FAKE_GEMINI, wavespeed_api_key=FAKE_WAVESPEED, runpod_api_key=FAKE_RUNPOD)
        self.gemini(seconds=len(text.split()) / 3.0 + 1.0)
        self.transcriber(text)
        self.assertEqual(self.c.post(self.url(eid, "/voice"), json={"use_free_tier": True, "confirm_usd": 0}).status_code, 200)
        self.env.run_jobs(["short_voice"])
        v = self.c.get(self.url(eid)).json()
        self.c.post(self.url(eid, "/voice/approve"), json={"take_id": v["voice"]["takes"][0]["id"]})
        scenes = v["scenes"]["items"]
        self.c.post(self.url(eid, "/pictures/all"), json={"confirm_usd": round(0.04 * len(scenes), 4)})
        self.env.run_jobs(["short_picture"])
        v = self.c.get(self.url(eid)).json()
        for s in v["scenes"]["items"]:
            self.c.post(self.url(eid, f"/scenes/{s['n']}/picture/approve"), json={"asset_id": s["pictures"][0]["asset_id"]})
        # motion: rented mode, the estimate confirmed; one session for all scenes, terminated at the end
        self.assertEqual(self.c.put("/api/settings/gpu", json={"mode": "rented"}).status_code, 200)
        rp, cf = FakeRunPod(), FakeComfy(self.clip())
        runpod.set_test_transport(rp)
        comfy.set_test_transport(httpx.MockTransport(cf))
        est = self.c.get(self.url(eid)).json()["estimates"]["motion"]
        self.assertEqual(len(est["scenes"]), len(scenes))
        self.assertEqual(self.c.post(self.url(eid, "/motion"), json={"confirm_usd": est["usd_max"] - 0.01}).status_code, 409)
        self.assertEqual(self.c.post(self.url(eid, "/motion"), json={"confirm_usd": est["usd_max"]}).status_code, 200)
        ran = self.env.run_jobs(["short_motion"])
        self.assertEqual(ran[0][:2], ("short_motion", "succeeded"), ran)
        self.assertEqual(len([c for c in rp.calls if c[0] == "POST" and c[1] == "/v2/pods"]), 1)   # one session
        self.assertEqual(len(cf.graphs), len(scenes))
        self.assertTrue(all((g["w"]["inputs"]["width"], g["w"]["inputs"]["height"]) == (720, 1280) for g in cf.graphs))
        self.assertTrue(all(p["status"] == "TERMINATED" for p in rp.pods.values()))                 # turned off
        v = self.c.get(self.url(eid)).json()
        self.assertTrue(all(s["clips"] and not s["clip_approved"] for s in v["scenes"]["items"]))
        # music on, captions off
        r = self.c.put(self.url(eid, "/music"), content=self.music(), headers={"Content-Type": "audio/wav"})
        self.assertEqual(r.status_code, 200, r.text)
        self.c.put(self.url(eid, "/options"), json={"captions": False})
        self.assertEqual(self.c.post(self.url(eid, "/assemble")).status_code, 200)
        ran = self.env.run_jobs(["short_assembly"])
        self.assertEqual(ran[0][:2], ("short_assembly", "succeeded"), ran)
        v = self.c.get(self.url(eid)).json()
        cut = v["final"]["cuts"][0]
        self.assertTrue(cut["current"])
        self.assertFalse(cut["captions"])
        self.assertIsNotNone(cut["music_gain_db"])
        self.assertEqual(cut["frames"], sum(r["frames"] for r in v["timing"]["rows"]))
        self.assertIsNone(v["final"].get("approved"))                               # waits for the owner
        from oddstudio.db import new_session
        from oddstudio.models import Asset
        from oddstudio.storage import storage
        from oddstudio.assembly import probe_frames
        with new_session() as db:
            path = storage().local_path(db.get(Asset, cut["asset_id"]).storage_key)
            self.assertEqual(probe_frames(os.environ["FFPROBE"], path), cut["frames"])           # frame-exact
        v = self.c.post(self.url(eid, "/final/approve"), json={"cut_id": cut["id"]}).json()
        self.assertEqual(v["final"]["approved"], cut["id"])
        # captions back on: a new cut is needed (the old one is no longer current); without Node it says so
        v = self.c.put(self.url(eid, "/options"), json={"captions": True}).json()
        self.assertFalse(v["final"]["cuts"][0]["current"])
        from unittest import mock
        with mock.patch.object(NS.shutil, "which", return_value=None):
            self.assertEqual(self.c.post(self.url(eid, "/assemble")).status_code, 200)
            ran = self.env.run_jobs(["short_assembly"])
        self.assertEqual(ran[0][:2], ("short_assembly", "succeeded"), ran)
        cut2 = self.c.get(self.url(eid)).json()["final"]["cuts"][0]
        self.assertFalse(cut2["captions"])
        self.assertTrue(any("captions are left out" in w for w in cut2["warnings"]))


class AutopilotTest(Base):
    def test_make_this_short_waits_at_every_gate(self):
        from oddstudio import autopilot as AP
        os.environ["FFMPEG"] = FFMPEG
        from oddstudio import config
        config.reset_settings()
        eid = self.new()["id"]
        self.keys(openai_api_key=FAKE_OPENAI, wavespeed_api_key=FAKE_WAVESPEED, runpod_api_key=FAKE_RUNPOD,
                  gemini_api_key=FAKE_GEMINI)
        self.assertEqual(self.c.put("/api/settings/gpu", json={"mode": "rented"}).status_code, 200)
        ideas = {"ideas": [{"title": f"Idea {i}", "hook": "h", "twist": "t", "label": "fiction"} for i in range(10)]}
        self.gpt([json.dumps(ideas), SCRIPT])
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/autopilot/start", json={"budget_usd": 5}).status_code, 409)
        r = self.c.post(f"/api/episodes/{eid}/autopilot/start", json={"budget_usd": 5, "confirm_usd": 5, "use_free_tier": True})
        self.assertEqual(r.status_code, 200, r.text)
        a = r.json()
        self.assertEqual([s["key"] for s in a["steps"]], list(__import__("oddstudio.short_autopilot", fromlist=["x"]).STEPS))
        from oddstudio.db import new_session
        with new_session() as db:
            a = AP.tick(db, eid)
        self.assertEqual(a["status"], "waiting")                                    # the owner picks the idea
        self.assertIn("Pick one of the 10 ideas", a["waiting_for"][0]["what"])
        v = self.c.get(self.url(eid)).json()
        self.assertIsNone(v["idea"])
        self.c.put(self.url(eid, "/idea"), json={"idea_id": v["ideas"]["items"][3]["id"]})
        with new_session() as db:
            AP.tick(db, eid)
            a = AP.tick(db, eid)
        self.assertEqual(a["status"], "waiting")
        self.assertIn("approve", a["waiting_for"][0]["what"])
        v = self.c.get(self.url(eid)).json()
        self.assertEqual(len(v["script"]["versions"]), 1)
        self.assertIsNone(v["script"]["approved"])                                  # never approved by the autopilot
        self.c.post(self.url(eid, "/script/approve"), json={"version": 1})
        self.gemini(seconds=8.0)
        self.transcriber(SCRIPT)
        with new_session() as db:
            for _ in range(3):
                a = AP.tick(db, eid)
        # prompts from the templates? no: GPT has no more answers, so the call fails and the run pauses (not retried)
        self.assertIn(a["status"], ("paused", "running", "waiting"))
        with new_session() as db:
            v = AP.stored(db, eid)
        self.assertLessEqual(AP.spent(v), 5.0)
        vv = self.c.get(self.url(eid)).json()
        self.assertIsNone(vv["voice"].get("approved"))
        self.assertTrue(all(not s["picture_approved"] for s in vv["scenes"]["items"]))
        self.assertIsNone((vv["final"] or {}).get("approved"))

    def test_voice_and_picture_gates(self):
        """With the script approved and prompts written, the autopilot makes the narration and waits; after the owner
        approves it, it draws every picture and waits for each approval."""
        from oddstudio import autopilot as AP
        from oddstudio.db import new_session
        eid = self.new()["id"]
        self.approved_script(eid)
        self.c.post(self.url(eid, "/scenes/prompts"), json={"use_template": True})
        self.c.put(self.url(eid, "/idea"), json={"title": "Own idea", "label": "fiction"})
        self.keys(wavespeed_api_key=FAKE_WAVESPEED, runpod_api_key=FAKE_RUNPOD, gemini_api_key=FAKE_GEMINI)
        self.assertEqual(self.c.put("/api/settings/gpu", json={"mode": "rented"}).status_code, 200)
        os.environ["FFMPEG"] = FFMPEG
        from oddstudio import config
        config.reset_settings()
        self.gemini(seconds=8.0)
        self.transcriber(SCRIPT)
        r = self.c.post(f"/api/episodes/{eid}/autopilot/start", json={"budget_usd": 3, "confirm_usd": 3, "use_free_tier": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.env.run_jobs(["short_voice"])
        with new_session() as db:
            a = AP.tick(db, eid)
        self.assertEqual(a["status"], "waiting")
        self.assertIn("Listen to the narration", a["waiting_for"][0]["what"])
        v = self.c.get(self.url(eid)).json()
        self.assertIsNone(v["voice"].get("approved"))
        self.c.post(self.url(eid, "/voice/approve"), json={"take_id": v["voice"]["takes"][0]["id"]})
        with new_session() as db:
            AP.tick(db, eid)
        self.env.run_jobs(["short_picture"])
        with new_session() as db:
            a = AP.tick(db, eid)
        v = self.c.get(self.url(eid)).json()
        n = len(v["scenes"]["items"])
        self.assertEqual(len(self.ws.runs), n)
        self.assertEqual(a["status"], "waiting")
        self.assertEqual(len(a["waiting_for"]), n)                                  # one approval per scene picture
        self.assertTrue(all(not s["picture_approved"] for s in v["scenes"]["items"]))
        with new_session() as db:
            st = AP.stored(db, eid)
        self.assertAlmostEqual(AP.spent(st), round(0.04 * n, 4), places=4)


class ChatTest(Base):
    def test_short_proposals_are_validated(self):
        from oddstudio import shot_chat as SC
        ok = SC.validate_proposal("short_picture", "2", {"type": "redo_picture", "prompt": "the character in reference image 1 jumps"})
        self.assertEqual(ok["type"], "redo_picture")
        self.assertEqual(SC.validate_proposal("short_picture", "2", {"type": "rewrite_line", "scene": 2, "text": "New."})["scene"], 2)
        with self.assertRaises(ValueError):
            SC.validate_proposal("short_picture", "2", {"type": "rewrite_line", "scene": 3, "text": "Other scene."})
        with self.assertRaises(ValueError):
            SC.validate_proposal("short_clip", "2", {"type": "redo_picture", "prompt": "x"})         # not offered here
        with self.assertRaises(ValueError):
            SC.validate_proposal("short_voice", "1", {"type": "regenerate_voice", "voice": "Bob"})
        with self.assertRaises(ValueError):
            SC.validate_proposal("short_clip", "2", {"type": "redo_clip", "prompt": "x", "cfg": 3})  # unknown field
        self.assertEqual(SC.validate_proposal("short_voice", "1", {"type": "regenerate_voice", "style": "dramatic"})["style"], "dramatic")

    def test_threads_and_apply(self):
        eid = self.new()["id"]
        self.approved_script(eid)
        t = self.c.get(f"/api/shot-chat/thread?step=short_picture&item=1&episode_id={eid}").json()
        self.assertEqual(t["proposals"], ["note_only", "redo_picture", "rewrite_line"])
        self.assertEqual(self.c.get(f"/api/shot-chat/thread?step=short_picture&item=99&episode_id={eid}").status_code, 404)
        self.assertEqual(self.c.get(f"/api/shot-chat/thread?step=short_script&item=1&episode_id={eid}").status_code,
                         200 if eid == 1 else 422)
        self.keys(openai_api_key=FAKE_OPENAI)
        from oddstudio import shot_chat as SC

        def handler(url, headers, body):
            return 200, openai_response(json.dumps({"reply": "Try this.", "proposal": {"type": "redo_picture",
                                                    "prompt": "The character in reference image 1 stares at a giant chair."}}))
        SC.set_test_handler(handler)
        try:
            body = {"episode_id": eid, "step": "short_picture", "item": "1", "text": "He should look smaller"}
            est = self.c.post("/api/shot-chat/estimate", json=body).json()
            r = self.c.post("/api/shot-chat/send", json={**body, "confirm_usd": est["usd_max"]})
            self.assertEqual(r.status_code, 200, r.text)
        finally:
            SC.set_test_handler(None)
        m = r.json()["reply"]
        self.assertEqual(m["cost"]["usd"], 0.04)
        self.keys(wavespeed_api_key=FAKE_WAVESPEED)
        ref = {"episode_id": eid, "step": "short_picture", "item": "1", "message_id": m["id"]}
        self.assertEqual(self.c.post("/api/shot-chat/apply", json=ref).status_code, 409)              # price not confirmed
        r = self.c.post("/api/shot-chat/apply", json={**ref, "confirm_usd": 0.04})
        self.assertEqual(r.status_code, 200, r.text)
        self.env.run_jobs(["short_picture"])
        v = self.c.get(self.url(eid)).json()
        s1 = v["scenes"]["items"][0]
        self.assertEqual(s1["picture_prompt"], "The character in reference image 1 stares at a giant chair.")
        self.assertFalse(s1["picture_approved"])


if __name__ == "__main__":
    unittest.main()
