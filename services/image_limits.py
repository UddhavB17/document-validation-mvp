"""Cap rendered/OCR image size so Paddle does not hang on phone-scan megapixels."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from services.config import get_int


def max_image_side_px() -> int:
    return get_int("DMEF_MAX_IMAGE_SIDE_PX", 1600, minimum=800, maximum=4000)


def downscale_if_needed(image: np.ndarray, *, max_side: int | None = None) -> np.ndarray:
    """Return *image* resized so its longest side is at most *max_side*."""
    limit = max_side or max_image_side_px()
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= limit:
        return image

    scale = limit / float(longest)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)


def prepare_image_path_for_ocr(image_path: str | Path) -> str:
    """Ensure the on-disk image is within OCR size limits; rewrite if needed."""
    path = Path(image_path)
    image = cv2.imread(str(path))
    if image is None:
        return str(path)

    resized = downscale_if_needed(image)
    if resized.shape[:2] == image.shape[:2]:
        return str(path)

    cv2.imwrite(str(path), resized)
    return str(path)
