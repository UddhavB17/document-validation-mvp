"""Shared provenance and reliability gates for extracted field validation."""

from __future__ import annotations

import re
from typing import Any

from services.person_names import has_independent_identity_anchor, is_person_name_candidate


IDENTITY_FIELDS = {
    "applicant_name",
    "borrower_name",
    "account_holder_name",
    "customer_name",
    "date_of_birth",
    "dob",
    "pan_number",
    "aadhaar_number",
    "aadhaar_last4",
}
BUREAU_SCORE_FIELDS = {"credit_score", "cibil_score", "crif_score"}
BANKING_FIELDS = {
    "account_holder_name",
    "account_number",
    "ifsc",
    "bank_name",
    "branch",
    "account_type",
    "statement_period_start",
    "statement_period_end",
}
WEAK_INHERITED_METHODS = {"inherited", "sandwich_smoothed", "agreement_context_smoothed"}


def canonical_field(field: Any) -> str:
    aliases = {
        "name": "applicant_name",
        "borrower_name": "applicant_name",
        "customer_name": "applicant_name",
        "account_holder_name": "applicant_name",
        "dob": "date_of_birth",
        "mobile_number": "phone_number",
        "mobile_no": "phone_number",
        "pan": "pan_number",
        "aadhaar": "aadhaar_number",
        "aadhar": "aadhaar_number",
        "pincode": "pin_code",
    }
    key = re.sub(r"[^a-z0-9]+", "_", str(field or "").lower()).strip("_")
    return aliases.get(key, key)


def attach_field_provenance(
    page: dict[str, Any],
    *,
    source_document: dict[str, Any] | None = None,
) -> None:
    """Attach per-field provenance inside ``page['extracted_fields']``.

    The DB schema stores extracted fields as JSON, so provenance lives beside
    the public values under ``_field_provenance`` without requiring a migration.
    """
    fields = page.get("extracted_fields")
    if not isinstance(fields, dict):
        return
    classification = fields.get("_classification") if isinstance(fields.get("_classification"), dict) else {}
    source_segment = None
    if source_document:
        start = source_document.get("internal_page_start")
        end = source_document.get("internal_page_end")
        if start not in (None, "") and end not in (None, ""):
            source_segment = f"{start}-{end}" if start != end else str(start)
        page["source_document_id"] = source_document.get("source_document_id")
        page["source_filename"] = source_document.get("original_filename")
        page["source_segment"] = source_segment

    type_confidence = _float(page.get("classification_confidence"), 0.0)
    ocr_confidence = page.get("ocr_confidence")
    text_confidence = 1.0 if ocr_confidence in (None, "") else _float(ocr_confidence, 0.0)
    base_confidence = max(0.0, min(type_confidence or 0.0, text_confidence))
    method = str(page.get("detection_method") or classification.get("detection_method") or "")
    raw_type = str(classification.get("raw_document_type") or page.get("document_type") or "Unknown")
    smoothed = method in WEAK_INHERITED_METHODS

    provenance: dict[str, Any] = {}
    for field_name, value in list(fields.items()):
        if str(field_name).startswith("_") or value in (None, "", [], {}):
            continue
        field_key = canonical_field(field_name)
        confidence = base_confidence
        if smoothed and _is_raw_unknown(raw_type) and field_key in IDENTITY_FIELDS | BUREAU_SCORE_FIELDS | BANKING_FIELDS:
            confidence = min(confidence, 0.45)
        if field_key == "applicant_name" and not is_person_name_candidate(value):
            confidence = 0.0
        provenance[field_name] = {
            "source_pages": [page.get("page_number")],
            "source_file": page.get("source_filename"),
            "source_document_id": page.get("source_document_id"),
            "source_segment": page.get("source_segment") or source_segment,
            "extractor": str(page.get("document_type") or "Unknown"),
            "schema": str(page.get("provided_document_type") or page.get("document_type") or "Unknown"),
            "anchor_evidence": _anchor_evidence(page, field_key),
            "field_confidence": round(confidence, 3),
            "type_confidence": round(type_confidence, 3),
            "raw_document_type": raw_type,
            "smoothed_classification": smoothed,
            "detection_method": method,
        }
    if provenance:
        fields["_field_provenance"] = provenance


def field_reliable_for_validation(
    page: dict[str, Any],
    field: Any,
    value: Any,
    *,
    expected_document_type: str | None = None,
) -> bool:
    """Return True when a field is safe to use for trusted/cross-doc anomalies."""
    if value in (None, "", [], {}):
        return False
    field_key = canonical_field(field)
    fields = page.get("extracted_fields") or {}
    if field_key == "applicant_name" and not is_person_name_candidate(value):
        return False
    if isinstance(fields, dict) and fields.get("_identity_extraction_reliable") is False and field_key in IDENTITY_FIELDS:
        return False
    if _weak_smoothed_identity_page(page) and field_key in IDENTITY_FIELDS | BUREAU_SCORE_FIELDS | BANKING_FIELDS:
        return False
    if expected_document_type and not compatible_field_for_document(expected_document_type, field_key, page):
        return False
    provenance = _field_provenance(fields, field)
    if provenance:
        min_confidence = 0.60
        if field_key in {"applicant_name", "pan_number", "aadhaar_number", "date_of_birth"}:
            min_confidence = 0.65
        if _float(provenance.get("field_confidence"), 1.0) < min_confidence:
            return False
    return True


