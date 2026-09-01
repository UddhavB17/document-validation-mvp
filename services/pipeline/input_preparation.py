"""PDF input preparation and early pipeline setup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from database.models import DocumentVerificationReport
from services.audit_service import log_action
from services.checklist_engine import build_anomaly
from services.input_classifier import classify_input_text
from services.ocr_json_export import save_ocr_document_json
from services.pdf_processor import process_pdf_structure
from services.pipeline.finalization import _finalize_pipeline_result
from services.pipeline.page_details import _build_db_data_fields, _is_starting_json_db_page
from services.pipeline.persistence import _save_ground_truth, _save_pages, _update_uploaded_file_counts
from services.progress_tracker import get_progress, start_tracking, update_stage
from services.text_extractor import extract_digital_text, extract_ground_truth
from services.verification_report_store import save_verification_report


def _prepare_pdf_input(
    *,
    pdf_path: Path,
    application_id: int,
    output_dir: str | Path,
    system_data: dict[str, Any] | None,
    mapped_manifest: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[int, str], dict[str, Any], dict[str, Any]]:
    """Extract the PDF structure, digital text, and trusted input data."""
    application_output_dir = Path(output_dir) / f"application_{application_id}"
    structure = process_pdf_structure(pdf_path, application_output_dir / "pages")
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
    if mapped_manifest is not None:
        ground_truth = _mapped_ground_truth(mapped_manifest, system_data)
        if system_data is not None:
            system_data.setdefault("reference_data", ground_truth.get("reference_data"))
            system_data.setdefault("people", ground_truth.get("reference_data"))
    elif system_data:
        ground_truth = {
            **system_data,
            **{key: value for key, value in ground_truth.items() if value},
        }

    return structure, digital_text_by_page, ground_truth, classify_input_text(digital_text_by_page)


def _handle_unsupported_input(
    *,
    application_id: int,
    structure: dict[str, Any],
    digital_text_by_page: dict[int, str],
    ground_truth: dict[str, Any],
    input_classification: dict[str, Any],
    mapped_manifest: dict[str, Any] | None,
    generate_llm_summary: bool | None,
) -> dict[str, Any] | None:
    """Finalize unsupported PDFs early while preserving mapped-upload behavior."""
    if input_classification["input_type"] != "unsupported":
        return None

    if mapped_manifest is not None:
        log_action(application_id, "mapped_input_classifier_warning", input_classification)
        return None

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


def _source_page_starts(
    source_documents: list[dict[str, Any]] | None,
    mapped_manifest: dict[str, Any] | None,
) -> set[int]:
    """Collect page numbers that begin source documents in a package."""
    page_starts = {
        int(document["internal_page_start"])
        for document in source_documents or []
        if document.get("internal_page_start") is not None
    }
    if mapped_manifest is None:
        return page_starts

    pages_by_source: dict[str, list[int]] = {}
    for document in mapped_manifest.get("documents") or []:
        source_id = str(document.get("source_document_id") or "unassigned")
        pages_by_source.setdefault(source_id, []).extend(
            int(number) for number in document.get("pages") or []
        )
    page_starts.update(min(numbers) for numbers in pages_by_source.values() if numbers)
    return page_starts


def _mapped_ground_truth(
    manifest: dict[str, Any],
    system_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten primary trusted data for checklist/report compatibility."""
    reference_data = manifest.get("reference_data") or {}
    primary = reference_data.get("primary") if isinstance(reference_data, dict) else {}
    primary = primary if isinstance(primary, dict) else {}
    return {
        **{key: value for key, value in manifest.items() if key not in {"documents", "reference_data"}},
        **(system_data or {}),
        **primary,
        "loan_id": manifest.get("loan_id") or (system_data or {}).get("loan_id"),
        "product_type": manifest.get("product_type") or (system_data or {}).get("product_type") or "LAP",
        "reference_data": reference_data,
    }


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


def _checklist_processing_metadata(progress_snapshot: dict[str, Any]) -> dict[str, int]:
    completed_pages = progress_snapshot.get("completed_pages") or []
    ocr_time_ms = int(
        sum(float(page.get("elapsed_seconds") or 0) for page in completed_pages) * 1000
    )
    return {
        "ocr_time_ms": ocr_time_ms,
        "classification_time_ms": 0,
        "narration_time_ms": 0,
    }


def _build_unsupported_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_info in page_structure:
        page_number = int(page_info["page_number"])
        page_type = page_info["page_type"]
        text = digital_text_by_page.get(page_number, "")
        is_db_data = page_type == "digital" and _is_starting_json_db_page(page_number=page_number, text=text)
        document_type = "DB Data" if is_db_data else "Unknown"
        pages.append(
            {
                "page_number": page_number,
                "page_type": page_type,
                "image_path": page_info.get("image_path"),
                "is_readable": bool(text),
                "ocr_text": text,
                "ocr_confidence": None,
                "document_type": document_type,
                "classification_confidence": 1.0 if is_db_data else 0.0,
                "detection_method": "db_data" if is_db_data else "unknown",
                "detected_page_number": page_number if is_db_data else None,
                "extracted_fields": _build_db_data_fields(page_number=page_number, text=text) if is_db_data else {},
            }
        )
    return pages


def _persist_pipeline_outputs(
    *,
    application_id: int,
    output_dir: str | Path,
    structure: dict[str, Any],
    ground_truth: dict[str, Any],
    pages: list[dict[str, Any]],
    document_page_numbers: set[int] | None,
    verification_report: DocumentVerificationReport | None,
) -> tuple[dict[str, Any], Path]:
    """Persist extracted data, OCR evidence, and the optional verification report."""
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
    return progress_snapshot, ocr_json_path
