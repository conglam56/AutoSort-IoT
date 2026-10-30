"""Real video decoding, isolated capture deadlines, and offline-only previews."""
from dataclasses import replace
import io
import json
import os
import runpy
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'camera-bridge'))
import bridge
import camera_check
import local_camera


def stalled_driver(connection, *args):
    time.sleep(60)


class LocalCameraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.video = self.folder / 'sample.avi'
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*'MJPG'), 1, (64, 48))
        self.assertTrue(writer.isOpened())
        for color in [(0, 240, 0), (0, 0, 240), (240, 0, 0)]:
            writer.write(np.full((48, 64, 3), color, dtype=np.uint8))
        writer.release()
        self.settings = bridge.Settings(phone_url='', api_key='', camera_source='video',
                                        video_path=str(self.video), capture_timeout=5)

    def camera(self):
        camera = local_camera.LocalCamera(self.settings)
        self.addCleanup(camera.close)
        return camera

    def test_video_advances_persistent_handle_and_never_repeats_on_eof(self):
        camera = self.camera()
        for expected_channel in (1, 0, 2):  # JPEG pixels are RGB; fixture is BGR.
            content = camera.capture(time.monotonic() + 5)
            self.assertTrue(content.startswith(b'\xff\xd8'))
            self.assertLessEqual(len(content), bridge.MAX_IMAGE_BYTES)
            with Image.open(io.BytesIO(content)) as image:
                self.assertEqual(image.size, (64, 48))
                means = np.asarray(image).mean(axis=(0, 1))
                self.assertEqual(int(np.argmax(means)), expected_channel)
        process = camera._process
        with self.assertRaisesRegex(bridge.BridgeError, 'hết video'):
            camera.capture(time.monotonic() + 5)
        self.assertFalse(process.is_alive())
        with self.assertRaises(bridge.BridgeError):
            camera.capture(time.monotonic() + 5)

    def test_stalled_native_driver_is_terminated_within_deadline_and_cannot_reuse_frame(self):
        camera = self.camera()
        with patch.object(local_camera, 'camera_worker', stalled_driver):
            camera._start()
        process = camera._process
        began = time.monotonic()
        with self.assertRaisesRegex(bridge.BridgeError, 'quá hạn'):
            camera.capture(began + .3)
        self.assertLess(time.monotonic() - began, 2)
        self.assertFalse(process.is_alive())
        with self.assertRaises(bridge.BridgeError):
            camera.capture(time.monotonic() + 5)

    def test_expired_job_does_not_open_any_capture_process(self):
        camera = self.camera()
        with patch.object(camera, '_start') as start, self.assertRaises(bridge.BridgeError):
            camera.capture(time.monotonic() - 1)
        start.assert_not_called()

    def test_missing_or_broken_video_fails_instead_of_falling_back_to_webcam(self):
        self.video.write_bytes(b'not a video')
        with self.assertRaises(bridge.BridgeError):
            self.camera().capture(time.monotonic() + 5)

    def test_encoding_bounds_dimensions_and_bytes(self):
        frame = np.random.default_rng(42).integers(0, 256, (1800, 2400, 3), dtype=np.uint8)
        content = local_camera.encode_frame(frame)
        self.assertLessEqual(len(content), bridge.MAX_IMAGE_BYTES)
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size, (1600, 1200))
        for invalid in (None, np.zeros((0, 0, 3), np.uint8), np.zeros((3, 3), np.uint8)):
            with self.assertRaises(ValueError):
                local_camera.encode_frame(invalid)

    def test_configuration_needs_no_phone_url_for_webcam_and_no_secrets_for_preview(self):
        values = {'CAMERA_SOURCE': 'webcam', 'CAMERA_INDEX': '2', 'SERIAL_PORT': 'COM3',
                  'DEVICE_API_KEY': 'k'*40}
        with patch.dict(os.environ, values, clear=True):
            settings = bridge.Settings.from_environment()
            self.assertEqual(settings.camera_index, 2)
            self.assertEqual(settings.phone_url, '')
        with patch.dict(os.environ, {'CAMERA_SOURCE': 'webcam'}, clear=True):
            bridge.Settings.from_environment(manual=True, camera_only=True)
            with self.assertRaises(bridge.BridgeError):
                bridge.Settings.from_environment(manual=True)
        for changes in ({'CAMERA_SOURCE': 'other'}, {'CAMERA_INDEX': '-1'},
                        {'CAMERA_BACKEND': 'unknown'}, {'CAMERA_SOURCE': 'video', 'CAMERA_VIDEO_PATH': ''}):
            with patch.dict(os.environ, {**values, **changes}, clear=True), self.assertRaises(bridge.BridgeError):
                bridge.Settings.from_environment(manual=True)

    def test_video_is_explicitly_forbidden_in_real_conveyor_mode(self):
        values = {'CAMERA_SOURCE': 'video', 'CAMERA_VIDEO_PATH': str(self.video),
                  'DEVICE_API_KEY': 'k'*40, 'SERIAL_PORT': 'COM3'}
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(bridge.BridgeError, 'không dùng để điều khiển'):
                bridge.Settings.from_environment()
            bridge.Settings.from_environment(manual=True)

    def test_factory_preserves_existing_phone_path_and_selects_local_only_when_requested(self):
        session = Mock()
        phone = bridge.create_camera(replace(self.settings, camera_source='phone'), session)
        self.assertIsInstance(phone, bridge.PhoneCamera)
        self.assertIs(phone.session, session)
        local = bridge.create_camera(self.settings, session)
        self.addCleanup(local.close)
        self.assertIsInstance(local, local_camera.LocalCamera)

    def test_script_entrypoint_and_imported_camera_share_error_type(self):
        entrypoint = runpy.run_path(str(ROOT / 'camera-bridge/bridge.py'))
        self.assertIs(entrypoint['BridgeError'], local_camera.BridgeError)

    def test_webcam_uses_selected_index_backend_and_reads_after_request_not_cached_frame(self):
        connection, driver = Mock(), Mock()
        connection.poll.side_effect = [False, True, True]
        connection.recv.side_effect = ['capture', 'close']
        driver.read.side_effect = [(True, np.full((4, 4, 3), 10, np.uint8)),
                                   (True, np.full((4, 4, 3), 200, np.uint8))]
        with patch.object(cv2, 'VideoCapture', return_value=driver) as capture:
            local_camera.camera_worker(connection, 'webcam', 2, 'dshow', '')
        capture.assert_called_once_with(2, cv2.CAP_DSHOW)
        kind, content = connection.send.call_args.args[0]
        self.assertEqual(kind, 'frame')
        with Image.open(io.BytesIO(content)) as image:
            self.assertGreater(float(np.asarray(image).mean()), 190)
        driver.release.assert_called_once()

    def test_disconnected_webcam_sends_error_and_never_reuses_last_frame(self):
        connection, driver = Mock(), Mock()
        connection.poll.return_value = True
        connection.recv.return_value = 'capture'
        driver.read.return_value = (False, None)
        with patch.object(cv2, 'VideoCapture', return_value=driver):
            local_camera.camera_worker(connection, 'webcam', 0, 'auto', '')
        connection.send.assert_called_once_with(('error', 'CAMERA_LOST'))
        driver.release.assert_called_once()

    def test_preview_writes_real_images_and_report_without_cloud_serial_or_credentials(self):
        output = self.folder / 'preview'
        with patch.dict(os.environ, {}, clear=True), patch.object(camera_check, 'load_dotenv'), \
                patch.object(bridge.serial, 'Serial') as serial, \
                patch.object(bridge.CloudAI, 'classify') as infer, \
                patch.object(bridge.requests.Session, 'post') as post:
            code = camera_check.main(['--source', 'video', '--video-file', str(self.video),
                                      '--frames', '3', '--interval', '0', '--output', str(output)])
        self.assertEqual(code, 0)
        serial.assert_not_called()
        infer.assert_not_called()
        post.assert_not_called()
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'ok')
        self.assertFalse(report['cloud_contacted'])
        self.assertFalse(report['serial_opened'])
        self.assertEqual(len(report['frames']), 3)
        self.assertTrue((output / 'index.html').is_file())
        self.assertTrue(all((output / row['file']).is_file() for row in report['frames']))

    def test_preview_reports_eof_instead_of_silently_repeating_and_does_not_overwrite(self):
        output = self.folder / 'preview'
        with patch.dict(os.environ, {}, clear=True), patch.object(camera_check, 'load_dotenv'):
            code = camera_check.main(['--source', 'video', '--video-file', str(self.video),
                                      '--frames', '4', '--interval', '0', '--output', str(output)])
        self.assertEqual(code, 1)
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(len(report['frames']), 3)
        self.assertEqual(report['status'], 'error')
        original = (output / 'report.json').read_bytes()
        with patch.dict(os.environ, {}, clear=True), patch.object(camera_check, 'load_dotenv'):
            self.assertEqual(camera_check.main(['--source', 'video', '--video-file', str(self.video),
                                               '--output', str(output)]), 1)
        self.assertEqual((output / 'report.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
