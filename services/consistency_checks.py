"""Cross-document and trusted-data consistency checks for loan packets."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from services.bureau_scores import has_explicit_no_score_evidence
from services.person_names import (
    canonicalize_person_name,
    comparable_name,
    is_person_name_candidate,
    name_similarity,
    names_match,
)
from services.document_classifier import (
    is_insurance_application_context,
    is_insurer_local_application_identifier,
)
from services.field_verification import address_with_relationship
from services.validation_gates import field_reliable_for_validation
from services.language_detection import (
    analyze_text_languages,
    normalize_language_code,
)


EXACT_FIELDS = {
    "loan_id", "application_number", "account_number", "pan_number",
    "aadhaar_number", "aadhaar_last4", "voter_id_number", "dl_number",
    "gstin", "ifsc", "pin_code", "phone_number", "customer_id",
    "stamp_certificate_number", "stamp_unique_document_reference",
}
NUMERIC_FIELDS = {
    "loan_amount", "requested_amount", "recommended_amount", "sanction_amount",
    "tenure", "roi", "interest_rate", "apr", "emi", "first_emi", "final_emi",
    "processing_fee", "insurance_amount", "net_disbursement", "foir", "ltv",
    "monthly_income", "verified_income", "considered_income", "monthly_obligations",
    "available_income", "maximum_emi", "turnover", "margin", "cibil_score", "crif_score",
    "installment_count", "total_interest", "total_repayment", "other_charges",
    "property_value", "market_value", "distress_value", "land_value",
    "construction_value", "property_area", "mandate_amount",
    "stamp_duty_amount", "stamp_consideration_amount",
}
NAME_FIELDS = {"applicant_name", "borrower_name", "account_holder_name", "father_name", "mother_name"}
HOLDER_NAME_FIELDS = {"applicant_name", "borrower_name", "account_holder_name"}
ADDRESS_FIELDS = {"address", "current_address", "permanent_address", "communication_address"}
DATE_FIELDS = {
    "date_of_birth", "repayment_start_date", "maturity_date", "mandate_validity",
    "occupied_since", "stamp_date",
}

# These are the requested JSON-to-document comparison fields. A field is checked
# whenever both the trusted dump and at least one document expose it.
PERSON_FIELDS = {
    "applicant_name", "salutation", "customer_id", "pan_number", "aadhaar_number",
    "aadhaar_last4", "voter_id_number", "dl_number", "ration_card_number", "gstin",
    "udyam_status", "kyc_status", "profile_photograph_present", "facial_identity_status",
    "date_of_birth", "dob", "age", "gender",
    "marital_status", "qualification", "profession", "disability_status", "ews_status",
    "caste", "religion", "medical_condition", "father_name", "mother_name", "relationship",
    "phone_number", "email", "bank_linked_mobile", "current_address", "permanent_address",
    "communication_address", "address", "address_ownership", "address_subtype", "landmark",
    "locality", "tehsil", "district", "state", "country", "pin_code", "occupied_since",
    "latitude", "longitude", "employment_type", "income_source", "occupation", "work_profile",
    "industry", "job_role", "job_description", "monthly_income", "verified_income",
    "considered_income", "turnover", "margin", "years_current_work", "overall_experience",
    "income_stability", "verification_method", "income_proof_basis", "verification_status",
    "verifier", "field_remarks", "account_holder_name", "account_number", "bank_name", "branch",
    "ifsc", "account_type", "bank_verification_status", "primary_account", "nach_status",
    "mandate_amount", "mandate_validity", "payment_destination", "six_month_banking_required",
    "cibil_score", "crif_score", "bureau_account_count",
    "overdue_account_count", "dpd_status", "credit_report_id", "monthly_obligations",
    "available_income", "maximum_emi", "foir", "all_bureau_accounts_considered",
    "zero_obligation_supported", "property_owner", "ownership_type", "property_role",
    "age_policy_deviation", "age_deviation_approval", "guarantor_role",
}
LOAN_FIELDS = {
    "loan_id", "application_number", "account_number", "loan_purpose", "product_type",
    "requested_amount", "recommended_amount", "sanction_amount", "loan_amount", "roi",
    "interest_rate", "apr", "tenure", "emi", "first_emi", "final_emi",
    "repayment_start_date", "maturity_date", "installment_count", "total_interest",
    "total_repayment", "processing_fee", "insurance_amount", "other_charges",
    "net_disbursement", "foir", "ltv", "property_owner", "property_value", "market_value",
    "distress_value", "land_value", "construction_value", "property_area", "property_address",
    "site_address", "property_usage", "occupancy", "property_condition", "construction_status",
    "sanction_conditions", "approved_deviations", "pending_conditions", "tranche_structure",
    "workflow_status", "repayment_status", "overdue_status",
    "stamp_certificate_number", "stamp_unique_document_reference", "stamp_account_reference",
    "stamp_jurisdiction_state", "stamp_duty_amount", "stamp_consideration_amount",
    "stamp_instrument_description", "stamp_article", "stamp_purchased_by", "stamp_first_party",
    "stamp_second_party", "stamp_date",
}


def run_consistency_checks(pages: list[dict], trusted: dict) -> list[dict]:
    anomalies: list[dict] = []
    people = _people(trusted)
    # Ensure pages carry person_id even when callers skip checklist assign.
    try:
        from services.person_ownership import assign_page_owners

        assign_page_owners(pages, {"people": people, **(trusted or {})})
    except Exception:
        pass
    observations = _observations(pages, people)

    anomalies.extend(_trusted_matches(observations, people, trusted))
    anomalies.extend(_application_name_checks(pages, people))
    anomalies.extend(_cross_document_matches(observations, people))
    anomalies.extend(_aadhaar_address_checks(observations, people))
    anomalies.extend(_relationship_checks(observations, people))
    anomalies.extend(_bureau_checks(pages, observations))
    anomalies.extend(_application_language_checks(pages, trusted))
    from services.repayment_schedule import validate_repayment_schedules

    anomalies.extend(validate_repayment_schedules(pages, trusted))
    anomalies.extend(_identity_affidavit_checks(pages, anomalies, people))
    return anomalies


def _people(trusted: dict) -> dict[str, dict]:
    raw = trusted.get("people") or trusted.get("reference_data") or {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)} if isinstance(raw, dict) else {}


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
        has_person_rows = (
            isinstance(person_records, list)
            and any(isinstance(record, dict) and bool(record) for record in person_records)
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
                    if (
                        canonical_field in ADDRESS_FIELDS
                        and _is_guarantor_person(record_person_id, people)
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
                    if not _observation_is_reliable(
                        page, canonical_field, comparison_value
                    ):
                        continue
                    result.append({
                        "person_id": record_person_id,
                        "field": canonical_field,
                        "value": comparison_value,
                        "document_type": str(page.get("document_type") or "Unknown"),
                        "page_number": _find_supporting_page_number(pages, page, value),
                        "ocr_text": page.get("ocr_text"),
                    })
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
            if not _observation_is_reliable(
                page, canonical_field, comparison_value
            ):
                continue
            result.append({
                "person_id": person_id or "unassigned",
                "field": canonical_field,
                "value": comparison_value,
                "document_type": str(page.get("document_type") or "Unknown"),
                "page_number": _find_supporting_page_number(pages, page, value),
                "ocr_text": page.get("ocr_text"),
            })
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
        "guarantor": (
            r"\bguarantor(?:\s+details|\s+address|\s+kyc|\s+employment|\s+business)?\b",
        ),
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
    except Exception:
        pass

    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    if field in NAME_FIELDS | {"applicant_name"}:
        # Relationship labels / OCR form debris mistaken for names.
        if re.fullmatch(r"(?:c/?o|s/?o|w/?o|d/?o)(?:\s*[,/]\s*(?:c/?o|s/?o|w/?o|d/?o))*", text.strip(), re.I):
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
    if document_key in {
        "insurance form", "life insurance form", "property insurance form"
    } and field == "application_number" and is_insurer_local_application_identifier(
        ocr_text, value
    ):
        # Insurer proposal/application IDs are not loan application numbers.
        return False
    if document_key in {"crif report", "cibil report"} and field in {
        "branch", "apr", "roi", "sanction_amount", "loan_amount", "processing_fee",
        # Bureau phone numbers are often historic/shared-family and should not
        # create TRUSTED_PHONE mismatches against CRM numbers.
        "phone_number", "bank_linked_mobile",
    }:
        return False
    if field in {"loan_amount", "sanction_amount", "requested_amount", "recommended_amount"} and document_key in {
        "gst certificate", "utility bill", "bank statement", "passbook",
        "cheque", "nach form", "affidavit", "insurance form",
        "life insurance form", "property insurance form",
    }:
        # Tax/premium/ledger amounts do not establish the current loan terms.
        # This also protects consistency checks that read older cached runs.
        return False
    if document_key == "cersai report" and field in {
        # CERSAI debtor-search DOB is frequently OCR/parser noise relative to KYC.
        "date_of_birth", "dob", "phone_number",
    }:
        return False
    if document_key in {"technical report", "technical clearance report"} and field in {
        "phone_number", "email", "branch",
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
    except Exception:
        pass
    observed = fields.get("applicant_name") or fields.get("borrower_name") or fields.get("account_holder_name")
    if observed and is_person_name_candidate(observed):
        ranked = [(_similarity(observed, person.get("applicant_name")), person_id) for person_id, person in people.items()]
        if ranked and max(ranked)[0] >= 0.82:
            return max(ranked)[1]
    return ""


def _trusted_matches(observations: list[dict], people: dict[str, dict], trusted: dict) -> list[dict]:
    anomalies: list[dict] = []
    emitted: set[tuple[str, str, int | None]] = set()
    multi_person = len(people) > 1
    for obs in observations:
        person_id = obs["person_id"]
        field = obs["field"]
        # Ownership was resolved from the complete document/record before
        # observations were flattened. Never infer an owner from the very value
        # that is about to be reported as a mismatch. A unique, positive exact-ID
        # match may still correct an explicitly wrong page stamp.
        if people and person_id in people and field in {
            "pan_number", "aadhaar_number", "aadhaar_last4"
        }:
            exact_owner = _positive_exact_identity_owner(field, obs["value"], people)
            if exact_owner and exact_owner != person_id:
                person_id = exact_owner
                obs = {**obs, "person_id": exact_owner}

        if person_id in {"", "unassigned"} and field in PERSON_FIELDS:
            # Unresolved owner: do not invent a mismatch against anyone.
            # Single-person manifests still contain other people's documents
            # (guarantors, family); those pages surface as AUTO_OWNER_UNRESOLVED.
            continue
        person = people.get(person_id, {})
        if field in PERSON_FIELDS:
            expected = _lookup(person, field)
            # Never fall back to flat/primary trusted dump for person fields when
            # multiple people exist; that is the cross-person mismatch bug.
            if expected in (None, "") and not multi_person:
                expected = _lookup(trusted, field)
        else:
            expected = _lookup(trusted, field)
            if expected in (None, "") and field in LOAN_FIELDS:
                expected = _lookup(next(iter(people.values()), {}), field)
        address_records: list[dict | None] = [person]
        if not multi_person or person_id == "primary":
            # Flat/root person fields in the company dump describe the primary
            # borrower.  They must not become accepted address variants for a
            # co-applicant or guarantor in a multi-person manifest.
            address_records.append(trusted)
        address_variants = (
            _trusted_address_variants(*address_records)
            if field in ADDRESS_FIELDS
            else []
        )
        if address_variants and any(
            _matches("address", value, obs["value"]) for value in address_variants
        ):
            continue
        if expected in (None, "") and address_variants:
            expected = address_variants[0]
        if field in NAME_FIELDS and not is_person_name_candidate(expected):
            continue
        if expected in (None, "") or _matches(field, expected, obs["value"]):
            continue
        # Multi-KYC collage pages often extract the wrong card's address. If the
        # page OCR still contains the trusted address/prefix, do not flag it.
        if field in ADDRESS_FIELDS and _page_text_supports_value(obs.get("ocr_text"), expected):
            continue
        # Person PIN on the extracted address + short trusted relation prefix
        # is operationally consistent for rural KYC dumps.
        if field in ADDRESS_FIELDS:
            person_pin = str(person.get("pin_code") or "")
            found_pins = set(re.findall(r"\b[1-8]\d{5}\b", str(obs["value"])))
            expected_tokens = set(re.findall(r"[a-z0-9]+", str(expected).lower()))
            if person_pin and person_pin in found_pins and len(expected_tokens) <= 4:
                continue
        # If the extracted name matches another known person, this is ownership
        # noise rather than a trusted-data mismatch for the assigned person.
        if field in HOLDER_NAME_FIELDS and people and any(
            other_id != person_id and _matches("applicant_name", other.get("applicant_name"), obs["value"])
            for other_id, other in people.items()
        ):
            continue
        # A name that adds only the person's trusted father/mother tokens
        # ("Anupkumar Chetanbhai Suthar" for "Suthar Anupkumar") identifies
        # the same person in Indian naming conventions.
        if field in HOLDER_NAME_FIELDS and _name_matches_with_relatives(obs["value"], person):
            continue
        key = (person_id, field, obs["page_number"])
        if key in emitted:
            continue
        emitted.add(key)
        anomalies.append(_anomaly(
            f"TRUSTED_{field.upper()}_MISMATCH", "HIGH" if field in EXACT_FIELDS | NAME_FIELDS else "MEDIUM",
            expected, obs["value"], {**obs, "person_id": person_id},
            f"{field.replace('_', ' ').title()} does not match the trusted JSON/database dump.",
        ))
    return anomalies


def _name_matches_with_relatives(observed: Any, person: dict) -> bool:
    if not isinstance(person, dict) or not person:
        return False
    try:
        from services.person_ownership import name_matches_trusted_person

        return name_matches_trusted_person(observed, person)
    except Exception:
        return False


def _page_text_supports_value(page_text: Any, expected: Any) -> bool:
    text = str(page_text or "")
    if not text or expected in (None, ""):
        return False
    if _compact(expected) and _compact(expected) in _compact(text):
        return True
    return _names_equivalent(expected, text)


def _find_supporting_page_number(
    pages: list[dict],
    current_page: dict,
    value: Any,
) -> int:
    """Find the page number in the same document that supports the value, or return current page number."""
    current_page_no = int(current_page.get("page_number") or 0)
    if value in (None, ""):
        return current_page_no
    if _page_text_supports_value(current_page.get("ocr_text"), value):
        return current_page_no

    doc_id = current_page.get("source_document_id")
    doc_type = current_page.get("document_type")
    
    candidates = []
    for p in pages:
        p_no = int(p.get("page_number") or 0)
        if p_no == current_page_no:
            continue
        if doc_id and p.get("source_document_id") == doc_id:
            candidates.append(p)
        elif not doc_id and p.get("document_type") == doc_type and abs(p_no - current_page_no) <= 12:
            candidates.append(p)
            
    for p in sorted(candidates, key=lambda item: int(item.get("page_number") or 0)):
        if _page_text_supports_value(p.get("ocr_text"), value):
            return int(p.get("page_number") or 0)
            
    return current_page_no


def _cross_document_matches(
    observations: list[dict], people: dict[str, dict] | None = None
) -> list[dict]:
    anomalies: list[dict] = []
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    consistency_fields = PERSON_FIELDS | LOAN_FIELDS | NAME_FIELDS | ADDRESS_FIELDS
    for obs in observations:
        if obs["field"] in consistency_fields and not (
            obs["person_id"] == "unassigned" and obs["field"] in PERSON_FIELDS
        ):
            grouped[(obs["person_id"], obs["field"])].append(obs)
    for (person_id, field), values in grouped.items():
        person = (people or {}).get(person_id, {})
        values = sorted(
            values,
            key=lambda item: _observation_anchor_rank(item, field, person),
            reverse=True,
        )
        anchor = values[0]
        for other in values[1:]:
            if anchor["document_type"] == other["document_type"] or _matches(field, anchor["value"], other["value"]):
                continue
            if field in HOLDER_NAME_FIELDS and person and (
                _name_matches_with_relatives(anchor["value"], person)
                and _name_matches_with_relatives(other["value"], person)
            ):
                continue
            address_variants = _trusted_address_variants(person)
            if field in ADDRESS_FIELDS and address_variants and all(
                any(_matches("address", variant, item["value"]) for variant in address_variants)
                for item in (anchor, other)
            ):
                continue
            anomalies.append(_anomaly(
                f"CROSS_DOCUMENT_{field.upper()}_MISMATCH", "HIGH" if field in NAME_FIELDS | EXACT_FIELDS else "MEDIUM",
                f"{anchor['value']} ({anchor['document_type']})", f"{other['value']} ({other['document_type']})", other,
                f"{field.replace('_', ' ').title()} is inconsistent across documents for {person_id}.",
            ))
            break
    return anomalies


def _observation_anchor_rank(obs: dict, field: str, person: dict) -> tuple[int, int, int]:
    """Prefer semantically authoritative, trusted-matching observations.

    Page order is not evidence quality. In particular, an early tax, premium,
    or transaction amount must never become the reference loan amount merely
    because it was encountered first.
    """
    value = obs.get("value")
    trusted_values = (
        _trusted_address_variants(person)
        if field in ADDRESS_FIELDS
        else [_lookup(person, field)]
    )
    trusted_match = int(any(
        expected not in (None, "") and _matches(field, expected, value)
        for expected in trusted_values
    ))
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
            "aadhaar": 8, "pan": 8, "pan card": 8, "passport": 8,
            "voter id": 7, "driving license": 7, "application form": 5,
            "cam": 5, "bank statement": 4,
        }
    elif field in ADDRESS_FIELDS:
        authority = {
            "aadhaar": 8, "passport": 8, "voter id": 7,
            "driving license": 7, "utility bill": 6, "application form": 5,
        }
    else:
        authority = {}
    value_detail = min(20, len(re.findall(r"[A-Za-z0-9\u0900-\u097f]+", str(value or ""))))
    return trusted_match, authority.get(document_type, 1), value_detail


def _aadhaar_address_checks(
    observations: list[dict], people: dict[str, dict] | None = None
) -> list[dict]:
    anomalies: list[dict] = []
    by_person: dict[str, list[dict]] = defaultdict(list)
    for obs in observations:
        if obs["field"] in ADDRESS_FIELDS:
            by_person[obs["person_id"]].append(obs)
    for person_id, values in by_person.items():
        if person_id == "unassigned":
            continue
        address_variants = _trusted_address_variants((people or {}).get(person_id, {}))
        aadhaar_values = [item for item in values if item["document_type"] == "Aadhaar"]
        aadhaar = max(
            aadhaar_values,
            key=lambda item: (
                int(any(_matches("address", variant, item["value"]) for variant in address_variants)),
                -int(bool(re.search(
                    r"unique\s+identification\s+authority|"
                    r"भारतीय\s+विशिष्ट\s+पहचान\s+प्राधिकरण",
                    str(item.get("value") or ""),
                    re.I,
                ))),
                len(str(item.get("value") or "")),
            ),
            default=None,
        )
        if not aadhaar:
            continue
        for other in values:
            if other is aadhaar or _matches("address", aadhaar["value"], other["value"]):
                continue
            if address_variants and all(
                any(_matches("address", variant, item["value"]) for variant in address_variants)
                for item in (aadhaar, other)
            ):
                continue
            anomalies.append(_anomaly(
                "AADHAAR_ADDRESS_MISMATCH", "HIGH", aadhaar["value"], other["value"], other,
                f"Address does not match the Aadhaar address for {person_id}.",
            ))
    return anomalies


def _positive_exact_identity_owner(
    field: str, value: Any, people: dict[str, dict]
) -> str | None:
    matches = [
        person_id
        for person_id, person in people.items()
        if _lookup(person, field) not in (None, "")
        and _matches(field, _lookup(person, field), value)
    ]
    return matches[0] if len(matches) == 1 else None


def _trusted_address_variants(*records: dict | None) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if _canonical(str(key)) not in ADDRESS_FIELDS or value in (None, ""):
                continue
            marker = _compact(value)
            if not marker or marker in seen:
                continue
            seen.add(marker)
            values.append(value)
    return values


def _relationship_checks(observations: list[dict], people: dict[str, dict]) -> list[dict]:
    anomalies: list[dict] = []
    relations = [obs for obs in observations if obs["field"] == "relationship_qualifier"]
    related_names = {(obs["person_id"], obs["page_number"]): obs for obs in observations if obs["field"] == "related_person_name"}
    known_names = {person_id: person.get("applicant_name") for person_id, person in people.items()}
    primary_rel = next((item for item in relations if item["person_id"] == "primary"), None)
    primary_related = (
        related_names.get(("primary", primary_rel["page_number"])) if primary_rel else None
    )
    for relation in relations:
        related = related_names.get((relation["person_id"], relation["page_number"]))
        if not related:
            continue
        declared = str(people.get(relation["person_id"], {}).get("relationship") or "").lower()
        qualifier = str(relation["value"]).lower()
        person_name = known_names.get(relation["person_id"])
        consistent = True
        if declared == "father" and primary_related:
            consistent = _relationship_name_matches(primary_related["value"], person_name)
        elif declared == "mother" and primary_related:
            if qualifier in {"w/o", "wife of"}:
                consistent = _relationship_name_matches(primary_related["value"], related["value"])
            else:
                consistent = _relationship_name_matches(primary_related["value"], person_name)
        elif declared in {"son", "daughter"}:
            consistent = qualifier in {"s/o", "d/o", "son of", "daughter of"} and _relationship_name_matches(
                related["value"], known_names.get("primary")
            )
        elif declared == "wife":
            consistent = qualifier in {"w/o", "wife of"} and _relationship_name_matches(
                related["value"], known_names.get("primary")
            )
        if not consistent:
            anomalies.append(_anomaly(
                "RELATIONSHIP_QUALIFIER_MISMATCH", "HIGH", declared, relation["value"], relation,
                f"S/O, D/O, W/O or C/O evidence conflicts with the declared relationship for {relation['person_id']}.",
            ))
        if known_names and not any(_matches("applicant_name", name, related["value"]) for name in known_names.values() if name):
            # A parent/spouse need not be a borrower, so report this softly for review.
            # Do not flag the parent named on a father/mother co-applicant's own
            # Aadhaar: that person is a grandparent and need not be on the loan.
            if declared in {"wife", "husband", "son", "daughter"}:
                anomalies.append(_anomaly(
                    "RELATIONSHIP_NAME_REVIEW", "LOW", "Declared family relationship", related["value"], related,
                    "Related person's name could not be linked to a named applicant/co-applicant; review the family chain.",
                ))
    return anomalies


def _relationship_name_matches(left: Any, right: Any) -> bool:
    """Compare family-chain names with transliteration and surname omission.

    Aadhaar relationship lines commonly omit a surname, while trusted data may
    spell a given name phonetically (Tika/Teeka). Require at least two aligned
    name tokens before allowing that tolerance so unrelated one-word names do
    not become matches.
    """
    if _matches("applicant_name", left, right):
        return True
    left_tokens = list(dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(left)))
    right_tokens = list(dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(right)))
    if min(len(left_tokens), len(right_tokens)) < 2:
        return False
    if len(left_tokens) <= len(right_tokens):
        short, long = left_tokens, right_tokens
    else:
        short, long = right_tokens, left_tokens
    aligned = long[: len(short)]
    def token_matches(short_token: str, long_token: str) -> bool:
        if _similarity(short_token, long_token) >= 0.80:
            return True
        # Transliteration often changes only the written vowel (Tika/Teeka,
        # Mohammad/Mohammed). A shared two-character consonant skeleton is
        # acceptable here only because the full relationship comparison also
        # requires another aligned name token.
        consonants = lambda token: re.sub(r"[aeiouy]", "", token.casefold())
        left_skeleton = consonants(short_token)
        right_skeleton = consonants(long_token)
        return len(left_skeleton) >= 2 and left_skeleton == right_skeleton

    return all(token_matches(a, b) for a, b in zip(short, aligned))


def _application_name_checks(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    if not people:
        return []
    found: list[tuple[str, dict]] = []
    app_pages = [page for page in pages if page.get("document_type") == "Application Form"]
    if not app_pages:
        return []
    # Co-applicant names often appear on later form pages that sandwich-smoothing
    # has not yet retyped, so also scan nearby KYC/application-looking pages.
    search_pages = list(app_pages)
    app_nums = {int(p.get("page_number") or 0) for p in app_pages}
    for page in pages:
        pn = int(page.get("page_number") or 0)
        if pn and any(abs(pn - other) <= 8 for other in app_nums):
            search_pages.append(page)
    extraction_noise = False
    for page in app_pages:
        fields = page.get("extracted_fields") or {}
        if isinstance(fields, dict) and fields.get("_identity_extraction_reliable") is False:
            extraction_noise = True
            continue
        values = fields.get("applicant_names") or [fields.get("applicant_name")]
        for value in values:
            if not value:
                continue
            candidate = canonicalize_person_name(value)
            if candidate.valid and candidate.value:
                found.append((candidate.value, page))
            else:
                # A rejected candidate (label/address noise) means extraction
                # failed on this form, not that the name is absent from it.
                extraction_noise = True
    anomalies: list[dict] = []
    for person_id, person in people.items():
        expected = person.get("applicant_name")
        name_visible_in_text = any(
            _compact(expected) in _compact(page.get("ocr_text"))
            or _names_equivalent(expected, page.get("ocr_text"))
            for page in search_pages
        ) if expected else False
        if not expected or not is_person_name_candidate(expected) or name_visible_in_text or any(
            _matches("applicant_name", expected, value) for value, _ in found
        ):
            continue
        if not found and extraction_noise:
            # Name candidates existed but were rejected as noise (or extraction
            # was marked unreliable): an extraction gap, not a mismatch.
            continue
        page = found[0][1] if found else app_pages[0]
        anomalies.append({
            "rule_id": "APPLICATION_NAME_MISMATCH", "s_no": 1, "severity": "HIGH",
            "document_type": "Application Form", "expected_value": expected,
            "found_value": ", ".join(value for value, _ in found) or "Name not extracted",
            "page_number": page.get("page_number"), "person_id": person_id,
            "reason": "Applicant/co-applicant name or spelling is missing or inconsistent in the application form.",
        })
    return anomalies


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


def _bureau_checks(pages: list[dict], observations: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    bureau_pages = [
        page for page in pages
        if page.get("document_type") in {"CRIF Report", "CIBIL Report"}
    ]
    grouped: dict[tuple[Any, str, Any], list[dict]] = defaultdict(list)
    for page in bureau_pages:
        fields = page.get("extracted_fields") or {}
        key = (
            page.get("source_document_id")
            or fields.get("credit_report_id")
            or page.get("detected_page_number")
            or page.get("page_number"),
            str(page.get("document_type") or ""),
            page.get("person_id"),
        )
        grouped[key].append(page)

    for (_segment, document_type, person_id), group_pages in grouped.items():
        score_values: list[tuple[Any, dict]] = []
        for page in group_pages:
            fields = page.get("extracted_fields") or {}
            for field in ("credit_score", "cibil_score", "crif_score"):
                value = fields.get(field)
                if value not in (None, "", [], {}):
                    score_values.append((value, page))
        valid_scores = [
            value for value, _page in score_values
            if (score := _number(value)) is not None and (score == 0 or 300 <= score <= 900)
        ]
        explicit_no_score = any(
            has_explicit_no_score_evidence(str(page.get("ocr_text") or ""))
            for page in group_pages
        )
        if valid_scores or explicit_no_score:
            continue
        score_page = next((_page for _value, _page in score_values), None)
        if score_page is None:
            score_page = next((page for page in group_pages if _has_bureau_score_table(page)), None)
        if score_page is None:
            continue
        found = next((value for value, _page in score_values if value not in (None, "")), None)
        obs = {
            "document_type": document_type,
            "page_number": score_page.get("page_number"),
            "person_id": person_id or "unassigned",
        }
        anomalies.append(_anomaly(
            "BUREAU_SCORE_MISSING", "HIGH", "Bureau score of 0 (no score) or 300 to 900",
            found if found not in (None, "") else "Blank score table", obs,
            "Credit bureau report does not expose a valid score on its score page.",
        ))
    return anomalies


def _has_bureau_score_table(page: dict) -> bool:
    text = str(page.get("ocr_text") or "").lower()
    return bool(
        re.search(r"\b(?:crif|cibil|credit\s+information|credit\s+report)\b", text)
        and re.search(r"\bscore(?:\(s\))?\b", text)
        and ("score name" in text or "range" in text or "crif hm score" in text)
    )


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

    person_ids = {
        str(anomaly.get("person_id") or "primary")
        for anomaly in mismatches
    }
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


def _identity_mismatch_is_affidavit_worthy(
    anomaly: dict, page: dict, person: dict
) -> bool:
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
        if not _plausible_adult_date_of_birth(
            fields.get("date_of_birth") or fields.get("dob")
        ):
            return False
        observed_name = fields.get("applicant_name") or fields.get("borrower_name")
        name_matches = (
            observed_name not in (None, "")
            and _matches("applicant_name", person.get("applicant_name"), observed_name)
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
    source_name = str(
        page.get("source_filename")
        or page.get("original_filename")
        or ""
    ).casefold()
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
    has_hindi_resolution = (
        hindi_identity_families >= 3
        and any(marker in lowered for marker in ("सही", "मान्य", "अंतर", "भिन्न", "अलग"))
    )
    if not (has_english_identity_resolution or has_hindi_resolution):
        return False
    if page_person not in {"", "unassigned", "unknown", person_id}:
        return False
    expected_name = person.get("applicant_name") if isinstance(person, dict) else None
    if page_person == person_id or not expected_name:
        return True
    return _page_text_supports_value(text, expected_name)


def _application_language_checks(pages: list[dict], trusted: dict | None = None) -> list[dict]:
    """Verify that a digital application form contains a second language.

    Scanned application forms are excluded because OCR is not reliable enough
    for this checklist rule. Hindi is a valid second language.
    """
    anomalies: list[dict] = []
    app_pages = [
        page
        for page in pages
        if page.get("document_type") == "Application Form"
        and str(page.get("page_type") or "").strip().casefold() == "digital"
    ]
    if not app_pages:
        return anomalies

    configured_languages = _configured_application_languages(trusted or {})
    for page in app_pages:
        fields = page.get("extracted_fields") or {}
        declared_language = fields.get("second_language")
        if _is_second_application_language(declared_language):
            return []
        if any(_is_second_application_language(value) for value in configured_languages):
            return []

        language_metadata = fields.get("_language") if isinstance(fields.get("_language"), dict) else {}
        provider_languages = language_metadata.get("provider_languages") or []
        if any(_is_second_application_language(value) for value in provider_languages):
            return []

        text = str(page.get("ocr_text") or "")
        scripts = set(analyze_text_languages(text)["scripts"])
        if "latin" in scripts and scripts.difference({"latin"}):
            return []

    all_scripts = {
        script
        for app_page in app_pages
        for script in analyze_text_languages(str(app_page.get("ocr_text") or ""))["scripts"]
    }
    if "latin" in all_scripts and all_scripts.difference({"latin"}):
        return []

    page = app_pages[0]
    anomalies.append({
        "rule_id": "APPLICATION_SECOND_LANGUAGE_MISSING", "s_no": 10, "severity": "MEDIUM",
        "document_type": "Application Form", "expected_value": "Second language (Hindi accepted)",
        "found_value": "Not found", "page_number": page.get("page_number"), "person_id": None,
        "reason": "Verify that the digital application form includes a second language; Hindi is accepted.",
    })
    return anomalies


def _is_second_application_language(value: Any) -> bool:
    """Return true for a recognized language other than English, including Hindi."""
    code = normalize_language_code(value)
    return bool(code and code != "en")


def _configured_application_languages(trusted: dict) -> list[Any]:
    """Read optional case/template language declarations from trusted input."""
    values: list[Any] = []
    for key in ("application_form_languages", "required_application_languages"):
        value = trusted.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    document_languages = trusted.get("document_languages")
    if isinstance(document_languages, dict):
        value = document_languages.get("Application Form") or document_languages.get("application_form")
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    return values


def _canonical(field: str) -> str:
    aliases = {
        "name": "applicant_name", "full_name": "applicant_name", "borrower_name": "applicant_name",
        "account_holder_name": "applicant_name",
        "dob": "date_of_birth", "mobile_number": "phone_number", "mobile_no": "phone_number",
        "credit_score": "credit_score", "interest_rate": "roi", "loan_tenure": "tenure",
        "bank_account_number": "account_number", "application_id": "application_number",
    }
    key = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
    return aliases.get(key, key)


def _lookup(data: dict, field: str) -> Any:
    for key, value in data.items():
        if _canonical(str(key)) == field and value not in (None, ""):
            return value
    if field == "credit_score":
        return data.get("cibil_score") or data.get("crif_score")
    return None


def _matches(field: str, left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return True
    if field in NUMERIC_FIELDS or field == "credit_score":
        a, b = _number(left), _number(right)
        return a is not None and b is not None and abs(a - b) <= max(0.01, abs(a) * 0.01)
    if field in DATE_FIELDS:
        try:
            from datetime import date
            from dateutil import parser

            def parse_date(value: Any) -> date:
                text = str(value).strip()
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                    return date.fromisoformat(text)
                return parser.parse(text, dayfirst=True).date()

            return parse_date(left) == parse_date(right)
        except (TypeError, ValueError, OverflowError):
            pass
    if field in EXACT_FIELDS:
        left_compact, right_compact = _compact(left), _compact(right)
        return left_compact == right_compact or (
            field in {"aadhaar_number", "aadhaar_last4", "account_number"}
            and len(left_compact) >= 4 and len(right_compact) >= 4
            and left_compact[-4:] == right_compact[-4:]
        )
    if field in ADDRESS_FIELDS:
        if _explicit_address_unit_conflict(left, right):
            return False

        def address_tokens(value: Any) -> set[str]:
            normalized = re.sub(
                r"\b([swdc])\s*/\s*o\b", r"\1o", str(value).lower()
            )
            # OCR often glues "UkarLal" / "UkarLal," — split common Indian name endings.
            normalized = re.sub(r"([a-z])(lal|bai|devi|singh|kumar)\b", r"\1 \2", normalized)
            return set(re.findall(r"[a-z0-9]+", normalized))

        left_tokens = address_tokens(left)
        right_tokens = address_tokens(right)
        shared = left_tokens & right_tokens
        # Trusted dumps sometimes contain only the relationship/address prefix
        # (for example "S/O: Unkar Lal").  A full document address containing
        # that exact prefix is consistent, not a mismatch.
        if min(len(left_tokens), len(right_tokens)) >= 2 and (
            left_tokens <= right_tokens or right_tokens <= left_tokens
        ):
            return True
        # If trusted data intentionally stores only a relationship prefix,
        # tolerate a one-character OCR error in that related person's name.
        def relation_prefix(value: Any) -> tuple[str, str] | None:
            normalized = re.sub(r"\b([swdc])\s*/\s*o\b", r"\1o", str(value).lower())
            normalized = re.sub(r"([a-z])(lal|bai|devi|singh|kumar)\b", r"\1 \2", normalized)
            match = re.search(r"\b(so|wo|do|co)\s*[:\-]?\s*([a-z]+(?:\s+[a-z]+)?)", normalized)
            return (match.group(1), match.group(2)) if match else None

        left_relation = relation_prefix(left)
        right_relation = relation_prefix(right)
        if left_relation and right_relation and left_relation[0] == right_relation[0]:
            if len(left_relation[1].split()) <= len(right_relation[1].split()):
                short_name, long_name = left_relation[1], right_relation[1]
            else:
                short_name, long_name = right_relation[1], left_relation[1]
            word_count = max(1, len(short_name.split()))
            comparable_long_name = " ".join(long_name.split()[:word_count])
            relation_name_matches = (
                _names_equivalent(short_name, comparable_long_name)
                or _similarity(short_name, comparable_long_name) >= 0.75
            )
            if relation_name_matches and (
                min(len(left_tokens), len(right_tokens)) <= 3 or len(shared) >= 3
            ):
                return True
            # Short trusted prefix vs long OCR address: same PIN + relation match is enough.
            same_pin_for_prefix = bool(
                set(re.findall(r"\b[1-8]\d{5}\b", str(left)))
                & set(re.findall(r"\b[1-8]\d{5}\b", str(right)))
            )
            if relation_name_matches and same_pin_for_prefix and min(len(left_tokens), len(right_tokens)) <= 4:
                return True
        # OCR often produces one or two spelling variants in a full address
        # (Semah/Semali, Sulia/Suilia) and may add Hindi tokens. When the PIN is
        # identical and at least three quarters of the shorter Latin-token set
        # agrees, the addresses are operationally consistent.
        same_pin = bool(
            set(re.findall(r"\b[1-8]\d{5}\b", str(left)))
            & set(re.findall(r"\b[1-8]\d{5}\b", str(right)))
        )
        containment = len(shared) / max(1, min(len(left_tokens), len(right_tokens)))
        if same_pin and len(shared) >= 5 and containment >= 0.75:
            return True
        generic_address_tokens = {
            "so", "wo", "do", "co", "po", "dist", "district", "state",
            "india", "gujarat", "rajasthan", "ahmedabad", "ahmadabad",
            *re.findall(r"\b[1-8]\d{5}\b", f"{left} {right}"),
        }
        distinctive_shared = {
            token for token in shared
            if token not in generic_address_tokens and len(token) >= 3
        }
        left_distinctive = {
            token for token in left_tokens
            if token not in generic_address_tokens and len(token) >= 3 and not token.isdigit()
        }
        right_distinctive = {
            token for token in right_tokens
            if token not in generic_address_tokens and len(token) >= 3 and not token.isdigit()
        }
        fuzzy_distinctive_pairs = {
            (left_token, right_token)
            for left_token in left_distinctive - distinctive_shared
            for right_token in right_distinctive - distinctive_shared
            if _similarity(left_token, right_token) >= 0.78
        }
        left_units = _explicit_address_units(left)
        right_units = _explicit_address_units(right)
        matched_unit = any(
            not left_values.isdisjoint(right_units[category])
            for category, left_values in left_units.items()
            if category in right_units
        )
        # Layout OCR may corrupt a PIN or one locality spelling while preserving
        # the exact flat/unit plus multiple address anchors (B-402, Pandit,
        # Hathijan). Conversely rural addresses often have an exact PIN plus
        # one exact and one near-identical village token (Harniyau/Harniyav).
        if (
            matched_unit
            and len(distinctive_shared) >= 2
        ) or (
            same_pin
            and len(distinctive_shared) + len(fuzzy_distinctive_pairs) >= 2
        ):
            return True
        # Trusted rural addresses often contain only village/locality + PIN,
        # while Aadhaar adds relation, PO, tehsil and district text. Two shared
        # distinctive locality tokens plus the same PIN identify that variant.
        if same_pin and len(distinctive_shared) >= 2 and containment >= 0.55:
            return True
        # Multi-card OCR collage: locality + PIN agree even when Hindi OCR is noisy.
        locality_markers = {"semli", "semali", "bakhta", "bakta", "sulia", "jhalawar", "pachpahar", "rajasthan"}
        if same_pin and len(shared & locality_markers) >= 2 and containment >= 0.4:
            return True
        overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        return overlap >= 0.70 or _similarity(left, right) >= 0.82
    if field in HOLDER_NAME_FIELDS:
        return (
            names_match(_without_honorific(left), _without_honorific(right), threshold=0.85)
            or _names_equivalent(left, right)
        )
    if field in {"father_name", "mother_name"}:
        return _related_names_equivalent(left, right)
    return _similarity(left, right) >= 0.88


def _explicit_address_unit_conflict(left: Any, right: Any) -> bool:
    """Reject locality-tolerant matches when both addresses disagree on a unit.

    PIN and locality overlap are deliberately tolerant of OCR noise.  A clear
    Flat/House/Unit number is different: B-402 and B-403 cannot describe the
    same service address even if every remaining token is identical.
    """
    left_units = _explicit_address_units(left)
    right_units = _explicit_address_units(right)
    for category in left_units.keys() & right_units.keys():
        if left_units[category].isdisjoint(right_units[category]):
            return True
    return False


def _explicit_address_units(value: Any) -> dict[str, set[str]]:
    text = str(value or "").casefold()
    result: dict[str, set[str]] = defaultdict(set)
    identifier = r"([a-z]?\s*[-/]?\s*\d{1,5}(?:\s*[-/]\s*\d{1,5})?[a-z]?)"
    patterns = (
        (
            "occupancy",
            rf"\b(?:flat|apartment|apt|house|unit|door|room|quarter)\s*(?:(?:number|no)\.?\s*)?{identifier}",
        ),
        ("occupancy", rf"\bh\s*\.?\s*no\.?\s*{identifier}"),
        ("plot", rf"\bplot\s*(?:(?:number|no)\.?\s*)?{identifier}"),
        ("block", rf"\bblock\s*(?:(?:number|no)\.?\s*)?{identifier}"),
    )
    for category, pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            normalized = re.sub(r"[^a-z0-9]", "", match.group(1).casefold())
            if normalized:
                result[category].add(normalized)

    # Company dumps commonly omit the word "Flat" and start directly with
    # an alphanumeric unit such as "B 402" or "B-402".
    leading = re.match(r"^\s*([a-z])\s*[-/]?\s*(\d{1,5}[a-z]?)\b", text)
    if leading:
        result["occupancy"].add(f"{leading.group(1)}{leading.group(2)}")
    return result


def _without_honorific(value: Any) -> str:
    return re.sub(
        r"^\s*(?:mr|mrs|ms|miss|shri|smt|dr)\.?\s+",
        "",
        str(value or ""),
        flags=re.IGNORECASE,
    )


def _related_names_equivalent(left: Any, right: Any) -> bool:
    """Compare parent names without holder-only extra-relative tolerance."""
    left_tokens = list(
        dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(left))
    )
    right_tokens = list(
        dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(right))
    )
    if not left_tokens or not right_tokens or len(left_tokens) != len(right_tokens):
        return False
    if left_tokens == right_tokens or set(left_tokens) == set(right_tokens):
        return True
    return SequenceMatcher(
        None,
        "".join(left_tokens),
        "".join(right_tokens),
    ).ratio() >= 0.88


# Common North-Indian OCR/transliteration variants that humans treat as the same person.
_NAME_VARIANT_GROUPS = (
    frozenset({"unkar", "onkar", "ukar", "unkarlal", "onkarlal", "ukarlal"}),
    frozenset({"peeru", "peerulal"}),
    frozenset({"radha", "radhabai", "radhe", "radhebai"}),
)


def _name_tokens(value: Any) -> list[str]:
    text = _without_honorific(value).lower()
    text = re.sub(r"([a-z])(lal|bai|devi|singh|kumar)\b", r"\1 \2", text)
    return re.findall(r"[a-z]+", text)


def _canonical_name_token(token: str) -> str:
    compact = re.sub(r"[^a-z]", "", token.lower())
    for group in _NAME_VARIANT_GROUPS:
        if compact in group:
            return next(iter(sorted(group)))
    return compact


def _names_equivalent(left: Any, right: Any) -> bool:
    """True when two person names match after honorific/transliteration normalization."""
    # Trusted dumps sometimes duplicate a token ("Kuldeep KULDEEP"); compare
    # unique tokens in order so duplication does not create a mismatch.
    left_tokens = list(dict.fromkeys(_canonical_name_token(tok) for tok in _name_tokens(left)))
    right_tokens = list(dict.fromkeys(_canonical_name_token(tok) for tok in _name_tokens(right)))
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    # Indian documents commonly rotate given/father/surname order while
    # preserving the same complete token set.
    if len(left_tokens) == len(right_tokens) and set(left_tokens) == set(right_tokens):
        return True
    # Allow substring containment for "Unkar" vs "Unkar Lal" style pairs.
    if len(left_tokens) <= len(right_tokens):
        short, long = left_tokens, right_tokens
    else:
        short, long = right_tokens, left_tokens
    if short == long[: len(short)]:
        return True
    left_compact = "".join(left_tokens)
    right_compact = "".join(right_tokens)
    if left_compact == right_compact:
        return True
    # Compact form appearing inside OCR/page text haystack.
    if isinstance(right, str) and len(left_compact) >= 4 and left_compact in _compact(right):
        return True
    if isinstance(left, str) and len(right_compact) >= 4 and right_compact in _compact(left):
        return True
    return SequenceMatcher(None, left_compact, right_compact).ratio() >= 0.85


def _compact(value: Any) -> str:
    return comparable_name(value)


def _similarity(left: Any, right: Any) -> float:
    if is_person_name_candidate(left) and is_person_name_candidate(right):
        return name_similarity(left, right)
    a, b = _compact(left), _compact(right)
    if not a or not b:
        return 0.0
    # Prefer transliteration-aware comparison for short person names.
    if _names_equivalent(left, right):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _number(value: Any) -> float | None:
    try:
        return float(re.sub(r"[^0-9.-]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _anomaly(rule_id: str, severity: str, expected: Any, found: Any, obs: dict, reason: str) -> dict:
    return {
        "rule_id": rule_id, "s_no": None, "severity": severity,
        "document_type": obs["document_type"], "expected_value": expected,
        "found_value": found, "page_number": obs["page_number"],
        "person_id": None if obs["person_id"] == "unassigned" else obs["person_id"],
        "reason": reason,
    }
