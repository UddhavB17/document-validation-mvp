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


def _is_kyc_osv_mark(text_lower: str) -> bool:
    return (
        "original seen and verified" in text_lower
        or "original seen verified" in text_lower
        or re.search(r"\bosv\b", text_lower) is not None
    )


def _is_facility_agreement(text_lower: str) -> bool:
    return "facility agreement" in text_lower


def _is_passbook(text_lower: str) -> bool:
    return (
        "passbook" in text_lower
        or "pass book" in text_lower
        or "savings bank passbook" in text_lower
    )


def _is_consent_letter(text_lower: str) -> bool:
    return "consent letter" in text_lower or "customer consent" in text_lower


def _is_insurance_consent_letter(text_lower: str) -> bool:
    return "insurance consent" in text_lower or (
        "insurance" in text_lower and "consent" in text_lower and "tenure" in text_lower
    )


def _is_technical_report(text_lower: str) -> bool:
    return (
        "technical report" in text_lower
        or "technical evaluation" in text_lower
        or "technical valuation" in text_lower
        or "valuation report" in text_lower
    )


def _is_technical_clearance(text_lower: str) -> bool:
    return "technical clearance" in text_lower


def _is_legal_clearance(text_lower: str) -> bool:
    return (
        "legal clearance" in text_lower
        or "legal report" in text_lower
        or "title search report" in text_lower
    )


def _is_fi_report(text_lower: str) -> bool:
    return (
        "fi report" in text_lower
        or "field investigation" in text_lower
        or "field inquiry report" in text_lower
    )


def _is_pdc(text_lower: str) -> bool:
    return (
        "post dated cheque" in text_lower
        or "post-dated cheque" in text_lower
        or re.search(r"\bpdc\b", text_lower) is not None
        or "security cheque" in text_lower
    )


def _is_disbursement_request(text_lower: str) -> bool:
    return "request for disbursement" in text_lower or "disbursement request" in text_lower


def _is_bt_undertaking(text_lower: str) -> bool:
    return "bt undertaking" in text_lower or "balance transfer undertaking" in text_lower


def _is_crime_check_report(text_lower: str) -> bool:
    return (
        "crime check" in text_lower
        or "criminal verification" in text_lower
        or "police verification report" in text_lower
    )


def _is_customer_app_proof(text_lower: str) -> bool:
    return (
        "customer app" in text_lower
        or "mobile app installed" in text_lower
        or "ms fincap app" in text_lower
        or "msfincap app" in text_lower
    )


def _is_bank_signature_verification(text_lower: str) -> bool:
    return (
        "bank signature verification" in text_lower
        or re.search(r"\bbsv\b", text_lower) is not None
        or "signature verification from bank" in text_lower
    )


def _is_ach_approval_document(text_lower: str) -> bool:
    return (
        "cbo approval" in text_lower
        or "ceo approval" in text_lower
        or "nach approval" in text_lower
    )


def _is_foreclosure_letter(text_lower: str) -> bool:
    return (
        "foreclosure letter" in text_lower
        or "list of documents" in text_lower
        or re.search(r"\blod\b", text_lower) is not None
    )


def _is_payment_favoring_letter(text_lower: str) -> bool:
    return (
        "payment favoring" in text_lower
        or "favoring account" in text_lower
        or "payee account" in text_lower
    )


def _is_pre_disbursement_conditions(text_lower: str) -> bool:
    return (
        "pre disbursement" in text_lower
        or "pre-disbursement" in text_lower
        or "sanction condition" in text_lower
        or "special condition" in text_lower
    )


def _is_charges_deduction_document(text_lower: str) -> bool:
    return (
        "charges deduction" in text_lower
        or "processing fee" in text_lower
        or "login fee" in text_lower
    )


def _is_otc_pdd_document(text_lower: str) -> bool:
    return (
        re.search(r"\botc\b", text_lower) is not None
        or re.search(r"\bpdd\b", text_lower) is not None
        or "post disbursement document" in text_lower
    )


def _is_dual_name_declaration(text_lower: str) -> bool:
    return (
        "dual name" in text_lower
        or "name mismatch declaration" in text_lower
        or ("affidavit" in text_lower and "name" in text_lower)
    )


def _is_approval_letter(text_lower: str) -> bool:
    return (
        "approval of authority" in text_lower
        or "sanctioning authority" in text_lower
        or "approved by credit" in text_lower
    )


def _is_relationship_proof(text_lower: str) -> bool:
    return "relationship proof" in text_lower or "relationship between" in text_lower


def _is_vernacular_document(text_lower: str) -> bool:
    return "vernacular" in text_lower or "regional language declaration" in text_lower


def _is_agreement_signing_photo(text_lower: str) -> bool:
    return (
        "signing photo" in text_lower
        or "agreement photo" in text_lower
        or "signing video" in text_lower
        or "agreement signing" in text_lower
    )


def _is_udyam_certificate(text_lower: str) -> bool:
    return "udyam" in text_lower or "msme registration" in text_lower


