"""Field and document rules used by mapped verification."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from database.models import FieldVerificationResult
from services.field_verification import (
    verify_aadhaar,
    verify_address,
    verify_amount,
    verify_date,
    verify_name,
    verify_pan,
    verify_phone,
    verify_pincode,
)


def verify_supported_field(field: str, extracted: str, expected: str) -> FieldVerificationResult:
    """Compare a supported field through the shared consistency matcher."""
    from services.consistency_checks import _matches

    matched = _matches(field, expected, extracted)
    return FieldVerificationResult(
        field_name=field,
        extracted_value=extracted,
        db_value=expected,
        match=matched,
        confidence=1.0 if matched else 0.0,
        method="exact" if field in {"account_number", "application_number", "ifsc"} else "fuzzy",
        mismatch_reason=None if matched else "Value does not match the trusted JSON/database dump",
    )


VERIFY: dict[str, Callable[[str, str], Any]] = {
    "aadhaar_number": verify_aadhaar,
    "pan_number": verify_pan,
    "phone_number": verify_phone,
    "date_of_birth": verify_date,
    "loan_amount": verify_amount,
    "applicant_name": verify_name,
    "address": verify_address,
    "pin_code": verify_pincode,
    **{
        field: partial(verify_supported_field, field)
        for field in (
            "account_number",
            "application_number",
            "ifsc",
            "tenure",
            "installment_count",
            "emi",
            "roi",
            "apr",
            "sanction_amount",
            "total_interest",
            "total_repayment",
            "processing_fee",
            "insurance_amount",
            "net_disbursement",
            "foir",
            "ltv",
        )
    },
}

ALIASES = {
    "aadhaar": "aadhaar_number",
    "aadhar": "aadhaar_number",
    "pan": "pan_number",
    "phone": "phone_number",
    "dob": "date_of_birth",
    "name": "applicant_name",
    "borrower_name": "applicant_name",
    "account_holder_name": "applicant_name",
    "pincode": "pin_code",
    "current_address": "address",
    "permanent_address": "address",
    "communication_address": "address",
    "requested_amount": "loan_amount",
}

DOCUMENT_FIELDS = {
    "cam": {
        "application_number",
        "applicant_name",
        "phone_number",
        "loan_amount",
        "sanction_amount",
        "tenure",
        "emi",
        "roi",
        "account_number",
        "ifsc",
    },
    "aadhaar": {"aadhaar_number", "applicant_name", "date_of_birth", "address", "pin_code"},
    "pan": {"pan_number", "applicant_name", "date_of_birth"},
    "pan card": {"pan_number", "applicant_name", "date_of_birth"},
    "sanction letter": {"applicant_name", "loan_amount"},
    "kfs": {"loan_amount"},
    "loan agreement": {"applicant_name", "loan_amount"},
    "facility agreement": {"applicant_name", "loan_amount"},
    "application form": {
        "applicant_name",
        "aadhaar_number",
        "pan_number",
        "date_of_birth",
        "phone_number",
        "address",
        "pin_code",
        "loan_amount",
    },
    "utility bill": set(),
    "voter id": {"applicant_name", "date_of_birth", "address"},
    "cibil report": {"applicant_name"},
    "crif report": {"applicant_name"},
    "bank statement": {"applicant_name", "account_number", "ifsc"},
    "passbook": {"applicant_name", "account_number", "ifsc"},
    "cheque": {"applicant_name", "account_number", "ifsc"},
    "nach form": {"applicant_name", "account_number", "ifsc"},
}

AGGREGATED_FIELD_DOC_TYPES = frozenset(
    {
        "sanction letter",
        "cam",
        "kfs",
        "loan agreement",
        "facility agreement",
        "application form",
        "aadhaar",
        "pan",
        "pan card",
        "voter id",
        "driving license",
        "bank statement",
        "passbook",
        "utility bill",
        "cibil report",
        "crif report",
        "stamp duty",
        "insurance consent",
        "nach form",
        "cheque",
    }
)

LOW_OCR_CONFIDENCE_THRESHOLD = 0.55
OPTIONAL_ON_MULTIPAGE_BANKING_DOC_TYPES = frozenset({"bank statement", "passbook", "cheque"})
