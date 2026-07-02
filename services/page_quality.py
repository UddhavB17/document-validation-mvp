"""Confidence helpers for document-type matches."""

from __future__ import annotations

from typing import Any

MIN_CLASSIFICATION_CONFIDENCE = 0.60
MIN_SCANNED_OCR_CONFIDENCE = 0.70


def is_confident_document_match(page: dict[str, Any], document_type: str) -> bool:
    """Return True when a page can safely satisfy a checklist document type."""
    if page.get("document_type") != document_type:
        return False

    classification_confidence = page.get("classification_confidence")
    if classification_confidence is not None and float(classification_confidence) < MIN_CLASSIFICATION_CONFIDENCE:
        return False

    ocr_confidence = page.get("ocr_confidence")
    if page.get("page_type") == "scanned" and ocr_confidence is not None:
        return float(ocr_confidence) >= MIN_SCANNED_OCR_CONFIDENCE

    return True


def confident_pages_for_types(pages: list[dict[str, Any]], document_types: list[str]) -> list[dict[str, Any]]:
    return [
        page
        for page in pages
        if any(is_confident_document_match(page, document_type) for document_type in document_types)
    ]
