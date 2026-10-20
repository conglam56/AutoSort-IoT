"""Convert a local Roboflow COCO export to YOLO classification folders.

Crop each annotated fruit and preserve the source train/valid/test assignments.
The original download is never changed. This script does not download data or
read credentials. Expected labels: unripe, ripe, rotten.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image

CLASS_MAP = {"unripe": "GREEN", "ripe": "RIPE", "rotten": "REJECT"}
CLASSES = sorted(CLASS_MAP.values())
SOURCE_URL = "https://universe.roboflow.com/jobbie/calamansi-ripeness-cvxus"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"


def image_path_within(folder, filename):
    path = (folder / filename).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError(f"Missing image or path outside split directory: {filename}")
    return path


def crop_bounds(box, width, height, padding):
    if len(box) != 4 or not all(math.isfinite(value) for value in box):
        raise ValueError(f"Invalid COCO bbox: {box}")
    x, y, box_width, box_height = box
    if box_width <= 0 or box_height <= 0:
        raise ValueError(f"Empty COCO bbox: {box}")
    left = max(0, math.floor(x - box_width * padding))
    top = max(0, math.floor(y - box_height * padding))
    right = min(width, math.ceil(x + box_width * (1 + padding)))
    bottom = min(height, math.ceil(y + box_height * (1 + padding)))
    if right <= left or bottom <= top:
        raise ValueError(f"COCO bbox outside image: {box}")
    return left, top, right, bottom


def convert_dataset(source, destination, padding=0.10, source_url=SOURCE_URL, min_size=32):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError(f"Destination already exists; preserved: {destination}")
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Source and destination must be separate directories")
    if not math.isfinite(padding) or not 0 <= padding <= 1:
        raise ValueError("Padding must be between 0 and 1")
    if not isinstance(min_size, int) or min_size < 1:
        raise ValueError("Minimum crop size must be a positive integer")

    planned = []
    source_images = {}
    skipped_duplicates = Counter()
    skipped_small = Counter()
    counts = {split: Counter({label: 0 for label in CLASSES}) for split in ("train", "val", "test")}
    # Prefer training copies when the export repeats a source across splits,
    # removing those copies from evaluation to avoid exact-image leakage.
    for input_split, output_split in (("train", "train"), ("valid", "val"), ("test", "test")):
        folder = source / input_split
        if input_split == "valid" and not folder.is_dir():
            folder = source / "val"
        annotation_file = folder / "_annotations.coco.json"
        if not annotation_file.is_file():
            raise ValueError(f"COCO annotations not found: {annotation_file}")
        data = json.loads(annotation_file.read_text(encoding="utf-8"))
        categories = {entry["id"]: entry["name"].strip().lower() for entry in data["categories"]}
        annotations = {}
        for annotation in data["annotations"]:
            name = categories[annotation["category_id"]]
            if name not in CLASS_MAP:
                raise ValueError(f"Unsupported annotation class: {name}")
            if annotation.get("iscrowd", 0):
                raise ValueError("Crowd annotations cannot be used as individual fruit crops")
            annotations.setdefault(annotation["image_id"], []).append(annotation)

        image_ids = {entry["id"] for entry in data["images"]}
        if set(annotations) - image_ids:
            raise ValueError(f"Annotation refers to an unknown image in {input_split}")
        for image_info in data["images"]:
            boxes = annotations.get(image_info["id"], [])
            if not boxes:
                continue
            path = image_path_within(folder, image_info["file_name"])
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                if image.size != (image_info["width"], image_info["height"]):
                    raise ValueError(f"Image dimensions disagree with COCO annotations: {path}")
                fingerprint = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
            if fingerprint in source_images:
                skipped_duplicates[output_split] += 1
                continue
            source_images[fingerprint] = output_split
            for annotation in boxes:
                label = CLASS_MAP[categories[annotation["category_id"]]]
                bounds = crop_bounds(annotation["bbox"], *image.size, padding)
                if min(bounds[2] - bounds[0], bounds[3] - bounds[1]) < min_size:
                    skipped_small[output_split] += 1
                    continue
                # Numeric sequence prevents filename collisions or unsafe source names.
                filename = f"fruit_{len(planned):06d}.jpg"
                planned.append({
                    "source": path,
                    "source_image": image_info["file_name"],
                    "source_hash": fingerprint,
                    "annotation_id": annotation["id"],
                    "split": output_split,
                    "label": label,
                    "bounds": bounds,
                    "filename": filename,
                })
                counts[output_split][label] += 1

    empty = [f"{split}/{label}" for split, labels in counts.items() for label, count in labels.items() if count == 0]
    if empty:
        raise ValueError(f"Empty classification groups after validation: {', '.join(empty)}")

    # All annotations and source images are validated before creating output.
    destination.mkdir(parents=True, exist_ok=False)
    for split in counts:
        for label in CLASSES:
            (destination / split / label).mkdir(parents=True)
    manifest_items = []
    for item in planned:
        relative_path = Path(item["split"]) / item["label"] / item["filename"]
        with Image.open(item["source"]) as image:
            image.convert("RGB").crop(item["bounds"]).save(destination / relative_path, quality=95)
        manifest_items.append({
            "file": relative_path.as_posix(),
            "source_image": item["source_image"],
            "source_hash": item["source_hash"],
            "annotation_id": item["annotation_id"],
            "crop_box": list(item["bounds"]),
        })
    manifest = {
        "source_url": source_url,
        "author": "Jobbie",
        "license": "CC BY 4.0",
        "license_url": LICENSE_URL,
        "changes": "COCO bounding-box crops with 10% padding by default; labels mapped to GREEN/RIPE/REJECT",
        "padding": padding,
        "minimum_crop_size": min_size,
        "class_mapping": CLASS_MAP,
        "counts": {split: dict(labels) for split, labels in counts.items()},
        "source_image_count": len(source_images),
        "skipped_duplicate_images": dict(skipped_duplicates),
        "skipped_small_crops": dict(skipped_small),
        "limitations": [
            "Calamansi reference data; validate on the target kumquat variety and camera before deployment.",
            "Exact source-image duplicates removed; physical-fruit identity and near-duplicates are not available.",
            "Original source splits preserved; all crops from a source image stay together.",
        ],
        "images": manifest_items,
    }
    (destination / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    attribution = (
        "Calamansi-ripeness dataset by Jobbie (2025)\n"
        f"Source: {source_url}\n"
        f"License: CC BY 4.0 - {LICENSE_URL}\n"
        "Changes: bounding-box crops, padding, and class-name mapping.\n"
        "This is reference data, not a guarantee of field accuracy.\n"
    )
    (destination / "ATTRIBUTION.txt").write_text(attribution, encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True, help="Extracted COCO export root")
    parser.add_argument("--dest", type=Path, default=Path("datasets/kumquat"))
    parser.add_argument("--padding", type=float, default=0.10)
    parser.add_argument("--min-size", type=int, default=32, help="Skip crops with either dimension below this size")
    args = parser.parse_args()
    try:
        manifest = convert_dataset(args.src, args.dest, args.padding, min_size=args.min_size)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"[ERROR] {error}")
        return 1
    for split, counts in manifest["counts"].items():
        print(f"{split}: {counts}")
    print(f"Skipped small crops: {manifest['skipped_small_crops']}")
    print(f"[OK] Classification data ready: {args.dest.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
