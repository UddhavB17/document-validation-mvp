"""Loan-term extractors: CAM, sanction letter, loan agreement."""

from __future__ import annotations

import re
from typing import Any

from services.extraction._generic import _sanitize_generic_value
from services.extraction._shared import (
    _clean_name_like_value,
    _digits_only,
    _extract_amount,
    _extract_date_near,
    _extract_emi,
    _extract_identifier,
    _extract_percentage_near,
    _extract_roi,
    _extract_tenure_months,
    _float_or_none,
    _int_or_none,
    _line_after_label,
    _next_nonempty_line,
    _normalize_amount,
    _numeric_line_after_label,
    _parse_date,
    _sanitize_address_value,
)


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
    requested_amount = _normalize_amount(_next_nonempty_line(text, "requested loan amount"))
    requested_roi = _float_or_none(_normalize_amount(_next_nonempty_line(text, "requested irr")))
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
        r"(?:^|\n)\s*(?:DECISION\s*\n\s*)?Sanction\s+Loan\s+Amount\s*\n"
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
        fields.update(
            {
                "loan_amount": amount,
                "sanction_amount": amount,
                "tenure": _int_or_none(decision.group(2)),
                "roi": _float_or_none(decision.group(4)),
                "emi": _normalize_amount(decision.group(5)),
            }
        )

    if re.search(r"\bREPAYMENT\s+BANK\s+DETAILS\b", text, re.IGNORECASE):
        section_match = re.search(
            r"\bREPAYMENT\s+BANK\s+DETAILS\b(.*?)(?=\n\s*(?:DECISION|SANCTION\s+CONDITIONS)\b|\Z)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        bank_text = section_match.group(1) if section_match else ""
        fields.update(
            {
                "account_number": _digits_only(
                    _next_nonempty_line(bank_text, "account number") or ""
                )
                or None,
                "ifsc": (_next_nonempty_line(bank_text, "ifsc code") or "").upper() or None,
                "account_holder_name": _next_nonempty_line(bank_text, "account holder name"),
            }
        )
    return fields


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
        records.append(
            {
                "applicant_name": re.sub(r"\s+", " ", match.group(2)).strip(),
                "phone_number": match.group(3),
                "date_of_birth": _parse_date(re.sub(r"\s+", "", match.group(4))),
            }
        )
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
        records.append(
            {
                "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
                "aadhaar_last4": match.group(2)[-4:],
                "pan_number": match.group(3).upper(),
            }
        )
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
        records.append(
            {
                "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
                "address": address,
                f"{subtype}_address": address,
            }
        )
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
        records.append(
            {
                "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
                f"{bureau}_score": match.group(3),
            }
        )
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
            t,
            "sanctioned loan amount",
            "sanctioned amount",
            "loan amount",
            "amount sanctioned",
            "amount of facility",
            "sanction amount",
        )
        or _normalize_amount(
            _numeric_line_after_label(
                text,
                "sanctioned loan amount (in rs.)",
                "sanction amount",
                "amount of facility (in rs.)",
            )
        ),
        "tenure": _extract_tenure_months(t)
        or _int_or_none(_numeric_line_after_label(text, "loan terms (months)", "tenure (months)")),
        "emi": _extract_emi(t)
        or _normalize_amount(_numeric_line_after_label(text, "epi (in rs.)", "emi")),
        "roi": _extract_roi(t)
        or _float_or_none(
            _numeric_line_after_label(text, "roi (p.a)", "interest rate (%) and type")
        ),
        "apr": _extract_percentage_near(t, "apr", "annual percentage rate"),
        "applicant_name": _line_after_label(text, "borrower", "applicant name"),
        "application_number": _extract_identifier(
            text, "application number", "application no", "loan account number", "loan id"
        ),
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
        )
        or _normalize_amount(_numeric_line_after_label(text, "amount of facility (in rs.)")),
        "tenure": _extract_tenure_months(t)
        or _int_or_none(_numeric_line_after_label(text, "term or tenure")),
        "emi": _extract_emi(t)
        or _normalize_amount(
            _numeric_line_after_label(text, "emi amount* (in rs.)", "emi amount (in rs.)")
        ),
        "roi": _extract_roi(t)
        or _float_or_none(_numeric_line_after_label(text, "rate of interest")),
        "apr": _extract_percentage_near(t, "apr", "annual percentage rate"),
        "borrower_name": (
            re.sub(r"\s+", " ", schedule_name.group(1)).strip()
            if schedule_name
            else _line_after_label(text, "borrower")
        ),
        "agreement_date": _extract_date_near(t, "date of agreement", "agreement date", "date"),
        "application_number": _extract_identifier(
            text, "application number", "application no", "loan account number", "loan id"
        ),
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
            part.strip(" .") for part in purpose_match.groups() if part and part.strip(" .")
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
