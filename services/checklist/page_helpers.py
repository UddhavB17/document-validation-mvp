"""Checklist engine submodule."""

from __future__ import annotations

import re

from services.checklist.anomaly_builder import build_anomaly
from services.config import effective_config
from services.page_quality import confident_pages_for_types, is_confident_document_match


def _document_evidence_count(pages: list[dict], document_type: str) -> tuple[int, str]:
    """Count physical evidence, not PDF pages, when a document exposes items."""
    if document_type == "PDC":
        cheque_numbers = {
            str(number)
            for page in pages
            for number in ((page.get("extracted_fields") or {}).get("cheque_numbers") or [])
            if number not in (None, "")
        }
        if cheque_numbers:
            return len(cheque_numbers), "cheque(s)"
    return len(pages), "page(s)"


def _numeric(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(re.sub(r"[^0-9.-]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _pages_for_person(pages: list[dict], person_id: str) -> list[dict]:
    return [
        page
        for page in pages
        if str(page.get("person_id") or page.get("applicant_role") or "") == person_id
    ]


def _missing_presence_anomaly(
    item: dict, *, document_type: str, person_id: str | None = None
) -> dict:
    s_no = item.get("s_no")
    expected = "Document present"
    if person_id:
        expected += f" for {person_id}"
    return build_anomaly(
        rule_id=f"MISSING_DOC_S{s_no}" + (f"_{person_id}" if person_id else ""),
        s_no=s_no,
        severity=item.get("severity_if_missing", "MEDIUM"),
        expected_value=expected,
        found_value="Not found in file",
        reason=item.get("description", ""),
        document_type=document_type,
        person_id=person_id,
    )


def _find_pages(pages: list[dict], document_type: str) -> list[dict]:
    return confident_pages_for_types(pages, [document_type])


def _find_pages_any_confidence(pages: list[dict], document_type: str) -> list[dict]:
    return [page for page in pages if page.get("document_type") == document_type]


def _document_types(value: str | list[str]) -> list[str]:
    return value if isinstance(value, list) else [value]


def _matching_pages(pages: list[dict], document_type: str | list[str]) -> list[dict]:
    return confident_pages_for_types(pages, _document_types(document_type))


def _field_from_pages(pages: list[dict], *field_names: str) -> tuple[object | None, dict | None]:
    for page in pages:
        fields = page.get("extracted_fields") or {}
        for field_name in field_names:
            if fields.get(field_name) not in (None, ""):
                return fields[field_name], page
    return None, None


def _normalized_status(value: object) -> str:
    return re.sub(r"[^a-z]+", " ", str(value or "").lower()).strip()


def _page_status(page: dict, field_names: list[str]) -> str:
    fields = page.get("extracted_fields") or {}
    for field_name in field_names:
        if fields.get(field_name) not in (None, ""):
            return _normalized_status(fields[field_name])
    text = str(page.get("ocr_text") or "")
    if (
        page.get("document_type") == "OTC PDD Document"
        and re.search(
            r"\brequest\s+legal\s+(?:otc\s*/?\s*pdd|pdd\s*/?\s*otc)\s+approval\b",
            text,
            re.IGNORECASE,
        )
        and re.search(r"(?mi)^\s*ok\s*$", text)
    ):
        return "approved"
    return _normalized_status(text)


def _is_positive_status(
    page: dict, accepted: list[str], rejected: list[str], fields: list[str]
) -> bool:
    status = _page_status(page, fields)
    if any(term.lower() in status for term in rejected):
        return False
    return any(term.lower() in status for term in accepted)


def _has_explicit_status_field(page: dict, fields: list[str]) -> bool:
    extracted = page.get("extracted_fields") or {}
    return any(extracted.get(name) not in (None, "") for name in fields)


def _status_looks_like_full_page_fallback(page: dict, fields: list[str]) -> bool:
    """True when status was inferred from whole-page OCR rather than a status field."""
    if _has_explicit_status_field(page, fields):
        return False
    status = _page_status(page, fields)
    return len(status) > 80


def _distinct_document_key(page: dict) -> str:
    return str(
        page.get("source_document_id")
        or page.get("document_instance_id")
        or page.get("report_id")
        or f"page:{page.get('page_number')}"
    )


def _document_derived_system_data(pages: list[dict]) -> dict[str, object]:
    """Derive conditional checklist inputs from explicit document evidence."""
    for page in pages:
        fields = page.get("extracted_fields") or {}
        status = fields.get("nach_status")
        if status in (None, ""):
            continue
        normalized = _normalized_status(status)
        if any(term in normalized for term in ("not registered", "not done", "failed", "inactive")):
            return {"nach_registered": False}
        if any(term in normalized for term in ("done", "registered", "active", "approved")):
            return {"nach_registered": True}
    return {}


def _non_loan_relevance_anomaly(
    pages: list[dict],
    presence_items: list[dict],
) -> dict | None:
    """Return one anomaly when uploaded file appears unrelated to loan processing.

    We only short-circuit when:
    - there are pages, and
    - no required checklist document type is detected anywhere, and
    - almost all pages are unclassified/unknown.
    """
    if not pages:
        return None

    expected_types: set[str] = set()
    for item in presence_items:
        document_type = item.get("document_type")
        if isinstance(document_type, str) and document_type:
            expected_types.add(document_type)
        elif isinstance(document_type, list):
            expected_types.update(str(value) for value in document_type if value)

    if not expected_types:
        return None

    doc_types = [str(page.get("document_type") or "").strip() for page in pages]
    matched_expected = sum(
        1
        for page in pages
        for expected_type in expected_types
        if is_confident_document_match(page, expected_type)
    )
    unknown_count = sum(1 for item in doc_types if item in {"", "Unknown", "None"})
    unknown_ratio = unknown_count / max(1, len(doc_types))

    config = effective_config()
    min_expected_matches = config.min_checklist_matches_for_loan_file
    max_unknown_ratio = config.max_unknown_ratio_for_unsupported_file

    # Keep valid loan files unaffected: only block weak, mostly-unclassified uploads.
    if matched_expected >= min_expected_matches or unknown_ratio < max_unknown_ratio:
        return None

    return build_anomaly(
        rule_id="UNSUPPORTED_DOCUMENT_TYPE",
        s_no=None,
        severity="HIGH",
        expected_value="Loan-file documents matching checklist",
        found_value=(
            f"Only {matched_expected} confident checklist document match(es) "
            f"across {len(pages)} pages"
        ),
        reason="Uploaded PDF appears unrelated to the loan checklist workflow.",
        page_number=1,
        document_type="Unsupported",
    )
