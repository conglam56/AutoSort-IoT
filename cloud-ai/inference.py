"""Lightweight YOLO classification input/output contract shared with parity checks.

Matches the standard Ultralytics square classification transform: RGB,
shortest-edge bilinear resize, center crop, float32 / 255, contiguous NCHW.
The exported classification head already includes softmax.
"""

import io

import numpy as np
from PIL import Image, ImageOps


def preprocess_image_bytes(content: bytes, target_size: int = 224) -> np.ndarray:
    """Preserve aspect ratio and use torchvision's resize/crop rounding rules."""
    if not isinstance(target_size, int) or target_size <= 0:
        raise ValueError("Image size must be a positive integer")

    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        if width <= height:
            resized = (target_size, int(target_size * height / width))
        else:
            resized = (int(target_size * width / height), target_size)
        if image.size != resized:
            image = image.resize(resized, Image.Resampling.BILINEAR)

        left = int(round((image.width - target_size) / 2.0))
        top = int(round((image.height - target_size) / 2.0))
        image = image.crop((left, top, left + target_size, top + target_size))
        pixels = np.asarray(image, dtype=np.float32) / np.float32(255.0)
        return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None, ...])


def classification_probabilities(output: np.ndarray, num_classes: int) -> np.ndarray:
    """Validate one exported YOLO probability vector without applying softmax again.

    Fail on incompatible logits, batch shapes, or class counts instead of
    silently producing a plausible but incorrect confidence or label.
    """
    values = np.asarray(output)
    if values.shape != (1, num_classes) or num_classes < 1:
        raise ValueError(f"Expected classification output (1, {num_classes}), got {values.shape}")
    if not np.issubdtype(values.dtype, np.floating) or not np.all(np.isfinite(values)):
        raise ValueError("Classification probabilities must be finite floating-point values")
    probabilities = values[0]
    if np.any(probabilities < 0) or np.any(probabilities > 1):
        raise ValueError("Expected probabilities in [0, 1], not logits")
    if not np.isclose(probabilities.sum(), 1.0, rtol=1e-5, atol=1e-4):
        raise ValueError("Classification probabilities must sum to 1")
    return probabilities
