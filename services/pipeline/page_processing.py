"""Per-page OCR, classification, and field extraction loop."""

from __future__ import annotations

import copy
import hashlib
import time
import unicodedata
from typing import Any

from services.classification_review_log import log_classification_review_event
from services.content_triage import triage_page_content
from services.field_assignment_refiner import refine_field_assignments
from services.job_control import cooperate
from services.language_detection import analyze_text_languages, normalize_language_code
from services.llm_page_classifier import is_llm_classification_candidate
from services.ocr_router import OCRResult, OCRRouter, get_ocr_router, run_fast_ocr_on_page
from services.page_classification import classify_page_text, create_llm_classifier_budget
from services.pipeline.classification import (
    _assign_sequential_document_type,
    _content_category_for_image_type,
    _deterministic_routing_document_type,
    _filename_type_contradicted_by_text,
    _image_evidence_type_from_text,
    _infer_document_type_from_filename,
    _log_classification_review_if_needed,
    _mark_unanchored_inherited_identity,
    _normalize_fresh_document_text,
    _smooth_page_classifications,
    _source_document_for_page,
    _source_filename_override_allowed,
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
    _extract_fields_with_layout,
    _is_starting_json_db_page,
    _record_completed_page_event,
)
from services.processing_policy import (
    OCR_SKIPPED_DOCUMENT_TYPE,
    build_ocr_skipped_fields,
    selected_scanned_page_numbers,
)
from services.progress_tracker import mark_page_started, update_page_progress
from services.stamp_duty_rules import evaluate_stamp_duty, load_stamp_duty_rules
from services.structured_llm_classifier import classify_with_structured_llm
from services.validation_gates import attach_field_provenance

run_ocr_on_page = run_fast_ocr_on_page

_DEFAULT_FAST_OCR_PROCESSOR = run_fast_ocr_on_page


def _pipeline_ocr_router() -> OCRRouter:
    if run_ocr_on_page is _DEFAULT_FAST_OCR_PROCESSOR:
        return get_ocr_router()
    return OCRRouter(
        fast_processor=run_ocr_on_page,
        structured_processor=run_ocr_on_page,
    )


