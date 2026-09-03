"""Build and persist OCR document JSON exports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.field_assignment_refiner import is_suspicious_assignment
from services.paths import processed_output_dir


def build_ocr_document_json(
    application_id: int,
    pages: list[dict[str, Any]],
    *,
    document_page_numbers: set[int] | None = None,
    page_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert OCR-processed document pages into comparison-ready JSON."""
    selected_pages = _select_document_pages(pages, document_page_numbers)
    page_events_by_number = _page_events_by_number(page_events or [])
    documents = [
        _page_to_document_json(page, page_events_by_number.get(int(page.get("page_number") or 0)))
        for page in selected_pages
    ]
    combined_fields = merge_public_extracted_fields(selected_pages)
    return {
        "application_id": application_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "document_page_count": len(documents),
        "combined_extracted_fields": combined_fields,
        "structured_extracted_data": build_structured_extracted_data(
            selected_pages, combined_fields
        ),
        "raw_ocr_pages": _raw_ocr_pages(documents),
        "documents": documents,
    }


def save_ocr_document_json(
    application_id: int,
    pages: list[dict[str, Any]],
    output_dir: str | Path | None = None,
    *,
    document_page_numbers: set[int] | None = None,
    page_events: list[dict[str, Any]] | None = None,
) -> Path:
    """Save OCR document-page JSON for later review or download."""
    export_payload = build_ocr_document_json(
        application_id,
        pages,
        document_page_numbers=document_page_numbers,
        page_events=page_events,
    )
    resolved_output_dir = Path(output_dir) if output_dir is not None else processed_output_dir()
    target_dir = resolved_output_dir / f"application_{application_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "document_ocr_data.json"
    with target_path.open("w", encoding="utf-8") as file:
        json.dump(export_payload, file, indent=2, ensure_ascii=False)
    return target_path


