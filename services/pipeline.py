"""End-to-end PDF validation pipeline.

This module connects the existing phase services into one upload-time flow:
PDF structure detection, text/OCR extraction, page classification, field
extraction, checklist checks, exception aggregation, and report persistence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import fitz

from database.db import get_connection
from services.audit_service import log_action
from services.checklist_engine import build_anomaly, run_checks
from services.config import effective_config
from services.document_classifier import classify_page
from services.exception_aggregator import aggregate
from services.field_extractor import extract_fields
from services.input_classifier import classify_input_text
from services.llm_service import generate_explanation, summarize_exceptions
from services.page_classification import classify_page_text, create_llm_classifier_budget
from services.ocr_engine import run_ocr_on_page
from services.pdf_processor import process_pdf_structure
from services.progress_tracker import (
    mark_completed,
    mark_page_started,
    start_tracking,
    update_page_progress,
    update_stage,
)
from services.report_generator import build_report, save_report_json
from services.text_extractor import extract_digital_text, extract_ground_truth


DOCUMENT_TYPE_ALIASES = {
    "PAN Card": "PAN",
    "None": "Unknown",
}


def run_pipeline(
    pdf_path: str | Path,
    application_id: int,
    output_dir: str | Path = "data/processed",
    system_data: dict[str, Any] | None = None,
    product_type: str = "LAP",
    generate_llm_summary: bool | None = None,
) -> dict[str, Any]:
    """Process one uploaded loan-file PDF and persist validation results."""
    pdf_path = Path(pdf_path)
    application_output_dir = Path(output_dir) / f"application_{application_id}"
    image_output_dir = application_output_dir / "pages"

    structure = process_pdf_structure(pdf_path, image_output_dir)
    start_tracking(
        application_id,
        total_pages=int(structure.get("total_pages") or 0),
        digital_pages=int(structure.get("digital_pages") or 0),
        scanned_pages=int(structure.get("scanned_pages") or 0),
        stage="structure_processed",
        message="PDF structure extracted",
    )
    update_stage(application_id, "extracting_digital_text", "Extracting digital text")
    digital_text_by_page = _extract_digital_text_by_page(pdf_path)
    ground_truth = dict(extract_ground_truth(pdf_path))
    if system_data:
        ground_truth = {**system_data, **{key: value for key, value in ground_truth.items() if value}}

    input_classification = classify_input_text(digital_text_by_page)
    if input_classification["input_type"] == "unsupported":
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

    update_stage(application_id, "processing_pages", "Classifying and extracting page fields")
    pages = _build_page_records(structure["pages"], digital_text_by_page, application_id=application_id)
    update_stage(application_id, "persisting_outputs", "Saving extracted data")
    _save_ground_truth(application_id, ground_truth)
    _save_pages(application_id, pages)
    _update_uploaded_file_counts(application_id, structure)

    update_stage(application_id, "running_checklist", "Running validation checks")
    anomalies = _run_checklist_with_fallback(pages, ground_truth, system_data, product_type)
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
    result = aggregate(pages, anomalies, ground_truth, application_id=application_id)
    pipeline_status = _pipeline_outcome(result["anomalies"], processing_error_anomalies)

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
            "partial_failure_count": len(processing_error_anomalies),
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
            "partial_failure_count": len(processing_error_anomalies),
            "report_path": str(report_path),
        },
    )
    return result


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
            "partial_failure_count": 0,
            "llm_summary": summary,
            "report_path": str(report_path),
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


def _extract_digital_text_by_page(pdf_path: Path) -> dict[int, str]:
    doc = fitz.open(pdf_path)
    try:
        return {
            page_number: text
            for page_number, page in enumerate(doc, start=1)
            if (text := extract_digital_text(page))
        }
    finally:
        doc.close()


def _build_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
    application_id: int | None = None,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    llm_budget = create_llm_classifier_budget()
    total_pages = len(page_structure)
    processing_order = sorted(
        page_structure,
        key=lambda item: (item.get("page_type") != "digital", int(item.get("page_number") or 0)),
    )
    for page_info in processing_order:
        page_number = int(page_info["page_number"])
        page_type = page_info["page_type"]
        image_path = page_info.get("image_path")
        if application_id is not None:
            mark_page_started(
                application_id,
                current_page=page_number,
                total_pages=total_pages,
                message=f"Processing page {page_number}/{total_pages}",
            )

        try:
            if page_type == "digital":
                text = digital_text_by_page.get(page_number, "")
                is_readable = bool(text)
                ocr_confidence = None
            else:
                ocr_result = run_ocr_on_page(image_path or "")
                text = ocr_result.get("ocr_text", "")
                is_readable = ocr_result.get("is_readable", False)
                ocr_confidence = ocr_result.get("confidence", 0.0)

            classification, classification_meta = classify_page_text(
                text,
                ocr_confidence=ocr_confidence,
                llm_budget=llm_budget,
            )
            document_type = _normalize_document_type(classification.get("document_type"))
            extracted_fields = extract_fields(document_type, text)
            if classification_meta:
                extracted_fields = {
                    **extracted_fields,
                    "_classification": classification_meta,
                }
        except Exception as exc:  # noqa: BLE001
            text = ""
            is_readable = False
            ocr_confidence = 0.0
            document_type = "Unknown"
            classification = {"confidence": 0.0}
            extracted_fields = {"_processing_error": str(exc)}

        pages.append(
            {
                "page_number": page_number,
                "page_type": page_type,
                "image_path": image_path,
                "is_readable": is_readable,
                "ocr_text": text,
                "ocr_confidence": ocr_confidence,
                "document_type": document_type,
                "classification_confidence": classification.get("confidence", 0.0),
                "extracted_fields": extracted_fields,
            }
        )
        if application_id is not None:
            update_page_progress(
                application_id,
                processed_pages=len(pages),
                total_pages=total_pages,
                current_page=page_number,
            )
    return sorted(pages, key=lambda item: int(item.get("page_number") or 0))


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
                "extracted_fields": extracted_fields,
            }
        )
    return pages


def _build_unsupported_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
) -> list[dict[str, Any]]:
    return [
        {
            "page_number": int(page_info["page_number"]),
            "page_type": page_info["page_type"],
            "image_path": page_info.get("image_path"),
            "is_readable": bool(digital_text_by_page.get(int(page_info["page_number"]), "")),
            "ocr_text": digital_text_by_page.get(int(page_info["page_number"]), ""),
            "ocr_confidence": None,
            "document_type": "Unknown",
            "classification_confidence": 0.0,
            "extracted_fields": {},
        }
        for page_info in page_structure
    ]


def _coerce_partner_doc(doc_key: str, value: Any) -> tuple[str, str | None, dict[str, Any], float]:
    if isinstance(value, dict):
        text = str(value.get("text") or value.get("ocr_text") or value.get("raw_text") or "")
        document_type = value.get("document_type") or _document_type_from_key(doc_key)
        extracted_fields = value.get("extracted_fields") or value.get("fields") or {}
        confidence = float(value.get("confidence") or value.get("ocr_confidence") or 1.0)
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
        "cibil": "CRIF Report",
        "bank_statement": "Bank Statement",
        "salary_slip": "Salary Slip",
        "sanction_letter": "Sanction Letter",
        "loan_agreement": "Loan Agreement",
        "application_form": "Application Form",
    }
    return aliases.get(normalized)


def _normalize_document_type(document_type: str | None) -> str:
    if not document_type:
        return "Unknown"
    return DOCUMENT_TYPE_ALIASES.get(document_type, document_type)


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
                found_value=str(extracted_fields.get("_processing_error") or "Unknown processing error"),
                reason="OCR, classification, or field extraction failed for this page.",
                page_number=page.get("page_number"),
                document_type=page.get("document_type"),
            )
        )
    return anomalies


def _pipeline_outcome(anomalies: list[dict[str, Any]], processing_errors: list[dict[str, Any]]) -> str:
    if len(processing_errors) >= effective_config().page_failure_threshold:
        return "failed"
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


def _save_ground_truth(application_id: int, ground_truth: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM ground_truth WHERE application_id = ?", (application_id,))
        connection.execute(
            """
            INSERT INTO ground_truth (
                application_id,
                applicant_name,
                pan_number,
                loan_amount,
                phone,
                address,
                product_type,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                ground_truth.get("applicant_name"),
                ground_truth.get("pan_number"),
                ground_truth.get("loan_amount"),
                ground_truth.get("phone"),
                ground_truth.get("address"),
                ground_truth.get("product_type"),
                json.dumps(ground_truth, ensure_ascii=False),
            ),
        )


