"""Cinematic mode (feat/cinematic-mode): realistic invented actors side by side with the cartoon mode.

Covered: the episodes.mode migration (existing episodes become "cartoon", reversible) and the model default; the
screenplay parser (sizes, camera moves, one line per shot, unknown speakers added, limits), the owner's script parser
and the labelled template; the public-domain scripture guard (unknown / copyrighted translations and copyright notices
refused, text that does not read like the named translation flagged until the owner confirms); the "Cinematic
realistic" preset and every cinematic prompt carrying the invented-people rule, and the two modes never mixing styles;
the Qwen still graph (references wired to image1-3, empty latent, Qwen-Image-2512 without references) and the Wan 2.2
i2v graph (start only / first+last frame, 1280x720, 81 frames, 4-step LoRAs); the TTS licence rules (non-commercial
engines refused, only catalogue voices) and the line approval gate (a spoken take never drives a talking shot until the
owner approves it); the YouTube disclosure (saved; the final cut cannot be approved without it); the autopilot's
cinematic order and gates (it waits and never approves); and the shot chat's cinematic proposals. No network and no paid
call: WaveSpeed is a stub, OpenAI has no key (template), Kokoro is a stub, RunPod is never reached."""
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from helpers import Env
from test_stick_pipeline import Stub, uninstall

from oddstudio import cinematic as C
from oddstudio import cinematic_graphs as G
from oddstudio import cinematic_tts as TTS
from oddstudio import scripture as SCR
from oddstudio.cast_styles import DEFAULT_STYLES, INVENTED_PEOPLE_RULE

API = Path(__file__).resolve().parents[1]

KJV = ("Then Nebuchadnezzar in his rage and fury commanded to bring Shadrach, Meshach, and Abednego. Then they brought "
       "these men before the king. Nebuchadnezzar spake and said unto them, Is it true, O Shadrach, Meshach, and "
       "Abednego, do not ye serve my gods, nor worship the golden image which I have set up?")
MODERN = ("Furious with rage, Nebuchadnezzar summoned Shadrach, Meshach and Abednego. So these men were brought before "
          "the king, and Nebuchadnezzar said to them, Is it true that you don't serve my gods or worship the image of "
          "gold I have set up? It's your last chance.")

SP = {"title": "The Fire King", "logline": "A king's rival reveals a power over fire.",
      "characters": [{"name": "King Aldric", "role": "the ageing king", "age": "60s", "voice": "male, deep"},
                     {"name": "Queen Mira", "role": "the queen", "voice": "female"}],
      "locations": [{"name": "Throne room", "description": "stone hall, torches, night"}],
      "scenes": [{"heading": "The challenge", "location": "Throne room", "shots": [
          {"size": "EWS", "camera": "crane down", "action": "The hall at night.", "characters": [], "seconds": 4},
          {"size": "CU", "camera": "dolly in", "characters": ["King Aldric"],
           "line": {"speaker": "King Aldric", "text": "Kneel before your king.", "emotion": "angry"}},
          {"size": "medium", "camera": "something odd", "characters": ["Queen Mira"], "vfx": "fire blooms in her palm",
           "dialogue": [{"speaker": "Queen Mira", "text": "No.", "emotion": "cold"},
                        {"speaker": "Stranger", "text": "Who dares?", "emotion": "shocked"}]}]}]}


def wav(path: Path, seconds: float) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 9))) for i in range(int(seconds * 16000))))
    return path


# ================================================================== pure
class MigrationTest(unittest.TestCase):
    def test_0017_fills_cartoon_and_is_reversible(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect
        from oddstudio import config
        tmp = Path(tempfile.mkdtemp(prefix="oddstudio-mig17-"))
        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'm.db').as_posix()}"
        config.reset_settings()
        try:
            cfg = Config(str(API / "alembic.ini"))
            cfg.set_main_option("script_location", str(API / "migrations"))
            command.upgrade(cfg, "0016")
            eng = create_engine(os.environ["DATABASE_URL"])
            with eng.begin() as conn:      # an episode written by the previous release
                conn.exec_driver_sql("insert into episodes (title, stage, revision, storyboard_version, last_error, format, source, "
                                     "audio_rights_confirmed, audio_rights_source, dialogue_display, created_at, updated_at) values "
                                     "('Old', 'script_pending', 1, 0, '', 'short', 'script', 0, '', 'bubbles', '2026-11-20', '2026-11-20')")
            command.upgrade(cfg, "0017")
            with eng.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("select mode from episodes").scalar(), "cartoon")
            command.downgrade(cfg, "0016")
            self.assertNotIn("mode", {c["name"] for c in inspect(eng).get_columns("episodes")})
            eng.dispose()
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            config.reset_settings()


