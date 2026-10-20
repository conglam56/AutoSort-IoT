"""Create a training ZIP with stable paths and a limited, credential-free file list."""

import argparse
from pathlib import Path
import sys
import zipfile

from dataset_checks import IMAGE_EXTENSIONS, inspect_dataset

ROOT = Path(__file__).resolve().parents[1]


def create_package(dataset, output, root=ROOT):
    dataset, output, root = Path(dataset).resolve(), Path(output).resolve(), Path(root).resolve()
    counts = inspect_dataset(dataset)
    sources = [(path, path.relative_to(root).as_posix()) for path in sorted((root / "training").glob("*.py"))]
    for name in ("requirements.txt", "AutoSort_Train.ipynb"):
        path = root / "training" / name
        if not path.is_file():
            raise ValueError(f"Required training file missing: {path}")
        sources.append((path, f"training/{name}"))
    for name in ("inference.py", "quatsample.jpg", "ripe.jpg", "reject.jpg"):
        path = root / "cloud-ai" / name
        if not path.is_file():
            raise ValueError(f"Required parity sample or helper missing: {path}")
        sources.append((path, f"cloud-ai/{name}"))
    for path in sorted(dataset.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(dataset)
        is_image = len(relative.parts) == 3 and relative.parts[0] in counts and path.suffix.lower() in IMAGE_EXTENSIONS
        if is_image or relative.as_posix() in ("dataset_manifest.json", "ATTRIBUTION.txt"):
            if not path.resolve().is_relative_to(dataset):
                raise ValueError(f"Dataset symlink points outside dataset: {path}")
            sources.append((path, (Path("datasets/kumquat") / relative).as_posix()))
    # Exclusive creation preserves a previously generated package.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, archive_name in sources:
            archive.write(path, archive_name)
    with zipfile.ZipFile(output) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f"ZIP verification failed: {bad_file}")
    return counts, len(sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/kumquat"))
    parser.add_argument("--output", type=Path, default=Path("autosort-training.zip"))
    args = parser.parse_args()
    try:
        counts, total = create_package(args.dataset, args.output)
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}")
        return 1
    print(f"[OK] {args.output.resolve()} ({total} files)")
    print(f"Dataset: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
