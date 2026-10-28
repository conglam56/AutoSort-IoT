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
import render_start

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

    def extra_client(self, username="viewer", password=None):
        client = self.enterContext(TestClient(main.app))
        result = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"username": username, "password": password or self.password})
        self.assertEqual(result.status_code, 200)
        return client, result.json()

    def account_id(self, username):
        with database.connect() as db:
            return str(db.execute("SELECT id FROM app_users WHERE username=%s", (username,)).fetchone()["id"])

    def test_viewer_reads_do_not_create_any_session_and_admin_routes_are_forbidden(self):
        user, headers = self.login("viewer")
        self.assertIsNone(self.client.get("/api/session/current").json())
        self.assertEqual(self.client.get("/api/sessions").json(), [])
        self.assertEqual(self.client.post("/api/sessions/new", headers=headers).status_code, 403)
        for path in ("/api/admin/users", "/api/admin/audit-logs"):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/users", headers=headers, json={"username": "intruder", "password": self.password, "role": "admin"}).status_code, 403)
        for suffix, body in (("settings", {"role": "admin", "active": True}), ("password", {"password": self.password}), ("revoke-sessions", {})):
            self.assertEqual(self.client.post('/api/admin/users/' + user['id'] + '/' + suffix, headers=headers, json=body).status_code, 403)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM sorting_sessions").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM app_users").fetchone()["n"], 2)

    def test_admin_create_list_search_validation_and_audit(self):
        _, headers = self.login()
        body = {"username": "  New.Member  ", "password": self.password}
        self.assertEqual(self.client.post("/api/admin/users", json=body).status_code, 403)
        response = self.client.post("/api/admin/users", headers=headers, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["username"], "new.member")
        self.assertEqual(response.json()["role"], "viewer")
        self.assertNotIn("password", response.text)
        self.assertEqual(self.client.post("/api/admin/users", headers=headers, json=body).status_code, 409)
        for invalid in ({**body, "role": "owner"}, {**body, "username": "<script>"}, {**body, "password": "short"}, {**body, "active": True}):
            self.assertEqual(self.client.post("/api/admin/users", headers=headers, json=invalid).status_code, 422)
        result = self.client.get("/api/admin/users?search=member&limit=1").json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["users"][0]["username"], "new.member")
        self.assertNotIn("password_hash", str(result))
        self.assertNotIn("csrf", str(result))
        self.assertEqual(len(self.client.get("/api/admin/users?limit=1&offset=1").json()["users"]), 1)
        logs = self.client.get("/api/admin/audit-logs?kind=account").json()["logs"]
        self.assertTrue(any(row["action"] == "account.created:new.member" and row["username"] == "admin" for row in logs))

    def test_admin_lock_unlock_and_role_change_revoke_existing_sessions(self):
        _, headers = self.login()
        victim, _ = self.extra_client()
        target = self.account_id("viewer")
        path = '/api/admin/users/' + target + '/settings'
        self.assertEqual(self.client.post(path, headers=headers, json={"role": "viewer", "active": False}).status_code, 200)
        self.assertEqual(victim.get('/api/auth/me').status_code, 401)
        self.assertEqual(victim.post('/api/auth/login', headers={"Origin": ORIGIN}, json={"username": "viewer", "password": self.password}).status_code, 401)
        self.assertEqual(self.client.post(path, headers=headers, json={"role": "admin", "active": True}).status_code, 200)
        login = victim.post('/api/auth/login', headers={"Origin": ORIGIN}, json={"username": "viewer", "password": self.password})
        self.assertEqual(login.json()['role'], 'admin')
        self.assertEqual(victim.get('/api/admin/users').status_code, 200)
        self.assertEqual(self.client.post(path, headers=headers, json={"role": "viewer", "active": True}).status_code, 200)
        self.assertEqual(victim.get('/api/admin/users').status_code, 401)
        self.assertEqual(self.client.post(path, headers=headers, json={"role": "owner", "active": True}).status_code, 422)
        self.assertEqual(self.client.post(path, headers=headers, json={"role": "viewer", "active": "false"}).status_code, 422)

    def test_last_admin_and_own_access_cannot_be_removed(self):
        user, headers = self.login()
        path = '/api/admin/users/' + user['id'] + '/settings'
        response = self.client.post(path, headers=headers, json={"role": "viewer", "active": False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'LAST_ADMIN_REQUIRED')
        self.client.post('/api/admin/users', headers=headers, json={"username": "second-admin", "password": self.password, "role": "admin"})
        response = self.client.post(path, headers=headers, json={"role": "viewer", "active": True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'CANNOT_CHANGE_OWN_ACCESS')

    def test_cli_cannot_disable_last_administrator(self):
        import io
        from contextlib import redirect_stderr
        import manage
        with patch.object(sys, 'argv', ['manage.py', 'disable-user', 'admin']), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                manage.main()
        self.assertEqual(stopped.exception.code, 2)
        with database.connect() as db:
            self.assertTrue(db.execute("SELECT active FROM app_users WHERE username='admin'").fetchone()['active'])

    def test_mutation_rechecks_role_after_dependency_has_become_stale(self):
        user, _ = self.login()
        token = auth.digest(self.client.cookies.get(config.COOKIE_NAME))
        with database.connect() as db:
            stale = db.execute("SELECT u.id,u.username,u.role,s.token_hash,s.csrf_token FROM app_users u JOIN auth_sessions s ON s.user_id=u.id WHERE s.token_hash=%s", (token,)).fetchone()
            db.execute("UPDATE app_users SET role='viewer' WHERE id=%s", (stale['id'],))
        main.app.dependency_overrides[auth.require_admin] = lambda: stale
        self.addCleanup(main.app.dependency_overrides.pop, auth.require_admin, None)
        self.assertEqual(self.client.post('/api/sessions/new').status_code, 403)
        self.assertEqual(self.client.post('/api/admin/users', json={"username": "stale-admin", "password": self.password}).status_code, 403)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM sorting_sessions").fetchone()['n'], 0)

    def test_concurrent_admin_changes_leave_one_active_administrator(self):
        first, headers = self.login()
        created = self.client.post('/api/admin/users', headers=headers, json={"username": "second-admin", "password": self.password, "role": "admin"})
        self.assertEqual(created.status_code, 201)
        second_client, second = self.extra_client('second-admin')
        second_headers = {'Origin': ORIGIN, 'X-CSRF-Token': second['csrfToken']}
        def disable(args):
            client, target, csrf = args
            return client.post('/api/admin/users/' + target + '/settings', headers=csrf, json={'role': 'admin', 'active': False}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(disable, [(self.client, second['id'], headers), (second_client, first['id'], second_headers)]))
        self.assertEqual(results.count(200), 1, results)
        self.assertTrue(any(code in (401, 403) for code in results), results)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM app_users WHERE active AND role='admin'").fetchone()['n'], 1)

    def test_admin_password_reset_and_session_revocation(self):
        admin_user, headers = self.login()
        victim, _ = self.extra_client()
        target = self.account_id('viewer')
        new_password = 'changed-' + uuid4().hex
        self.assertEqual(self.client.post('/api/admin/users/' + target + '/password', headers=headers, json={'password': new_password}).status_code, 200)
        self.assertEqual(victim.get('/api/auth/me').status_code, 401)
        old = victim.post('/api/auth/login', headers={'Origin': ORIGIN}, json={'username': 'viewer', 'password': self.password})
        self.assertEqual(old.status_code, 401)
        logged = victim.post('/api/auth/login', headers={'Origin': ORIGIN}, json={'username': 'viewer', 'password': new_password})
        self.assertEqual(logged.status_code, 200)
        self.assertEqual(self.client.post('/api/admin/users/' + target + '/revoke-sessions', headers=headers).status_code, 200)
        self.assertEqual(victim.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/users/' + admin_user['id'] + '/password', headers=headers, json={'password': new_password}).status_code, 409)

    def test_user_changes_own_password_and_all_sessions_are_revoked(self):
        _, headers = self.login('viewer')
        other, _ = self.extra_client()
        new_password = 'own-new-' + uuid4().hex
        self.assertEqual(self.client.post('/api/auth/password', json={'current_password': self.password, 'new_password': new_password}).status_code, 403)
        wrong = self.client.post('/api/auth/password', headers=headers, json={'current_password': 'wrong', 'new_password': new_password})
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(self.client.post('/api/auth/password', headers=headers, json={'current_password': self.password, 'new_password': new_password}).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(other.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', headers={'Origin': ORIGIN}, json={'username': 'viewer', 'password': self.password}).status_code, 401)
        fresh = self.client.post('/api/auth/login', headers={'Origin': ORIGIN}, json={'username': 'viewer', 'password': new_password})
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.json()['role'], 'viewer')

    def test_anonymous_cannot_read_history_or_write_and_device_needs_key(self):
        for path in ("/api/auth/me", "/api/session/current", "/api/sessions", "/api/sessions/bad", "/api/audit-logs"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post("/api/sessions/new").status_code, 401)
        self.assertEqual(self.client.post("/infer").status_code, 401)
        self.assertEqual(self.client.post("/infer", headers={"X-API-Key": "wrong-key"}).status_code, 401)
        self.assertEqual(self.client.get("/api/sessions", headers={"X-API-Key": self.key}).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_cloud_readiness_detects_database_outage_without_disclosing_credentials(self):
        self.assertEqual(self.client.get("/ready").json()["status"], "ready")
        self.assertEqual(self.client.get("/", follow_redirects=False).headers["location"], "/dashboard/")
        with patch.object(database, "check_database", side_effect=psycopg.OperationalError("private-database-secret")):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-database-secret", response.text)

    def test_render_bootstrap_is_atomic_and_never_overwrites_or_recreates_admin(self):
        # Every connection here uses only this class's isolated PostgreSQL schema.
        with database.connect() as db:
            db.execute("DROP TABLE auth_sessions,login_limits,fruit_results,audit_logs,sorting_sessions,app_users,schema_version CASCADE")
        with patch.dict(os.environ, {"INITIALIZE_DATABASE": "false"}):
            with self.assertRaises(RuntimeError):
                render_start.prepare_database()
        with patch.dict(os.environ, {"INITIALIZE_DATABASE": "true", "BOOTSTRAP_ADMIN_PASSWORD": "short"}):
            with self.assertRaises(RuntimeError):
                render_start.prepare_database()
        with database.connect() as db:
            self.assertIsNone(db.execute("SELECT to_regclass('schema_version') AS name").fetchone()["name"])
        settings = {"INITIALIZE_DATABASE": "true", "BOOTSTRAP_ADMIN_USERNAME": "admin", "BOOTSTRAP_ADMIN_PASSWORD": self.password}
        with patch.dict(os.environ, settings):
            render_start.prepare_database()
        self.login()
        with database.connect() as db:
            original = db.execute("SELECT id,password_hash FROM app_users").fetchone()
        with patch.dict(os.environ, {**settings, "BOOTSTRAP_ADMIN_PASSWORD": "different-password-123"}):
            render_start.prepare_database()
        with database.connect() as db:
            unchanged = db.execute("SELECT id,password_hash FROM app_users").fetchone()
            self.assertEqual(original, unchanged)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM audit_logs WHERE action='account.bootstrap'").fetchone()["n"], 1)
            db.execute("UPDATE app_users SET active=false")
        with patch.dict(os.environ, settings):
            with self.assertRaises(RuntimeError):
                render_start.prepare_database()

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

    def send_image(self, key="request-test", fruit="F-test", camera="phone_cam01", content=None, client=None):
        return (client or self.client).post("/infer", headers={"X-API-Key": self.key, "Idempotency-Key": key},
            data={"fruit_id": fruit, "camera_id": camera},
            files={"image": ("fruit.jpg", content or (ROOT / "cloud-ai/quatsample.jpg").read_bytes(), "image/jpeg")})

    def test_inference_receipt_survives_rollover_restart_and_model_change(self):
        with patch.multiple(main, model_ready=False, ort_session=None):
            first = self.send_image()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["request_id"], "request-test")
        _, headers = self.login()
        original = self.client.get("/api/session/current").json()["id"]
        self.client.post("/api/sessions/new", headers=headers).raise_for_status()
        with TestClient(main.app) as restarted, patch.object(main, "classify_image", side_effect=AssertionError("Must replay, not classify")):
            repeat = self.send_image(client=restarted)
        self.assertEqual(repeat.json(), first.json())
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM fruit_results").fetchone()["n"], 1)
            self.assertEqual(str(db.execute("SELECT session_id FROM fruit_results").fetchone()["session_id"]), original)

    def test_idempotency_key_cannot_be_reused_for_other_input(self):
        with patch.multiple(main, model_ready=False, ort_session=None):
            self.assertEqual(self.send_image().status_code, 200)
            for change in ({"fruit": "other"}, {"camera": "other"}, {"content": (ROOT / "cloud-ai/ripe.jpg").read_bytes()}):
                with self.subTest(change=list(change)):
                    result = self.send_image(**change)
                    self.assertEqual(result.status_code, 409, result.text)
                    self.assertEqual(result.json()["detail"], "IDEMPOTENCY_KEY_REUSED")
            self.assertEqual(self.send_image(key="bad key").status_code, 422)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM fruit_results").fetchone()["n"], 1)

    def test_concurrent_identical_requests_create_one_fruit_and_one_receipt(self):
        with patch.multiple(main, model_ready=False, ort_session=None):
            with ThreadPoolExecutor(max_workers=6) as workers:
                replies = list(workers.map(lambda _: self.send_image(), range(12)))
        self.assertTrue(all(r.status_code == 200 for r in replies))
        self.assertTrue(all(r.json() == replies[0].json() for r in replies))
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM fruit_results").fetchone()["n"], 1)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM inference_requests").fetchone()["n"], 1)

    def test_inference_receipt_and_result_roll_back_together(self):
        data = {"fruit_id": "F-test", "camera_id": "phone_cam01", "label": "GREEN", "confidence": .9,
                "inference_ms": 1., "decision_reason": "CLASSIFIED", "model_version": "test"}
        with patch.object(database, "Jsonb", side_effect=RuntimeError("Receipt write failed")):
            with self.assertRaises(RuntimeError):
                database.record_inference_once("request-test", "F-test", "phone_cam01", b"jpeg", lambda: data)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM fruit_results").fetchone()["n"], 0)
            self.assertEqual(db.execute("SELECT count(*) AS n FROM inference_requests").fetchone()["n"], 0)
        database.record_inference_once("request-test", "F-test", "phone_cam01", b"jpeg", lambda: data)

    def test_bridge_lost_http_response_retries_once_without_duplicate_data_or_servo(self):
        import tempfile
        import requests
        from unittest.mock import Mock
        sys.path.insert(0, str(ROOT / "camera-bridge"))
        import bridge

        class LostResponseTransport:
            def __init__(transport):
                transport.calls = 0

            def post(transport, url, **kwargs):
                reply = self.client.post("/infer", headers=kwargs["headers"], data=kwargs["data"], files=kwargs["files"])
                transport.calls += 1
                if transport.calls == 1:
                    raise requests.Timeout("Simulate response lost after PostgreSQL committed")
                result = requests.Response()
                result.status_code, result._content, result._content_consumed = reply.status_code, reply.content, True
                return result

        settings = bridge.Settings(phone_url="http://phone/shot.jpg", api_key=self.key)
        transport = LostResponseTransport()
        camera, port = Mock(), Mock()
        camera.capture.return_value = (ROOT / "cloud-ai/quatsample.jpg").read_bytes()
        port.write.side_effect = len
        def classify(fruit_id, camera_id, content):
            return {"fruit_id": fruit_id, "camera_id": camera_id, "label": "GREEN", "raw_label": "GREEN", "confidence": .95,
                    "decision_reason": "CLASSIFIED", "model_version": "integration-test", "inference_ms": 1., "image_bytes": len(content)}
        with tempfile.TemporaryDirectory() as folder, patch.object(main, "classify_image", side_effect=classify), patch.object(bridge.time, "sleep"):
            journal = bridge.EventJournal(Path(folder) / "state.sqlite3")
            try:
                label = bridge.process_trigger("boot1:1", settings, camera, bridge.CloudAI(settings, transport), journal, port)
                self.assertEqual(label, "GREEN")
                self.assertIsNone(bridge.process_trigger("boot1:1", settings, camera, bridge.CloudAI(settings, transport), journal, port))
            finally:
                journal.close()
        self.assertEqual(transport.calls, 2)
        port.write.assert_called_once_with(b"SORT:GREEN\n")
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM fruit_results").fetchone()["n"], 1)

    def test_v1_migration_requires_opt_in_and_preserves_data_and_accounts(self):
        with database.connect() as db:
            admin = db.execute("SELECT id,password_hash FROM app_users WHERE role='admin'").fetchone()
            db.execute("DROP TABLE inference_requests")
            db.execute("DELETE FROM schema_version WHERE version=2")
        try:
            with patch.dict(os.environ, {"MIGRATE_DATABASE": "false"}):
                with self.assertRaisesRegex(config.ConfigurationError, "MIGRATE_DATABASE"):
                    render_start.prepare_database()
            with patch.dict(os.environ, {"MIGRATE_DATABASE": "true"}):
                render_start.prepare_database()
                render_start.prepare_database()
            with database.connect() as db:
                self.assertEqual(db.execute("SELECT id,password_hash FROM app_users WHERE role='admin'").fetchone(), admin)
                self.assertEqual(db.execute("SELECT count(*) AS n FROM app_users").fetchone()["n"], 2)
            database.check_database()
        finally:
            with database.connect() as db:
                db.execute((ROOT / "cloud-ai/schema.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