class ScreenplayParseTest(unittest.TestCase):
    def test_normalised(self):
        sp = C.parse_screenplay(SP)
        shots = C.shots_of(sp)
        self.assertEqual([s["size"] for s in shots], ["extreme wide", "close", "medium", "medium"])
        self.assertEqual(shots[1]["camera"], "push in")
        self.assertEqual((shots[2]["camera"], shots[2]["camera_note"]), ("static", "something odd"))
        # two lines in one shot became two shots, each with one line; the unknown speaker was added (with a warning)
        self.assertEqual([s["line"]["text"] for s in shots[2:]], ["No.", "Who dares?"])
        self.assertIn("Stranger", [c["name"] for c in sp["characters"]])
        self.assertTrue(any("Stranger" in w for w in sp["warnings"]))
        self.assertEqual([s["kind"] for s in shots], ["motion", "talk", "talk", "talk"])
        self.assertEqual([ln["id"] for ln in C.lines_of(sp)], ["L2", "L3", "L4"])
        self.assertEqual(shots[0]["seconds"], 4.0)
        self.assertEqual(shots[2]["vfx"], "fire blooms in her palm")
        self.assertIn("Stranger", shots[3]["characters"])          # the speaker is always in the shot

    def test_json_text_and_errors(self):
        import json
        self.assertEqual(C.parse_screenplay("Here:\n" + json.dumps(SP) + "\nDone.")["title"], "The Fire King")
        with self.assertRaises(ValueError):
            C.parse_screenplay("not json")
        with self.assertRaises(ValueError):
            C.parse_screenplay({"scenes": []})

    def test_owner_script_and_template(self):
        raw = C.parse_script_text("INT. THRONE ROOM - NIGHT\nThe torches flicker.\nKING (angry): Kneel.\n"
                                  "[VFX: fire bursts from his hands]\nEXT. DESERT - DAY\nMIRA: I will not.")
        sp = C.parse_screenplay(raw)
        shots = C.shots_of(sp)
        self.assertEqual([loc["name"] for loc in sp["locations"]], ["Throne Room", "Desert"])
        self.assertEqual(shots[1]["line"], {"speaker": "King", "text": "Kneel.", "emotion": "angry"})
        self.assertEqual(shots[1]["vfx"], "fire bursts from his hands")
        self.assertEqual(shots[2]["location"], "Desert")
        t = C.parse_screenplay(C.template_screenplay({"source": "idea", "idea": "A rival queen with fire powers."}))
        self.assertTrue(C.shots_of(t))


class ScriptureTest(unittest.TestCase):
    def test_reference(self):
        self.assertEqual(SCR.parse_reference("Daniel 3:1-30")["text"], "Daniel 3:1-30")
        self.assertEqual(SCR.parse_reference("1 samuel 17")["book"], "1 Samuel")
        self.assertEqual(SCR.parse_reference("Psalm 23:1-6")["book"], "Psalms")
        for bad in ("Hezekiah 3:1", "Daniel", "Daniel 3:9-2"):
            with self.assertRaises(ValueError):
                SCR.parse_reference(bad)

    def test_guard(self):
        self.assertEqual(SCR.check_text(KJV, "KJV")["status"], "ok")
        self.assertEqual(SCR.check_text(KJV, "King James Version")["status"], "ok")
        self.assertEqual(SCR.check_text(KJV, "NIV")["status"], "refused")                  # not public domain
        self.assertEqual(SCR.check_text(KJV, "Some Bible")["status"], "refused")           # unknown translation
        self.assertEqual(SCR.check_text(KJV + " Copyright 2011 by Biblica, Inc.", "KJV")["status"], "refused")
        self.assertEqual(SCR.check_text(KJV + " (ESV)", "KJV")["status"], "refused")
        r = SCR.check_text(MODERN, "KJV")                                                   # does not read like the KJV
        self.assertEqual(r["status"], "flagged")
        self.assertEqual(SCR.check_text(MODERN, "WEB")["status"], "flagged")               # contractions
        # the story input: refused -> ValueError, flagged -> LookupError until the owner confirms
        with self.assertRaises(ValueError):
            C.check_story("bible", passage="Daniel 3", translation="NIV", scripture_text=KJV)
        with self.assertRaises(LookupError):
            C.check_story("bible", passage="Daniel 3", translation="KJV", scripture_text=MODERN)
        ok = C.check_story("bible", passage="Daniel 3", translation="KJV", scripture_text=MODERN, confirm_public_domain=True)
        self.assertTrue(ok["confirmed_public_domain"])
        with self.assertRaises(ValueError):
            C.check_story("bible", passage="Daniel 3", translation="NLT")                   # no text, still refused


