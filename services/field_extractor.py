"""Field extractor for DMEF.

Extracts structured fields from OCR-extracted text for each document type.
Called after classify_page() identifies the document type.

Public API
----------
extract_fields(document_type: str, text: str) -> dict
    Dispatches to the correct per-type extractor and returns a flat dict
    of field_name → value.

Cross-match contract (Sanction Letter & Loan Agreement)
-------------------------------------------------------
These fields are consumed by checklist_engine for Graviton cross-matching.
Field names and types MUST NOT change without updating the engine:

    loan_amount  → str   (digits only, no commas, no currency symbols)
    tenure       → int   (always normalised to number of months)
    emi          → str   (digits only, no commas, no currency symbols)
    roi          → float (percentage as a float, e.g. 8.5 for 8.5%)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from services.bureau_scores import has_explicit_no_score_evidence
from services.cersai import DEBTOR_BASED, search_criteria_text, search_type
from services.identifiers import plausible_aadhaar_digits
from services.person_names import canonicalize_person_name, is_name_field
from services.validation_gates import (
    has_labeled_aadhaar_value,
    is_aadhaar_verification_appendix,
    is_amortization_schedule,
)

# python-dateutil – graceful import with informative error
try:
    from dateutil import parser as _dateutil_parser
    _DATEUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DATEUTIL_AVAILABLE = False

# Lazy import to avoid circular dependency; only used inside extractors.
def _xml_cleaner(text: str) -> str:
    """Strip XML/digital-signature content from page text before field extraction."""
    try:
        from services.text_extractor import clean_xml_and_metadata  # noqa: PLC0415
        return clean_xml_and_metadata(text)
    except Exception:  # pragma: no cover
        return text


# ── Public dispatcher ─────────────────────────────────────────────────────────

def extract_fields(
    document_type: str,
    text: str,
    *,
    structured_content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured fields from *text* for *document_type*.

    Args:
        document_type: Classifier output (e.g. "Sanction Letter").
        text:          Raw OCR text of the page / document.
        structured_content: Optional OCR layout regions. Application-form
            address extraction uses these coordinates to avoid mixing values
            from adjacent form columns.

    Returns:
        Dict of field_name → extracted value (str | int | float | None).
        Unknown document types return an empty dict.
    """
    if document_type == "Aadhaar" and is_aadhaar_verification_appendix(text):
        return {"_aadhaar_verification_appendix": True}

    _EXTRACTORS = {
        "CAM":              _extract_cam,
        "Sanction Letter":  _extract_sanction_letter,
        "KFS":              _extract_sanction_letter,
        "Loan Agreement":   _extract_loan_agreement,
        "Facility Agreement": _extract_loan_agreement,
        "PAN":              _extract_pan,
        "PAN Card":         _extract_pan,
        "Aadhaar":          _extract_aadhaar,
        "Voter ID":         _extract_voter_id,
        "Driving License":  _extract_driving_license,
        "CERSAI Report":    _extract_cersai_report,
        "CRIF Report":      _extract_crif_report,
        "CIBIL Report":     _extract_crif_report,
        "Passbook":         _extract_passbook,
        "Bank Statement":   _extract_bank_statement,
        "Cheque":           _extract_cheque,
        "Salary Slip":      _extract_salary_slip,
        "Utility Bill":     _extract_utility_bill,
        "Application Form": _extract_application_form,
        "Insurance Form":   _extract_insurance_form,
        "Life Insurance Form": _extract_insurance_form,
        "End-Use Letter":   _extract_end_use_letter,
        "Stamp Duty":       _extract_stamp_duty,
        "Insurance Consent Letter": _extract_insurance_consent,
        "Legal Clearance Report": _extract_clearance_report,
        "Technical Clearance Report": _extract_clearance_report,
        "Technical Report": _extract_clearance_report,
        "NACH Form":        _extract_nach_form,
        "PDC":              _extract_pdc,
    }
    extractor = _EXTRACTORS.get(document_type)
    if extractor is None:
        return {}
    fields = _sanitize_name_fields(extractor(text))
    if document_type == "Application Form":
        fields.update(_extract_application_layout_addresses(structured_content))
    for field_name in ("address", "current_address", "permanent_address", "communication_address"):
        if field_name in fields:
            fields[field_name] = _sanitize_address_value(fields[field_name])
    for field_name, value in _extract_generic_labeled_fields(text).items():
        if field_name not in _generic_fields_allowed_for(document_type):
            continue
        value = _sanitize_generic_value(field_name, value)
        if fields.get(field_name) in (None, "", [], {}):
            if value not in (None, ""):
                fields[field_name] = value
    from services.repayment_schedule import extract_repayment_summary

    if _has_repayment_summary_evidence(text):
        for field_name, value in extract_repayment_summary(text).items():
            if fields.get(field_name) in (None, "", [], {}):
                fields[field_name] = value
    return fields


# ── Shared extraction helpers ─────────────────────────────────────────────────

def _digits_only(value: str) -> str:
    """Strip everything except digits and return as string."""
    return re.sub(r"[^\d]", "", value)


def _normalize_amount(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return str(int(number)) if number.is_integer() else (f"{number:.2f}".rstrip("0").rstrip("."))


def _extract_generic_labeled_fields(text: str) -> dict[str, Any]:
    """Extract clearly labelled fields shared by forms, CAMs and loan records."""
    labels = {
        "salutation": ("salutation",), "customer_id": ("customer id", "applicant id"),
        "application_number": ("application number", "application no", "loan account number", "loan id"),
        "ration_card_number": ("ration card number", "ration card no"),
        "gstin": ("gstin", "gst number"), "udyam_status": ("udyam status",),
        "kyc_status": ("kyc status", "kyc verification status"),
        "profile_photograph_present": ("profile photograph", "photograph status"),
        "facial_identity_status": ("facial identity", "face match status"),
        "age": ("age",), "gender": ("gender",), "marital_status": ("marital status",),
        "qualification": ("qualification",), "profession": ("profession",),
        "disability_status": ("disability status", "disabled"), "ews_status": ("ews status",),
        "caste": ("caste",), "religion": ("religion",), "medical_condition": ("medical condition",),
        "father_name": ("father's name", "father name"), "mother_name": ("mother's name", "mother name"),
        "relationship": ("relationship to applicant", "relation with applicant"),
        "phone_number": ("mobile number", "mobile no", "phone numbers", "phone number"), "email": ("email", "email id", "email ids"),
        "bank_linked_mobile": ("bank linked mobile", "mobile linked to bank"),
        "address_ownership": ("address ownership", "residence ownership"),
        "address_subtype": ("address subtype", "residence type"), "landmark": ("landmark",),
        "locality": ("village/locality", "locality", "village"), "tehsil": ("tehsil",),
        "district": ("district",), "state": ("state",), "country": ("country",),
        "pin_code": ("pin code", "pincode"), "occupied_since": ("occupied since", "residing since"),
        "latitude": ("latitude",), "longitude": ("longitude",),
        "employment_type": ("employment type",), "income_source": ("income source",),
        "occupation": ("occupation",), "work_profile": ("work profile",), "industry": ("industry",),
        "job_role": ("job role",), "job_description": ("job description",),
        "monthly_income": ("monthly declared income", "monthly income"),
        "verified_income": ("monthly verified income", "verified income"),
        "considered_income": ("income considered", "eligibility income"),
        "turnover": ("turnover",), "margin": ("margin",),
        "years_current_work": ("years in current work", "work vintage"),
        "overall_experience": ("overall experience", "total experience"),
        "income_stability": ("income stability",), "verification_method": ("verification method",),
        "income_proof_basis": ("income proof basis",), "verification_status": ("verification status",),
        "verifier": ("verified by", "verifier"), "field_remarks": ("field remarks", "pd remarks"),
        "bank_name": ("bank name", "name of bank"), "branch": ("bank branch", "branch"),
        "account_type": ("account type",), "bank_verification_status": ("bank verification status",),
        "primary_account": ("primary account",), "nach_status": ("nach status", "mandate status"),
        "mandate_amount": ("mandate amount",), "mandate_validity": ("mandate validity",),
        "payment_destination": ("payment destination",),
        "bureau_account_count": ("number of accounts", "total accounts"),
        "overdue_account_count": ("overdue account count", "overdue accounts"),
        "dpd_status": ("dpd status",), "credit_report_id": ("credit report id", "report id"),
        "monthly_obligations": ("monthly obligations",), "available_income": ("available income",),
        "maximum_emi": ("maximum emi", "max emi"), "foir": ("foir",),
        "loan_purpose": ("loan purpose",), "product_type": ("loan product", "product type"),
        "requested_amount": ("requested amount",), "recommended_amount": ("recommended amount",),
        "sanction_amount": ("sanctioned amount", "sanction amount"), "apr": ("apr",),
        "first_emi": ("first emi",), "final_emi": ("final emi",),
        "repayment_start_date": ("repayment commencement date", "repayment start date"),
        "maturity_date": ("maturity date",), "installment_count": ("scheduled installments", "installment count"),
        "total_interest": ("total interest",), "total_repayment": ("total borrower repayment", "total repayment"),
        "processing_fee": ("processing fee",), "insurance_amount": ("insurance amount",),
        "other_charges": ("other charges",), "net_disbursement": ("net disbursement",),
        "ltv": ("ltv", "loan to value"), "property_owner": ("property owner",),
        "ownership_type": ("ownership type",), "market_value": ("market value",),
        "distress_value": ("distress value",), "land_value": ("land value",),
        "construction_value": ("construction value",), "property_area": ("property area", "total area"),
        "property_address": ("property address", "document address"), "site_address": ("site address",),
        "property_usage": ("property usage",), "occupancy": ("occupancy",),
        "property_condition": ("property condition",), "construction_status": ("construction status",),
        "sanction_conditions": ("sanction conditions",), "approved_deviations": ("approved deviations",),
        "pending_conditions": ("pending conditions",), "tranche_structure": ("tranche structure",),
        "workflow_status": ("workflow status",), "repayment_status": ("repayment status",),
        "overdue_status": ("overdue status",),
    }
    fields: dict[str, Any] = {}
    for field_name, candidates in labels.items():
        value = _raw_value_after_label(text, *candidates)
        if value not in (None, ""):
            fields[field_name] = value
    return fields


_IDENTITY_GENERIC_FIELDS = {
    "salutation", "customer_id", "application_number", "ration_card_number", "gstin",
    "udyam_status", "kyc_status", "profile_photograph_present", "facial_identity_status",
    "age", "gender", "marital_status", "qualification", "profession",
    "disability_status", "ews_status", "caste", "religion", "medical_condition",
    "father_name", "mother_name", "relationship", "phone_number", "email",
}
_ADDRESS_GENERIC_FIELDS = {
    "address_ownership", "address_subtype", "landmark", "locality", "tehsil", "district",
    "state", "country", "pin_code", "occupied_since", "latitude", "longitude",
}
_BANK_GENERIC_FIELDS = {
    "bank_linked_mobile", "bank_name", "branch", "account_type", "bank_verification_status",
    "primary_account", "nach_status", "mandate_amount", "mandate_validity", "payment_destination",
}
_BUREAU_GENERIC_FIELDS = {
    "bureau_account_count", "overdue_account_count", "dpd_status", "credit_report_id",
    "monthly_obligations", "available_income", "maximum_emi", "foir",
}
_LOAN_GENERIC_FIELDS = {
    "loan_purpose", "product_type", "requested_amount", "recommended_amount", "sanction_amount",
    "apr", "first_emi", "final_emi", "repayment_start_date", "maturity_date",
    "installment_count", "total_interest", "total_repayment", "processing_fee",
    "insurance_amount", "other_charges", "net_disbursement", "ltv", "property_owner",
    "ownership_type", "market_value", "distress_value", "land_value", "construction_value",
    "property_area", "property_address", "site_address", "property_usage", "occupancy",
    "property_condition", "construction_status", "sanction_conditions", "approved_deviations",
    "pending_conditions", "tranche_structure", "workflow_status", "repayment_status", "overdue_status",
}
_EMPLOYMENT_GENERIC_FIELDS = {
    "employment_type", "income_source", "occupation", "work_profile", "industry", "job_role",
    "job_description", "monthly_income", "verified_income", "considered_income", "turnover",
    "margin", "years_current_work", "overall_experience", "income_stability",
    "verification_method", "income_proof_basis", "verification_status", "verifier", "field_remarks",
}


def _generic_fields_allowed_for(document_type: str) -> set[str]:
    """Limit generic labels to fields that are semantically valid for a document.

    Credit reports contain labels such as ``BRANCH ID``, month names such as APR,
    and historical sanctioned amounts.  Treating those as current loan fields was
    the main source of false mismatches in large packets.
    """
    if document_type in {"CRIF Report", "CIBIL Report"}:
        return _IDENTITY_GENERIC_FIELDS | _BUREAU_GENERIC_FIELDS
    if document_type in {"Aadhaar", "PAN", "PAN Card", "Voter ID", "Driving License"}:
        return _IDENTITY_GENERIC_FIELDS | _ADDRESS_GENERIC_FIELDS
    if document_type == "Application Form":
        return (
            _IDENTITY_GENERIC_FIELDS | _ADDRESS_GENERIC_FIELDS | _BANK_GENERIC_FIELDS
            | _BUREAU_GENERIC_FIELDS | _LOAN_GENERIC_FIELDS | _EMPLOYMENT_GENERIC_FIELDS
        )
    if document_type == "CAM":
        return (
            _IDENTITY_GENERIC_FIELDS | _ADDRESS_GENERIC_FIELDS | _BANK_GENERIC_FIELDS
            | _BUREAU_GENERIC_FIELDS | _LOAN_GENERIC_FIELDS | _EMPLOYMENT_GENERIC_FIELDS
        )
    if document_type in {"Sanction Letter", "KFS", "Loan Agreement", "Facility Agreement"}:
        return _IDENTITY_GENERIC_FIELDS | _LOAN_GENERIC_FIELDS | _ADDRESS_GENERIC_FIELDS
    if document_type == "End-Use Letter":
        return _IDENTITY_GENERIC_FIELDS | _LOAN_GENERIC_FIELDS
    if document_type in {"Bank Statement", "Passbook", "Cheque", "NACH Form"}:
        return _IDENTITY_GENERIC_FIELDS | _BANK_GENERIC_FIELDS
    if document_type in {"Technical Report", "Technical Clearance Report", "Legal Clearance Report"}:
        return _LOAN_GENERIC_FIELDS | {"latitude", "longitude", "application_number"}
    return set()


def _sanitize_generic_value(field_name: str, value: Any) -> Any:
    value_text = str(value or "").strip()
    if not value_text:
        return None
    compact = re.sub(r"\s+", " ", value_text)
    if field_name in {"phone_number", "bank_linked_mobile"}:
        digits = _digits_only(compact)
        return digits[-10:] if re.fullmatch(r"(?:91)?[6-9]\d{9}", digits) else None
    if field_name == "pin_code":
        digits = _digits_only(compact)
        return digits if re.fullmatch(r"\d{6}", digits) else None
    if field_name == "email":
        return compact if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", compact) else None
    if field_name in {"application_number", "customer_id", "credit_report_id", "gstin", "ration_card_number"}:
        return compact if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./_-]{3,40}", compact) else None
    if field_name in {
        "requested_amount", "recommended_amount", "sanction_amount", "apr", "first_emi", "final_emi",
        "installment_count", "total_interest", "total_repayment", "processing_fee", "insurance_amount",
        "other_charges", "net_disbursement", "ltv", "market_value", "distress_value", "land_value",
        "construction_value", "property_area", "monthly_income", "verified_income", "considered_income",
        "turnover", "margin", "monthly_obligations", "available_income", "maximum_emi", "foir",
        "bureau_account_count", "overdue_account_count", "mandate_amount", "latitude", "longitude",
    }:
        return compact if re.search(r"\d", compact) else None
    if field_name in {"father_name", "mother_name"}:
        return _clean_name_like_value(compact)
    if not re.search(r"[A-Za-z0-9]", compact):
        return None
    return compact


