"""Tests for services/document_classifier.py.

Each test feeds a representative text snippet into classify_page() and
asserts both the document_type and that confidence == 1.0 (or 0.0 for
the unclassified fallback).
"""

import pytest

from services.document_classifier import classify_page


# ── Helper ────────────────────────────────────────────────────────────────────

def _classify(text: str) -> str:
    """Return only the document_type string for cleaner assertions."""
    return classify_page(text)["document_type"]


def _confidence(text: str) -> float:
    return classify_page(text)["confidence"]


# ── Existing document types ───────────────────────────────────────────────────

def test_pan_card_classified() -> None:
    text = "Income Tax Department Permanent Account Number ABCDE1234F"
    assert _classify(text) == "PAN Card"
    assert _confidence(text) == 1.0


def test_aadhaar_classified() -> None:
    text = "UIDAI Aadhaar Unique Identification Authority of India 1234 5678 9012"
    assert _classify(text) == "Aadhaar"


def test_bank_statement_classified() -> None:
    text = "Bank Statement Account Statement Debit Credit Balance"
    assert _classify(text) == "Bank Statement"


def test_salary_slip_classified() -> None:
    text = "Pay Slip Gross Salary Net Salary Basic HRA Deductions"
    assert _classify(text) == "Salary Slip"


def test_loan_agreement_classified() -> None:
    # Must NOT contain sanction keywords (sanction is higher priority)
    text = "Loan Agreement between the Borrower and the Lender Repayment Schedule"
    assert _classify(text) == "Loan Agreement"


def test_nach_form_classified() -> None:
    text = "NACH National Automated Clearing House Auto Debit Mandate"
    assert _classify(text) == "NACH Form"


def test_property_document_classified() -> None:
    text = "Sale Deed Property Document Registered Deed"
    assert _classify(text) == "Property Document"


def test_application_form_classified() -> None:
    text = "Loan Application Applicant Name Date of Birth Application Form"
    assert _classify(text) == "Application Form"


def test_unclassified_returns_none() -> None:
    text = "Some random unrelated text with no keywords"
    assert _classify(text) == "None"
    assert _confidence(text) == 0.0


# ── New document types ────────────────────────────────────────────────────────

def test_voter_id_classified() -> None:
    text = "Election Commission of India Electors Photo Identity Card"
    assert _classify(text) == "Voter ID"
    assert _confidence(text) == 1.0


def test_voter_id_classified_via_epic() -> None:
    text = "EPIC Voter ID Government of India"
    assert _classify(text) == "Voter ID"


def test_driving_license_classified() -> None:
    # Needs a DL phrase + a date for the expiry check
    text = "Driving Licence Motor Vehicles Act Transport Department Valid Until 31/12/2028"
    assert _classify(text) == "Driving License"
    assert _confidence(text) == 1.0


def test_driving_license_requires_date() -> None:
    # DL phrase present but no date → should NOT classify as Driving License
    text = "Driving Licence Motor Vehicles Act no date here"
    result = classify_page(text)["document_type"]
    assert result != "Driving License"


def test_passport_classified() -> None:
    text = "Republic of India Passport Ministry of External Affairs A1234567"
    assert _classify(text) == "Passport"
    assert _confidence(text) == 1.0


def test_passport_requires_number() -> None:
    # Republic + passport phrase but no passport number → not Passport
    text = "Republic of India Passport Ministry of External Affairs"
    result = _classify(text)
    assert result != "Passport"


def test_sanction_letter_classified() -> None:
    text = "Sanction Letter Sanctioned Amount Tenure Loan Sanction"
    assert _classify(text) == "Sanction Letter"
    assert _confidence(text) == 1.0


def test_sanction_letter_via_kfs() -> None:
    text = "Key Fact Statement KFS Home Loan"
    assert _classify(text) == "Sanction Letter"


def test_crif_classified() -> None:
    text = "CRIF Credit Information Report Credit Score"
    assert _classify(text) == "CRIF Report"
    assert _confidence(text) == 1.0


def test_crif_classified_via_cibil() -> None:
    text = "CIBIL Credit Report Bureau Score"
    assert _classify(text) == "CRIF Report"


def test_insurance_classified() -> None:
    text = "Life Insurance Policy Sum Assured Nominee Premium"
    assert _classify(text) == "Insurance Form"
    assert _confidence(text) == 1.0


def test_insurance_requires_all_three_groups() -> None:
    # Has 'insurance' and type but no policy/sum assured/nominee → not Insurance Form
    text = "Insurance Life Premium only"
    result = _classify(text)
    assert result != "Insurance Form"


def test_stamp_duty_classified() -> None:
    text = "Non Judicial Stamp Paper Stamp Duty Franking"
    assert _classify(text) == "Stamp Duty"
    assert _confidence(text) == 1.0


def test_stamp_duty_classified_via_estamp() -> None:
    text = "e-Stamp Certificate Government of Maharashtra"
    assert _classify(text) == "Stamp Duty"


def test_guarantee_deed_classified() -> None:
    text = "Guarantee Deed Deed of Guarantee executed by Guarantor"
    assert _classify(text) == "Guarantee Deed"
    assert _confidence(text) == 1.0


def test_guarantee_deed_via_guarantor_and_deed() -> None:
    text = "This deed is executed by the guarantor in favour of the lender"
    assert _classify(text) == "Guarantee Deed"


def test_utility_bill_electricity_classified() -> None:
    text = "Electricity Bill Consumer No 123456 Due Date 15/07/2025"
    assert _classify(text) == "Utility Bill"
    assert _confidence(text) == 1.0


def test_utility_bill_broadband_classified() -> None:
    text = "Broadband Internet Services Monthly Invoice"
    assert _classify(text) == "Utility Bill"


# ── Priority order tests ──────────────────────────────────────────────────────

def test_sanction_before_loan_agreement() -> None:
    """Sanction Letter must win when both keywords appear on the same page."""
    text = (
        "Sanction Letter Loan Agreement Borrower Lender "
        "Sanctioned Amount Tenure Repayment"
    )
    assert _classify(text) == "Sanction Letter"


def test_pan_before_aadhaar() -> None:
    """PAN is priority 1; Aadhaar is priority 2."""
    text = (
        "Permanent Account Number ABCDE1234F "
        "Aadhaar UIDAI 1234 5678 9012"
    )
    assert _classify(text) == "PAN Card"


def test_passport_before_voter_id() -> None:
    """Passport (priority 3) beats Voter ID (priority 5)."""
    text = (
        "Republic of India Passport Ministry of External Affairs A1234567 "
        "Election Commission Voter ID"
    )
    assert _classify(text) == "Passport"


def test_crif_before_bank_statement() -> None:
    """CRIF Report (priority 9) beats Bank Statement (priority 10)."""
    text = "CRIF Credit Report Debit Credit Balance Account Statement"
    assert _classify(text) == "CRIF Report"


def test_insurance_before_utility_bill() -> None:
    """Insurance Form (priority 12) beats Utility Bill (priority 15)."""
    text = "Life Insurance Policy Sum Assured Nominee Premium Electricity Bill"
    assert _classify(text) == "Insurance Form"
