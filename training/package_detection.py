"""Package the verified unified detector dataset and credential-free tools."""
import argparse
import json
from pathlib import Path
import zipfile

from train_detection import verify_dataset

ROOT = Path(__file__).resolve().parents[1]
TOOLS = [
    'training/prepare_detection_dataset.py', 'training/train_detection.py',
    'training/export_detection.py', 'training/AutoSort_Detection_Train.ipynb',
    'training/evaluate_detection.py',
    'cloud-ai/worker.py', 'cloud-ai/inference.py', 'cloud-ai/detection.py',
    'cloud-ai/quatsample.jpg', 'cloud-ai/ripe.jpg', 'cloud-ai/reject.jpg',
    'docs/AI_DETECTION_TRAINING.md',
    'docs/AI_DETECTION_RESULTS.md',
]


def create_detection_package(dataset, output, root=ROOT):
    dataset, output, root = Path(dataset).resolve(), Path(output).resolve(), Path(root).resolve()
    config, manifest = verify_dataset(dataset)
    files = []
    for relative in TOOLS:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f'Missing or unsafe package source: {relative}')
        files.append((path, relative))
    dataset_names = {'manifest.json', 'ATTRIBUTION.txt'}
    for item in manifest['images']:
        dataset_names.add(item['file'])
        dataset_names.add((Path('labels') / item['split'] / (Path(item['file']).stem + '.txt')).as_posix())
    dataset_names.update(item['file'] for item in manifest['quarantine'])
    for relative in sorted(dataset_names):
        path = (dataset / relative).resolve()
        if not path.is_relative_to(dataset) or not path.is_file():
            raise ValueError(f'Missing or unsafe dataset file: {relative}')
        files.append((path, 'datasets/kumquat-detection/' + relative))
    import yaml
    config['path'] = '.'
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            archive.write(path, name)
        archive.writestr('datasets/kumquat-detection/data.yaml', yaml.safe_dump(config, sort_keys=False))
        archive.writestr('PACKAGE_README.txt', 'Use training/AutoSort_Detection_Train.ipynb in Colab, or run training/train_detection.py with --dataset datasets/kumquat-detection. The trainer resolves the portable dataset path. No API key or Roboflow download is required. Review quarantined images before adding them to training.\n')
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise ValueError('Package ZIP verification failed')
        names = archive.namelist()
        if any('/.env' in n or n.endswith('.pt') or '.local/' in n for n in names):
            raise ValueError('Unexpected private/artifact file in training package')
    return {'output': str(output), 'files': len(files) + 2, 'counts': manifest['counts']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create_detection_package(args.dataset, args.output), indent=2))


if __name__ == '__main__':
    main()
