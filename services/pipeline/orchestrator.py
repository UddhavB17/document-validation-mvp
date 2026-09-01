"""Top-level PDF validation pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.checklist_output import build_checklist_verification_response
from services.exception_aggregator import aggregate
from services.llm_service import generate_explanation, summarize_exceptions
from services.pipeline.anomalies import _collect_pipeline_anomalies, _pipeline_outcome
from services.pipeline.finalization import (
    _add_pipeline_result_metadata,
    _complete_pipeline,
    _mapped_report_metadata,
    _save_mapped_reviewer_summary,
)
from services.pipeline.input_preparation import (
    _checklist_processing_metadata,
    _handle_unsupported_input,
    _persist_pipeline_outputs,
    _prepare_pdf_input,
    _source_page_starts,
)
from services.pipeline.page_processing import _build_page_records
from services.pipeline.persistence import _save_llm_summary, _should_call_llm
from services.pipeline.verification import _verify_pipeline_documents
from services.progress_tracker import update_stage
from services.report_generator import build_report, save_report_json


def run_pipeline(
    pdf_path: str | Path,
    application_id: int,
    output_dir: str | Path = "data/processed",
    system_data: dict[str, Any] | None = None,
    product_type: str = "LAP",
    generate_llm_summary: bool | None = None,
    mapped_manifest: dict[str, Any] | None = None,
    source_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Process one uploaded loan-file PDF and persist validation results."""
    pdf_path = Path(pdf_path)
    structure, digital_text_by_page, ground_truth, input_classification = _prepare_pdf_input(
        pdf_path=pdf_path,
        application_id=application_id,
        output_dir=output_dir,
        system_data=system_data,
        mapped_manifest=mapped_manifest,
    )

    unsupported_result = _handle_unsupported_input(
        application_id=application_id,
        structure=structure,
        digital_text_by_page=digital_text_by_page,
        ground_truth=ground_truth,
        input_classification=input_classification,
        mapped_manifest=mapped_manifest,
        generate_llm_summary=generate_llm_summary,
    )
    if unsupported_result is not None:
        return unsupported_result

    update_stage(application_id, "processing_pages", "Classifying and extracting page fields")
    source_page_starts = _source_page_starts(source_documents, mapped_manifest)
    pages = _build_page_records(
        structure["pages"],
        digital_text_by_page,
        application_id=application_id,
        source_page_starts=source_page_starts,
        source_documents=source_documents,
    )
    mapped_result, verification_report, document_page_numbers = _verify_pipeline_documents(
        pdf_path=pdf_path,
        application_id=application_id,
        pages=pages,
        ground_truth=ground_truth,
        mapped_manifest=mapped_manifest,
        source_documents=source_documents,
    )
    progress_snapshot, ocr_json_path = _persist_pipeline_outputs(
        application_id=application_id,
        output_dir=output_dir,
        structure=structure,
        ground_truth=ground_truth,
        pages=pages,
        document_page_numbers=document_page_numbers,
        verification_report=verification_report,
    )

    anomalies, processing_error_anomalies = _collect_pipeline_anomalies(
        application_id=application_id,
        pages=pages,
        ground_truth=ground_truth,
        system_data=system_data,
        product_type=product_type,
        mapped_result=mapped_result,
    )
    result = aggregate(pages, anomalies, ground_truth, application_id=application_id)
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

    summary = summarize_exceptions(result["anomalies"])
    if _should_call_llm(generate_llm_summary):
        llm_summary = generate_explanation(result["anomalies"], ground_truth, application_id)
        summary = llm_summary or summary
    if summary:
        _save_llm_summary(application_id, summary)

    _save_mapped_reviewer_summary(
        application_id=application_id,
        total_pages=len(pages),
        anomalies=result["anomalies"],
        mapped_result=mapped_result,
    )

    report_path = save_report_json(
        build_report(
            application_id=application_id,
            loan_id=str(ground_truth.get("loan_id") or ""),
            exceptions=result["anomalies"],
            llm_summary=summary or "",
            metadata=_mapped_report_metadata(mapped_result, checklist_verification),
        )
    )

    _add_pipeline_result_metadata(
        result=result,
        application_id=application_id,
        pipeline_status=pipeline_status,
        partial_failure_count=len(processing_error_anomalies),
        summary=summary,
        report_path=report_path,
        ocr_json_path=ocr_json_path,
        verification_report=verification_report,
        checklist_verification=checklist_verification,
        mapped_result=mapped_result,
    )
    _complete_pipeline(
        application_id=application_id,
        result=result,
        pipeline_status=pipeline_status,
        partial_failure_count=len(processing_error_anomalies),
        report_path=report_path,
    )
    return result