def _sanitize_address_value(value: Any) -> str | None:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if not compact:
        return None
    if _address_value_is_contaminated(compact):
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", compact.casefold()).strip()
    if re.fullmatch(
        r"(?:guarantor|co applicant|applicant)?\s*"
        r"(?:employment|employement|business|kyc|personal)?\s*details",
        normalized,
    ) or re.fullmatch(
        r"(?:guarantor|co applicant|applicant)\s+(?:address|details)",
        normalized,
    ):
        return None
    placeholder_tokens = {
        "address", "landmark", "locality", "city", "district", "pin", "code",
        "state", "country", "village", "tehsil",
    }
    latin_tokens = re.findall(r"[A-Za-z0-9]+", compact)
    if latin_tokens and not any(token.isdigit() for token in latin_tokens):
        if {token.casefold() for token in latin_tokens} <= placeholder_tokens:
            return None
    if not re.search(r"\b\d{6}\b", compact) and len(latin_tokens) < 3:
        return None
    return compact


_ADDRESS_FORM_NOISE_PATTERNS = (
    r"\baadhaar\s+no\b",
    r"\bdriving\s+licen[cs]e\b",
    r"\bpan\s*/?\s*gir\b",
    r"\bprofessionally\s+qualified\b",
    r"\bbusiness\s+constitution\b",
    r"\b(?:undergraduate|graduate|postgraduate|post\s+graduate)\b",
    r"\b(?:mobile|telephone|whatsapp)(?:\s+(?:number|no|contact))?\b",
    r"\b(?:nature|industry|sector)\s+of\s+business\b",
)


def _address_value_is_contaminated(value: str) -> bool:
    """Reject form-label soup produced by flattened multi-column OCR."""
    normalized = re.sub(r"\s+", " ", str(value or "")).casefold()
    noise_hits = sum(bool(re.search(pattern, normalized)) for pattern in _ADDRESS_FORM_NOISE_PATTERNS)
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    return noise_hits >= 2 or (noise_hits >= 1 and len(tokens) > 28) or len(tokens) > 55


def _raw_value_after_label(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*[:\-–]\s*([^\n\r]{{1,160}})",
            text,
            re.IGNORECASE,
        )
        if match:
            value = match.group(1).strip(" :\t")
            if value:
                return value
    return None


def _extract_amount(text_lower: str, *label_patterns: str) -> str | None:
    """Extract a numeric amount following any of the label phrases.

    Handles Indian comma-separated formats like 5,00,000.
    Returns digits-only string (no commas, no ₹/Rs.).
    """
    for pattern in label_patterns:
        match = re.search(
            rf"{re.escape(pattern)}[ \t]*[:\-–]?[ \t]*(?:rs\.?|₹|inr)?[ \t]*([\d,]+(?:\.\d+)?)",
            text_lower,
        )
        if match:
            return _normalize_amount(match.group(1))
    return None