class PromptsAndGraphsTest(unittest.TestCase):
    def test_invented_people_rule_everywhere(self):
        self.assertIn(INVENTED_PEOPLE_RULE, DEFAULT_STYLES["cinematic"]["style_prompt"])
        self.assertIn("must not resemble any real person", DEFAULT_STYLES["cinematic"]["style_prompt"])
        shot = C.shots_of(C.parse_screenplay(SP))[1]
        for p in (G.still_prompt(shot, ["King Aldric"], "Throne room", ["King Aldric"], True, "nano"),
                  G.still_prompt(shot, ["King Aldric"], "Throne room", ["King Aldric"], True, "qwen"),
                  G.motion_prompt(shot), G.talk_prompt(shot, "King Aldric")):
            self.assertIn(INVENTED_PEOPLE_RULE, p)
        self.assertIn("Image 1 is the location", G.still_prompt(shot, ["King Aldric"], "Throne room", ["King Aldric"], True, "nano"))
        self.assertIn("image 1 is King Aldric", G.still_prompt(shot, ["King Aldric"], "Throne room", ["King Aldric"], True, "qwen"))
        self.assertIn("the camera slowly pushes in", G.motion_prompt(shot).lower())
        # the location prompt is a room_sets wall prompt that the straight-on check accepts
        from oddstudio.room_sets import straight_on_problem
        self.assertIsNone(straight_on_problem(C.location_template("Throne room", "stone hall, torches")))

    def test_qwen_still_graph_with_references(self):
        from oddstudio.reactions import QWEN_MODELS
        g = G.qwen_still_graph(["king.png", "queen.png", "hall.png"], "the prompt", 7, "p", QWEN_MODELS)
        self.assertEqual(g["u"]["inputs"]["unet_name"], "qwen_image_edit_2511_fp8mixed.safetensors")
        pe = g["pe"]["inputs"]
        self.assertEqual((pe["image1"], pe["image2"], pe["image3"]), (["sc1", 0], ["sc2", 0], ["sc3", 0]))
        self.assertEqual([g[f"li{i}"]["inputs"]["image"] for i in (1, 2, 3)], ["king.png", "queen.png", "hall.png"])
        self.assertEqual(g["ne"]["inputs"]["image1"], ["sc1", 0])
        self.assertEqual(g["k"]["inputs"]["latent_image"], ["lat", 0])
        self.assertEqual((g["lat"]["inputs"]["width"], g["lat"]["inputs"]["height"]), (1280, 720))
        self.assertEqual(g["k"]["inputs"]["model"], ["cn", 0])
        self.assertEqual(g["k"]["inputs"]["positive"], ["pm", 0])
        g1 = G.qwen_still_graph(["king.png"], "x", 1, "p", QWEN_MODELS)
        self.assertNotIn("image2", g1["pe"]["inputs"])
        g0 = G.qwen_still_graph([], "x", 1, "p", QWEN_MODELS)                       # no reference: Qwen-Image-2512
        self.assertEqual(g0["u"]["inputs"]["unet_name"], G.QWEN_IMAGE_2512["filename"])
        self.assertEqual(g0["pe"]["class_type"], "CLIPTextEncode")
        with self.assertRaises(ValueError):
            G.qwen_still_graph(["a", "b", "c", "d"], "x", 1, "p", QWEN_MODELS)
        self.assertNotIn("2.1", G.QWEN_IMAGE_2512["filename"])                       # never the non-commercial 2.1

    def test_i2v_graph(self):
        from oddstudio.reactions import WAN_MODELS
        g = G.i2v_graph("start.png", None, "go", 5, "p", WAN_MODELS)
        self.assertEqual(g["w"]["class_type"], "WanImageToVideo")
        self.assertEqual(g["w"]["inputs"]["start_image"], ["a", 0])
        self.assertEqual((g["w"]["inputs"]["width"], g["w"]["inputs"]["height"], g["w"]["inputs"]["length"]), (1280, 720, 81))
        self.assertEqual(g["uh"]["inputs"]["unet_name"], "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors")
        self.assertEqual(g["ul"]["inputs"]["unet_name"], "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors")
        self.assertIn("lightx2v_4steps", g["lh"]["inputs"]["lora_name"])
        self.assertIn("lightx2v_4steps", g["ll"]["inputs"]["lora_name"])
        self.assertEqual((g["k1"]["inputs"]["end_at_step"], g["k2"]["inputs"]["start_at_step"], g["k2"]["inputs"]["end_at_step"]), (2, 2, 4))
        self.assertEqual(g["cv"]["inputs"]["fps"], 16)
        self.assertNotIn("b", g)
        f = G.i2v_graph("start.png", "end.png", "go", 5, "p", WAN_MODELS)
        self.assertEqual(f["w"]["class_type"], "WanFirstLastFrameToVideo")
        self.assertEqual(f["w"]["inputs"]["end_image"], ["b", 0])
        self.assertEqual(G.motion_pieces(5), [81])
        self.assertEqual(G.motion_pieces(9), [81, 81])
        e = G.estimate([{"kind": "motion", "pieces": [81]}, {"kind": "still"}], [1.0, 2.0], 120)
        self.assertGreater(e["usd_max"], e["usd_typical"])

    def test_audio_mix_graph(self):
        g = G.voice_audio_graph([0.0, 4.5], True, 10.0, 0.25)
        self.assertIn("adelay=4500|4500", g)
        self.assertIn("[3:a]", g)                                                  # the music after the two lines
        self.assertIn("amix=inputs=3", g)
        self.assertTrue(G.voice_audio_graph([], False, 3.0, 0.2).startswith("anullsrc"))


