"""Partner-supplied JSON validation pipeline."""

from __future__ import annotations

from typing import Any

from services.audit_service import log_action
from services.checklist_output import build_checklist_verification_response
from services.document_classifier import classify_page
from services.exception_aggregator import aggregate
from services.field_extractor import extract_fields
from services.llm_service import generate_explanation, summarize_exceptions
from services.pipeline.anomalies import _pipeline_outcome, _run_checklist_with_fallback
from services.pipeline.classification import _normalize_document_type, _smooth_page_classifications
from services.pipeline.persistence import (
    _save_ground_truth,
    _save_llm_summary,
    _save_pages,
    _should_call_llm,
)
from services.progress_tracker import (
    mark_completed,
    start_tracking,
    update_page_progress,
    update_stage,
)
from services.report_generator import build_report, save_report_json


def run_partner_json_pipeline(
    payload: dict[str, Any],
    application_id: int,
    system_data: dict[str, Any] | None = None,
    product_type: str = "LAP",
    generate_llm_summary: bool | None = False,
) -> dict[str, Any]:
    """Run checklist validation from partner-supplied OCR/extraction JSON."""
    ground_truth = {
        **(system_data or {}),
        **(payload.get("digital_text") or {}),
    }
    pages = _build_partner_pages(payload.get("scanned_docs") or {})
    start_tracking(
        application_id,
        total_pages=len(pages),
        digital_pages=0,
        scanned_pages=len(pages),
        stage="processing_partner_json",
        message="Processing partner supplied JSON",
    )
    update_page_progress(
        application_id,
        processed_pages=len(pages),
        total_pages=len(pages),
        current_page=len(pages) if pages else None,
    )

    update_stage(application_id, "persisting_outputs", "Saving extracted data")
    _save_ground_truth(application_id, ground_truth)
    _save_pages(application_id, pages)

    update_stage(application_id, "running_checklist", "Running validation checks")
    anomalies = _run_checklist_with_fallback(pages, ground_truth, system_data, product_type)
    result = aggregate(pages, anomalies, ground_truth, application_id=application_id)
    pipeline_status = _pipeline_outcome(result["anomalies"], [])
    checklist_verification = build_checklist_verification_response(
        loan_file_id=str(ground_truth.get("loan_id") or application_id),
        pages=pages,
        anomalies=anomalies,
        product_type=product_type,
        system_data={**ground_truth, **(system_data or {})},
        processing_metadata={},
        include_narration=False,
    )
    from services.trusted_reconciliation import build_trusted_reconciliation

    trusted_reconciliation = build_trusted_reconciliation(
        pages,
        {**ground_truth, **(system_data or {})},
    )

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
            metadata={
                "trusted_reconciliation": trusted_reconciliation,
                "checklist_verification": checklist_verification.model_dump(mode="json"),
            },
        )
    )
    result.update(
        {
            "application_id": application_id,
            "pipeline_status": pipeline_status,
            "partial_failure_count": 0,
            "llm_summary": summary,
            "report_path": str(report_path),
            "checklist_verification": checklist_verification.model_dump(mode="json"),
            "trusted_reconciliation": trusted_reconciliation,
        }
    )
    mark_completed(application_id, result["final_status"], pipeline_status)
    log_action(
        application_id,
        "partner_json_pipeline_completed",
        {
            "anomaly_count": len(result["anomalies"]),
            "final_status": result["final_status"],
            "report_path": str(report_path),
        },
    )
    return result


def _build_partner_pages(scanned_docs: dict[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_number, (doc_key, value) in enumerate(scanned_docs.items(), start=1):
        text, document_type, extracted_fields, confidence = _coerce_partner_doc(doc_key, value)
        if not document_type:
            classification = classify_page(text)
            document_type = _normalize_document_type(classification.get("document_type"))
            confidence = classification.get("confidence", confidence)
        else:
            document_type = _normalize_document_type(document_type)

        if not extracted_fields:
            extracted_fields = extract_fields(document_type, text)

        pages.append(
            {
                "page_number": page_number,
                "page_type": "scanned",
                "image_path": None,
                "is_readable": bool(text),
                "ocr_text": text,
                "ocr_confidence": confidence,
                "document_type": document_type,
                "classification_confidence": confidence,
                "detection_method": "detected",
                "detected_page_number": page_number,
                "extracted_fields": extracted_fields,
            }
        )
    pages = _smooth_page_classifications(pages, None, len(pages))
    return pages


def _coerce_partner_doc(doc_key: str, value: Any) -> tuple[str, str | None, dict[str, Any], float]:
    if isinstance(value, dict):
        text = str(value.get("text") or value.get("ocr_text") or value.get("raw_text") or "")
        document_type = value.get("document_type") or _document_type_from_key(doc_key)
        extracted_fields = value.get("extracted_fields") or value.get("fields") or {}
        confidence = value.get("confidence")
        if confidence is None:
            confidence = value.get("ocr_confidence")
        confidence = float(confidence) if confidence is not None else 1.0
        return text, document_type, extracted_fields, confidence
    return str(value or ""), _document_type_from_key(doc_key), {}, 1.0


def _document_type_from_key(doc_key: str) -> str | None:
    normalized = doc_key.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "pan": "PAN",
        "pan_card": "PAN",
        "aadhaar": "Aadhaar",
        "aadhar": "Aadhaar",
        "voter_id": "Voter ID",
        "driving_license": "Driving License",
        "driving_licence": "Driving License",
        "crif": "CRIF Report",
        "crif_report": "CRIF Report",
        "cibil": "CIBIL Report",
        "cibil_report": "CIBIL Report",
        "cersai": "CERSAI Report",
        "cersai_report": "CERSAI Report",
        "cheque": "Cheque",
        "check": "Cheque",
        "cancelled_cheque": "Cheque",
        "canceled_check": "Cheque",
        "bank_statement": "Bank Statement",
        "passbook": "Passbook",
        "pass_book": "Passbook",
        "salary_slip": "Salary Slip",
        "sanction_letter": "Sanction Letter",
        "loan_agreement": "Loan Agreement",
        "application_form": "Application Form",
    }
    return aliases.get(normalized)
