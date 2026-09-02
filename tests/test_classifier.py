"""Tests for services/document_classifier.py.

Each test feeds a representative text snippet into classify_page() and
asserts both the document_type and that confidence == 1.0 (or 0.0 for
the unclassified fallback).
"""


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


def test_credit_approval_memo_is_not_split_into_embedded_kyc_types() -> None:
    text = (
        "CREDIT APPROVAL MEMO | Confidential\n"
        "KYC DOCUMENTS\nCustomer Type\nName\nAadhaar\nPAN\n"
        "Applicant\nPeeru Lal\nXXXXXXXX0001\nTSTAA0001T"
    )
    assert _classify(text) == "CAM"


def test_bank_statement_classified() -> None:
    text = "Bank Statement Account Statement Debit Credit Balance"
    assert _classify(text) == "Bank Statement"


def test_application_bank_table_is_not_a_standalone_bank_statement() -> None:
    text = (
        "A/C HOLDER NAME A/C NUMBER BANK NAME IFSC CODE ACCOUNT TYPE\n"
        "SECURITY & OFFERED PROPERTY\nCO-APPLICANT DETAILS\nUnkar Lal"
    )
    assert _classify(text) != "Bank Statement"


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


def test_nach_payment_narration_is_not_a_mandate_form() -> None:
    text = (
        "Amount Received Mode - NACH Instrument NO-NACH48041510022026 "
        "Instrument Amount 10195 Loan Allocation Amount 10195 "
        "Txn Date 2026-02-10 Value Date 2026-02-10 Receipt No RV1"
    )
    assert _classify(text) != "NACH Form"


def test_premium_calculator_is_unclassified_not_a_form_or_gst_certificate() -> None:
    text = (
        "MS FINCAP PVT LTD - LOAN AGAINST PROPERTY\nPREMIUM CALCULATOR\n"
        "SANCTIONED LOAN AMOUNT (IN RS.)\n6,10,000.00\n"
        "KOTAK PREMIUM WITHOUT GOODS AND SERVICES TAX\n7,765.30\n"
        "GOODS AND SERVICES TAX @ 18%\n1,397.75\nTOTAL PREMIUM\n9,163.05"
    )
    assert _classify(text) == "None"


def test_hindi_notarised_identity_affidavit_is_classified_from_document_form() -> None:
    text = (
        "01 JUL 2026\nNOTARY\nGOVT OF RAJASTHAN\nIDENTIFIED BY\nशपथ-पत्र\n"
        "मैं मोसमी मीना सशपथ बयान करती हूं कि आधार कार्ड में जन्म दिनांक और नाम "
        "सही एवं मान्य है तथा पेन कार्ड में नाम अलग है।\nसत्यापन\nहस्ताक्षर शपथग्रहिता"
    )
    assert _classify(text) == "Affidavit"


def test_agreement_clause_requesting_affidavit_is_not_an_affidavit_document() -> None:
    text = (
        "11. Submit to the Lender a duly attested affidavit confirming that the Borrower "
        "does not appear in a defaulter list. The Borrower shall repay the Facility and "
        "comply with all covenants under this Agreement."
    )
    assert _classify(text) != "Affidavit"


def test_short_nach_substring_inside_ocr_word_is_not_a_nach_form() -> None:
    text = (
        "HOME CONTENTS INSURANCE PROPOSAL\n"
        "Is valuation certificate anached? Sum insured and replacement cost"
    )
    assert _classify(text) != "NACH Form"


def test_property_document_classified() -> None:
    text = "Sale Deed Property Document Registered Deed"
    assert _classify(text) == "Property Document"


def test_griha_raksha_is_property_insurance_not_generic_insurance() -> None:
    text = (
        "Kotak Bharat Griha Raksha Policy Proposal Form\n"
        "covering Home Building and Home Contents against Fire and Allied Perils"
    )
    assert _classify(text) == "Property Insurance Form"


def test_application_form_classified() -> None:
    text = "Loan Application Applicant Name Date of Birth Application Form"
    assert _classify(text) == "Application Form"


