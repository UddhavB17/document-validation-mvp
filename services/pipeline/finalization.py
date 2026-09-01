"""Pipeline result finalization and metadata assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database.models import ChecklistVerificationResponse, DocumentVerificationReport
from services.audit_service import log_action
from services.exception_aggregator import aggregate
from services.llm_service import generate_explanation, summarize_exceptions
from services.pipeline.persistence import _save_ground_truth, _save_llm_summary, _save_pages, _should_call_llm
from services.progress_tracker import mark_completed
from services.report_generator import build_report, save_report_json
from services.reviewer import build_reviewer_summary, save_reviewer_summary


def _finalize_pipeline_result(
    *,
    application_id: int,
    pages: list[dict[str, Any]],
    ground_truth: dict[str, Any],
    anomalies: list[dict[str, Any]],
    pipeline_status: str,
    partial_failure_count: int,
    generate_llm_summary: bool | None,
) -> dict[str, Any]:
    _save_ground_truth(application_id, ground_truth)
    _save_pages(application_id, pages)
    result = aggregate(pages, anomalies, ground_truth, application_id=application_id)
    summary = summarize_exceptions(result["anomalies"])
    if _should_call_llm(generate_llm_summary):
        llm_summary = generate_explanation(result["anomalies"], ground_truth, application_id)
        summary = llm_summary or summary
    if summary:
        _save_llm_summary(application_id, summary)

    report_path = save_report_json(
        build_report(
            application_id=application_id,
            loan_id=str(ground_truth.get("loan_id") or ""),
            exceptions=result["anomalies"],
            llm_summary=summary or "",
        )
    )
    result.update(
        {
            "application_id": application_id,
            "pipeline_status": pipeline_status,
            "partial_failure_count": partial_failure_count,
            "llm_summary": summary,
            "report_path": str(report_path),
        }
    )
    mark_completed(application_id, result["final_status"], pipeline_status)
    log_action(
        application_id,
        "pipeline_completed",
        {
            "total_pages": result["total_pages"],
            "anomaly_count": len(result["anomalies"]),
            "final_status": result["final_status"],
            "pipeline_status": pipeline_status,
            "partial_failure_count": partial_failure_count,
            "report_path": str(report_path),
        },
    )
    return result


def _complete_pipeline(
    *,
    application_id: int,
    result: dict[str, Any],
    pipeline_status: str,
    partial_failure_count: int,
    report_path: str | Path,
) -> None:
    """Mark a pipeline complete and write its final audit event."""
    mark_completed(application_id, result["final_status"], pipeline_status)
    from services.reviewer import collapse_for_reviewer

    actionable_count = len(collapse_for_reviewer(result["anomalies"]))
    log_action(
        application_id,
        "pipeline_completed",
        {
            "total_pages": result["total_pages"],
            "anomaly_count": actionable_count,
            "raw_anomaly_count": len(result["anomalies"]),
            "final_status": result["final_status"],
            "pipeline_status": pipeline_status,
            "partial_failure_count": partial_failure_count,
            "report_path": str(report_path),
        },
    )
    result["actionable_anomaly_count"] = actionable_count


def _add_pipeline_result_metadata(
    *,
    result: dict[str, Any],
    application_id: int,
    pipeline_status: str,
    partial_failure_count: int,
    summary: str | None,
    report_path: str | Path,
    ocr_json_path: Path,
    verification_report: DocumentVerificationReport | None,
    checklist_verification: ChecklistVerificationResponse,
    mapped_result: dict[str, Any] | None,
) -> None:
    """Attach persisted artifacts and mode-specific data to the API result."""
    result.update(
        {
            "application_id": application_id,
            "pipeline_status": pipeline_status,
            "partial_failure_count": partial_failure_count,
            "llm_summary": summary,
            "report_path": str(report_path),
            "ocr_json_path": str(ocr_json_path),
            "verification_report": (
                verification_report.model_dump(mode="json")
                if verification_report is not None
                else None
            ),
            "checklist_verification": checklist_verification.model_dump(mode="json"),
        }
    )
    if mapped_result is None:
        return

    result.update(
        {
            "verification_mode": _mapped_verification_mode(mapped_result),
            "checked_fields": mapped_result["checked_fields"],
            "matched_fields": mapped_result["matched_fields"],
            "observations": mapped_result["observations"],
            "people_verification": mapped_result["people_verification"],
            "source_classifications": mapped_result["source_classifications"],
            "automatic_document_index": mapped_result.get("automatic_document_index", []),
            "unclassified_pages": mapped_result.get("unclassified_pages", []),
        }
    )


def _mapped_report_metadata(
    mapped_result: dict[str, Any] | None,
    checklist_verification: ChecklistVerificationResponse,
) -> dict[str, Any] | None:
    """Build report metadata that only applies to mapped verification."""
    if mapped_result is None:
        return None

    return {
        "verification_mode": _mapped_verification_mode(mapped_result),
        "checked_fields": mapped_result["checked_fields"],
        "matched_fields": mapped_result["matched_fields"],
        "people_verification": mapped_result["people_verification"],
        "source_classifications": mapped_result["source_classifications"],
        "automatic_document_index": mapped_result.get("automatic_document_index", []),
        "unclassified_pages": mapped_result.get("unclassified_pages", []),
        "checklist_verification": checklist_verification.model_dump(mode="json"),
    }


def _mapped_verification_mode(mapped_result: dict[str, Any]) -> str:
    """Return the public mode name for a mapped comparison result."""
    if "automatic_document_index" in mapped_result:
        return "automatic_json_comparison"
    return "mapped_zip_json_comparison"


def _save_mapped_reviewer_summary(
    *,
    application_id: int,
    total_pages: int,
    anomalies: list[dict[str, Any]],
    mapped_result: dict[str, Any] | None,
) -> None:
    """Persist reviewer-only details produced by trusted JSON comparison."""
    if mapped_result is None:
        return

    reviewer_summary = build_reviewer_summary(
        total_pages=total_pages,
        anomalies=anomalies,
        checked_fields=int(mapped_result["checked_fields"]),
        matched_fields=int(mapped_result["matched_fields"]),
    )
    reviewer_summary.update(
        {
            "people_verification": mapped_result["people_verification"],
            "source_classifications": mapped_result["source_classifications"],
            "automatic_document_index": mapped_result.get("automatic_document_index", []),
            "unclassified_pages": mapped_result.get("unclassified_pages", []),
        }
    )
    save_reviewer_summary(application_id, reviewer_summary)
