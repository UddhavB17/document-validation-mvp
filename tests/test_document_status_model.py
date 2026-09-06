"""Tests for the formalized document/checklist status model."""

import pytest

from services.checklist_output import build_checklist_verification_response
from services.checklist_status_map import (
    CHECKLIST_STATUSES,
    OCR_STATUSES,
    map_legacy_checklist_status,
)
from services.pipeline.page_processing import compute_ocr_status


def test_legacy_unknown_maps_to_manual_review() -> None:
    assert map_legacy_checklist_status("unknown") == "manual_review"
    assert map_legacy_checklist_status("verified") == "required_and_present"
    assert map_legacy_checklist_status("missing") == "required_and_missing"
    assert map_legacy_checklist_status("not_applicable") == "not_applicable"
    assert map_legacy_checklist_status("needs_review") == "manual_review"


def test_unmapped_legacy_status_raises_instead_of_passing_through() -> None:
    with pytest.raises(ValueError):
        map_legacy_checklist_status("something_new")


def test_checklist_status_enum_has_no_legacy_values() -> None:
    assert set(CHECKLIST_STATUSES) == {
        "required_and_present",
        "required_and_missing",
        "not_applicable",
        "not_evaluated_by_engine",
        "manual_review",
    }
    assert set(OCR_STATUSES) == {
        "success",
        "failed",
        "no_text_extracted",
        "not_applicable",
    }


def test_ocr_failed_page_routes_to_manual_review_without_anomaly() -> None:
    pages = [
        {
            "page_number": 1,
            "page_type": "scanned",
            "document_type": "PAN",
            "classification_confidence": 0.95,
            "ocr_confidence": 0.0,
            "ocr_status": "failed",
            "ocr_text": "",
            "extracted_fields": {"_processing_error": "boom"},
        }
    ]
    response = build_checklist_verification_response(
        loan_file_id="LAP-1",
        pages=pages,
        anomalies=[],
        product_type="LAP",
    )
    pan_item = next(item for item in response.items if item.item_number == 7)
    assert pan_item.status == "manual_review"
    assert pan_item.flagged_reason == "ocr_failed"


def test_ocr_status_thresholds() -> None:
    # Error always wins for scanned pages.
    assert (
        compute_ocr_status(
            page_type="scanned",
            document_type="PAN",
            text="some recovered text that is long enough to count",
            error="timeout",
        )
        == "failed"
    )
    # Empty / short text recovers nothing.
    assert (
        compute_ocr_status(
            page_type="scanned", document_type="PAN", text="", error=None
        )
        == "no_text_extracted"
    )
    assert (
        compute_ocr_status(
            page_type="scanned", document_type="PAN", text="  short  ", error=None
        )
        == "no_text_extracted"
    )
    # Budget-skipped pages carry no text and must NOT be not_applicable.
    assert (
        compute_ocr_status(
            page_type="scanned", document_type="OCR Skipped", text="", error=None
        )
        == "no_text_extracted"
    )
    # Healthy scanned page.
    assert (
        compute_ocr_status(
            page_type="scanned",
            document_type="PAN",
            text="PAN number TSTAA0001T with plenty of surrounding text here",
            error=None,
        )
        == "success"
    )
    # OCR genuinely does not apply here.
    assert (
        compute_ocr_status(
            page_type="digital",
            document_type="Application Form",
            text="digital text",
            error="ignored",
        )
        == "not_applicable"
    )
    assert (
        compute_ocr_status(
            page_type="digital",
            document_type="DB Data",
            text="{}",
            error=None,
        )
        == "not_applicable"
    )
