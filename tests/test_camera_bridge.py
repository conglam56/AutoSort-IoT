"""Phone/HTTP/Serial failure paths, without a physical camera or controller."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import requests
import serial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "camera-bridge"))
import bridge


def response(payload=None, status=200, body=None, headers=None):
    result = Mock()
    result.status_code = status
    result.headers = headers or {}
    result.iter_content.return_value = [body if body is not None else json.dumps(payload).encode()]
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def prediction(**changes):
    return {"fruit_id": "F-test", "request_id": "request-test", "camera_id": "phone_cam01",
            "label": "GREEN", "raw_label": "GREEN", "confidence": .95,
            "decision_reason": "CLASSIFIED", "model_version": "test-v1", **changes}


class CameraBridgeTests(unittest.TestCase):
    def setUp(self):
        self.settings = bridge.Settings(phone_url="http://192.168.1.15:8080/shot.jpg", api_key="k" * 40)
        self.session = Mock()
        self.cloud = bridge.CloudAI(self.settings, self.session)

    def test_configuration_requires_phone_key_and_explicit_serial_or_manual(self):
        values = {"PHONE_IP_WEBCAM_URL": self.settings.phone_url, "DEVICE_API_KEY": self.settings.api_key}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(bridge.Settings.from_environment(manual=True).camera_id, "phone_cam01")
            with self.assertRaises(bridge.BridgeError):
                bridge.Settings.from_environment()
        for changes in ({"JOB_TIMEOUT_SECONDS": "nan"}, {"CLOUD_MAX_ATTEMPTS": "0"},
                        {"CLOUD_INFER_URL": "http://remote.example/infer"}, {"DEVICE_API_KEY": "replace_private_key"},
                        {"PHONE_IP_WEBCAM_URL": "http://user:secret@phone/shot.jpg"}):
            with self.subTest(changes=changes), patch.dict(os.environ, {**values, **changes}, clear=True):
                with self.assertRaises(bridge.BridgeError):
                    bridge.Settings.from_environment(manual=True)

    def test_phone_accepts_real_jpeg_and_rejects_html_corrupt_and_oversize(self):
        content = io.BytesIO()
        Image.new("RGB", (32, 32)).save(content, format="JPEG")
        for image, valid in ((content.getvalue(), True), (b"<html>login</html>", False),
                             (b"\xff\xd8broken", False), (b"x" * 1_000_001, False)):
            self.session.get.return_value = response(body=image)
            camera = bridge.PhoneCamera(self.settings, self.session)
            with self.subTest(size=len(image)):
                if valid:
                    self.assertEqual(camera.capture(time.monotonic() + 10), image)
                else:
                    with self.assertRaises(bridge.BridgeError):
                        camera.capture(time.monotonic() + 10)

    def test_startup_requires_database_real_model_and_idempotency(self):
        for health, ready_status in (({"mode": "mock", "model_ready": False}, 200),
                                     ({"mode": "onnx", "model_ready": True}, 200),
                                     ({"mode": "onnx", "model_ready": True, "idempotency_supported": True}, 503)):
            self.session.get.side_effect = [response({"status": "ready"}, ready_status), response(health)]
            with self.subTest(health=health), self.assertRaises(bridge.BridgeError):
                self.cloud.check_ready()
        self.session.get.side_effect = [response({"status": "ready"}), response({"mode": "onnx", "model_ready": True, "idempotency_supported": True})]
        self.cloud.check_ready()
        self.session.post.assert_not_called()

    def test_lost_response_reuses_identical_image_ids_and_idempotency_key(self):
        self.session.post.side_effect = [requests.Timeout("private-url-with-key"), response(prediction())]
        with patch.object(bridge.time, "sleep"):
            self.assertEqual(self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() + 20), "GREEN")
        calls = self.session.post.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0].kwargs["headers"]["Idempotency-Key"], "request-test")
        self.assertFalse(calls[0].kwargs["allow_redirects"])

    def test_broken_response_stream_retries_the_same_request(self):
        self.session.post.side_effect = [requests.exceptions.ChunkedEncodingError("stream lost"), response(prediction())]
        with patch.object(bridge.time, "sleep"):
            self.assertEqual(self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() + 20), "GREEN")
        self.assertEqual(self.session.post.call_count, 2)
        self.assertEqual(self.session.post.call_args_list[0], self.session.post.call_args_list[1])

    def test_transient_errors_retry_but_rejections_and_bad_payloads_do_not(self):
        for status in (429, 500, 502, 503, 504):
            self.session.post.reset_mock()
            self.session.post.side_effect = [response(status=status), response(prediction())]
            with self.subTest(status=status), patch.object(bridge.time, "sleep"):
                self.assertEqual(self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() + 20), "GREEN")
                self.assertEqual(self.session.post.call_count, 2)
        for reply in (response(status=401), response(status=409), response(status=413), response(status=302), response(body=b"<html>oops</html>")):
            self.session.post.reset_mock()
            self.session.post.side_effect = None
            self.session.post.return_value = reply
            with self.assertRaises(bridge.BridgeError):
                self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() + 20)
            self.assertEqual(self.session.post.call_count, 1)

    def test_retry_budget_respects_attempts_deadline_and_retry_after(self):
        self.session.post.side_effect = requests.ConnectionError("private-url")
        with patch.object(bridge.time, "sleep"), self.assertRaises(bridge.BridgeError):
            self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() + 20)
        self.assertEqual(self.session.post.call_count, 3)
        self.session.post.reset_mock()
        with self.assertRaises(bridge.BridgeError):
            self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() - 1)
        self.session.post.assert_not_called()
        self.session.post.side_effect = None
        self.session.post.return_value = response(status=429, headers={"Retry-After": "900"})
        with patch.object(bridge.time, "sleep") as sleep, self.assertRaises(bridge.BridgeError):
            self.cloud.classify(b"jpeg", "F-test", "request-test", time.monotonic() + 20)
        sleep.assert_not_called()
        self.assertEqual(self.session.post.call_count, 1)

    def test_mock_unknown_wrong_identity_and_invalid_numbers_are_never_labels(self):
        for changes in ({"label": "MOCK"}, {"label": "UNKNOWN"}, {"label": []}, {"request_id": "other"},
                        {"fruit_id": "F-other"}, {"camera_id": "other"}, {"confidence": float("nan")},
                        {"confidence": 1.5}, {"confidence": True}, {"decision_reason": []},
                        {"decision_reason": "MOCK_MODE"}, {"model_version": "mock-v0"},
                        {"decision_reason": "LOW_CONFIDENCE"}):
            with self.subTest(changes=changes), self.assertRaises(bridge.BridgeError):
                self.cloud.validate(prediction(**changes), "F-test", "request-test")
        self.assertEqual(self.cloud.validate(prediction(label="REJECT", decision_reason="LOW_CONFIDENCE"), "F-test", "request-test"), "REJECT")

    def test_journal_blocks_duplicate_triggers_across_restart_and_keeps_uncertain_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            journal = bridge.EventJournal(path)
            first = journal.claim("phone", "boot1:1")
            journal.close()  # Simulate interruption before serial completion.
            journal = bridge.EventJournal(path)
            try:
                self.assertIsNone(journal.claim("phone", "boot1:1"))
                self.assertNotEqual(journal.claim("phone", "boot2:1"), first)
                self.assertNotEqual(journal.claim("phone", None), journal.claim("phone", None))
            finally:
                journal.close()

    def test_one_trigger_has_one_serial_write_and_duplicate_has_none(self):
        with tempfile.TemporaryDirectory() as folder, bridge.EventJournal(Path(folder) / "state.sqlite3") as journal:
            port, camera, cloud = Mock(), Mock(), Mock()
            port.write.side_effect = len
            cloud.classify.return_value = "RIPE"
            self.assertEqual(bridge.process_trigger("boot:1", self.settings, camera, cloud, journal, port), "RIPE")
            self.assertIsNone(bridge.process_trigger("boot:1", self.settings, camera, cloud, journal, port))
            port.write.assert_called_once_with(b"SORT:RIPE\n")
            camera.capture.assert_called_once()
            args = cloud.classify.call_args.args
            self.assertEqual(args[1], "F-" + args[2])

    def test_camera_cloud_mock_and_deadline_failures_only_send_reject(self):
        with tempfile.TemporaryDirectory() as folder, bridge.EventJournal(Path(folder) / "state.sqlite3") as journal:
            for kind in ("camera", "cloud", "mock", "late"):
                port, camera, cloud = Mock(), Mock(), Mock()
                port.write.side_effect = len
                cloud.classify.return_value = "MOCK" if kind == "mock" else "GREEN"
                if kind == "camera":
                    camera.capture.side_effect = bridge.BridgeError("Camera timeout")
                if kind == "cloud":
                    cloud.classify.side_effect = bridge.BridgeError("Cloud timeout")
                clock = [0, 21] if kind == "late" else [0, 1]
                with self.subTest(kind=kind), patch.object(bridge.time, "monotonic", side_effect=clock):
                    self.assertEqual(bridge.process_trigger(kind, self.settings, camera, cloud, journal, port), "REJECT")
                    port.write.assert_called_once_with(b"SORT:REJECT\n")

    def test_partial_serial_write_is_not_retried_or_marked_completed(self):
        with tempfile.TemporaryDirectory() as folder, bridge.EventJournal(Path(folder) / "state.sqlite3") as journal:
            port, camera, cloud = Mock(), Mock(), Mock()
            port.write.return_value = 2
            cloud.classify.return_value = "GREEN"
            with self.assertRaises(serial.SerialException):
                bridge.process_trigger("boot:1", self.settings, camera, cloud, journal, port)
            port.write.assert_called_once()
            self.assertEqual(journal.db.execute("SELECT status FROM events").fetchone()[0], "processing")
            self.assertIsNone(bridge.process_trigger("boot:1", self.settings, camera, cloud, journal, port))
            self.assertEqual(port.write.call_count, 1)

    def test_serial_open_failure_exits_instead_of_falling_back_to_manual(self):
        settings = bridge.Settings(phone_url=self.settings.phone_url, api_key=self.settings.api_key, serial_port="COM-test")
        with patch.object(sys, "argv", ["bridge.py"]), patch.object(bridge.Settings, "from_environment", return_value=settings), \
                patch.object(bridge.CloudAI, "check_ready"), patch.object(bridge, "EventJournal") as journal, \
                patch.object(bridge.serial, "Serial", side_effect=serial.SerialException("private")), patch("builtins.input") as manual:
            self.assertEqual(bridge.main(), 1)
            manual.assert_not_called()
            journal.return_value.close.assert_called_once()

    def test_trigger_protocol(self):
        self.assertIsNone(bridge.parse_trigger("TRIGGER"))
        self.assertEqual(bridge.parse_trigger("TRIGGER:boot-123:4"), "boot-123:4")
        for line in ("TRIGGER:", "hello", "TRIGGER:bad id", "TRIGGER:" + "x" * 97):
            self.assertEqual(bridge.parse_trigger(line), "")


if __name__ == "__main__":
    unittest.main()