def merge_public_extracted_fields(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge non-private extracted OCR fields in page order."""
    merged: dict[str, Any] = {}
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        fields = page.get("extracted_fields") or {}
        if not isinstance(fields, dict):
            continue
        for field_name, value in fields.items():
            if str(field_name).startswith("_") or value in (None, ""):
                continue
            if is_suspicious_assignment(str(field_name), value):
                continue
            merged.setdefault(str(field_name), value)
    return merged


def build_structured_extracted_data(
    pages: list[dict[str, Any]],
    combined_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Group flat OCR fields into review/comparison-friendly sections."""
    combined = dict(combined_fields or merge_public_extracted_fields(pages))
    sources = _field_sources(pages)
    return {
        "applicant": _section(
            combined,
            sources,
            {
                "name": ("applicant_name", "borrower_name", "account_holder_name", "name"),
                "father_name": ("father_name",),
                "date_of_birth": ("date_of_birth", "dob"),
                "phone_number": ("phone_number", "phone"),
                "address": ("address",),
                "pin_code": ("pin_code", "pincode"),
            },
        ),
        "co_applicant": _section(
            combined,
            sources,
            {
                "name": ("co_applicant_name", "coapplicant_name", "co_borrower_name"),
                "father_name": ("co_applicant_father_name",),
                "date_of_birth": ("co_applicant_dob", "co_applicant_date_of_birth"),
                "phone_number": ("co_applicant_phone", "co_applicant_phone_number"),
                "address": ("co_applicant_address",),
            },
        ),
        "identity_documents": {
            "pan": _section(
                combined,
                sources,
                {
                    "number": ("pan_number", "pan"),
                    "name": ("pan_name", "applicant_name"),
                    "father_name": ("father_name",),
                    "date_of_birth": ("date_of_birth", "dob"),
                },
            ),
            "aadhaar": _section(
                combined,
                sources,
                {
                    "number": ("aadhaar_number", "aadhaar"),
                    "name": ("aadhaar_name", "applicant_name"),
                    "date_of_birth": ("date_of_birth", "dob"),
                    "address": ("address",),
                    "pin_code": ("pin_code", "pincode"),
                },
            ),
            "voter_id": _section(
                combined,
                sources,
                {
                    "number": ("voter_id_number",),
                    "name": ("voter_name", "applicant_name"),
                    "date_of_birth": ("date_of_birth", "dob"),
                    "address": ("address",),
                },
            ),
            "driving_license": _section(
                combined,
                sources,
                {
                    "number": ("dl_number",),
                    "name": ("dl_name", "applicant_name"),
                    "date_of_birth": ("date_of_birth", "dob"),
                    "validity_date": ("validity_date",),
                    "is_expired": ("is_expired",),
                },
            ),
        },
        "banking": _section(
            combined,
            sources,
            {
                "account_holder_name": ("account_holder_name", "applicant_name"),
                "account_number": ("account_number",),
                "ifsc": ("ifsc",),
                "customer_id": ("customer_id",),
                "statement_period_start": ("statement_period_start",),
                "statement_period_end": ("statement_period_end",),
                "passbook_issue_date": ("passbook_issue_date",),
                "cheque_number": ("cheque_number",),
                "cheque_date": ("cheque_date",),
                "cheque_amount": ("amount",),
                "is_cancelled_cheque": ("is_cancelled",),
            },
        ),
        "loan": _section(
            combined,
            sources,
            {
                "loan_amount": ("loan_amount", "amount"),
                "loan_type": ("loan_type", "product_type"),
                "tenure_months": ("tenure",),
                "emi": ("emi",),
                "roi": ("roi",),
                "agreement_date": ("agreement_date",),
            },
        ),
        "credit_and_registry": _section(
            combined,
            sources,
            {
                "credit_score": ("credit_score",),
                "report_date": ("report_date",),
                "cersai_search_reference_number": ("search_reference_number",),
                "cersai_transaction_id": ("transaction_id",),
                "cersai_search_result": ("search_result",),
            },
        ),
        "other_extracted_fields": _other_fields(combined),
        "document_pages": _document_page_summary(pages),
    }


def _select_document_pages(
    pages: list[dict[str, Any]],
    document_page_numbers: set[int] | None,
) -> list[dict[str, Any]]:
    sorted_pages = [
        page
        for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0))
        if str(page.get("document_type") or "") != "DB Data"
    ]
    if document_page_numbers is None:
        return sorted_pages
    return [
        page for page in sorted_pages if int(page.get("page_number") or 0) in document_page_numbers
    ]


