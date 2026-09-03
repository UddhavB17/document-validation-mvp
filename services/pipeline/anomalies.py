"""Checklist and anomaly collection helpers."""

from __future__ import annotations

from typing import Any

from services.checklist_engine import build_anomaly, run_checks
from services.processing_policy import OCR_SKIPPED_DOCUMENT_TYPE, max_scanned_pages_for_ocr


def _processing_error_anomalies(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for page in pages:
        extracted_fields = page.get("extracted_fields") or {}
        if not isinstance(extracted_fields, dict) or "_processing_error" not in extracted_fields:
            continue
        anomalies.append(
            build_anomaly(
                rule_id="PAGE_PROCESSING_ERROR",
                s_no=None,
                severity="HIGH",
                expected_value="Page processed without internal errors",
                found_value=str(
                    extracted_fields.get("_processing_error") or "Unknown processing error"
                ),
                reason="OCR, classification, or field extraction failed for this page.",
                page_number=page.get("page_number"),
                document_type=page.get("document_type"),
            )
        )
    return anomalies


def _ocr_budget_anomaly(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    scanned_pages = [page for page in pages if page.get("page_type") == "scanned"]
    skipped_pages = [
        page for page in scanned_pages if page.get("document_type") == OCR_SKIPPED_DOCUMENT_TYPE
    ]
    if not skipped_pages:
        return None

    budget = max_scanned_pages_for_ocr()
    processed_count = len(scanned_pages) - len(skipped_pages)
    return build_anomaly(
        rule_id="OCR_BUDGET_PARTIAL_SCAN",
        s_no=None,
        severity="MEDIUM",
        expected_value="All scanned pages OCR-checked for final validation",
        found_value=(
            f"OCR checked {processed_count} of {len(scanned_pages)} scanned page(s); "
            f"{len(skipped_pages)} page(s) skipped by budget {budget}"
        ),
        reason=(
            "Checklist results are based on an OCR sample. Run a full scan before "
            "final sign-off if missing-document accuracy is required."
        ),
        page_number=skipped_pages[0].get("page_number"),
        document_type=OCR_SKIPPED_DOCUMENT_TYPE,
    )


def _pipeline_outcome(
    anomalies: list[dict[str, Any]], processing_errors: list[dict[str, Any]]
) -> str:
    if processing_errors:
        return "partial_failed"
    if any(anomaly.get("rule_id") == "UNSUPPORTED_DOCUMENT_TYPE" for anomaly in anomalies):
        return "unsupported_input"
    return "completed"


def _run_checklist_with_fallback(
    pages: list[dict[str, Any]],
    ground_truth: dict[str, Any],
    system_data: dict[str, Any] | None,
    product_type: str,
) -> list[dict[str, Any]]:
    try:
        return run_checks(pages, ground_truth, system_data, product_type)
    except ValueError as exc:
        anomalies = run_checks(pages, ground_truth, system_data, "LAP")
        anomalies.append(
            build_anomaly(
                rule_id="CHECKLIST_PRODUCT_FALLBACK",
                s_no=None,
                severity="LOW",
                expected_value=f"Checklist for {product_type}",
                found_value="Using LAP checklist",
                reason=str(exc),
            )
        )
        return anomalies
