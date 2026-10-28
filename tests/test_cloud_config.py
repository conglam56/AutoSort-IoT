"""Deployment origin and cookie policy must not fall back to localhost in cloud."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud-ai"))
import config
import render_start


class CloudConfigurationTests(unittest.TestCase):
    def test_deploy_logs_actionable_configuration_errors_but_redacts_driver_secrets(self):
        cases = [
            (config.ConfigurationError("Set DATABASE_URL to a PostgreSQL connection URL"), "DATABASE_URL"),
            (RuntimeError("private-database-password"), "RuntimeError"),
        ]
        for failure, expected in cases:
            with self.subTest(error=type(failure).__name__), patch.object(render_start, "prepare_database", side_effect=failure):
                with self.assertLogs("autosort-deploy", level="ERROR") as captured:
                    with self.assertRaises(SystemExit):
                        render_start.main()
                self.assertIn(expected, " ".join(captured.output))
                self.assertNotIn("private-database-password", " ".join(captured.output))

    def test_render_uses_exact_service_https_origin(self):
        with patch.dict(os.environ, {"RENDER": "true", "RENDER_EXTERNAL_URL": "https://autosort-iot.onrender.com/"}, clear=True):
            self.assertEqual(config.read_allowed_origins(), ["https://autosort-iot.onrender.com"])
        with patch.dict(os.environ, {"RENDER": "true"}, clear=True):
            self.assertEqual(config.read_allowed_origins(), [])

    def test_local_defaults_and_explicit_custom_domain(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.read_allowed_origins(), ["http://127.0.0.1:8000", "http://localhost:8000"])
        with patch.dict(os.environ, {"RENDER": "true", "ALLOWED_ORIGINS": "https://sort.example.com"}, clear=True):
            self.assertEqual(config.read_allowed_origins(), ["https://sort.example.com"])

    def test_render_rejects_insecure_cookie_or_origin(self):
        with patch.dict(os.environ, {"RENDER": "true"}), patch.multiple(
            config, DATABASE_URL="postgresql://test:test@localhost/test", DEVICE_API_KEY="x" * 40,
            COOKIE_SECURE=False, ALLOWED_ORIGINS=["http://localhost:8000"]
        ):
            with self.assertRaises(RuntimeError):
                config.validate_config()
        with patch.dict(os.environ, {"RENDER": "true"}), patch.multiple(
            config, DATABASE_URL="postgresql://test:test@localhost/test", DEVICE_API_KEY="x" * 40,
            COOKIE_SECURE=True, ALLOWED_ORIGINS=["https://autosort-iot.onrender.com"]
        ):
            config.validate_config()


if __name__ == "__main__":
    unittest.main()
