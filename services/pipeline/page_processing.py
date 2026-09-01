"""Build normalized page records from PDF structure."""

from __future__ import annotations

import time
from typing import Any

from services.classification_review_log import log_classification_review_event
from services.content_triage import triage_page_content
from services.field_assignment_refiner import refine_field_assignments
from services.field_extractor import extract_fields
from services.ocr_engine import run_ocr_on_page
from services.page_classification import classify_page_text, create_llm_classifier_budget
from services.pipeline.classification import (
    _assign_sequential_document_type,
    _infer_document_type_from_filename,
    _log_classification_review_if_needed,
    _smooth_page_classifications,
)
from services.pipeline.logging_helpers import (
    _flush_log_handlers,
    _log_page_phase_done,
    _log_page_phase_failed,
    _log_page_phase_start,
    _log_total_page_time,
    _mark_page_phase,
    logger,
)
from services.pipeline.page_details import (
    _apply_llm_extraction_fallback,
    _build_db_data_fields,
    _ensure_page_has_json_details,
    _is_starting_json_db_page,
    _record_completed_page_event,
)
from services.processing_policy import (
    OCR_SKIPPED_DOCUMENT_TYPE,
    build_ocr_skipped_fields,
    selected_scanned_page_numbers,
)
from services.progress_tracker import mark_page_started, update_page_progress
from services.structured_llm_classifier import classify_with_structured_llm


def _build_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
    application_id: int | None = None,
    source_page_starts: set[int] | None = None,
    source_documents: list[dict[str, Any]] | None = None,
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
        if source_page_starts and page_number in source_page_starts:
            current_type = "Unknown"
            current_confidence = 0.0
            current_detected_page = None
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
                if _is_starting_json_db_page(page_number=page_number, text=text):
                    document_type = "DB Data"
                    classification = {"confidence": 1.0}
                    extracted_fields = _build_db_data_fields(page_number=page_number, text=text)
                    _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                    db_data_page = {
                        "page_number": page_number,
                        "page_type": page_type,
                        "image_path": image_path,
                        "is_readable": is_readable,
                        "ocr_text": text,
                        "ocr_confidence": ocr_confidence,
                        "document_type": document_type,
                        "classification_confidence": classification.get("confidence", 0.0),
                        "detection_method": "db_data",
                        "detected_page_number": page_number,
                        "extracted_fields": extracted_fields,
                    }
                    pages.append(db_data_page)
                    page_elapsed = _log_total_page_time(page_number, total_pages, page_started_at)
                    _record_completed_page_event(
                        application_id,
                        page=db_data_page,
                        total_pages=total_pages,
                        elapsed_seconds=page_elapsed,
                        status=page_status,
                    )
                    if application_id is not None:
                        update_page_progress(
                            application_id,
                            processed_pages=len(pages),
                            total_pages=total_pages,
                            current_page=page_number,
                            message=f"Processed {len(pages)}/{total_pages} pages (DB data)",
                        )
                    continue
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
                detection_method = "triage_low_confidence"
                if source_documents:
                    for doc in source_documents:
                        start = doc.get("internal_page_start")
                        end = doc.get("internal_page_end")
                        if start is not None and end is not None and start <= page_number <= end:
                            inferred = _infer_document_type_from_filename(str(doc.get("original_filename") or ""))
                            if inferred:
                                document_type = inferred
                                detection_method = "filename_inference"
                                classification = {"confidence": 0.85}
                            break
                classification = {"confidence": 0.0}
                extracted_fields = {
                    **extracted_fields,
                    "review_flag": "low_confidence_needs_review",
                    "_triage": triage,
                    "_classification": {
                        "source": "triage",
                        "assigned_type": document_type,
                        "detection_method": detection_method,
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
                detection_method = assigned["detection_method"]
                # A photo packet may visibly contain identity cards without
                # being an Aadhaar document. Strong source filenames are the
                # authoritative type for these operational image bundles.
                source_filename_type = None
                if source_documents:
                    for doc in source_documents:
                        start = doc.get("internal_page_start")
                        end = doc.get("internal_page_end")
                        if start is not None and end is not None and start <= page_number <= end:
                            source_filename_type = _infer_document_type_from_filename(
                                str(doc.get("original_filename") or "")
                            )
                            break
                if source_filename_type in {"House Photo", "Workplace Photo", "Property Image"}:
                    document_type = source_filename_type
                    classification = {"confidence": 0.95}
                    detection_method = "filename_override"
                if document_type == "Unknown" and source_documents:
                    for doc in source_documents:
                        start = doc.get("internal_page_start")
                        end = doc.get("internal_page_end")
                        if start is not None and end is not None and start <= page_number <= end:
                            inferred = _infer_document_type_from_filename(str(doc.get("original_filename") or ""))
                            if inferred:
                                document_type = inferred
                                detection_method = "filename_inference"
                            break
                if detection_method == "detected":
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
                    "detection_method": detection_method,
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
                    extracted_fields = _apply_llm_extraction_fallback(
                        deterministic_document_type=document_type,
                        structured_llm_result=structured_llm_result,
                        text=text,
                        extracted_fields=extracted_fields,
                    )
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
            detection_method = "unknown"
            if source_documents:
                for doc in source_documents:
                    start = doc.get("internal_page_start")
                    end = doc.get("internal_page_end")
                    if start is not None and end is not None and start <= page_number <= end:
                        inferred = _infer_document_type_from_filename(str(doc.get("original_filename") or ""))
                        if inferred:
                            document_type = inferred
                            detection_method = "filename_inference"
                        break
            classification = {"confidence": 0.0}
            extracted_fields = {
                "_processing_error": str(exc),
                "_classification": {
                    "assigned_type": document_type,
                    "detection_method": detection_method,
                    "raw_document_type": document_type,
                    "raw_confidence": 0.0,
                    "detected_page_number": None,
                },
            }

        extracted_fields = _ensure_page_has_json_details(
            document_type=document_type,
            text=text,
            extracted_fields=extracted_fields,
        )
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
    pages = _smooth_page_classifications(pages, application_id, total_pages)
    return sorted(pages, key=lambda item: int(item.get("page_number") or 0))