def _section(
    fields: dict[str, Any],
    sources: dict[str, list[dict[str, Any]]],
    mapping: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    section: dict[str, Any] = {}
    section_sources: dict[str, list[dict[str, Any]]] = {}
    for output_name, candidate_names in mapping.items():
        source_field, value = _first_value(fields, candidate_names)
        if source_field is None:
            continue
        section[output_name] = value
        if source_field in sources:
            section_sources[output_name] = sources[source_field]
    if section_sources:
        section["_sources"] = section_sources
    return section


def _first_value(
    fields: dict[str, Any], candidate_names: tuple[str, ...]
) -> tuple[str | None, Any]:
    for field_name in candidate_names:
        value = fields.get(field_name)
        if value not in (None, "", [], {}):
            return field_name, value
    return None, None


def _field_sources(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sources: dict[str, list[dict[str, Any]]] = {}
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        page_number = page.get("page_number")
        document_type = page.get("document_type") or "Unknown"
        fields = page.get("extracted_fields") or {}
        if not isinstance(fields, dict):
            continue
        for field_name, value in fields.items():
            if str(field_name).startswith("_") or value in (None, "", [], {}):
                continue
            if is_suspicious_assignment(str(field_name), value):
                continue
            sources.setdefault(str(field_name), []).append(
                {
                    "page_number": page_number,
                    "document_type": document_type,
                    "field_name": str(field_name),
                }
            )
    return sources


def _other_fields(fields: dict[str, Any]) -> dict[str, Any]:
    known_fields = {
        "aadhaar",
        "aadhaar_number",
        "account_holder_name",
        "account_number",
        "address",
        "agreement_date",
        "amount",
        "applicant_name",
        "borrower_name",
        "cheque_date",
        "cheque_number",
        "co_applicant_address",
        "co_applicant_date_of_birth",
        "co_applicant_dob",
        "co_applicant_father_name",
        "co_applicant_name",
        "co_applicant_phone",
        "co_applicant_phone_number",
        "co_borrower_name",
        "coapplicant_name",
        "credit_score",
        "customer_id",
        "date_of_birth",
        "dl_name",
        "dl_number",
        "dob",
        "emi",
        "father_name",
        "ifsc",
        "is_cancelled",
        "is_expired",
        "loan_amount",
        "loan_type",
        "name",
        "pan",
        "pan_name",
        "pan_number",
        "passbook_issue_date",
        "phone",
        "phone_number",
        "pin_code",
        "pincode",
        "product_type",
        "report_date",
        "roi",
        "search_reference_number",
        "search_result",
        "statement_period_end",
        "statement_period_start",
        "tenure",
        "transaction_id",
        "validity_date",
        "voter_id_number",
        "voter_name",
    }
    return {
        field_name: value
        for field_name, value in fields.items()
        if field_name not in known_fields and value not in (None, "", [], {})
    }


def _document_page_summary(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        fields = page.get("extracted_fields") or {}
        public_fields = (
            {
                key: value
                for key, value in fields.items()
                if not str(key).startswith("_") and value not in (None, "", [], {})
            }
            if isinstance(fields, dict)
            else {}
        )
        summary.append(
            {
                "page_number": page.get("page_number"),
                "document_type": page.get("document_type") or "Unknown",
                "llm_document_type": _llm_document_type(fields)
                if isinstance(fields, dict)
                else None,
                "ocr_confidence": page.get("ocr_confidence"),
                "field_names": sorted(public_fields),
            }
        )
    return summary


def _raw_ocr_pages(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "page_number": document.get("page_number"),
            "document_type": document.get("document_type"),
            "llm_document_type": document.get("llm_document_type"),
            "ocr_confidence": document.get("ocr_confidence"),
            "ocr_text": document.get("ocr_text") or "",
            "ocr_structure": document.get("ocr_structure") or {},
            "extracted_fields": document.get("extracted_fields") or {},
        }
        for document in documents
    ]


def _page_events_by_number(page_events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(event["page_number"]): event
        for event in page_events
        if event.get("page_number") is not None
    }


def _page_to_document_json(
    page: dict[str, Any], event: dict[str, Any] | None = None
) -> dict[str, Any]:
    event = event or {}
    fields = page.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    fields = _json_safe(fields)
    page_details = _json_safe(page)
    processing_event = _json_safe(event)
    return {
        "page_number": page.get("page_number"),
        "page_type": page.get("page_type"),
        "total_pages": event.get("total_pages"),
        "status": event.get("status") or page.get("status") or "completed",
        "document_type": page.get("document_type") or "Unknown",
        "llm_document_type": _llm_document_type(fields),
        "image_path": page.get("image_path"),
        "is_readable": page.get("is_readable"),
        "ocr_confidence": page.get("ocr_confidence"),
        "classification_confidence": page.get("classification_confidence"),
        "detection_method": page.get("detection_method"),
        "detected_page_number": page.get("detected_page_number"),
        "elapsed_seconds": event.get("elapsed_seconds") or page.get("elapsed_seconds"),
        "completed_at": event.get("completed_at") or page.get("completed_at"),
        "error": event.get("error") or page.get("error"),
        "ocr_text": page.get("ocr_text") or "",
        "extracted_fields": fields,
        "page_details": page_details,
        "processing_event": processing_event,
    }


def _llm_document_type(fields: dict[str, Any]) -> str | None:
    result = fields.get("_structured_llm_classification")
    if not isinstance(result, dict):
        return None
    document_type = str(result.get("document_type") or "").strip()
    return document_type or None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