def _is_gst_certificate(text_lower: str) -> bool:
    return "gst registration" in text_lower or "gstin" in text_lower


def _is_shop_establishment_certificate(text_lower: str) -> bool:
    return "shop establishment" in text_lower or "shop act" in text_lower


def _is_income_tax_return(text_lower: str) -> bool:
    return (
        "income tax return" in text_lower
        or "itr-" in text_lower
        or "form 26as" in text_lower
    )


def _is_assessed_income_document(text_lower: str) -> bool:
    return "assessed income" in text_lower or "income assessment" in text_lower


def _is_operations_checklist(text_lower: str) -> bool:
    return (
        "non discrepancy checklist" in text_lower
        or "operations checklist" in text_lower
        or ("msfc / ndc" in text_lower and "checklist" in text_lower)
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

    # 6b. Facility Agreement — before generic Loan Agreement
    if _is_facility_agreement(text_lower):
        return _result("Facility Agreement")

    # 7. Loan Agreement
    if _is_loan_agreement(text_lower):
        return _result("Loan Agreement")

    # 8. NACH Form
    if _is_nach_form(text_lower):
        return _result("NACH Form")

    # 9. CRIF Report
    if _is_crif_report(text_lower):
        return _result("CRIF Report")

    # 10. Passbook — before Bank Statement
    if _is_passbook(text_lower):
        return _result("Passbook")

    # 11. Bank Statement
    if _is_bank_statement(text_lower):
        return _result("Bank Statement")

    # 12. Salary Slip
    if _is_salary_slip(text_lower):
        return _result("Salary Slip")

    # 13. Insurance Form
    if _is_insurance_form(text_lower):
        return _result("Insurance Form")

    # 14. Insurance Consent Letter
    if _is_insurance_consent_letter(text_lower):
        return _result("Insurance Consent Letter")

    # 15. Stamp Duty
    if _is_stamp_duty(text_lower):
        return _result("Stamp Duty")

    # 16. Guarantee Deed
    if _is_guarantee_deed(text_lower):
        return _result("Guarantee Deed")

    # 17. Utility Bill
    if _is_utility_bill(text_lower):
        return _result("Utility Bill")

    # 18. Property Document
    if _is_property_document(text_lower):
        return _result("Property Document")

    # 19. MSFC operational / legal documents
    if _is_operations_checklist(text_lower):
        return _result("Operations Checklist")
    if _is_kyc_osv_mark(text_lower):
        return _result("KYC OSV Mark")
    if _is_consent_letter(text_lower):
        return _result("Consent Letter")
    if _is_technical_report(text_lower):
        return _result("Technical Report")
    if _is_technical_clearance(text_lower):
        return _result("Technical Clearance Report")
    if _is_legal_clearance(text_lower):
        return _result("Legal Clearance Report")
    if _is_fi_report(text_lower):
        return _result("FI Report")
    if _is_pdc(text_lower):
        return _result("PDC")
    if _is_disbursement_request(text_lower):
        return _result("Disbursement Request")
    if _is_bt_undertaking(text_lower):
        return _result("BT Undertaking")
    if _is_crime_check_report(text_lower):
        return _result("Crime Check Report")
    if _is_customer_app_proof(text_lower):
        return _result("Customer App Proof")
    if _is_bank_signature_verification(text_lower):
        return _result("Bank Signature Verification")
    if _is_ach_approval_document(text_lower):
        return _result("ACH Approval Document")
    if _is_foreclosure_letter(text_lower):
        return _result("Foreclosure Letter")
    if _is_payment_favoring_letter(text_lower):
        return _result("Payment Favoring Letter")
    if _is_pre_disbursement_conditions(text_lower):
        return _result("Pre-Disbursement Conditions")
    if _is_charges_deduction_document(text_lower):
        return _result("Charges Deduction Document")
    if _is_otc_pdd_document(text_lower):
        return _result("OTC PDD Document")
    if _is_dual_name_declaration(text_lower):
        return _result("Dual Name Declaration")
    if _is_approval_letter(text_lower):
        return _result("Approval Letter")
    if _is_relationship_proof(text_lower):
        return _result("Relationship Proof")
    if _is_vernacular_document(text_lower):
        return _result("Vernacular Document")
    if _is_agreement_signing_photo(text_lower):
        return _result("Agreement Signing Photo")
    if _is_udyam_certificate(text_lower):
        return _result("Udyam Certificate")
    if _is_gst_certificate(text_lower):
        return _result("GST Certificate")
    if _is_shop_establishment_certificate(text_lower):
        return _result("Shop Establishment Certificate")
    if _is_income_tax_return(text_lower):
        return _result("Income Tax Return")
    if _is_assessed_income_document(text_lower):
        return _result("Assessed Income Document")

    # 20. Application Form
    if _is_application_form(text_lower):
        return _result("Application Form")

    # 18. Unclassified
    return _result("None", confidence=0.0)
