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
import os
from pathlib import Path
from typing import Any, TypedDict

import cv2
import numpy as np

from services.preprocessing import check_readability, preprocess_image

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PADDLE_CACHE_DIR = Path(os.getenv("PADDLE_PDX_CACHE_HOME", _PROJECT_ROOT / "data/paddlex_cache"))


def _configure_paddle_runtime() -> None:
    """Apply Paddle flags before the native runtime is imported."""
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(PADDLE_CACHE_DIR))
    # oneDNN/MKLDNN triggers PIR runtime errors on many CPU installs (incl. Py 3.11).
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


_configure_paddle_runtime()


def _create_paddle_ocr() -> Any:
    """Create a PaddleOCR instance with CPU-safe defaults."""
    from paddleocr import PaddleOCR as _PaddleOCR

    base_kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "lang": "en",
    }
    try:
        return _PaddleOCR(**base_kwargs, enable_mkldnn=False)
    except TypeError:
        # Older paddleocr builds do not expose enable_mkldnn.
        return _PaddleOCR(**base_kwargs)


# ---------------------------------------------------------------------------
# Module-level OCR model – initialised once, reused on every call
# ---------------------------------------------------------------------------

try:
    ocr_model: Any | None = _create_paddle_ocr()
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
    is_blurry: bool
    ocr_text: str
    confidence: float
    blur_score: float
    error: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_ocr_on_page(image_path: str | Path) -> _OcrResult:
    """Run OCR on a single scanned-page image.

    Steps
    -----
    1. Check readability via :func:`~services.preprocessing.check_readability`.
    2. If blurry / unreadable, return early with ``is_readable=False``.
    3. Run PaddleOCR on the rendered page image.
    4. Aggregate text lines and confidence scores.
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
    readability = check_readability(image_path)
    is_blurry = not readability["is_readable"]
    if is_blurry:
        return {
            "is_readable": False,
            "is_blurry": True,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": readability["blur_score"],
        }

    if ocr_model is None:
        return {
            "is_readable": False,
            "is_blurry": is_blurry,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": readability["blur_score"],
            "error": (
                "PaddleOCR model is not loaded. "
                "Install paddlepaddle and paddleocr to enable OCR."
            ),
        }

    try:
        result = _run_paddle_ocr(ocr_model, image_path)
        text, confidence = _extract_ocr_text_and_confidence(result)

        return {
            "is_readable": bool(text.strip()),
            "is_blurry": is_blurry,
            "ocr_text": text,
            "confidence": confidence,
            "blur_score": readability["blur_score"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("OCR failed for %s", image_path)
        return {
            "is_readable": False,
            "is_blurry": is_blurry,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": readability["blur_score"],
            "error": str(exc),
        }


def _run_paddle_ocr(model: Any, image_path: str | Path) -> Any:
    """Run PaddleOCR 3.x ``predict`` or fall back to legacy ``ocr``."""
    path = str(image_path)
    inference_kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }

    if hasattr(model, "predict"):
        try:
            return model.predict(path, **inference_kwargs)
        except TypeError:
            return model.predict(path)

    preprocessed = _prepare_for_paddle(preprocess_image(image_path))
    try:
        return model.ocr(preprocessed, **inference_kwargs)
    except TypeError:
        return model.ocr(preprocessed)


def _prepare_for_paddle(image: np.ndarray) -> np.ndarray:
    """PaddleOCR 2.x expects a 3-channel image, not grayscale."""
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return image


def _extract_ocr_text_and_confidence(result: Any) -> tuple[str, float]:
    """Normalize PaddleOCR 2.x and 3.x results into text plus mean confidence."""
    if not result:
        return "", 0.0

    if isinstance(result, list):
        legacy_text, legacy_scores = _extract_legacy_lines(result)
        if legacy_text or legacy_scores:
            return " ".join(legacy_text), _mean_score(legacy_scores)

        new_text: list[str] = []
        new_scores: list[float] = []
        for page_result in result:
            page_text, page_scores = _extract_mapping_result(page_result)
            new_text.extend(page_text)
            new_scores.extend(page_scores)
        return " ".join(new_text), _mean_score(new_scores)

    text, scores = _extract_mapping_result(result)
    return " ".join(text), _mean_score(scores)


def _extract_legacy_lines(result: list[Any]) -> tuple[list[str], list[float]]:
    page_lines = result[0] if result and isinstance(result[0], list) else result
    lines: list[str] = []
    scores: list[float] = []
    for line in page_lines:
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        text_score = line[1]
        if not isinstance(text_score, (list, tuple)) or len(text_score) < 2:
            continue
        lines.append(str(text_score[0]))
        scores.append(float(text_score[1]))
    return lines, scores


def _extract_mapping_result(result: Any) -> tuple[list[str], list[float]]:
    if not isinstance(result, dict) and hasattr(result, "json"):
        try:
            result = result.json
        except Exception:  # noqa: BLE001
            pass

    if not isinstance(result, dict):
        return [], []

    if "res" in result and isinstance(result["res"], dict):
        result = result["res"]

    rec_texts = result.get("rec_texts") or []
    rec_scores = result.get("rec_scores") or []

    lines = [str(text) for text in rec_texts if text]
    scores = [float(score) for score in rec_scores if score is not None]
    return lines, scores


def _mean_score(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0
