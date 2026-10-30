"""Check class remapping, REJECT precedence, and split isolation."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
from prepare_detection_dataset import merge_boxes, parse_boxes, prepare_dataset
from package_detection import create_detection_package


class DetectionDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = []
        self.entries = []
        for cls, label in enumerate(['green', 'ripe', 'reject']):
            entries = {'data.yaml': f"nc: 1\nnames: ['{label} fruit']\n".encode()}
            for split_id, split in enumerate(['train', 'valid', 'test']):
                for number in range(2):
                    buf = io.BytesIO()
                    Image.new('RGB', (64, 64), (20 + cls * 75, 20 + split_id * 75, 20 + number * 70)).save(buf, format='PNG')
                    name = f'{cls}-{split}-{number}'
                    entries[f'{split}/images/{name}.png'] = buf.getvalue()
                    entries[f'{split}/labels/{name}.txt'] = b'0 0.5 0.5 0.7 0.7\n'
            self.entries.append(entries)
            self.sources.append(self.root / f'{label}.zip')

    def build(self):
        for path, entries in zip(self.sources, self.entries):
            with zipfile.ZipFile(path, 'w') as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
        return prepare_dataset(self.sources, self.root / 'output')

    def add_copy(self, source_class, name, dest_class, dest_name, label=None):
        self.entries[dest_class][dest_name] = self.entries[source_class][name]
        label_path = dest_name.replace('/images/', '/labels/').replace('.png', '.txt')
        self.entries[dest_class][label_path] = label or b'0 0.5 0.5 0.7 0.7\n'

    def test_remaps_all_classes_and_preserves_sources(self):
        result = self.build()
        self.assertEqual(len(result['images']), 18)
        for info in result['counts'].values():
            self.assertEqual(info['boxes'], {'GREEN': 2, 'RIPE': 2, 'REJECT': 2})
        self.assertTrue(all(path.exists() for path in self.sources))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            prepare_dataset(self.sources, self.root / 'output')

    def test_exact_image_across_splits_is_train_only(self):
        self.add_copy(0, 'train/images/0-train-0.png', 0, 'test/images/copied.png')
        result = self.build()
        shared = next(i for i in result['images'] if len(i['sources']) == 2)
        self.assertEqual(shared['split'], 'train')
        self.assertEqual(len(result['images']), 18)

    def test_reject_overrides_same_object_and_preserves_other_objects(self):
        self.add_copy(0, 'train/images/0-train-0.png', 2, 'train/images/reject-copy.png')
        result = self.build()
        shared = next(i for i in result['images'] if len(i['sources']) == 2)
        self.assertEqual([b['class'] for b in shared['boxes']], [2])
        self.assertEqual(result['reject_overridden_object_clusters'], 1)
        a = {'class': 0, 'box': [.2, .5, .2, .2]}
        b = {'class': 2, 'box': [.8, .5, .2, .2]}
        boxes, reason, _ = merge_boxes([a, b])
        self.assertIsNone(reason)
        self.assertEqual(len(boxes), 2)

    def test_green_ripe_same_object_is_quarantined(self):
        self.add_copy(0, 'train/images/0-train-0.png', 1, 'train/images/ripe-copy.png')
        result = self.build()
        self.assertEqual(result['quarantine_reasons']['green_ripe_same_object_conflict'], 1)

    def test_uncertain_overlap_is_not_silently_relabelled(self):
        boxes, reason, _ = merge_boxes([
            {'class': 0, 'box': [.4, .5, .5, .5]},
            {'class': 2, 'box': [.6, .5, .5, .5]},
        ])
        self.assertEqual(reason, 'uncertain_cross_class_overlap')
        self.assertEqual(boxes, [])

    def test_empty_annotations_are_quarantined(self):
        self.entries[0]['train/labels/0-train-0.txt'] = b''
        result = self.build()
        self.assertEqual(result['quarantine_reasons']['empty_annotations'], 1)

    def test_rejects_invalid_boxes_and_unsafe_archive_paths(self):
        for line in ['1 .5 .5 .2 .2', '0 .5 .5 0 .2', '0 nan .5 .2 .2']:
            with self.assertRaises(ValueError):
                parse_boxes(line)
        self.entries[0]['../escape.jpg'] = b'invalid'
        with self.assertRaisesRegex(ValueError, 'Unsafe ZIP path'):
            self.build()
        self.assertFalse((self.root / 'output').exists())

    def test_package_is_portable_and_excludes_private_files(self):
        self.build()
        folder = self.root / 'output'
        (folder / '.env').write_text('PRIVATE_VALUE=not-for-package')
        (folder / 'review_changes.json').write_text('{"review": "fixture"}')
        (folder / 'supplement_review.json').write_text('{"supplement": "fixture"}')
        output = self.root / 'training.zip'
        create_detection_package(folder, output)
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertNotIn('datasets/kumquat-detection/.env', names)
            self.assertIn('datasets/kumquat-detection/review_changes.json', names)
            self.assertIn('datasets/kumquat-detection/supplement_review.json', names)
            self.assertIn('datasets/kumquat-detection/labels/test', '\n'.join(names))
            notebook = json.loads(archive.read('training/AutoSort_Detection_Train.ipynb'))
            for cell in notebook['cells']:
                if cell['cell_type'] == 'code':
                    compile(''.join(cell['source']), 'AutoSort_Detection_Train.ipynb', 'exec')
        with self.assertRaises(FileExistsError):
            create_detection_package(folder, output)

    def test_attribution_does_not_copy_unexpected_credentials(self):
        self.entries[0]['data.yaml'] += b'roboflow:\n  workspace: public-source\n  api_key: PRIVATE_VALUE\n'
        result = self.build()
        self.assertEqual(result['sources'][0]['attribution'], {'workspace': 'public-source'})
        self.assertNotIn('PRIVATE_VALUE', (self.root / 'output/ATTRIBUTION.txt').read_text())


if __name__ == '__main__':
    unittest.main()
