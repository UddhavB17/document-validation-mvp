"""OCR engine for scanned loan-document pages.

Uses PaddleOCR for text recognition.  The model is initialised *once* at
module import time so that subsequent calls to :func:`run_ocr_on_page` share
the same warm model without reloading weights.

Public API
----------
run_ocr_on_page(image_path)
    Assess readability, preprocess, run OCR, and return a result dict.

Module-level
------------
ocr_model
    Singleton :class:`PaddleOCR` instance (or ``None`` when PaddleOCR is not
    installed in this environment).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

from services.preprocessing import check_readability, preprocess_image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level OCR model – initialised once, reused on every call
# ---------------------------------------------------------------------------

try:
    from paddleocr import PaddleOCR as _PaddleOCR

    ocr_model: _PaddleOCR | None = _PaddleOCR(
        use_textline_orientation=True,  # use_angle_cls renamed in PaddleOCR 3.x
        lang="en",
        show_log=False,
    )
except Exception as _paddle_exc:  # ImportError, RuntimeError, etc.
    logger.warning(
        "PaddleOCR could not be loaded (%s). "
        "OCR will be unavailable until PaddleOCR and PaddlePaddle are installed.",
        _paddle_exc,
    )
    ocr_model = None


# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------


class _OcrResult(TypedDict, total=False):
    is_readable: bool
    ocr_text: str
    confidence: float
    error: str  # only present when OCR raises


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_ocr_on_page(image_path: str | Path) -> _OcrResult:
    """Run OCR on a single scanned-page image.

    Steps
    -----
    1. Check readability via :func:`~services.preprocessing.check_readability`.
    2. If blurry / unreadable, return early with ``is_readable=False``.
    3. Preprocess the image (grayscale + denoising).
    4. Run PaddleOCR and aggregate text lines and confidence scores.
    5. Wrap everything in ``try/except`` – OCR failures return an error dict
       instead of raising.

    Parameters
    ----------
    image_path:
        Path to the PNG / JPEG image produced by the PDF processor.

    Returns
    -------
    dict
        ``is_readable`` – ``bool``.

        ``ocr_text`` – space-joined OCR output (empty string on failure).

        ``confidence`` – mean confidence score (0.0–1.0).

        ``error`` *(optional)* – exception message when OCR raises.
    """
    # ── 1. Readability gate ──────────────────────────────────────────────────
    readability = check_readability(image_path)
    if not readability["is_readable"]:
        return {
            "is_readable": False,
            "ocr_text": "",
            "confidence": 0.0,
        }

    # ── 2. Guard: model not available ────────────────────────────────────────
    if ocr_model is None:
        return {
            "is_readable": False,
            "ocr_text": "",
            "confidence": 0.0,
            "error": (
                "PaddleOCR model is not loaded. "
                "Install paddlepaddle and paddleocr to enable OCR."
            ),
        }

    # ── 3. Preprocess → OCR ──────────────────────────────────────────────────
    try:
        preprocessed = preprocess_image(image_path)
        result = ocr_model.ocr(preprocessed, cls=True)

        lines: list[str] = [line[1][0] for line in result[0]]
        text = " ".join(lines)

        scores: list[float] = [line[1][1] for line in result[0]]
        confidence = sum(scores) / len(scores) if scores else 0.0

        return {
            "is_readable": True,
            "ocr_text": text,
            "confidence": confidence,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("OCR failed for %s", image_path)
        return {
            "is_readable": False,
            "ocr_text": "",
            "confidence": 0.0,
            "error": str(exc),
        }
