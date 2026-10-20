"""
Train YOLO11 Classification on the prepared Kumquat dataset.

Usage:
    python training/train.py --dataset datasets/kumquat --device 0 --epochs 30 --batch 16
"""

import argparse
import json
from pathlib import Path
import sys

from dataset_checks import inspect_dataset


def parse_args():
    parser = argparse.ArgumentParser(description="Train YOLO11n Classification model")
    parser.add_argument(
        "--dataset",
        type=str,
        default="datasets/kumquat",
        help="Path to prepared dataset directory containing train/val(/test)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n-cls.pt",
        help="Pretrained YOLO model (e.g., yolo11n-cls.pt, yolov8n-cls.pt)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=30,
        help="Number of training epochs (default: 30)",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
        help="Batch size (default: 16)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=224,
        help="Image size (default: 224)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="0",
        help="Device to run on: '0', 'cpu', etc. Auto-falls back to cpu if GPU unavailable.",
    )
    parser.add_argument(
        "--project",
        type=str,
        default="runs/autosort",
        help="Project directory for outputs (default: runs/autosort)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="yolo11-cls",
        help="Experiment name (default: yolo11-cls)",
    )
    return parser.parse_args()


def resolve_device(requested_device: str) -> str:
    import torch

    if requested_device != "cpu":
        if not torch.cuda.is_available():
            print(f"[!] Warning: CUDA is not available on this machine. Falling back to device='cpu'.")
            return "cpu"
    return requested_device


def main():
    args = parse_args()

    # Resolve dataset path
    data_path = Path(args.dataset)
    if not data_path.is_absolute():
        data_path = Path.cwd() / data_path

    if not data_path.exists():
        # Check if in datasets/<arg>
        alt_path = Path.cwd() / "datasets" / args.dataset
        if alt_path.exists():
            data_path = alt_path
        else:
            print(f"[ERROR] Dataset directory not found: {data_path}")
            sys.exit(1)

    try:
        counts = inspect_dataset(data_path)
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}")
        sys.exit(1)
    for split, labels in counts.items():
        print(f"[*] {split}: {labels}")

    try:
        import torch
        from ultralytics import YOLO
    except ImportError as error:
        print(f"[ERROR] Training dependency missing: {error}")
        print("Install training/requirements.txt in the training environment, or use the supplied Colab notebook.")
        sys.exit(1)

    device = resolve_device(args.device)

    print("=" * 60)
    print(f"[*] Training YOLO Classification Model: {args.model}")
    print(f"[*] Dataset: {data_path}")
    print(f"[*] Epochs: {args.epochs} | Batch: {args.batch} | Image Size: {args.imgsz}")
    print(f"[*] Device: {device} (CUDA available: {torch.cuda.is_available()})")
    print(f"[*] Output Project: {args.project}/{args.name}")
    print("=" * 60)

    # Load model
    model = YOLO(args.model)

    # Train
    model.train(
        data=str(data_path),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=device,
        project=args.project,
        name=args.name,
        exist_ok=False,
    )

    save_dir = Path(model.trainer.save_dir) if hasattr(model, "trainer") and model.trainer else Path(args.project) / args.name
    best_weights = save_dir / "weights" / "best.pt"

    print("\n" + "=" * 60)
    print("[*] Training Completed!")
    if best_weights.exists():
        print(f"[*] Best weights saved at: {best_weights}")
    else:
        print(f"[ERROR] Training did not produce best.pt: {best_weights}")
        sys.exit(1)
    print("=" * 60)

    # Evaluate on test set if test directory exists
    test_dir = data_path / "test"
    top1 = None
    if test_dir.exists():
        print("\n[*] Evaluating best model on test set...")
        best_model = YOLO(str(best_weights))
        test_metrics = best_model.val(data=str(data_path), split="test")
        top1 = getattr(test_metrics, "top1", None)
        top5 = getattr(test_metrics, "top5", None)
        print(f"[*] Test Top-1 Accuracy: {top1}")
        if top5 is not None:
            print(f"[*] Test Top-5 Accuracy: {top5}")

    summary = {
        "save_dir": str(save_dir.resolve()),
        "best_weights": str(best_weights.resolve()),
        "dataset": str(data_path.resolve()),
        "counts": counts,
        "test_top1": float(top1) if top1 is not None else None,
    }
    summary_path = Path(args.project) / "latest_run.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[*] Run summary: {summary_path}")


if __name__ == "__main__":
    main()
