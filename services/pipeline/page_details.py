"""Page-level JSON details and generic field extraction fallbacks."""

from __future__ import annotations

import json
import re
from typing import Any

from services.field_assignment_refiner import refine_field_assignments
from services.field_extractor import extract_fields
from services.job_control import mark_checkpoint
from services.pipeline.persistence import _save_page_checkpoint
from services.progress_tracker import record_page_completed


def _extract_fields_with_layout(
    document_type: str,
    text: str,
    structured_content: Any,
) -> dict[str, Any]:
    if isinstance(structured_content, dict) and structured_content.get("layout_regions"):
        return extract_fields(
            document_type,
            text,
            structured_content=structured_content,
        )
    return extract_fields(document_type, text)


def _record_completed_page_event(
    application_id: int | None,
    *,
    job_id: int | None = None,
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
    _save_page_checkpoint(application_id, page)
    mark_checkpoint(job_id, int(page.get("page_number") or 0))


def _build_db_data_fields(*, page_number: int, text: str) -> dict[str, Any]:
    payload = _extract_json_payload(text)
    fields: dict[str, Any] = {
        "content_category": "db_data",
        "db_data_page": True,
        "db_data_source": "digital_pdf_json",
        "db_data_text_excerpt": str(text or "").strip()[:700],
        "_classification": {
            "source": "digital_text",
            "assigned_type": "DB Data",
            "detection_method": "db_data",
            "raw_document_type": "DB Data",
            "raw_confidence": 1.0,
            "detected_page_number": page_number,
        },
    }
    if payload:
        fields["db_data_json"] = payload
        fields["db_data_json_keys"] = sorted(str(key) for key in payload.keys())
    return fields


def _is_starting_json_db_page(*, page_number: int, text: str) -> bool:
    """Return True only for opening digital pages that contain parseable JSON."""
    if page_number > 3:
        return False
    return bool(_extract_json_payload(text))


def _extract_json_payload(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        return {}
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _apply_llm_extraction_fallback(
    *,
    deterministic_document_type: str,
    structured_llm_result: dict[str, Any],
    text: str,
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    if deterministic_document_type != "Unknown":
        return extracted_fields

    llm_document_type = str(structured_llm_result.get("document_type") or "").strip()
    if not llm_document_type or llm_document_type == "Unknown":
        return extracted_fields

    fallback_fields = extract_fields(llm_document_type, text)
    public_fields = {
        key: value
        for key, value in fallback_fields.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return {
            **extracted_fields,
            "_llm_field_extraction": {
                "source": "structured_llm_classification",
                "document_type": llm_document_type,
                "confidence": structured_llm_result.get("confidence"),
                "status": "no_fields_extracted",
            },
        }

    fallback_fields = refine_field_assignments(
        document_type=llm_document_type,
        ocr_text=text,
        extracted_fields=fallback_fields,
    )
    fallback_fields["_llm_field_extraction"] = {
        "source": "structured_llm_classification",
        "document_type": llm_document_type,
        "confidence": structured_llm_result.get("confidence"),
        "status": "fields_extracted",
        "field_names": sorted(public_fields),
    }
    return {
        **extracted_fields,
        **fallback_fields,
    }


def _ensure_page_has_json_details(
    *,
    document_type: str,
    text: str,
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    # Repayment tables are structural evidence.  Parse them even when the page
    # already has other public fields, and even when a continuation page was
    # misclassified as a bank statement or NACH form.
    from services.repayment_schedule import attach_repayment_fields

    # Six-column repayment rows are structural and safe to detect on any page.
    # KFS summary labels are not: insurance premium calculators also contain a
    # "sanctioned loan amount" input and their columnar OCR can bind that label
    # to GST/premium values.  Only attach semantic loan-summary fields when the
    # page has actually been classified into a loan-term document family.
    summary_document_types = {
        "cam",
        "facility agreement",
        "key fact statement",
        "kfs",
        "loan agreement",
        "repayment schedule",
        "sanction letter",
    }
    extracted_fields = attach_repayment_fields(
        extracted_fields,
        text,
        include_summary=str(document_type or "").strip().casefold() in summary_document_types,
    )
    if _has_informative_public_fields(extracted_fields):
        return extracted_fields
    if not str(text or "").strip():
        return extracted_fields

    generic_fields = _extract_generic_page_details(document_type=document_type, text=text)
    if not generic_fields:
        return extracted_fields
    return {
        **extracted_fields,
        **generic_fields,
        "_generic_field_extraction": {
            "source": "ocr_text_generic_fallback",
            "reason": "No document-specific fields were extracted from this non-empty page.",
            "status": "fields_extracted",
        },
    }


def _has_informative_public_fields(fields: dict[str, Any]) -> bool:
    ignored_fields = {"content_category", "review_flag"}
    for field_name, value in (fields or {}).items():
        if str(field_name).startswith("_") or field_name in ignored_fields:
            continue
        if value not in (None, "", [], {}):
            return True
    return False


def _extract_generic_page_details(*, document_type: str, text: str) -> dict[str, Any]:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return {}

    details: dict[str, Any] = {}
    detected = _generic_detected_values(normalized_text)
    for key, value in detected.items():
        if value:
            details[key] = value

    return details


def _generic_detected_values(text: str) -> dict[str, list[str]]:
    return {
        "generic_pan_numbers": _unique_matches(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text.upper()),
        "generic_aadhaar_numbers": _unique_matches(
            r"(?<!\d)\d{4}[ \t]?\d{4}[ \t]?\d{4}(?!\d)", text
        ),
        "generic_phone_numbers": _unique_matches(r"\b[6-9]\d{9}\b", text),
        "generic_ifsc_codes": _unique_matches(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", text.upper()),
        "generic_dates": _unique_matches(
            r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{2}[/\-\.]\d{2})\b",
            text,
        ),
        "generic_amounts": _unique_matches(
            r"(?:rs\.?|inr|₹)?\s?\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b",
            text,
            flags=re.IGNORECASE,
        ),
        "generic_emails": _unique_matches(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, flags=re.IGNORECASE
        ),
    }


def _generic_keywords(text: str) -> list[str]:
    lowered = text.lower()
    keyword_map = {
        "account": ("account", "a/c", "ifsc"),
        "address": ("address", "village", "district", "tehsil", "pin code"),
        "amount": ("amount", "loan", "emi", "tenure", "interest"),
        "credit_report": ("cibil", "crif", "credit score", "score"),
        "identity": ("pan", "aadhaar", "voter", "election commission", "date of birth"),
        "property": ("property", "khasra", "plot", "patta", "registry"),
    }
    return [label for label, terms in keyword_map.items() if any(term in lowered for term in terms)]


def _unique_matches(pattern: str, text: str, *, flags: int = 0, limit: int = 10) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(pattern, text, flags):
        value = re.sub(r"\s+", " ", match.group(0)).strip()
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
        if len(values) >= limit:
            break
    return values