def _build_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
    application_id: int | None = None,
    source_page_starts: set[int] | None = None,
    source_documents: list[dict[str, Any]] | None = None,
    job_id: int | None = None,
    checkpoint_pages: list[dict[str, Any]] | None = None,
    refresh_cached_ocr: bool = False,
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
    current_ocr_route: str | None = None
    checkpoints = {
        int(page.get("page_number") or 0): page
        for page in checkpoint_pages or []
        if int(page.get("page_number") or 0) > 0
    }
    reuse_page_map = _build_page_reuse_map(source_documents or [], digital_text_by_page)

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
            current_ocr_route = None
        checkpoint = checkpoints.get(page_number)
        if checkpoint is not None:
            if refresh_cached_ocr:
                checkpoint = _refresh_page_from_cached_ocr(
                    checkpoint,
                    current_type=current_type,
                    current_confidence=current_confidence,
                    current_detected_page=current_detected_page,
                    source_documents=source_documents or [],
                )
            pages.append(checkpoint)
            current_type = str(checkpoint.get("document_type") or "Unknown")
            current_confidence = float(checkpoint.get("classification_confidence") or 0.0)
            current_detected_page = checkpoint.get("detected_page_number")
            current_ocr_route = checkpoint.get("ocr_route")
            continue
        cooperate(job_id, application_id or 0)
        reuse = reuse_page_map.get(page_number)
        if reuse:
            canonical_page = next(
                (
                    page
                    for page in pages
                    if int(page.get("page_number") or 0) == int(reuse["canonical_page"])
                ),
                None,
            )
            if canonical_page is not None:
                if application_id is not None:
                    mark_page_started(
                        application_id,
                        current_page=page_number,
                        total_pages=total_pages,
                        message=f"Reusing duplicate page {page_number}/{total_pages}",
                    )
                reused_page = _clone_reused_page(
                    canonical_page,
                    page_info=page_info,
                    reuse=reuse,
                    source_document=_source_document_for_page(source_documents or [], page_number),
                )
                pages.append(reused_page)
                current_type = str(reused_page.get("document_type") or "Unknown")
                current_confidence = float(reused_page.get("classification_confidence") or 0.0)
                current_detected_page = reused_page.get("detected_page_number")
                current_ocr_route = reused_page.get("ocr_route")
                page_elapsed = _log_total_page_time(page_number, total_pages, page_started_at)
                _record_completed_page_event(
                    application_id,
                    job_id=job_id,
                    page=reused_page,
                    total_pages=total_pages,
                    elapsed_seconds=page_elapsed,
                    status="reused",
                )
                if application_id is not None:
                    update_page_progress(
                        application_id,
                        processed_pages=len(pages),
                        total_pages=total_pages,
                        current_page=page_number,
                        message=f"Processed {len(pages)}/{total_pages} pages (duplicate reused)",
                    )
                continue
        needs_ocr = page_type == "scanned" and page_number in selected_scanned_pages
        ocr_metadata: dict[str, Any] = {}
        if application_id is not None:
            mark_page_started(
                application_id,
                current_page=page_number,
                total_pages=total_pages,
                message=f"Working on page {page_number}/{total_pages}",
            )

        triage: dict[str, Any] = {}
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
                        job_id=job_id,
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
                    job_id=job_id,
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
                        message=(f"Processed {len(pages)}/{total_pages} pages (OCR budget skip)"),
                    )
                continue
            else:
                _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                phase_name = "OCR classification pass"
                phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
                preliminary_ocr = _pipeline_ocr_router().process_fast_for_classification(
                    image_path or ""
                )
                ocr_result = _ocr_result_dict(preliminary_ocr)
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
                document_type = _image_evidence_type_from_text(text) or "Property Image"
                classification = {"confidence": triage["confidence"]}
                extracted_fields = {
                    **extracted_fields,
                    "content_category": _content_category_for_image_type(document_type),
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
            elif triage["category"] == "handwritten" and (
                ocr_confidence is None or float(ocr_confidence) < 0.70
            ):
                document_type = "Unknown"
                detection_method = "triage_low_confidence"
                if source_documents:
                    for doc in source_documents:
                        start = doc.get("internal_page_start")
                        end = doc.get("internal_page_end")
                        if start is not None and end is not None and start <= page_number <= end:
                            inferred = _infer_document_type_from_filename(
                                str(doc.get("original_filename") or "")
                            )
                            if inferred and not _filename_type_contradicted_by_text(inferred, text):
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
                if source_filename_type in {
                    "House Photo",
                    "Workplace Photo",
                    "Property Image",
                    "KYC Card Photo",
                    "Ration Card Photo",
                    "PDC",
                    "Cheque",
                } and _source_filename_override_allowed(source_filename_type, document_type):
                    document_type = source_filename_type
                    classification = {"confidence": 0.95}
                    detection_method = "filename_override"
                if (
                    document_type == "Unknown"
                    and "gps map camera" in _normalize_fresh_document_text(text)
                ):
                    # GPS-overlay photos exported from messaging apps carry no
                    # classifiable text, but the overlay itself proves the page
                    # is photographic evidence rather than a named document.
                    document_type = "Property Image"
                    detection_method = "photo_evidence"
                    classification = {"confidence": 0.85}
                if document_type == "Unknown" and source_documents:
                    for doc in source_documents:
                        start = doc.get("internal_page_start")
                        end = doc.get("internal_page_end")
                        if start is not None and end is not None and start <= page_number <= end:
                            inferred = _infer_document_type_from_filename(
                                str(doc.get("original_filename") or "")
                            )
                            if inferred and not _filename_type_contradicted_by_text(inferred, text):
                                document_type = inferred
                                detection_method = "filename_inference"
                                classification = {
                                    "confidence": max(
                                        float(classification.get("confidence") or 0.0),
                                        0.70,
                                    )
                                }
                            break
                routed_ocr = None
                if needs_ocr:
                    phase_name = "OCR routing"
                    phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
                    inherited_route = (
                        current_ocr_route
                        if assigned.get("detection_method") == "inherited"
                        and current_ocr_route in {"fast", "structured"}
                        else None
                    )
                    routing_document_type = _deterministic_routing_document_type(
                        document_type=document_type,
                        detection_method=detection_method,
                        classification_metadata=classification_meta,
                    )
                    routed_ocr = _pipeline_ocr_router().process_page(
                        image_path or "",
                        routing_document_type,
                        page_number,
                        doc_id=(
                            f"{application_id}:{assigned.get('detected_page_number') or page_number}"
                            if application_id is not None
                            else None
                        ),
                        inherited_route=inherited_route,
                        preliminary_fast_result=preliminary_ocr,
                    )
                    _log_page_phase_done(page_number, total_pages, phase_name, phase_started_at)
                    text = routed_ocr.text
                    ocr_confidence = routed_ocr.confidence
                    is_readable = bool(text.strip())
                    ocr_metadata = routed_ocr.to_legacy_dict()
                    if routed_ocr.error:
                        extracted_fields["_processing_error"] = routed_ocr.error
                    if page_number % 5 == 0:
                        import gc

                        gc.collect()
                if detection_method == "detected":
                    current_type = document_type
                    current_confidence = float(assigned["confidence"] or 0.0)
                    current_detected_page = page_number
                    if routed_ocr is not None:
                        current_ocr_route = routed_ocr.requested_route or routed_ocr.route_used
                phase_name = "field extraction"
                _mark_page_phase(application_id, page_number, total_pages, "extracting fields")
                phase_started_at = _log_page_phase_start(page_number, total_pages, phase_name)
                extracted_fields = {
                    **extracted_fields,
                    **_extract_fields_with_layout(
                        document_type,
                        text,
                        ocr_metadata.get("structured_content"),
                    ),
                }
                extracted_fields = refine_field_assignments(
                    document_type=document_type,
                    ocr_text=text,
                    extracted_fields=extracted_fields,
                )
                if document_type == "Stamp Duty":
                    extracted_fields["_stamp_duty_validation"] = evaluate_stamp_duty(
                        extracted_fields,
                        {},
                        load_stamp_duty_rules(),
                    )
                _mark_unanchored_inherited_identity(
                    extracted_fields,
                    detection_method=detection_method,
                    raw_document_type=assigned.get("raw_document_type"),
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
                logger.exception(
                    "[Page %s/%s] Page processing failed: %s", page_number, total_pages, exc
                )
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
                        inferred = _infer_document_type_from_filename(
                            str(doc.get("original_filename") or "")
                        )
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
        # Run the structured classifier only after deterministic and generic
        # extraction has completed, and only for the two allowed fallback
        # cases. Photo pages intentionally stay on the visual triage path.
        if (
            page_status != "error"
            and triage.get("category") != "photo"
            and is_llm_classification_candidate(document_type, ocr_confidence)
        ):
            _mark_page_phase(
                application_id,
                page_number,
                total_pages,
                "checking LLM classification",
            )
            structured_llm_result = classify_with_structured_llm(
                deterministic_document_type=document_type,
                structured_fields=extracted_fields,
                ocr_text=text,
                ocr_confidence=ocr_confidence,
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
                            "structured_llm_document_type": structured_llm_result.get(
                                "document_type"
                            ),
                            "structured_llm_confidence": structured_llm_result.get("confidence"),
                            "structured_llm_reason": structured_llm_result.get("reason"),
                            "structured_llm_trigger": structured_llm_result.get("trigger"),
                        },
                        llm_document_type=str(structured_llm_result.get("document_type") or ""),
                    )
        language_profile = analyze_text_languages(text)
        provider_languages = ocr_metadata.get("ocr_languages")
        declared_languages = [
            value for value in (extracted_fields.get("second_language"),) if value not in (None, "")
        ]
        identified_languages: list[dict[str, str]] = []
        for source, values in (
            ("declared_on_document", declared_languages),
            ("ocr_provider", provider_languages or []),
        ):
            for value in values:
                code = normalize_language_code(value)
                if code and not any(
                    item["code"] == code and item["source"] == source
                    for item in identified_languages
                ):
                    identified_languages.append({"code": code, "source": source})
        if language_profile["scripts"] or provider_languages or declared_languages:
            extracted_fields["_language"] = {
                **language_profile,
                "declared_languages": declared_languages,
                "provider_languages": provider_languages or [],
                "identified_languages": identified_languages,
            }
        completed_page = {
            "page_number": page_number,
            "page_type": page_type,
            "image_path": image_path,
            "is_readable": is_readable,
            "ocr_text": text,
            "ocr_confidence": ocr_confidence,
            "ocr_structure": _public_ocr_structure(ocr_metadata),
            "structured_content": ocr_metadata.get("structured_content"),
            "ocr_route": ocr_metadata.get("ocr_route"),
            "ocr_escalated": bool(ocr_metadata.get("ocr_escalated", False)),
            "ocr_processing_time_ms": int(ocr_metadata.get("ocr_processing_time_ms") or 0),
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
        attach_field_provenance(
            completed_page,
            source_document=_source_document_for_page(source_documents or [], page_number),
        )
        pages.append(completed_page)
        page_elapsed = _log_total_page_time(page_number, total_pages, page_started_at)
        _record_completed_page_event(
            application_id,
            job_id=job_id,
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


def _refresh_page_from_cached_ocr(
    checkpoint: dict[str, Any],
    *,
    current_type: str,
    current_confidence: float,
    current_detected_page: int | None,
    source_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Re-run rules/extraction on persisted OCR without calling an OCR provider.

    OCR text is expensive evidence and does not become stale when deterministic
    classification or extraction rules change. This path lets a completed
    application be revalidated offline while preserving the original OCR,
    images, confidence, layout, and source provenance.
    """
    refreshed = copy.deepcopy(checkpoint)
    page_number = int(refreshed.get("page_number") or 0)
    text = str(refreshed.get("ocr_text") or "")
    old_type = str(refreshed.get("document_type") or "Unknown")
    if not text.strip() or old_type in {"DB Data", OCR_SKIPPED_DOCUMENT_TYPE}:
        return refreshed

    ocr_confidence = refreshed.get("ocr_confidence")
    classification, classification_meta = classify_page_text(
        text,
        ocr_confidence=ocr_confidence,
        layout_metadata=None,
        llm_budget=None,
    )
    assigned = _assign_sequential_document_type(
        page_number=page_number,
        text=text,
        classification=classification,
        current_type=current_type,
        current_confidence=current_confidence,
        current_detected_page=current_detected_page,
    )
    document_type = assigned["document_type"]
    confidence = float(assigned["confidence"] or 0.0)
    detection_method = str(assigned["detection_method"] or "unknown")
    source_document = _source_document_for_page(source_documents, page_number)
    filename_type = _infer_document_type_from_filename(
        str((source_document or {}).get("original_filename") or "")
    )
    if filename_type in {
        "House Photo",
        "Workplace Photo",
        "Property Image",
        "KYC Card Photo",
        "Ration Card Photo",
        "PDC",
        "Cheque",
    } and _source_filename_override_allowed(filename_type, document_type):
        document_type = filename_type
        confidence = 0.95
        detection_method = "filename_override"
    elif (
        document_type == "Unknown"
        and filename_type
        and not _filename_type_contradicted_by_text(filename_type, text)
    ):
        document_type = filename_type
        detection_method = "filename_inference"
        confidence = max(confidence, 0.70)
    elif (
        document_type == "Unknown"
        and old_type in {"House Photo", "Workplace Photo", "Property Image", "KYC Card Photo"}
        and len(text.strip()) < 160
    ):
        document_type = old_type
        detection_method = "cached_visual_evidence"
        confidence = max(confidence, float(refreshed.get("classification_confidence") or 0.0))

    fields = _extract_fields_with_layout(
        document_type,
        text,
        refreshed.get("structured_content") or refreshed.get("ocr_structure"),
    )
    fields = refine_field_assignments(
        document_type=document_type,
        ocr_text=text,
        extracted_fields=fields,
    )
    if document_type == "Stamp Duty":
        fields["_stamp_duty_validation"] = evaluate_stamp_duty(
            fields,
            {},
            load_stamp_duty_rules(),
        )
    _mark_unanchored_inherited_identity(
        fields,
        detection_method=detection_method,
        raw_document_type=assigned.get("raw_document_type"),
    )
    classification_meta = {
        **classification_meta,
        "assigned_type": document_type,
        "detection_method": detection_method,
        "raw_document_type": assigned.get("raw_document_type"),
        "raw_confidence": assigned.get("raw_confidence"),
        "detected_page_number": assigned.get("detected_page_number"),
        "cached_ocr_revalidation": True,
    }
    if assigned.get("inheritance_warning"):
        classification_meta["inheritance_warning"] = assigned["inheritance_warning"]
    if assigned.get("abstain_reason"):
        classification_meta["abstain_reason"] = assigned["abstain_reason"]
    fields["_classification"] = classification_meta
    fields = _ensure_page_has_json_details(
        document_type=document_type,
        text=text,
        extracted_fields=fields,
    )
    language_profile = analyze_text_languages(text)
    previous_language = (
        (checkpoint.get("extracted_fields") or {}).get("_language")
        if isinstance(checkpoint.get("extracted_fields"), dict)
        else None
    )
    if language_profile["scripts"] or isinstance(previous_language, dict):
        fields["_language"] = {
            **language_profile,
            "declared_languages": list((previous_language or {}).get("declared_languages") or []),
            "provider_languages": list((previous_language or {}).get("provider_languages") or []),
            "identified_languages": list(
                (previous_language or {}).get("identified_languages") or []
            ),
        }

    refreshed.update(
        {
            "document_type": document_type,
            "classification_confidence": confidence,
            "detection_method": detection_method,
            "detected_page_number": assigned.get("detected_page_number"),
            "extracted_fields": fields,
        }
    )
    attach_field_provenance(refreshed, source_document=source_document)
    return refreshed


def _build_page_reuse_map(
    source_documents: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
) -> dict[int, dict[str, Any]]:
    """Map repeated pages to an earlier canonical page before OCR/LLM work.

    Exact ZIP-member duplicates cover scanned files. Exact normalized embedded
    text covers stamped/e-signed PDF variants whose business content is the
    same but whose visual overlays still need a separate variant audit.
    """
    reuse: dict[int, dict[str, Any]] = {}
    source_by_id = {
        str(source.get("source_document_id") or ""): source
        for source in source_documents
        if source.get("source_document_id")
    }
    for source in source_documents:
        canonical_id = str(source.get("duplicate_of_source_document_id") or "")
        canonical = source_by_id.get(canonical_id)
        if not canonical:
            continue
        start = int(source.get("internal_page_start") or 0)
        end = int(source.get("internal_page_end") or 0)
        canonical_start = int(canonical.get("internal_page_start") or 0)
        canonical_end = int(canonical.get("internal_page_end") or 0)
        if start <= 0 or canonical_start <= 0 or end - start != canonical_end - canonical_start:
            continue
        for offset, page_number in enumerate(range(start, end + 1)):
            reuse[page_number] = {
                "canonical_page": canonical_start + offset,
                "method": "exact_file_sha256",
                "canonical_source_document_id": canonical_id,
            }

    first_page_by_text: dict[str, int] = {}
    for page_number, text in sorted(digital_text_by_page.items()):
        fingerprint = _digital_text_fingerprint(text)
        if not fingerprint:
            continue
        canonical_page = first_page_by_text.get(fingerprint)
        if canonical_page is None:
            first_page_by_text[fingerprint] = page_number
            continue
        reuse.setdefault(
            page_number,
            {
                "canonical_page": canonical_page,
                "method": "exact_embedded_text",
                "visual_variant_check_required": True,
            },
        )
    return reuse


def _digital_text_fingerprint(text: str) -> str | None:
    normalized = " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())
    # Avoid deduplicating short headers or near-empty pages that may have
    # different visual evidence despite sharing a few words.
    if len(normalized) < 120:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _clone_reused_page(
    canonical_page: dict[str, Any],
    *,
    page_info: dict[str, Any],
    reuse: dict[str, Any],
    source_document: dict[str, Any] | None,
) -> dict[str, Any]:
    page_number = int(page_info.get("page_number") or 0)
    cloned = copy.deepcopy(canonical_page)
    canonical_number = int(canonical_page.get("page_number") or 0)
    canonical_detected_number = canonical_page.get("detected_page_number")
    starts_logical_document = canonical_detected_number == canonical_number
    cloned.update(
        {
            "page_number": page_number,
            "page_type": page_info.get("page_type"),
            "image_path": page_info.get("image_path"),
            "ocr_processing_time_ms": 0,
            "ocr_escalated": False,
            "detection_method": "deduplicated_reuse",
            "detected_page_number": page_number if starts_logical_document else None,
        }
    )
    fields = cloned.get("extracted_fields")
    if not isinstance(fields, dict):
        fields = {}
        cloned["extracted_fields"] = fields
    fields.pop("_field_provenance", None)
    fields["_deduplication"] = {
        **reuse,
        "reused_from_page": int(reuse.get("canonical_page") or 0),
    }
    classification = fields.get("_classification")
    if isinstance(classification, dict):
        classification["detection_method"] = "deduplicated_reuse"
        classification["detected_page_number"] = page_number if starts_logical_document else None
    attach_field_provenance(cloned, source_document=source_document)
    return cloned


def _public_ocr_structure(metadata: dict[str, Any]) -> dict[str, Any]:
    """Select structured OCR fields that should be persisted and exported."""
    keys = (
        "ocr_pipeline",
        "ocr_languages",
        "ocr_language_hints",
        "header_text",
        "layout_blocks",
        "tables",
        "seals",
        "formulas",
        "structure_json",
        "ocr_route",
        "ocr_escalated",
        "ocr_routing_rationale",
        "ocr_original_confidence",
        "ocr_processing_time_ms",
        "bounding_boxes",
        "structured_content",
    )
    return {key: metadata[key] for key in keys if key in metadata}


def _ocr_result_dict(result: OCRResult | dict[str, Any]) -> dict[str, Any]:
    return result.to_legacy_dict() if isinstance(result, OCRResult) else dict(result)
