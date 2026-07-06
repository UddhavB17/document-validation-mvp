"""End-to-end PDF validation pipeline.

This module connects the existing phase services into one upload-time flow:
PDF structure detection, text/OCR extraction, page classification, field
extraction, checklist checks, exception aggregation, and report persistence.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz

from database.db import get_connection
from database.models import DocumentVerificationReport
from services.audit_service import log_action
from services.checklist_engine import build_anomaly, run_checks
from services.classification_review_log import log_classification_review_event
from services.content_triage import triage_page_content
from services.document_classifier import HIGH_CONFIDENCE, classify_page
from services.exception_aggregator import aggregate
from services.field_assignment_refiner import refine_field_assignments
from services.field_verification import verify_all_fields
from services.field_extractor import extract_fields
from services.input_classifier import classify_input_text
from services.llm_service import generate_explanation, summarize_exceptions
from services.ocr_json_export import merge_public_extracted_fields, save_ocr_document_json
from services.page_classification import classify_page_text, create_llm_classifier_budget
from services.ocr_engine import run_ocr_on_page
from services.pdf_processor import process_pdf_structure
from services.processing_policy import (
    OCR_SKIPPED_DOCUMENT_TYPE,
    build_ocr_skipped_fields,
    max_scanned_pages_for_ocr,
    selected_scanned_page_numbers,
)
from services.progress_tracker import (
    get_progress,
    mark_completed,
    mark_page_started,
    record_page_completed,
    start_tracking,
    update_page_progress,
    update_stage,
)
from services.report_generator import build_report, save_report_json
from services.structured_llm_classifier import classify_with_structured_llm
from services.text_extractor import extract_digital_text, extract_ground_truth
from services.verification_pdf_parser import VerificationPdfParseError, parse_verification_pdf
from services.verification_report_store import save_verification_report

try:  # pragma: no cover - exercised when rapidfuzz is available
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - fallback keeps the pipeline dependency-light
    fuzz = None


DOCUMENT_TYPE_ALIASES = {
    "PAN Card": "PAN",
    "None": "Unknown",
}

logger = logging.getLogger("dmef.pipeline")
_LOGGING_CONFIGURED = False


def _ensure_pipeline_logging() -> None:
    global _LOGGING_CONFIGURED
    if not _LOGGING_CONFIGURED and not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
            force=False,
        )
        _LOGGING_CONFIGURED = True
    logger.setLevel(logging.INFO)


def _log_page_phase_start(page_number: int, total_pages: int, phase: str) -> float:
    _ensure_pipeline_logging()
    logger.info("[Page %s/%s] Phase: %-22s started", page_number, total_pages, phase)
    _flush_log_handlers()
    return time.perf_counter()


def _log_page_phase_done(page_number: int, total_pages: int, phase: str, started_at: float) -> None:
    elapsed = time.perf_counter() - started_at
    logger.info("[Page %s/%s] Phase: %-22s done in %.2fs", page_number, total_pages, phase, elapsed)
    _flush_log_handlers()


def _log_page_phase_failed(page_number: int, total_pages: int, phase: str, started_at: float, exc: Exception) -> None:
    elapsed = time.perf_counter() - started_at
    logger.exception(
        "[Page %s/%s] Phase: %-22s failed in %.2fs: %s",
        page_number,
        total_pages,
        phase,
        elapsed,
        exc,
    )
    _flush_log_handlers()


def _log_total_page_time(page_number: int, total_pages: int, started_at: float) -> float:
    elapsed = time.perf_counter() - started_at
    logger.info("[Page %s/%s] Total page time: %.2fs", page_number, total_pages, elapsed)
    _flush_log_handlers()
    return elapsed


def _flush_log_handlers() -> None:
    for handler in logger.handlers + logging.getLogger().handlers:
        handler.flush()


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
    update_stage(application_id, "verifying_documents", "Comparing OCR fields with Graviton data")
    verification_report, document_page_numbers = _run_document_verification(pdf_path, application_id, pages)
    update_stage(application_id, "persisting_outputs", "Saving extracted data")
    _save_ground_truth(application_id, ground_truth)
    _save_pages(application_id, pages)
    progress_snapshot = get_progress(application_id) or {}
    ocr_json_path = save_ocr_document_json(
        application_id,
        pages,
        output_dir=output_dir,
        document_page_numbers=document_page_numbers,
        page_events=progress_snapshot.get("completed_pages") or [],
    )
    if verification_report is not None:
        save_verification_report(application_id, verification_report)
    _update_uploaded_file_counts(application_id, structure)

    update_stage(application_id, "running_checklist", "Running validation checks")
    anomalies = _run_checklist_with_fallback(pages, ground_truth, system_data, product_type)
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
            "ocr_json_path": str(ocr_json_path),
            "verification_report": (
                verification_report.model_dump(mode="json")
                if verification_report is not None
                else None
            ),
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
    selected_scanned_pages = selected_scanned_page_numbers(page_structure)
    total_scanned_pages = sum(1 for page in page_structure if page.get("page_type") == "scanned")
    processing_order = sorted(page_structure, key=lambda item: int(item.get("page_number") or 0))
    current_type = "Unknown"
    current_confidence = 0.0
    current_detected_page: int | None = None

    for page_info in processing_order:
        page_started_at = time.perf_counter()
        phase_started_at: float | None = None
        phase_name = "page processing"
        page_status = "completed"
        page_error: str | None = None
        page_number = int(page_info["page_number"])
        page_type = page_info["page_type"]
        image_path = page_info.get("image_path")
        needs_ocr = page_type == "scanned" and page_number in selected_scanned_pages
        if application_id is not None:
            mark_page_started(
                application_id,
                current_page=page_number,
                total_pages=total_pages,
                message=f"Working on page {page_number}/{total_pages}",
            )

        try:
            extracted_fields: dict[str, Any] = {}
            phase_name = "page load"
            phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
            if page_type == "digital":
                text = digital_text_by_page.get(page_number, "")
                is_readable = bool(text)
                ocr_confidence = None
                ocr_metadata = {}
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
            elif page_number not in selected_scanned_pages:
                text = ""
                is_readable = None
                ocr_confidence = None
                document_type = OCR_SKIPPED_DOCUMENT_TYPE
                classification = {"confidence": 1.0}
                extracted_fields = build_ocr_skipped_fields(page_number, total_scanned_pages)
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                skipped_page = {
                    "page_number": page_number,
                    "page_type": page_type,
                    "image_path": image_path,
                    "is_readable": is_readable,
                    "ocr_text": text,
                    "ocr_confidence": ocr_confidence,
                    "document_type": document_type,
                    "classification_confidence": classification.get("confidence", 0.0),
                    "detection_method": "skipped",
                    "detected_page_number": None,
                    "extracted_fields": extracted_fields,
                }
                pages.append(skipped_page)
                page_elapsed = _log_total_page_time(page_number, total_pages, page_started_at)
                _record_completed_page_event(
                    application_id,
                    page=skipped_page,
                    total_pages=total_pages,
                    elapsed_seconds=page_elapsed,
                    status="skipped",
                )
                if application_id is not None:
                    update_page_progress(
                        application_id,
                        processed_pages=len(pages),
                        total_pages=total_pages,
                        current_page=page_number,
                        message=(
                            f"Processed {len(pages)}/{total_pages} pages "
                            f"(OCR budget skip)"
                        ),
                    )
                continue
            else:
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                phase_name = "OCR (PaddleOCR)"
                phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
                ocr_result = run_ocr_on_page(image_path or "")
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                text = ocr_result.get("ocr_text", "")
                is_readable = ocr_result.get("is_readable", False)
                ocr_confidence = ocr_result.get("confidence", 0.0)
                ocr_metadata = dict(ocr_result)
                extracted_fields = {}
                if ocr_result.get("error"):
                    extracted_fields["_processing_error"] = str(ocr_result["error"])

            phase_name = "content triage"
            phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
            triage = triage_page_content(
                page_type=page_type,
                text=text,
                ocr_confidence=ocr_confidence,
                ocr_metadata=ocr_metadata,
            )
            _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)

            if triage["category"] == "photo":
                document_type = "Property Image"
                classification = {"confidence": triage["confidence"]}
                extracted_fields = {
                    **extracted_fields,
                    "content_category": "property_image",
                    "_triage": triage,
                    "_classification": {
                        "source": "triage",
                        "assigned_type": document_type,
                        "detection_method": "triage_photo",
                        "raw_document_type": document_type,
                        "raw_confidence": triage["confidence"],
                        "detected_page_number": page_number,
                    },
                }
            elif triage["category"] == "handwritten" and (ocr_confidence is None or float(ocr_confidence) < 0.70):
                document_type = "Unknown"
                classification = {"confidence": 0.0}
                extracted_fields = {
                    **extracted_fields,
                    "review_flag": "low_confidence_needs_review",
                    "_triage": triage,
                    "_classification": {
                        "source": "triage",
                        "assigned_type": document_type,
                        "detection_method": "triage_low_confidence",
                        "raw_document_type": document_type,
                        "raw_confidence": 0.0,
                        "detected_page_number": None,
                    },
                }
                log_classification_review_event(
                    application_id=application_id,
                    page_number=page_number,
                    predicted_type=document_type,
                    confidence=0.0,
                    reason="low_confidence_needs_review",
                    anchor_match_results={"triage": triage},
                )
            else:
                phase_name = "classification"
                _mark_page_phase(application_id, page_number, total_pages, "classifying document")
                phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
                classification, classification_meta = classify_page_text(
                    text,
                    ocr_confidence=ocr_confidence,
                    layout_metadata=ocr_metadata,
                    llm_budget=llm_budget,
                )
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                assigned = _assign_sequential_document_type(
                    page_number=page_number,
                    text=text,
                    classification=classification,
                    current_type=current_type,
                    current_confidence=current_confidence,
                    current_detected_page=current_detected_page,
                )
                document_type = assigned["document_type"]
                classification = {"confidence": assigned["confidence"]}
                if assigned["detection_method"] == "detected":
                    current_type = document_type
                    current_confidence = float(assigned["confidence"] or 0.0)
                    current_detected_page = page_number
                phase_name = "field extraction"
                _mark_page_phase(application_id, page_number, total_pages, "extracting fields")
                phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
                extracted_fields = {**extracted_fields, **extract_fields(document_type, text)}
                extracted_fields = refine_field_assignments(
                    document_type=document_type,
                    ocr_text=text,
                    extracted_fields=extracted_fields,
                )
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                classification_meta = {
                    **classification_meta,
                    "assigned_type": document_type,
                    "detection_method": assigned["detection_method"],
                    "raw_document_type": assigned["raw_document_type"],
                    "raw_confidence": assigned["raw_confidence"],
                    "detected_page_number": assigned["detected_page_number"],
                    "triage": triage,
                }
                if assigned.get("inheritance_warning"):
                    classification_meta["inheritance_warning"] = assigned["inheritance_warning"]
                if assigned.get("abstain_reason"):
                    classification_meta["abstain_reason"] = assigned["abstain_reason"]
                if classification_meta:
                    extracted_fields = {
                        **extracted_fields,
                        "_classification": classification_meta,
                    }
                _mark_page_phase(application_id, page_number, total_pages, "checking Ollama classification")
                structured_llm_result = classify_with_structured_llm(
                    deterministic_document_type=document_type,
                    structured_fields=extracted_fields,
                    ocr_text=text,
                )
                if structured_llm_result:
                    extracted_fields["_structured_llm_classification"] = structured_llm_result
                    if structured_llm_result.get("document_type") != document_type:
                        log_classification_review_event(
                            application_id=application_id,
                            page_number=page_number,
                            predicted_type=document_type,
                            confidence=float(classification.get("confidence") or 0.0),
                            reason="structured_llm_disagreement",
                            anchor_match_results={
                                "deterministic_document_type": document_type,
                                "structured_llm_document_type": structured_llm_result.get("document_type"),
                                "structured_llm_confidence": structured_llm_result.get("confidence"),
                                "structured_llm_reason": structured_llm_result.get("reason"),
                            },
                            llm_document_type=str(structured_llm_result.get("document_type") or ""),
                        )
                _log_classification_review_if_needed(
                    application_id=application_id,
                    page_number=page_number,
                    document_type=document_type,
                    confidence=float(classification.get("confidence") or 0.0),
                    metadata=classification_meta,
                )
        except Exception as exc:  # noqa: BLE001
            if phase_started_at is not None:
                _log_page_phase_failed(page_number, total_pages, phase_name, phase_started_at, exc)
            else:
                logger.exception("[Page %s/%s] Page processing failed: %s", page_number, total_pages, exc)
                _flush_log_handlers()
            page_status = "error"
            page_error = str(exc)
            text = ""
            is_readable = False
            ocr_confidence = 0.0
            document_type = "Unknown"
            classification = {"confidence": 0.0}
            extracted_fields = {
                "_processing_error": str(exc),
                "_classification": {
                    "assigned_type": "Unknown",
                    "detection_method": "unknown",
                    "raw_document_type": "Unknown",
                    "raw_confidence": 0.0,
                    "detected_page_number": None,
                },
            }

        completed_page = {
            "page_number": page_number,
            "page_type": page_type,
            "image_path": image_path,
            "is_readable": is_readable,
            "ocr_text": text,
            "ocr_confidence": ocr_confidence,
            "document_type": document_type,
            "classification_confidence": classification.get("confidence", 0.0),
            "detection_method": (
                extracted_fields.get("_classification", {}).get("detection_method")
                if isinstance(extracted_fields.get("_classification"), dict)
                else "detected"
            ),
            "detected_page_number": (
                extracted_fields.get("_classification", {}).get("detected_page_number")
                if isinstance(extracted_fields.get("_classification"), dict)
                else page_number
            ),
            "extracted_fields": extracted_fields,
        }
        pages.append(completed_page)
        page_elapsed = _log_total_page_time(page_number, total_pages, page_started_at)
        _record_completed_page_event(
            application_id,
            page=completed_page,
            total_pages=total_pages,
            elapsed_seconds=page_elapsed,
            status=page_status,
            error=page_error,
        )
        if application_id is not None:
            update_page_progress(
                application_id,
                processed_pages=len(pages),
                total_pages=total_pages,
                current_page=page_number,
                message=f"Processed {len(pages)}/{total_pages} pages",
            )
    if application_id is not None and pages:
        update_page_progress(
            application_id,
            processed_pages=len(pages),
            total_pages=total_pages,
            current_page=pages[-1]["page_number"],
            message=f"Processed {len(pages)}/{total_pages} pages",
        )
    return sorted(pages, key=lambda item: int(item.get("page_number") or 0))


def _record_completed_page_event(
    application_id: int | None,
    *,
    page: dict[str, Any],
    total_pages: int,
    elapsed_seconds: float,
    status: str,
    error: str | None = None,
) -> None:
    if application_id is None:
        return
    record_page_completed(
        application_id,
        page_number=int(page.get("page_number") or 0),
        total_pages=total_pages,
        page_type=page.get("page_type"),
        document_type=page.get("document_type"),
        elapsed_seconds=elapsed_seconds,
        extracted_fields=page.get("extracted_fields") or {},
        status=status,
        error=error,
    )


def _mark_page_phase(
    application_id: int | None,
    page_number: int,
    total_pages: int,
    phase: str,
) -> None:
    if application_id is None:
        return
    mark_page_started(
        application_id,
        current_page=page_number,
        total_pages=total_pages,
        message=f"Working on page {page_number}/{total_pages}: {phase}",
    )


def _log_classification_review_if_needed(
    *,
    application_id: int | None,
    page_number: int,
    document_type: str,
    confidence: float,
    metadata: dict[str, Any],
) -> None:
    anchor_type = metadata.get("anchor_document_type")
    llm_type = metadata.get("llm_document_type")
    anchor_matches = metadata.get("anchor_matches") or {}
    if anchor_type and llm_type and anchor_type != llm_type:
        log_classification_review_event(
            application_id=application_id,
            page_number=page_number,
            predicted_type=document_type,
            confidence=confidence,
            reason="anchor_llm_disagreement",
            anchor_match_results=anchor_matches,
            llm_document_type=str(llm_type),
        )
        return

    if confidence < 0.65:
        log_classification_review_event(
            application_id=application_id,
            page_number=page_number,
            predicted_type=document_type,
            confidence=confidence,
            reason="classification_confidence_below_threshold",
            anchor_match_results=anchor_matches,
            llm_document_type=str(llm_type) if llm_type else None,
        )


def _assign_sequential_document_type(
    *,
    page_number: int,
    text: str,
    classification: dict[str, Any],
    current_type: str,
    current_confidence: float,
    current_detected_page: int | None,
) -> dict[str, Any]:
    raw_type = _normalize_document_type(classification.get("document_type"))
    raw_confidence = float(classification.get("confidence") or 0.0)
    if raw_type != "Unknown" and raw_confidence >= HIGH_CONFIDENCE:
        return {
            "document_type": raw_type,
            "confidence": raw_confidence,
            "detection_method": "detected",
            "detected_page_number": page_number,
            "raw_document_type": raw_type,
            "raw_confidence": raw_confidence,
        }

    if current_type != "Unknown":
        if _looks_like_fresh_page_without_match(text):
            return {
                "document_type": "Unknown",
                "confidence": 0.0,
                "detection_method": "unknown",
                "detected_page_number": None,
                "raw_document_type": raw_type,
                "raw_confidence": raw_confidence,
                "abstain_reason": "fresh-page-like-no-match",
            }
        inherited_confidence = max(0.55, min(0.85, current_confidence * 0.85))
        return {
            "document_type": current_type,
            "confidence": round(inherited_confidence, 3),
            "detection_method": "inherited",
            "detected_page_number": current_detected_page,
            "raw_document_type": raw_type,
            "raw_confidence": raw_confidence,
            "inheritance_warning": None,
        }

    return {
        "document_type": "Unknown",
        "confidence": 0.0,
        "detection_method": "unknown",
        "detected_page_number": None,
        "raw_document_type": raw_type,
        "raw_confidence": raw_confidence,
    }


def _looks_like_fresh_page_without_match(text: str) -> bool:
    raw_text = text or ""
    header = " ".join(raw_text.splitlines()[:6])
    normalized_header = _normalize_fresh_document_text(header)
    normalized_text = _normalize_fresh_document_text(raw_text)
    if not normalized_text:
        return False

    generic_header_terms = (
        "certificate",
        "letter",
        "agreement",
        "deed",
        "report",
        "statement",
        "form",
        "application",
        "undertaking",
        "declaration",
    )
    if any(term in normalized_header for term in generic_header_terms):
        return True

    strong_terms = (
        "affidavit",
        "notary",
        "notarised",
        "notarized",
        "attested",
        "stamp paper",
        "non judicial",
        "non-judicial",
        "adhesive stamp",
        "gps map camera",
        "patta",
        "शपथ",
        "शपथ पत्र",
        "हलफनामा",
        "पट्टा",
        "प्रपत्र",
        "नोटरी",
        "स्टाम्प",
        "न्यायिक",
        "घोषणा",
        "अभियान",
    )
    if any(_normalize_fresh_document_text(term) in normalized_text for term in strong_terms):
        return True

    fuzzy_terms = ("शपथ", "हलफनामा", "पट्टा", "प्रपत्र", "नोटरी", "स्टाम्प", "न्यायिक", "घोषणा")
    return any(_fuzzy_contains(normalized_text, _normalize_fresh_document_text(term)) for term in fuzzy_terms)


def _normalize_fresh_document_text(value: str) -> str:
    normalized = str(value or "").lower()
    normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"[^0-9a-z\u0900-\u097f-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _fuzzy_contains(text: str, term: str, *, threshold: float = 0.85) -> bool:
    if not text or not term:
        return False
    if term in text:
        return True
    if fuzz is not None:
        return (float(fuzz.partial_ratio(term, text)) / 100.0) >= threshold

    term_length = len(term)
    if len(text) <= term_length:
        return SequenceMatcher(None, term, text).ratio() >= threshold
    best_ratio = 0.0
    for start in range(0, len(text) - term_length + 1):
        window = text[start : start + term_length]
        best_ratio = max(best_ratio, SequenceMatcher(None, term, window).ratio())
        if best_ratio >= threshold:
            return True
    return False


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
            "detection_method": "unknown",
            "detected_page_number": None,
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
        "cibil": "CIBIL Report",
        "cibil_report": "CIBIL Report",
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


def _ocr_budget_anomaly(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    scanned_pages = [page for page in pages if page.get("page_type") == "scanned"]
    skipped_pages = [page for page in scanned_pages if page.get("document_type") == OCR_SKIPPED_DOCUMENT_TYPE]
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


def _pipeline_outcome(anomalies: list[dict[str, Any]], processing_errors: list[dict[str, Any]]) -> str:
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


def _run_document_verification(
    pdf_path: Path,
    application_id: int,
    pages: list[dict[str, Any]],
) -> tuple[DocumentVerificationReport | None, set[int] | None]:
    try:
        graviton_record, document_pages = parse_verification_pdf(str(pdf_path))
    except VerificationPdfParseError as exc:
        log_action(
            application_id,
            "verification_skipped",
            {
                "reason": str(exc),
                "pdf_path": str(pdf_path),
            },
        )
        return None, None

    document_page_numbers = {int(page["page_number"]) for page in document_pages}
    document_only_pages = [
        page
        for page in pages
        if int(page.get("page_number") or 0) in document_page_numbers
    ]
    extracted_fields = merge_public_extracted_fields(document_only_pages)
    report = verify_all_fields(extracted_fields, graviton_record)
    log_action(
        application_id,
        "verification_completed",
        {
            "graviton_application_id": graviton_record.application_id,
            "document_page_count": len(document_pages),
            "overall_match": report.overall_match,
            "match_percentage": report.match_percentage,
            "needs_manual_review": report.needs_manual_review,
        },
    )
    return report, document_page_numbers


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
                    detection_method,
                    detected_page_number,
                    extracted_fields
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    page.get("page_number"),
                    page.get("page_type"),
                    page.get("image_path"),
                    page.get("is_readable") if page.get("is_readable") is not None else None,
                    page.get("ocr_text"),
                    page.get("ocr_confidence"),
                    page.get("document_type"),
                    page.get("classification_confidence"),
                    page.get("detection_method"),
                    page.get("detected_page_number"),
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
