"""Generic labeled-field extraction shared across document families."""

from __future__ import annotations

import re
from typing import Any

from services.extraction._shared import (
    _clean_name_like_value,
    _digits_only,
    _raw_value_after_label,
)

_IDENTITY_GENERIC_FIELDS = {
    "salutation",
    "customer_id",
    "application_number",
    "ration_card_number",
    "gstin",
    "udyam_status",
    "kyc_status",
    "profile_photograph_present",
    "facial_identity_status",
    "age",
    "gender",
    "marital_status",
    "qualification",
    "profession",
    "disability_status",
    "ews_status",
    "caste",
    "religion",
    "medical_condition",
    "father_name",
    "mother_name",
    "relationship",
    "phone_number",
    "email",
}
_ADDRESS_GENERIC_FIELDS = {
    "address_ownership",
    "address_subtype",
    "landmark",
    "locality",
    "tehsil",
    "district",
    "state",
    "country",
    "pin_code",
    "occupied_since",
    "latitude",
    "longitude",
}
_BANK_GENERIC_FIELDS = {
    "bank_linked_mobile",
    "bank_name",
    "branch",
    "account_type",
    "bank_verification_status",
    "primary_account",
    "nach_status",
    "mandate_amount",
    "mandate_validity",
    "payment_destination",
}
_BUREAU_GENERIC_FIELDS = {
    "bureau_account_count",
    "overdue_account_count",
    "dpd_status",
    "credit_report_id",
    "monthly_obligations",
    "available_income",
    "maximum_emi",
    "foir",
}
_LOAN_GENERIC_FIELDS = {
    "loan_purpose",
    "product_type",
    "requested_amount",
    "recommended_amount",
    "sanction_amount",
    "apr",
    "first_emi",
    "final_emi",
    "repayment_start_date",
    "maturity_date",
    "installment_count",
    "total_interest",
    "total_repayment",
    "processing_fee",
    "insurance_amount",
    "other_charges",
    "net_disbursement",
    "ltv",
    "property_owner",
    "ownership_type",
    "market_value",
    "distress_value",
    "land_value",
    "construction_value",
    "property_area",
    "property_address",
    "site_address",
    "property_usage",
    "occupancy",
    "property_condition",
    "construction_status",
    "sanction_conditions",
    "approved_deviations",
    "pending_conditions",
    "tranche_structure",
    "workflow_status",
    "repayment_status",
    "overdue_status",
}
_EMPLOYMENT_GENERIC_FIELDS = {
    "employment_type",
    "income_source",
    "occupation",
    "work_profile",
    "industry",
    "job_role",
    "job_description",
    "monthly_income",
    "verified_income",
    "considered_income",
    "turnover",
    "margin",
    "years_current_work",
    "overall_experience",
    "income_stability",
    "verification_method",
    "income_proof_basis",
    "verification_status",
    "verifier",
    "field_remarks",
}


