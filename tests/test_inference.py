"""Regression checks using real JPEG inputs and controlled model probabilities."""

import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np
from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import Headers, UploadFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud-ai"))
import main as api
from inference import classification_probabilities, preprocess_image_bytes


class InferenceTests(unittest.IsolatedAsyncioTestCase):
    async def predict(self, probabilities, image_name="quatsample.jpg"):
        session = Mock()
        session.run.return_value = [np.array([probabilities], dtype=np.float32)]
        upload = UploadFile(
            file=io.BytesIO((ROOT / "cloud-ai" / image_name).read_bytes()),
            filename=image_name,
            headers=Headers({"content-type": "image/jpeg"}),
        )
        with patch.multiple(
            api,
            model_ready=True,
            ort_session=session,
            input_name="images",
            confidence_threshold=0.70,
            classes_list=["GREEN", "REJECT", "RIPE"],
            idx_to_class={"0": "GREEN", "1": "REJECT", "2": "RIPE"},
        ):
            return await api.infer("F-test", "cam-test", upload)

    async def test_confident_predictions_keep_original_probability_on_all_samples(self):
        cases = [
            ("quatsample.jpg", [0.95, 0.03, 0.02], "GREEN"),
            ("reject.jpg", [0.02, 0.95, 0.03], "REJECT"),
            ("ripe.jpg", [0.02, 0.03, 0.95], "RIPE"),
        ]
        for filename, probabilities, label in cases:
            with self.subTest(image=filename):
                result = await self.predict(probabilities, filename)
                self.assertEqual(result["confidence"], 0.95)
                self.assertEqual(result["raw_label"], label)
                self.assertEqual(result["label"], label)
                self.assertEqual(result["decision_reason"], "CLASSIFIED")

    async def test_uncertain_prediction_is_rejected(self):
        result = await self.predict([0.40, 0.35, 0.25])
        self.assertEqual(result["confidence"], 0.40)
        self.assertEqual(result["raw_label"], "GREEN")
        self.assertEqual(result["label"], "REJECT")
        self.assertEqual(result["decision_reason"], "LOW_CONFIDENCE")

    async def test_threshold_is_inclusive_and_uses_unrounded_probability(self):
        at_threshold = await self.predict([0.70, 0.20, 0.10])
        self.assertEqual(at_threshold["label"], "GREEN")
        below_threshold = await self.predict([0.6999, 0.2001, 0.10])
        self.assertEqual(below_threshold["label"], "REJECT")

    async def test_incompatible_model_output_is_an_error(self):
        for output in ([2.0, 1.0, -1.0], [0.8, 0.2], [float("nan"), 0.0, 1.0]):
            with self.subTest(output=output), self.assertRaises(HTTPException) as caught:
                await self.predict(output)
            self.assertEqual(caught.exception.status_code, 500)

    async def test_missing_model_remains_explicitly_mock(self):
        upload = UploadFile(
            file=io.BytesIO((ROOT / "cloud-ai" / "quatsample.jpg").read_bytes()),
            headers=Headers({"content-type": "image/jpeg"}),
        )
        with patch.multiple(api, model_ready=False, ort_session=None):
            self.assertEqual(api.health()["mode"], "mock")
            result = await api.infer("F-test", "cam-test", upload)
        self.assertEqual(result["label"], "MOCK")
        self.assertEqual(result["confidence"], 0.0)

    async def test_corrupt_jpeg_is_client_error(self):
        upload = UploadFile(
            file=io.BytesIO(b"\xff\xd8not-a-real-jpeg"),
            headers=Headers({"content-type": "image/jpeg"}),
        )
        with patch.multiple(api, model_ready=True, ort_session=Mock()):
            with self.assertRaises(HTTPException) as caught:
                await api.infer("F-test", "cam-test", upload)
        self.assertEqual(caught.exception.status_code, 400)


class PreprocessingTests(unittest.TestCase):
    def encode(self, image, **kwargs):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", **kwargs)
        return buffer.getvalue()

    def test_all_sample_images_produce_contiguous_float32_nchw(self):
        paths = sorted((ROOT / "cloud-ai").glob("*.jpg"))
        self.assertTrue(paths, "No sample JPEGs found")
        for path in paths:
            with self.subTest(image=path.name):
                tensor = preprocess_image_bytes(path.read_bytes())
                self.assertEqual(tensor.shape, (1, 3, 224, 224))
                self.assertEqual(tensor.dtype, np.float32)
                self.assertTrue(tensor.flags.c_contiguous)
                self.assertTrue(np.isfinite(tensor).all())
                self.assertGreaterEqual(float(tensor.min()), 0.0)
                self.assertLessEqual(float(tensor.max()), 1.0)

    def test_rectangular_images_crop_center_without_stretching(self):
        pixels = np.zeros((2, 6, 3), dtype=np.uint8)
        pixels[:, :2] = [255, 0, 0]
        pixels[:, 2:4] = [0, 255, 0]
        pixels[:, 4:] = [0, 0, 255]
        for data in (pixels, pixels.transpose(1, 0, 2)):
            with self.subTest(shape=data.shape):
                tensor = preprocess_image_bytes(self.encode(Image.fromarray(data)), 2)
                np.testing.assert_array_equal(tensor[0, 1], np.ones((2, 2)))
                np.testing.assert_array_equal(tensor[0, (0, 2)], np.zeros((2, 2, 2)))

    def test_odd_crop_offset_matches_torchvision_rounding(self):
        pixels = np.zeros((2, 5, 3), dtype=np.uint8)
        pixels[:, 2:4, 0] = 255
        tensor = preprocess_image_bytes(self.encode(Image.fromarray(pixels)), 2)
        np.testing.assert_array_equal(tensor[0, 0], np.ones((2, 2)))

    def test_rgb_order_and_normalization(self):
        tensor = preprocess_image_bytes(self.encode(Image.new("RGB", (8, 4), (17, 68, 255))), 2)
        np.testing.assert_allclose(tensor[0, :, 0, 0], [17 / 255, 68 / 255, 1.0], atol=1e-7)

    def test_grayscale_converts_to_rgb(self):
        tensor = preprocess_image_bytes(self.encode(Image.new("L", (8, 4), 128)), 2)
        np.testing.assert_allclose(tensor, np.full((1, 3, 2, 2), 128 / 255), atol=1e-7)

    def test_exif_orientation_matches_physically_rotated_image(self):
        pixels = np.arange(6 * 4 * 3, dtype=np.uint8).reshape(4, 6, 3)
        image = Image.fromarray(pixels)
        exif = Image.Exif()
        exif[274] = 6  # Rotate clockwise by 90 degrees for display.
        tagged = self.encode(image, exif=exif)
        rotated = self.encode(image.transpose(Image.Transpose.ROTATE_270))
        np.testing.assert_array_equal(
            preprocess_image_bytes(tagged, 2), preprocess_image_bytes(rotated, 2)
        )

    def test_invalid_output_contract_is_rejected(self):
        invalid = (
            np.array([[0.2, 0.2, 0.2]], dtype=np.float32),
            np.array([[0.8, 0.3, -0.1]], dtype=np.float32),
            np.array([[float("inf"), 0.0, 0.0]], dtype=np.float32),
            np.array([[0, 0, 1]]),
            np.array([0.1, 0.2, 0.7], dtype=np.float32),
            np.array([[0.1, 0.2, 0.7], [0.1, 0.2, 0.7]], dtype=np.float32),
        )
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(ValueError):
                classification_probabilities(output, 3)


if __name__ == "__main__":
    unittest.main()
