"""Compare production preprocessing and ONNX probabilities with Ultralytics.

With no image arguments, check every JPEG/PNG in cloud-ai/. Multiple files can
also be supplied with --image. A failed check returns a nonzero exit status.
"""

import argparse
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud-ai"))
from inference import classification_probabilities, preprocess_image_bytes

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=Path("runs/autosort/yolo11-cls/weights/best.pt"))
    parser.add_argument("--onnx", type=Path, default=Path("cloud-ai/model/best.onnx"))
    parser.add_argument("--classes", type=Path, default=Path("cloud-ai/model/classes.json"))
    parser.add_argument("--image", type=Path, nargs="+", help="One or more sample images")
    parser.add_argument("--image-dir", type=Path, help="Directory of sample images (default: cloud-ai)")
    parser.add_argument("--atol", type=float, default=1e-3, help="Maximum absolute probability difference")
    return parser.parse_args()


def find_images(args):
    paths = list(args.image or [])
    if args.image_dir is not None or not paths:
        directory = args.image_dir if args.image_dir is not None else ROOT / "cloud-ai"
        if not directory.is_dir():
            raise ValueError(f"Image directory not found: {directory}")
        paths.extend(sorted(p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file()))
    return list(dict.fromkeys(p.resolve() for p in paths))


def check_image(pt_model, session, image_path, classes, imgsz, atol):
    content = image_path.read_bytes()
    production_input = preprocess_image_bytes(content, target_size=imgsz)
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

    # A PIL source uses the same decoder as the API, avoiding JPEG decoder
    # differences between OpenCV and Pillow. Let Ultralytics run its own transforms.
    result = pt_model.predict(image, imgsz=imgsz, device="cpu", verbose=False)[0]
    pt_probs = classification_probabilities(
        result.probs.data.cpu().numpy()[None, :], len(classes)
    )
    bgr_image = np.ascontiguousarray(np.asarray(image)[:, :, ::-1])
    reference_input = pt_model.predictor.preprocess([bgr_image]).cpu().numpy()
    if reference_input.shape != production_input.shape:
        raise ValueError(f"Preprocessing shape mismatch for {image_path.name}")
    input_diff = float(np.max(np.abs(reference_input - production_input)))

    output = session.run(None, {session.get_inputs()[0].name: production_input})[0]
    onnx_probs = classification_probabilities(output, len(classes))
    max_diff = float(np.max(np.abs(pt_probs - onnx_probs)))
    pt_top1, onnx_top1 = int(np.argmax(pt_probs)), int(np.argmax(onnx_probs))
    passed = input_diff <= 1e-6 and max_diff <= atol and pt_top1 == onnx_top1

    print(f"\n[{image_path.name}] {'PASS' if passed else 'FAIL'}")
    print(f"  Input tensor max difference: {input_diff:.6e}")
    for name, pt_probability, onnx_probability in zip(classes, pt_probs, onnx_probs):
        print(f"  {name:<12} PyTorch={pt_probability:.6f} ONNX={onnx_probability:.6f}")
    print(f"  Top-1: PyTorch={classes[pt_top1]}, ONNX={classes[onnx_top1]}")
    print(f"  Max probability difference: {max_diff:.6e} (limit {atol:g})")
    return passed


def main():
    args = parse_args()
    if not np.isfinite(args.atol) or args.atol < 0:
        print("[ERROR] --atol must be finite and nonnegative")
        return 1

    # Check prerequisites before importing the optional training dependencies.
    missing = [p for p in (args.weights, args.onnx, args.classes) if not p.is_file()]
    if missing:
        for path in missing:
            print(f"[ERROR] Required file not found: {path}")
        print("Train and export the kumquat model before running real PyTorch/ONNX parity.")
        return 1

    try:
        images = find_images(args)
        if not images:
            raise ValueError("No sample images found")
        for path in images:
            if not path.is_file():
                raise ValueError(f"Sample image not found: {path}")
        with args.classes.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        classes = metadata["classes"]
        imgsz = metadata.get("imgsz", 224)
        expected_mapping = {str(i): name for i, name in enumerate(classes)}
        if metadata.get("idx_to_class", expected_mapping) != expected_mapping:
            raise ValueError("classes and idx_to_class disagree")

        import onnxruntime as ort
        from ultralytics import YOLO

        pt_model = YOLO(str(args.weights))
        if pt_model.task != "classify":
            raise ValueError("Weights must be a classification model")
        pt_classes = [pt_model.names[i] for i in range(len(pt_model.names))]
        if classes != pt_classes:
            raise ValueError(f"Metadata class order {classes} differs from PyTorch {pt_classes}")
        session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])

        results = []
        for image_path in images:
            results.append(check_image(pt_model, session, image_path, classes, imgsz, args.atol))
        passed = sum(results)
        print(f"\nParity: {passed}/{len(results)} images passed")
        return 0 if all(results) else 1
    except (ImportError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"[ERROR] {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
