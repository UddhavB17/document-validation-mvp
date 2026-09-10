"""Pipeline result finalization for early-exit paths."""

from __future__ import annotations

import logging
from typing import Any

from services.audit_service import log_action
from services.exception_aggregator import aggregate
from services.llm_service import generate_explanation, generate_summaries, summarize_exceptions
from services.pipeline.persistence import (
    _save_llm_summary,
    _save_pages,
    _should_call_llm,
)
from services.progress_tracker import mark_completed
from services.report_generator import build_report, save_report_json

logger = logging.getLogger(__name__)


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
    _save_pages(application_id, pages)
    result = aggregate(pages, anomalies, ground_truth, application_id=application_id)
    # ws-f accuracy: persist the ops payload (minus checklist) so
    # ``applications.ops_findings_json`` is non-null after a successful run.
    # The endpoint recomputes when needed; a store failure must never fail
    # the pipeline (store_ops_payload already swallows/logs internally).
    try:
        from services.ops_presentation import store_ops_payload

        store_ops_payload(application_id)
    except Exception:  # noqa: BLE001 - ops persistence is best-effort
        logger.warning(
            "Could not store ops payload for application %s", application_id, exc_info=True
        )
    summary = summarize_exceptions(result["anomalies"])
    if _should_call_llm(generate_llm_summary):
        llm_summary = generate_explanation(result["anomalies"], ground_truth, application_id)
        summary = llm_summary or summary
    if summary:
        _save_llm_summary(application_id, summary)
    # --- fx-schema: persist bilingual ops summaries ---
    generate_summaries(application_id, {"findings": result["anomalies"], "ground_truth": ground_truth})

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
