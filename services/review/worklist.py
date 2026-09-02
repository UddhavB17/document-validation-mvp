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
    if isinstance(value, (int, str)):
        return int(value)
    raise ValueError(f"Expected an integer-compatible worklist value, got {value!r}")


def _summary_count(summary: object, key: str) -> int:
    if not isinstance(summary, dict):
        return 0
    value = summary.get(key, 0)
    return int(value) if isinstance(value, (int, float, str)) else 0


def build_worklist() -> WorklistResponse:
    rows = list_application_rows_ordered_by_created_at()
    application_ids = [_required_int(row["id"]) for row in rows]
    anomalies_by_app = load_validation_results_by_application_ids(application_ids)
    progress_by_app = load_pipeline_progress_by_application_ids(application_ids)

    items: list[WorklistItem] = []
    for row in rows:
        application_id = _required_int(row["id"])
        anomalies = anomalies_by_app.get(application_id, [])
        summary = summarize_for_display([dict(anomaly) for anomaly in anomalies])
        progress = progress_by_app.get(application_id)
        applicant_name = row.get("applicant_name")
        product_type = row.get("product_type")
        items.append(
            {
                "id": application_id,
                "loan_id": str(row["loan_id"]),
                "applicant_name": str(applicant_name) if applicant_name is not None else None,
                "product_type": str(product_type) if product_type is not None else None,
                "status": str(row["status"]),
                "created_at": str(row["created_at"]),
                "issues": _summary_count(summary, "raw_count"),
                "reviewer_issues": _summary_count(summary, "reviewer_count"),
                "business_issues": _summary_count(summary, "business_count"),
                "processing_warnings": _summary_count(summary, "processing_warning_count"),
                "pipeline_status": str(
                    progress.get("operational_status") if progress else "not_started"
                ),
                "pipeline_retryable": bool(progress and progress.get("retryable")),
            }
        )

    return {"items": items}
