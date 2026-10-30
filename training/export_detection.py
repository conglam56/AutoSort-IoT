"""Export a unified detector and verify real PyTorch/ONNX input and output parity."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--imgsz', type=int, default=320)
    parser.add_argument('--threshold', type=float, default=0.0, help='Legacy decision threshold; unused by highest_confidence')
    parser.add_argument('--decision-policy', choices=['threshold', 'highest_confidence'], default='highest_confidence')
    parser.add_argument('--model-version', default='autosort-yolo11n-detect-v1-policy3')
    args = parser.parse_args()
    if args.destination.exists():
        raise ValueError('Export destination exists; existing artifacts preserved')
    os.environ['YOLO_AUTOINSTALL'] = 'false'
    os.environ['ULTRALYTICS_SAFE_LOAD'] = 'true'
    import cv2
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from ultralytics import YOLO, settings
    from ultralytics.data.augment import LetterBox
    settings.update({key: False for key in ['sync', 'clearml', 'comet', 'dvc', 'mlflow', 'raytune', 'tensorboard', 'wandb']})
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cloud-ai'))
    from detection import preprocess_detection_bytes, detection_candidates, decide_detection, validate_detection_metadata
    from worker import Engine

    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    model = YOLO(str(args.weights.resolve()), task='detect')
    names = [model.names[i] for i in range(len(model.names))]
    if names != ['GREEN', 'RIPE', 'REJECT'] or model.task != 'detect':
        raise ValueError('Expected one three-class detector with GREEN=0, RIPE=1, REJECT=2')
    meta = {'task': 'detect', 'output_format': 'yolo11_raw', 'classes': names,
            'idx_to_class': {str(i): name for i, name in enumerate(names)},
            'class_to_idx': {name: i for i, name in enumerate(names)},
            'num_classes': 3, 'imgsz': args.imgsz, 'threshold': args.threshold, 'decision_policy': args.decision_policy,
            'model_version': args.model_version, 'candidate_threshold': .25,
            'nms_iou': .7, 'target_iou': .5, 'class_margin': .15,
            'target_roi': [0, 0, 1, 1], 'deployment_status': 'candidate_pending_review'}
    policy = validate_detection_metadata(meta, args.threshold)
    exported = Path(model.export(format='onnx', imgsz=args.imgsz, batch=1, dynamic=False,
                                 simplify=False, nms=False, opset=17, half=False, device='cpu'))
    graph = onnx.load(str(exported))
    onnx.checker.check_model(graph)
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(exported), options, providers=['CPUExecutionProvider'])
    if session.get_inputs()[0].shape != [1, 3, args.imgsz, args.imgsz] or session.get_outputs()[0].shape[:2] != [1, 7]:
        raise ValueError('Unexpected exported model shape')
    manifest = json.loads((args.dataset / 'manifest.json').read_text(encoding='utf-8'))
    selected = []
    # Validation probes are chosen without consulting test metrics or outcomes.
    for class_id in range(3):
        candidates = [i for i in manifest['images'] if i['split'] == 'val' and any(b['class'] == class_id for b in i['boxes'])]
        selected += [args.dataset / i['file'] for i in candidates[:4]]
    selected += sorted((Path(__file__).resolve().parents[1] / 'cloud-ai').glob('*.jpg'))
    selected = list(dict.fromkeys(p.resolve() for p in selected))
    net = model.model.float().eval().fuse(verbose=False)
    details = []
    for path in selected:
        content = path.read_bytes()
        tensor, geometry = preprocess_detection_bytes(content, args.imgsz)
        source = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        reference_pixels = LetterBox(new_shape=(args.imgsz, args.imgsz), auto=False, stride=32)(image=source)
        reference_input = np.ascontiguousarray(reference_pixels[..., ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / np.float32(255)
        input_error = float(np.abs(tensor - reference_input).max())
        if input_error > 1e-6:
            raise ValueError(f'Preprocessing mismatch: {path.name}')
        with torch.inference_mode():
            result = net(torch.from_numpy(tensor))
            reference = (result[0] if isinstance(result, (tuple, list)) else result).cpu().numpy()
        begin = time.perf_counter()
        actual = session.run(None, {session.get_inputs()[0].name: tensor})[0]
        elapsed_ms = (time.perf_counter() - begin) * 1000
        if actual.shape != reference.shape:
            raise ValueError('PT/ONNX shape mismatch')
        probability_error = float(np.abs(actual[:, 4:] - reference[:, 4:]).max())
        box_error = float(np.abs(actual[:, :4] - reference[:, :4]).max())
        if probability_error > 1e-4 or box_error > .02:
            raise ValueError(f'Raw output mismatch: {path.name}')
        decisions = []
        for raw in [reference, actual]:
            candidates = detection_candidates(raw, names, geometry, policy['candidate_threshold'], policy['nms_iou'])
            decisions.append(decide_detection(candidates, args.threshold, policy['roi'], policy['target_iou'], policy['class_margin'], policy['decision_policy']))
        if any(decisions[0][k] != decisions[1][k] for k in ['label', 'raw_label', 'decision_reason', 'decision_detail']):
            raise ValueError(f'PT/ONNX decision mismatch: {path.name}')
        details.append({'image': str(path), 'input_max_abs_error': input_error,
                        'score_max_abs_error': probability_error, 'box_max_abs_error_pixels': box_error,
                        'onnx_ms_cpu_single_thread': elapsed_ms, 'decision': decisions[1]})
    args.destination.mkdir(parents=True)
    shutil.copy2(exported, args.destination / 'best.onnx')
    (args.destination / 'classes.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    engine = Engine(args.destination)
    if not engine.model_ready or engine.task != 'detect':
        raise ValueError('Export did not initialize the production worker')
    for item, path in zip(details, selected):
        if path.suffix.lower() in {'.jpg', '.jpeg'}:
            result = engine.classify('parity-fruit', 'parity-camera', path.read_bytes())
            if result['label'] != item['decision']['label'] or result['decision_reason'] != item['decision']['decision_reason']:
                raise ValueError('Worker decision disagrees with parity check')
    report = {'status': 'passed', 'images': details, 'versions': {'torch': torch.__version__, 'onnx': onnx.__version__, 'onnxruntime': ort.__version__},
              'limitations': ['Parity verifies implementation consistency, not classification quality or hardware behavior.',
                              'Threshold and ROI require station-camera validation before physical operation.']}
    (args.destination / 'parity.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'images': len(details), 'destination': str(args.destination.resolve()),
                      'max_score_error': max(i['score_max_abs_error'] for i in details),
                      'max_box_error_pixels': max(i['box_max_abs_error_pixels'] for i in details)}), flush=True)


if __name__ == '__main__':
    main()
