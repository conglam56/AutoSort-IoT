"""Detection image, output and single-fruit policy regression tests."""
import io
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cloud-ai'))
from detection import (decide_detection, detection_candidates, preprocess_detection_bytes,
                       validate_detection_metadata)


CLASSES = ['GREEN', 'RIPE', 'REJECT']


class DetectionTests(unittest.TestCase):
    def candidate(self, label, score, box=(.1, .1, .9, .9)):
        return {'label': label, 'confidence': score, 'box': list(box)}

    def test_letterbox_keeps_whole_image_and_rgb_order(self):
        content = io.BytesIO()
        Image.new('RGB', (200, 100), (255, 0, 0)).save(content, 'PNG')
        tensor, geometry = preprocess_detection_bytes(content.getvalue(), 320)
        self.assertEqual(tensor.shape, (1, 3, 320, 320))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertTrue(tensor.flags.c_contiguous)
        self.assertEqual(geometry['top'], 80)
        np.testing.assert_array_equal(tensor[0, :, 160, 160], [1, 0, 0])
        np.testing.assert_allclose(tensor[0, :, 0, 0], [114 / 255] * 3, atol=1e-7)

    def test_output_validation_and_class_aware_nms(self):
        geometry = {'width': 320, 'height': 320, 'ratio': 1, 'left': 0, 'top': 0}
        output = np.zeros((1, 7, 3), dtype=np.float32)
        output[0, :4, :] = np.array([[160, 160, 160], [160, 160, 160], [200, 200, 200], [200, 200, 200]])
        output[0, 4, :] = [.95, .9, 0]
        output[0, 6, 2] = .85
        candidates = detection_candidates(output, CLASSES, geometry)
        self.assertEqual([c['label'] for c in candidates], ['GREEN', 'REJECT'])
        result = decide_detection(candidates, .7)
        self.assertEqual(result['label'], 'REJECT')
        self.assertEqual(result['decision_detail'], 'REJECT_PRIORITY')
        # Independent detection class scores do not need to sum to one.
        for invalid in [np.zeros((1, 3)), np.full((1, 7, 1), np.nan), np.full((1, 7, 1), 2.)]:
            with self.assertRaises(ValueError):
                detection_candidates(invalid, CLASSES, geometry)

    def test_unletterboxes_to_original_image(self):
        output = np.array([[[160], [160], [160], [80], [.9], [0], [0]]], dtype=np.float32)
        geometry = {'width': 200, 'height': 100, 'ratio': 1.6, 'left': 0, 'top': 80}
        candidates = detection_candidates(output, CLASSES, geometry)
        np.testing.assert_allclose(candidates[0]['box'], [.25, .25, .75, .75], atol=1e-6)

    def test_reject_priority_does_not_depend_on_largest_confidence(self):
        result = decide_detection([self.candidate('GREEN', .99), self.candidate('REJECT', .8)], .7)
        self.assertEqual(result['label'], 'REJECT')
        self.assertEqual(result['confidence'], .8)

    def test_multiple_objects_and_missing_target_never_return_good_label(self):
        cases = [[], [self.candidate('GREEN', .99, (0, 0, .3, .3)), self.candidate('RIPE', .99, (.7, .7, 1, 1))]]
        for candidates in cases:
            result = decide_detection(candidates, .7)
            self.assertEqual(result['label'], 'REJECT')
            self.assertEqual(result['decision_reason'], 'LOW_CONFIDENCE')

    def test_roi_ignores_other_fruit_without_affecting_target(self):
        result = decide_detection([
            self.candidate('REJECT', .99, (.0, .0, .1, .1)),
            self.candidate('RIPE', .9, (.3, .3, .7, .7))], .7, roi=(.2, .2, .8, .8))
        self.assertEqual(result['label'], 'RIPE')

    def test_maturity_conflict_and_low_confidence_keep_existing_bridge_contract(self):
        candidates = [self.candidate('GREEN', .9), self.candidate('RIPE', .85)]
        result = decide_detection(candidates, .7)
        self.assertEqual(result['decision_detail'], 'MATURITY_CONFLICT')
        self.assertEqual(result['label'], 'REJECT')
        result = decide_detection([self.candidate('GREEN', .6999)], .7)
        self.assertEqual(result['decision_reason'], 'LOW_CONFIDENCE')
        self.assertEqual(result['label'], 'REJECT')
        result = decide_detection([self.candidate('GREEN', float(np.float32(.7)))], .7)
        self.assertEqual(result['label'], 'GREEN')

    def test_metadata_rejects_unsupported_format_and_bad_roi(self):
        base = {'output_format': 'yolo11_raw'}
        self.assertEqual(validate_detection_metadata(base, .7)['roi'], [0, 0, 1, 1])
        for override in [{'output_format': 'nms'}, {'target_roi': [1, 0, 0, 1]}, {'candidate_threshold': .9}, {'nms_iou': float('nan')}]:
            with self.assertRaises(ValueError):
                validate_detection_metadata(base | override, .7)


if __name__ == '__main__':
    unittest.main()
