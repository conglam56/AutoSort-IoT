"""Train one unified YOLO11 detector and evaluate its untouched test split."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def verify_dataset(root):
    import yaml
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('classes') != ['GREEN', 'RIPE', 'REJECT']:
        raise ValueError('Expected GREEN=0, RIPE=1, REJECT=2')
    seen = {}
    group_splits = {}
    for item in manifest['images']:
        path = (root / item['file']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Invalid image manifest path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Source image changed after preparation')
        if item['sha256'] in seen or (item['group'] in group_splits and group_splits[item['group']] != item['split']):
            raise ValueError('Image or near-duplicate group leaks across splits')
        seen[item['sha256']] = item['split']
        group_splits[item['group']] = item['split']
        label_path = root / 'labels' / item['split'] / (path.stem + '.txt')
        lines = label_path.read_text(encoding='utf-8').splitlines()
        expected = ['%d ' % b['class'] + ' '.join(f'{v:.10f}' for v in b['box']) for b in item['boxes']]
        if lines != expected:
            raise ValueError('Labels changed after preparation; rebuild the manifest')
    config = yaml.safe_load((root / 'data.yaml').read_text())
    if config.get('names') != {0: 'GREEN', 1: 'RIPE', 2: 'REJECT'}:
        raise ValueError('Unexpected class IDs')
    config['path'] = str(root)
    return config, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--project', type=Path, default=Path('runs/autosort-detection'))
    parser.add_argument('--name', default='unified-v1')
    parser.add_argument('--model', default='yolo11n.pt')
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--imgsz', type=int, default=320)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--freeze', type=int, default=10)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--patience', type=int, default=8)
    parser.add_argument('--resume', action='store_true', help='Resume this run from its unstripped last.pt')
    parser.add_argument('--lr0', type=float, default=.001)
    parser.add_argument('--class-weight-power', type=float, default=0,
                        help='Ultralytics cls_pw inverse-frequency loss weights (0 disables)')
    args = parser.parse_args()
    if not 0 <= args.class_weight_power <= 1 or not 0 < args.lr0 <= 1:
        parser.error('class-weight-power must be in [0,1]; lr0 must be in (0,1]')
    root = args.dataset.resolve()
    project = args.project.resolve()
    run = project / args.name
    if run.exists() and not args.resume:
        raise ValueError('Training output already exists; choose a new run name')
    if args.resume and (not (run/'weights/last.pt').is_file() or (run/'handoff.json').exists()):
        raise ValueError('Resume requires an interrupted run with last.pt and no completed handoff')
    os.environ.setdefault('YOLO_CONFIG_DIR', str(project / '.settings'))
    os.environ['YOLO_AUTOINSTALL'] = 'false'
    os.environ['ULTRALYTICS_SAFE_LOAD'] = 'true'
    os.environ['OMP_NUM_THREADS'] = str(args.threads)
    os.environ['MKL_NUM_THREADS'] = str(args.threads)
    import torch
    import yaml
    from ultralytics import YOLO, settings
    if args.class_weight_power:
        from ultralytics.cfg import DEFAULT_CFG_DICT
        if 'cls_pw' not in DEFAULT_CFG_DICT:
            raise RuntimeError('Class weighting requires a compatible Ultralytics version; tested with 8.4.191. Install training/requirements.txt.')
    settings.update({key: False for key in ['sync', 'clearml', 'comet', 'dvc', 'mlflow', 'raytune', 'tensorboard', 'wandb']})
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    config, manifest = verify_dataset(root)
    manifest_sha256 = hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    input_record = project/(args.name+'-input.json')
    previous_elapsed = 0
    if args.resume:
        if not input_record.is_file() or json.loads(input_record.read_text(encoding='utf-8'))['dataset_manifest_sha256'] != manifest_sha256:
            raise ValueError('Resume needs the original matching dataset fingerprint')
        previous = project/(args.name+'-progress.json')
        if previous.is_file():
            previous_elapsed = json.loads(previous.read_text(encoding='utf-8')).get('elapsed_seconds', 0)
    project.mkdir(parents=True, exist_ok=True)
    config_file = project / (args.name + '-dataset.yaml')
    config_file.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    model = YOLO(str(run/'weights/last.pt') if args.resume else args.model, task='detect')
    if args.resume and (model.ckpt.get('optimizer') is None or model.ckpt.get('epoch',-1)<0):
        raise ValueError('Checkpoint has no resumable optimizer/epoch state; use it for a new fine-tuning run instead')
    if not args.resume:
        input_record.write_text(json.dumps({'dataset_manifest_sha256':manifest_sha256,'args':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}},indent=2),encoding='utf-8')
    progress_file = project / (args.name + '-progress.json')
    began = time.time()

    def set_threads(trainer):
        torch.set_num_threads(args.threads)

    def progress(trainer):
        # Final validation can emit this callback after the epoch counter advances.
        state = {'epoch': min(trainer.epoch + 1, trainer.epochs), 'planned_epochs': trainer.epochs,
                 'elapsed_seconds': previous_elapsed + time.time() - began, 'metrics': trainer.metrics,
                 'run': str(trainer.save_dir), 'status': 'training'}
        progress_file.write_text(json.dumps(state, indent=2, default=float), encoding='utf-8')
        print('AUTOSORT_PROGRESS ' + json.dumps(state, default=float), flush=True)

    model.add_callback('on_train_start', set_threads)
    model.add_callback('on_fit_epoch_end', progress)
    extra = {'cls_pw': args.class_weight_power} if args.class_weight_power else {}
    model.train(data=str(config_file), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, workers=0, project=str(project), name=args.name,
                exist_ok=False, seed=42, deterministic=True, amp=False, cache=False,
                optimizer='AdamW', lr0=args.lr0, lrf=.1, cos_lr=True,
                freeze=args.freeze, patience=args.patience,
                hsv_h=.01, hsv_s=.2, hsv_v=.2, mosaic=.3, close_mosaic=5,
                plots=True, save=True, verbose=False, resume=args.resume, **extra)
    actual = Path(model.trainer.save_dir)
    best = actual / 'weights/best.pt'
    if not best.is_file():
        raise RuntimeError('Training did not produce best.pt')
    best_model = YOLO(str(best), task='detect')
    test = best_model.val(data=str(config_file), split='test', imgsz=args.imgsz,
                          batch=args.batch, device=args.device, workers=0,
                          project=str(project), name=args.name + '-test', plots=True,
                          verbose=False, save_json=True)
    report = {'run': str(actual), 'weights': str(best), 'dataset_manifest_sha256': hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
              'counts': manifest['counts'], 'class_names': best_model.names,
              'args': {k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()},
              'test': {k: float(v) for k,v in test.results_dict.items()},
              'test_per_class': test.summary(), 'test_speed_ms': test.speed,
              'elapsed_seconds': previous_elapsed + time.time()-began,
              'resumed': args.resume,
              'limitations': manifest['limitations'] + ['Local test metrics do not establish phone-camera or station performance.']}
    (actual/'handoff.json').write_text(json.dumps(report,indent=2,default=float),encoding='utf-8')
    progress_file.write_text(json.dumps({'status':'complete', 'report':str(actual/'handoff.json'), 'elapsed_seconds':previous_elapsed+time.time()-began}),encoding='utf-8')
    print('AUTOSORT_COMPLETE ' + json.dumps(report,default=float),flush=True)


if __name__ == '__main__':
    main()
