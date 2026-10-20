"""
Export trained YOLO Classification model to ONNX format and generate classes.json.

Usage:
    python training/export_onnx.py \
        --weights runs/autosort/yolo11-cls/weights/best.pt \
        --destination cloud-ai/model \
        --threshold 0.70
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="Export YOLO model to ONNX and create classes.json")
    parser.add_argument(
        "--weights",
        type=str,
        default="runs/autosort/yolo11-cls/weights/best.pt",
        help="Path to trained PyTorch weights (best.pt)",
    )
    parser.add_argument(
        "--destination",
        type=str,
        default="cloud-ai/model",
        help="Destination folder for exported best.onnx and classes.json",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Confidence threshold for cloud classification decision (default: 0.70)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=224,
        help="Model input image dimension (default: 224)",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=17,
        help="ONNX opset version (default: 17)",
    )
    parser.add_argument(
        "--model-version",
        type=str,
        default="yolo11n-cls-kumquat-v1",
        help="Model version string for API response",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    weights_path = Path(args.weights).resolve()
    dest_path = Path(args.destination).resolve()

    if not weights_path.exists():
        print(f"[ERROR] Weights file not found: {weights_path}")
        sys.exit(1)

    print("=" * 60)
    print(f"[*] Loading PyTorch weights from: {weights_path}")
    model = YOLO(str(weights_path))

    # Extract class dictionary
    names_dict = model.names
    # Convert keys to int if necessary
    int_names = {int(k): str(v) for k, v in names_dict.items()}
    num_classes = len(int_names)
    sorted_classes = [int_names[i] for i in range(num_classes)]
    class_to_idx = {name: i for i, name in enumerate(sorted_classes)}
    idx_to_class = {str(i): name for i, name in enumerate(sorted_classes)}

    print(f"[*] Detected {num_classes} classes: {sorted_classes}")

    # Export to ONNX
    print(f"[*] Exporting to ONNX (imgsz={args.imgsz}, opset={args.opset})...")
    export_result = model.export(
        format="onnx",
        imgsz=args.imgsz,
        opset=args.opset,
        dynamic=False,
    )

    exported_file = Path(export_result)
    if not exported_file.exists():
        # Fallback search if export_result is string representation
        candidate = weights_path.with_suffix(".onnx")
        if candidate.exists():
            exported_file = candidate
        else:
            print(f"[ERROR] Could not locate exported ONNX file at {export_result}")
            sys.exit(1)

    # Prepare destination directory
    dest_path.mkdir(parents=True, exist_ok=True)
    target_onnx = dest_path / "best.onnx"
    target_json = dest_path / "classes.json"

    # Copy ONNX to destination
    shutil.copy2(exported_file, target_onnx)
    onnx_size_mb = target_onnx.stat().st_size / (1024 * 1024)

    # Save classes.json
    metadata = {
        "model_version": args.model_version,
        "threshold": args.threshold,
        "imgsz": args.imgsz,
        "num_classes": num_classes,
        "classes": sorted_classes,
        "class_to_idx": class_to_idx,
        "idx_to_class": idx_to_class,
    }

    with open(target_json, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("[*] Export Complete!")
    print(f"[*] ONNX Model: {target_onnx} ({onnx_size_mb:.2f} MB)")
    print(f"[*] Classes Metadata: {target_json}")
    print("=" * 60)


if __name__ == "__main__":
    main()
