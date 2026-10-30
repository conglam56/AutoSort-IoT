"""Business regression cases for the user's highest-score label policy."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cloud-ai'))
from detection import decide_detection, validate_detection_metadata


class HighestConfidenceTests(unittest.TestCase):
    def choose(self, candidates, **kwargs):
        return decide_detection(candidates, .7, decision_policy='highest_confidence', **kwargs)

    def candidate(self, label, confidence, box=(.1, .1, .9, .9)):
        return {'label': label, 'confidence': confidence, 'box': box}

    def test_all_labels_compete_without_seventy_percent_or_reject_priority(self):
        for label, score, other, other_score in [
            ('RIPE', .61, 'REJECT', .59),
            ('GREEN', .99, 'REJECT', .8),
            ('REJECT', .49, 'RIPE', .41),
        ]:
            with self.subTest(winner=label):
                result = self.choose([self.candidate(other, other_score), self.candidate(label, score)])
                self.assertEqual(result['label'], label)
                self.assertEqual(result['confidence'], score)
                self.assertEqual(result['decision_reason'], 'CLASSIFIED')

    def test_weaker_side_objects_do_not_veto_the_highest_target(self):
        result = self.choose([self.candidate('RIPE', .9183), self.candidate('REJECT', .64, (.85, .4, 1, 1))])
        self.assertEqual(result['label'], 'RIPE')

    def test_roi_still_limits_which_targets_can_be_chosen(self):
        result = self.choose([self.candidate('REJECT', .99, (0, 0, .1, .1)), self.candidate('GREEN', .4)], roi=(.2, .2, .8, .8))
        self.assertEqual(result['label'], 'GREEN')
        self.assertEqual(self.choose([])['decision_detail'], 'NO_TARGET')

    def test_equal_scores_have_stable_order_independent_replay(self):
        candidates = [self.candidate('RIPE', .6), self.candidate('GREEN', .6)]
        self.assertEqual(self.choose(candidates), self.choose(list(reversed(candidates))))

    def test_metadata_explicitly_selects_the_policy_and_retains_legacy_support(self):
        meta = {'output_format': 'yolo11_raw', 'decision_policy': 'highest_confidence'}
        self.assertEqual(validate_detection_metadata(meta, 0)['decision_policy'], 'highest_confidence')
        self.assertEqual(validate_detection_metadata({'output_format': 'yolo11_raw'}, .7)['decision_policy'], 'threshold')
        with self.assertRaises(ValueError):
            validate_detection_metadata(meta | {'decision_policy': 'typo'}, 0)
