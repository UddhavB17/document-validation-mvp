"""Shared provenance and reliability gates for extracted field validation."""

from __future__ import annotations

import re
from typing import Any

from services.cersai import is_debtor_based, search_criteria_text
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


def is_aadhaar_verification_appendix(text: Any) -> bool:
    """Return True for the signed-XML appendix bundled with some e-Aadhaar PDFs.

    The appendix contains both the holder's signed ``Poa`` data and the signing
    certificate's address.  It is verification evidence, not a second source
    of demographic fields.
    """
    raw = str(text or "")
    non_empty_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    heading = " ".join(non_empty_lines[:8])
    if not re.search(
        r"\bdigitally\s+signed\s+e[\s-]*aadhaar\s+xml\b",
        heading,
        re.IGNORECASE,
    ):
        return False
    return bool(re.search(
        r"<\s*(?:Certificate|KycRes|UidData)\b|"
        r"\b(?:X509Certificate|SignatureValue|DigestValue)\b",
        raw,
        re.IGNORECASE,
    ))


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
    recovery_metadata = fields.get("_trusted_candidate_recovery")
    if not isinstance(recovery_metadata, dict):
        recovery_metadata = {}

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
        recovery = recovery_metadata.get(field_key)
        if not isinstance(recovery, dict):
            recovery = None
        if recovery is not None:
            confidence = min(
                text_confidence,
                _float(recovery.get("confidence"), confidence),
            )
        item = {
            "source_pages": [page.get("page_number")],
            "source_file": page.get("source_filename"),
            "source_document_id": page.get("source_document_id"),
            "source_segment": page.get("source_segment") or source_segment,
            "extractor": str(page.get("document_type") or "Unknown"),
            "schema": str(page.get("provided_document_type") or page.get("document_type") or "Unknown"),
            "anchor_evidence": (
                [recovery.get("anchor"), "trusted_value_present_in_ocr"]
                if recovery is not None
                else _anchor_evidence(page, field_key)
            ),
            "field_confidence": round(confidence, 3),
            "type_confidence": round(type_confidence, 3),
            "raw_document_type": raw_type,
            "smoothed_classification": smoothed,
            "detection_method": method,
        }
        if recovery is not None:
            item.update({
                "resolution_method": "trusted_candidate_match",
                "match_method": recovery.get("match_method"),
                "ocr_line": recovery.get("ocr_line"),
            })
        provenance[field_name] = item
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
    if (
        str(expected_document_type or page.get("document_type") or "").strip().casefold()
        == "aadhaar"
        and (
            (isinstance(fields, dict) and fields.get("_aadhaar_verification_appendix") is True)
            or is_aadhaar_verification_appendix(page.get("ocr_text"))
        )
    ):
        # Also protects cached runs that still contain fields extracted before
        # the appendix marker was introduced.
        return False
    if field_key == "applicant_name" and not is_person_name_candidate(value):
        return False
    if (
        str(expected_document_type or page.get("document_type") or "").strip().casefold()
        == "application form"
        and field_key == "aadhaar_number"
        and not has_labeled_aadhaar_value(str(page.get("ocr_text") or ""), value)
    ):
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
    if doc_key == "application form" and field == "application_number":
        from services.document_classifier import (
            is_insurance_application_context,
            is_insurer_local_application_identifier,
        )

        if is_insurance_application_context(text) and is_insurer_local_application_identifier(
            text, fields.get(field)
        ):
            return False
    if doc_key in {
        "insurance form", "life insurance form", "property insurance form"
    } and field == "application_number":
        from services.document_classifier import is_insurer_local_application_identifier

        if is_insurer_local_application_identifier(text, fields.get(field)):
            return False
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
    if doc_key == "cersai report" and field in {
        "applicant_name", "date_of_birth", "pan_number"
    }:
        return _has_cersai_debtor_anchor(text, fields, field)
    return True


def _has_cersai_debtor_anchor(text: str, fields: dict[str, Any], field: str) -> bool:
    """Accept CERSAI identity only when it belongs to the entered debtor."""
    if not is_debtor_based(text, fields):
        return False
    debtor_alias = {
        "applicant_name": "debtor_name",
        "pan_number": "debtor_pan_number",
        "date_of_birth": "debtor_date_of_birth",
    }[field]
    value = fields.get(field)
    debtor_value = fields.get(debtor_alias)
    if value not in (None, "") and debtor_value not in (None, ""):
        left = re.sub(r"[^a-z0-9]+", "", str(value).casefold())
        right = re.sub(r"[^a-z0-9]+", "", str(debtor_value).casefold())
        if left and left == right:
            return True
    criteria = search_criteria_text(text)
    compact_value = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    compact_criteria = re.sub(r"[^a-z0-9]+", "", criteria.casefold())
    return bool(compact_value and compact_value in compact_criteria)


