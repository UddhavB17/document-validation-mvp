"""Confidence helpers for document-type matches."""

from __future__ import annotations

from typing import Any

from services.config import effective_config
from services.validation_gates import (
    has_bank_statement_anchor,
    has_bureau_anchor,
    has_cheque_anchor,
    has_pan_anchor,
    has_passbook_anchor,
)


_DOCUMENT_TYPE_ALIASES: dict[str, set[str]] = {
    "Technical Clearance Report": {"Technical Report"},
}


def is_confident_document_match(page: dict[str, Any], document_type: str) -> bool:
    """Return True when a page can safely satisfy a checklist document type."""
    actual_type = page.get("document_type")
    if actual_type != document_type and actual_type not in _DOCUMENT_TYPE_ALIASES.get(document_type, set()):
        if not _is_legal_clearance_evidence(page, document_type):
            return False

    if not _meets_confidence_threshold(page):
        return False

    fields = page.get("extracted_fields") or {}
    text = str(page.get("ocr_text") or "")
    expected_key = str(document_type or "").strip().lower()
    if expected_key in {"pan", "pan card"} and not has_pan_anchor(text, fields):
        return False
    if expected_key == "bank statement" and not has_bank_statement_anchor(text, fields):
        return False
    if expected_key == "passbook" and not has_passbook_anchor(text, fields):
        return False
    if expected_key == "cheque" and not has_cheque_anchor(text, fields):
        return False
    if expected_key in {"crif report", "cibil report"} and not has_bureau_anchor(text, fields, "applicant_name"):
        return False

    return True


def _meets_confidence_threshold(page: dict[str, Any]) -> bool:
    config = effective_config()
    classification_confidence = page.get("classification_confidence")
    if classification_confidence is not None and float(classification_confidence) < config.min_classification_confidence:
        return False

    ocr_confidence = page.get("ocr_confidence")
    if page.get("page_type") == "scanned" and ocr_confidence is not None:
        return float(ocr_confidence) >= config.min_scanned_ocr_confidence

    return True


def _is_legal_clearance_evidence(page: dict[str, Any], expected_type: str) -> bool:
    if expected_type != "Legal Clearance Report":
        return False

    if page.get("document_type") not in {"Legal Clearance Report", "Property Document", "Sanction Letter"}:
        return False

    text = str(page.get("ocr_text") or "").lower()
    # Agreement/sanction boilerplate often contains isolated words such as
    # "legal", "security" and "clear".  Only accept it as alternate legal
    # clearance evidence when it actually states a positive title conclusion.
    has_title_signal = "title" in text
    has_positive_title_signal = any(
        term in text for term in ("marketable", "unencumbered", "clear title", "title is clear")
    )
    if not (has_title_signal and has_positive_title_signal):
        return False

    return _meets_confidence_threshold(page)


def is_exact_confident_document_match(page: dict[str, Any], document_type: str) -> bool:
    """Return True only for exact document-type matches."""
    if page.get("document_type") != document_type:
        return False
    return _meets_confidence_threshold(page)


def confident_pages_for_types(pages: list[dict[str, Any]], document_types: list[str]) -> list[dict[str, Any]]:
    return [
        page
        for page in pages
        if any(is_confident_document_match(page, document_type) for document_type in document_types)
    ]
