"""Consistency-check submodule."""

from __future__ import annotations

import re
from typing import Any

from services.consistency.constants import (
    ADDRESS_FIELDS,
    DATE_FIELDS,
    HOLDER_NAME_FIELDS,
    NAME_FIELDS,
    PERSON_FIELDS,
)
from services.consistency.matching import (
    _canonical,
    _lookup,
    _matches,
    _names_equivalent,
    _similarity,
    _trusted_address_variants,
)
from services.consistency.page_support import _find_supporting_page_number
from services.document_classifier import (
    is_insurance_application_context,
    is_insurer_local_application_identifier,
)
from services.field_verification import address_with_relationship
from services.person_names import (
    is_person_name_candidate,
)
from services.validation_gates import field_reliable_for_validation


def _people(trusted: dict) -> dict[str, dict]:
    raw = trusted.get("people") or trusted.get("reference_data") or {}
    return (
        {str(key): value for key, value in raw.items() if isinstance(value, dict)}
        if isinstance(raw, dict)
        else {}
    )


def _observations(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    result: list[dict] = []
    multi_person_section_roles: dict[str, str] = {}
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        fields = page.get("extracted_fields") or {}
        person_id = str(page.get("person_id") or page.get("applicant_role") or "").strip()
        if not person_id or person_id in {"unknown"}:
            person_id = _infer_person(fields, people, str(page.get("document_type") or ""))
        person_records = fields.get("person_records")
        type_key = str(page.get("document_type") or "").strip().casefold()
        if type_key == "utility bill":
            # Business requirement: recognize presence only. Never turn noisy
            # provider/date/address extraction into a consistency anomaly.
            continue
        is_multi_person_type = type_key in {"application form", "cam"}
        section_role = "primary"
        if is_multi_person_type:
            context_key = _multi_person_context_key(page, fields)
            role_hint = _multi_person_section_role(str(page.get("ocr_text") or ""))
            if role_hint:
                multi_person_section_roles[context_key] = role_hint
            section_role = multi_person_section_roles.setdefault(context_key, "primary")
        has_person_rows = isinstance(person_records, list) and any(
            isinstance(record, dict) and bool(record) for record in person_records
        )
        misowned_application_section = (
            type_key == "application form"
            and section_role in {"coapplicant", "guarantor"}
            and not _section_role_matches_person(section_role, person_id, people)
        )
        multi_person_container = is_multi_person_type and (
            has_person_rows or misowned_application_section
        )
        if isinstance(person_records, list):
            for record in person_records:
                if not isinstance(record, dict):
                    continue
                provided_record_id = str(record.get("_resolved_person_id") or "").strip()
                record_person_id = (
                    provided_record_id
                    if provided_record_id in people
                    else _infer_person(record, people, "Application Form")
                ) or "unassigned"
                for field, value in record.items():
                    if str(field).startswith("_") or value in (None, "", [], {}):
                        continue
                    canonical_field = _canonical(str(field))
                    if canonical_field in ADDRESS_FIELDS and _is_guarantor_person(
                        record_person_id, people
                    ):
                        # Guarantors can supply their own address as supporting
                        # evidence. It is not an applicant/co-applicant address
                        # variant and must not enter address consistency checks.
                        continue
                    comparison_value = (
                        address_with_relationship(value, record)
                        if canonical_field in ADDRESS_FIELDS
                        else value
                    )
                    if not _usable_observation_value(
                        str(page.get("document_type") or "Unknown"),
                        canonical_field,
                        comparison_value,
                        str(page.get("ocr_text") or ""),
                    ):
                        continue
                    if not _observation_is_reliable(page, canonical_field, comparison_value):
                        continue
                    result.append(
                        {
                            "person_id": record_person_id,
                            "field": canonical_field,
                            "value": comparison_value,
                            "document_type": str(page.get("document_type") or "Unknown"),
                            "page_number": _find_supporting_page_number(pages, page, value),
                            "ocr_text": page.get("ocr_text"),
                        }
                    )
        for field, value in fields.items():
            if (
                str(field).startswith("_")
                or field in {"person_records", "repayment_schedule_rows"}
                or value in (None, "", [], {})
            ):
                continue
            canonical_field = _canonical(str(field))
            if canonical_field in ADDRESS_FIELDS and _is_guarantor_person(person_id, people):
                # Keep guarantor documents in the packet, but exclude their
                # address from borrower/co-borrower validation.
                continue
            if multi_person_container and canonical_field in PERSON_FIELDS:
                # Application/CAM pages are multi-person containers even when
                # OCR cannot assemble a person_records row in an explicitly
                # marked guarantor/co-applicant section. Re-reading that flat
                # value as primary creates high-severity false mismatches.
                continue
            comparison_value = (
                address_with_relationship(value, fields)
                if canonical_field in ADDRESS_FIELDS
                else value
            )
            if not _usable_observation_value(
                str(page.get("document_type") or "Unknown"),
                canonical_field,
                comparison_value,
                str(page.get("ocr_text") or ""),
            ):
                continue
            if not _observation_is_reliable(page, canonical_field, comparison_value):
                continue
            result.append(
                {
                    "person_id": person_id or "unassigned",
                    "field": canonical_field,
                    "value": comparison_value,
                    "document_type": str(page.get("document_type") or "Unknown"),
                    "page_number": _find_supporting_page_number(pages, page, value),
                    "ocr_text": page.get("ocr_text"),
                }
            )
    return result


def _multi_person_context_key(page: dict, fields: dict) -> str:
    resolution = fields.get("_evidence_resolution")
    if isinstance(resolution, dict) and resolution.get("document_id"):
        return str(resolution["document_id"])
    return str(
        page.get("source_document_id")
        or page.get("source_filename")
        or f"{page.get('document_type')}:{page.get('page_number')}"
    )


def _multi_person_section_role(text: str) -> str | None:
    """Infer an explicit role section while allowing it to continue on later pages."""
    # Multi-person form sections often start below a KYC table or bilingual
    # labels. Inspect a bounded page header/body window and use the first
    # explicit section marker instead of defaulting an entire page to primary.
    header = " ".join(str(text or "").splitlines()[:96]).casefold()
    header = re.sub(r"[^a-z0-9\- ]+", " ", header)
    header = re.sub(r"\s+", " ", header).strip()
    if not header:
        return None
    role_patterns = {
        "primary": (
            r"\b(?:loan\s+application\s+form|application\s+details)\b",
            r"\b(?:details\s+of\s+security|bank\s+account\s+details|"
            r"existing\s+credit\s+facilities|loan\s+purpose|declaration)\b",
        ),
        "guarantor": (r"\bguarantor(?:\s+details|\s+address|\s+kyc|\s+employment|\s+business)?\b",),
        "coapplicant": (
            r"\b(?:co[\s-]*applicant|co[\s-]*borrower)"
            r"(?:\s+details|\s+address|\s+kyc|\s+personal)?\b",
        ),
    }
    matches = [
        (match.start(), role)
        for role, patterns in role_patterns.items()
        for pattern in patterns
        if (match := re.search(pattern, header))
    ]
    return min(matches)[1] if matches else None


def _section_role_matches_person(
    section_role: str,
    person_id: str,
    people: dict[str, dict],
) -> bool:
    if not person_id or person_id in {"unassigned", "unknown"}:
        return False
    person = people.get(person_id) or {}
    role_text = " ".join(
        str(value or "")
        for value in (
            person_id,
            person.get("role"),
            person.get("applicant_role"),
            person.get("person_role"),
        )
    ).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "", role_text)
    if section_role == "primary":
        return person_id == "primary" or normalized in {"applicant", "primaryapplicant"}
    if section_role == "coapplicant":
        return "coapplicant" in normalized or "coborrower" in normalized
    if section_role == "guarantor":
        return "guarantor" in normalized
    return False


