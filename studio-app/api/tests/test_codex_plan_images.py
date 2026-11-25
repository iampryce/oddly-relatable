"""Codex on the ChatGPT plan as an image provider. A fake `codex` command stands in for the real CLI (no network, no
plan use); the provider, fallback, settings status and capability code are the real code."""
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from helpers import Env

from oddstudio import providers
from oddstudio.providers import ProviderError, ProviderNotConfigured

# The fake CLI. FAKE_CODEX_DIR holds its controls: state (login status text), mode (where it saves the image:
# "out" = ./out.png as asked, "home" = only in CODEX_HOME/generated_images, "none" = nowhere) and seen.json (what it got).
FAKE = textwrap.dedent('''\
    #!{py}
    import json, os, sys, uuid
    ctl = os.environ["FAKE_CODEX_DIR"]
    rd = lambda n, d="": open(os.path.join(ctl, n)).read().strip() if os.path.exists(os.path.join(ctl, n)) else d
    if sys.argv[1:3] == ["login", "status"]:
        print(rd("state", "Not logged in")); sys.exit(0)
    if sys.argv[1:3] == ["login", "--device-auth"]:
        import time
        print("\\x1b[1mOpen this link\\x1b[0m\\n   https://auth.openai.com/codex/device\\n2. Enter this code\\n   \\x1b[94mAB12-CDEFG\\x1b[0m", flush=True)
        for _ in range(200):
            if os.path.exists(os.path.join(ctl, "approve")):
                open(os.path.join(ctl, "state"), "w").write("Logged in using ChatGPT")
                print("Successfully logged in"); sys.exit(0)
            time.sleep(0.05)
        sys.exit(1)
    if sys.argv[1:2] == ["logout"]:
        open(os.path.join(ctl, "state"), "w").write("Not logged in"); sys.exit(0)
    args = sys.argv[1:]
    cwd = args[args.index("-C") + 1]
    prompt = sys.stdin.read()
    json.dump({{"args": args, "prompt": prompt, "openai_env": sorted(k for k in os.environ if k.startswith("OPENAI"))}},
              open(os.path.join(ctl, "seen.json"), "w"))
    png = bytes.fromhex("89504e470d0a1a0a") + b"fake"
    mode = rd("mode", "out")
    if mode == "out":
        open(os.path.join(cwd, "out.png"), "wb").write(png)
    elif mode == "home":
        d = os.path.join(os.environ["CODEX_HOME"], "generated_images", uuid.uuid4().hex)
        os.makedirs(d); open(os.path.join(d, "exec-1.png"), "wb").write(png)
    ''')


