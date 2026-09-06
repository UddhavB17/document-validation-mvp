"""Main PDF validation pipeline orchestration."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from services.audit_service import log_action
from services.checklist_engine import build_anomaly
from services.checklist_output import build_checklist_verification_response
from services.config import get_setting
from services.exception_aggregator import aggregate
from services.input_classifier import classify_input_text
from services.job_control import cooperate
from services.llm_service import generate_explanation, generate_summaries, summarize_exceptions
from services.paths import processed_output_dir
from services.pdf_processor import process_pdf_structure
from services.pipeline.anomalies import (
    _ocr_budget_anomaly,
    _pipeline_outcome,
    _processing_error_anomalies,
    _run_checklist_with_fallback,
)
from services.pipeline.finalization import _finalize_pipeline_result
from services.pipeline.input_preparation import (
    _build_unsupported_page_records,
    _checklist_processing_metadata,
    _extract_digital_text_by_page,
    _mapped_ground_truth,
)
from services.pipeline.page_processing import _build_page_records
from services.pipeline.persistence import (
    _load_page_checkpoints,
    _save_ground_truth,
    _save_llm_summary,
    _save_pages,
    _should_call_llm,
    _update_uploaded_file_counts,
)
from services.pipeline.verification import (
    _run_document_verification,
    _stamp_pages_from_document_index,
)
from services.progress_tracker import mark_completed, start_tracking, touch_progress, update_stage
from services.report_generator import build_report, save_report_json
from services.reviewer import build_reviewer_summary, save_reviewer_summary
from services.text_extractor import extract_ground_truth
from services.verification_report_store import save_verification_report


def run_pipeline(
    pdf_path: str | Path,
    application_id: int,
    output_dir: str | Path | None = None,
    system_data: dict[str, Any] | None = None,
    product_type: str = "LAP",
    generate_llm_summary: bool | None = None,
    mapped_manifest: dict[str, Any] | None = None,
    source_documents: list[dict[str, Any]] | None = None,
    job_id: int | None = None,
    resume: bool = False,
    refresh_cached_ocr: bool = False,
) -> dict[str, Any]:
    """Process one uploaded loan-file PDF and persist validation results."""
    # Transient page renders live under the job work dir (contracts §2) so no
    # durable page image is ever written next to processed outputs. Without a
    # job id (tests, offline re-runs) fall back to the caller's output dir.
    # The work dir is always removed in a ``finally``.
    job_work_root = Path(
        str(get_setting("dmef.job_work_dir", "/tmp/dmef-jobs") or "/tmp/dmef-jobs")
    )
    job_work_dir = job_work_root / str(job_id) if job_id is not None else None
    try:
        return _run_pipeline_impl(
            pdf_path,
            application_id,
            output_dir=output_dir,
            system_data=system_data,
            product_type=product_type,
            generate_llm_summary=generate_llm_summary,
            mapped_manifest=mapped_manifest,
            source_documents=source_documents,
            job_id=job_id,
            resume=resume,
            refresh_cached_ocr=refresh_cached_ocr,
            _job_work_dir=job_work_dir,
        )
    finally:
        if job_work_dir is not None:
            shutil.rmtree(job_work_dir, ignore_errors=True)


def _run_pipeline_impl(
    pdf_path: str | Path,
    application_id: int,
    output_dir: str | Path | None = None,
    system_data: dict[str, Any] | None = None,
    product_type: str = "LAP",
    generate_llm_summary: bool | None = None,
    mapped_manifest: dict[str, Any] | None = None,
    source_documents: list[dict[str, Any]] | None = None,
    job_id: int | None = None,
    resume: bool = False,
    refresh_cached_ocr: bool = False,
    _job_work_dir: Path | None = None,
) -> dict[str, Any]:
    """Inner pipeline body; ``run_pipeline`` owns the job work-dir lifetime."""
    pdf_path = Path(pdf_path)
    resolved_output_dir = Path(output_dir) if output_dir is not None else processed_output_dir()
    if _job_work_dir is not None:
        image_output_dir = _job_work_dir / "pages"
    else:
        image_output_dir = resolved_output_dir / f"application_{application_id}" / "pages"

    cooperate(job_id, application_id)
    structure = process_pdf_structure(pdf_path, image_output_dir)
    start_tracking(
        application_id,
        total_pages=int(structure.get("total_pages") or 0),
        digital_pages=int(structure.get("digital_pages") or 0),
        scanned_pages=int(structure.get("scanned_pages") or 0),
        stage="structure_processed",
        message="PDF structure extracted",
        resume=resume,
    )
    update_stage(application_id, "extracting_digital_text", "Extracting digital text")
    digital_text_by_page = _extract_digital_text_by_page(pdf_path)
    ground_truth = dict(extract_ground_truth(pdf_path))
    if mapped_manifest is not None:
        ground_truth = _mapped_ground_truth(mapped_manifest, system_data)
        if system_data is not None:
            if "reference_data" not in system_data:
                system_data["reference_data"] = ground_truth.get("reference_data")
            if "people" not in system_data:
                system_data["people"] = ground_truth.get("reference_data")
    elif system_data:
        ground_truth = {
            **system_data,
            **{key: value for key, value in ground_truth.items() if value},
        }

    # ground_truth is saved once, after verification, at persisting_outputs
    # (ws-a data diet: no duplicate raw-dump writes per run).

    input_classification = classify_input_text(digital_text_by_page)
    if input_classification["input_type"] == "unsupported" and mapped_manifest is None:
        update_stage(application_id, "unsupported_input", str(input_classification["reason"]))
        pages = _build_unsupported_page_records(structure["pages"], digital_text_by_page)
        result = _finalize_pipeline_result(
            application_id=application_id,
            pages=pages,
            ground_truth=ground_truth,
            anomalies=[
                build_anomaly(
                    rule_id="UNSUPPORTED_DOCUMENT_TYPE",
                    s_no=None,
                    severity="HIGH",
                    expected_value="Loan-file documents matching checklist",
                    found_value=str(input_classification["reason"]),
                    reason="Uploaded PDF appears unrelated to the loan checklist workflow.",
                    page_number=1,
                    document_type="Unsupported",
                )
            ],
            pipeline_status="unsupported_input",
            partial_failure_count=0,
            generate_llm_summary=generate_llm_summary,
        )
        _update_uploaded_file_counts(application_id, structure)
        log_action(application_id, "input_classified_unsupported", input_classification)
        return result
    if input_classification["input_type"] == "unsupported" and mapped_manifest is not None:
        log_action(
            application_id,
            "mapped_input_classifier_warning",
            input_classification,
        )

    update_stage(application_id, "processing_pages", "Classifying and extracting page fields")
    source_page_starts = {
        int(item.get("internal_page_start") or 0)
        for item in source_documents or []
        if item.get("internal_page_start") is not None
    }
    if mapped_manifest is not None:
        source_mapping_pages: dict[str, list[int]] = {}
        for item in mapped_manifest.get("documents") or []:
            source_id = str(item.get("source_document_id") or "unassigned")
            source_mapping_pages.setdefault(source_id, []).extend(
                int(number) for number in item.get("pages") or []
            )
        source_page_starts.update(
            min(numbers) for numbers in source_mapping_pages.values() if numbers
        )
    checkpoint_pages = _load_page_checkpoints(application_id) if resume else []
    pages = _build_page_records(
        structure["pages"],
        digital_text_by_page,
        application_id=application_id,
        source_page_starts=source_page_starts,
        source_documents=source_documents,
        job_id=job_id,
        checkpoint_pages=checkpoint_pages,
        refresh_cached_ocr=refresh_cached_ocr,
    )
    mapped_result: dict[str, Any] | None = None
    evidence_resolution: dict[str, Any] | None = None
    from services.person_ownership import assign_page_owners

    if mapped_manifest is not None:
        cooperate(job_id, application_id)
        update_stage(
            application_id,
            "resolving_document_evidence",
            "Resolving document groups and people from observed identity evidence",
        )
        from services.evidence_resolution import resolve_trusted_evidence

        evidence_resolution = resolve_trusted_evidence(
            pages,
            mapped_manifest.get("reference_data") or {},
            source_documents=source_documents,
        )
        log_action(
            application_id,
            "trusted_evidence_resolved",
            {
                "mode": evidence_resolution.get("mode"),
                "resolved_groups": evidence_resolution.get("resolved_groups"),
                "resolved_owners": evidence_resolution.get("resolved_owners"),
            },
        )

    assign_page_owners(
        pages, {**(ground_truth or {}), **(system_data or {}), **(mapped_manifest or {})}
    )
    if mapped_manifest is not None:
        automatic_index: dict[str, Any] | None = None
        if not (mapped_manifest.get("documents") or []):
            from services.automatic_document_index import build_automatic_document_index

            automatic_index = build_automatic_document_index(
                pages,
                mapped_manifest.get("reference_data") or {},
                source_documents=source_documents,
            )
            mapped_manifest = {
                **mapped_manifest,
                "documents": automatic_index["documents"],
            }
            _stamp_pages_from_document_index(pages, automatic_index["documents"])
        update_stage(
            application_id,
            "verifying_mapped_documents",
            "Comparing automatically identified documents with trusted JSON",
        )
        from services.mapped_verification import compare_processed_pages

        mapped_result = compare_processed_pages(
            pages,
            mapped_manifest,
            source_documents=source_documents,
        )
        if evidence_resolution is not None:
            mapped_result["evidence_resolution"] = evidence_resolution
        if automatic_index is not None:
            mapped_result["anomalies"] = [
                *automatic_index["anomalies"],
                *mapped_result["anomalies"],
            ]
            mapped_result["automatic_document_index"] = automatic_index["documents"]
            mapped_result["unclassified_pages"] = automatic_index["unclassified_pages"]
        verification_report = None
    else:
        cooperate(job_id, application_id)
        update_stage(
            application_id, "verifying_documents", "Comparing OCR fields with Graviton data"
        )
        verification_report, _document_page_numbers = _run_document_verification(
            pdf_path, application_id, pages, ground_truth
        )
    cooperate(job_id, application_id)
    update_stage(application_id, "persisting_outputs", "Saving extracted data")
    _save_ground_truth(application_id, ground_truth)
    touch_progress(application_id, "Saved ground truth")
    _save_pages(application_id, pages)
    touch_progress(application_id, f"Saved {len(pages)} page records")
    # Avoid loading every page-event payload (can be huge with LLM metadata) just
    # to export OCR JSON — that was hanging/staling jobs at persisting_outputs.
    progress_snapshot = {
        "completed_pages": [
            {
                "page_number": page.get("page_number"),
                "total_pages": len(pages),
                "page_type": page.get("page_type"),
                "document_type": page.get("document_type"),
                "status": page.get("status") or "completed",
                "elapsed_seconds": page.get("elapsed_seconds"),
                "error": page.get("error"),
            }
            for page in pages
        ]
    }
    # The OCR document JSON export is generated on demand only
    # (GET /review/applications/{id}/ocr-json); nothing is written at run end
    # (ws-a data diet).
    touch_progress(application_id, "OCR export deferred to on-demand download")
    if verification_report is not None:
        save_verification_report(application_id, verification_report)
    _update_uploaded_file_counts(application_id, structure)

    cooperate(job_id, application_id)
    update_stage(application_id, "running_checklist", "Running validation checks")
    anomalies = _run_checklist_with_fallback(pages, ground_truth, system_data, product_type)
    if mapped_result is not None:
        anomalies.extend(mapped_result["anomalies"])
    partial_scan_anomaly = _ocr_budget_anomaly(pages)
    if partial_scan_anomaly is not None:
        anomalies.append(partial_scan_anomaly)
    processing_error_anomalies = _processing_error_anomalies(pages)
    for anomaly in processing_error_anomalies:
        log_action(
            application_id,
            "page_processing_error",
            {
                "page_number": anomaly.get("page_number"),
                "reason": anomaly.get("found_value"),
            },
        )
    anomalies.extend(processing_error_anomalies)
    touch_progress(application_id, f"Aggregating {len(anomalies)} checklist findings")
    result = aggregate(pages, anomalies, ground_truth, application_id=application_id)
    # fx-integrate-df (NEEDS-COORDINATION: orchestrator is shared pipeline
    # code): persist the ops payload on the live path so
    # ``applications.ops_findings_json`` is non-null after a successful run.
    # Best-effort; the endpoint recomputes when needed.
    try:
        from services.ops_presentation import store_ops_payload

        store_ops_payload(application_id)
    except Exception:  # noqa: BLE001 - ops persistence is best-effort
        logging.getLogger(__name__).warning(
            "Could not store ops payload for application %s", application_id, exc_info=True
        )
    pipeline_status = _pipeline_outcome(result["anomalies"], processing_error_anomalies)
    checklist_verification = build_checklist_verification_response(
        loan_file_id=str(ground_truth.get("loan_id") or application_id),
        pages=pages,
        anomalies=anomalies,
        product_type=product_type,
        system_data={**ground_truth, **(system_data or {})},
        processing_metadata=_checklist_processing_metadata(progress_snapshot),
        include_narration=False,
    )
    from services.trusted_reconciliation import build_trusted_reconciliation

    trusted_reconciliation = build_trusted_reconciliation(
        pages,
        {**ground_truth, **(system_data or {})},
    )

    summary = summarize_exceptions(result["anomalies"])
    if _should_call_llm(generate_llm_summary):
        cooperate(job_id, application_id)
        touch_progress(application_id, "Generating LLM reviewer summary")
        llm_summary = generate_explanation(result["anomalies"], ground_truth, application_id)
        summary = llm_summary or summary
        touch_progress(application_id, "LLM reviewer summary complete")
    if summary:
        _save_llm_summary(application_id, summary)
    # --- fx-schema: persist bilingual ops summaries ---
    generate_summaries(application_id, {"findings": result["anomalies"], "ground_truth": ground_truth})

    if mapped_result is not None:
        reviewer_summary = build_reviewer_summary(
            total_pages=len(pages),
            anomalies=result["anomalies"],
            checked_fields=int(mapped_result["checked_fields"]),
            matched_fields=int(mapped_result["matched_fields"]),
        )
        reviewer_summary["people_verification"] = mapped_result["people_verification"]
        reviewer_summary["source_classifications"] = mapped_result["source_classifications"]
        reviewer_summary["automatic_document_index"] = mapped_result.get(
            "automatic_document_index", []
        )
        reviewer_summary["unclassified_pages"] = mapped_result.get("unclassified_pages", [])
        reviewer_summary["evidence_resolution"] = mapped_result.get("evidence_resolution", {})
        reviewer_summary["trusted_reconciliation"] = trusted_reconciliation
        save_reviewer_summary(application_id, reviewer_summary)

    report_path = save_report_json(
        build_report(
            application_id=application_id,
            loan_id=str(ground_truth.get("loan_id") or ""),
            exceptions=result["anomalies"],
            llm_summary=summary or "",
            metadata=(
                {
                    "verification_mode": (
                        "automatic_json_comparison"
                        if "automatic_document_index" in mapped_result
                        else "mapped_zip_json_comparison"
                    ),
                    "checked_fields": mapped_result["checked_fields"],
                    "matched_fields": mapped_result["matched_fields"],
                    "people_verification": mapped_result["people_verification"],
                    "source_classifications": mapped_result["source_classifications"],
                    "automatic_document_index": mapped_result.get("automatic_document_index", []),
                    "unclassified_pages": mapped_result.get("unclassified_pages", []),
                    "evidence_resolution": mapped_result.get("evidence_resolution", {}),
                    "trusted_reconciliation": trusted_reconciliation,
                    "checklist_verification": checklist_verification.model_dump(mode="json"),
                }
                if mapped_result is not None
                else {
                    "trusted_reconciliation": trusted_reconciliation,
                    "checklist_verification": checklist_verification.model_dump(mode="json"),
                }
            ),
        )
    )

    result.update(
        {
            "application_id": application_id,
            "pipeline_status": pipeline_status,
            "partial_failure_count": len(processing_error_anomalies),
            "llm_summary": summary,
            "report_path": str(report_path),
            "ocr_json_path": None,
            "verification_report": (
                verification_report.model_dump(mode="json")
                if verification_report is not None
                else None
            ),
            "checklist_verification": checklist_verification.model_dump(mode="json"),
            "trusted_reconciliation": trusted_reconciliation,
        }
    )
    if mapped_result is not None:
        result.update(
            {
                "verification_mode": (
                    "automatic_json_comparison"
                    if "automatic_document_index" in mapped_result
                    else "mapped_zip_json_comparison"
                ),
                "checked_fields": mapped_result["checked_fields"],
                "matched_fields": mapped_result["matched_fields"],
                "observations": mapped_result["observations"],
                "people_verification": mapped_result["people_verification"],
                "source_classifications": mapped_result["source_classifications"],
                "automatic_document_index": mapped_result.get("automatic_document_index", []),
                "unclassified_pages": mapped_result.get("unclassified_pages", []),
                "evidence_resolution": mapped_result.get("evidence_resolution", {}),
            }
        )
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
            "partial_failure_count": len(processing_error_anomalies),
            "report_path": str(report_path),
        },
    )
    result["actionable_anomaly_count"] = actionable_count
    return result
