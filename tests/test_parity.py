"""Check that the parity tool detects drift, without requiring trained weights."""

import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
import check_parity


class ParityTests(unittest.TestCase):
    def check(self, onnx_probabilities, input_drift=False):
        image_path = ROOT / "cloud-ai" / "quatsample.jpg"
        reference = check_parity.preprocess_image_bytes(image_path.read_bytes())
        if input_drift:
            reference = reference + np.float32(0.01)
        model = Mock()
        result = Mock()
        result.probs.data.cpu.return_value.numpy.return_value = np.array([0.95, 0.03, 0.02], dtype=np.float32)
        model.predict.return_value = [result]
        model.predictor.preprocess.return_value.cpu.return_value.numpy.return_value = reference
        session = Mock()
        session.get_inputs.return_value = [SimpleNamespace(name="images")]
        session.run.return_value = [np.array([onnx_probabilities], dtype=np.float32)]
        with contextlib.redirect_stdout(io.StringIO()):
            return check_parity.check_image(
                model, session, image_path, ["GREEN", "REJECT", "RIPE"], 224, 1e-3
            )

    def test_matching_probabilities_and_inputs_pass(self):
        self.assertTrue(self.check([0.95, 0.03, 0.02]))

    def test_probability_drift_fails_even_when_top_label_matches(self):
        self.assertFalse(self.check([0.90, 0.06, 0.04]))

    def test_preprocessing_drift_fails_even_when_probabilities_match(self):
        self.assertFalse(self.check([0.95, 0.03, 0.02], input_drift=True))

    def test_default_selection_includes_all_three_user_images(self):
        paths = check_parity.find_images(SimpleNamespace(image=None, image_dir=None))
        self.assertIn("quatsample.jpg", [p.name for p in paths])
        self.assertEqual(len(paths), len(set(paths)))

    def test_missing_weights_returns_failure_before_loading_training_dependencies(self):
        with patch.object(sys, "argv", ["check_parity.py", "--weights", "missing-weights.pt"]):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_parity.main(), 1)


if __name__ == "__main__":
    unittest.main()
