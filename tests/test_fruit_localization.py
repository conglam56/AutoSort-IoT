"""Real ONNX image-dependent tests for optional whole-frame recovery."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cloud-ai'))
from detection import preprocess_detection_bytes, preprocess_detection_image
from worker import Engine


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = {'file': 'fruit.onnx', 'classes': ['orange'], 'accepted_classes': ['orange'],
                       'imgsz': 64, 'candidate_threshold': .25, 'padding': 0.0,
                       'trigger_area': .9, 'max_region_fraction': .5}
        self.meta = {'task': 'detect', 'output_format': 'yolo11_raw',
                     'classes': ['GREEN', 'RIPE', 'REJECT'], 'imgsz': 64, 'threshold': 0.,
                     'decision_policy': 'highest_confidence', 'model_version': 'test-recovery',
                     'localizer': self.config}
        image = np.zeros((64, 64, 3), np.uint8)
        image[:, :, 1] = 255
        image[24:40, 24:40] = [0, 0, 255]
        self.jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 100])[1].tobytes()
        self.localizer()
        self.quality()

    def save(self, nodes, initializers, channels, filename):
        graph = helper.make_graph(nodes, filename,
                                  [helper.make_tensor_value_info('images', TensorProto.FLOAT, [1, 3, 64, 64])],
                                  [helper.make_tensor_value_info('predictions', TensorProto.FLOAT, [1, channels, 1])],
                                  initializer=initializers)
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)])
        model.ir_version = 10
        onnx.checker.check_model(model)
        onnx.save(model, self.directory / filename)

    def localizer(self, score=.3, box=(32, 32, 16, 16)):
        raw = np.asarray([[*box, score]], np.float32).T[None]
        self.save([helper.make_node('Constant', [], ['predictions'], value=numpy_helper.from_array(raw))],
                  [], 5, 'fruit.onnx')

    def quality(self, box=(32, 32, 64, 64), ripe=None):
        # Green full scene, red small fruit. Confidence comes from image pixels.
        constants = [('box', np.asarray(box, np.float32)[None, :, None]),
                     ('zero', np.zeros((1, 1, 1), np.float32)),
                     ('green_index', np.asarray([1], np.int64)),
                     ('red_index', np.asarray([0], np.int64)),
                     ('shape', np.asarray([1, 1, 1], np.int64))]
        nodes = [helper.make_node('ReduceMean', ['images'], ['means'], axes=[2, 3], keepdims=0),
                 helper.make_node('Gather', ['means', 'green_index'], ['g'], axis=1),
                 helper.make_node('Gather', ['means', 'red_index'], ['r'], axis=1),
                 helper.make_node('Reshape', ['g', 'shape'], ['green']),
                 helper.make_node('Reshape', ['r', 'shape'], ['red'])]
        maturity = 'zero'
        if ripe is not None:
            constants = [(k, v) for k, v in constants if k != 'zero']
            constants.append(('ripe', np.asarray([[[ripe]]], np.float32)))
            maturity = 'ripe'
        nodes.append(helper.make_node('Concat', ['box', 'green', maturity, 'red'], ['predictions'], axis=1))
        self.save(nodes, [numpy_helper.from_array(v, k) for k, v in constants], 7, 'best.onnx')

    def engine(self):
        (self.directory / 'classes.json').write_text(json.dumps(self.meta))
        with contextlib.redirect_stderr(io.StringIO()):
            return Engine(self.directory)

    def test_recovery_uses_actual_crop_pixels_and_preserves_raw_quality_score(self):
        engine = self.engine()
        self.assertTrue(engine.model_ready)
        result = engine.classify('F', 'C', self.jpeg)
        self.assertEqual(result['label'], 'REJECT')
        self.assertEqual(result['decision_reason'], 'CLASSIFIED')
        self.assertGreater(result['confidence'], .9)  # Not multiplied by .3 proposal confidence.
        del self.meta['localizer']
        self.assertEqual(self.engine().classify('F', 'C', self.jpeg)['label'], 'GREEN')

    def test_valid_closeup_is_retained(self):
        self.quality(box=(32, 32, 48, 48))
        self.assertEqual(self.engine().classify('F', 'C', self.jpeg)['label'], 'GREEN')

    def test_missing_native_target_can_recover_and_project_into_frame(self):
        from localization import localized_quality_candidates
        image = np.zeros((64, 64, 3), np.uint8)
        image[24:40, 24:40] = [0, 0, 255]
        content = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 100])[1].tobytes()
        engine = self.engine()
        self.assertEqual(engine.classify('F', 'C', content)['label'], 'REJECT')
        self.assertEqual(engine.classify('F', 'C', content)['decision_reason'], 'CLASSIFIED')
        candidates = localized_quality_candidates(content, engine.fruit_localizer, engine)
        np.testing.assert_allclose(candidates[0]['box'], [.375, .375, .625, .625], atol=1e-6)
        del self.meta['localizer']
        self.assertEqual(self.engine().classify('F', 'C', content)['decision_detail'], 'NO_TARGET')

    def test_absent_or_large_proposal_retains_native(self):
        for score, box in [(.1, (32, 32, 16, 16)), (.8, (32, 32, 64, 64))]:
            self.localizer(score, box)
            self.assertEqual(self.engine().classify('F', 'C', self.jpeg)['label'], 'GREEN')

    def test_crop_chooses_highest_without_reject_priority(self):
        # Half-red crop produces ~.5 REJECT; RIPE .65 wins without a .7 veto.
        self.localizer(box=(32, 32, 32, 16))
        self.quality(ripe=.65)
        result = self.engine().classify('F', 'C', self.jpeg)
        self.assertEqual(result['label'], 'RIPE')
        self.assertEqual(result['confidence'], .65)

    def test_invalid_auxiliary_configuration_never_reports_ready(self):
        changes = [{'file': '../fruit.onnx'}, {'file': 'missing.onnx'}, {'sha256': '0'*64},
                   {'max_targets': 99}, {'trigger_area': float('nan')},
                   {'imgsz': 128}, {'classes': ['orange', 'apple']}]
        for change in changes:
            original = self.config.copy()
            self.config.update(change)
            self.assertFalse(self.engine().model_ready, change)
            self.config.clear(); self.config.update(original)
        self.meta['decision_policy'] = 'threshold'
        self.assertFalse(self.engine().model_ready)

    def test_proposals_outside_frame_roi_cannot_change_result(self):
        self.meta['target_roi'] = [.6, .6, 1., 1.]
        result = self.engine().classify('F', 'C', self.jpeg)
        self.assertEqual(result['decision_detail'], 'NO_TARGET')

    def test_decoded_preprocessing_is_identical_for_non_square_jpeg(self):
        content = (ROOT / 'cloud-ai/reject.jpg').read_bytes()
        tensor, geometry = preprocess_detection_bytes(content, 320)
        image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        actual, actual_geometry = preprocess_detection_image(image, 320)
        np.testing.assert_array_equal(actual, tensor)
        self.assertEqual(actual_geometry, geometry)


if __name__ == '__main__':
    unittest.main()
