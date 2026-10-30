"""Export a separate COCO fruit-proposal graph with PyTorch/ONNX parity checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT / '.local/ai-training/settings-localizer-export'))
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
os.environ.setdefault('ULTRALYTICS_SAFE_LOAD', 'true')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--imgsz', type=int, default=320)
    parser.add_argument('--probe', type=Path, action='append', required=True)
    args = parser.parse_args()
    source, destination = args.weights.resolve(), args.destination.resolve()
    if not source.is_file() or destination.exists():
        raise ValueError('Provide existing weights and a new export directory')
    if not 32 <= args.imgsz <= 2048 or args.imgsz % 32:
        raise ValueError('Image size must be a multiple of 32 in [32,2048]')
    for probe in args.probe:
        if not probe.is_file():
            raise ValueError('Missing parity probe')
    import torch
    import numpy as np
    import onnx
    import onnxruntime as ort
    from ultralytics import YOLO, settings
    settings.update({key: False for key in ['sync', 'clearml', 'comet', 'dvc', 'mlflow',
                                           'raytune', 'tensorboard', 'wandb']})
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    sys.path.insert(0, str(ROOT / 'cloud-ai'))
    from detection import preprocess_detection_bytes
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    destination.mkdir(parents=True)
    weights = destination / 'localizer.pt'
    shutil.copy2(source, weights)
    model = YOLO(str(weights), task='detect')
    names = [model.names[i] for i in range(len(model.names))]
    if len(names) != 80 or not {'apple', 'orange'}.issubset(names):
        raise ValueError('Expected the pretrained COCO-80 detection checkpoint')
    graph = Path(model.export(format='onnx', imgsz=args.imgsz, batch=1, dynamic=False,
                              simplify=False, nms=False, opset=17, half=False, device='cpu'))
    onnx.checker.check_model(onnx.load(str(graph)))
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(graph), options, providers=['CPUExecutionProvider'])
    if (session.get_inputs()[0].shape != [1, 3, args.imgsz, args.imgsz]
            or session.get_outputs()[0].shape[:2] != [1, 84]):
        raise ValueError('Unexpected exported graph shape')
    net = model.model.float().eval().fuse(verbose=False)
    probes = []
    for path in args.probe:
        content = path.read_bytes()
        tensor, _ = preprocess_detection_bytes(content, args.imgsz)
        with torch.inference_mode():
            output = net(torch.from_numpy(tensor))
            reference = (output[0] if isinstance(output, (tuple, list)) else output).numpy()
        actual = session.run(None, {session.get_inputs()[0].name: tensor})[0]
        if not np.isfinite(actual).all() or not np.isfinite(reference).all():
            raise ValueError('Non-finite parity output')
        score = float(np.abs(actual[:, 4:] - reference[:, 4:]).max())
        box = float(np.abs(actual[:, :4] - reference[:, :4]).max())
        if score >= 1e-4 or box >= .02:
            raise ValueError('ONNX/PyTorch parity failed')
        probes.append({'file': path.name, 'sha256': hashlib.sha256(content).hexdigest(),
                       'score_max_abs_error': score, 'box_max_abs_error_pixels': box})
    config = {'file': graph.name, 'classes': names, 'accepted_classes': ['apple', 'orange'],
              'imgsz': args.imgsz, 'candidate_threshold': .25, 'nms_iou': .5,
              'padding': .05, 'max_targets': 4, 'trigger_area': .9, 'max_region_fraction': .5,
              'sha256': hashlib.sha256(graph.read_bytes()).hexdigest()}
    (destination / 'localizer.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    report = {'status': 'passed', 'source_checkpoint_sha256': source_hash,
              'source': 'Ultralytics pretrained YOLO11n COCO-80; proposals only, not quality labels',
              'documentation': 'https://docs.ultralytics.com/models/yolo11/', 'probes': probes}
    (destination / 'parity.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'destination': str(destination), 'probes': len(probes)}))


if __name__ == '__main__':
    main()
