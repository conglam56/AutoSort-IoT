"""Private JSON-lines ONNX worker. Spring Boot owns HTTP, authentication and DB."""
import base64
import binascii
import io
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, UnidentifiedImageError
from inference import classification_probabilities, preprocess_image_bytes


class EngineError(RuntimeError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status


class Engine:
    def __init__(self, model_dir=None):
        self.model_ready = False
        self.ort_session = None
        self.input_name = None
        self.img_size = 224
        self.confidence_threshold = .70
        self.model_version = "yolo11n-cls-kumquat-v1"
        self.classes_list = ["GREEN", "REJECT", "RIPE"]
        self.idx_to_class = dict(enumerate(self.classes_list))
        self.task = 'classify'
        self.detection_policy = {}
        self.fruit_localizer = None
        directory = Path(model_dir or os.getenv("AI_MODEL_DIR", Path(__file__).with_name("model")))
        if not (directory / "best.onnx").is_file():
            return
        try:
            import onnxruntime as ort
            meta = json.loads((directory / "classes.json").read_text(encoding="utf-8"))
            classes = meta["classes"]
            if len(classes) != 3 or set(classes) != {"GREEN", "RIPE", "REJECT"}:
                raise ValueError("Classes must match the controller contract")
            self.classes_list = classes
            self.idx_to_class = meta.get("idx_to_class", {str(i): c for i, c in enumerate(classes)})
            if any(self.idx_to_class.get(str(i)) != c for i, c in enumerate(classes)):
                raise ValueError("Class order mismatch")
            self.confidence_threshold = float(meta.get("threshold", .70))
            self.img_size = int(meta.get("imgsz", 224))
            self.model_version = meta.get("model_version", self.model_version)
            self.task = meta.get('task', 'classify')
            if self.task not in {'classify', 'detect'}:
                raise ValueError('Unsupported model task')
            if not math.isfinite(self.confidence_threshold) or not 0 <= self.confidence_threshold <= 1 or not 16 <= self.img_size <= 2048:
                raise ValueError("Invalid model metadata")
            if not isinstance(self.model_version, str) or not self.model_version or self.model_version.lower().startswith("mock"):
                raise ValueError("Invalid model version")
            if self.task == 'detect':
                from detection import validate_detection_metadata
                self.detection_policy = validate_detection_metadata(meta, self.confidence_threshold)
            options = ort.SessionOptions()
            options.intra_op_num_threads = options.inter_op_num_threads = 1
            self.ort_session = ort.InferenceSession(str(directory / "best.onnx"), options, providers=["CPUExecutionProvider"])
            inputs = self.ort_session.get_inputs()
            if len(inputs) != 1 or inputs[0].type != "tensor(float)" or list(inputs[0].shape)[1:] != [3, self.img_size, self.img_size]:
                raise ValueError("Expected NCHW float32 image input")
            outputs = self.ort_session.get_outputs()
            if self.task == 'detect' and (len(outputs) != 1 or outputs[0].type != 'tensor(float)' or len(outputs[0].shape) != 3 or outputs[0].shape[:2] != [1, 7]):
                raise ValueError('Expected a three-class YOLO11 detection output')
            self.input_name = inputs[0].name
            if 'localizer' in meta:
                if self.task != 'detect' or self.detection_policy['decision_policy'] != 'highest_confidence':
                    raise ValueError('Fruit localization requires highest-confidence detection')
                from localization import FruitLocalizer
                self.fruit_localizer = FruitLocalizer(directory, meta['localizer'])
            self.model_ready = True
        except Exception as error:
            self.ort_session = None
            print(f"AI initialization failed ({type(error).__name__}); MOCK mode", file=sys.stderr, flush=True)

    def health(self):
        return {"mode": "onnx" if self.model_ready else "mock", "model_ready": self.model_ready,
                "classes": self.classes_list if self.model_ready else ["MOCK"],
                "model_version": self.model_version if self.model_ready else "mock-v0",
                "threshold": self.confidence_threshold if self.model_ready else 0.0,
                "task": self.task if self.model_ready else None,
                "decision_policy": self.detection_policy.get('decision_policy') if self.model_ready else None}

    def classify(self, fruit_id, camera_id, content):
        try:
            if not 0 < len(content) <= 1_000_000 or not content.startswith(b"\xff\xd8"):
                raise ValueError("Expected JPEG")
            with Image.open(io.BytesIO(content)) as image:
                if image.format != "JPEG" or image.width * image.height > 25_000_000:
                    raise ValueError("Image dimensions exceed limit")
                image.load()
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise EngineError(400, "Invalid JPEG data") from error
        result = {"fruit_id": fruit_id, "camera_id": camera_id, "image_bytes": len(content)}
        if not self.model_ready or self.ort_session is None:
            return {**result, "label": "MOCK", "raw_label": "MOCK", "confidence": 0.0,
                    "decision_reason": "MOCK_MODE", "model_version": "mock-v0", "inference_ms": 0.0,
                    "note": "AI model not ready on server; running in mock fallback mode"}
        started = time.perf_counter()
        try:
            if self.task == 'detect':
                from detection import preprocess_detection_bytes, detection_candidates, decide_detection
                tensor, geometry = preprocess_detection_bytes(content, self.img_size)
                output = self.ort_session.run(None, {self.input_name: tensor})[0]
                policy = self.detection_policy
                candidates = detection_candidates(output, self.classes_list, geometry,
                                                  policy['candidate_threshold'], policy['nms_iou'])
                if self.fruit_localizer is not None:
                    from localization import recover_full_frame_candidates
                    candidates, _ = recover_full_frame_candidates(content, self.fruit_localizer, self, candidates)
                decision = decide_detection(candidates, self.confidence_threshold, policy['roi'],
                                            policy['target_iou'], policy['class_margin'], policy['decision_policy'])
                return {**result, **decision, 'model_version': self.model_version,
                        'inference_ms': round((time.perf_counter() - started) * 1000, 2)}
            tensor = preprocess_image_bytes(content, self.img_size)
            probabilities = classification_probabilities(self.ort_session.run(None, {self.input_name: tensor})[0], len(self.classes_list))
            index = int(np.argmax(probabilities))
            confidence = float(probabilities[index])
            raw = self.idx_to_class.get(str(index))
            if raw not in {"GREEN", "RIPE", "REJECT"}:
                raise ValueError("Invalid model class")
            threshold = float(np.asarray(self.confidence_threshold, dtype=probabilities.dtype))
            low = confidence < threshold
            return {**result, "label": "REJECT" if low else raw, "raw_label": raw,
                    "confidence": round(confidence, 4), "decision_reason": "LOW_CONFIDENCE" if low else "CLASSIFIED",
                    "model_version": self.model_version, "inference_ms": round((time.perf_counter() - started) * 1000, 2)}
        except Exception as error:
            raise EngineError(500, "Inference failed") from error


def main():
    engine = Engine()
    for line in sys.stdin:
        try:
            if len(line) > 1_500_000:
                raise EngineError(413, "Image must be 1 MB or smaller")
            message = json.loads(line)
            if message.get("operation") == "health":
                result = engine.health()
            else:
                content = base64.b64decode(message["image"], validate=True)
                result = engine.classify(message["fruit_id"], message["camera_id"], content)
            output = {"ok": True, "result": result}
        except EngineError as error:
            output = {"ok": False, "status": error.status, "detail": str(error)}
        except (ValueError, KeyError, TypeError, binascii.Error):
            output = {"ok": False, "status": 400, "detail": "Invalid worker input"}
        except Exception:
            output = {"ok": False, "status": 500, "detail": "Inference worker failed"}
        print(json.dumps(output, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
