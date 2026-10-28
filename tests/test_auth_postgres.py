"""Real PostgreSQL integration tests in a temporary, isolated schema.

Set AUTOSORT_TEST_DATABASE_URL explicitly. No production tables are modified.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud-ai"))
import auth
import config
import database
import main

TEST_URL = os.getenv("AUTOSORT_TEST_DATABASE_URL")
ORIGIN = "http://testserver"


@unittest.skipUnless(TEST_URL, "Set AUTOSORT_TEST_DATABASE_URL for real PostgreSQL integration tests")
class AuthenticationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "autosort_test_" + uuid4().hex
        with psycopg.connect(TEST_URL) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.connection_patch = patch.object(database, "connect", side_effect=lambda: psycopg.connect(
            TEST_URL, row_factory=dict_row, options="-csearch_path=" + cls.schema))
        cls.connection_patch.start()
        with database.connect() as db:
            db.execute((ROOT / "cloud-ai/schema.sql").read_text(encoding="utf-8"))
        cls.password = "integration-" + uuid4().hex
        cls.password_hash = auth.password_hasher.hash(cls.password)

    @classmethod
    def tearDownClass(cls):
        cls.connection_patch.stop()
        with psycopg.connect(TEST_URL) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.key = "test-device-" + uuid4().hex
        settings = patch.multiple(config, DATABASE_URL=TEST_URL, DEVICE_API_KEY=self.key,
                                  COOKIE_SECURE=False, ALLOWED_ORIGINS=[ORIGIN])
        settings.start()
        self.addCleanup(settings.stop)
        # config.validate_config allows only localhost HTTP, while this TestClient uses a mock host.
        self.validation = patch.object(config, "validate_config")
        self.validation.start()
        self.addCleanup(self.validation.stop)
        with database.connect() as db:
            db.execute("TRUNCATE app_users,auth_sessions,sorting_sessions,fruit_results,audit_logs,login_limits RESTART IDENTITY CASCADE")
            for role in ("admin", "viewer"):
                db.execute("INSERT INTO app_users(id,username,password_hash,role) VALUES (%s,%s,%s,%s)",
                           (uuid4(), role, self.password_hash, role))
        self.client = self.enterContext(TestClient(main.app))

    def login(self, username="admin"):
        result = self.client.post("/api/auth/login", headers={"Origin": ORIGIN},
                                  json={"username": username, "password": self.password})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json(), {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrfToken"]}

    def test_anonymous_cannot_read_history_or_write_and_device_needs_key(self):
        for path in ("/api/auth/me", "/api/session/current", "/api/sessions", "/api/sessions/bad", "/api/audit-logs"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post("/api/sessions/new").status_code, 401)
        self.assertEqual(self.client.post("/infer").status_code, 401)
        self.assertEqual(self.client.post("/infer", headers={"X-API-Key": "wrong-key"}).status_code, 401)
        self.assertEqual(self.client.get("/api/sessions", headers={"X-API-Key": self.key}).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_cookie_csrf_role_and_logout_revocation(self):
        user, headers = self.login()
        self.assertEqual(user["role"], "admin")
        self.assertNotIn("password", str(user))
        self.assertEqual(self.client.get("/api/auth/me").json()["username"], "admin")
        self.assertEqual(self.client.post("/api/sessions/new").status_code, 403)
        self.assertEqual(self.client.post("/api/sessions/new", headers={"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions/new", headers={**headers, "X-CSRF-Token": "incorrect"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions/new", headers={**headers, "Origin": "https://evil.example"}).status_code, 403)
        result = self.client.post("/api/sessions/new", headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        cookie = self.client.cookies.get(config.COOKIE_NAME)
        with database.connect() as db:
            row = db.execute("SELECT * FROM auth_sessions").fetchone()
            self.assertEqual(row["token_hash"], auth.digest(cookie))
            self.assertNotEqual(row["token_hash"], cookie)
            self.assertTrue(db.execute("SELECT password_hash FROM app_users LIMIT 1").fetchone()["password_hash"].startswith("$argon2id$"))
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
        self.client.cookies.set(config.COOKIE_NAME, cookie)
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)

    def test_viewer_is_read_only_and_cannot_use_person_cookie_as_device_key(self):
        _, headers = self.login("viewer")
        self.assertEqual(self.client.get("/api/session/current").status_code, 200)
        self.assertEqual(self.client.get("/api/sessions").status_code, 200)
        self.assertEqual(self.client.get("/api/audit-logs").status_code, 403)
        self.assertEqual(self.client.post("/api/sessions/new", headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/infer").status_code, 401)
        with database.connect() as db:
            db.execute("UPDATE app_users SET active=false WHERE username='viewer'")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_origin_login_rate_limit_and_generic_errors(self):
        body = {"username": "admin", "password": "incorrect-password"}
        self.assertEqual(self.client.post("/api/auth/login", json=body).status_code, 403)
        for _ in range(10):
            result = self.client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=body)
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json()["detail"], "Invalid username or password")
        self.assertEqual(self.client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=body).status_code, 429)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM auth_sessions").fetchone()["n"], 0)

    def test_session_expiry_and_production_cookie_flags(self):
        with patch.object(config, "COOKIE_SECURE", True):
            response = self.client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"username": "admin", "password": self.password})
        cookie_header = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=lax", "max-age=28800"):
            self.assertIn(flag, cookie_header)
        self.client.cookies.clear()
        self.login()
        with database.connect() as db:
            db.execute("UPDATE auth_sessions SET expires_at=now()-interval '1 second'")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_infer_persists_mock_and_history_survives_application_restart(self):
        with patch.multiple(main, model_ready=False, ort_session=None):
            response = self.client.post("/infer", headers={"X-API-Key": self.key},
                                        data={"fruit_id": "F001", "camera_id": "cam1"},
                                        files={"image": ("fruit.jpg", (ROOT / "cloud-ai/quatsample.jpg").read_bytes(), "image/jpeg")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["label"], "MOCK")
        _, headers = self.login()
        first = self.client.get("/api/session/current").json()
        self.assertEqual(len(first["fruits"]), 1)
        self.assertIn("Không điều khiển", first["fruits"][0]["servoAction"])
        self.assertEqual(self.client.post("/api/sessions/new", headers=headers).status_code, 200)
        # A new application lifespan and client must read the same persisted data.
        with TestClient(main.app) as restarted:
            restarted.cookies.update(self.client.cookies)
            history = restarted.get("/api/sessions/" + first["id"]).json()
            self.assertEqual(history["status"], "COMPLETED")
            self.assertEqual(len(history["fruits"]), 1)
            self.assertEqual(restarted.get("/api/sessions/not-a-uuid").status_code, 404)
        self.assertTrue(any(r["action"] == "session.created" for r in self.client.get("/api/audit-logs").json()))

    def test_concurrent_results_and_rollovers_lose_no_records(self):
        with database.connect() as db:
            admin = db.execute("SELECT id FROM app_users WHERE role='admin'").fetchone()["id"]
        def operation(index):
            if index % 5 == 0:
                database.new_session(admin, "test")
            else:
                database.record_fruit_to_session({"fruit_id": str(index), "camera_id": "test", "label": "GREEN",
                                                  "confidence": .9, "inference_ms": 1., "decision_reason": "CLASSIFIED", "model_version": "test"})
        with ThreadPoolExecutor(max_workers=6) as workers:
            list(workers.map(operation, range(30)))
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM fruit_results").fetchone()["n"], 24)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM sorting_sessions WHERE status='RUNNING'").fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
