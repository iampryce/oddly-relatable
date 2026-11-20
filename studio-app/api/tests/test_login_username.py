"""Sign-in with a username (owner decision 2026-11-20): OWNER_EMAIL may be any name, e.g. "admin"; the login page asks
for a "Username" in a plain text field, and a wrong one is reported as "Wrong username or password"."""
import os
import unittest
from pathlib import Path

from helpers import PASSWORD, Env

WEB = Path(__file__).resolve().parents[2] / "web"


class UsernameLoginTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        os.environ["OWNER_EMAIL"] = "admin"
        from oddstudio import config
        config.reset_settings()
        self.c = self.env.client

    def tearDown(self):
        self.env.close()

    def test_admin_signs_in(self):
        self.assertEqual(self.c.get("/api/overview").status_code, 401, "sign-in is required")
        r = self.c.post("/api/auth/login", json={"email": "admin", "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"email": "admin"})
        self.assertEqual(self.c.get("/api/auth/me").json(), {"email": "admin"})
        self.assertEqual(self.c.get("/api/overview").status_code, 200)
        self.assertEqual(self.c.post("/api/auth/login", json={"email": " Admin ", "password": PASSWORD}).status_code, 200,
                         "the same case-insensitive, trimmed match as before")

    def test_wrong_username_or_password(self):
        for body in ({"email": "admin", "password": "nope"}, {"email": "owner@example.com", "password": PASSWORD}):
            r = self.c.post("/api/auth/login", json=body)
            self.assertEqual(r.status_code, 401, r.text)
            self.assertEqual(r.json()["detail"], "Wrong username or password")

    def test_the_login_page_asks_for_a_username_in_a_text_field(self):
        page = (WEB / "app/login/page.tsx").read_text()
        self.assertIn('>Username</label>', page)
        self.assertIn('type="text"', page)
        self.assertNotIn('type="email"', page, "browsers refuse 'admin' in an email field")


if __name__ == "__main__":
    unittest.main()
