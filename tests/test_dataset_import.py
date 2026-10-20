"""Conversion checks for public COCO data using small generated fixtures."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from import_roboflow import convert_dataset, crop_bounds, image_path_within
from dataset_checks import inspect_dataset
from package_colab import create_package


class DatasetImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.destination = self.root / "classification"
        for split_index, split in enumerate(("train", "valid", "test")):
            folder = self.source / split
            folder.mkdir(parents=True)
            data = {"images": [], "annotations": [], "categories": []}
            for category, name in enumerate(("unripe", "ripe", "rotten"), start=1):
                filename = f"sample-{category}.png"
                Image.new("RGB", (100, 100), (category * 50, split_index * 70, 30)).save(folder / filename)
                data["categories"].append({"id": category, "name": name})
                data["images"].append({"id": category, "file_name": filename, "width": 100, "height": 100})
                data["annotations"].append({"id": category, "image_id": category, "category_id": category, "bbox": [25, 25, 50, 50]})
            self.write_annotations(split, data)

    def read_annotations(self, split):
        return json.loads((self.source / split / "_annotations.coco.json").read_text())

    def write_annotations(self, split, data):
        (self.source / split / "_annotations.coco.json").write_text(json.dumps(data))

    def test_crops_map_labels_and_preserve_splits_and_attribution(self):
        manifest = convert_dataset(self.source, self.destination)
        self.assertEqual(len(manifest["images"]), 9)
        self.assertEqual(manifest["source_image_count"], 9)
        for split in ("train", "val", "test"):
            self.assertEqual(manifest["counts"][split], {"GREEN": 1, "REJECT": 1, "RIPE": 1})
        for item in manifest["images"]:
            with Image.open(self.destination / item["file"]) as image:
                self.assertEqual(image.size, (60, 60))
        self.assertIn("Jobbie", (self.destination / "ATTRIBUTION.txt").read_text())
        self.assertEqual(len(list(self.source.glob("*/*.png"))), 9)

    def test_existing_destination_is_never_overwritten(self):
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("existing work")
        with self.assertRaisesRegex(ValueError, "already exists"):
            convert_dataset(self.source, self.destination)
        self.assertEqual(marker.read_text(), "existing work")

    def test_duplicate_training_source_is_excluded_from_validation(self):
        shutil.copy2(self.source / "train" / "sample-1.png", self.source / "valid" / "duplicate.png")
        data = self.read_annotations("valid")
        data["images"].append({"id": 4, "file_name": "duplicate.png", "width": 100, "height": 100})
        data["annotations"].append({"id": 4, "image_id": 4, "category_id": 1, "bbox": [25, 25, 50, 50]})
        self.write_annotations("valid", data)
        manifest = convert_dataset(self.source, self.destination)
        self.assertEqual(manifest["skipped_duplicate_images"], {"val": 1})
        hashes_by_split = {}
        for item in manifest["images"]:
            split = item["file"].split("/")[0]
            hashes_by_split.setdefault(split, set()).add(item["source_hash"])
        self.assertFalse(hashes_by_split["train"] & hashes_by_split["val"])

    def test_unknown_class_fails_before_writing_output(self):
        data = self.read_annotations("train")
        data["categories"][0]["name"] = "orange"
        self.write_annotations("train", data)
        with self.assertRaisesRegex(ValueError, "Unsupported annotation class"):
            convert_dataset(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_missing_class_fails_before_writing_output(self):
        data = self.read_annotations("test")
        data["annotations"] = data["annotations"][:-1]
        self.write_annotations("test", data)
        with self.assertRaisesRegex(ValueError, "Empty classification groups"):
            convert_dataset(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_annotation_paths_cannot_escape_the_split(self):
        outside = self.root / "private.png"
        Image.new("RGB", (10, 10)).save(outside)
        with self.assertRaisesRegex(ValueError, "outside split directory"):
            image_path_within(self.source / "train", "../../private.png")

    def test_invalid_boxes_are_rejected(self):
        for box in ([0, 0, 0, 2], [40, 40, 3, 3], [float("nan"), 0, 1, 1]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                crop_bounds(box, 20, 20, 0.1)

    def test_tiny_annotation_is_skipped_without_affecting_other_classes(self):
        data = self.read_annotations("train")
        data["annotations"].append({"id": 4, "image_id": 1, "category_id": 1, "bbox": [0, 0, 3, 3]})
        self.write_annotations("train", data)
        manifest = convert_dataset(self.source, self.destination)
        self.assertEqual(manifest["skipped_small_crops"], {"train": 1})
        self.assertEqual(len(manifest["images"]), 9)

    def test_training_validation_rejects_an_empty_class(self):
        convert_dataset(self.source, self.destination)
        for path in (self.destination / "val" / "GREEN").iterdir():
            path.unlink()
        with self.assertRaisesRegex(ValueError, "No images"):
            inspect_dataset(self.destination)

    def test_training_validation_rejects_a_corrupt_image(self):
        convert_dataset(self.source, self.destination)
        (self.destination / "train" / "GREEN" / "broken.jpg").write_bytes(b"not an image")
        with self.assertRaisesRegex(ValueError, "Unreadable image"):
            inspect_dataset(self.destination)

    def test_package_preserves_paths_and_excludes_unrelated_files(self):
        convert_dataset(self.source, self.destination)
        (self.destination / ".env").write_text("DO_NOT_PACKAGE=fixture")
        output = self.root / "training.zip"
        counts, total = create_package(self.destination, output)
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), total)
            self.assertIsNone(archive.testzip())
            self.assertIn("datasets/kumquat/dataset_manifest.json", names)
            self.assertIn("datasets/kumquat/ATTRIBUTION.txt", names)
            self.assertIn("training/AutoSort_Train.ipynb", names)
            self.assertIn("cloud-ai/inference.py", names)
            self.assertIn("cloud-ai/ripe.jpg", names)
            self.assertNotIn("datasets/kumquat/.env", names)
            self.assertEqual(sum(name.endswith(".jpg") and name.startswith("datasets/") for name in names), 9)
        self.assertEqual(counts["train"]["GREEN"], 1)
        with self.assertRaises(FileExistsError):
            create_package(self.destination, output)

    def test_notebook_code_cells_are_valid_python(self):
        notebook = json.loads((ROOT / "training" / "AutoSort_Train.ipynb").read_text(encoding="utf-8"))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "AutoSort_Train.ipynb", "exec")


if __name__ == "__main__":
    unittest.main()
