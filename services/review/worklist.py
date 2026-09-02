"""Worklist assembly for the reviewer UI."""

from __future__ import annotations

from services.reviewer import summarize_for_display
from services.review.repository import (
    list_application_rows_ordered_by_created_at,
    load_pipeline_progress_by_application_ids,
    load_validation_results_by_application_ids,
)
from services.review.types import WorklistItem, WorklistResponse


def build_worklist() -> WorklistResponse:
    rows = list_application_rows_ordered_by_created_at()
    application_ids = [int(row["id"]) for row in rows]
    anomalies_by_app = load_validation_results_by_application_ids(application_ids)
    progress_by_app = load_pipeline_progress_by_application_ids(application_ids)

    items: list[WorklistItem] = []
    for row in rows:
        application_id = int(row["id"])
        anomalies = anomalies_by_app.get(application_id, [])
        summary = summarize_for_display([dict(anomaly) for anomaly in anomalies])
        progress = progress_by_app.get(application_id)
        items.append(
            {
                "id": application_id,
                "loan_id": str(row["loan_id"]),
                "applicant_name": row.get("applicant_name"),  # type: ignore[typeddict-item]
                "product_type": row.get("product_type"),  # type: ignore[typeddict-item]
                "status": str(row["status"]),
                "created_at": str(row["created_at"]),
                "issues": int(summary["raw_count"]),
                "reviewer_issues": int(summary["reviewer_count"]),
                "business_issues": int(summary["business_count"]),
                "processing_warnings": int(summary["processing_warning_count"]),
                "pipeline_status": (
                    progress.get("operational_status") if progress else "not_started"
                ),
                "pipeline_retryable": bool(progress and progress.get("retryable")),
            }
        )

    return {"items": items}
