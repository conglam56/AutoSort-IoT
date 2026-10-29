"""YOLO11 detection preprocessing, class-aware NMS and one-fruit decisions.

Uncertain or multiple targets use the existing LOW_CONFIDENCE -> REJECT
contract. decision_detail distinguishes these cases from a predicted defect.
"""
import math

import cv2
import numpy as np

cv2.setNumThreads(1)


def preprocess_detection_bytes(content, size):
    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or not isinstance(size, int) or size < 16:
        raise ValueError('Invalid detection image or size')
    height, width = image.shape[:2]
    ratio = min(size / height, size / width)
    scaled = (round(width * ratio), round(height * ratio))
    if (width, height) != scaled:
        image = cv2.resize(image, scaled, interpolation=cv2.INTER_LINEAR)
    dx, dy = (size - scaled[0]) / 2, (size - scaled[1]) / 2
    left, right = round(dx - .1), round(dx + .1)
    top, bottom = round(dy - .1), round(dy + .1)
    image = cv2.copyMakeBorder(image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    # OpenCV is BGR; the network input is contiguous RGB NCHW float32 / 255.
    tensor = np.ascontiguousarray(image[..., ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / np.float32(255)
    return tensor, {'width': width, 'height': height, 'ratio': ratio, 'left': left, 'top': top, 'size': size}


def pair_iou(box, boxes):
    boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)
    intersection = np.maximum(0, np.minimum(box[2:], boxes[:, 2:]) - np.maximum(box[:2], boxes[:, :2])).prod(axis=1)
    area = np.maximum(0, box[2:] - box[:2]).prod()
    areas = np.maximum(0, boxes[:, 2:] - boxes[:, :2]).prod(axis=1)
    return intersection / np.maximum(area + areas - intersection, np.finfo(np.float32).eps)


def detection_candidates(output, classes, geometry, candidate_threshold=.25, nms_iou=.7):
    raw = np.asarray(output)
    if raw.ndim != 3 or raw.shape[:2] != (1, 4 + len(classes)) or not 1 <= raw.shape[2] <= 100_000:
        raise ValueError('Expected YOLO11 raw detection output [1, 4+classes, anchors]')
    if not np.issubdtype(raw.dtype, np.floating) or not np.isfinite(raw).all():
        raise ValueError('Detection output must be finite floating point')
    rows = raw[0].T
    probabilities = rows[:, 4:]
    if np.any(probabilities < 0) or np.any(probabilities > 1):
        raise ValueError('Detection scores must be probabilities')
    indices = probabilities.argmax(axis=1)
    scores = probabilities[np.arange(len(rows)), indices]
    selected = (scores >= np.asarray(candidate_threshold, dtype=scores.dtype)) & (rows[:, 2] > 0) & (rows[:, 3] > 0)
    rows, scores, indices = rows[selected], scores[selected], indices[selected]
    if not len(rows):
        return []
    boxes = np.column_stack((rows[:, :2] - rows[:, 2:4] / 2, rows[:, :2] + rows[:, 2:4] / 2))
    order = np.argsort(-scores, kind='stable')[:1000]
    kept = []
    while len(order) and len(kept) < 100:
        current = int(order[0])
        kept.append(current)
        remaining = order[1:]
        suppress = (indices[remaining] == indices[current]) & (pair_iou(boxes[current], boxes[remaining]) > nms_iou)
        order = remaining[~suppress]
    result = []
    for index in kept:
        box = boxes[index].copy()
        box[[0, 2]] = (box[[0, 2]] - geometry['left']) / geometry['ratio'] / geometry['width']
        box[[1, 3]] = (box[[1, 3]] - geometry['top']) / geometry['ratio'] / geometry['height']
        box = np.clip(box, 0, 1)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        result.append({'label': classes[int(indices[index])], 'confidence': float(scores[index]),
                       'box': [float(v) for v in box]})
    return result


def decide_detection(candidates, threshold, roi=(0, 0, 1, 1), target_iou=.5, class_margin=.15):
    def uncertain(detail, raw='REJECT', confidence=0.0):
        return {'label': 'REJECT', 'raw_label': raw, 'confidence': round(confidence, 4),
                'decision_reason': 'LOW_CONFIDENCE', 'decision_detail': detail}
    targets = []
    for candidate in candidates:
        x1, y1, x2, y2 = candidate['box']
        if roi[0] <= (x1 + x2) / 2 <= roi[2] and roi[1] <= (y1 + y2) / 2 <= roi[3]:
            targets.append(candidate)
    if not targets:
        return uncertain('NO_TARGET')
    # Candidate boxes must all refer to one fruit. Never classify another fruit
    # merely because its confidence or box area is larger.
    reference = targets[0]
    if any(float(pair_iou(np.asarray(reference['box']), [c['box']])[0]) < target_iou for c in targets[1:]):
        return uncertain('MULTIPLE_OR_AMBIGUOUS_TARGETS')
    scores = {}
    for candidate in targets:
        scores[candidate['label']] = max(scores.get(candidate['label'], 0), candidate['confidence'])
    cutoff = float(np.asarray(threshold, dtype=np.float32))
    if scores.get('REJECT', 0) >= cutoff:
        return {'label': 'REJECT', 'raw_label': 'REJECT', 'confidence': round(scores['REJECT'], 4),
                'decision_reason': 'CLASSIFIED', 'decision_detail': 'REJECT_PRIORITY'}
    ordered = sorted(scores.items(), key=lambda p: (-p[1], p[0]))
    label, confidence = ordered[0]
    if confidence < cutoff:
        return uncertain('BELOW_THRESHOLD', label, confidence)
    maturity = sorted((s for c, s in scores.items() if c in {'GREEN', 'RIPE'}), reverse=True)
    if len(maturity) > 1 and maturity[0] - maturity[1] < class_margin:
        return uncertain('MATURITY_CONFLICT', label, confidence)
    return {'label': label, 'raw_label': label, 'confidence': round(confidence, 4),
            'decision_reason': 'CLASSIFIED', 'decision_detail': 'SINGLE_TARGET'}


def validate_detection_metadata(meta, threshold):
    candidate_threshold = float(meta.get('candidate_threshold', .25))
    nms_iou = float(meta.get('nms_iou', .7))
    target_iou = float(meta.get('target_iou', .5))
    class_margin = float(meta.get('class_margin', .15))
    roi = meta.get('target_roi', [0, 0, 1, 1])
    values = [candidate_threshold, nms_iou, target_iou, class_margin]
    if not all(math.isfinite(v) and 0 < v <= 1 for v in values) or candidate_threshold > threshold:
        raise ValueError('Invalid detection policy')
    if len(roi) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in roi) or roi[2] <= roi[0] or roi[3] <= roi[1]:
        raise ValueError('Invalid normalized target ROI')
    if meta.get('output_format') != 'yolo11_raw':
        raise ValueError('Unsupported detection export format')
    return {'candidate_threshold': candidate_threshold, 'nms_iou': nms_iou,
            'target_iou': target_iou, 'class_margin': class_margin, 'roi': roi}
