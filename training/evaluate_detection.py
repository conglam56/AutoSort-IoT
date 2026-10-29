"""Evaluate production ONNX decisions on a fixed prepared split, without tuning."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

from train_detection import verify_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--split', choices=['val', 'test'], default='test')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Evaluation output exists; existing results preserved')
    root = args.dataset.resolve()
    _, manifest = verify_dataset(root)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cloud-ai'))
    from worker import Engine
    engine = Engine(args.model_dir)
    if not engine.model_ready or engine.task != 'detect':
        raise ValueError('A verified detection ONNX model is required')
    rows = []
    matrix = defaultdict(Counter)
    reasons = Counter()
    classified = correct_classified = bad_accepted = good_rejected = 0
    scored = excluded = 0
    for item in manifest['images']:
        if item['split'] != args.split:
            continue
        path = root / item['file']
        if path.suffix.lower() not in {'.jpg', '.jpeg'}:
            raise ValueError('Production API evaluation requires JPEG source images')
        result = engine.classify(item['sha256'][:16], 'evaluation-only', path.read_bytes())
        expected = manifest['classes'][item['boxes'][0]['class']] if len(item['boxes']) == 1 else None
        rows.append({'file': item['file'], 'expected_single_fruit_label': expected,
                     'annotated_fruits': len(item['boxes']), 'result': result})
        if expected is None:
            excluded += 1
            continue
        scored += 1
        matrix[expected][result['label']] += 1
        reasons[result.get('decision_detail', result['decision_reason'])] += 1
        is_classified = result['decision_reason'] == 'CLASSIFIED'
        classified += is_classified
        correct_classified += is_classified and result['label'] == expected
        bad_accepted += expected == 'REJECT' and result['label'] in {'GREEN', 'RIPE'}
        good_rejected += expected in {'GREEN', 'RIPE'} and result['label'] == 'REJECT'
    smoke = []
    for path in sorted((Path(__file__).resolve().parents[1] / 'cloud-ai').glob('*.jpg')):
        smoke.append({'file': path.name, 'result': engine.classify('smoke-only', 'evaluation-only', path.read_bytes())})
    report = {'model': engine.health(), 'split': args.split, 'total_images': len(rows),
              'single_annotated_fruit_images': scored, 'excluded_multi_fruit_images': excluded,
              'final_label_confusion': {k: dict(v) for k, v in matrix.items()},
              'classified_decisions': classified, 'correct_classified_decisions': correct_classified,
              'reject_label_accepted_as_green_or_ripe': bad_accepted,
              'green_or_ripe_labels_sent_to_reject': good_rejected,
              'decision_details': dict(reasons), 'samples': smoke, 'images': rows,
              'limitations': ['Ground truth is derived from supplied annotations, not full manual visual review.',
                              'Single annotated fruit does not guarantee no unannotated fruit appears in the image.',
                              'Fallback REJECT is not evidence that the model detected a defect.',
                              'This fixed split was not used to tune threshold or ROI.',
                              'No physical hardware or station-phone validation was performed.']}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in {'images', 'samples'}}, indent=2))


if __name__ == '__main__':
    main()