def _is_guarantor_person(person_id: str, people: dict[str, dict]) -> bool:
    """Return whether an owner is a guarantor, including numbered IDs."""
    if not person_id or person_id in {"unassigned", "unknown"}:
        return False
    person = people.get(person_id) or {}
    role_text = " ".join(
        str(value or "")
        for value in (
            person_id,
            person.get("role"),
            person.get("applicant_role"),
            person.get("person_role"),
        )
    ).casefold()
    return "guarantor" in re.sub(r"[^a-z0-9]+", "", role_text)


def _usable_observation_value(
    document_type: str,
    field: str,
    value: Any,
    ocr_text: str = "",
) -> bool:
    if not _field_is_semantically_valid(document_type, field, ocr_text, value):
        return False
    if _is_garbage_extracted_value(field, value):
        return False
    return True


def _is_garbage_extracted_value(field: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    try:
        from services.field_assignment_refiner import is_suspicious_assignment

        if is_suspicious_assignment(field, text):
            return True
    except ImportError:
        # Optional refinement helper; absence should not block garbage detection.
        pass

    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    if field in NAME_FIELDS | {"applicant_name"}:
        # Relationship labels / OCR form debris mistaken for names.
        if re.fullmatch(
            r"(?:c/?o|s/?o|w/?o|d/?o)(?:\s*[,/]\s*(?:c/?o|s/?o|w/?o|d/?o))*", text.strip(), re.I
        ):
            return True
        if compact in {"coso", "soco", "wo", "so", "co", "do", "null", "none", "name"}:
            return True
        latin_letters = re.sub(r"[^a-zA-Z]", "", text)
        if len(latin_letters) < 3 and not re.search(r"[\u0900-\u097f]{3,}", text):
            return True
        if re.search(r"[<>{}=]|xmlns|http", text, re.I):
            return True

    if field in DATE_FIELDS:
        # Masked EPIC/Aadhaar style dates are not comparable to trusted DOB.
        if re.search(r"\bxx\b", text, re.I) or "xxxx" in text.lower():
            return True
        if not re.search(r"\d", text):
            return True

    if field in ADDRESS_FIELDS:
        if re.fullmatch(r"(?:landmark|locality|city|district|pin\s*code|/)+", text, re.I):
            return True
        if len(re.findall(r"[a-zA-Z\u0900-\u097f]", text)) < 6:
            return True
        if re.search(
            r"\b(?:website|helpline|gst\s*(?:no|number)|"
            r"unique\s+identification\s+authority|guarantor\s+"
            r"(?:(?:employment|employement)(?:\s*/?\s*business)?|business|kyc)?\s*details)\b|"
            r"भारतीय\s+विशिष्ट\s+पहचान\s+प्राधिकरण|www\.|\S+@\S+",
            text,
            re.I,
        ):
            return True

    if field == "pin_code":
        digits = re.sub(r"\D", "", text)
        if not re.fullmatch(r"[1-9]\d{5}", digits):
            return True

    if field in {"credit_score", "cibil_score", "crif_score"}:
        cleaned = text.strip(" '\"()[]")
        if not re.fullmatch(r"(?:0|[3-9]\d{2})", cleaned):
            return True

    return False


def _field_is_semantically_valid(
    document_type: str,
    field: str,
    ocr_text: str = "",
    value: Any = None,
) -> bool:
    """Reject fields whose labels mean something different in this document.

    A bureau report's BRANCH ID, APR month column, and historic sanctioned
    amount are not the loan-file branch, annual percentage rate, or current
    sanction amount.
    """
    if (
        document_type == "Application Form"
        and field == "application_number"
        and is_insurance_application_context(ocr_text)
        and is_insurer_local_application_identifier(ocr_text, value)
    ):
        # Cached runs can retain the old generic type and an insurer-local
        # application number.  It is not the loan application identifier.
        return False
    document_key = str(document_type or "").strip().casefold()
    if (
        document_key in {"insurance form", "life insurance form", "property insurance form"}
        and field == "application_number"
        and is_insurer_local_application_identifier(ocr_text, value)
    ):
        # Insurer proposal/application IDs are not loan application numbers.
        return False
    if document_key in {"crif report", "cibil report"} and field in {
        "branch",
        "apr",
        "roi",
        "sanction_amount",
        "loan_amount",
        "processing_fee",
        # Bureau phone numbers are often historic/shared-family and should not
        # create TRUSTED_PHONE mismatches against CRM numbers.
        "phone_number",
        "bank_linked_mobile",
    }:
        return False
    if field in {
        "loan_amount",
        "sanction_amount",
        "requested_amount",
        "recommended_amount",
    } and document_key in {
        "gst certificate",
        "utility bill",
        "bank statement",
        "passbook",
        "cheque",
        "nach form",
        "affidavit",
        "insurance form",
        "life insurance form",
        "property insurance form",
    }:
        # Tax/premium/ledger amounts do not establish the current loan terms.
        # This also protects consistency checks that read older cached runs.
        return False
    if document_key == "cersai report" and field in {
        # CERSAI debtor-search DOB is frequently OCR/parser noise relative to KYC.
        "date_of_birth",
        "dob",
        "phone_number",
    }:
        return False
    if document_key in {"technical report", "technical clearance report"} and field in {
        "phone_number",
        "email",
        "branch",
    }:
        return False
    if document_key in {"bank statement", "passbook", "cheque", "nach form"} and field == "branch":
        # The account-servicing bank branch is a different semantic field from
        # the lender/originating branch stored in the loan JSON.
        return False
    return True


def _infer_person(fields: dict, people: dict[str, dict], document_type: str = "") -> str:
    if not people:
        return ""
    try:
        from services.person_ownership import resolve_person_owner

        owner = resolve_person_owner(
            {"extracted_fields": fields, "document_type": document_type},
            people,
            document_type,
        )
        person_id = owner.get("person_id")
        return str(person_id) if person_id else ""
    except (ImportError, TypeError, ValueError, KeyError, AttributeError):
        # Fall back to lightweight name similarity when ownership resolution is unavailable.
        pass
    observed = (
        fields.get("applicant_name")
        or fields.get("borrower_name")
        or fields.get("account_holder_name")
    )
    if observed and is_person_name_candidate(observed):
        ranked = [
            (_similarity(observed, person.get("applicant_name")), person_id)
            for person_id, person in people.items()
        ]
        if ranked and max(ranked)[0] >= 0.82:
            return max(ranked)[1]
    return ""


def _observation_anchor_rank(obs: dict, field: str, person: dict) -> tuple[int, int, int]:
    """Prefer semantically authoritative, trusted-matching observations.

    Page order is not evidence quality. In particular, an early tax, premium,
    or transaction amount must never become the reference loan amount merely
    because it was encountered first.
    """
    value = obs.get("value")
    trusted_values = (
        _trusted_address_variants(person) if field in ADDRESS_FIELDS else [_lookup(person, field)]
    )
    trusted_match = int(
        any(
            expected not in (None, "") and _matches(field, expected, value)
            for expected in trusted_values
        )
    )
    document_type = str(obs.get("document_type") or "").casefold()
    authority: dict[str, int]
    if field in {"loan_amount", "sanction_amount", "requested_amount", "recommended_amount"}:
        authority = {
            "cam": 8,
            "sanction letter": 8,
            "kfs": 8,
            "facility agreement": 7,
            "loan agreement": 7,
            "application form": 6,
        }
    elif field in HOLDER_NAME_FIELDS:
        authority = {
            "aadhaar": 8,
            "pan": 8,
            "pan card": 8,
            "passport": 8,
            "voter id": 7,
            "driving license": 7,
            "application form": 5,
            "cam": 5,
            "bank statement": 4,
        }
    elif field in ADDRESS_FIELDS:
        authority = {
            "aadhaar": 8,
            "passport": 8,
            "voter id": 7,
            "driving license": 7,
            "utility bill": 6,
            "application form": 5,
        }
    else:
        authority = {}
    value_detail = min(20, len(re.findall(r"[A-Za-z0-9\u0900-\u097f]+", str(value or ""))))
    return trusted_match, authority.get(document_type, 1), value_detail


def _name_observation_is_reliable(page: dict, field: str, value: Any) -> bool:
    if field not in NAME_FIELDS:
        return True
    fields = page.get("extracted_fields") or {}
    if isinstance(fields, dict) and fields.get("_identity_extraction_reliable") is False:
        return False
    if (
        str(page.get("document_type") or "").strip().casefold() == "aadhaar"
        and isinstance(fields, dict)
        and fields.get("related_person_name") not in (None, "")
        and _names_equivalent(value, fields.get("related_person_name"))
    ):
        # Aadhaar back sides print S/O, W/O, D/O or C/O. Older cached
        # extraction sometimes copied that relative into applicant_name.
        return False
    return is_person_name_candidate(value)


def _observation_is_reliable(page: dict, field: str, value: Any) -> bool:
    if not _name_observation_is_reliable(page, field, value):
        return False
    return field_reliable_for_validation(
        page,
        field,
        value,
        expected_document_type=str(page.get("document_type") or "Unknown"),
    )