def _save_pages(application_id: int, pages: list[dict[str, Any]]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM pages WHERE application_id = ?", (application_id,))
        for page in pages:
            connection.execute(
                """
                INSERT INTO pages (
                    application_id,
                    page_number,
                    page_type,
                    image_path,
                    is_readable,
                    ocr_text,
                    ocr_confidence,
                    document_type,
                    classification_confidence,
                    extracted_fields
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    page.get("page_number"),
                    page.get("page_type"),
                    page.get("image_path"),
                    bool(page.get("is_readable")),
                    page.get("ocr_text"),
                    page.get("ocr_confidence"),
                    page.get("document_type"),
                    page.get("classification_confidence"),
                    json.dumps(page.get("extracted_fields") or {}, ensure_ascii=False),
                ),
            )


def _update_uploaded_file_counts(application_id: int, structure: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE uploaded_files
            SET total_pages = ?, digital_pages = ?, scanned_pages = ?
            WHERE application_id = ?
            """,
            (
                structure.get("total_pages"),
                structure.get("digital_pages"),
                structure.get("scanned_pages"),
                application_id,
            ),
        )


def _should_call_llm(generate_llm_summary: bool | None) -> bool:
    if generate_llm_summary is not None:
        return generate_llm_summary
    return os.getenv("ENABLE_LLM_SUMMARY", "").lower() in {"1", "true", "yes", "on"}


def _save_llm_summary(application_id: int, summary: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE applications SET llm_summary = ? WHERE id = ?",
            (summary, application_id),
        )