class CodexPlanImagesTest(unittest.TestCase):
    def setUp(self):
        self.env = Env().login()
        self.ctl = Path(tempfile.mkdtemp(prefix="fake-codex-"))
        exe = self.ctl / "codex"
        exe.write_text(FAKE.format(py=sys.executable))
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.saved = {k: os.environ.get(k) for k in ("CODEX_BIN", "CODEX_HOME", "FAKE_CODEX_DIR", "OPENAI_API_KEY")}
        os.environ.update({"CODEX_BIN": str(exe), "CODEX_HOME": str(self.ctl / "home"), "FAKE_CODEX_DIR": str(self.ctl),
                           "OPENAI_API_KEY": "sk-must-not-reach-codex"})
        from oddstudio import config
        config.reset_settings()
        providers._login_cache.clear()
        providers.set_test_image(None)
        self.out = self.env.tmp / "img" / "out.png"

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        from oddstudio import config
        config.reset_settings()
        providers._login_cache.clear()
        self.env.close()

    def ctl_set(self, **kw):
        for k, v in kw.items():
            (self.ctl / k).write_text(v)
        providers._login_cache.clear()

    def seen(self):
        return json.loads((self.ctl / "seen.json").read_text())

    def test_refuses_without_chatgpt_sign_in(self):
        with self.assertRaises(ProviderNotConfigured) as e:
            providers.image_generate({"provider": "codex-cli"}, "a cat", self.out)
        self.assertIn("not signed in", str(e.exception))
        self.ctl_set(state="Logged in using an API key - sk-***")
        with self.assertRaises(ProviderNotConfigured) as e:
            providers.image_generate({"provider": "codex-cli"}, "a cat", self.out)
        self.assertIn("API key", str(e.exception))
        self.assertFalse((self.ctl / "seen.json").exists())   # Codex was never asked to make an image

    def test_makes_image_on_plan_without_api_key_in_env(self):
        self.ctl_set(state="Logged in using ChatGPT")
        ref = self.env.tmp / "ref.png"
        ref.write_bytes(b"ref")
        got = providers.image_generate({"provider": "codex-cli", "background": None, "size": "1536x864"},
                                       "the study", self.out, [ref])
        self.assertEqual(got, self.out)
        self.assertTrue(self.out.read_bytes().startswith(bytes.fromhex("89504e47")))
        seen = self.seen()
        self.assertEqual(seen["openai_env"], [])                      # API credentials stripped
        self.assertIn("-i", seen["args"])                             # reference attached
        self.assertIn("own full scenery", seen["prompt"])             # no transparent background for scenes
        self.assertNotIn("Transparent background", seen["prompt"])
        self.assertIn("1536x864", seen["prompt"])

    def test_poses_still_ask_for_transparent_background(self):
        self.ctl_set(state="Logged in using ChatGPT")
        providers.image_generate({"provider": "codex-cli"}, "a pose", self.out)
        self.assertIn("Transparent background", self.seen()["prompt"])

    def test_collects_image_codex_failed_to_copy(self):
        self.ctl_set(state="Logged in using ChatGPT", mode="home")
        old = self.ctl / "home" / "generated_images" / "older"
        old.mkdir(parents=True)
        (old / "exec-0.png").write_bytes(b"OLD image from another call")
        providers.image_generate({"provider": "codex-cli"}, "a pose", self.out)
        self.assertTrue(self.out.read_bytes().startswith(bytes.fromhex("89504e47")))   # the new one, never the old

    def test_no_image_fails_and_never_falls_back_to_paid_provider(self):
        self.ctl_set(state="Logged in using ChatGPT", mode="none")
        calls = []
        real = providers._image_generate_one

        def spy(cfg, *a, **k):
            calls.append(cfg.get("provider"))
            return real(cfg, *a, **k)
        providers._image_generate_one = spy
        try:
            with self.assertRaises(ProviderError) as e:
                providers.image_generate({"provider": "codex-cli", "fallback": "openai"}, "a pose", self.out)
        finally:
            providers._image_generate_one = real
        self.assertEqual(calls, ["codex-cli"])          # openai (paid) was never tried
        self.assertFalse(e.exception.transient)         # so the worker will not retry it automatically

    def test_settings_show_sign_in_and_plan_cost(self):
        r = self.env.client.get("/api/settings").json()
        self.assertEqual(r["integrations"]["codex_login"], "none")
        codex = r["capabilities"]["image"]["providers"]["codex-cli"]
        self.assertFalse(codex["configured"])
        self.assertEqual(codex["missing"], ["tool:codex"])
        self.assertEqual(codex["cost_label"], "$0 (plan allowance)")
        self.ctl_set(state="Logged in using ChatGPT")
        r = self.env.client.get("/api/settings").json()
        self.assertEqual(r["integrations"]["codex_login"], "chatgpt")
        self.assertTrue(r["capabilities"]["image"]["providers"]["codex-cli"]["configured"])

    def test_dashboard_sign_in_flow(self):
        import time
        c = self.env.client
        self.assertEqual(c.get("/api/settings/codex").json()["login"], "none")
        r = c.post("/api/settings/codex/login")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["url"], "https://auth.openai.com/codex/device")
        self.assertEqual(r.json()["code"], "AB12-CDEFG")                       # colour codes stripped
        self.assertEqual(c.post("/api/settings/codex/login").json()["code"], "AB12-CDEFG")   # one at a time
        self.assertEqual(c.get("/api/settings/codex").json()["pending"]["code"], "AB12-CDEFG")
        (self.ctl / "approve").write_text("1")                                  # the owner enters the code
        for _ in range(200):     # up to 10 s: CI machines can be slow to start the fake CLI
            st = c.get("/api/settings/codex").json()
            if st["login"] == "chatgpt" and st["pending"] is None and st["last"]:
                break
            time.sleep(0.05)
        self.assertEqual(st["login"], "chatgpt")
        self.assertEqual(st["last"]["result"], "signed in")
        self.assertNotIn("AB12", json.dumps(st))                                # finished: code not kept
        self.assertEqual(c.post("/api/settings/codex/logout").json()["login"], "none")

    def test_sign_in_routes_need_the_owner(self):
        from fastapi.testclient import TestClient
        from oddstudio.main import app
        anon = TestClient(app)
        for m, path in (("get", "/api/settings/codex"), ("post", "/api/settings/codex/login"),
                        ("post", "/api/settings/codex/logout")):
            self.assertIn(getattr(anon, m)(path).status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