class TtsLicenceTest(unittest.TestCase):
    def test_engines_and_voices(self):
        e = TTS.choose_engine("kokoro")
        self.assertTrue(e["commercial"])
        self.assertIn("Apache-2.0", e["weights_licence"])
        for bad in ("xtts-v2", "f5-tts", "fish-speech", "something-else"):
            with self.assertRaises(ValueError):
                TTS.choose_engine(bad)
        self.assertEqual(TTS.check_voice("bm_george"), "kokoro:bm_george")
        self.assertEqual(TTS.check_voice("kokoro:af_heart"), "kokoro:af_heart")
        with self.assertRaises(ValueError):
            TTS.check_voice("xtts:morgan")
        s = TTS.suggest([{"name": "King", "voice": "male"}, {"name": "Queen", "voice": "female"}, {"name": "Guard", "role": "a guard"}])
        self.assertEqual(TTS.KOKORO_VOICES[s["Queen"]][1], "female")
        self.assertEqual(len(set(s.values())), 3)
        with self.assertRaises(ValueError):
            from oddstudio.settings_store import put_section  # noqa: F401  (checked through the section validator)
            C.check_settings({"voice_engine": "xtts-v2"})


# ================================================================== API
class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.c = self.env.client
        self.stub = Stub().install()
        self.spoken = []

        def speak(text, voice, speed, out):
            self.spoken.append((text, voice, speed))
            return wav(out.with_suffix(".wav"), 1.2)
        TTS.set_test_speak(speak)
        self.secrets(wavespeed_api_key="fake-wavespeed-credential-for-tests")

    def tearDown(self):
        TTS.set_test_speak(None)
        uninstall()
        self.env.close()

    def db(self):
        from oddstudio.db import new_session
        return new_session()

    def secrets(self, **vals):
        from oddstudio.secrets_store import put_secrets
        with self.db() as db:
            put_secrets(db, vals)

    def create(self, **story):
        r = self.c.post("/api/cinematic-episodes", json={"title": "The Fire King", "story": story or {"source": "idea", "idea": "A queen reveals fire powers."}})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["episode"]["id"]

    def url(self, eid, p=""):
        return f"/api/episodes/{eid}/cinematic{p}"

    def with_screenplay(self, eid, approve=True):
        r = self.c.put(self.url(eid, "/screenplay"), json={"screenplay": SP})
        self.assertEqual(r.status_code, 200, r.text)
        if approve:
            self.assertEqual(self.c.post(self.url(eid, "/screenplay/approve"), json={}).status_code, 200)
        return r.json()

    def approve_masters(self, eid):
        from PIL import Image
        from oddstudio.models import CharacterAsset
        from oddstudio.storage import storage
        v = self.c.get(self.url(eid)).json()
        with self.db() as db:
            for c in v["cast"]:
                f = Path(tempfile.mkdtemp()) / "m.png"
                Image.new("RGB", (30, 40), (120, 90, 80)).save(f)
                storage().put_file(f"characters/x/{c['id']}.png", f, "image/png")
                db.add(CharacterAsset(character_id=c["id"], kind="master", storage_key=f"characters/x/{c['id']}.png", status="approved"))
            db.commit()


