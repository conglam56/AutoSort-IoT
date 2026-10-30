"""Verify the shipped model, not only synthetic ONNX fixtures."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cloud-ai'))
from worker import Engine


class BundledModelTests(unittest.TestCase):
    def test_release_checksum_and_real_inference_contract(self):
        folder = ROOT / 'cloud-ai/model'
        for line in (folder / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertIn(name, {'best.onnx', 'classes.json'})
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
        engine = Engine(folder)
        health = engine.health()
        self.assertTrue(health['model_ready'], health)
        self.assertEqual(health['mode'], 'onnx')
        self.assertEqual(health['task'], 'detect')
        self.assertEqual(health['classes'], ['GREEN', 'RIPE', 'REJECT'])
        self.assertEqual(health['model_version'], 'autosort-yolo11n-detect-v1-policy3')
        self.assertEqual(health['decision_policy'], 'highest_confidence')
        for name in ('quatsample.jpg', 'ripe.jpg', 'reject.jpg'):
            with self.subTest(image=name):
                result = engine.classify('release-probe', 'sample-only', (ROOT / 'cloud-ai' / name).read_bytes())
                self.assertIn(result['label'], {'GREEN', 'RIPE', 'REJECT'})
                self.assertIn(result['decision_reason'], {'CLASSIFIED', 'LOW_CONFIDENCE'})
                self.assertEqual(result['model_version'], health['model_version'])
                self.assertEqual(result['fruit_id'], 'release-probe')
                if result['decision_reason'] == 'LOW_CONFIDENCE':
                    self.assertEqual(result['label'], 'REJECT')
