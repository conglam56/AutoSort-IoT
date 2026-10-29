"""Merge the three local one-class YOLO exports without overwriting sources.

Class IDs are GREEN=0, RIPE=1, REJECT=2. REJECT supersedes maturity only
for annotations describing the same object. Ambiguous images are quarantined.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import zipfile

import numpy as np
from PIL import Image, ImageOps
import yaml

CLASSES = ['GREEN', 'RIPE', 'REJECT']
SPLIT_PRIORITY = {'train': 0, 'val': 1, 'test': 2}
MATCH_IOU = .8
AMBIGUOUS_IOU = .3


class Groups:
    def __init__(self, size):
        self.parents = list(range(size))

    def find(self, i):
        while self.parents[i] != i:
            self.parents[i] = self.parents[self.parents[i]]
            i = self.parents[i]
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parents[max(a, b)] = min(a, b)


def box_iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = max(0, min(ax + aw / 2, bx + bw / 2) - max(ax - aw / 2, bx - bw / 2))
    h = max(0, min(ay + ah / 2, by + bh / 2) - max(ay - ah / 2, by - bh / 2))
    inter = w * h
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0


def parse_boxes(text):
    boxes = []
    for line in text.splitlines():
        values = [float(v) for v in line.split()]
        if len(values) != 5 or values[0] != 0 or not all(math.isfinite(v) for v in values):
            raise ValueError('Expected a one-class YOLO detection annotation')
        x, y, w, h = values[1:]
        if not all(0 <= v <= 1 for v in (x, y, w, h)) or min(w, h) <= 0:
            raise ValueError('Invalid normalized box')
        # Clip small source annotation overhangs to the actual image.
        left, top = max(0, x - w / 2), max(0, y - h / 2)
        right, bottom = min(1, x + w / 2), min(1, y + h / 2)
        if right <= left or bottom <= top:
            raise ValueError('Box is outside image')
        boxes.append([(left + right) / 2, (top + bottom) / 2, right - left, bottom - top])
    return boxes


def merge_boxes(annotations):
    """Resolve same-object overlap only; preserve separate fruit boxes."""
    if not annotations:
        return [], 'empty_annotations', 0
    groups = Groups(len(annotations))
    for i, a in enumerate(annotations):
        for j, b in enumerate(annotations[:i]):
            if box_iou(a['box'], b['box']) >= MATCH_IOU:
                groups.union(i, j)
    clusters = defaultdict(list)
    for i, box in enumerate(annotations):
        clusters[groups.find(i)].append(box)
    merged = []
    overrides = 0
    for cluster in clusters.values():
        # Reject chain-linked clusters that do not consistently describe one fruit.
        if any(box_iou(a['box'], b['box']) < MATCH_IOU for i, a in enumerate(cluster) for b in cluster[:i]):
            return [], 'ambiguous_box_cluster', 0
        labels = {a['class'] for a in cluster}
        if 2 in labels:
            label = 2
            overrides += bool(labels - {2})
        elif len(labels) == 1:
            label = next(iter(labels))
        else:
            return [], 'green_ripe_same_object_conflict', 0
        candidates = sorted((a for a in cluster if a['class'] == label), key=lambda a: a['box'])
        merged.append({'class': label, 'box': candidates[0]['box']})
    # A partial overlap between different labels is not sufficient to relabel.
    for i, a in enumerate(merged):
        for b in merged[:i]:
            if a['class'] != b['class'] and box_iou(a['box'], b['box']) >= AMBIGUOUS_IOU:
                return [], 'uncertain_cross_class_overlap', 0
    return sorted(merged, key=lambda a: (a['class'], a['box'])), None, overrides


def image_features(raw):
    with Image.open(io.BytesIO(raw)) as im:
        im.verify()
    with Image.open(io.BytesIO(raw)) as im:
        if im.width * im.height > 25_000_000:
            raise ValueError('Oversized source image')
        upright = ImageOps.exif_transpose(im)
        # Rotated annotations would require an explicit box transform.
        if upright.size != im.size or im.getexif().get(274, 1) not in (1, None):
            raise ValueError('Source EXIF orientation requires annotation review')
        rgb = np.asarray(im.convert('RGB').resize((32, 32)), dtype=np.float32)
        gray = np.asarray(im.convert('L').resize((32, 32)), dtype=np.float32)
        dims = list(im.size)
    n = np.arange(32, dtype=np.float64)
    k = np.arange(8, dtype=np.float64)[:, None]
    basis = np.cos((2 * n + 1) * k * math.pi / 64)
    block = basis @ gray @ basis.T
    bits = (block > np.median(block.flatten()[1:])).flatten()
    bits[0] = False
    phash = sum(int(v) << i for i, v in enumerate(bits))
    return phash, rgb, dims


def read_sources(sources):
    images = {}
    source_info = []
    for class_id, source in enumerate(sources):
        source = Path(source).resolve()
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > 50_000 or sum(e.file_size for e in entries) > 512 * 1024 ** 2:
                raise ValueError('Source ZIP exceeds expected limits')
            by_name = defaultdict(list)
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.filename:
                    raise ValueError('Unsafe ZIP path')
                by_name[entry.filename].append(entry)
            for name, versions in by_name.items():
                if len(versions) > 1 and len({hashlib.sha256(archive.read(e)).hexdigest() for e in versions}) != 1:
                    raise ValueError(f'Conflicting duplicate ZIP entry: {name}')
            metadata = yaml.safe_load(archive.read('data.yaml'))
            expected = CLASSES[class_id].lower() + ' fruit'
            if metadata.get('nc') != 1 or metadata.get('names') != [expected]:
                raise ValueError(f'Unexpected source classes for {source.name}')
            upstream = metadata.get('roboflow', {})
            if not isinstance(upstream, dict):
                raise ValueError('Invalid dataset attribution')
            attribution = {key: upstream[key] for key in ('workspace', 'project', 'version', 'license', 'url') if key in upstream}
            source_info.append({'file': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                'class': CLASSES[class_id], 'attribution': attribution})
            for name in sorted(by_name):
                path = PurePosixPath(name)
                if path.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
                    continue
                split_parts = [s for s in ('train', 'valid', 'test') if s in path.parts]
                if len(split_parts) != 1 or 'images' not in path.parts:
                    raise ValueError('Unexpected source image path')
                split = 'val' if split_parts[0] == 'valid' else split_parts[0]
                entry = by_name[name][0]
                if entry.file_size > 20_000_000:
                    raise ValueError('Oversized image archive entry')
                raw = archive.read(entry)
                digest = hashlib.sha256(raw).hexdigest()
                label_path = name.replace('/images/', '/labels/').rsplit('.', 1)[0] + '.txt'
                boxes = parse_boxes(archive.read(label_path).decode('utf-8-sig').strip())
                source_id = re.sub(r'(_jpg|_png)?\.rf\..*$', '', path.stem)
                if digest not in images:
                    phash, thumb, dims = image_features(raw)
                    images[digest] = {'sha256': digest, 'raw': raw, 'extension': path.suffix.lower(),
                                      'phash': phash, 'thumb': thumb, 'dimensions': dims,
                                      'sources': [], 'annotations': []}
                images[digest]['sources'].append({'dataset': CLASSES[class_id], 'file': name,
                                                 'split': split, 'source_id': source_id,
                                                 'box_count': len(boxes)})
                images[digest]['annotations'].extend({'class': class_id, 'box': b} for b in boxes)
    return sorted(images.values(), key=lambda i: i['sha256']), source_info


def prepare_dataset(sources, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Destination already exists; existing work preserved')
    images, provenance = read_sources(sources)
    groups = Groups(len(images))
    by_source = {}
    for i, image in enumerate(images):
        for source in image['sources']:
            key = source['source_id']
            if key in by_source:
                groups.union(i, by_source[key])
            else:
                by_source[key] = i
    near_pairs = []
    for i, image in enumerate(images):
        for j, other in enumerate(images[:i]):
            if image['dimensions'] != other['dimensions'] or (image['phash'] ^ other['phash']).bit_count() > 4:
                continue
            delta = image['thumb'] - other['thumb']
            if float(np.abs(delta).mean()) <= 4 and float(np.sqrt((delta ** 2).mean())) <= 8:
                groups.union(i, j)
                near_pairs.append([image['sha256'], other['sha256']])
    cluster_splits = {}
    cluster_ids = defaultdict(list)
    for i, image in enumerate(images):
        group = groups.find(i)
        cluster_ids[group].append(image['sha256'])
        proposed = min((s['split'] for s in image['sources']), key=SPLIT_PRIORITY.get)
        previous = cluster_splits.get(group, proposed)
        cluster_splits[group] = min((proposed, previous), key=SPLIT_PRIORITY.get)
    planned = []
    quarantine = []
    overrides = 0
    for i, image in enumerate(images):
        boxes, reason, count = merge_boxes(image['annotations'])
        group = groups.find(i)
        item = {'sha256': image['sha256'], 'group': min(cluster_ids[group]),
                'sources': image['sources'], 'dimensions': image['dimensions'],
                'split': cluster_splits[group], 'boxes': boxes}
        if reason:
            quarantine.append(item | {'reason': reason, 'original_annotations': image['annotations']})
        else:
            planned.append((image, item))
            overrides += count
    counts = {s: {'images': 0, 'boxes': {c: 0 for c in CLASSES}} for s in SPLIT_PRIORITY}
    for _, item in planned:
        counts[item['split']]['images'] += 1
        for box in item['boxes']:
            counts[item['split']]['boxes'][CLASSES[box['class']]] += 1
    if any(not all(info['boxes'].values()) for info in counts.values()):
        raise ValueError(f'Every split needs all three classes: {counts}')
    destination.mkdir(parents=True)
    for image, item in planned:
        rel = Path('images') / item['split'] / (image['sha256'] + image['extension'])
        label = Path('labels') / item['split'] / (image['sha256'] + '.txt')
        (destination / rel).parent.mkdir(parents=True, exist_ok=True)
        (destination / label).parent.mkdir(parents=True, exist_ok=True)
        (destination / rel).write_bytes(image['raw'])
        (destination / label).write_text(''.join(f"{b['class']} " + ' '.join(f'{v:.10f}' for v in b['box']) + '\n' for b in item['boxes']), encoding='utf-8')
        item['file'] = rel.as_posix()
    for item in quarantine:
        image = next(i for i in images if i['sha256'] == item['sha256'])
        rel = Path('review') / (item['sha256'] + image['extension'])
        (destination / rel).parent.mkdir(exist_ok=True)
        (destination / rel).write_bytes(image['raw'])
        item['file'] = rel.as_posix()
    config = {'path': str(destination), 'train': 'images/train', 'val': 'images/val', 'test': 'images/test',
              'names': dict(enumerate(CLASSES))}
    (destination / 'data.yaml').write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf-8')
    manifest = {'format_version': 1, 'classes': CLASSES, 'sources': provenance,
                'policy': {'same_object_iou': MATCH_IOU, 'ambiguous_overlap_iou': AMBIGUOUS_IOU,
                           'reject_priority': True, 'split_priority': list(SPLIT_PRIORITY),
                           'near_duplicates': 'pHash distance <=4, RGB MAE <=4, RGB RMSE <=8 at 32px; same dimensions'},
                'unique_source_images': len(images), 'near_duplicate_pairs': near_pairs,
                'reject_overridden_object_clusters': overrides, 'counts': counts,
                'images': [item for _, item in planned], 'quarantine': quarantine,
                'quarantine_reasons': dict(Counter(q['reason'] for q in quarantine)),
                'limitations': ['Labels derive from supplied annotations, not full manual visual relabeling.',
                                'Perceptual grouping does not guarantee independence of capture scenes.',
                                'Missing annotations on additional fruit may remain in supplied data.']}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    attribution = ['Unified three-class detection dataset', 'Derived from the three user-supplied Roboflow exports.',
                   'Source declarations (verify upstream rights before redistribution):']
    for source in provenance:
        attribution.append(json.dumps(source, ensure_ascii=False))
    (destination / 'ATTRIBUTION.txt').write_text('\n'.join(attribution) + '\n', encoding='utf-8')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--green', type=Path, required=True)
    p.add_argument('--ripe', type=Path, required=True)
    p.add_argument('--reject', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    a = p.parse_args()
    report = prepare_dataset([a.green, a.ripe, a.reject], a.destination)
    print(json.dumps({k: report[k] for k in ['unique_source_images', 'counts', 'reject_overridden_object_clusters', 'quarantine_reasons']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
