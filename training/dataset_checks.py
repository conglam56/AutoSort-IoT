"""Validate classification folders before starting a training run."""

from pathlib import Path

from PIL import Image

CLASSES = ("GREEN", "REJECT", "RIPE")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def inspect_dataset(root):
    root = Path(root)
    splits = ["train", "val"] + (["test"] if (root / "test").exists() else [])
    counts = {}
    for split in splits:
        folder = root / split
        if not folder.is_dir():
            raise ValueError(f"Missing split directory: {folder}")
        labels = {path.name for path in folder.iterdir() if path.is_dir() and not path.name.startswith(".")}
        if labels != set(CLASSES):
            raise ValueError(f"{split}: expected classes {CLASSES}, found {sorted(labels)}")
        counts[split] = {}
        for label in CLASSES:
            images = sorted(path for path in (folder / label).iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
            if not images:
                raise ValueError(f"No images in {folder / label}; add data before training")
            for path in images:
                try:
                    with Image.open(path) as image:
                        image.verify()
                except (OSError, ValueError) as error:
                    raise ValueError(f"Unreadable image: {path}") from error
            counts[split][label] = len(images)
    return counts