def has_pan_anchor(text: str, fields: dict[str, Any]) -> bool:
    return bool(
        re.search(r"\b[A-Z]{5}\d{4}[A-Z]\b", text.upper())
        and re.search(r"\b(?:permanent\s+account\s+number|income\s+tax|govt\.?\s+of\s+india|pan)\b", text, re.I)
    ) or bool(fields.get("pan_number") and re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", str(fields.get("pan_number")).upper()))


def has_labeled_aadhaar_value(text: str, value: Any) -> bool:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 12:
        return False
    for match in re.finditer(r"(?<!\d)\d{4}[ \t]?\d{4}[ \t]?\d{4}(?!\d)", text):
        if re.sub(r"\D", "", match.group(0)) != digits:
            continue
        window = text[max(0, match.start() - 180) : min(len(text), match.end() + 60)]
        if re.search(r"\b(?:aadhaar|aadhar|uid)\b|आधार", window, re.I):
            return True
    return False


def has_intrinsic_aadhaar_evidence(text: str) -> bool:
    """Return True only when the page itself is an Aadhaar credential.

    Consent forms and address declarations often mention Aadhaar/UIDAI in body
    prose. Those mentions are not evidence that the page is an Aadhaar card.
    """
    raw = str(text or "")
    non_empty_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    heading = " ".join(non_empty_lines[:6]).casefold()
    if re.search(r"\bself[\s-]*declaration\b[\s\S]{0,80}\bcurrent\s+address\b", heading, re.I):
        return False
    authority_heading = any(
        marker in heading
        for marker in (
            "unique identification authority",
            "uidai",
            "e-aadhaar",
            "digilocker verified e-aadhaar",
            "भारतीय विशिष्ट पहचान प्राधिकरण",
            "मेरा आधार",
        )
    )
    aadhaar_numbers = list(
        re.finditer(r"(?<!\d)\d{4}[ \t]?\d{4}[ \t]?\d{4}(?!\d)", raw)
    )
    for match in aadhaar_numbers:
        if has_labeled_aadhaar_value(raw, match.group(0)):
            return True
    government_heading = any(
        marker in heading
        for marker in ("government of india", "govt. of india", "भारत सरकार")
    )
    aadhaar_xml = bool(
        re.search(r"<\s*PrintLetterBarcodeData\b", raw, re.I)
        and re.search(r"\buid\s*=\s*['\"]\d{12}['\"]", raw, re.I)
    )
    return authority_heading or aadhaar_xml or bool(government_heading and aadhaar_numbers)


def has_bank_statement_anchor(text: str, fields: dict[str, Any]) -> bool:
    lowered = text.lower()
    if is_amortization_schedule(text):
        return False
    if _is_disbursal_continuation(text):
        return False

    has_account = bool(
        fields.get("account_number")
        or fields.get("ifsc")
        or re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", text.upper())
        or re.search(
            r"\b(?:a/?c|account)\s*(?:number|no\.?|#)\s*[:\-]?\s*(?:[X*]{2,}\d{3,}|\d{6,18})\b",
            text,
            re.IGNORECASE,
        )
    )
    if not lowered.strip():
        return has_account

    has_bank_context = bool(
        re.search(
            r"\b(?:bank|account\s+statement|bank\s+statement|statement\s+of\s+account|"
            r"transaction|debit|credit|balance)\b",
            lowered,
        )
    )
    return has_bank_context and (has_account or _has_transaction_table_signature(text))


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
    # A lender's statement of account legitimately contains principal,
    # interest, instalment and balance columns. Its explicit statement title
    # and transaction ledger are stronger semantic evidence than those shared
    # financial terms.
    statement_evidence = bool(re.search(
        r"\b(?:bank statement|account statement|statement of account|"
        r"customer(?:'s)? statement of account|transaction details)\b",
        lowered,
    ))
    transaction_evidence = _has_transaction_table_signature(text) or sum(
        1
        for marker in (
            "particulars", "amount received", "instrument no", "receipt no",
            "txn date", "value date", "opening balance",
        )
        if marker in lowered
    ) >= 3
    explicit_schedule = (
        "repayment schedule" in lowered
        or "amortisation" in lowered
        or "amortization" in lowered
    ) and bool(re.search(r"\bemi\b", lowered))
    schedule_table = all(
        re.search(pattern, lowered)
        for pattern in (r"\bprincipal\b", r"\binterest\b", r"\b(?:emi|instal+ment)\b", r"\bbalance\b")
    )
    return bool(
        (explicit_schedule or schedule_table)
        and not (statement_evidence and transaction_evidence)
    )


def _has_transaction_table_signature(text: str) -> bool:
    """Require a genuine bank-ledger column set, not merely two parsed dates."""
    lowered = str(text or "").lower()
    has_date = bool(re.search(r"\b(?:txn\.?\s*date|transaction\s+date|value\s+date|date)\b", lowered))
    has_narration = bool(re.search(r"\b(?:narration|particulars|description|remarks)\b", lowered))
    has_debit = bool(re.search(r"\b(?:debit|withdrawal|withdrawals|dr)\.?\b", lowered))
    has_credit = bool(re.search(r"\b(?:credit|deposit|deposits|cr)\.?\b", lowered))
    has_balance = bool(re.search(r"\b(?:balance|running\s+balance)\b", lowered))
    return has_date and has_narration and has_debit and has_credit and has_balance


def _is_disbursal_continuation(text: str) -> bool:
    lowered = str(text or "").lower()
    if re.search(r"\b(?:request\s+for\s+disburs(?:al|ement)|drawdown\s+request)\b", lowered):
        return True
    return bool(
        re.search(r"\bforeclosure\s+letter\b", lowered)
        and re.search(r"\bstatement\s+of\s+account\b", lowered)
        and re.search(r"\btime\s+of\s+disbursement\b", lowered)
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
