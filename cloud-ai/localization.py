"""Optional fruit localization before the existing three-class quality detector."""
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np

from detection import detection_candidates, pair_iou, preprocess_detection_image


class FruitLocalizer:
    def __init__(self, directory, metadata):
        import onnxruntime as ort

        if not isinstance(metadata, dict):
            raise ValueError('Invalid localizer metadata')
        directory = Path(directory).resolve()
        filename = metadata.get('file')
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError('Localizer must be a file inside the model directory')
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError('Missing or unsafe localizer model')
        if metadata.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != metadata['sha256']:
            raise ValueError('Localizer checksum mismatch')
        self.classes = metadata.get('classes')
        if (not isinstance(self.classes, list) or not 1 <= len(self.classes) <= 1000
                or any(not isinstance(n, str) or not n for n in self.classes)
                or len(set(self.classes)) != len(self.classes)):
            raise ValueError('Invalid localizer class names')
        accepted = metadata.get('accepted_classes')
        if not isinstance(accepted, list) or not accepted or any(n not in self.classes for n in accepted):
            raise ValueError('Invalid accepted fruit classes')
        self.accepted = set(accepted)
        self.size = metadata.get('imgsz')
        self.max_targets = metadata.get('max_targets', 4)
        if type(self.size) is not int or not 32 <= self.size <= 2048 or self.size % 32:
            raise ValueError('Invalid localizer image size')
        if type(self.max_targets) is not int or not 1 <= self.max_targets <= 8:
            raise ValueError('Invalid localizer target limit')
        self.threshold = float(metadata.get('candidate_threshold', .25))
        self.nms_iou = float(metadata.get('nms_iou', .5))
        self.padding = float(metadata.get('padding', .05))
        self.trigger_area = float(metadata.get('trigger_area', .9))
        self.max_region_fraction = float(metadata.get('max_region_fraction', .5))
        if not all(math.isfinite(v) and 0 < v <= 1 for v in (self.threshold, self.nms_iou)):
            raise ValueError('Invalid localizer detection policy')
        if not math.isfinite(self.padding) or not 0 <= self.padding <= .25:
            raise ValueError('Invalid localizer crop padding')
        if not math.isfinite(self.trigger_area) or not .5 <= self.trigger_area <= 1:
            raise ValueError('Invalid whole-frame recovery boundary')
        if not math.isfinite(self.max_region_fraction) or not 0 < self.max_region_fraction < 1:
            raise ValueError('Invalid localization scale ratio')
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (len(inputs) != 1 or inputs[0].type != 'tensor(float)'
                or inputs[0].shape != [1, 3, self.size, self.size]):
            raise ValueError('Unexpected localizer input')
        if (len(outputs) != 1 or outputs[0].type != 'tensor(float)'
                or len(outputs[0].shape) != 3 or outputs[0].shape[:2] != [1, 4 + len(self.classes)]):
            raise ValueError('Unexpected localizer output')
        self.input_name = inputs[0].name

    def locate(self, content, roi):
        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
        tensor, geometry = preprocess_detection_image(image, self.size)
        output = self.session.run(None, {self.input_name: tensor})[0]
        candidates = detection_candidates(output, self.classes, geometry, self.threshold, self.nms_iou)
        targets = []
        for candidate in sorted(candidates, key=lambda c: (-c['confidence'], c['label'], tuple(c['box']))):
            x1, y1, x2, y2 = candidate['box']
            if candidate['label'] not in self.accepted or not (roi[0] <= (x1+x2)/2 <= roi[2] and roi[1] <= (y1+y2)/2 <= roi[3]):
                continue
            # Apple/orange are both proposals for one fruit, not quality labels.
            if any(float(pair_iou(np.asarray(candidate['box']), [other['box']])[0]) > self.nms_iou for other in targets):
                continue
            targets.append(candidate)
            if len(targets) == self.max_targets:
                break
        return image, targets


def localized_quality_candidates(content, localizer, quality_engine, image=None, targets=None):
    """Project quality detections back to the original frame; keep raw scores."""
    policy = quality_engine.detection_policy
    if image is None or targets is None:
        image, targets = localizer.locate(content, policy['roi'])
    height, width = image.shape[:2]
    result = []
    for target in targets:
        x1, y1, x2, y2 = target['box']
        dx, dy = (x2-x1)*localizer.padding, (y2-y1)*localizer.padding
        left, top = max(0, math.floor((x1-dx)*width)), max(0, math.floor((y1-dy)*height))
        right, bottom = min(width, math.ceil((x2+dx)*width)), min(height, math.ceil((y2+dy)*height))
        if right-left < 2 or bottom-top < 2:
            continue
        tensor, geometry = preprocess_detection_image(image[top:bottom, left:right], quality_engine.img_size)
        output = quality_engine.ort_session.run(None, {quality_engine.input_name: tensor})[0]
        candidates = detection_candidates(output, quality_engine.classes_list, geometry,
                                          policy['candidate_threshold'], policy['nms_iou'])
        for candidate in candidates:
            a, b, c, d = candidate['box']
            result.append({**candidate, 'box': [(left+a*(right-left))/width, (top+b*(bottom-top))/height,
                                                (left+c*(right-left))/width, (top+d*(bottom-top))/height]})
    return result


def recover_full_frame_candidates(content, localizer, quality_engine, native_candidates):
    """Recover suspicious whole-frame boxes, retaining normal close-up behavior.

    The independent localizer must find substantially smaller fruit regions.
    Its apple/orange labels never become quality labels or quality scores.
    """
    roi = quality_engine.detection_policy['roi']
    eligible = [c for c in native_candidates if roi[0] <= (c['box'][0]+c['box'][2])/2 <= roi[2]
                and roi[1] <= (c['box'][1]+c['box'][3])/2 <= roi[3]]
    best = min(eligible, key=lambda c: (-c['confidence'], c['label'], tuple(c['box']))) if eligible else None
    area = lambda c: (c['box'][2]-c['box'][0])*(c['box'][3]-c['box'][1])
    if best and area(best) < localizer.trigger_area:
        return native_candidates, False
    image, targets = localizer.locate(content, roi)
    if best:
        targets = [c for c in targets if area(c) <= area(best)*localizer.max_region_fraction]
    if not targets:
        return native_candidates, False
    return localized_quality_candidates(content, localizer, quality_engine, image, targets), True