def _numeric_line_after_label(text: str, *labels: str, max_lines: int = 8) -> str | None:
    """Return the next value-like line after a bilingual table label."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        normalized = re.sub(r"\s+", " ", line.strip()).lower()
        if not any(normalized == label or normalized.startswith(f"{label} ") for label in labels):
            continue
        for candidate_line in lines[index + 1:index + 1 + max_lines]:
            candidate = candidate_line.strip()
            match = re.fullmatch(
                r"(?:rs\.?\s*)?([\d,]+(?:\.\d+)?)\s*(?:%|fixed|months?|/-)?",
                candidate,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)
    return None


def _has_repayment_summary_evidence(text: str) -> bool:
    """Gate the broad KFS summary parser on real table structure.

    Loan boilerplate can mention a KFS and ``rate of interest`` before a
    numbered clause such as ``6. In case of digital loans``.  A loose
    cross-line regex previously turned that clause number into ROI=6.  Real KFS
    summaries expose at least two labelled rows (or the explicit APR
    illustration heading).
    """
    raw = str(text or "")
    if re.search(r"\billustration\s+for\s+computation\s+of\s+apr\b", raw, re.I):
        return True
    row_patterns = (
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?(?:sanctioned\s+)?loan\s+amount\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?loan\s+term\b",
        r"(?:^|\n)\s*(?:[A-Z][.)]\s*)?type\s+of\s+emi\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?rate\s+of\s+interest\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?total\s+interest\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?net\s+disburs(?:ed|ement)\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?total\s+amount\s+to\s+be\s+paid\b",
    )
    return sum(bool(re.search(pattern, raw, re.I)) for pattern in row_patterns) >= 2


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(float(str(value))) if value not in (None, "") else None
    except ValueError:
        return None


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(str(value)) if value not in (None, "") else None
    except ValueError:
        return None


def _extract_tenure_months(text_lower: str) -> int | None:
    """Extract tenure and normalise to integer number of months.

    Recognises:
      - "60 months" / "60 month"
      - "5 years"  / "5 year"
      - bare digits after "tenure" when no unit is present
    """
    # Explicit months
    match = re.search(
        r"(?:loan\s+)?tenure\s*[:\-–]?\s*(\d+)\s*months?",
        text_lower,
    )
    if match:
        return int(match.group(1))

    # Explicit years → convert
    match = re.search(
        r"(?:loan\s+)?tenure\s*[:\-–]?\s*(\d+)\s*years?",
        text_lower,
    )
    if match:
        return int(match.group(1)) * 12

    # Fallback: bare number after "tenure"
    match = re.search(
        r"(?:loan\s+)?tenure\s*[:\-–]?\s*(\d+)",
        text_lower,
    )
    if match:
        return int(match.group(1))

    return None


def _extract_roi(text_lower: str) -> float | None:
    """Extract rate of interest as a float (e.g. 8.5)."""
    # Look for percentage near roi / rate of interest
    match = re.search(
        r"(?:rate of interest|roi)\s*[:\-–]?\s*(\d+\.?\d*)\s*%",
        text_lower,
    )
    if match:
        return float(match.group(1))

    return None


def _extract_percentage_near(text_lower: str, *labels: str) -> float | None:
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\b\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*%?", text_lower)
        if match:
            return float(match.group(1))
    return None


def _extract_identifier(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:\-–#]?\s*([A-Z0-9][A-Z0-9\-/]{{3,40}})", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_emi(text_lower: str) -> str | None:
    """Extract EMI amount (digits only).

    Handles labels:
      - "emi amount"  (spec: "EMI Amount: Rs. 10,500")
      - "emi"
      - "equated monthly instalment"
    """
    # KFS APR illustrations commonly present the value as
    # ``Monthly 8234.00 & 60`` below a bilingual "Type of EMI" heading.
    # Read that row before the generic label matcher, which can otherwise
    # wander into the preceding sanctioned-loan-amount value.
    monthly_row = re.search(
        r"\bmonthly\s+(?:rs\.?\s*)?([\d,]+(?:\.\d+)?)\s*(?:&|and)\s*\d+\b",
        text_lower,
    )
    if monthly_row:
        return _normalize_amount(monthly_row.group(1))

    # On amortisation pages the first row can be a broken-period instalment
    # (for example 2582), while the recurring EMI is repeated in later rows.
    # Select the modal EMI column value rather than the serial number directly
    # below the table heading.
    if "repayment schedule" in text_lower and re.search(r"emi\s*\(\s*in\s+rs", text_lower):
        schedule_values = [
            _normalize_amount(value)
            for _, _, value, _, _, _ in re.findall(
                r"(?:^|\n)\s*(\d+)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)",
                text_lower,
            )
        ]
        if schedule_values:
            recurring = max(set(schedule_values), key=schedule_values.count)
            if schedule_values.count(recurring) >= 2:
                return recurring

    match = re.search(
        r"(?:^|\n)\s*(?:emi(?:\s+amount)?|equated\s+monthly\s*instalment?)"
        r"\s*\*?\s*(?:\(\s*in\s+rs\.?\s*\))?\s*[:\-–]?\s*(?:rs\.?|₹|inr)?\s*"
        r"(?:\n\s*)?([\d,]+)(?![A-Za-z-])",
        text_lower,
    )
    if match:
        return _digits_only(match.group(1))
    return None


def _line_after_label(text: str, *labels: str) -> str | None:
    """Return the first non-empty line that follows any of *labels*."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        matched_label = next(
            (
                label for label in labels
                if re.fullmatch(rf"{re.escape(label)}\s*[:\-–]?", line_stripped, re.IGNORECASE)
                or re.match(rf"^{re.escape(label)}\s*[:\-–]\s*\S", line_stripped, re.IGNORECASE)
            ),
            None,
        )
        if matched_label:
            # Try the remainder of the same line first
            parts = re.split(r"[:\-–]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                candidate = _clean_name_like_value(parts[1])
                if candidate:
                    return candidate
            # Else next non-empty line (bounded to 8 lines max)
            for j in range(i + 1, min(len(lines), i + 9)):
                if not any(character.isalpha() for character in lines[j]):
                    continue
                candidate = _clean_name_like_value(lines[j])
                if candidate:
                    return candidate
    return None


def _clean_name_like_value(value: str) -> str | None:
    candidate = canonicalize_person_name(value)
    return candidate.value if candidate.valid else None


def _sanitize_name_fields(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(fields)
    for field_name, value in list(cleaned.items()):
        if str(field_name).startswith("_"):
            continue
        if field_name == "person_records" and isinstance(value, list):
            cleaned[field_name] = [
                _sanitize_name_fields(record) if isinstance(record, dict) else record
                for record in value
            ]
            continue
        if isinstance(value, list):
            if is_name_field(field_name):
                names = [
                    candidate.value
                    for item in value
                    if (candidate := canonicalize_person_name(item)).valid
                ]
                cleaned[field_name] = names
            continue
        if is_name_field(field_name) and value not in (None, ""):
            candidate = canonicalize_person_name(value)
            cleaned[field_name] = candidate.value if candidate.valid else None
    return cleaned


def _lines_after_label(text: str, label: str, max_lines: int = 3) -> str | None:
    """Return up to *max_lines* lines following *label*, joined by spaces."""
    lines = text.splitlines()
    stop_labels = {
        "name", "applicant name", "father name", "date of birth", "dob",
        "date of issue", "issue date", "issued on", "valid till", "valid upto",
        "validity", "licence no", "license no", "dl no", "address", "pin code",
        "gender", "sex", "date", "mobile", "phone", "blood group",
    }
    for i, line in enumerate(lines):
        if not re.search(rf"\b{re.escape(label)}\b", line, re.IGNORECASE):
            continue
        collected: list[str] = []
        inline = re.split(r"[:\-–]", line, maxsplit=1)
        if len(inline) == 2 and inline[1].strip():
            return inline[1].strip()
        for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
            part = lines[j].strip()
            if not part:
                continue
            normalized = _normalize_label(part).split(":", 1)[0]
            if normalized in stop_labels or any(
                normalized.startswith(f"{stop} ") for stop in stop_labels
            ):
                break
            collected.append(part)
        return " ".join(collected) if collected else None
    return None


def _lines_after_label_until_stop(
    text: str,
    label: str,
    *,
    stop_labels: set[str],
    max_lines: int = 4,
) -> str | None:
    """Return lines after *label* until a known non-address label is reached."""
    lines = text.splitlines()
    normalized_stops = {_normalize_label(stop_label) for stop_label in stop_labels}
    for i, line in enumerate(lines):
        if label in line.lower():
            collected: list[str] = []
            for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
                part = lines[j].strip()
                if not part:
                    continue
                if _normalize_label(part).split(":")[0] in normalized_stops:
                    break
                if any(_normalize_label(part).startswith(stop) for stop in normalized_stops):
                    break
                collected.append(part)
            return " ".join(collected) if collected else None
    return None


def _value_after_label(text: str, *labels: str) -> str | None:
    """Return the next useful value after an exact-ish OCR label."""
    lines = [line.strip() for line in text.splitlines()]
    normalized_labels = {_normalize_label(label) for label in labels}
    stop_labels = {
        "aadhaar",
        "address",
        "date of birth",
        "dob",
        "mobile number",
        "name of the debtor",
        "pan",
        "search criteria",
        "search reference number",
        "transaction id",
    }
    for index, line in enumerate(lines):
        for label in labels:
            inline_match = re.match(
                rf"^\s*{re.escape(label)}\s*[:\-–]\s*(.+?)\s*$",
                line,
                re.IGNORECASE,
            )
            if inline_match:
                return inline_match.group(1).strip(" :\t\r\n")
        normalized_line = _normalize_label(line)
        if normalized_line not in normalized_labels:
            continue
        for candidate in lines[index + 1: index + 5]:
            normalized_candidate = _normalize_label(candidate)
            if not candidate or normalized_candidate in stop_labels:
                continue
            return candidate.strip(" :\t\r\n")
    return None


def _normalize_label(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-z]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_date(text: str) -> str | None:
    """Parse *text* as a date and return ISO-8601 string, or None on failure."""
    stripped = str(text or "").strip()
    # dateutil with dayfirst=True swaps the month and day of already-normalized
    # ISO dates (for example 1994-12-05 -> 1994-05-12). Preserve ISO semantics.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        try:
            return date.fromisoformat(stripped).isoformat()
        except ValueError:
            return None
    if not _DATEUTIL_AVAILABLE:
        # Fallback: return the raw string stripped of noise
        return stripped or None
    try:
        dt = _dateutil_parser.parse(stripped, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def _extract_date_near(text_lower: str, *anchors: str) -> str | None:
    """Find a date-like pattern near any of the anchor keywords."""
    date_pattern = re.compile(
        r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"   # DD/MM/YYYY or DD-MM-YY
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"            # YYYY-MM-DD
        r"|\d{1,2}[-\s]+\w+[-\s]+\d{4})\b"           # 01-January-2025
    )
    for anchor in anchors:
        idx = text_lower.find(anchor)
        if idx == -1:
            continue
        # Search in a 120-character window around the anchor
        window = text_lower[max(0, idx - 20): idx + 100]
        match = date_pattern.search(window)
        if match:
            return _parse_date(match.group(0))
    return None


def _extract_date_after_label(text: str, *labels: str) -> str | None:
    """Extract a date immediately following one of the supplied labels."""
    date_pattern = (
        r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"
        r"|\d{1,2}[-\s]+\w+[-\s]+\d{4}"
    )
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*[:\-–]?\s*({date_pattern})",
            text,
            re.IGNORECASE,
        )
        if match:
            return _parse_date(match.group(1))
    return None


def _is_past_date(iso_date: str | None) -> bool:
    """Return True if *iso_date* is before today."""
    if iso_date is None:
        return False
    try:
        return date.fromisoformat(iso_date) < date.today()
    except ValueError:
        return False


# ── Per-document-type extractors ──────────────────────────────────────────────

def _extract_cam(text: str) -> dict[str, Any]:
    """Extract conservative loan-level fields from a Credit Approval Memo.

    CAM pages contain many applicant, KYC, bureau and sanction tables. Treating
    an individual table heading as a standalone Aadhaar/PAN/sanction document
    creates false identity mismatches. Only the unambiguous application-details
    block is extracted here; the remaining CAM tables stay available as page
    evidence without being assigned to the wrong person.
    """
    if not re.search(r"\bcredit\s+(?:approval|appraisal)\s+memo\b", text, re.IGNORECASE):
        return {}
    person_records = [
        *_extract_cam_person_records(text),
        *_extract_cam_kyc_records(text),
        *_extract_cam_address_records(text),
        *_extract_cam_score_records(text),
    ]
    decision_fields = _extract_cam_decision_fields(text)
    if not re.search(r"\bapplication\s+details\b", text, re.IGNORECASE):
        return {"person_records": person_records, **decision_fields}

    application_number = _next_nonempty_line(text, "application id")
    applicant_name = _clean_name_like_value(_next_nonempty_line(text, "name") or "")
    phone_number = _sanitize_generic_value(
        "phone_number", _next_nonempty_line(text, "mobile number")
    )
    tenure_value = _normalize_amount(_next_nonempty_line(text, "tenure"))
    requested_amount = _normalize_amount(
        _next_nonempty_line(text, "requested loan amount")
    )
    requested_roi = _float_or_none(
        _normalize_amount(_next_nonempty_line(text, "requested irr"))
    )
    return {
        "application_number": application_number,
        "applicant_name": applicant_name,
        "phone_number": phone_number,
        "tenure": _int_or_none(tenure_value),
        "requested_amount": requested_amount,
        "roi": requested_roi,
        "loan_purpose": _next_nonempty_line(text, "purpose of loan"),
        "branch": _next_nonempty_line(text, "branch name"),
        "person_records": person_records,
        **decision_fields,
    }


def _extract_cam_decision_fields(text: str) -> dict[str, Any]:
    """Extract the vertically stacked sanction-decision and repayment-bank tables.

    CAM exports place all decision labels first and all values beneath them, so
    ordinary ``label: value`` matching cannot safely associate the columns.
    Requiring the complete ordered header block prevents unrelated numbers on a
    CAM page from being mistaken for current sanction terms.
    """
    decision = re.search(
        r"(?:^|\n)\s*DECISION\s*\n"
        r"\s*Sanction\s+Loan\s+Amount\s*\n"
        r"\s*Sanction\s+Tenure\s*\n"
        r"\s*Advance\s+EMI\s*\n"
        r"\s*Sanction\s+Rate\s*\n"
        r"\s*Sanction\s+EMI\s*\n"
        r"\s*Sanction\s+Date\s*\n"
        r"\s*Sanction\s+Remarks\s*\n"
        r"\s*Username\s*\n"
        r"\s*([\d,]+(?:\.\d+)?)\s*\n"
        r"\s*(\d{1,3})\s*\n"
        r"\s*([^\n\r]{1,30})\s*\n"
        r"\s*(\d+(?:\.\d+)?)\s*\n"
        r"\s*([\d,]+(?:\.\d+)?)\b",
        text,
        re.IGNORECASE,
    )
    fields: dict[str, Any] = {}
    if decision:
        amount = _normalize_amount(decision.group(1))
        fields.update({
            "loan_amount": amount,
            "sanction_amount": amount,
            "tenure": _int_or_none(decision.group(2)),
            "roi": _float_or_none(decision.group(4)),
            "emi": _normalize_amount(decision.group(5)),
        })

    if re.search(r"\bREPAYMENT\s+BANK\s+DETAILS\b", text, re.IGNORECASE):
        section_match = re.search(
            r"\bREPAYMENT\s+BANK\s+DETAILS\b(.*?)(?=\n\s*(?:DECISION|SANCTION\s+CONDITIONS)\b|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        bank_text = section_match.group(1) if section_match else ""
        fields.update({
            "account_number": _digits_only(_next_nonempty_line(bank_text, "account number") or "") or None,
            "ifsc": (_next_nonempty_line(bank_text, "ifsc code") or "").upper() or None,
            "account_holder_name": _next_nonempty_line(bank_text, "account holder name"),
        })
    return fields


def _next_nonempty_line(text: str, label: str, *, max_lines: int = 3) -> str | None:
    """Return a short table value immediately below an exact label line."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.sub(r"\s+", " ", line.strip()).casefold() != label.casefold():
            continue
        for candidate_line in lines[index + 1:index + 1 + max_lines]:
            candidate = re.sub(r"\s+", " ", candidate_line.strip())
            if candidate:
                return candidate[:160]
    return None


def _extract_cam_person_records(text: str) -> list[dict[str, Any]]:
    """Extract repeated person rows from the CAM personal-details table."""
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*(Applicant|Coapplicant)\s*\n"
        r"\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*([6-9]\d{9})\s*\n"
        r"\s*(\d{1,2}-[A-Za-z]+-(?:\s*\n\s*)?\d{4})",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        records.append({
            "applicant_name": re.sub(r"\s+", " ", match.group(2)).strip(),
            "phone_number": match.group(3),
            "date_of_birth": _parse_date(re.sub(r"\s+", "", match.group(4))),
        })
    return records


def _extract_cam_kyc_records(text: str) -> list[dict[str, Any]]:
    """Extract name-scoped masked Aadhaar and PAN values from the CAM."""
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*(?:Applicant|Co[\s-]*Applicant)\s*\n"
        r"\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*([X*]{8}\d{4})\s*\n"
        r"\s*([A-Z]{5}\d{4}[A-Z])\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        records.append({
            "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
            "aadhaar_last4": match.group(2)[-4:],
            "pan_number": match.group(3).upper(),
        })
    return records


def _extract_cam_address_records(text: str) -> list[dict[str, Any]]:
    """Extract current/permanent address rows from the CAM address table."""
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*(?:Applicant|Co[\s-]*Applicant)\s*\n"
        r"\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*(?:Owned|Rented|Family Owned)\s*\n"
        r"\s*(Permanent|Current|Communication)\s*\n"
        r"(.*?)"
        r"(?=\n\s*(?:Applicant|Co[\s-]*Applicant)\s*\n|\n\s*CREDIT SCORE\b|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        address = _sanitize_address_value(match.group(3))
        if not address:
            continue
        subtype = match.group(2).lower()
        records.append({
            "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
            "address": address,
            f"{subtype}_address": address,
        })
    return records


def _extract_cam_score_records(text: str) -> list[dict[str, Any]]:
    """Extract numeric CRIF/CIBIL scores from the CAM credit-score table."""
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*(?:Applicant|Coapplicant)\s*\n"
        r"\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*(CRIF|CIBIL)\s*\n\s*(\d{3}|NA)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        if not match.group(3).isdigit():
            continue
        bureau = match.group(2).lower()
        records.append({
            "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
            f"{bureau}_score": match.group(3),
        })
    return records


def _extract_application_coapplicant_records(text: str) -> list[dict[str, Any]]:
    """Extract co-applicant rows whose values are stacked below table headers."""
    if "CO-APPLICANT DETAILS" not in text.upper():
        return []
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*(\d{1,2}-[A-Za-z]+-(?:\s*\n\s*)?\d{4})\s*\n"
        r"\s*([A-Za-z][A-Za-z ]{1,60}?)\s*\n"
        r"\s*([6-9]\d{9})\s*\n"
        r"\s*(FATHER|MOTHER|WIFE|HUSBAND|SON|DAUGHTER)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        records.append({
            "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
            "date_of_birth": _parse_date(re.sub(r"\s+", "", match.group(2))),
            "father_name": re.sub(r"\s+", " ", match.group(3)).strip(),
            "phone_number": match.group(4),
            "relationship": match.group(5).title(),
        })
    return records


def _extract_sanction_letter(text: str) -> dict[str, Any]:
    """Extract fields from a Sanction Letter.

    Cross-match fields (exact names required by checklist_engine):
        loan_amount  → str   digits only
        tenure       → int   months
        emi          → str   digits only
        roi          → float percentage
    """
    t = text.lower()
    return {
        "loan_amount": _extract_amount(
            t, "sanctioned loan amount", "sanctioned amount", "loan amount", "amount sanctioned",
            "amount of facility", "sanction amount"
        ) or _normalize_amount(_numeric_line_after_label(
            text, "sanctioned loan amount (in rs.)", "sanction amount", "amount of facility (in rs.)"
        )),
        "tenure": _extract_tenure_months(t) or _int_or_none(
            _numeric_line_after_label(text, "loan terms (months)", "tenure (months)")
        ),
        "emi": _extract_emi(t) or _normalize_amount(_numeric_line_after_label(text, "epi (in rs.)", "emi")),
        "roi": _extract_roi(t) or _float_or_none(_numeric_line_after_label(
            text, "roi (p.a)", "interest rate (%) and type"
        )),
        "apr": _extract_percentage_near(t, "apr", "annual percentage rate"),
        "applicant_name": _line_after_label(text, "borrower", "applicant name"),
        "application_number": _extract_identifier(text, "application number", "application no", "loan account number", "loan id"),
        "first_emi": _extract_amount(t, "first emi"),
        "final_emi": _extract_amount(t, "final emi", "last emi"),
        "processing_fee": _extract_amount(t, "processing fee"),
        "insurance_amount": _extract_amount(t, "insurance amount", "insurance premium"),
        "net_disbursement": _extract_amount(t, "net disbursement", "net disbursal"),
        "repayment_start_date": _extract_date_near(t, "repayment start date", "first emi date"),
        "maturity_date": _extract_date_near(t, "maturity date", "last emi date"),
        "foir": _extract_percentage_near(t, "foir"),
        "ltv": _extract_percentage_near(t, "ltv", "loan to value"),
    }


def _extract_loan_agreement(text: str) -> dict[str, Any]:
    """Extract fields from a Loan Agreement.

    Cross-match fields match Sanction Letter naming exactly.
    """
    t = text.lower()
    schedule_name = re.search(
        r"APPLICANT\s+NAME\s+ADDRESS\s+TYPE\s+ADDRESS\s+(?:Mr\.?|Mrs\.?|Ms\.?)?\s*"
        r"([A-Za-z][A-Za-z\s]{2,60}?)\s+(?:Current|Permanent)",
        text,
        re.IGNORECASE,
    )
    return {
        "loan_amount": _extract_amount(
            t, "amount of facility", "loan amount", "sanctioned amount", "amount sanctioned"
        ) or _normalize_amount(_numeric_line_after_label(text, "amount of facility (in rs.)")),
        "tenure": _extract_tenure_months(t) or _int_or_none(
            _numeric_line_after_label(text, "term or tenure")
        ),
        "emi": _extract_emi(t) or _normalize_amount(_numeric_line_after_label(
            text, "emi amount* (in rs.)", "emi amount (in rs.)"
        )),
        "roi": _extract_roi(t) or _float_or_none(_numeric_line_after_label(text, "rate of interest")),
        "apr": _extract_percentage_near(t, "apr", "annual percentage rate"),
        "borrower_name": (
            re.sub(r"\s+", " ", schedule_name.group(1)).strip()
            if schedule_name else _line_after_label(text, "borrower")
        ),
        "agreement_date": _extract_date_near(t, "date of agreement", "agreement date", "date"),
        "application_number": _extract_identifier(text, "application number", "application no", "loan account number", "loan id"),
        "processing_fee": _extract_amount(t, "processing fee"),
        "insurance_amount": _extract_amount(t, "insurance amount", "insurance premium"),
        "net_disbursement": _extract_amount(t, "net disbursement", "net disbursal"),
        "repayment_start_date": _extract_date_near(t, "repayment start date", "first emi date"),
        "maturity_date": _extract_date_near(t, "maturity date", "last emi date"),
    }


def _extract_end_use_letter(text: str) -> dict[str, Any]:
    purpose_match = re.search(
        r"purpose\s+of\s*:\s*([^\n\r]+)(?:\r?\n(?!\s*I\s*/\s*We\b)([^\n\r]+))?",
        text,
        re.IGNORECASE,
    )
    purpose = None
    if purpose_match:
        purpose = " ".join(
            part.strip(" .")
            for part in purpose_match.groups()
            if part and part.strip(" .")
        )
    reference_match = re.search(
        r"(?:^|\n)\s*(?:Ref\.?|Loan\s+No\.?)\s*[:\-]\s*([A-Z0-9][A-Z0-9/-]{3,40})",
        text,
        re.IGNORECASE,
    )
    return {
        "loan_purpose": purpose,
        "application_number": reference_match.group(1) if reference_match else None,
    }


def _extract_pan(text: str) -> dict[str, Any]:
    """Extract fields from a PAN card."""
    text = _xml_cleaner(text)
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper())
    if not pan_match and not re.search(
        r"\b(?:permanent\s+account\s+number|income\s+tax|govt\.?\s+of\s+india|pan\s+card)\b",
        text,
        re.IGNORECASE,
    ):
        return {}
    inline_name = None
    if pan_match:
        after_pan = text[pan_match.end():pan_match.end() + 160]
        name_match = (
            re.search(
                r"\bH?Name\s+([A-Za-z][A-Za-z ]{2,60}?)"
                r"(?=\s+(?:[A-Za-z]?\d|[\u0900-\u097f]|Date\b|Father\b))",
                after_pan,
                re.IGNORECASE,
            )
            or re.search(
                r"(?:Account\s+Number\s+)?(?:नाम\s*)?(?:[A-Z]?\s*Name\s+)?"
                r"([A-Za-z][A-Za-z ]{2,60}?)(?=\s+(?:[\u0900-\u097f]|Date\b|Father\b))",
                after_pan,
                re.IGNORECASE,
            )
        )
        inline_name = _clean_name_like_value(name_match.group(1)) if name_match else None
    dob = _extract_date_near(text.lower(), "date of birth", "dob")
    if dob is None:
        damaged_date = re.search(r"(?:date|fafuDate)\s+(\d{2})7(\d{2})/(\d{4})", text, re.IGNORECASE)
        if damaged_date:
            dob = _parse_date("/".join(damaged_date.groups()))
    return {
        "applicant_name": _line_after_label(
            text,
            "name",
            "applicant name",
            "card holder name",
        ) or inline_name,
        "pan_number": pan_match.group(1) if pan_match else None,
        "dob": dob,
    }


def _extract_aadhaar(text: str) -> dict[str, Any]:
    """Extract fields from an Aadhaar card."""
    if is_aadhaar_verification_appendix(text):
        return {"_aadhaar_verification_appendix": True}
    heading = " ".join(
        line.strip() for line in str(text or "").splitlines()[:6] if line.strip()
    )
    if re.search(
        r"\bself[\s-]*declaration\b[\s\S]{0,80}\bcurrent\s+address\b",
        heading,
        re.IGNORECASE,
    ):
        return {}
    xml_fields = _extract_aadhaar_xml(text)
    text = _xml_cleaner(text)
    digilocker_fields = _extract_digilocker_aadhaar_summary(text)
    aadhaar_match = re.search(r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)", text)
    authority_evidence = bool(re.search(
        r"unique\s+identification\s+authority|\buidai\b|e-?aadhaar|"
        r"भारतीय\s+विशिष्ट\s+पहचान|मेरा\s+आधार",
        text,
        re.IGNORECASE,
    ))
    form_kyc_section = bool(re.search(
        r"(?:applicant|co[\s-]*applicant|guarantor)\s+kyc\s+details",
        text,
        re.IGNORECASE,
    ))
    if form_kyc_section and not authority_evidence:
        return {}
    aadhaar_number = plausible_aadhaar_digits(aadhaar_match.group(1)) if aadhaar_match else None
    relation_match = re.search(
        r"\b(S\s*/\s*O|D\s*/\s*O|W\s*/\s*O|C\s*/\s*O|son\s+of|daughter\s+of|wife\s+of|care\s+of)\b\s*[:\-]?\s*([^\n\r,]{3,70})",
        text,
        re.IGNORECASE,
    )
    qualifier = re.sub(r"\s+", "", relation_match.group(1)).upper() if relation_match else None
    qualifier = {"SONOF": "S/O", "DAUGHTEROF": "D/O", "WIFEOF": "W/O", "CAREOF": "C/O"}.get(qualifier or "", qualifier)
    result = {
        "applicant_name": (
            xml_fields.get("applicant_name")
            or digilocker_fields.get("applicant_name")
            or _line_after_label(text, "name", "नाम")
        ),
        "aadhaar_number": aadhaar_number,
        "aadhaar_last4": xml_fields.get("aadhaar_last4") or digilocker_fields.get("aadhaar_last4"),
        "dob": (
            xml_fields.get("dob")
            or digilocker_fields.get("dob")
            or _extract_date_near(text.lower(), "date of birth", "dob", "year of birth", "yob")
        ),
        "address": (
            xml_fields.get("address")
            or digilocker_fields.get("address")
            or _extract_aadhaar_address(text)
        ),
        "pin_code": xml_fields.get("pin_code") or digilocker_fields.get("pin_code"),
        "gender": xml_fields.get("gender") or digilocker_fields.get("gender"),
        "relationship_qualifier": (
            xml_fields.get("relationship_qualifier")
            or digilocker_fields.get("relationship_qualifier")
            or qualifier
        ),
        "related_person_name": (
            xml_fields.get("related_person_name")
            or digilocker_fields.get("related_person_name")
        ) or (
            _clean_name_like_value(relation_match.group(2)) if relation_match else None
        ),
    }
    return result


def _extract_digilocker_aadhaar_summary(text: str) -> dict[str, Any]:
    """Parse DigiLocker label-first/value-second Aadhaar summary pages."""
    if not re.search(r"DigiLocker\s+verified\s+e-?Aadhaar", text or "", re.IGNORECASE):
        return {}

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    fields: dict[str, Any] = {}
    masked = re.search(r"(?i)\b[x*]{4,}(\d{4})\b", text or "")
    if masked:
        fields["aadhaar_last4"] = masked.group(1)

    for index, line in enumerate(lines):
        if not re.fullmatch(r"\d{2}[-/.]\d{2}[-/.]\d{4}", line):
            continue
        if index == 0 or index + 1 >= len(lines):
            continue
        gender = lines[index + 1].upper()
        if gender not in {"MALE", "FEMALE", "TRANSGENDER"}:
            continue
        name = _clean_name_like_value(lines[index - 1])
        if name:
            fields["applicant_name"] = name
            fields["dob"] = _parse_date(line)
            fields["gender"] = gender
            break

    relationship_pattern = re.compile(r"^(S/O|D/O|W/O|C/O)\s*:?\s*([^,\n]{2,70})", re.IGNORECASE)
    relationship_rows = [
        index for index, line in enumerate(lines) if relationship_pattern.match(line)
    ]
    for index in relationship_rows:
        line = lines[index]
        relationship = relationship_pattern.match(line)
        assert relationship is not None
        related_name = _clean_name_like_value(relationship.group(2))
        if related_name and not fields.get("related_person_name"):
            fields["relationship_qualifier"] = relationship.group(1).upper()
            fields["related_person_name"] = related_name

        # DigiLocker table extraction often repeats the relationship at the
        # start of the actual address, splitting both a name and PIN over lines
        # ("S/O: Nanga" + "Ram,Deoli..." and "30402" + "3").
        nearby = lines[index : index + 7]
        if not any("," in part for part in nearby[:3]):
            continue
        address = re.sub(r"\s+", " ", " ".join(nearby))
        address = re.sub(
            r"\b([1-8]\d{1,4})\s+(\d{1,4})\b",
            lambda match: (
                match.group(1) + match.group(2)
                if len(match.group(1) + match.group(2)) == 6
                else match.group(0)
            ),
            address,
        )
        pin = re.search(r"\b([1-8]\d{5})\b", address)
        if not pin:
            continue
        address = address[:pin.end()]
        combined_relationship = relationship_pattern.match(address)
        if combined_relationship:
            combined_name = _clean_name_like_value(combined_relationship.group(2))
            if combined_name and len(combined_name) > len(str(fields.get("related_person_name") or "")):
                fields["related_person_name"] = combined_name
            address = address[combined_relationship.end():].lstrip(" ,")
        fields["pin_code"] = pin.group(1)
        fields["address"] = address
        break

    if not fields.get("pin_code"):
        pin = re.search(r"(?m)^\s*([1-8]\d{5})\s*$", text or "")
        if pin:
            fields["pin_code"] = pin.group(1)
    return fields


def _extract_aadhaar_xml(text: str) -> dict[str, Any]:
    """Read identity and PoA attributes from digitally signed e-Aadhaar XML.

    The certificate following ``Poa`` contains a second postal address for the
    signing authority.  Regexing the word "address" therefore captured the
    certificate subject instead of the holder's Aadhaar address.
    """
    # Aadhaar XML back pages can omit ``Poi`` while still carrying the holder
    # name in ``LData`` and the authoritative address/relationship in ``Poa``.
    # Requiring ``Poi`` made those pages fall through to generic/LLM extraction,
    # which could mistake the signing certificate's postal code for the
    # holder's PIN and the holder's own name for their related person's name.
    if "<UidData" not in text or "<Poa" not in text:
        return {}
    try:
        uid_fragment = re.search(r"<UidData\b[^>]*", text, re.IGNORECASE)
        poi_fragment = re.search(r"<Poi\b[^>]*/?>", text, re.IGNORECASE)
        ldata_fragment = re.search(r"<LData\b[^>]*/?>", text, re.IGNORECASE)
        poa_fragment = re.search(r"<Poa\b[^>]*/?>", text, re.IGNORECASE)
        if not (uid_fragment and poa_fragment):
            return {}

        def attributes(fragment: str) -> dict[str, str]:
            return {
                key.lower(): value
                for key, value in re.findall(r'([A-Za-z][A-Za-z0-9]*)="([^"]*)"', fragment)
            }

        uid = attributes(uid_fragment.group(0)).get("uid", "")
        poi = attributes(poi_fragment.group(0)) if poi_fragment else {}
        ldata = attributes(ldata_fragment.group(0)) if ldata_fragment else {}
        poa = attributes(poa_fragment.group(0))
        co_value = poa.get("co", "").strip()
        relation_match = re.match(r"\s*(S/O|D/O|W/O|C/O)\s*:\s*(.+)", co_value, re.IGNORECASE)
        address_parts = [
            poa.get("house"), poa.get("street"), poa.get("lm"), poa.get("loc"),
            poa.get("vtc"), poa.get("po"), poa.get("subdist"), poa.get("dist"),
            poa.get("state"), poa.get("country"), poa.get("pc"),
        ]
        address = ", ".join(dict.fromkeys(part.strip() for part in address_parts if part and part.strip()))
        return {
            "applicant_name": poi.get("name") or ldata.get("name") or None,
            "aadhaar_last4": _digits_only(uid)[-4:] if len(_digits_only(uid)) >= 4 else None,
            "dob": _parse_date(poi.get("dob")) if poi.get("dob") else None,
            "gender": {"M": "MALE", "F": "FEMALE", "T": "TRANSGENDER"}.get(poi.get("gender", "").upper()),
            "address": address or None,
            "pin_code": poa.get("pc") or None,
            "relationship_qualifier": relation_match.group(1).upper() if relation_match else None,
            "related_person_name": _clean_name_like_value(relation_match.group(2)) if relation_match else None,
            "_aadhaar_xml_demographic_fields": sorted(set(poi) | set(ldata) | set(poa)),
        }
    except (AttributeError, ValueError):
        return {}


def _extract_aadhaar_address(text: str) -> str | None:
    """Extract the holder address without UIDAI footer/header boilerplate."""
    match = re.search(
        r"\baddress\s*:\s*(.{8,360}?\b[1-8]\d{5}\b)",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _clean_aadhaar_address_value(match.group(1))
    return _clean_aadhaar_address_value(_lines_after_label(text, "address", max_lines=4))


def _clean_aadhaar_address_value(value: Any) -> str | None:
    """Remove issuing-authority text accidentally interleaved after Address:."""
    if value in (None, ""):
        return None
    cleaned = str(value)
    authority_patterns = (
        r"भारतीय\s+विशिष्ट\s+पहचान\s+प्राधिकरण",
        r"\bUnique\s+Identification\s+Authority\s+of\s+India\b",
        r"\b(?:Government|Govt\.?)\s+of\s+India\b",
    )
    for pattern in authority_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:^|\s)(?:address|पता)\s*:\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")
    return cleaned or None


def _extract_application_form(text: str) -> dict[str, Any]:
    """Extract identity fields commonly repeated in a loan application form."""
    is_coapplicant_kyc_table = "CO-APPLICANT KYC DETAILS" in text.upper()
    pan_match = None if is_coapplicant_kyc_table else re.search(
        r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper()
    )
    aadhaar_match = next(
        (
            match
            for match in re.finditer(r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)", text)
            if has_labeled_aadhaar_value(text, match.group(1))
        ),
        None,
    )
    # Do not attribute co-applicant or corporate-header phones to the primary.
    phone_match = None
    if "CO-APPLICANT DETAILS" not in text.upper():
        phone_match = re.search(
            r"MOBILE\s+NUMBER[^\n\r]*\n(?:[^A-Za-z0-9\n\r]*\n){0,3}\s*([6-9]\d{9})(?!\d)",
            text,
            re.IGNORECASE,
        )
    pin_match = re.search(r"(?:pin\s*code|pincode)\s*[:\-–]?\s*(\d{6})", text, re.IGNORECASE)
    labeled_names = [
        _clean_name_like_value(value)
        for value in re.findall(
            r"(?:applicant|co[\s-]*applicant|borrower|guarantor)\s*(?:name)?\s*[:\-–]\s*([^\n\r]{3,70})",
            text,
            re.IGNORECASE,
        )
    ]
    language_match = re.search(
        r"(?:second|alternate|vernacular)\s+language\s*[:\-–]?\s*([A-Za-z\u0600-\u06FF\u0900-\u0D7F ]{3,30})",
        text,
        re.IGNORECASE,
    )
    applicant_section = text[text.upper().find("APPLICANT DETAILS"):] if "APPLICANT DETAILS" in text.upper() else text
    name_match = re.search(
        r"(?:^|\n)\s*NAME\s*\n(?:[^A-Za-z0-9\n]*\n){0,3}\s*([A-Za-z][A-Za-z .'-]{2,70})\s*\n"
        r"\s*DATE\s+OF\s+BIRTH",
        applicant_section,
        re.IGNORECASE,
    )
    current_address = (
        _extract_application_address_block(
            text, "COMMUNICATION ADDRESS", ("PERMANENT ADDRESS", "OFFICE ADDRESS")
        )
        or _extract_residential_address_alias(
            text,
            "current address",
            "current resi. address",
            "current resi address",
            "current residential address",
        )
    )
    permanent_address = (
        _extract_application_address_block(
            text, "PERMANENT ADDRESS", ("OFFICE ADDRESS", "APPLICANT EMPLOYEMENT")
        )
        or _extract_residential_address_alias(
            text,
            "permanent address",
            "permanent resi. address",
            "permanent resi address",
            "permanent residential address",
        )
    )
    communication_address = (
        _extract_application_address_block(
            text, "COMMUNICATION ADDRESS", ("PERMANENT ADDRESS", "OFFICE ADDRESS")
        )
        or _extract_residential_address_alias(text, "communication address")
    )
    person_records = [
        *_extract_application_coapplicant_records(text),
        *_extract_application_kyc_records(text),
    ]
    coapplicant_address_record = _extract_coapplicant_address_record(
        text,
        current_address=current_address,
        permanent_address=permanent_address,
    )
    if coapplicant_address_record:
        address_name = str(coapplicant_address_record.get("applicant_name") or "").casefold()
        matching_record = next(
            (
                record for record in person_records
                if isinstance(record, dict)
                and str(record.get("applicant_name") or "").casefold() == address_name
            ),
            None,
        )
        if matching_record is None:
            person_records.append(coapplicant_address_record)
        else:
            for field_name, value in coapplicant_address_record.items():
                if value not in (None, "") and matching_record.get(field_name) in (None, ""):
                    matching_record[field_name] = value
        # These values belong to the named co-applicant row, not to the
        # container-level/primary applicant.
        current_address = None
        permanent_address = None
        communication_address = None
    return {
        "applicant_name": (name_match.group(1).strip() if name_match else _line_after_label(
            text, "applicant name", "borrower name", "name of applicant"
        )),
        "pan_number": pan_match.group(1) if pan_match else None,
        "aadhaar_number": plausible_aadhaar_digits(aadhaar_match.group(1)) if aadhaar_match else None,
        "date_of_birth": _extract_date_near(text.lower(), "date of birth", "dob"),
        "loan_amount": _normalize_amount(_numeric_line_after_label(text, "loan amount")),
        "phone_number": phone_match.group(1) if phone_match else None,
        "pin_code": pin_match.group(1) if pin_match else None,
        "current_address": current_address,
        "permanent_address": permanent_address,
        "communication_address": communication_address,
        "applicant_names": [name for name in labeled_names if name],
        "person_records": person_records,
        "second_language": language_match.group(1).strip() if language_match else None,
    }


_APPLICATION_LAYOUT_ADDRESS_LABELS = {
    "current_address": (
        "current res address",
        "current resi address",
        "current residential address",
    ),
    "permanent_address": (
        "permanent res address",
        "permanent resi address",
        "permanent residential address",
    ),
    "communication_address": ("communication address",),
}

_LAYOUT_ADDRESS_REJECT_PREFIXES = (
    "aadhaar no",
    "business constitution",
    "city",
    "driving license",
    "driving licence",
    "email",
    "e mail",
    "mobile",
    "name",
    "owned rented",
    "professionally qualified",
    "telephone",
    "whatsapp",
    "years at",
    "years in",
)


def _extract_application_layout_addresses(
    structured_content: dict[str, Any] | None,
) -> dict[str, str]:
    """Extract application-form address rows from OCR bounding boxes.

    Google Vision's flat text can interleave two form columns.  Region geometry
    keeps values on the same visual row as their address label and prevents a
    distant PAN, education, or contact field from entering the address.
    """
    if not isinstance(structured_content, dict):
        return {}
    raw_regions = structured_content.get("layout_regions")
    if not isinstance(raw_regions, list):
        return {}

    regions: list[dict[str, Any]] = []
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            continue
        text = re.sub(r"\s+", " ", str(raw_region.get("text") or "")).strip()
        geometry = _layout_region_geometry(raw_region)
        if not text or geometry is None:
            continue
        try:
            confidence = float(raw_region.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        x0, y0, x1, y1 = geometry
        regions.append({
            "text": text,
            "normalized": _normalized_layout_text(text),
            "confidence": confidence,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
        })

    extracted: dict[str, str] = {}
    for field_name, labels in _APPLICATION_LAYOUT_ADDRESS_LABELS.items():
        anchors = [
            region
            for region in regions
            if any(label in region["normalized"] for label in labels)
        ]
        for anchor in anchors:
            value = _layout_address_value(regions, anchor)
            if value:
                extracted[field_name] = value
                break
    return extracted


def _layout_region_geometry(region: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bounding_box = region.get("bounding_box") or region.get("boundingBox") or {}
    vertices = bounding_box.get("vertices") if isinstance(bounding_box, dict) else None
    if not isinstance(vertices, list) or not vertices:
        return None
    try:
        xs = [float(vertex.get("x") or 0.0) for vertex in vertices if isinstance(vertex, dict)]
        ys = [float(vertex.get("y") or 0.0) for vertex in vertices if isinstance(vertex, dict)]
    except (TypeError, ValueError):
        return None
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _normalized_layout_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _layout_address_value(regions: list[dict[str, Any]], anchor: dict[str, Any]) -> str | None:
    label_right = float(anchor["x1"])
    label_top = float(anchor["y0"])
    label_bottom = float(anchor["y1"])

    primary: list[dict[str, Any]] = []
    continuation: list[dict[str, Any]] = []
    pin_regions: list[dict[str, Any]] = []
    for region in regions:
        if region is anchor or float(region["x0"]) <= label_right + 4:
            continue
        if not _is_layout_address_piece(region["text"], region["normalized"]):
            continue
        y0 = float(region["y0"])
        y1 = float(region["y1"])
        if y0 <= label_bottom + 4 and y1 >= label_top - 8:
            primary.append(region)
            continue
        if label_bottom < y0 <= label_bottom + 32:
            continuation.append(region)
            continue
        if label_top - 4 <= y0 <= label_bottom + 55 and re.fullmatch(
            r"(?:pin\s*)?[1-8]\d{5}(?:\s+tele)?",
            region["normalized"],
        ):
            pin_regions.append(region)

    continuation.sort(key=lambda region: (float(region["y0"]), float(region["x0"])))
    pin_regions.sort(key=lambda region: (float(region["y0"]), float(region["x0"])))

    selected: list[dict[str, Any]] = [*primary, *continuation]
    if not any(re.search(r"\b[1-8]\d{5}\b", str(region["text"])) for region in selected):
        selected.extend(pin_regions[:1])
    if not selected:
        return None

    pieces: list[str] = []
    for region in selected:
        piece = re.sub(r"^PIN\s*", "", str(region["text"]), flags=re.IGNORECASE)
        piece = re.sub(r"\s+Tele(?:phone)?\b.*$", "", piece, flags=re.IGNORECASE)
        piece = piece.strip(" ,.;:-")
        if piece and piece not in pieces:
            pieces.append(piece)
    value = " ".join(pieces)
    if not _looks_like_postal_address(value) or _address_value_is_contaminated(value):
        return None

    confidences = [float(region["confidence"]) for region in selected if region["confidence"]]
    if confidences and sum(confidences) / len(confidences) < 0.60:
        return None
    core_confidences = [
        float(region["confidence"])
        for region in selected
        if region["confidence"]
        and not re.fullmatch(r"(?:pin\s*)?[1-8]\d{5}(?:\s+tele)?", region["normalized"])
    ]
    if core_confidences and min(core_confidences) < 0.60:
        return None
    return value


def _is_layout_address_piece(text: str, normalized: str) -> bool:
    if not normalized or any(normalized.startswith(prefix) for prefix in _LAYOUT_ADDRESS_REJECT_PREFIXES):
        return False
    if any(re.search(pattern, normalized) for pattern in _ADDRESS_FORM_NOISE_PATTERNS):
        return False
    if normalized in {
        "address", "current", "permanent", "office", "others", "pin",
        "residence", "yes", "no",
    }:
        return False
    if len(text) > 120 or not re.search(r"[A-Za-z0-9]", text):
        return False
    return True


def _extract_application_address_block(
    text: str,
    heading: str,
    stop_headings: tuple[str, ...],
) -> str | None:
    """Extract address-table values split across bilingual application rows."""
    upper = str(text or "").upper()
    start = upper.find(heading.upper())
    if start < 0:
        return None
    section_boundaries = (
        *stop_headings,
        "GUARANTOR DETAILS",
        "GUARANTOR ADDRESS",
        "GUARANTOR EMPLOYEMENT/BUSINESS DETAILS",
        "GUARANTOR EMPLOYMENT/BUSINESS DETAILS",
        "GUARANTOR EMPLOYMENT DETAILS",
        "GUARANTOR BUSINESS DETAILS",
        "CO-APPLICANT DETAILS",
        "CO-APPLICANT KYC DETAILS",
        "APPLICANT DETAILS",
    )
    ends = [
        upper.find(stop.upper(), start + len(heading))
        for stop in section_boundaries
    ]
    end = min((value for value in ends if value >= 0), default=len(text))
    lines = [line.strip() for line in text[start:end].splitlines() if line.strip()]
    label_names = {
        "address", "type", "address type", "sub type", "address sub type",
        "years at current address", "landmark", "tehsil", "district",
        "pincode", "pin code", "state", "country",
    }

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z]+", " ", value.casefold()).strip()

    def value_after(
        label: str,
        *,
        allow_status: bool = False,
        prefer_address: bool = False,
    ) -> str | None:
        for index, line in enumerate(lines):
            if normalized(line) != label:
                continue
            fallback: str | None = None
            candidates = lines[index + 1 : index + 10]
            for candidate_index, candidate in enumerate(candidates):
                key = normalized(candidate)
                if key in label_names:
                    break
                if not re.search(r"[A-Za-z0-9]", candidate):
                    continue
                if not allow_status and key in {"current", "permanent", "office"}:
                    continue
                cleaned = candidate.strip(" ,.;")
                if not prefer_address:
                    return cleaned
                if _looks_like_postal_address(cleaned):
                    pieces = [cleaned]
                    for continuation in candidates[candidate_index + 1 : candidate_index + 4]:
                        continuation_key = normalized(continuation)
                        if continuation_key in label_names:
                            break
                        continuation_text = continuation.strip(" ,.;")
                        if _looks_like_postal_address(continuation_text) or re.search(
                            r"\b[1-8]\d{5}\b", continuation_text
                        ):
                            pieces.append(continuation_text)
                    return " ".join(dict.fromkeys(pieces))
                # OCR often stacks NAME and ADDRESS labels first, followed by
                # the person's name and then the actual postal address.  Keep a
                # plausible non-name fallback, but never return the name itself
                # as the address.
                if not canonicalize_person_name(cleaned).valid and fallback is None:
                    fallback = cleaned
            if fallback:
                return fallback
        return None

    base = value_after("address", prefer_address=True)
    pin = value_after("pincode") or value_after("pin code")
    parts = [
        base,
        value_after("landmark"),
        value_after("tehsil"),
        value_after("district"),
        value_after("state"),
        value_after("country"),
        pin,
    ]
    result = ", ".join(dict.fromkeys(value for value in parts if value))
    return result or None


def _looks_like_postal_address(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return False
    if re.search(r"\b[1-8]\d{5}\b", text):
        return True
    tokens = re.findall(r"[A-Za-z0-9]+", text)
    return bool(
        len(tokens) >= 4
        and (
            re.search(r"\d", text)
            or re.search(
                r"\b(?:road|street|nagar|vas|village|taluka|district|ahmedabad|"
                r"flat|house|plot|sector|colony|society)\b",
                text,
                re.IGNORECASE,
            )
        )
    )


def _extract_residential_address_alias(text: str, *labels: str) -> str | None:
    """Extract inline/stacked residential-address labels used in Indian forms."""
    for label in labels:
        inline = _raw_value_after_label(text, label)
        if inline and _looks_like_postal_address(inline):
            return inline
        layout_block = _extract_jumbled_residential_block(text, label)
        if layout_block:
            return layout_block
        stacked = _lines_after_label_until_stop(
            text,
            label,
            stop_labels={
                "current address", "current resi. address", "permanent address",
                "permanent resi. address", "office address", "mobile number",
                "date of birth", "pan", "aadhaar",
            },
            max_lines=4,
        )
        if stacked and _looks_like_postal_address(stacked):
            return stacked
    return None


def _extract_jumbled_residential_block(text: str, label: str) -> str | None:
    """Recover form addresses whose visual columns OCR into interleaved lines."""
    lines = [re.sub(r"\s+", " ", line).strip(" ,.;") for line in str(text or "").splitlines()]
    normalized_label = re.sub(r"[^a-z]+", " ", label.casefold()).strip()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.sub(r"[^a-z]+", " ", line.casefold()).strip() == normalized_label
        ),
        None,
    )
    if start is None:
        return None

    stop_prefixes = (
        "permanent resi", "current resi", "permanent residential",
        "current residential", "occupation details", "preferred mailing",
    )
    ignored_exact = {
        "city", "telephone", "email id", "e mail id", "residence",
        "post graduate", "graduate", "non graduate", "pin", "fax",
        "whatsapp available", "yes", "no",
    }
    ignored_prefixes = (
        "mobile ", "owned rented", "years at ", "years in ",
        "preferred contact", "current office address", "additional office address",
    )
    pieces: list[str] = []
    for index, line in enumerate(lines[start + 1 : start + 23], start=start + 1):
        if not line:
            continue
        normalized = re.sub(r"[^a-z]+", " ", line.casefold()).strip()
        if index > start + 1 and any(normalized.startswith(prefix) for prefix in stop_prefixes):
            break
        pin_match = re.search(r"\bPIN\s*([0-9A-Z]{6})\b", line, re.IGNORECASE)
        if pin_match:
            pin = _ocr_normalized_pin(pin_match.group(1))
            if pin:
                pieces.append(pin)
            continue
        if normalized in ignored_exact or any(normalized.startswith(prefix) for prefix in ignored_prefixes):
            continue
        cleaned = re.sub(r"^if\s+different\s+from\s+above\)?\s*", "", line, flags=re.IGNORECASE)
        if cleaned and re.search(r"[A-Za-z0-9]", cleaned):
            pieces.append(cleaned)

    # Column-order OCR may print the labelled PIN just after an intervening
    # office-address heading.  Use it only as part of this address value.
    nearby = " ".join(lines[start + 1 : start + 18])
    for match in re.finditer(r"\bPIN\s*([0-9A-Z]{6})\b", nearby, re.IGNORECASE):
        pin = _ocr_normalized_pin(match.group(1))
        if pin and pin not in pieces:
            pieces.append(pin)
    result = " ".join(dict.fromkeys(pieces)).strip()
    return result if _looks_like_postal_address(result) else None


def _ocr_normalized_pin(value: str) -> str | None:
    translated = str(value or "").upper().translate(str.maketrans({
        "O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
        "Z": "2", "M": "4", "S": "5", "G": "6", "B": "8",
    }))
    return translated if re.fullmatch(r"[1-8]\d{5}", translated) else None


def _extract_coapplicant_address_record(
    text: str,
    *,
    current_address: str | None,
    permanent_address: str | None,
) -> dict[str, Any] | None:
    section_start = re.search(r"\bCO[\s-]*APPLICANT\s+ADDRESS\b", text, re.IGNORECASE)
    if not section_start:
        return None
    # Search only inside the co-applicant address section. Whole-document
    # extraction previously walked back to the lender's corporate header and
    # manufactured a company-as-person record.
    scoped_text = text[section_start.start():]
    section_end = re.search(
        r"(?:^|\n)\s*(?:GUARANTOR\s+(?:DETAILS|ADDRESS)|"
        r"APPLICANT\s+DETAILS|DECLARATION|BANK\s+ACCOUNT\s+DETAILS)\b",
        scoped_text[len(section_start.group(0)):],
        re.IGNORECASE,
    )
    if section_end:
        scoped_text = scoped_text[: len(section_start.group(0)) + section_end.start()]
    excluded = {
        "co applicant address", "communication address", "permanent address",
        "office address", "name", "address", "current",
    }
    person_name = None
    for line in scoped_text.splitlines():
        candidate_text = re.sub(r"\s+", " ", line).strip(" ,.;")
        normalized = re.sub(r"[^a-z]+", " ", candidate_text.casefold()).strip()
        if not candidate_text or normalized in excluded:
            continue
        candidate = canonicalize_person_name(candidate_text)
        if candidate.valid and len(re.findall(r"[A-Za-z]+", str(candidate.value or ""))) >= 2:
            person_name = candidate.value
            break
    if not person_name:
        return None
    return {
        "applicant_name": person_name,
        "current_address": current_address,
        "communication_address": current_address,
        "permanent_address": permanent_address,
    }


def _extract_application_kyc_records(text: str) -> list[dict[str, Any]]:
    """Keep each application-form KYC row attached to its named person."""
    if "KYC DETAILS" not in text.upper():
        return []
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*([X*]{8}\d{4})\s*\n"
        r"\s*([A-Z]{5}\d{4}[A-Z])\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        records.append({
            "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
            "aadhaar_last4": match.group(2)[-4:],
            "pan_number": match.group(3).upper(),
        })
    return records


def _extract_utility_bill(text: str) -> dict[str, Any]:
    """Extract address-proof fields from electricity/water/gas/phone bills."""
    consumer_match = re.search(
        r"(?:consumer|customer|account)\s*(?:name|holder)?\s*[:\-–]?\s*([^\n\r]{3,80})",
        text,
        re.IGNORECASE,
    )
    address_stop_labels = {
        "bill date",
        "billing date",
        "due date",
        "amount",
        "total amount",
        "consumer number",
        "consumer no",
        "account number",
        "meter number",
    }
    address = (
        _lines_after_label_until_stop(text, "service address", stop_labels=address_stop_labels)
        or _lines_after_label_until_stop(text, "billing address", stop_labels=address_stop_labels)
        or _lines_after_label_until_stop(text, "supply address", stop_labels=address_stop_labels)
        or _utility_service_block_after_bill_heading(text)
        or _lines_after_label_until_stop(text, "address", stop_labels=address_stop_labels)
    )
    if not address:
        # Some OCR engines flatten the entire bill into one line. Preserve the
        # relationship/address segment printed after the consumer name, while
        # stopping before the YYYYMM billing month so it cannot become a PIN.
        inline_address = re.search(
            r"\b(?:S\s*/\s*O|D\s*/\s*O|W\s*/\s*O|C\s*/\s*O)\s*[:\-]?\s*"
            r"([A-Z][A-Z ]{5,100}?)(?=\s+20\d{4}\b)",
            text,
            re.IGNORECASE,
        )
        if inline_address:
            relation_start = re.search(
                r"\b(?:S\s*/\s*O|D\s*/\s*O|W\s*/\s*O|C\s*/\s*O)\b",
                inline_address.group(0),
                re.IGNORECASE,
            )
            address = inline_address.group(0)[relation_start.start():].strip() if relation_start else None
    pin_match = re.search(r"(?<!\d)([1-8]\d{5})(?!\d)", address or "")
    if pin_match is None:
        pin_match = re.search(
            r"(?:pin\s*code|pincode|postal\s*code)\s*[:\-\u2013]?\s*([1-8]\d{5})",
            text,
            re.IGNORECASE,
        )
    holder_name = _clean_name_like_value(consumer_match.group(1)) if consumer_match else None
    if not holder_name:
        relation_name = re.search(
            r"\b([A-Z][A-Z ]{2,50})\s+(?:S/O|D/O|W/O|C/O)\b",
            text,
        )
        holder_name = _clean_name_like_value(relation_name.group(1)) if relation_name else None
    return {
        "applicant_name": holder_name,
        "address": address,
        "pin_code": pin_match.group(1) if pin_match else None,
        "bill_date": (
            _parse_date(date_match.group(0))
            if (date_match := re.search(r"\b\d{2}[-/]\d{2}[-/]\d{4}\b", text))
            else None
        ),
    }


def _utility_service_block_after_bill_heading(text: str) -> str | None:
    """Read the consumer/service block and avoid the utility's own header.

    Some electricity bills print ``ADDRESS`` only in the provider letterhead,
    while the actual premises follows ``E-ELECTRICITY BILL`` without a label.
    """
    lines = [line.strip() for line in str(text or "").splitlines()]
    start = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if re.search(r"\b(?:e[- ]?electricity|electricity|water|gas)\s+bill\b", line, re.I)
        ),
        None,
    )
    if start is None:
        return None
    collected: list[str] = []
    for line in lines[start : start + 12]:
        if not line:
            continue
        if re.search(
            r"\b(?:sub[- ]?division\s+office|bill\s+date|due\s+date|consumer\s+(?:no|number)|meter\s+(?:no|number))\b",
            line,
            re.I,
        ):
            break
        if re.search(r"\b(?:website|helpline|gst\s*(?:no|number))\b|www\.|\S+@\S+", line, re.I):
            continue
        collected.append(line)
    if (
        len(collected) >= 2
        and re.search(r"\d", collected[1])
        and (
            not re.search(r"\d", collected[0])
            or re.search(r"\b(?:exe|engineer|engr)\b", collected[0], re.I)
        )
    ):
        # The first row is often the consumer name; verification treats it as
        # separate from the premises address.
        collected = collected[1:]
    value = re.sub(r"\s+", " ", " ".join(collected)).strip(" ,.;")
    return value if len(re.findall(r"[A-Za-z\u0900-\u097f]", value)) >= 6 else None


def _extract_voter_id(text: str) -> dict[str, Any]:
    """Extract fields from a Voter ID / EPIC card."""
    t = text.lower()

    # Voter ID number: 3 uppercase letters + 7 digits  e.g. ABC1234567
    vid_match = re.search(r'\b([A-Z]{3}[0-9]{7})\b', text)

    # DOB
    dob_raw = _extract_date_near(t, "dob", "date of birth")

    return {
        "applicant_name": _voter_cardholder_name(text),
        "voter_id_number": vid_match.group(1) if vid_match else None,
        "address": _lines_after_label(text, "address", max_lines=3),
        "dob": dob_raw,
    }


def _voter_cardholder_name(text: str) -> str | None:
    """Prefer the Latin cardholder value in bilingual EPIC label/value blocks."""
    lines = text.splitlines()
    label_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(r"elector'?s\s+name|निर्वाचक\s+का\s+नाम", line, re.IGNORECASE)
        ),
        None,
    )
    if label_index is None:
        return _line_after_label(text, "name")

    valid_candidates: list[str] = []
    for line in lines[label_index + 1 : label_index + 14]:
        candidate = _clean_name_like_value(line)
        if not candidate:
            continue
        valid_candidates.append(candidate)
        if re.search(r"[A-Za-z]", candidate):
            return candidate
    return valid_candidates[0] if valid_candidates else None


def _extract_driving_license(text: str) -> dict[str, Any]:
    """Extract fields from a Driving License.

    Also flags expired licences via 'is_expired' key.
    """
    t = text.lower()

    # DL number: 2 uppercase letters + 2 digits + optional space + 11 digits
    # (\b does not work between \d and \D reliably, so we anchor with lookahead/lookbehind)
    dl_match = re.search(r'(?<![A-Z0-9])([A-Z]{2}\d{2}\s?\d{11})(?![A-Z0-9])', text)

    # Read dates only from their own labels.  A proximity window is unsafe on
    # DLs because Date of Issue, DOB and Valid Till are commonly printed beside
    # each other and flattened OCR loses the original columns.
    validity_date = _extract_date_after_label(
        text, "valid till", "valid upto", "valid up to", "validity date", "validity"
    )
    is_expired = _is_past_date(validity_date)

    dob_raw = _extract_date_after_label(text, "date of birth", "dob", "d.o.b")
    date_of_issue = _extract_date_after_label(
        text, "date of issue", "issue date", "issued on", "date issued"
    )

    return {
        "applicant_name": _line_after_label(text, "name"),
        "dl_number": dl_match.group(1).replace(" ", "") if dl_match else None,
        "dob": dob_raw,
        "date_of_issue": date_of_issue,
        "validity_date": validity_date,
        "is_expired": is_expired,
        "address": _lines_after_label(text, "address", max_lines=3),
    }


def _extract_cersai_report(text: str) -> dict[str, Any]:
    """Extract CERSAI metadata and only the entered debtor identity.

    The CERSAI corporate PAN and identities listed in search results are not the
    report subject.  Keeping extraction inside ``Search Criteria Entered`` is
    what makes applicant/co-applicant ownership deterministic.
    """
    t = text.lower()
    criteria_text = search_criteria_text(text)
    cersai_search_type = search_type(text)
    debtor_based = cersai_search_type == DEBTOR_BASED
    debtor_pan = _value_after_label(criteria_text, "pan") if debtor_based else None
    if debtor_pan and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", debtor_pan.upper()):
        debtor_pan = None
    transaction_id = _value_after_label(
        text, "transaction id", "transaction id / qrf", "transaction id / qrf no"
    )
    search_reference = _value_after_label(text, "search reference number")
    debtor_name = _value_after_label(criteria_text, "name of the debtor") if debtor_based else None
    debtor_dob = _extract_date_after_label(criteria_text, "date of birth") if debtor_based else None
    search_result = None
    if "no match found" in t:
        search_result = "No Match Found"
    elif "match found" in t:
        search_result = "Match Found"

    return {
        "cersai_search_type": cersai_search_type,
        "debtor_name": debtor_name,
        "debtor_pan_number": debtor_pan.upper() if debtor_pan else None,
        "debtor_date_of_birth": debtor_dob,
        # Backward-compatible person-field aliases. They always refer to the
        # entered debtor, never to a party found in the result section.
        "applicant_name": debtor_name,
        "pan_number": debtor_pan.upper() if debtor_pan else None,
        "date_of_birth": debtor_dob,
        "search_reference_number": search_reference,
        "transaction_id": transaction_id,
        "search_result": search_result,
        "report_date": _extract_date_near(
            t, "report download date", "report downloaded on", "downloaded on", "report date"
        ),
    }


def _extract_pdc(text: str) -> dict[str, Any]:
    """Extract individual cheque leaves from a scanned PDC sheet.

    MICR lines normally contain the six-digit cheque number followed by nine
    routing digits. OCR may repeat the same leaf, so return unique numbers.
    """
    cheque_numbers = list(dict.fromkeys(
        match.group(1)
        for match in re.finditer(
            r"(?<!\d)(\d{6})[\s'\"*]*(\d{9})(?!\d)", text or ""
        )
    ))
    return {
        "cheque_numbers": cheque_numbers,
        "cheque_count": len(cheque_numbers) or None,
    }


def _extract_crif_report(text: str) -> dict[str, Any]:
    """Extract fields from a CRIF / CIBIL credit report."""
    t = text.lower()

    # Credit score: 3-digit number near the word "score"
    score: str | None = None
    score_match = re.search(
        r'(?:credit\s+)?score\s*[:\-–]?\s*\b(0|[3-9]\d{2})\b',
        t,
    )
    if score_match:
        score = score_match.group(1)
    else:
        table_score = re.search(r"\b300\s*[-–]\s*900\s+(0|[3-9]\d{2})\b", t)
        if table_score:
            score = table_score.group(1)
    if score is None:
        # Broader fallback: any 3-digit number 300-900 near "score" in a 60-char window
        idx = t.find("score")
        if idx != -1:
            window = t[max(0, idx - 10): idx + 50]
            fb = re.search(r'\b(0|[3-9]\d{2})\b', window)
            if fb:
                score = fb.group(1)
    if score is None and has_explicit_no_score_evidence(text):
        score = "0"

    # Report date
    report_date = _extract_date_near(t, "report generated", "as on", "date of report")

    # Applicant name: first substantive non-header line
    applicant_name: str | None = _extract_bureau_applicant_name(text)

    account_count = re.search(r"(?:total|number\s+of)\s+accounts?\s*[:\-–]?\s*(\d+)", t)
    overdue_count = re.search(r"(?:overdue|past\s+due)\s+accounts?\s*[:\-–]?\s*(\d+)", t)
    report_id = re.search(r"(?:report|reference|document)\s*(?:id|no\.?|number)\s*[:\-–]?\s*([A-Z0-9\-/]+)", text, re.IGNORECASE)
    return {
        "applicant_name": applicant_name,
        "credit_score": score,
        "cibil_score" if "cibil" in t else "crif_score": score,
        "report_date": report_date,
        "bureau_account_count": account_count.group(1) if account_count else None,
        "overdue_account_count": overdue_count.group(1) if overdue_count else None,
        "dpd_status": _line_after_label(text, "dpd status", "days past due"),
        "credit_report_id": report_id.group(1) if report_id else None,
    }


def _extract_bureau_applicant_name(text: str) -> str | None:
    """Extract only the report subject, never variation/address-section rows."""
    header_window = text[:2500]
    for pattern in (
        r"(?:^|\n)\s*Consumer\s+Name\s*:?\s*(?:\n\s*)?"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)(?=\s*(?:\n|Date\b|DOB\b))",
        r"(?:^|\n)\s*Applicant\s+Name\s*[:\-–]?\s*(?:\n\s*)?"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)(?=\s*(?:\n|DOB\b|Gender\b))",
        r"(?:^|\n)\s*Name\s*:\s*([A-Za-z][A-Za-z .'-]{2,60}?)"
        r"(?=\s+(?:DOB|Gender|Father|Phone|ID|Current Address|$))",
        r"(?:^|\n)\s*For\s+([A-Za-z][A-Za-z .'-]{2,60}?)\s*(?=\n|$)",
    ):
        match = re.search(pattern, header_window, re.IGNORECASE | re.MULTILINE)
        if match:
            return _clean_name_like_value(match.group(1))
    return None


def _extract_bank_statement(text: str) -> dict[str, Any]:
    """Extract fields from a bank statement."""
    if is_amortization_schedule(text):
        return {
            "_validation_blocked_reason": "amortization_schedule_not_bank_statement",
        }
    t = text.lower()
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?)\s*[:\-–]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    branch_match = re.search(r"\bbranch[ \t]*[:\-–][ \t]*([^\n\r]{2,70})", text, re.IGNORECASE)
    bank_match = re.search(
        r"(?:^|\n)\s*(?:bank(?:\s+name)?|name\s+of\s+bank)\s*(?:\n\s*)?[:\-–]\s*([^\n\r]{2,70})",
        text,
        re.IGNORECASE,
    )
    type_match = re.search(r"\baccount\s+type\s*[:\-–]?\s*([^\n\r]{2,30})", text, re.IGNORECASE)
    period_start, period_end = _extract_statement_period(text)
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper())
    is_internal_approval = bool(re.search(
        r"request\s+for\s+approval|designation\s*:\s*|department\s*:\s*",
        text,
        re.IGNORECASE,
    ))
    phone_match = None if is_internal_approval else re.search(
        r"(?:registered\s+mobile|customer\s+mobile|mobile\s+(?:number|no\.?))"
        r"\s*[:\-–]?\s*([6-9]\d{9})(?!\d)",
        text,
        re.IGNORECASE,
    )
    # CAMS profile pages often present field labels in one column and their
    # values in another.  Prefer the value immediately following CKYC and a
    # date of birth, including title-case names (for example ``Kala Singh``).
    # The former all-caps-only pattern missed those pages, causing the generic
    # ``Name`` fallback to mistake a later profile label such as "Holding
    # Nature" for the account holder.
    profile_name = re.search(
        r"\bCKYC\s*\n\s*([A-Za-z][A-Za-z .]{2,70}(?:\n\s*[A-Za-z][A-Za-z .]{2,70})?)"
        r"\s*\n\s*\d{4}-\d{2}-\d{2}",
        text,
    )
    statement_title_name = _statement_holder_after_title(text)
    fallback_name = _line_after_label(text, "account holder", "customer name", "name")
    if fallback_name and fallback_name.casefold() in {
        "holding nature", "dob", "mobile", "landline", "email", "pan",
        "address", "nominee", "ckyc", "profile",
    }:
        fallback_name = None
    return {
        "account_holder_name": (
            _clean_name_like_value(re.sub(r"\s+", " ", profile_name.group(1))).title()
            if profile_name else statement_title_name or fallback_name
        ),
        "account_number": _digits_only(account_match.group(1)) if account_match else None,
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "bank_name": bank_match.group(1).strip() if bank_match else None,
        "branch": branch_match.group(1).strip() if branch_match else None,
        "account_type": type_match.group(1).strip() if type_match else None,
        "pan_number": pan_match.group(1) if pan_match else None,
        "phone_number": phone_match.group(1) if phone_match else None,
        "nach_status": (
            "done" if re.search(r"\be\s*-?\s*nach\s+(?:status\s*[-–:]*)?done\b", text, re.IGNORECASE)
            else None
        ),
        "statement_period_start": period_start,
        "statement_period_end": period_end,
    }


def _statement_holder_after_title(text: str) -> str | None:
    """Recover holder names from lender statement cover-page column order.

    OCR may emit the visual labels and lender logo before the statement title,
    so a generic ``Name`` lookup lands on a logo token. The subject printed
    immediately after an explicit statement-of-account title is stronger.
    """
    lines = [re.sub(r"\s+", " ", line).strip(" ,.;") for line in str(text or "").splitlines()]
    title_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(
                r"\b(?:customer(?:'s)?\s+)?statement\s+of\s+account\b|"
                r"\baccount\s+statement\b|\bbank\s+statement\b",
                line,
                re.IGNORECASE,
            )
        ),
        None,
    )
    if title_index is None:
        return None
    for line in lines[title_index + 1 : title_index + 10]:
        candidate = canonicalize_person_name(line)
        if not candidate.valid:
            continue
        latin_tokens = re.findall(r"[A-Za-z]+", str(candidate.value or ""))
        if len(latin_tokens) >= 2:
            return candidate.value
    return None


def _extract_passbook(text: str) -> dict[str, Any]:
    """Extract fields from a bank passbook page."""
    t = text.lower()
    stacked_name_branch = re.search(
        r"(?:name|नाम)\s*:\s*\n\s*([0-9Xx* ]{6,24})\s*\n"
        r"[^\n]*(?:branch|शाखा)\s*:\s*([A-Z][A-Z .'-]{3,70})\s*\n"
        r"\s*([A-Z][A-Z .'-]{2,70})\s*\n\s*IFSC",
        text,
        re.IGNORECASE,
    )
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?|खाता\s*संख्या)\s*[:\-\u2013]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    branch_match = re.search(r"\bbranch[ \t]*[:\-–]?[ \t]*([^\n\r]{2,70})", text, re.IGNORECASE)
    bank_match = re.search(r"\b(?:bank\s+name|name\s+of\s+bank)\s*[:\-–]?\s*([^\n\r]{2,70})", text, re.IGNORECASE)
    type_match = re.search(r"\baccount\s+type\s*[:\-–]?\s*([^\n\r]{2,30})", text, re.IGNORECASE)
    passbook_name = re.search(
        r"\b(?:SHRI|SMT|SRI|MR|MRS)\.?[^A-Za-z\n]{0,6}([A-Z][A-Z ]{2,60})\b",
        text,
        re.IGNORECASE,
    )
    return {
        "account_holder_name": (
            _clean_name_like_value(passbook_name.group(1)) if passbook_name else None
        ) or (
            _clean_name_like_value(stacked_name_branch.group(2))
            if stacked_name_branch else None
        ) or _line_after_label(text, "account holder", "customer name", "name", "नाम"),
        "account_number": (
            _digits_only(stacked_name_branch.group(1))
            if stacked_name_branch else (_digits_only(account_match.group(1)) if account_match else None)
        ),
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "bank_name": bank_match.group(1).strip() if bank_match else None,
        "branch": (
            stacked_name_branch.group(3).strip()
            if stacked_name_branch else (branch_match.group(1).strip() if branch_match else None)
        ),
        "account_type": type_match.group(1).strip() if type_match else None,
    }


def _extract_cheque(text: str) -> dict[str, Any]:
    """Extract fields from a cheque or cancelled cheque page."""
    cheque_number = _extract_cheque_number(text)
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|"
        r"a\s*[/\\lI|]?\s*c\s*(?:number|no\.)?|"
        r"a[lI]?[ct]\s*(?:number|no\.?))"
        r"\s*[:\-\u2013]?\s*(?:\r?\n\s*)?([0-9Xx*][0-9Xx* \t]{5,23})",
        text,
        re.IGNORECASE,
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    amount = _extract_amount(text.lower(), "rupees", "amount")
    return {
        "account_holder_name": (
            _extract_cheque_signature_holder(text)
            or _line_after_label(text, "account holder", "name")
        ),
        "account_number": _digits_only(account_match.group(1)) if account_match else None,
        "cheque_number": cheque_number,
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "cheque_date": _extract_date_near(text.lower(), "date"),
        "amount": amount,
        "is_cancelled": "cancelled" in text.lower() or "canceled" in text.lower(),
    }


def _extract_cheque_signature_holder(text: str) -> str | None:
    """Extract the printed holder name associated with the signature box."""
    for match in re.finditer(
        r"\b(?:mr|mrs|ms|miss|shri|smt|sri)\.?\s+"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)(?=\s*(?:\r?\n|$))",
        str(text or ""),
        re.IGNORECASE,
    ):
        signature_window = str(text or "")[match.end() : match.end() + 240]
        if not re.search(
            r"\b(?:please\s+sign\s+abov[es]|authori[sz]ed\s+signatory)\b",
            signature_window,
            re.IGNORECASE,
        ):
            continue
        candidate = _clean_name_like_value(match.group(1))
        if canonicalize_person_name(candidate).valid:
            return candidate
    return None


def _extract_cheque_number(text: str) -> str | None:
    labeled = re.search(r"(?:cheque\s*(?:number|no\.?)|chq\s*(?:number|no\.?))\s*[:\-\u2013]?\s*(\d{6})", text, re.IGNORECASE)
    if labeled:
        return labeled.group(1)
    candidates = re.findall(r"\b\d{6}\b", text)
    return candidates[0] if candidates else None


def _extract_statement_period(text: str) -> tuple[str | None, str | None]:
    date_pattern = (
        r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"
        r"|\d{1,2}\s+\w+\s+\d{4}"
    )
    match = re.search(
        rf"(?:period|statement\s+period|from)\s*[:\-–]?\s*({date_pattern})\s*(?:to|\-|\u2013|\u2014)\s*({date_pattern})",
        text,
        re.IGNORECASE,
    )
    if not match:
        start = re.search(rf"statement\s+from\s*[:\-–]?\s*({date_pattern})", text, re.IGNORECASE)
        end = re.search(rf"statement\s+to\s*[:\-–]?\s*({date_pattern})", text, re.IGNORECASE)
        if start and end:
            return _parse_date(start.group(1)), _parse_date(end.group(1))
        return None, None
    return _parse_date(match.group(1)), _parse_date(match.group(2))


def _extract_salary_slip(text: str) -> dict[str, Any]:
    """Extract fields from a salary slip."""
    t = text.lower()
    return {
        "applicant_name": _line_after_label(text, "employee name", "name"),
        "net_salary": _extract_amount(t, "net salary", "net pay", "take home"),
        "salary_month": _extract_salary_month(text),
    }


def _extract_salary_month(text: str) -> str | None:
    match = re.search(
        r"(?:salary\s+month|pay\s+period|month)\s*[:\-–]?\s*([A-Za-z]+\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _extract_stamp_duty(text: str) -> dict[str, Any]:
    lower = text.lower()
    state_match = re.search(
        r"government\s+of\s+([A-Za-z][A-Za-z &.-]{2,40})",
        text,
        re.IGNORECASE,
    )
    duty_amount_match = re.search(
        r"stamp\s+duty\s+amount\s*(?:\(\s*rs\.?\s*\))?\s*[:\-–]?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    consideration_match = re.search(
        r"consideration\s+(?:price|amount)\s*(?:\(\s*rs\.?\s*\))?\s*[:\-–]?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    instrument_description = _value_after_label(
        text, "description of document", "description of instrument", "instrument description"
    )
    article_match = re.search(
        r"\bArticle\s+([0-9]+(?:\([A-Za-z0-9]+\))?)",
        instrument_description or text,
        re.IGNORECASE,
    )
    return {
        "stamp_date": _extract_date_near(
            lower, "stamp date", "date of stamp", "certificate issued date", "issue date"
        ),
        "stamp_certificate_number": _value_after_label(
            text, "certificate no", "certificate number", "e-stamp number"
        ),
        "stamp_jurisdiction_state": state_match.group(1).strip(" .") if state_match else None,
        "stamp_duty_amount": _normalize_amount(duty_amount_match.group(1)) if duty_amount_match else None,
        "stamp_consideration_amount": (
            _normalize_amount(consideration_match.group(1)) if consideration_match else None
        ),
        "stamp_instrument_description": instrument_description,
        "stamp_article": article_match.group(1) if article_match else None,
        "stamp_unique_document_reference": _value_after_label(
            text, "unique doc. reference", "unique document reference", "uin"
        ),
        "stamp_account_reference": _value_after_label(text, "account reference"),
        "stamp_purchased_by": _value_after_label(text, "purchased by"),
        "stamp_first_party": _value_after_label(text, "first party"),
        "stamp_second_party": _value_after_label(text, "second party"),
    }


def _extract_insurance_form(text: str) -> dict[str, Any]:
    """Extract insurance-form fields without collapsing IDs into loan IDs.

    A proposal form can carry three different namespaces: the insurer's
    application/proposal number, the lender's loan application number and the
    lender's loan account number.  Keeping them separate prevents a local
    proposal ID from being compared with the trusted loan application ID.
    """
    insurer_match = re.search(
        r"(?:^|\n)\s*((?:[A-Z][A-Za-z0-9&.'()-]*\s+){1,8}"
        r"Insurance\s+(?:Company|Co\.?|Limited|Ltd\.?))\b",
        text,
        re.IGNORECASE,
    )
    policy_tenure_match = re.search(
        r"(?:^|\n)\s*Policy\s+Tenure\s*[:\-–]?\s*"
        r"(\d{1,3})\s*(Years?|Months?)\b",
        text,
        re.IGNORECASE,
    )
    policy_tenure_months = None
    if policy_tenure_match:
        policy_tenure_months = int(policy_tenure_match.group(1))
        if policy_tenure_match.group(2).casefold().startswith("year"):
            policy_tenure_months *= 12

    return {
        "insurer_name": (
            re.sub(r"\s+", " ", insurer_match.group(1)).strip()
            if insurer_match else None
        ),
        "insurance_application_number": _inline_identifier_after_label(
            text, "insurance application number", "insurance application no",
            "application number", "application no",
        ),
        "insurance_proposal_number": _inline_identifier_after_label(
            text, "proposal number", "proposal no",
        ),
        "insurance_policy_number": _inline_identifier_after_label(
            text, "policy number", "policy no",
        ),
        "loan_application_number": _inline_identifier_after_label(
            text, "loan application number", "loan application no",
        ),
        "loan_account_number": _inline_identifier_after_label(
            text, "loan account number", "loan account no", "loan a/c no",
        ),
        "proposer_name": _inline_text_after_label(text, "proposer name"),
        "insured_person_name": _inline_text_after_label(
            text, "insured person name", "name of person to be insured",
        ),
        "nominee_name": _inline_text_after_label(text, "nominee name"),
        "policy_tenure_months": policy_tenure_months,
        "sum_insured": _extract_amount(text.casefold(), "sum insured"),
        "total_premium": _extract_amount(
            text.casefold(), "total premium", "premium amount"
        ),
    }


def _inline_identifier_after_label(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)[ \t]*{re.escape(label)}[ \t]*[:\-–#]?[ \t]*"
            r"([A-Z0-9][A-Z0-9./_-]{2,40})[ \t]*(?:\r?$)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
    return None


def _inline_text_after_label(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*[:\-–]\s*([^\n\r]{{2,80}})",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" ,.;")
    return None


def _extract_insurance_consent(text: str) -> dict[str, Any]:
    lower = text.lower()
    tenure_match = re.search(
        r"insurance\s+tenure\s*[:\-–]?\s*(\d+)\s*(months?|years?)?", lower
    )
    insurance_tenure: int | None = None
    if tenure_match:
        insurance_tenure = int(tenure_match.group(1))
        if str(tenure_match.group(2) or "").startswith("year"):
            insurance_tenure *= 12
    return {
        "insurance_tenure": insurance_tenure,
        "applicant_name": _line_after_label(text, "applicant name", "customer name", "name"),
    }


def _extract_clearance_report(text: str) -> dict[str, Any]:
    lower = text.lower()
    status_window = _clearance_status_window(text)
    status_lower = status_window.lower()
    rejected = next(
        (status for status in ("not cleared", "not clear", "negative", "rejected", "pending") if status in status_lower),
        None,
    )
    accepted = next(
        (
            status
            for status in (
                "technically cleared",
                "title clear",
                "cleared",
                "clear",
                "positive",
                "approved",
                "recommended",
                "satisfactory",
            )
            if status in status_lower
        ),
        None,
    )
    return {
        "clearance_status": rejected or accepted,
        "report_status": rejected or accepted,
        "report_date": _extract_date_near(lower, "report date", "date of report", "as on"),
    }


def _clearance_status_window(text: str) -> str:
    for label in ("clearance status", "technical status", "report status", "recommendation", "remarks"):
        value = _lines_after_label(text, label, max_lines=3)
        if value:
            return value
    return " ".join(str(text or "").splitlines()[:20])


def _extract_nach_form(text: str) -> dict[str, Any]:
    lower = text.lower()
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?)\s*[:\-–]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    if "not registered" in lower or "registration pending" in lower:
        registration_status = "not registered"
    elif (
        "registered" in lower
        or "registration successful" in lower
        or re.search(r"\bregister[_\s-]*success(?:ful)?\b", lower)
        or "active" in lower
    ):
        registration_status = "registered"
    else:
        registration_status = None
    status_screen_name = re.search(
        r"\b[6-9]\d{9}\s*\n\s*([A-Z][A-Z .'-]{5,70})\s*\n\s*CRN\s*:",
        text,
        re.IGNORECASE,
    )
    return {
        "registration_status": registration_status,
        "account_holder_name": (
            _clean_name_like_value(status_screen_name.group(1))
            if status_screen_name else _line_after_label(text, "account holder", "customer name", "name")
        ),
        "account_number": _digits_only(account_match.group(1)) if account_match else None,
    }
