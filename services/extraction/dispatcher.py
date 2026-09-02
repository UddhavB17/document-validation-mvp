"""Route document types to family-specific extractors."""

from __future__ import annotations

from typing import Any

from services.extraction._generic import (
    _extract_generic_labeled_fields,
    _generic_fields_allowed_for,
    _sanitize_generic_value,
)
from services.extraction._shared import (
    _has_repayment_summary_evidence,
    _sanitize_address_fields,
    _sanitize_name_fields,
)
from services.extraction.application import (
    _extract_application_form,
    _extract_application_layout_addresses,
)
from services.extraction.banking import (
    _extract_bank_statement,
    _extract_cheque,
    _extract_nach_form,
    _extract_passbook,
    _extract_pdc,
)
from services.extraction.bureau import _extract_crif_report
from services.extraction.identity import (
    _extract_aadhaar,
    _extract_driving_license,
    _extract_pan,
    _extract_voter_id,
)
from services.extraction.loan_terms import (
    _extract_cam,
    _extract_end_use_letter,
    _extract_loan_agreement,
    _extract_sanction_letter,
)
from services.extraction.property_compliance import (
    _extract_cersai_report,
    _extract_clearance_report,
    _extract_insurance_consent,
    _extract_insurance_form,
    _extract_salary_slip,
    _extract_stamp_duty,
    _extract_utility_bill,
)
from services.validation_gates import is_aadhaar_verification_appendix


def extract_fields(
    document_type: str,
    text: str,
    *,
    structured_content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured fields from *text* for *document_type*."""
    if document_type == "Aadhaar" and is_aadhaar_verification_appendix(text):
        return {"_aadhaar_verification_appendix": True}

    extractors = {
        "CAM": _extract_cam,
        "Sanction Letter": _extract_sanction_letter,
        "KFS": _extract_sanction_letter,
        "Loan Agreement": _extract_loan_agreement,
        "Facility Agreement": _extract_loan_agreement,
        "PAN": _extract_pan,
        "PAN Card": _extract_pan,
        "Aadhaar": _extract_aadhaar,
        "Voter ID": _extract_voter_id,
        "Driving License": _extract_driving_license,
        "CERSAI Report": _extract_cersai_report,
        "CRIF Report": _extract_crif_report,
        "CIBIL Report": _extract_crif_report,
        "Passbook": _extract_passbook,
        "Bank Statement": _extract_bank_statement,
        "Cheque": _extract_cheque,
        "Salary Slip": _extract_salary_slip,
        "Utility Bill": _extract_utility_bill,
        "Application Form": _extract_application_form,
        "Insurance Form": _extract_insurance_form,
        "Life Insurance Form": _extract_insurance_form,
        "End-Use Letter": _extract_end_use_letter,
        "Stamp Duty": _extract_stamp_duty,
        "Insurance Consent Letter": _extract_insurance_consent,
        "Legal Clearance Report": _extract_clearance_report,
        "Technical Clearance Report": _extract_clearance_report,
        "Technical Report": _extract_clearance_report,
        "NACH Form": _extract_nach_form,
        "PDC": _extract_pdc,
    }
    extractor = extractors.get(document_type)
    if extractor is None:
        return {}
    fields = _sanitize_name_fields(extractor(text))
    if document_type == "Application Form":
        fields.update(_extract_application_layout_addresses(structured_content))
    fields = _sanitize_address_fields(fields)
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
