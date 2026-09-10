"""Worklist assembly for the reviewer UI."""

from __future__ import annotations

from services.review.repository import (
    list_application_rows_ordered_by_created_at,
    load_pipeline_progress_by_application_ids,
    load_validation_results_by_application_ids,
)
from services.review.types import WorklistItem, WorklistResponse
from services.reviewer import summarize_for_display


def _required_int(value: object) -> int:
    """Convert a database value known to contain an application ID."""
    if isinstance(value, (int, str)):
        return int(value)
    raise ValueError(f"Expected an integer-compatible worklist value, got {value!r}")


def _summary_count(summary: object, key: str) -> int:
    """Read a numeric count from a reviewer summary without trusting its shape."""
    if not isinstance(summary, dict):
        return 0
    value = summary.get(key, 0)
    return int(value) if isinstance(value, (int, float, str)) else 0


def _optional_int(value: object) -> int | None:
    """Return an int for real counts, else None (missing progress row)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _optional_float(value: object) -> float | None:
    """Return a float for real percentages, else None (missing progress row)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def build_worklist() -> WorklistResponse:
    """Assemble the reviewer worklist with issue counts and pipeline status."""
    application_rows = list_application_rows_ordered_by_created_at()
    application_ids = [_required_int(row["id"]) for row in application_rows]
    anomaly_rows_by_application = load_validation_results_by_application_ids(application_ids)
    progress_by_application = load_pipeline_progress_by_application_ids(application_ids)

    worklist_items: list[WorklistItem] = []
    for application_row in application_rows:
        application_id = _required_int(application_row["id"])
        anomaly_rows = anomaly_rows_by_application.get(application_id, [])
        display_summary = summarize_for_display([dict(anomaly) for anomaly in anomaly_rows])
        pipeline_progress = progress_by_application.get(application_id)
        applicant_name = application_row.get("applicant_name")
        product_type = application_row.get("product_type")
        worklist_items.append(
            {
                "id": application_id,
                "loan_id": str(application_row["loan_id"]),
                "applicant_name": str(applicant_name) if applicant_name is not None else None,
                "product_type": str(product_type) if product_type is not None else None,
                "status": str(application_row["status"]),
                "created_at": str(application_row["created_at"]),
                "issues": _summary_count(display_summary, "raw_count"),
                "reviewer_issues": _summary_count(display_summary, "reviewer_count"),
                "business_issues": _summary_count(display_summary, "business_count"),
                "processing_warnings": _summary_count(display_summary, "processing_warning_count"),
                "pipeline_status": str(
                    pipeline_progress.get("operational_status")
                    if pipeline_progress
                    else "not_started"
                ),
                "pipeline_retryable": bool(
                    pipeline_progress and pipeline_progress.get("retryable")
                ),
                "pipeline_processed_pages": _optional_int(
                    pipeline_progress.get("processed_pages") if pipeline_progress else None
                ),
                "pipeline_total_pages": _optional_int(
                    pipeline_progress.get("total_pages") if pipeline_progress else None
                ),
                "pipeline_percentage": _optional_float(
                    pipeline_progress.get("percentage") if pipeline_progress else None
                ),
            }
        )

    return {"items": worklist_items}