class ModeTest(Base):
    def test_create_and_modes_never_mix(self):
        eid = self.create()
        ep = self.c.get(f"/api/episodes/{eid}").json()
        self.assertEqual(ep["episode"]["mode"] if "episode" in ep else ep["mode"], "cinematic")
        # a cartoon episode keeps its mode and today's flow; its steps refuse the cinematic routes
        from oddstudio.models import Episode
        with self.db() as db:
            e = Episode(title="cartoon", stage="script_pending")
            db.add(e)
            db.commit()
            cid = e.id
            self.assertEqual(e.mode, "cartoon")
        self.assertEqual(self.c.get(self.url(cid)).status_code, 409)
        self.assertEqual(self.c.get(f"/api/episodes/{cid}/guide").json()["episode"]["mode"], "cartoon")
        self.assertEqual(self.c.put(f"/api/episodes/{cid}/cast-video/style", json={"style": "cinematic"}).status_code, 409)
        self.assertEqual(self.c.put(f"/api/episodes/{eid}/cast-video/style", json={"style": "clay"}).status_code, 409)
        styles = [s["id"] for s in self.c.get(f"/api/episodes/{eid}/cast-video").json()["styles"]]
        self.assertEqual(styles, ["cinematic"])
        styles = [s["id"] for s in self.c.get(f"/api/episodes/{cid}/cast-video").json()["styles"]]
        self.assertNotIn("cinematic", styles)

    def test_bible_story_guard_on_create(self):
        r = self.c.post("/api/cinematic-episodes", json={"title": "x", "story": {"source": "bible", "passage": "Daniel 3",
                                                                                 "translation": "NIV", "scripture_text": KJV}})
        self.assertEqual(r.status_code, 422)
        r = self.c.post("/api/cinematic-episodes", json={"title": "x", "story": {"source": "bible", "passage": "Daniel 3",
                                                                                 "translation": "KJV", "scripture_text": MODERN}})
        self.assertEqual(r.status_code, 409)
        self.assertIn("public-domain", r.json()["detail"])
        eid = self.create(source="bible", passage="Daniel 3:1-30", translation="KJV", scripture_text=KJV, angle="faith under fire")
        v = self.c.get(self.url(eid)).json()
        self.assertEqual(v["story"]["passage"], "Daniel 3:1-30")
        self.assertEqual(v["story"]["check"]["status"], "ok")

    def test_screenplay_template_without_key_and_approval(self):
        eid = self.create()
        r = self.c.post(self.url(eid, "/screenplay/write"), json={})
        self.assertEqual(r.status_code, 200, r.text)
        sp = r.json()["screenplay"]
        self.assertEqual(sp["source"], "template")
        self.assertIn("template", sp["label"])
        self.assertFalse(sp["approved"])
        self.assertEqual(self.c.post(self.url(eid, "/cast")).status_code, 409)          # not approved yet
        self.assertEqual(self.c.put(self.url(eid, "/screenplay"), json={"screenplay": {"scenes": []}}).status_code, 422)

    def test_screenplay_with_key_needs_confirmed_cost(self):
        self.secrets(openai_api_key="fake-openai-credential-for-tests")
        eid = self.create()
        r = self.c.post(self.url(eid, "/screenplay/write"), json={})
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm that amount", r.json()["detail"])


