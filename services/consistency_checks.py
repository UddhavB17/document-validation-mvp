"""Cross-document and trusted-data consistency checks for loan packets."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any


EXACT_FIELDS = {
    "loan_id", "application_number", "account_number", "pan_number",
    "aadhaar_number", "aadhaar_last4", "voter_id_number", "dl_number",
    "gstin", "ifsc", "pin_code", "phone_number", "customer_id",
}
NUMERIC_FIELDS = {
    "loan_amount", "requested_amount", "recommended_amount", "sanction_amount",
    "tenure", "roi", "interest_rate", "apr", "emi", "first_emi", "final_emi",
    "processing_fee", "insurance_amount", "net_disbursement", "foir", "ltv",
    "monthly_income", "verified_income", "considered_income", "monthly_obligations",
    "available_income", "maximum_emi", "turnover", "margin", "cibil_score", "crif_score",
}
NAME_FIELDS = {"applicant_name", "borrower_name", "account_holder_name", "father_name", "mother_name"}
ADDRESS_FIELDS = {"address", "current_address", "permanent_address", "communication_address"}
DATE_FIELDS = {
    "date_of_birth", "repayment_start_date", "maturity_date", "mandate_validity",
    "occupied_since",
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
}


def run_consistency_checks(pages: list[dict], trusted: dict) -> list[dict]:
    anomalies: list[dict] = []
    people = _people(trusted)
    observations = _observations(pages, people)

    anomalies.extend(_trusted_matches(observations, people, trusted))
    anomalies.extend(_application_name_checks(pages, people))
    anomalies.extend(_cross_document_matches(observations))
    anomalies.extend(_aadhaar_address_checks(observations))
    anomalies.extend(_relationship_checks(observations, people))
    anomalies.extend(_bureau_checks(pages, observations))
    anomalies.extend(_application_language_checks(pages))
    return anomalies


def _people(trusted: dict) -> dict[str, dict]:
    raw = trusted.get("people") or trusted.get("reference_data") or {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)} if isinstance(raw, dict) else {}


def _observations(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    result: list[dict] = []
    for page in pages:
        fields = page.get("extracted_fields") or {}
        person_id = str(page.get("person_id") or page.get("applicant_role") or "")
        if not person_id:
            person_id = _infer_person(fields, people)
        person_records = fields.get("person_records")
        if isinstance(person_records, list):
            for record in person_records:
                if not isinstance(record, dict):
                    continue
                record_person_id = _infer_person(record, people) or "unassigned"
                for field, value in record.items():
                    if value in (None, "", [], {}):
                        continue
                    canonical_field = _canonical(str(field))
                    if not _field_is_semantically_valid(
                        str(page.get("document_type") or "Unknown"), canonical_field
                    ):
                        continue
                    result.append({
                        "person_id": record_person_id,
                        "field": canonical_field,
                        "value": value,
                        "document_type": str(page.get("document_type") or "Unknown"),
                        "page_number": page.get("page_number"),
                    })
        for field, value in fields.items():
            if str(field).startswith("_") or field == "person_records" or value in (None, "", [], {}):
                continue
            canonical_field = _canonical(str(field))
            if not _field_is_semantically_valid(str(page.get("document_type") or "Unknown"), canonical_field):
                continue
            result.append({
                "person_id": person_id or "unassigned",
                "field": canonical_field,
                "value": value,
                "document_type": str(page.get("document_type") or "Unknown"),
                "page_number": page.get("page_number"),
            })
    return result


def _field_is_semantically_valid(document_type: str, field: str) -> bool:
    """Reject fields whose labels mean something different in this document.

    A bureau report's BRANCH ID, APR month column, and historic sanctioned
    amount are not the loan-file branch, annual percentage rate, or current
    sanction amount.
    """
    if document_type in {"CRIF Report", "CIBIL Report"} and field in {
        "branch", "apr", "roi", "sanction_amount", "loan_amount", "processing_fee",
    }:
        return False
    if document_type in {"Technical Report", "Technical Clearance Report"} and field in {
        "phone_number", "email", "branch",
    }:
        return False
    return True


def _infer_person(fields: dict, people: dict[str, dict]) -> str:
    observed = fields.get("applicant_name") or fields.get("borrower_name") or fields.get("account_holder_name")
    if observed:
        ranked = [(_similarity(observed, person.get("applicant_name")), person_id) for person_id, person in people.items()]
        if ranked and max(ranked)[0] >= 0.82:
            return max(ranked)[1]
    return ""


def _trusted_matches(observations: list[dict], people: dict[str, dict], trusted: dict) -> list[dict]:
    anomalies: list[dict] = []
    emitted: set[tuple[str, str, int | None]] = set()
    for obs in observations:
        person = people.get(obs["person_id"], {})
        field = obs["field"]
        if obs["person_id"] == "unassigned" and len(people) > 1 and field in PERSON_FIELDS:
            continue
        expected = (_lookup(person, field) or _lookup(trusted, field)) if field in PERSON_FIELDS else _lookup(trusted, field)
        if expected in (None, "") and field in LOAN_FIELDS:
            expected = _lookup(next(iter(people.values()), {}), field)
        if expected in (None, "") or _matches(field, expected, obs["value"]):
            continue
        key = (obs["person_id"], field, obs["page_number"])
        if key in emitted:
            continue
        emitted.add(key)
        anomalies.append(_anomaly(
            f"TRUSTED_{field.upper()}_MISMATCH", "HIGH" if field in EXACT_FIELDS | NAME_FIELDS else "MEDIUM",
            expected, obs["value"], obs,
            f"{field.replace('_', ' ').title()} does not match the trusted JSON/database dump.",
        ))
    return anomalies


def _cross_document_matches(observations: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    consistency_fields = PERSON_FIELDS | LOAN_FIELDS | NAME_FIELDS | ADDRESS_FIELDS
    for obs in observations:
        if obs["field"] in consistency_fields and not (
            obs["person_id"] == "unassigned" and obs["field"] in PERSON_FIELDS
        ):
            grouped[(obs["person_id"], obs["field"])].append(obs)
    for (person_id, field), values in grouped.items():
        anchor = values[0]
        for other in values[1:]:
            if anchor["document_type"] == other["document_type"] or _matches(field, anchor["value"], other["value"]):
                continue
            anomalies.append(_anomaly(
                f"CROSS_DOCUMENT_{field.upper()}_MISMATCH", "HIGH" if field in NAME_FIELDS | EXACT_FIELDS else "MEDIUM",
                f"{anchor['value']} ({anchor['document_type']})", f"{other['value']} ({other['document_type']})", other,
                f"{field.replace('_', ' ').title()} is inconsistent across documents for {person_id}.",
            ))
            break
    return anomalies


def _aadhaar_address_checks(observations: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    by_person: dict[str, list[dict]] = defaultdict(list)
    for obs in observations:
        if obs["field"] in ADDRESS_FIELDS:
            by_person[obs["person_id"]].append(obs)
    for person_id, values in by_person.items():
        if person_id == "unassigned":
            continue
        aadhaar = next((item for item in values if item["document_type"] == "Aadhaar"), None)
        if not aadhaar:
            continue
        for other in values:
            if other is aadhaar or _matches("address", aadhaar["value"], other["value"]):
                continue
            anomalies.append(_anomaly(
                "AADHAAR_ADDRESS_MISMATCH", "HIGH", aadhaar["value"], other["value"], other,
                f"Address does not match the Aadhaar address for {person_id}.",
            ))
    return anomalies


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
            consistent = _matches("applicant_name", primary_related["value"], person_name)
        elif declared == "mother" and primary_related:
            if qualifier in {"w/o", "wife of"}:
                consistent = _matches("applicant_name", primary_related["value"], related["value"])
            else:
                consistent = _matches("applicant_name", primary_related["value"], person_name)
        elif declared in {"son", "daughter"}:
            consistent = qualifier in {"s/o", "d/o", "son of", "daughter of"} and _matches(
                "applicant_name", related["value"], known_names.get("primary")
            )
        elif declared == "wife":
            consistent = qualifier in {"w/o", "wife of"} and _matches(
                "applicant_name", related["value"], known_names.get("primary")
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


def _application_name_checks(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    if not people:
        return []
    found: list[tuple[str, dict]] = []
    app_pages = [page for page in pages if page.get("document_type") == "Application Form"]
    for page in pages:
        if page.get("document_type") != "Application Form":
            continue
        fields = page.get("extracted_fields") or {}
        values = fields.get("applicant_names") or [fields.get("applicant_name")]
        for value in values:
            if value:
                found.append((str(value), page))
    anomalies: list[dict] = []
    for person_id, person in people.items():
        expected = person.get("applicant_name")
        name_visible_in_text = any(
            _compact(expected) in _compact(page.get("ocr_text")) for page in app_pages
        ) if expected else False
        if not expected or name_visible_in_text or any(_matches("applicant_name", expected, value) for value, _ in found):
            continue
        page = found[0][1] if found else (app_pages[0] if app_pages else {})
        anomalies.append({
            "rule_id": "APPLICATION_NAME_MISMATCH", "s_no": 1, "severity": "HIGH",
            "document_type": "Application Form", "expected_value": expected,
            "found_value": ", ".join(value for value, _ in found) or "Name not extracted",
            "page_number": page.get("page_number"), "person_id": person_id,
            "reason": "Applicant/co-applicant name or spelling is missing or inconsistent in the application form.",
        })
    return anomalies


def _bureau_checks(pages: list[dict], observations: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    for obs in observations:
        if obs["document_type"] not in {"CRIF Report", "CIBIL Report"} or obs["field"] not in {"credit_score", "cibil_score", "crif_score"}:
            continue
        score = _number(obs["value"])
        if score is None or not 300 <= score <= 900:
            anomalies.append(_anomaly(
                "BUREAU_SCORE_INVALID", "HIGH", "Valid bureau score from 300 to 900", obs["value"], obs,
                "CRIF/CIBIL score is outside the valid numeric range.",
            ))
    return anomalies


def _application_language_checks(pages: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    for page in pages:
        if page.get("document_type") != "Application Form":
            continue
        fields = page.get("extracted_fields") or {}
        language = str(fields.get("second_language") or "").strip()
        if language and language.lower() not in {"hindi", "हिंदी", "english"}:
            return []
    app_pages = [page for page in pages if page.get("document_type") == "Application Form"]
    if app_pages:
        page = app_pages[0]
        anomalies.append({
            "rule_id": "APPLICATION_SECOND_LANGUAGE_MISSING", "s_no": 10, "severity": "MEDIUM",
            "document_type": "Application Form", "expected_value": "Second language other than Hindi",
            "found_value": "Not found", "page_number": page.get("page_number"), "person_id": None,
            "reason": "Verify that the application form includes a second language other than Hindi.",
        })
    return anomalies


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
        def address_tokens(value: Any) -> set[str]:
            normalized = re.sub(
                r"\b([swdc])\s*/\s*o\b", r"\1o", str(value).lower()
            )
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
            relation_name_matches = _similarity(short_name, comparable_long_name) >= 0.75
            if relation_name_matches and (
                min(len(left_tokens), len(right_tokens)) <= 3 or len(shared) >= 3
            ):
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
        overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        return overlap >= 0.70 or _similarity(left, right) >= 0.82
    if field in NAME_FIELDS:
        return _similarity(_without_honorific(left), _without_honorific(right)) >= 0.90
    return _similarity(left, right) >= 0.88


def _without_honorific(value: Any) -> str:
    return re.sub(
        r"^\s*(?:mr|mrs|ms|miss|shri|smt|dr)\.?\s+",
        "",
        str(value or ""),
        flags=re.IGNORECASE,
    )


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _similarity(left: Any, right: Any) -> float:
    a, b = _compact(left), _compact(right)
    if not a or not b:
        return 0.0
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
