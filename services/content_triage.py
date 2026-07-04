"""Lightweight content triage before detailed document classification."""

from __future__ import annotations

import re
from typing import Any


PHOTO_MIN_CHARS = 40
PHOTO_MAX_CONFIDENCE = 0.35
HANDWRITTEN_MAX_CONFIDENCE = 0.62
HANDWRITTEN_MAX_DENSITY = 160.0
PRINTED_MIN_CONFIDENCE = 0.70
PRINTED_MIN_CHARS = 120


def triage_page_content(
    *,
    page_type: str,
    text: str,
    ocr_confidence: float | None,
    ocr_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bucket page content as photo, printed_scan, or handwritten.

    Thresholds are intentionally conservative:
    - photos usually have near-zero OCR text and very low confidence;
    - printed scans have dense text or high OCR confidence;
    - handwritten pages sit between those two and should be reviewed when
      confidence is too low to classify safely.
    """
    text = text or ""
    metadata = ocr_metadata or {}
    char_count = int(metadata.get("char_count") or len(text.strip()))
    word_count = int(metadata.get("word_count") or len(re.findall(r"\w+", text)))
    line_count = int(metadata.get("line_count") or len([line for line in text.splitlines() if line.strip()]))
    confidence = float(ocr_confidence) if ocr_confidence is not None else None
    text_density = _text_density(metadata, char_count)
    aspect_ratio = _aspect_ratio(metadata)

    if page_type == "digital":
        return _result(
            "printed_scan",
            1.0,
            "digital selectable text; OCR triage not required",
            char_count,
            word_count,
            line_count,
            text_density,
            aspect_ratio,
            confidence,
        )

    if char_count < PHOTO_MIN_CHARS and (confidence is None or confidence <= PHOTO_MAX_CONFIDENCE):
        reason = "near-zero OCR text and low OCR confidence"
        if aspect_ratio and (aspect_ratio >= 1.25 or aspect_ratio <= 0.80):
            reason += "; image aspect ratio is photo-like"
        return _result(
            "photo",
            0.95,
            reason,
            char_count,
            word_count,
            line_count,
            text_density,
            aspect_ratio,
            confidence,
        )

    if confidence is not None and confidence < HANDWRITTEN_MAX_CONFIDENCE and text_density < HANDWRITTEN_MAX_DENSITY:
        return _result(
            "handwritten",
            0.80,
            "sparse OCR text with low recognition confidence",
            char_count,
            word_count,
            line_count,
            text_density,
            aspect_ratio,
            confidence,
        )

    if (confidence is not None and confidence >= PRINTED_MIN_CONFIDENCE) or char_count >= PRINTED_MIN_CHARS:
        return _result(
            "printed_scan",
            0.90,
            "dense text or high OCR confidence",
            char_count,
            word_count,
            line_count,
            text_density,
            aspect_ratio,
            confidence,
        )

    return _result(
        "handwritten",
        0.65,
        "OCR signal is present but not dense/confident enough for printed classification",
        char_count,
        word_count,
        line_count,
        text_density,
        aspect_ratio,
        confidence,
    )


def _text_density(metadata: dict[str, Any], char_count: int) -> float:
    if metadata.get("text_density") is not None:
        return float(metadata["text_density"])
    width = float(metadata.get("image_width") or 0)
    height = float(metadata.get("image_height") or 0)
    megapixels = (width * height) / 1_000_000 if width and height else 1.0
    return round(char_count / max(megapixels, 0.1), 2)


def _aspect_ratio(metadata: dict[str, Any]) -> float | None:
    width = float(metadata.get("image_width") or 0)
    height = float(metadata.get("image_height") or 0)
    if not width or not height:
        return None
    return round(width / height, 3)


def _result(
    category: str,
    confidence: float,
    reason: str,
    char_count: int,
    word_count: int,
    line_count: int,
    text_density: float,
    aspect_ratio: float | None,
    ocr_confidence: float | None,
) -> dict[str, Any]:
    return {
        "category": category,
        "confidence": confidence,
        "reason": reason,
        "char_count": char_count,
        "word_count": word_count,
        "line_count": line_count,
        "text_density": text_density,
        "aspect_ratio": aspect_ratio,
        "ocr_confidence": ocr_confidence,
    }