def test_health_insurer_application_is_not_a_loan_application_form() -> None:
    text = (
        "Care Health Insurance Limited IRDAI Registration No. 148\n"
        "Group Care 360 Application Form\n"
        "Proposer Details Nominee Details Policy Period Sum Insured Premium\n"
        "Application No. 0030705"
    )

    assert _classify(text) == "Insurance Form"


def test_optional_insurance_section_does_not_override_loan_application() -> None:
    text = (
        "LOAN APPLICATION FORM\nApplicant Details Loan Amount Employment Details\n"
        "Optional insurance: name of insurance company, nominee, policy term, "
        "sum insured and premium\nApplication No: GJ000030765"
    )

    assert _classify(text) == "Application Form"


def test_insurer_words_without_insurance_form_boundary_do_not_override_application() -> None:
    text = (
        "LOAN APPLICATION FORM\nApplicant Name Date of Birth Loan Amount\n"
        "Insurance offered by Care Health Insurance Limited, IRDAI Registration No. 148\n"
        "Nominee Policy Sum Insured Premium"
    )

    assert _classify(text) == "Application Form"


def test_embedded_optional_insurance_subform_does_not_replace_loan_form() -> None:
    text = (
        "LOAN APPLICATION FORM\nApplicant Details Loan Amount Employment Details\n"
        "OPTIONAL INSURANCE APPLICATION FORM\n"
        "Care Health Insurance Limited IRDAI Registration No. 148\n"
        "Proposer Nominee Policy Sum Insured Premium"
    )

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
    assert _classify(text) == "KFS"


def test_kfs_acronym_alone_is_classified() -> None:
    text = "KFS Home Loan APR Tenure"
    assert _classify(text) == "KFS"


def test_application_form_employment_spelling_satisfies_required_any() -> None:
    # Correct spelling alone must pass the required_any gate (typo used to block it).
    from services.document_classifier import _score_rule, load_document_type_registry

    load_document_type_registry.cache_clear()
    rule = next(
        item
        for item in load_document_type_registry()["document_types"]
        if item["type"] == "Application Form"
    )
    text = "Applicant Employment section with Login Date and Channel Type fields"
    scored = _score_rule(text, rule)
    assert any(
        signal.get("value") == "applicant employment" for signal in scored["matched_signals"]
    )
    assert "applicant employment" in rule["required_any"]


def test_crif_classified() -> None:
    text = "CRIF Credit Information Report Credit Score"
    assert _classify(text) == "CRIF Report"
    assert _confidence(text) == 1.0


def test_cibil_classified_separately_from_crif() -> None:
    text = "TransUnion CIBIL Credit Information Report CIBIL Score Control Number"
    assert _classify(text) == "CIBIL Report"


def test_crif_high_mark_not_confused_with_cibil() -> None:
    text = "CRIF High Mark Credit Information Report Credit Score"
    assert _classify(text) == "CRIF Report"


def test_insurance_classified() -> None:
    text = "Life Insurance Policy Sum Assured Nominee Premium"
    assert _classify(text) == "Life Insurance Form"
    assert _confidence(text) == 1.0


def test_insurance_requires_all_three_groups() -> None:
    # Has 'insurance' and type but no policy/sum assured/nominee → not Insurance Form
    text = "Insurance Life Premium only"
    result = _classify(text)
    assert result != "Insurance Form"


def test_account_aggregator_profile_cover_is_bank_statement() -> None:
    text = (
        "Statement From : 27 Jul 2025\nStatement To : 27 Jul 2026\n"
        "Bank : BANK OF BARODA\nAccount Number : XXXX0605\nFI Type : DEPOSIT\n"
        "PROFILE\nName\nDoB\nMobile\nPAN\nCKYC\n"
        "ANUPKUMAR CHETANBHAI\nSUTHAR\n2001-06-18\n"
        "TRANSACTIONS\nTrxn ID\nValue Date\nType\nAmount\nCurrent Balance"
    )

    assert _classify(text) == "Bank Statement"


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
    text = (
        "DEED OF GUARANTEE This Guarantee Deed is executed by the guarantor in favour of the lender"
    )
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
    text = "Sanction Letter Loan Agreement Borrower Lender Sanctioned Amount Tenure Repayment"
    assert _classify(text) == "Sanction Letter"