class FlowTest(Base):
    def test_cast_locations_still_lines_gate_and_disclosure(self):
        eid = self.create()
        self.with_screenplay(eid)
        v = self.c.post(self.url(eid, "/cast")).json()
        self.assertEqual(sorted(c["name"] for c in v["cast"]), ["King Aldric", "Queen Mira", "Stranger"])
        cast = self.c.get(f"/api/episodes/{eid}/cast-video").json()
        self.assertEqual(cast["style"], "cinematic")
        self.assertIn(INVENTED_PEOPLE_RULE, cast["characters"][0]["prompt"]["text"])
        v = self.c.post(self.url(eid, "/locations")).json()
        self.assertEqual([loc["name"] for loc in v["locations"]], ["Throne room"])
        self.assertIn("photorealistic", v["locations"][0]["prompt"])
        # a still needs the masters and the location first
        r = self.c.post(self.url(eid, "/shots/2/still"), json={"confirm_usd": 0.04})
        self.assertEqual(r.status_code, 409)
        self.assertIn("approve a master for King Aldric", r.json()["detail"])
        self.approve_masters(eid)
        wid = v["locations"][0]["wall_id"]
        self.assertEqual(self.c.post(f"/api/episodes/{eid}/room-sets/walls/{wid}/make", json={"confirm_usd": 0.04}).status_code, 200)
        self.env.run_jobs(["room_image"])
        loc = self.c.get(self.url(eid)).json()["locations"][0]
        self.c.post(f"/api/episodes/{eid}/room-sets/walls/{wid}/approve", json={"take_id": loc["takes"][0]["id"]})
        self.assertEqual(self.c.post(self.url(eid, "/shots/2/still"), json={"confirm_usd": 0.01}).status_code, 409)   # wrong price
        r = self.c.post(self.url(eid, "/shots/2/still"), json={"confirm_usd": 0.04})
        self.assertEqual(r.status_code, 200, r.text)
        self.env.run_jobs(["cinematic_still"])
        endpoint, body = self.stub.runs[-1]
        self.assertEqual(endpoint, "google/nano-banana-2.1/edit")
        self.assertEqual(len(body["images"]), 2)                                         # the location + the king's master
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertIn(INVENTED_PEOPLE_RULE, body["prompt"])
        shot = self.c.get(self.url(eid)).json()["shots"][1]
        self.assertEqual(len(shot["stills"]), 1)
        self.assertIsNone(shot["approved"])                                              # never approved by itself
        self.c.post(self.url(eid, "/shots/2/still/approve"), json={"take_id": shot["stills"][0]["id"]})
        # the line: no voice chosen -> refused; with a voice -> spoken, not approved, so the render stays blocked
        r = self.c.post(self.url(eid, "/lines/generate"), json={"lines": ["L2"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("choose a voice for King Aldric", r.json()["detail"])
        king = next(c for c in self.c.get(self.url(eid)).json()["cast"] if c["name"] == "King Aldric")
        self.assertEqual(self.c.put(self.url(eid, "/voices"), json={"character_id": king["id"], "voice": "xtts:morgan"}).status_code, 422)
        self.assertEqual(self.c.put(self.url(eid, "/voices"), json={"character_id": king["id"], "voice": "bm_george"}).status_code, 200)
        self.assertEqual(self.c.post(self.url(eid, "/lines/generate"), json={"lines": ["L2"]}).status_code, 200)
        self.env.run_jobs(["cinematic_voice"])
        self.assertEqual(self.spoken[-1][:2], ("Kneel before your king.", "bm_george"))
        self.assertGreater(self.spoken[-1][2], 1.0)                                      # angry: a little faster
        v = self.c.get(self.url(eid)).json()
        ln = next(x for x in v["lines"] if x["id"] == "L2")
        self.assertEqual(len(ln["takes"]), 1)
        self.assertIsNone(ln["approved"])
        self.assertIn("approve its line's voice take", v["shots"][1]["render_blocked"])
        self.assertFalse(v["shots"][1]["render_ready"])
        r = self.c.post(self.url(eid, "/render"), json={"shots": [2], "confirm_usd": 50})
        self.assertEqual(r.status_code, 409)
        self.c.post(self.url(eid, f"/lines/L2/approve"), json={"take_id": ln["takes"][0]["id"]})
        v = self.c.get(self.url(eid)).json()
        self.assertTrue(v["shots"][1]["render_ready"])
        # the GPU is off: the render is refused before anything starts
        r = self.c.post(self.url(eid, "/render"), json={"shots": [2], "confirm_usd": 50})
        self.assertEqual(r.status_code, 409)
        self.assertIn("GPU worker", r.json()["detail"])
        # disclosure: the cut cannot be approved without it; the tick is saved
        with self.db() as db:
            cv = C.stored(db, eid)
            cv["cuts"] = [{"id": "cut1", "hash": "x", "asset_id": None}]
            C.save(db, eid, cv)
            db.commit()
        r = self.c.post(self.url(eid, "/cut/approve"), json={"cut_id": "cut1"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Altered or synthetic content", r.json()["detail"])
        v = self.c.put(self.url(eid, "/disclosure"), json={"acknowledged": True}).json()
        self.assertTrue(v["disclosure"]["acknowledged"])
        self.assertEqual(v["disclosure"]["text"], C.DISCLOSURE)
        self.assertEqual(self.c.post(self.url(eid, "/cut/approve"), json={"cut_id": "cut1"}).json()["approved_cut"], "cut1")

    def test_gpu_render_cost_first_and_cap(self):
        eid = self.create()
        self.with_screenplay(eid)
        self.c.put("/api/settings/gpu", json={"mode": "rented", "monthly_cap_usd": 50.0})
        self.secrets(runpod_api_key="fake-runpod-credential-for-tests")
        with self.db() as db:
            cv = C.stored(db, eid)
            cv.setdefault("shots", {})["1"] = {"stills": [{"id": "s1", "key": "episodes/x/s1.png", "asset_id": 1}], "approved": "s1"}
            C.save(db, eid, cv)
            db.commit()
        est = self.c.get(self.url(eid)).json()["shots"][0]["render_estimate"]
        self.assertGreater(est["usd_max"], 0)
        r = self.c.post(self.url(eid, "/render"), json={"shots": [1], "confirm_usd": est["usd_max"] / 2})
        self.assertEqual(r.status_code, 409)
        self.assertIn("confirm that amount", r.json()["detail"])
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 0.01})
        r = self.c.post(self.url(eid, "/render"), json={"shots": [1], "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("monthly GPU cap", r.json()["detail"])
        self.c.put("/api/settings/gpu", json={"monthly_cap_usd": 50.0})
        r = self.c.post(self.url(eid, "/render"), json={"shots": [1], "confirm_usd": est["usd_max"]})
        self.assertEqual(r.status_code, 200, r.text)
        from oddstudio.models import Job
        with self.db() as db:
            j = db.query(Job).filter_by(kind="cinematic_gpu").one()
            self.assertEqual(j.payload["tasks"][0]["kind"], "motion")
            self.assertEqual(j.payload["backend"], "gpu")


class ChatTest(Base):
    def test_cinematic_proposals(self):
        from oddstudio import shot_chat as SC
        p = SC.validate_proposal("cine_shot", "2", {"type": "rerender_shot", "prompt": "He slams the table.", "camera": "push in"})
        self.assertEqual(p, {"type": "rerender_shot", "prompt": "He slams the table.", "camera": "push in"})
        for bad in ({"type": "rerender_shot"}, {"type": "rerender_shot", "prompt": "x y z", "camera": "zoom wildly"},
                    {"type": "rerender_shot", "prompt": "abc", "settings": {}}, {"type": "redo_still"}):
            with self.assertRaises(ValueError):
                SC.validate_proposal("cine_shot", "2", bad)
        self.assertEqual(SC.validate_proposal("cine_still", "2", {"type": "redo_still", "prompt": "wider"})["type"], "redo_still")
        self.assertEqual(SC.validate_proposal("cine_line", "L2", {"type": "regenerate_line", "voice": "kokoro:bf_emma"})["voice"], "bf_emma")
        with self.assertRaises(ValueError):
            SC.validate_proposal("cine_line", "L2", {"type": "regenerate_line", "voice": "xtts:morgan"})
        self.assertIn("free", SC.describe({"type": "regenerate_line", "text": "Kneel."}))
        eid = self.create()
        self.with_screenplay(eid)
        with self.db() as db:
            ref = SC.Ref(episode_id=eid, step="cine_still", item="2")
            self.assertEqual(SC.proposal_cost(db, ref, {"type": "redo_still"})["usd"], 0.04)
            self.assertIsNone(SC.proposal_cost(db, SC.Ref(episode_id=eid, step="cine_line", item="L2"), {"type": "regenerate_line"}))
            self.assertIsNone(SC.proposal_cost(db, SC.Ref(episode_id=eid, step="cine_shot", item="2"),
                                               {"type": "rerender_shot", "prompt": "abc"})["usd"])   # no approved still yet
            cx = SC.build_context(db, SC.Ref(episode_id=eid, step="cine_shot", item="2"))
            self.assertIn(INVENTED_PEOPLE_RULE, cx["house_style"])


class AutopilotTest(Base):
    def setUp(self):
        os.environ["FFMPEG"] = "/usr/bin/ffmpeg"        # the assembly provider counts as ready (nothing is assembled here)
        super().setUp()
        from oddstudio import comfy_session as CS
        self._stop = CS.stop
        CS.stop = lambda db, reason: []

    def tearDown(self):
        from oddstudio import comfy_session as CS
        CS.stop = self._stop
        super().tearDown()
        os.environ.pop("FFMPEG", None)

    def state(self, eid):
        return self.c.get(f"/api/episodes/{eid}/autopilot").json()

    def tick(self, eid):
        from oddstudio import autopilot as AP
        with self.db() as db:
            return AP.tick(db, eid)

    def test_cinematic_order_and_gates(self):
        eid = self.create()
        s = self.state(eid)
        self.assertEqual([x["key"] for x in s["steps"]],
                         ["screenplay", "cast", "locations", "stills_c", "voices", "shots", "quality", "approvals_c", "assembly_c"])
        self.assertEqual(s["mode"], "cinematic")
        r = self.c.post(f"/api/episodes/{eid}/autopilot/start", json={"budget_usd": 1.0, "confirm_usd": 1.0})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["actions"][0]["what"], "Write the screenplay (template, free)")
        s = self.tick(eid)
        # no OpenAI key: a template screenplay (free), then it WAITS for the owner's approval
        self.assertEqual(s["status"], "waiting")
        self.assertEqual(s["step"], "screenplay")
        self.assertEqual([w["what"] for w in s["waiting_for"]], ["Read, edit and approve the screenplay"])
        with self.db() as db:
            self.assertFalse(C.screenplay_approved(C.stored(db, eid)))
        self.with_screenplay(eid)
        v = self.tick(eid)                    # the cast is made (free), then master candidates (paid, inside the budget)
        v = self.tick(eid)
        self.assertEqual(v["step"], "cast")
        from oddstudio.models import Job
        with self.db() as db:
            self.assertEqual(db.query(Job).filter_by(kind="cast_images").count(), 3)     # one per character
        self.env.run_jobs(["cast_images"])
        v = self.tick(eid)
        self.assertEqual(v["status"], "waiting")
        self.assertTrue(any(w["what"].startswith("Approve a master for") for w in v["waiting_for"]))
        self.assertLessEqual(v["spent_usd"], 1.0)
        # the owner approves the masters and chooses the voices: then locations come next
        self.approve_masters(eid)
        cv = self.c.get(self.url(eid)).json()
        v = self.tick(eid)
        self.assertEqual(v["step"], "cast")
        self.assertTrue(any("Choose a voice" in w["what"] for w in v["waiting_for"]))
        for c in cv["cast"]:
            self.c.put(self.url(eid, "/voices"), json={"character_id": c["id"], "voice": c["suggested_voice"] or "am_adam"})
        v = self.tick(eid)
        v = self.tick(eid)
        self.assertEqual(v["step"], "locations")
        with self.db() as db:
            self.assertEqual(db.query(Job).filter_by(kind="room_image").count(), 1)
        self.env.run_jobs(["room_image"])
        v = self.tick(eid)
        self.assertEqual(v["status"], "waiting")
        self.assertIn("Approve a picture of the location", v["waiting_for"][0]["what"])
        from oddstudio.models import Event
        with self.db() as db:                 # it never approved anything itself
            approvals = [e.message for e in db.query(Event).filter_by(kind="approval")]
        self.assertTrue(approvals)
        self.assertFalse([m for m in approvals if "Autopilot" in m], approvals)


class GpuJobTest(Base):
    """The GPU job with a fake ComfyUI session: a Qwen still and a motion shot come back as takes / results, wired with
    the right graphs, and nothing is approved."""

    def test_qwen_still_and_motion(self):
        from PIL import Image
        from oddstudio import reactions as R
        from oddstudio.models import Episode
        from oddstudio.storage import storage
        eid = self.create()
        self.with_screenplay(eid)
        self.c.put("/api/settings/gpu", json={"mode": "rented", "monthly_cap_usd": 50.0})
        self.secrets(runpod_api_key="fake-runpod-credential-for-tests")
        f = Path(tempfile.mkdtemp()) / "s.png"
        Image.new("RGB", (64, 36), (50, 60, 70)).save(f)
        storage().put_file("episodes/x/s1.png", f, "image/png")
        with self.db() as db:
            cv = C.stored(db, eid)
            cv.setdefault("shots", {})["1"] = {"stills": [{"id": "s1", "key": "episodes/x/s1.png", "asset_id": 1}], "approved": "s1"}
            C.save(db, eid, cv)
            db.commit()
        graphs = []

        class FakeClient:
            def upload(self, p):
                return Path(p).name

            def download(self, fi, dest):
                if dest.suffix == ".png":
                    Image.new("RGB", (64, 36), (9, 9, 9)).save(dest)
                else:
                    dest.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video")
                return dest
        sess = {"session": "s", "pod_id": "p", "gpu_type": "NVIDIA L40S", "price_per_hour": 1.0, "launched_at": 1e12,
                "client": FakeClient()}

        def fake_session(run, models):
            run.sess = sess
            return sess

        def fake_graph(run, g, minutes):
            graphs.append(g)
            if "lat" in g:
                return {"9": {"images": [{"filename": "o.png", "type": "output"}]}}
            return {"9": {"videos": [{"filename": "o.mp4", "type": "output"}]}}
        old = (R._Run.session, R._Run.run_graph, R._Run.finish, R._Run.spent)
        R._Run.session, R._Run.run_graph = fake_session, fake_graph
        R._Run.finish = lambda run, jid: None
        R._Run.spent = lambda run: 0.0
        try:
            with self.db() as db:
                cv = C.stored(db, eid)
                motion, why = C.render_task(db, db.get(Episode, eid), cv, C.shots_of(C.screenplay(cv))[0])
                self.assertEqual(why, "")
                tasks = [{"kind": "still", "shot": 2, "end": False, "prompt": "p " + INVENTED_PEOPLE_RULE,
                          "refs": ["episodes/x/s1.png"]}, motion]
                C.start_gpu(db, db.get(Episode, eid), tasks, 50.0, "owner", "a test run")
            ran = self.env.run_jobs(["cinematic_gpu"])
            self.assertEqual(ran[0][1], "succeeded", ran)
        finally:
            R._Run.session, R._Run.run_graph, R._Run.finish, R._Run.spent = old
        self.assertEqual(graphs[0]["pe"]["class_type"], "TextEncodeQwenImageEditPlus")
        self.assertEqual(graphs[1]["w"]["class_type"], "WanImageToVideo")
        v = self.c.get(self.url(eid)).json()
        self.assertEqual(len(v["shots"][1]["stills"]), 1)
        self.assertIsNone(v["shots"][1]["approved"])
        self.assertEqual(len(v["shots"][0]["renders"]), 1)
        self.assertEqual(v["shots"][0]["renders"][0]["frames"], 81)
        self.assertIsNone(v["shots"][0]["approved_render"])