def compatible_field_for_document(document_type: str, field: str, page: dict[str, Any]) -> bool:
    doc_key = str(document_type or "").strip().lower()
    text = str(page.get("ocr_text") or "")
    fields = page.get("extracted_fields") or {}
    if doc_key in {"pan", "pan card"} and field in {"applicant_name", "date_of_birth", "pan_number"}:
        return has_pan_anchor(text, fields)
    if doc_key in {"bank statement"} and field in BANKING_FIELDS | {"applicant_name"}:
        return has_bank_statement_anchor(text, fields)
    if doc_key in {"passbook"} and field in BANKING_FIELDS | {"applicant_name"}:
        return has_passbook_anchor(text, fields)
    if doc_key in {"cheque"} and field in BANKING_FIELDS | {"applicant_name"}:
        return has_cheque_anchor(text, fields)
    if doc_key in {"crif report", "cibil report"} and field in BUREAU_SCORE_FIELDS | {"applicant_name"}:
        return has_bureau_anchor(text, fields, field)
    return True


def has_pan_anchor(text: str, fields: dict[str, Any]) -> bool:
    return bool(
        re.search(r"\b[A-Z]{5}\d{4}[A-Z]\b", text.upper())
        and re.search(r"\b(?:permanent\s+account\s+number|income\s+tax|govt\.?\s+of\s+india|pan)\b", text, re.I)
    ) or bool(fields.get("pan_number") and re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", str(fields.get("pan_number")).upper()))


def has_bank_statement_anchor(text: str, fields: dict[str, Any]) -> bool:
    lowered = text.lower()
    if not lowered.strip() and fields:
        return True
    if is_amortization_schedule(text):
        return False
    has_bank = bool(re.search(r"\b(bank|statement|account\s+statement|transaction|debit|credit|balance)\b", lowered))
    has_account = bool(fields.get("account_number") or fields.get("ifsc") or re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", text.upper()))
    has_period = bool(fields.get("statement_period_start") and fields.get("statement_period_end"))
    return has_bank and (has_account or has_period)


def has_passbook_anchor(text: str, fields: dict[str, Any]) -> bool:
    lowered = text.lower()
    if not lowered.strip() and fields:
        return True
    return bool("passbook" in lowered or "pass book" in lowered or fields.get("account_number") or fields.get("ifsc"))


def has_cheque_anchor(text: str, fields: dict[str, Any]) -> bool:
    lowered = text.lower()
    if not lowered.strip() and fields:
        return True
    return bool("cheque" in lowered or "check" in lowered or fields.get("cheque_number"))


def has_bureau_anchor(text: str, fields: dict[str, Any], field: str) -> bool:
    lowered = text.lower()
    if not lowered.strip() and fields:
        return True
    if not re.search(r"\b(crif|cibil|credit\s+information|credit\s+report|high\s+mark)\b", lowered):
        return False
    if field in BUREAU_SCORE_FIELDS:
        return bool(re.search(r"\bscore\s*(?:name|range|score|:)?", lowered) and fields.get(field) not in (None, "", "null", "unknown"))
    return True


def is_amortization_schedule(text: str) -> bool:
    lowered = text.lower()
    return bool(
        ("repayment schedule" in lowered or "amortisation" in lowered or "amortization" in lowered)
        and re.search(r"\bemi\b", lowered)
        and not re.search(r"\b(?:bank statement|account statement|transaction details)\b", lowered)
    )


def _weak_smoothed_identity_page(page: dict[str, Any]) -> bool:
    fields = page.get("extracted_fields") or {}
    classification = fields.get("_classification") if isinstance(fields, dict) else {}
    method = str(page.get("detection_method") or (classification or {}).get("detection_method") or "")
    raw_type = str((classification or {}).get("raw_document_type") or "")
    if method not in WEAK_INHERITED_METHODS or not _is_raw_unknown(raw_type):
        return False
    return not (isinstance(fields, dict) and has_independent_identity_anchor(fields))


def _anchor_evidence(page: dict[str, Any], field: str) -> list[str]:
    fields = page.get("extracted_fields") or {}
    if field == "applicant_name" and isinstance(fields, dict):
        anchors = [
            anchor for anchor in ("pan_number", "aadhaar_number", "aadhaar_last4", "date_of_birth", "dob", "phone_number")
            if fields.get(anchor) not in (None, "", [], {})
        ]
        return anchors or ["label_or_context"]
    if field in BUREAU_SCORE_FIELDS:
        return ["bureau_score_table"]
    if field in BANKING_FIELDS:
        return ["banking_anchor"]
    return ["field_label"]


def _field_provenance(fields: Any, field: Any) -> dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    provenance = fields.get("_field_provenance")
    if not isinstance(provenance, dict):
        return {}
    if str(field) in provenance and isinstance(provenance[str(field)], dict):
        return provenance[str(field)]
    field_key = canonical_field(field)
    for key, item in provenance.items():
        if canonical_field(key) == field_key and isinstance(item, dict):
            return item
    return {}


def _is_raw_unknown(value: str) -> bool:
    return str(value or "").strip().lower() in {"", "none", "unknown", "ocr skipped"}


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