def _extract_generic_labeled_fields(text: str) -> dict[str, Any]:
    """Extract clearly labelled fields shared by forms, CAMs and loan records."""
    labels = {
        "salutation": ("salutation",),
        "customer_id": ("customer id", "applicant id"),
        "application_number": (
            "application number",
            "application no",
            "loan account number",
            "loan id",
        ),
        "ration_card_number": ("ration card number", "ration card no"),
        "gstin": ("gstin", "gst number"),
        "udyam_status": ("udyam status",),
        "kyc_status": ("kyc status", "kyc verification status"),
        "profile_photograph_present": ("profile photograph", "photograph status"),
        "facial_identity_status": ("facial identity", "face match status"),
        "age": ("age",),
        "gender": ("gender",),
        "marital_status": ("marital status",),
        "qualification": ("qualification",),
        "profession": ("profession",),
        "disability_status": ("disability status", "disabled"),
        "ews_status": ("ews status",),
        "caste": ("caste",),
        "religion": ("religion",),
        "medical_condition": ("medical condition",),
        "father_name": ("father's name", "father name"),
        "mother_name": ("mother's name", "mother name"),
        "relationship": ("relationship to applicant", "relation with applicant"),
        "phone_number": ("mobile number", "mobile no", "phone numbers", "phone number"),
        "email": ("email", "email id", "email ids"),
        "bank_linked_mobile": ("bank linked mobile", "mobile linked to bank"),
        "address_ownership": ("address ownership", "residence ownership"),
        "address_subtype": ("address subtype", "residence type"),
        "landmark": ("landmark",),
        "locality": ("village/locality", "locality", "village"),
        "tehsil": ("tehsil",),
        "district": ("district",),
        "state": ("state",),
        "country": ("country",),
        "pin_code": ("pin code", "pincode"),
        "occupied_since": ("occupied since", "residing since"),
        "latitude": ("latitude",),
        "longitude": ("longitude",),
        "employment_type": ("employment type",),
        "income_source": ("income source",),
        "occupation": ("occupation",),
        "work_profile": ("work profile",),
        "industry": ("industry",),
        "job_role": ("job role",),
        "job_description": ("job description",),
        "monthly_income": ("monthly declared income", "monthly income"),
        "verified_income": ("monthly verified income", "verified income"),
        "considered_income": ("income considered", "eligibility income"),
        "turnover": ("turnover",),
        "margin": ("margin",),
        "years_current_work": ("years in current work", "work vintage"),
        "overall_experience": ("overall experience", "total experience"),
        "income_stability": ("income stability",),
        "verification_method": ("verification method",),
        "income_proof_basis": ("income proof basis",),
        "verification_status": ("verification status",),
        "verifier": ("verified by", "verifier"),
        "field_remarks": ("field remarks", "pd remarks"),
        "bank_name": ("bank name", "name of bank"),
        "branch": ("bank branch", "branch"),
        "account_type": ("account type",),
        "bank_verification_status": ("bank verification status",),
        "primary_account": ("primary account",),
        "nach_status": ("nach status", "mandate status"),
        "mandate_amount": ("mandate amount",),
        "mandate_validity": ("mandate validity",),
        "payment_destination": ("payment destination",),
        "bureau_account_count": ("number of accounts", "total accounts"),
        "overdue_account_count": ("overdue account count", "overdue accounts"),
        "dpd_status": ("dpd status",),
        "credit_report_id": ("credit report id", "report id"),
        "monthly_obligations": ("monthly obligations",),
        "available_income": ("available income",),
        "maximum_emi": ("maximum emi", "max emi"),
        "foir": ("foir",),
        "loan_purpose": ("loan purpose",),
        "product_type": ("loan product", "product type"),
        "requested_amount": ("requested amount",),
        "recommended_amount": ("recommended amount",),
        "sanction_amount": ("sanctioned amount", "sanction amount"),
        "apr": ("apr",),
        "first_emi": ("first emi",),
        "final_emi": ("final emi",),
        "repayment_start_date": ("repayment commencement date", "repayment start date"),
        "maturity_date": ("maturity date",),
        "installment_count": ("scheduled installments", "installment count"),
        "total_interest": ("total interest",),
        "total_repayment": ("total borrower repayment", "total repayment"),
        "processing_fee": ("processing fee",),
        "insurance_amount": ("insurance amount",),
        "other_charges": ("other charges",),
        "net_disbursement": ("net disbursement",),
        "ltv": ("ltv", "loan to value"),
        "property_owner": ("property owner",),
        "ownership_type": ("ownership type",),
        "market_value": ("market value",),
        "distress_value": ("distress value",),
        "land_value": ("land value",),
        "construction_value": ("construction value",),
        "property_area": ("property area", "total area"),
        "property_address": ("property address", "document address"),
        "site_address": ("site address",),
        "property_usage": ("property usage",),
        "occupancy": ("occupancy",),
        "property_condition": ("property condition",),
        "construction_status": ("construction status",),
        "sanction_conditions": ("sanction conditions",),
        "approved_deviations": ("approved deviations",),
        "pending_conditions": ("pending conditions",),
        "tranche_structure": ("tranche structure",),
        "workflow_status": ("workflow status",),
        "repayment_status": ("repayment status",),
        "overdue_status": ("overdue status",),
    }
    fields: dict[str, Any] = {}
    for field_name, candidates in labels.items():
        value = _raw_value_after_label(text, *candidates)
        if value not in (None, ""):
            fields[field_name] = value
    return fields


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
            _IDENTITY_GENERIC_FIELDS
            | _ADDRESS_GENERIC_FIELDS
            | _BANK_GENERIC_FIELDS
            | _BUREAU_GENERIC_FIELDS
            | _LOAN_GENERIC_FIELDS
            | _EMPLOYMENT_GENERIC_FIELDS
        )
    if document_type == "CAM":
        return (
            _IDENTITY_GENERIC_FIELDS
            | _ADDRESS_GENERIC_FIELDS
            | _BANK_GENERIC_FIELDS
            | _BUREAU_GENERIC_FIELDS
            | _LOAN_GENERIC_FIELDS
            | _EMPLOYMENT_GENERIC_FIELDS
        )
    if document_type in {"Sanction Letter", "KFS", "Loan Agreement", "Facility Agreement"}:
        return _IDENTITY_GENERIC_FIELDS | _LOAN_GENERIC_FIELDS | _ADDRESS_GENERIC_FIELDS
    if document_type == "End-Use Letter":
        return _IDENTITY_GENERIC_FIELDS | _LOAN_GENERIC_FIELDS
    if document_type in {"Bank Statement", "Passbook", "Cheque", "NACH Form"}:
        return _IDENTITY_GENERIC_FIELDS | _BANK_GENERIC_FIELDS
    if document_type in {
        "Technical Report",
        "Technical Clearance Report",
        "Legal Clearance Report",
    }:
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
    if field_name in {
        "application_number",
        "customer_id",
        "credit_report_id",
        "gstin",
        "ration_card_number",
    }:
        return compact if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./_-]{3,40}", compact) else None
    if field_name in {
        "requested_amount",
        "recommended_amount",
        "sanction_amount",
        "apr",
        "first_emi",
        "final_emi",
        "installment_count",
        "total_interest",
        "total_repayment",
        "processing_fee",
        "insurance_amount",
        "other_charges",
        "net_disbursement",
        "ltv",
        "market_value",
        "distress_value",
        "land_value",
        "construction_value",
        "property_area",
        "monthly_income",
        "verified_income",
        "considered_income",
        "turnover",
        "margin",
        "monthly_obligations",
        "available_income",
        "maximum_emi",
        "foir",
        "bureau_account_count",
        "overdue_account_count",
        "mandate_amount",
        "latitude",
        "longitude",
    }:
        return compact if re.search(r"\d", compact) else None
    if field_name in {"father_name", "mother_name"}:
        return _clean_name_like_value(compact)
    if not re.search(r"[A-Za-z0-9]", compact):
        return None
    return compact
