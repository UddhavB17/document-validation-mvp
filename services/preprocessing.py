"""Image pre-processing for scanned loan-document pages.

Prepares PNG images (produced by pdf_processor.convert_page_to_image) before
they are passed to the OCR engine.

Public API
----------
check_readability(image_path)
    Measure Laplacian variance to detect blurry / unreadable images.

preprocess_image(image_path)
    Denoise a grayscale image and return a numpy array ready for OCR.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BLUR_THRESHOLD = 100.0  # Laplacian variance below this → image is blurry


# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------


class _ReadabilityResult(TypedDict):
    is_readable: bool
    blur_score: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_readability(image_path: str | Path) -> _ReadabilityResult:
    """Assess whether an image is sharp enough for reliable OCR.

    The Laplacian variance is a standard sharpness proxy: a low variance
    indicates a blurry (low-frequency) image that will produce poor OCR results.

    Parameters
    ----------
    image_path:
        Filesystem path to the PNG / JPEG image to evaluate.

    Returns
    -------
    dict
        ``is_readable`` – ``True`` when the image is sharp enough
        (``blur_score >= 100``), ``False`` otherwise.

        ``blur_score`` – Laplacian variance as a ``float``.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        # Image could not be loaded; treat as unreadable.
        return {"is_readable": False, "blur_score": 0.0}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variance: float = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    return {
        "is_readable": variance >= _BLUR_THRESHOLD,
        "blur_score": variance,
    }


def preprocess_image(image_path: str | Path) -> np.ndarray:
    """Load, grayscale, and denoise an image for OCR ingestion.

    Parameters
    ----------
    image_path:
        Filesystem path to the PNG / JPEG image.

    Returns
    -------
    numpy.ndarray
        Denoised single-channel (grayscale) image array.

    Raises
    ------
    FileNotFoundError
        If *image_path* does not exist or cannot be read by OpenCV.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not load image: {image_path}")

    from services.image_limits import downscale_if_needed

    image = downscale_if_needed(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Skip slow denoise on large loan-file pages; mobile OCR handles mild noise.
    if gray.shape[0] * gray.shape[1] <= 2_500_000:
        denoised: np.ndarray = cv2.fastNlMeansDenoising(gray, h=10)
    else:
        denoised = gray
    return denoised