def test_pan_before_aadhaar() -> None:
    """PAN is priority 1; Aadhaar is priority 2."""
    text = "Permanent Account Number ABCDE1234F Aadhaar UIDAI 1234 5678 9012"
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


def test_hindi_passbook_classified() -> None:
    text = "एचडीएफसी बैंक पासबुक खाता संख्या 1234567890"
    assert _classify(text) == "Passbook"


def test_hindi_sanction_letter_classified() -> None:
    text = "ऋण स्वीकृति पत्र स्वीकृत राशि 500000 अवधि 60 महीने"
    assert _classify(text) == "Sanction Letter"


def test_hindi_consent_letter_classified() -> None:
    text = "ग्राहक सहमति पत्र बीमा अवधि ऋण अवधि"
    assert _classify(text) == "Consent Letter"


# ── KYC checklist context ─────────────────────────────────────────────────────

from services.document_classifier import is_kyc_checklist_context  # noqa: E402


def test_kyc_checklist_context_detected_for_id_enumeration() -> None:
    text = (
        "KYC Documents Collected: Aadhaar Card / PAN Card / Voter ID / "
        "Driving License / Passport (any two)"
    )
    assert is_kyc_checklist_context(text) is True


def test_kyc_checklist_context_detected_for_hindi_enumeration() -> None:
    text = "दस्तावेज़: आधार कार्ड, पैन कार्ड, मतदाता पहचान पत्र, राशन कार्ड"
    assert is_kyc_checklist_context(text) is True


def test_genuine_aadhaar_card_is_not_checklist_context() -> None:
    text = (
        "Unique Identification Authority of India\n"
        "Government of India\nAadhaar 2345 1234 1234\nDOB: 01/01/1990"
    )
    assert is_kyc_checklist_context(text) is False


def test_checklist_page_not_classified_as_identity_card() -> None:
    text = (
        "Documents submitted for KYC verification:\n"
        "1. Aadhaar Card\n2. PAN Card\n3. Voter ID Card\n4. Ration Card\n"
        "Election Commission of India identity proofs accepted."
    )
    assert _classify(text) not in {
        "Aadhaar",
        "PAN",
        "PAN Card",
        "Voter ID",
        "Driving License",
        "Passport",
        "Ration Card",
    }


def test_loan_consent_clause_listing_uidai_is_not_aadhaar() -> None:
    text = (
        "I/We authorise the Company's representatives to collect and verify personal data "
        "from Credit Information Companies (CICs), CKYC, Account Aggregator, UIDAI, "
        "NSDL, SIDBI or any other agency for the purpose of the loan facility.\n"
        "KEY FACT STATEMENT (KFS)\nPART 1 - Interest Rate and Fees/Charges"
    )
    assert _classify(text) == "KFS"


def test_current_address_declaration_mentioning_uidai_is_not_aadhaar() -> None:
    text = (
        "Self-Declaration for Current Address\n"
        "To,\nMS Fincap Private Limited\nDear Sir/Madam,\n"
        "I further declare and confirm that my address as per the OVD / Aadhar is different.\n"
        "I authorize the lender to use my Aadhar number and demographic information "
        "to verify my details from UIDAI."
    )

    assert _classify(text) != "Aadhaar"


def test_opening_guarantee_deed_title_outweighs_body_loan_agreement_reference() -> None:
    result = classify_page(
        "DEED OF GUARANTEE\n"
        "This Deed of Guarantee is executed by the Guarantor in consideration "
        "of the Loan Agreement between the Borrower and the Lender."
    )

    assert result["document_type"] == "Guarantee Deed"
    assert result["confidence"] >= 0.9


def test_compound_loan_agreement_end_use_title_prefers_specific_letter() -> None:
    result = classify_page(
        "LOAN AGREEMENT - END-USE LETTER FROM THE BORROWER\n"
        "Purpose of: Business use\nBorrower: Ramesh Kumar"
    )

    assert result["document_type"] == "End-Use Letter"


def test_compound_facility_disbursal_title_prefers_request() -> None:
    result = classify_page(
        "FACILITY AGREEMENT - REQUEST FOR DISBURSAL\n"
        "Please disburse the sanctioned facility to the beneficiary account."
    )

    assert result["document_type"] == "Disbursement Request"
