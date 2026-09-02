"""Consistency-check submodule."""

from __future__ import annotations

import re
from typing import Any

from services.consistency.matching import _lookup, _matches
from services.consistency.page_support import _page_text_supports_value


def _identity_affidavit_checks(
    pages: list[dict],
    anomalies: list[dict],
    people: dict[str, dict],
) -> list[dict]:
    """Require discrepancy-specific evidence when a name or DOB conflicts.

    A generic agreement clause mentioning the word ``affidavit`` is not enough.
    The evidence must be classified as a declaration/affidavit and explicitly
    discuss dual names, a name/DOB/signature mismatch, an alias, or the person's
    correct identity.
    """
    discrepancy_rules = {
        "TRUSTED_APPLICANT_NAME_MISMATCH",
        "APPLICATION_NAME_MISMATCH",
        "TRUSTED_DATE_OF_BIRTH_MISMATCH",
    }
    mismatches = [
        anomaly
        for anomaly in anomalies
        if str(anomaly.get("rule_id") or "") in discrepancy_rules
        and str(anomaly.get("severity") or "").upper() in {"HIGH", "MEDIUM"}
    ]
    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if page.get("page_number") is not None
    }
    mismatches = [
        anomaly
        for anomaly in mismatches
        if _identity_mismatch_is_affidavit_worthy(
            anomaly,
            pages_by_number.get(int(anomaly.get("page_number") or 0), {}),
            people.get(str(anomaly.get("person_id") or "primary"), {}),
        )
    ]
    if not mismatches:
        return []

    person_ids = {str(anomaly.get("person_id") or "primary") for anomaly in mismatches}
    results: list[dict] = []
    for person_id in sorted(person_ids):
        person_mismatches = [
            anomaly
            for anomaly in mismatches
            if str(anomaly.get("person_id") or "primary") == person_id
        ]
        person = people.get(person_id, {})
        if any(_is_identity_declaration(page, person_id, person) for page in pages):
            continue
        first = person_mismatches[0]
        mismatch_kinds = sorted(
            {
                "DOB" if "DATE_OF_BIRTH" in str(item.get("rule_id")) else "name"
                for item in person_mismatches
            }
        )
        results.append(
            {
                "rule_id": "IDENTITY_AFFIDAVIT_MISSING",
                "s_no": 8,
                "severity": "HIGH",
                "document_type": "Dual Name Declaration / Affidavit",
                "expected_value": (
                    "Signed affidavit/declaration resolving the "
                    + " and ".join(mismatch_kinds)
                    + " discrepancy"
                ),
                "found_value": "No discrepancy-specific declaration found",
                "page_number": first.get("page_number"),
                "person_id": person_id,
                "reason": (
                    "A reliable identity mismatch exists, but the packet does not contain a "
                    "dual-name/DOB/signature affidavit or declaration that resolves it."
                ),
            }
        )
    return results


def _identity_mismatch_is_affidavit_worthy(anomaly: dict, page: dict, person: dict) -> bool:
    """Reject ownership/extraction noise before cascading to affidavit rules."""
    if not isinstance(page, dict) or not isinstance(person, dict) or not person:
        return False
    if str(page.get("document_type") or "") not in {
        "Aadhaar",
        "PAN",
        "PAN Card",
        "Voter ID",
        "Driving License",
        "Passport",
        "KYC Card Photo",
        "Application Form",
    }:
        return False
    fields = page.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        return False

    exact_anchors = (
        "pan_number",
        "aadhaar_number",
        "aadhaar_last4",
        "phone_number",
        "customer_id",
    )
    has_exact_anchor = any(
        fields.get(field) not in (None, "")
        and _lookup(person, field) not in (None, "")
        and _matches(field, _lookup(person, field), fields.get(field))
        for field in exact_anchors
    )
    rule_id = str(anomaly.get("rule_id") or "")
    if "DATE_OF_BIRTH" in rule_id:
        if not _plausible_adult_date_of_birth(fields.get("date_of_birth") or fields.get("dob")):
            return False
        observed_name = fields.get("applicant_name") or fields.get("borrower_name")
        name_matches = observed_name not in (None, "") and _matches(
            "applicant_name", person.get("applicant_name"), observed_name
        )
        return bool(has_exact_anchor or name_matches)

    # A conflicting name must still be anchored to the same trusted person by
    # another identifier/date; otherwise it is probably another person's page.
    return bool(has_exact_anchor)


def _plausible_adult_date_of_birth(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        from datetime import date

        from dateutil import parser

        parsed = parser.parse(str(value), dayfirst=True).date()
        today = date.today()
        age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
        return 18 <= age <= 100
    except (TypeError, ValueError, OverflowError):
        return False


def _is_identity_declaration(page: dict, person_id: str, person: dict) -> bool:
    document_type = str(page.get("document_type") or "").casefold()
    provided_type = str(page.get("provided_document_type") or "").casefold()
    source_name = str(page.get("source_filename") or page.get("original_filename") or "").casefold()
    combined_type = f"{document_type} {provided_type} {source_name}"
    text = str(page.get("ocr_text") or "")
    lowered = text.casefold()
    has_declared_type = any(
        marker in combined_type
        for marker in ("affidavit", "dual name", "name declaration", "self declaration")
    )
    has_affidavit_form = bool(
        re.search(r"\b(?:affidavit|deponent|solemnly\s+affirm)\b|शपथ[\s-]*पत्र|हलफनामा", lowered)
        and re.search(r"\b(?:notary|verified|verification)\b|नोटरी|सशपथ|शपथग्रहिता|सत्यापन", lowered)
    )
    if not (has_declared_type or has_affidavit_form):
        return False

    page_person = str(page.get("person_id") or "unassigned")
    identity_markers = (
        "dual name",
        "mismatch of name",
        "mismatch of last name",
        "mismatch of surname",
        "dual date of birth",
        "correct name",
        "correct date of birth",
        "one and the same",
        "one & the same",
        "also known as",
        "alias",
        "my name as per",
        "name/surname",
        "name or signature",
    )
    has_english_identity_resolution = any(marker in lowered for marker in identity_markers)
    hindi_identity_families = sum(
        1
        for family in (
            ("नाम",),
            ("जन्म दिनांक", "जन्म तिथि"),
            ("आधार कार्ड", "आधार"),
            ("पेन कार्ड", "पैन कार्ड", "स्थायी लेखा"),
        )
        if any(marker in lowered for marker in family)
    )
    has_hindi_resolution = hindi_identity_families >= 3 and any(
        marker in lowered for marker in ("सही", "मान्य", "अंतर", "भिन्न", "अलग")
    )
    if not (has_english_identity_resolution or has_hindi_resolution):
        return False
    if page_person not in {"", "unassigned", "unknown", person_id}:
        return False
    expected_name = person.get("applicant_name") if isinstance(person, dict) else None
    if page_person == person_id or not expected_name:
        return True
    return _page_text_supports_value(text, expected_name)
