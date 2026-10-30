"""Exercise production worker initialization and inference with real ONNX graphs."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cloud-ai'))
from worker import Engine, EngineError


class DetectionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.meta = {'task': 'detect', 'output_format': 'yolo11_raw', 'classes': ['GREEN', 'RIPE', 'REJECT'],
                     'idx_to_class': {'0': 'GREEN', '1': 'RIPE', '2': 'REJECT'},
                     'imgsz': 320, 'threshold': .7, 'model_version': 'test-detector-v1'}

    def engine(self, output):
        output = np.asarray(output, dtype=np.float32)
        graph = helper.make_graph([
            helper.make_node('Constant', [], ['predictions'], value=numpy_helper.from_array(output))
        ], 'constant-detector', [helper.make_tensor_value_info('images', TensorProto.FLOAT, [1, 3, 320, 320])],
            [helper.make_tensor_value_info('predictions', TensorProto.FLOAT, list(output.shape))])
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)])
        model.ir_version = 10
        onnx.save(model, self.folder / 'best.onnx')
        (self.folder / 'classes.json').write_text(json.dumps(self.meta), encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()):
            return Engine(self.folder)

    def test_real_onnx_detector_initializes_and_returns_existing_protocol(self):
        output = [[[160], [160], [200], [200], [.95], [.01], [.01]]]
        engine = self.engine(output)
        self.assertTrue(engine.model_ready)
        self.assertEqual(engine.health()['task'], 'detect')
        result = engine.classify('F-test', 'phone-test', (ROOT / 'cloud-ai/quatsample.jpg').read_bytes())
        self.assertEqual(result['label'], 'GREEN')
        self.assertEqual(result['raw_label'], 'GREEN')
        self.assertEqual(result['decision_reason'], 'CLASSIFIED')
        self.assertEqual(result['fruit_id'], 'F-test')

    def test_no_detection_is_an_explicit_low_confidence_reject(self):
        engine = self.engine(np.zeros((1, 7, 1), dtype=np.float32))
        result = engine.classify('F-test', 'phone-test', (ROOT / 'cloud-ai/quatsample.jpg').read_bytes())
        self.assertEqual(result['label'], 'REJECT')
        self.assertEqual(result['decision_reason'], 'LOW_CONFIDENCE')
        self.assertEqual(result['decision_detail'], 'NO_TARGET')

    def test_real_onnx_qualified_ripe_ignores_weak_side_fruit(self):
        output = np.zeros((1, 7, 3), dtype=np.float32)
        output[0, :4] = [[160, 296, 284], [160, 228, 70], [264, 48, 72], [252, 176, 140]]
        output[0, 5] = [.91831839, .64315474, .62864077]
        engine = self.engine(output)
        result = engine.classify('F-threshold', 'phone-test', (ROOT / 'cloud-ai/quatsample.jpg').read_bytes())
        self.assertEqual(result['label'], 'RIPE')
        self.assertEqual(result['confidence'], .9183)
        self.assertEqual(result['decision_reason'], 'CLASSIFIED')

    def test_wrong_detection_shape_never_reports_ready(self):
        engine = self.engine(np.zeros((1, 6, 1), dtype=np.float32))
        self.assertFalse(engine.model_ready)
        self.assertEqual(engine.health()['mode'], 'mock')

    def test_incompatible_detection_values_fail_instead_of_classifying(self):
        engine = self.engine(np.full((1, 7, 1), 2., dtype=np.float32))
        self.assertTrue(engine.model_ready)
        with self.assertRaises(EngineError) as caught:
            engine.classify('F-test', 'phone-test', (ROOT / 'cloud-ai/quatsample.jpg').read_bytes())
        self.assertEqual(caught.exception.status, 500)


if __name__ == '__main__':
    unittest.main()
