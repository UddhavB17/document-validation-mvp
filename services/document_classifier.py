"""Document page classifier for DMEF.

Classifies a single page of extracted text into one of the recognised
MS Fincap document types.

Public API
----------
classify_page(text: str) -> dict
    Returns {"document_type": str, "confidence": float}.

Priority order (most-specific first, generic last):
  1.  PAN Card
  2.  Aadhaar
  3.  Passport
  4.  Driving License
  5.  Voter ID
  6.  Sanction Letter   ← before Loan Agreement
  7.  Loan Agreement
  8.  NACH Form
  9.  CRIF Report
  10. Bank Statement
  11. Salary Slip
  12. Insurance Form
  13. Stamp Duty
  14. Guarantee Deed
  15. Utility Bill
  16. Property Document
  17. Application Form
  18. None              ← unclassified fallback
"""

from __future__ import annotations

import re


# ── Return-value helper ───────────────────────────────────────────────────────

def _result(document_type: str, confidence: float = 1.0) -> dict:
    return {"document_type": document_type, "confidence": confidence}


# ── Individual detectors (called in priority order) ───────────────────────────

def _is_pan(text_lower: str) -> bool:
    """PAN Card: permanent account number + income tax indicators."""
    has_pan_phrase = (
        "permanent account number" in text_lower
        or "income tax department" in text_lower
        or "pan card" in text_lower
    )
    has_pan_number = bool(re.search(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', text_lower.upper()))
    return has_pan_phrase or has_pan_number


def _is_aadhaar(text_lower: str) -> bool:
    """Aadhaar: UIDAI-issued identity card."""
    has_aadhaar_phrase = (
        "aadhaar" in text_lower
        or "unique identification" in text_lower
        or "uidai" in text_lower
        or "aadhar" in text_lower          # common misspelling
    )
    has_aadhaar_number = bool(re.search(r'\b\d{4}\s\d{4}\s\d{4}\b', text_lower))
    return has_aadhaar_phrase or has_aadhaar_number


def _is_passport(text_lower: str) -> bool:
    """Passport: Republic of India travel document with passport number."""
    has_republic = "republic of india" in text_lower
    has_passport_phrase = (
        "passport" in text_lower
        or "ministry of external affairs" in text_lower
    )
    has_passport_number = bool(re.search(r'[A-Z][0-9]{7}', text_lower.upper()))
    return has_republic and has_passport_phrase and has_passport_number


def _is_driving_license(text_lower: str) -> bool:
    """Driving License: MV Act + transport department + a date (expiry)."""
    has_dl_phrase = (
        "driving licence" in text_lower
        or "driving license" in text_lower
        or "motor vehicles act" in text_lower
        or "transport department" in text_lower
    )
    has_date = bool(
        re.search(
            r'\b\d{2}[/-]\d{2}[/-]\d{2,4}\b'   # DD/MM/YYYY or DD-MM-YY
            r'|\b\d{4}[/-]\d{2}[/-]\d{2}\b',    # YYYY-MM-DD
            text_lower,
        )
    )
    return has_dl_phrase and has_date


def _is_voter_id(text_lower: str) -> bool:
    """Voter ID / EPIC card issued by the Election Commission of India."""
    return (
        "election commission" in text_lower
        or "voter id" in text_lower
        or "electors photo identity" in text_lower
        or "epic" in text_lower
    )


def _is_sanction_letter(text_lower: str) -> bool:
    """Sanction Letter / Key Fact Statement."""
    has_simple = (
        "sanction letter" in text_lower
        or "key fact statement" in text_lower
        or "kfs" in text_lower
        or "loan sanction" in text_lower
    )
    has_compound = "sanctioned amount" in text_lower and "tenure" in text_lower
    return has_simple or has_compound


def _is_loan_agreement(text_lower: str) -> bool:
    """Loan Agreement."""
    return (
        "loan agreement" in text_lower
        or "borrower" in text_lower
        and "lender" in text_lower
        and "repayment" in text_lower
    )


def _is_nach_form(text_lower: str) -> bool:
    """NACH / ECS mandate form."""
    return (
        "nach" in text_lower
        or "national automated clearing house" in text_lower
        or "ecs mandate" in text_lower
        or "auto debit" in text_lower
    )


def _is_crif_report(text_lower: str) -> bool:
    """CRIF / CIBIL credit report."""
    return (
        "crif" in text_lower
        or "credit information report" in text_lower
        or "cibil" in text_lower
        or "credit score" in text_lower
        or "credit report" in text_lower
    )


def _is_bank_statement(text_lower: str) -> bool:
    """Bank Statement."""
    has_statement = (
        "bank statement" in text_lower
        or "account statement" in text_lower
        or "statement of account" in text_lower
    )
    has_transaction_markers = (
        "debit" in text_lower
        and "credit" in text_lower
        and "balance" in text_lower
    )
    return has_statement or has_transaction_markers


def _is_salary_slip(text_lower: str) -> bool:
    """Salary Slip / Pay Slip."""
    return (
        "salary slip" in text_lower
        or "pay slip" in text_lower
        or "payslip" in text_lower
        or ("gross salary" in text_lower and "net salary" in text_lower)
        or ("basic" in text_lower and "hra" in text_lower and "deductions" in text_lower)
    )


def _is_insurance_form(text_lower: str) -> bool:
    """Insurance Form: life/property insurance with policy details."""
    has_insurance = "insurance" in text_lower
    has_type = (
        "life" in text_lower
        or "property" in text_lower
        or "premium" in text_lower
    )
    has_policy = (
        "policy" in text_lower
        or "sum assured" in text_lower
        or "nominee" in text_lower
    )
    return has_insurance and has_type and has_policy


def _is_stamp_duty(text_lower: str) -> bool:
    """Stamp Duty / e-Stamp / Franking."""
    return (
        "stamp duty" in text_lower
        or "non judicial stamp" in text_lower
        or "e-stamp" in text_lower
        or "franking" in text_lower
        or "stamp paper" in text_lower
    )


def _is_guarantee_deed(text_lower: str) -> bool:
    """Guarantee Deed."""
    has_simple = (
        "guarantee deed" in text_lower
        or "deed of guarantee" in text_lower
    )
    has_compound = "guarantor" in text_lower and "deed" in text_lower
    return has_simple or has_compound


def _is_utility_bill(text_lower: str) -> bool:
    """Utility Bill (electricity, water, gas, telephone, broadband)."""
    has_simple = (
        "electricity bill" in text_lower
        or "water bill" in text_lower
        or "gas bill" in text_lower
        or "telephone bill" in text_lower
        or "broadband" in text_lower
    )
    has_compound = "consumer no" in text_lower and "due date" in text_lower
    return has_simple or has_compound


def _is_property_document(text_lower: str) -> bool:
    """Property Document / Sale Deed / Title Deed."""
    return (
        "sale deed" in text_lower
        or "title deed" in text_lower
        or "property document" in text_lower
        or "registered deed" in text_lower
        or ("survey number" in text_lower and "plot" in text_lower)
    )


def _is_application_form(text_lower: str) -> bool:
    """Loan Application Form."""
    return (
        "application form" in text_lower
        or "loan application" in text_lower
        or ("applicant name" in text_lower and "date of birth" in text_lower)
    )


# ── Main public function ──────────────────────────────────────────────────────

def classify_page(text: str) -> dict:
    """Classify a single page of extracted text into a document type.

    Checks are performed in the priority order defined in the module docstring.
    Returns the first match; unmatched pages return document_type="None".

    Args:
        text: Raw text extracted from a single PDF page.

    Returns:
        {"document_type": str, "confidence": float}
    """
    text_lower = text.lower()

    # 1. PAN Card
    if _is_pan(text_lower):
        return _result("PAN Card")

    # 2. Aadhaar
    if _is_aadhaar(text_lower):
        return _result("Aadhaar")

    # 3. Passport (specific: republic + passport phrase + passport number regex)
    if _is_passport(text_lower):
        return _result("Passport")

    # 4. Driving License (dl phrase + date regex)
    if _is_driving_license(text_lower):
        return _result("Driving License")

    # 5. Voter ID
    if _is_voter_id(text_lower):
        return _result("Voter ID")

    # 6. Sanction Letter — checked BEFORE Loan Agreement
    if _is_sanction_letter(text_lower):
        return _result("Sanction Letter")

    # 7. Loan Agreement
    if _is_loan_agreement(text_lower):
        return _result("Loan Agreement")

    # 8. NACH Form
    if _is_nach_form(text_lower):
        return _result("NACH Form")

    # 9. CRIF Report
    if _is_crif_report(text_lower):
        return _result("CRIF Report")

    # 10. Bank Statement
    if _is_bank_statement(text_lower):
        return _result("Bank Statement")

    # 11. Salary Slip
    if _is_salary_slip(text_lower):
        return _result("Salary Slip")

    # 12. Insurance Form
    if _is_insurance_form(text_lower):
        return _result("Insurance Form")

    # 13. Stamp Duty
    if _is_stamp_duty(text_lower):
        return _result("Stamp Duty")

    # 14. Guarantee Deed
    if _is_guarantee_deed(text_lower):
        return _result("Guarantee Deed")

    # 15. Utility Bill
    if _is_utility_bill(text_lower):
        return _result("Utility Bill")

    # 16. Property Document
    if _is_property_document(text_lower):
        return _result("Property Document")

    # 17. Application Form
    if _is_application_form(text_lower):
        return _result("Application Form")

    # 18. Unclassified
    return _result("None", confidence=0.0)
