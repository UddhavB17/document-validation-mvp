"""Tests for services/field_extractor.py.

Covers all five document types with:
  - Required spec test cases (exact text from the request)
  - Edge cases for Indian currency formatting (1,00,000 / 5,00,000)
  - Tenure normalisation (months vs years)
  - DL expiry flagging
  - Credit-score proximity matching
  - Priority / none-found cases
"""

from __future__ import annotations

import pytest

from services.field_extractor import extract_fields


def test_cam_extracts_only_unambiguous_application_details() -> None:
    text = """CREDIT APPROVAL MEMO
APPLICATION DETAILS
Application Id
RJ000028546
Loan Type
LAP_RAJ
Name
Peeru Lal
Tenure
60
Mobile Number
9000000001
Purpose of Loan
Extension / Renovation Of House
Branch Name
JHALAWAR
Requested Loan Amount
275000.00
Requested IRR
26.00
"""
    result = extract_fields("CAM", text)
    assert result["application_number"] == "RJ000028546"
    assert result["applicant_name"] == "Peeru Lal"
    assert result["phone_number"] == "9000000001"
    assert result["tenure"] == 60
    assert result["requested_amount"] == "275000"
    assert result["roi"] == pytest.approx(26.0)


def test_cam_extracts_person_scoped_mobile_rows() -> None:
    text = """CREDIT APPROVAL MEMO
APPLICATION DETAILS
PERSONAL DETAILS
Applicant
Peeru Lal
9000000001
18-May-1994
32
Coapplicant
Unkar  Lal
9000000002
05-June-1961
65
Coapplicant
Radha  Bai
9000000002
01-January-
1962
64
"""
    records = extract_fields("CAM", text)["person_records"]
    assert records == [
        {"applicant_name": "Peeru Lal", "phone_number": "9000000001", "date_of_birth": "1994-05-18"},
        {"applicant_name": "Unkar Lal", "phone_number": "9000000002", "date_of_birth": "1961-06-05"},
        {"applicant_name": "Radha Bai", "phone_number": "9000000002", "date_of_birth": "1962-01-01"},
    ]


def test_cam_extracts_person_scoped_kyc_address_and_scores() -> None:
    text = """CREDIT APPROVAL MEMO
KYC DOCUMENTS
Applicant
Peeru Lal
XXXXXXXX0001
TSTAA0001T
CoApplicant
Radha  Bai
********0003
TSTCC0003T
ADDRESSES
Applicant
Peeru Lal
Owned
Current
S/O: Unkar Lal, Semlibakta, Rajasthan, India, 326502
Co-Applicant
Radha Bai
Owned
Permanent
W/O: Ukar Lal, Semlibakta, Rajasthan, India, 326502
CREDIT SCORE
Applicant
Peeru Lal
CRIF
786
Coapplicant
Radha Bai
CIBIL
714
Coapplicant
Radha Bai
CRIF
NA
"""
    records = extract_fields("CAM", text)["person_records"]
    assert {"applicant_name": "Peeru Lal", "aadhaar_last4": "0001", "pan_number": "TSTAA0001T"} in records
    assert any(record.get("permanent_address", "").startswith("W/O: Ukar Lal") for record in records)
    assert {"applicant_name": "Peeru Lal", "crif_score": "786"} in records
    assert {"applicant_name": "Radha Bai", "cibil_score": "714"} in records
    assert not any(record.get("crif_score") == "NA" for record in records)


def test_cam_extracts_stacked_sanction_decision_and_repayment_bank_details() -> None:
    text = """CREDIT APPROVAL MEMO
APPLICATION BANK DETAILS
Account Number
11111111111111
REPAYMENT BANK DETAILS
Account Number
83770100000605
IFSC Code
BARB0DBHARA
Account Holder Name
ANUPKUMAR CHETANBHAI SUTHAR
DECISION
Sanction Loan Amount
Sanction Tenure
Advance EMI
Sanction Rate
Sanction EMI
Sanction Date
Sanction Remarks
Username
450000.000000
84
-
21.00
10,266.00
31-July-2026
approved with condition
msfc1500 - Rohit Kumar Banthia
"""

    result = extract_fields("CAM", text)

    assert result["loan_amount"] == "450000"
    assert result["sanction_amount"] == "450000"
    assert result["tenure"] == 84
    assert result["roi"] == pytest.approx(21.0)
    assert result["emi"] == "10266"
    assert result["account_number"] == "83770100000605"
    assert result["ifsc"] == "BARB0DBHARA"
    assert result["account_holder_name"] == "ANUPKUMAR CHETANBHAI SUTHAR"


def test_cam_extracts_sanction_table_when_decision_heading_is_on_previous_page() -> None:
    text = """CREDIT APPROVAL MEMO
Sanction Loan Amount
Sanction Tenure
Advance EMI
Sanction Rate
Sanction EMI
Sanction Date
Sanction Remarks
Username
275000.000000
60
-
26.00
8,234.00
20-June-2026
Case is approved
msfc1063 - Kailash Chandra Jat
SANCTION CONDITIONS
"""

    result = extract_fields("CAM", text)

    assert result["loan_amount"] == "275000"
    assert result["sanction_amount"] == "275000"
    assert result["tenure"] == 60
    assert result["roi"] == pytest.approx(26.0)
    assert result["emi"] == "8234"


def test_application_form_keeps_coapplicant_kyc_rows_person_scoped() -> None:
    text = """CO-APPLICANT KYC DETAILS
APPLICANT NAME
AADHAAR
PAN
Unkar  Lal
XXXXXXXX0002
TSTBB0002T
Not Provided
Radha  Bai
********0003
TSTCC0003T
Not Provided
"""
    result = extract_fields("Application Form", text)
    assert result["pan_number"] is None
    assert result["person_records"] == [
        {"applicant_name": "Unkar Lal", "aadhaar_last4": "0002", "pan_number": "TSTBB0002T"},
        {"applicant_name": "Radha Bai", "aadhaar_last4": "0003", "pan_number": "TSTCC0003T"},
    ]


def test_kfs_extracts_emi_from_monthly_apr_illustration_row() -> None:
    text = """Sanctioned Loan Amount (in Rupees)
275000.00 /-
Type of EMI Amount of each EMI (in Rupees) and nos. of EMIs
Monthly 8234.00 & 60
"""
    assert extract_fields("KFS", text)["emi"] == "8234"


def test_kfs_extracts_recurring_emi_from_repayment_schedule() -> None:
    text = """Repayment Schedule under Equated Periodic Instalment
S No.
Opening Balance
EMI (In Rs.)
Principal
Interest
Closing Balance
1
275000
2582.00
0.00
2582.00
275000
2
275000
8234.00
2276.00
5958.00
272724
3
272724
8234.00
2325.00
5909.00
270399
"""
    assert extract_fields("KFS", text)["emi"] == "8234"


def test_kfs_repayment_summary_and_schedule_rows_are_structured() -> None:
    fields = extract_fields(
        "KFS",
        "Illustration for computation of APR for Retail and MSME loans\n"
        "1. Sanctioned Loan Amount (in Rupees)\n450000.00\n"
        "2. Loan Term (in months)\n84\nMonthly 10266.00 & 84\n"
        "5. Total interest amount to be charged during the entire tenure\n412250.18\n"
        "6. Fee/ Charges payable\n1000.00\n"
        "8. Total amount to be paid by the borrower (sum of 1 and 5)\n862250.18\n"
        "Repayment Schedule EMI (In Rs.) Principal Interest Closing Balance\n"
        "1 450000.00 10266.00 2391.00 7875.00 447609.00\n"
        "2 447609.00 10266.00 2432.84 7833.16 445176.16",
    )

    assert fields["installment_count"] == 84
    assert fields["total_interest"] == 412250.18
    assert fields["total_repayment"] == 862250.18


def test_pan_extracts_name_when_ocr_prefixes_name_label() -> None:
    text = "Permanent Account Number TSTCC0003T HName Radha Bai a9 Date 01/01/1962 of Birth"
    assert extract_fields("PAN", text)["applicant_name"] == "Radha Bai"


def test_pan_extractor_requires_pan_anchor_before_accepting_property_names() -> None:
    text = """Endorsement of Execution
Name: MOHAN LAL Age: 40
The lease deed or allotment order issued by the Gram Panchayat
"""
    assert extract_fields("PAN", text) == {}


def test_aadhaar_xml_keeps_relationship_out_of_physical_address() -> None:
    text = '''<UidData uid="XXXXXXXX0001"><Poi name="Peeru Lal" dob="18-05-1994" gender="M"/><Poa co="S/O: Unkar Lal" lm="mehar basti" loc="semli bakhta" vtc="Semlibakta" dist="Jhalawar" state="Rajasthan" country="India" pc="326502"/></UidData>'''
    result = extract_fields("Aadhaar", text)
    assert result["applicant_name"] == "Peeru Lal"
    assert result["relationship_qualifier"] == "S/O"
    assert result["related_person_name"] == "Unkar Lal"
    assert result["address"] == "mehar basti, semli bakhta, Semlibakta, Jhalawar, Rajasthan, India, 326502"


def test_crif_address_variation_row_is_not_applicant_name() -> None:
    text = """Address Variations
MEHAR BASTI SEMALI BAKHATA ..... 326502 RJ
Employment details
Account Information
"""
    result = extract_fields("CRIF Report", text)
    assert result.get("applicant_name") is None


def test_crif_extracts_subject_name_from_report_header() -> None:
    text = """CRIF HIGH MARK
Credit Information Report
For PEERU LAL
Inquiry Input Information
Name: PEERU LAL DOB/Age: 18-05-1994 Gender: MALE
CRIF HM Score(S):
SCORE NAME RANGE SCORE
PERFORM CONSUMER 2.2 300-900 786
"""
    result = extract_fields("CRIF Report", text)
    assert result["applicant_name"] == "PEERU LAL"
    assert result["credit_score"] == "786"


def test_bank_statement_extractor_blocks_amortization_schedule() -> None:
    text = """Repayment Schedule under Equated Periodic Instalment
S No. Opening Balance EMI (In Rs.) Principal Interest Closing Balance
15 241248 8234.00 3007.00 5227.00 238241
"""
    result = extract_fields("Bank Statement", text)
    assert result == {"_validation_blocked_reason": "amortization_schedule_not_bank_statement"}


def test_bank_statement_extracts_account_from_stacked_sbi_header() -> None:
    text = """STATE BANK OF INDIA
Name: Mrs.
RADHA
S/0/H/0 : UNKAR LAL
CIF Number:
Account No.:
A/C Type
Address
71216839034
38 TINY SPL OD GEN PUB IND
: SEMALI BAKHATA
61246812678
SEMALI BAKHATA
Code: 31270
IFSC: SBIN0031270
"""

    result = extract_fields("Bank Statement", text)

    assert result["account_number"] == "61246812678"


def test_passbook_extracts_shri_account_holder_name() -> None:
    text = """PUNJAB NATIONAL BANK
Account Particulars
A/C No.: 0071000100264386
SHRI PEERU LAL
IFSC Code: PUNB0007100
"""
    result = extract_fields("Passbook", text)
    assert result["account_holder_name"] == "PEERU LAL"
    assert result["account_number"] == "0071000100264386"


@pytest.mark.parametrize(
    "candidate",
    ["Semali Bakhata", "C/O", "S/O", "F/O", "Applicant Name"],
)
def test_name_extraction_rejects_non_person_candidates(candidate: str) -> None:
    text = f"APPLICATION DETAILS\nApplicant Name\n{candidate}\nMobile Number\n9000000001"
    result = extract_fields("Application Form", text)
    assert result.get("applicant_name") is None


def test_aadhaar_extracts_devanagari_name_after_hindi_label() -> None:
    text = "भारत सरकार\nनाम\nराम लाल\nजन्म तिथि 01/01/1990\n"
    assert extract_fields("Aadhaar", text)["applicant_name"] == "राम लाल"


def test_voter_id_skips_bilingual_labels_and_extracts_cardholder() -> None:
    text = """भारत निर्वाचन आयोग
ELECTION COMMISSION OF INDIA
निर्वाचक का नाम
ELECTOR'S NAME
पति का नाम
HUSBAND'S NAME
लिंग / Sex
जन्म की तारीख
DATE OF BIRTH
राधा बाई
RADHA BAI
उकार लाल
UNKAR LAL
FEMALE
"""

    assert extract_fields("Voter ID", text)["applicant_name"] == "RADHA BAI"


@pytest.mark.parametrize(
    "text",
    [
        "APPLICANT KYC DETAILS\nAPPLICANT NAME\nAADHAAR\n1234 5678 9012",
        "GUARANTOR KYC DETAILS\nAPPLICANT NAME\nAADHAAR\nNot Provided",
    ],
)
def test_aadhaar_extractor_rejects_application_form_kyc_tables(text: str) -> None:
    assert extract_fields("Aadhaar", text) == {}


def test_digilocker_aadhaar_label_first_layout_uses_value_block() -> None:
    text = """DigiLocker verified e-Aadhaar
This document is generated from verified Aadhaar XML
Masked Aadhaar number
Name
Date of Birth
Gender
c/o , s/o
Address
Landmark
Locality
City / District
Pin Code
State
xxxxxxxx0001
semli bakhta
2026-06-11T14:31:29.346+05:30
2026-06-11T14:31:29.346+05:30
Peeru Lal
18-05-1994
Male
S/O: Unkar Lal
326502
Rajasthan
S/O: Unkar Lal,mehar basti,semli
bakhta,Semlibakta,Pachpahar,Sulia,Jhalawar,R
ajasthan,326502
Jhalawar
Pachpahar
"""

    result = extract_fields("Aadhaar", text)

    assert result["applicant_name"] == "Peeru Lal"
    assert result["aadhaar_last4"] == "0001"
    assert result["dob"] == "1994-05-18"
    assert result["related_person_name"] == "Unkar Lal"
    assert result["relationship_qualifier"] == "S/O"
    assert result["pin_code"] == "326502"
    assert result["address"].startswith("mehar basti")


def test_aadhaar_number_does_not_join_unrelated_numbers_across_lines() -> None:
    text = """Unique Identification Authority of India
1947
1800 300 1947
9999 8888 0003
"""

    assert extract_fields("Aadhaar", text)["aadhaar_number"] == "999988880003"


def test_bank_approval_does_not_assign_employee_signature_mobile_to_customer() -> None:
    text = """Request for Approval - new bank accounts
A/c No.: 0071000100264386
Name: Mr. Peeru Lal
E NACH done
Designation: BM | Department: Sales
Mobile: 9166511960
"""
    result = extract_fields("Bank Statement", text)
    assert result["phone_number"] is None
    assert result["nach_status"] == "done"


def test_utility_bill_extracts_flattened_inline_address_without_billing_month_as_pin() -> None:
    text = "ONKAR LAL S/O KANMA MEHAR SEMLI BAKTA SEMLI BAKTA 202606 10026 09-06-2026"
    result = extract_fields("Utility Bill", text)
    assert result["address"] == "S/O KANMA MEHAR SEMLI BAKTA SEMLI BAKTA"
    assert result["pin_code"] is None
    assert result["bill_date"] == "2026-06-09"


def test_application_extracts_coapplicant_table_rows() -> None:
    text = """CO-APPLICANT DETAILS
Unkar  Lal
05-June-
1961
Kanha
9000000002
FATHER
No
Radha  Bai
01-January-
1962
Ukar Lal
9000000003
MOTHER
No
"""
    records = extract_fields("Application Form", text)["person_records"]
    assert [record["applicant_name"] for record in records] == ["Unkar Lal", "Radha Bai"]
    assert [record["phone_number"] for record in records] == ["9000000002", "9000000003"]


def test_cersai_uses_debtor_pan_not_cersai_corporate_pan() -> None:
    text = """Debtor Based Search Report
CERSAI Details
PAN
AAECC5770G
Search Reference Number
4186439765923
Search Criteria Entered
Name of the Debtor
PEERU LAL
PAN
TSTAA0001T
Date Of Birth
1994-12-05
Search Output Details
No Match Found
"""
    result = extract_fields("CERSAI Report", text)
    assert result["cersai_search_type"] == "debtor_based"
    assert result["debtor_name"] == "PEERU LAL"
    assert result["debtor_pan_number"] == "TSTAA0001T"
    assert result["applicant_name"] == "PEERU LAL"
    assert result["pan_number"] == "TSTAA0001T"
    assert result["date_of_birth"] == "1994-12-05"


def test_asset_cersai_does_not_expose_cersai_corporate_pan_as_borrower_pan() -> None:
    result = extract_fields(
        "CERSAI Report",
        "Asset Based Search Report\nCERSAI Details\nPAN\nAAECC5770G\nSearch Criteria Entered\nAsset Category\nImmovable",
    )
    assert result["cersai_search_type"] == "asset_based"
    assert result["debtor_name"] is None
    assert result["debtor_pan_number"] is None
    assert result["pan_number"] is None


def test_cersai_debtor_extraction_ignores_people_in_search_output() -> None:
    result = extract_fields(
        "CERSAI Report",
        """Debtor Based Search Report
CERSAI Details
PAN
AAECC5770G
Search Criteria Entered
Name of the Debtor
RADHA BAI
PAN
TSTCC0003T
Search Output Details
Applicant PEERU LAL PAN TSTAA0001T
Co-Applicant UNKAR LAL PAN TSTBB0002T
""",
    )

    assert result["debtor_name"] == "RADHA BAI"
    assert result["debtor_pan_number"] == "TSTCC0003T"
    assert result["applicant_name"] == "RADHA BAI"
    assert result["pan_number"] == "TSTCC0003T"


def test_pdc_counts_unique_cheque_numbers_from_repeated_ocr() -> None:
    result = extract_fields(
        "PDC",
        '"865981"326024025 "865982"326024025 "865983"326024025 865981326024025',
    )
    assert result["cheque_numbers"] == ["865981", "865982", "865983"]
    assert result["cheque_count"] == 3


def test_cheque_extracts_printed_signature_holder_instead_of_bank_name() -> None:
    result = extract_fields(
        "Cheque",
        """PAY
State Bank Of India
Alc No
41249946368
Mr. Kala Singh
Please sign abovs
""",
    )

    assert result["account_holder_name"] == "Kala Singh"
    assert result["account_number"] == "41249946368"


# ════════════════════════════════════════════
# SANCTION LETTER
# ════════════════════════════════════════════

class TestSanctionLetter:

    def _extract(self, text: str) -> dict:
        return extract_fields("Sanction Letter", text)

    # ── Spec test cases ───────────────────────

    def test_loan_amount_extracted_from_sanction(self) -> None:
        """Spec: 'Sanctioned Amount: Rs. 5,00,000' → loan_amount='500000'"""
        result = self._extract("Sanctioned Amount: Rs. 5,00,000")
        assert result["loan_amount"] == "500000"

    def test_tenure_extracted_as_months(self) -> None:
        """Spec: 'Loan Tenure: 60 Months' → tenure=60"""
        result = self._extract("Loan Tenure: 60 Months")
        assert result["tenure"] == 60

    def test_emi_extracted(self) -> None:
        """Spec: 'EMI Amount: Rs. 10,500' → emi='10500'"""
        result = self._extract("EMI Amount: Rs. 10,500")
        assert result["emi"] == "10500"

    # ── Additional sanction letter tests ─────

    def test_loan_amount_via_loan_amount_label(self) -> None:
        result = self._extract("Loan Amount: ₹ 10,00,000")
        assert result["loan_amount"] == "1000000"

    def test_loan_amount_via_amount_sanctioned(self) -> None:
        result = self._extract("Amount Sanctioned: 750000")
        assert result["loan_amount"] == "750000"

    def test_tenure_in_years_normalised_to_months(self) -> None:
        result = self._extract("Tenure: 5 Years")
        assert result["tenure"] == 60

    def test_tenure_bare_number(self) -> None:
        result = self._extract("Loan Tenure: 240")
        assert result["tenure"] == 240

    def test_roi_extracted(self) -> None:
        result = self._extract("Rate of Interest: 8.5%")
        assert result["roi"] == pytest.approx(8.5)

    def test_roi_via_roi_label(self) -> None:
        result = self._extract("ROI: 9.25%")
        assert result["roi"] == pytest.approx(9.25)

    def test_applicant_name_after_borrower(self) -> None:
        text = "Borrower\nRavi Kumar\nLoan Amount: 500000"
        result = self._extract(text)
        assert result["applicant_name"] == "Ravi Kumar"

    def test_applicant_name_after_applicant_name_label(self) -> None:
        text = "Applicant Name: Sunita Sharma\nLoan Tenure: 120 Months"
        result = self._extract(text)
        assert result["applicant_name"] == "Sunita Sharma"

    def test_missing_fields_return_none(self) -> None:
        result = self._extract("This letter confirms your loan.")
        assert result["loan_amount"] is None
        assert result["tenure"] is None
        assert result["emi"] is None
        assert result["roi"] is None

    def test_cross_match_field_names_present(self) -> None:
        """Verify exact field names required by checklist_engine are all present."""
        result = self._extract(
            "Sanctioned Amount: Rs. 20,00,000\n"
            "Tenure: 180 Months\n"
            "EMI: Rs. 22,000\n"
            "Rate of Interest: 8.75%"
        )
        assert "loan_amount" in result
        assert "tenure" in result
        assert "emi" in result
        assert "roi" in result

    def test_loan_amount_type_is_string_of_digits(self) -> None:
        result = self._extract("Sanctioned Amount: 5,00,000")
        assert isinstance(result["loan_amount"], str)
        assert result["loan_amount"].isdigit()

    def test_tenure_type_is_int(self) -> None:
        result = self._extract("Tenure: 60 Months")
        assert isinstance(result["tenure"], int)

    def test_roi_type_is_float(self) -> None:
        result = self._extract("Rate of Interest: 10%")
        assert isinstance(result["roi"], float)


# ════════════════════════════════════════════
# LOAN AGREEMENT
# ════════════════════════════════════════════

class TestLoanAgreement:

    def _extract(self, text: str) -> dict:
        return extract_fields("Loan Agreement", text)

    def test_loan_amount_extracted(self) -> None:
        result = self._extract("Loan Amount: Rs. 15,00,000")
        assert result["loan_amount"] == "1500000"

    def test_tenure_months(self) -> None:
        result = self._extract("Loan Tenure: 120 Months")
        assert result["tenure"] == 120

    def test_tenure_years(self) -> None:
        result = self._extract("Tenure: 10 Years")
        assert result["tenure"] == 120

    def test_emi_extracted(self) -> None:
        result = self._extract("EMI: Rs. 18,000")
        assert result["emi"] == "18000"

    def test_borrower_name_extracted(self) -> None:
        text = "Borrower: Amol Patil\nLender: ABC Finance Ltd"
        result = self._extract(text)
        assert result["borrower_name"] == "Amol Patil"

    def test_cross_match_field_names_same_as_sanction(self) -> None:
        """loan_amount / tenure / emi / roi names must match Sanction Letter."""
        result = self._extract(
            "Loan Amount: 500000\nTenure: 60 Months\nEMI: 9000\nROI: 8.5%"
        )
        for key in ("loan_amount", "tenure", "emi", "roi"):
            assert key in result


def test_kfs_uses_loan_detail_extractor() -> None:
    result = extract_fields(
        "KFS",
        "Key Fact Statement\nLoan Amount: Rs. 5,00,000\nTenure: 60 months\nROI: 9.5%\nEMI: 10500",
    )
    assert result["loan_amount"] == "500000"
    assert result["tenure"] == 60
    assert result["roi"] == pytest.approx(9.5)


def test_stamp_duty_extracts_stamp_date() -> None:
    result = extract_fields("Stamp Duty", "e-Stamp Certificate\nStamp Date: 12/07/2026")
    assert result["stamp_date"] == "2026-07-12"


def test_stamp_duty_extracts_jurisdiction_certificate_and_amounts() -> None:
    result = extract_fields(
        "Stamp Duty",
        "\n".join(
            [
                "Government of Gujarat",
                "Certificate No: GJ-12345",
                "Certificate Issued Date: 02/04/2025",
                "Account Reference: ACC-9988",
                "Unique Doc. Reference: UDR-5566",
                "Purchased by: ABC Finance Limited",
                "Description of Document: Article 5(h) Agreement - Loan Agreement",
                "Consideration Price (Rs.): 500000",
                "First Party: Ramesh Kumar",
                "Second Party: ABC Finance Limited",
                "Stamp Duty Amount (Rs.): 300",
            ]
        ),
    )
    assert result["stamp_jurisdiction_state"] == "Gujarat"
    assert result["stamp_certificate_number"] == "GJ-12345"
    assert result["stamp_unique_document_reference"] == "UDR-5566"
    assert result["stamp_article"] == "5(h)"
    assert result["stamp_consideration_amount"] == "500000"
    assert result["stamp_duty_amount"] == "300"
    assert result["stamp_date"] == "2025-04-02"


def test_crif_zero_score_is_extracted() -> None:
    result = extract_fields("CRIF Report", "CRIF Credit Information Report Credit Score: 0")
    assert result["credit_score"] == "0"


def test_crif_blank_score_table_with_zero_accounts_is_normalized_to_no_score() -> None:
    result = extract_fields(
        "CRIF Report",
        """CRIF HM Score(S):
SCORE NAME
RANGE
SCORE
Description
Account Summary
Number
of
Accounts
Active Accounts Overdue Accounts Secured Accounts
0 0 0 0
Group Account Summary
""",
    )
    assert result["credit_score"] == "0"
    assert result["crif_score"] == "0"


def test_crif_blank_score_table_with_accounts_remains_missing() -> None:
    result = extract_fields(
        "CRIF Report",
        """CRIF HM Score(S):
SCORE NAME RANGE SCORE Description
Account Summary
Number of Accounts Active Accounts Overdue Accounts
2 1 0
Group Account Summary
""",
    )
    assert result["credit_score"] is None
    assert result["crif_score"] is None


def test_cibil_minus_one_insufficient_history_is_normalized_to_no_score() -> None:
    result = extract_fields(
        "CIBIL Report",
        """CIBIL COMBO REPORT
SCORE
Score Name
Score
Scoring Factors
CREDITVISION SCORE
-1
1. Insufficient history to score
""",
    )
    assert result["credit_score"] == "0"
    assert result["cibil_score"] == "0"


def test_end_use_letter_extracts_purpose_for_json_comparison() -> None:
    result = extract_fields(
        "End-Use Letter",
        "END-USE LETTER FROM THE BORROWER\nRef.: GJ000030765\n"
        "The said Loan is for the purpose of: Business Use and\nRunning Loan Closer\n"
        "I / We hereby confirm the purpose is valid.",
    )
    assert result["application_number"] == "GJ000030765"
    assert result["loan_purpose"] == "Business Use and Running Loan Closer"


def test_clearance_report_prefers_negative_status() -> None:
    result = extract_fields(
        "Legal Clearance Report",
        "Legal status is not cleared. Approval remains pending.",
    )
    assert result["clearance_status"] == "not cleared"


def test_nach_extracts_not_registered_before_registered_substring() -> None:
    result = extract_fields("NACH Form", "NACH is not registered for Account No: 1234567890")
    assert result["registration_status"] == "not registered"
    assert result["account_number"] == "1234567890"

    def test_unknown_document_type_returns_empty(self) -> None:
        result = extract_fields("Unknown Document", "some text")
        assert result == {}


def test_utility_bill_extracts_address_proof_fields() -> None:
    result = extract_fields(
        "Utility Bill",
        "\n".join([
            "Electricity Bill",
            "Consumer Name: Ramesh Kumar",
            "Service Address",
            "12 Market Road",
            "Delhi 110001",
            "Bill Date: 01/07/2026",
            "Due Date: 15/07/2026",
        ]),
    )

    assert result["applicant_name"] == "Ramesh Kumar"
    assert result["address"] == "12 Market Road Delhi 110001"
    assert result["pin_code"] == "110001"


def test_passport_extracts_machine_readable_identity_fields() -> None:
    result = extract_fields(
        "Passport",
        """REPUBLIC OF INDIA PASSPORT
Passport No: A1234567
Surname: KUMAR
Given Names: RAVI
Nationality: INDIAN
Date of Birth: 12/03/1990
Place of Birth: JAIPUR
Date of Issue: 01/02/2020
Date of Expiry: 31/01/2030
Place of Issue: JAIPUR
P<INDKUMAR<<RAVI
""",
    )

    assert result["passport_number"] == "A1234567"
    assert result["applicant_name"] == "RAVI KUMAR"
    assert result["dob"] == "1990-03-12"
    assert result["date_of_expiry"] == "2030-01-31"


def test_passbook_transaction_pages_supply_three_month_period() -> None:
    result = extract_fields(
        "Passbook",
        """PASSBOOK Account Number 123456789012
Transaction Date Narration Debit Credit Balance
05/05/2026 Opening 0 0 1000
10/06/2026 Deposit 0 500 1500
31/07/2026 Transfer 100 0 1400
""",
    )

    assert result["statement_period_start"] == "2026-05-05"
    assert result["statement_period_end"] == "2026-07-31"


def test_insurance_signature_requires_affirmative_completion_evidence() -> None:
    blank = extract_fields(
        "Life Insurance Form",
        "Life Insurance Proposal Form\nProposer Name: Ravi Kumar\nSignature of Proposer: ____",
    )
    signed = extract_fields(
        "Life Insurance Form",
        "Life Insurance Proposal Form\nProposer Name: Ravi Kumar\nDigitally signed by Ravi Kumar",
    )

    assert blank["signature_present"] is None
    assert signed["signature_present"] is True


def test_fi_crime_udyam_and_shop_fields_are_extracted() -> None:
    fi = extract_fields(
        "FI Report",
        "FIELD INVESTIGATION REPORT\nApplicant Name: Ravi Kumar\n"
        "Verification Status: Positive\nVisit Date: 01/08/2026",
    )
    crime = extract_fields(
        "Crime Check Report",
        "CRIME CHECK REPORT\nSubject Name: Ravi Kumar\nNo adverse record\nApproved by Credit",
    )
    udyam = extract_fields(
        "Udyam Certificate",
        "UDYAM REGISTRATION CERTIFICATE\nUDYAM-RJ-12-1234567\n"
        "Name of Enterprise: Ravi Traders\nDate of Udyam Registration: 01/07/2026",
    )
    shop = extract_fields(
        "Shop Establishment Certificate",
        "GUMASTA CERTIFICATE\nRegistration No: RJ-123\n"
        "Name of Establishment: Ravi Traders\nNature of Business: Retail",
    )

    assert fi["fi_report_status"] == "positive"
    assert crime["report_status"] == "clear"
    assert crime["credit_approval_status"] == "approved"
    assert udyam["udyam_registration_number"] == "UDYAM-RJ-12-1234567"
    assert shop["registration_number"] == "RJ-123"


def test_pdc_extractor_counts_multiple_leaves_and_preserves_owners() -> None:
    result = extract_fields(
        "PDC",
        """A/C No: 111111111111
Account Holder: Ravi Kumar
Cheque No: 000001
000001 123456789
A/C No: 222222222222
Account Holder: Neha Kumar
Cheque No: 000002
000002 987654321
""",
    )

    assert result["cheque_numbers"] == ["000001", "000002"]
    assert result["cheque_count"] == 2
    assert {leaf["account_number"] for leaf in result["pdc_leaves"]} == {
        "111111111111", "222222222222"
    }


def test_utility_bill_does_not_treat_billing_month_as_pin_code() -> None:
    result = extract_fields(
        "Utility Bill",
        "ONKAR LAL S/O KANHA MEHAR SEMLI BAKTA 202606 10026 5 BAKTA",
    )
    assert result["applicant_name"] == "ONKAR LAL"
    assert result["pin_code"] is None


def test_aadhaar_address_stops_at_first_pin_code() -> None:
    result = extract_fields(
        "Aadhaar",
        "Unique Identification Authority of India Address: W/O: Ukar Lal, Semlibakta, Jhalawar, Rajasthan 326502 9999 8888 0003 help@uidai.gov.in",
    )
    assert result["address"] == "W/O: Ukar Lal, Semlibakta, Jhalawar, Rajasthan 326502"


# ════════════════════════════════════════════
# PAN
# ════════════════════════════════════════════

class TestPAN:

    def _extract(self, text: str) -> dict:
        return extract_fields("PAN", text)

    def test_pan_number_extracted(self) -> None:
        result = self._extract("INCOME TAX DEPARTMENT\nName: Ramesh Kumar\nABCDE1234F")
        assert result["pan_number"] == "ABCDE1234F"

    def test_pan_card_alias_supported(self) -> None:
        result = extract_fields("PAN Card", "Permanent Account Number ABCDE1234F")
        assert result["pan_number"] == "ABCDE1234F"

    def test_applicant_name_extracted(self) -> None:
        result = self._extract("Name: Priya Mehta\nDate of Birth: 01/01/1990\nABCDE1234F")
        assert result["applicant_name"] == "Priya Mehta"
        assert result["dob"] == "1990-01-01"

    def test_missing_pan_returns_none(self) -> None:
        result = self._extract("Income Tax Department")
        assert result["pan_number"] is None

    def test_inline_bilingual_pan_card_extracts_name_and_dob(self) -> None:
        result = self._extract(
            "Permanent TSTCC0003T Account Number नामWName Radha Bai "
            "जम fafuDate 01701/1962 ofBnu"
        )
        assert result["applicant_name"] == "Radha Bai"
        assert result["dob"] == "1962-01-01"


# ════════════════════════════════════════════
# AADHAAR
# ════════════════════════════════════════════

class TestAadhaar:

    def _extract(self, text: str) -> dict:
        return extract_fields("Aadhaar", text)

    def test_aadhaar_number_extracted(self) -> None:
        result = self._extract("Government of India\nName: Sunita Sharma\n1234 5678 9012")
        assert result["aadhaar_number"] == "123456789012"

    def test_dob_and_address_extracted(self) -> None:
        text = "DOB: 15/08/1985\nAddress\n12 Main Street\nPune 411001"
        result = self._extract(text)
        assert result["dob"] == "1985-08-15"
        assert "Main Street" in result["address"]

    def test_digitally_signed_xml_uses_holder_poa_not_certificate_address(self) -> None:
        text = (
            '<UidData uid="xxxxxxxx0001"><Poi dob="18-05-1994" gender="M" name="Peeru Lal"/>'
            '<Poa co="S/O: Unkar Lal" country="India" dist="Jhalawar" pc="326502" '
            'state="Rajasthan" street="mehar basti" vtc="Semlibakta"/>'
            '<X509SubjectName>postalCode=110003,O=DIGITAL INDIA CORPORATION</X509SubjectName>'
        )
        result = self._extract(text)
        assert result["applicant_name"] == "Peeru Lal"
        assert result["aadhaar_last4"] == "0001"
        assert result["relationship_qualifier"] == "S/O"
        assert result["address"].startswith("mehar basti")
        assert "DIGITAL INDIA" not in result["address"]
        assert result["related_person_name"] == "Unkar Lal"

    def test_xml_back_without_poi_uses_poa_before_signature_metadata(self) -> None:
        text = (
            '<UidData uid="xxxxxxxx1641"><Poa co="W/O: Kala Singh" country="India" '
            'dist="Ganganagar" loc="v p o 27 f kaminpura" pc="335027" '
            'state="Rajasthan"/><LData co="W/O: Kala Singh" name="Seeta" pc="335027"/>'
            '<X509SubjectName>postalCode=110003,O=DIGITAL INDIA</X509SubjectName>'
        )

        result = self._extract(text)

        assert result["applicant_name"] == "Seeta"
        assert result["pin_code"] == "335027"
        assert result["relationship_qualifier"] == "W/O"
        assert result["related_person_name"] == "Kala Singh"
        assert "110003" not in result["address"]

    def test_signed_xml_appendix_is_audit_evidence_not_a_field_source(self) -> None:
        text = (
            "Digitally signed e-Aadhaar XML\n"
            '<UidData uid="xxxxxxxx1641"><Poa co="W/O: Kala Singh" country="India" '
            'dist="Ganganagar" pc="335027" state="Rajasthan"/></UidData>\n'
            "CN=DS DIGITAL INDIA CORPORATION 3,postalCode=110003,O=DIGITAL INDIA\n"
            "<SignatureValue>signed-value</SignatureValue>"
        )

        result = self._extract(text)

        assert result == {"_aadhaar_verification_appendix": True}


# ════════════════════════════════════════════
# VOTER ID
# ════════════════════════════════════════════

class TestVoterID:

    def _extract(self, text: str) -> dict:
        return extract_fields("Voter ID", text)

    def test_voter_id_number_extracted(self) -> None:
        """Spec: text with 'ABC1234567' → voter_id_number='ABC1234567'"""
        result = self._extract("EPIC No: ABC1234567\nName: Priya Mehta")
        assert result["voter_id_number"] == "ABC1234567"

    def test_voter_id_number_different_value(self) -> None:
        result = self._extract("Voter ID: XYZ9876543")
        assert result["voter_id_number"] == "XYZ9876543"

    def test_applicant_name_after_name(self) -> None:
        text = "Name: Ravi Kumar\nDOB: 01/01/1990"
        result = self._extract(text)
        assert result["applicant_name"] == "Ravi Kumar"

    def test_applicant_name_after_electors_name(self) -> None:
        text = "Elector's Name\nSunita Sharma"
        result = self._extract(text)
        assert result["applicant_name"] == "Sunita Sharma"

    def test_dob_extracted(self) -> None:
        result = self._extract("Date of Birth: 15/08/1985\nABC1234567")
        assert result["dob"] == "1985-08-15"

    def test_address_extracted(self) -> None:
        text = "Address\n12 Main Street\nPune 411001"
        result = self._extract(text)
        assert result["address"] is not None
        assert "Main Street" in result["address"]

    def test_no_voter_id_number_returns_none(self) -> None:
        result = self._extract("Election Commission of India")
        assert result["voter_id_number"] is None


# ════════════════════════════════════════════
# DRIVING LICENSE
# ════════════════════════════════════════════

class TestDrivingLicense:

    def _extract(self, text: str) -> dict:
        return extract_fields("Driving License", text)

    def test_dl_validity_extracted(self) -> None:
        """Spec: 'Valid Till: 01/01/2030' → validity_date='2030-01-01'"""
        result = self._extract(
            "Driving Licence\nName: Rahul Joshi\nValid Till: 01/01/2030"
        )
        assert result["validity_date"] == "2030-01-01"

    def test_dl_number_extracted(self) -> None:
        # Valid DL format: 2 letters + 2 digits + 11 digits = 15 chars total
        result = self._extract("DL No: MH0112345678901\nValid Till: 01/01/2030")
        assert result["dl_number"] is not None

    def test_dl_number_exact_format(self) -> None:
        result = self._extract("Licence No: MH0112345678901")
        assert result["dl_number"] == "MH0112345678901"

    def test_expired_dl_flagged(self) -> None:
        result = self._extract("Valid Till: 01/01/2020\nName: Old Driver")
        assert result["is_expired"] is True

    def test_valid_dl_not_flagged(self) -> None:
        result = self._extract("Valid Till: 01/01/2040\nName: Future Driver")
        assert result["is_expired"] is False

    def test_dob_extracted(self) -> None:
        result = self._extract("DOB: 10/05/1990\nValid Till: 01/01/2030")
        assert result["dob"] == "1990-05-10"

    def test_issue_date_is_not_used_as_dob(self) -> None:
        result = self._extract(
            "Driving Licence\nDate of Issue: 10/05/2020\n"
            "Date of Birth: 10/05/1990\nValid Till: 01/01/2030"
        )
        assert result["date_of_issue"] == "2020-05-10"
        assert result["dob"] == "1990-05-10"

    def test_issue_date_alone_does_not_create_dob(self) -> None:
        result = self._extract(
            "Driving Licence\nDate of Issue: 10/05/2020\nValid Till: 01/01/2030"
        )
        assert result["date_of_issue"] == "2020-05-10"
        assert result["dob"] is None

    def test_dob_survives_interleaved_blood_group_column(self) -> None:
        result = self._extract(
            """UNION OF INDIA Driving Licence
RJ13 20240001114
Date of Issue
er/Validity
27/11/2034
21/02/2024
Date of Birth
Blood Group
Unknown
28/11/1994
नाम / Name
KULDEEP SINGH
"""
        )

        assert result["dob"] == "1994-11-28"
        assert result["validity_date"] == "2034-11-27"

    def test_dob_block_stops_before_next_identity_field(self) -> None:
        result = self._extract(
            "Driving Licence\nDate of Birth\nBlood Group\nUnknown\n"
            "Name\nRahul Joshi\nDate of Issue\n21/02/2024"
        )

        assert result["dob"] is None

    def test_address_stops_before_next_dl_field(self) -> None:
        result = self._extract(
            "Driving Licence\nAddress\n12 Main Street\nPune 411001\n"
            "Date of Issue\n10/05/2020"
        )
        assert result["address"] == "12 Main Street Pune 411001"

    def test_applicant_name_extracted(self) -> None:
        text = "Name: Meera Singh\nValid Till: 31/12/2029"
        result = self._extract(text)
        assert result["applicant_name"] == "Meera Singh"

    def test_no_dl_number_returns_none(self) -> None:
        result = self._extract("Driving Licence Valid Till: 01/01/2030")
        assert result["dl_number"] is None


# ════════════════════════════════════════════
# CRIF REPORT
# ════════════════════════════════════════════

class TestCRIFReport:

    def _extract(self, text: str) -> dict:
        return extract_fields("CRIF Report", text)

    def test_crif_score_extracted(self) -> None:
        """Spec: text with 'Credit Score: 742' → credit_score='742'"""
        result = self._extract("Credit Score: 742")
        assert result["credit_score"] == "742"

    def test_score_extracted_via_score_label(self) -> None:
        result = self._extract("Score: 685\nReport Generated: 01/06/2025")
        assert result["credit_score"] == "685"

    def test_score_must_be_3_digit(self) -> None:
        # Ensure 4-digit numbers near "score" are not captured
        result = self._extract("Score: 1234")
        assert result["credit_score"] is None or len(result["credit_score"]) == 3

    def test_report_date_near_report_generated(self) -> None:
        result = self._extract("Report Generated: 15/03/2025\nScore: 720")
        assert result["report_date"] == "2025-03-15"

    def test_report_date_near_as_on(self) -> None:
        result = self._extract("As On: 01/01/2025\nCredit Score: 750")
        assert result["report_date"] == "2025-01-01"

    def test_applicant_name_extracted(self) -> None:
        text = "Applicant Name: Vikram Nair\nCredit Score: 790"
        result = self._extract(text)
        assert result["applicant_name"] == "Vikram Nair"

    def test_no_score_returns_none(self) -> None:
        result = self._extract("CRIF Report with no score information")
        assert result["credit_score"] is None

    def test_bureau_columns_are_not_current_loan_fields(self) -> None:
        result = self._extract(
            "Consumer Name:\nRADHA BAI\nBRANCH ID:\nBRANCH3217\n"
            "APR MAR MAY\nSanctioned Amount: 285,000"
        )
        assert "branch" not in result
        assert "apr" not in result
        assert "sanction_amount" not in result


def test_bilingual_loan_table_extracts_actual_values() -> None:
    result = extract_fields(
        "Loan Agreement",
        "Amount of Facility (in Rs.)\nऋण राशि\n275000.00\n"
        "Term or Tenure\nअवधि\n60\nRate of Interest\nब्याज\n26.00 %\n"
        "EMI Amount* (in Rs.)\nईएमआई\n8234.00",
    )
    assert result["loan_amount"] == "275000"
    assert result["tenure"] == 60
    assert result["roi"] == pytest.approx(26.0)
    assert result["emi"] == "8234"


def test_kfs_does_not_use_unrelated_percentage_as_roi() -> None:
    result = extract_fields("KFS", "Disbursement in Stages or 100% upfront")
    assert result["roi"] is None


def test_bilingual_application_form_extracts_primary_values_not_header_phone() -> None:
    result = extract_fields(
        "Application Form",
        "Ph.: 9374200200\nAPPLICATION DETAILS\nLOAN AMOUNT\nऋण राशि\n275000.00 /-\n"
        "APPLICANT DETAILS\nNAME\nनाम\nPeeru Lal\nDATE OF BIRTH\nजन्म\n18-May-1994",
    )
    assert result["applicant_name"] == "Peeru Lal"
    assert result["date_of_birth"] == "1994-05-18"
    assert result["loan_amount"] == "275000"
    assert result["phone_number"] is None


def test_application_form_supports_residential_address_aliases() -> None:
    result = extract_fields(
        "Application Form",
        "Current Resi. Address: B-402 Pandit Dindayal Nagar, Hathijan, Ahmedabad 382445\n"
        "Permanent Resi. Address: 81 Modi Vas, Harniyav, Ahmedabad 382435",
    )

    assert result["current_address"] == (
        "B-402 Pandit Dindayal Nagar, Hathijan, Ahmedabad 382445"
    )
    assert result["permanent_address"] == "81 Modi Vas, Harniyav, Ahmedabad 382435"


def test_application_form_never_uses_page_counter_as_address() -> None:
    result = extract_fields(
        "Application Form",
        """PERMANENT ADDRESS
ADDRESS
YEARS AT CURRENT ADDRESS
LANDMARK
TEHSIL
Page 2 of 128
Signed by: Peeru Lal
Reason: Applied For Loan
Date: 2026-06-20
""",
    )

    assert result["permanent_address"] is None


def test_coapplicant_address_keeps_value_before_page_footer() -> None:
    result = extract_fields(
        "Application Form",
        """CO-APPLICANT DETAILS
Unkar Lal
05-June-
1961
Kanha
9509341692
FATHER
CO-APPLICANT ADDRESS
COMMUNICATION ADDRESS
NAME
ADDRESS
Unkar Lal
S/O: Kanha, mehar basti, Semlibakta, Pachpahar, Sulia, Jhalawar,
Page 4 of 128
Signed by: Peeru Lal
Reason: Applied For Loan
Date: 2026-06-20
""",
    )

    record = result["person_records"][0]
    assert record["current_address"] == (
        "S/O: Kanha, mehar basti, Semlibakta, Pachpahar, Sulia, Jhalawar"
    )
    assert "Page 4 of 128" not in str(result)


def test_real_address_survives_when_page_counter_is_appended() -> None:
    result = extract_fields(
        "Application Form",
        "Permanent Resi. Address: 12 Market Road Delhi 110001 Page 2 of 128\n"
        "Signed by: Peeru Lal",
    )

    assert result["permanent_address"] == "12 Market Road Delhi 110001"


def test_coapplicant_stacked_name_is_not_extracted_as_address() -> None:
    result = extract_fields(
        "Application Form",
        """CO-APPLICANT ADDRESS
COMMUNICATION ADDRESS
NAME
ADDRESS
AARATIBEN ANUPKUMAR SUTHAR
B 402 PANDIT DINDAYAL-2, NR V NAGAR HATHIJAN, AHMEDABAD,
Ahmedabad, Gujarat, India, 382445, HATHIJAN
PERMANENT ADDRESS
NAME
ADDRESS
AARATIBEN ANUPKUMAR SUTHAR
81 MODI VAS, HARNIVAV, AHMEDABAD, Gujarat, India, 382435
OFFICE ADDRESS
""",
    )

    assert result["current_address"] is None
    assert result["permanent_address"] is None
    assert result["person_records"] == [{
        "applicant_name": "AARATIBEN ANUPKUMAR SUTHAR",
        "current_address": (
            "B 402 PANDIT DINDAYAL-2, NR V NAGAR HATHIJAN, AHMEDABAD "
            "Ahmedabad, Gujarat, India, 382445, HATHIJAN"
        ),
        "communication_address": (
            "B 402 PANDIT DINDAYAL-2, NR V NAGAR HATHIJAN, AHMEDABAD "
            "Ahmedabad, Gujarat, India, 382445, HATHIJAN"
        ),
        "permanent_address": "81 MODI VAS, HARNIVAV, AHMEDABAD, Gujarat, India, 382435",
    }]


def test_kfs_boilerplate_clause_number_is_not_roi() -> None:
    result = extract_fields(
        "Loan Agreement",
        """5.
In case of collaborative lending, details may be furnished:
Blended rate of interest
6.
In case of digital loans, specific disclosures may be furnished.
The IRR and Repayment Schedule specified in this Key Facts Statement (KFS)
are subject to change. The rate of interest in the loan documents is final.
""",
    )

    assert result["roi"] is None


def test_current_address_declaration_does_not_extract_aadhaar_fields() -> None:
    result = extract_fields(
        "Aadhaar",
        """Self-Declaration for Current Address
To,
MS Fincap Private Limited
I confirm that my address as per the OVD / Aadhar is different.
I authorize the lender to use my Aadhar information to verify my details from UIDAI.
Name & Signature
Aarti""",
    )

    assert result == {}


def test_facility_schedule_extracts_line_broken_borrower_name() -> None:
    result = extract_fields(
        "Facility Agreement",
        """APPLICANT
NAME
ADDRESS TYPE
ADDRESS
Mr. SUTHAR
ANUPKUMAR
Permanent
MODIVAS, HARNIYAV, AHMEDABAD, GUJARAT, 382435
Amount of Facility (in Rs.)
450000.00
""",
    )

    assert result["borrower_name"] == "SUTHAR ANUPKUMAR"
    assert result["loan_amount"] == "450000"


def test_insurance_form_keeps_insurer_and_loan_identifiers_separate() -> None:
    result = extract_fields(
        "Insurance Form",
        """Care Health Insurance Limited
Insurance Application Form - Group Care Scheme
Loan Application No: GJ000030765
Loan Account Number: 5000030765
Application No: 0030705
Proposal No: CARE-8842
Policy No: POL-17
Proposer Name: Suthar Anupkumar
Nominee Name: Aartiben Suthar
Policy Tenure: 5 Years
Sum Insured: 4,50,000
Total Premium: 5,707
""",
    )

    assert "application_number" not in result
    assert result["insurance_application_number"] == "0030705"
    assert result["insurance_proposal_number"] == "CARE-8842"
    assert result["insurance_policy_number"] == "POL-17"
    assert result["loan_application_number"] == "GJ000030765"
    assert result["loan_account_number"] == "5000030765"
    assert result["policy_tenure_months"] == 60
    assert result["sum_insured"] == "450000"
    assert result["total_premium"] == "5707"


def test_application_form_recovers_interleaved_residential_address_columns() -> None:
    text = (
        "LOAN APPLICATION FORM\nContact Details\nCurrent Resi. Address\nB\n402\nNAMAR\n"
        "Post graduate\nPANDIT\nHATHIJAN\nCity\nTelephone\nDINDAJAL-2\nNRV\n"
        "AHMEDABAD\nPIN 35244S\nMobile 3857927\nE-mail ID\nResidence\n"
        "Permanent Resi. Address\nIf different from above)\n"
        "MODIVAS HARNIYAU HARNSLAV\nAHMEDABAD\nCity\nCurrent Office Address\n"
        "PIN 382M35 Tele\nPIN\nCity\nWhatsapp Available\nYes\nNo Whatsapp Contact No.\n"
        "Occupation Details"
    )

    result = extract_fields("Application Form", text)

    assert "B 402" in result["current_address"]
    assert "PANDIT" in result["current_address"]
    assert "HATHIJAN" in result["current_address"]
    assert "382435" in result["permanent_address"]


def test_bank_statement_profile_extracts_two_line_holder_name() -> None:
    text = (
        "Statement From : 27 Jul 2025\nStatement To : 27 Jul 2026\n"
        "Account Number : XXXX0605\nPROFILE\nName\nDoB\nMobile\nLandline\nEmail\nPAN\n"
        "Address\nHolding Nature\nNominee\nCKYC\nANUPKUMAR CHETANBHAI\nSUTHAR\n"
        "2001-06-18\n9328577271\nNBRPS4867N\nTRANSACTIONS\nTrxn ID\nBalance"
    )

    result = extract_fields("Bank Statement", text)

    assert result["account_holder_name"] == "Anupkumar Chetanbhai Suthar"
    assert result["account_number"] == "0605"


def test_bank_statement_profile_extracts_title_case_holder_after_ckyc() -> None:
    """CAMS profile tables must not treat "Holding Nature" as a person's name."""
    text = (
        "Statement From : 29 Jul 2025\nStatement To : 29 Jul 2026\n"
        "Bank\n: STATE BANK OF INDIA\nAccount Number\n: XXXXXXXXXXXXX6368\n"
        "PROFILE\nName\nDoB\nMobile\nLandline\nEmail\nPAN\nAddress\n"
        "Holding Nature\nNominee\nCKYC\nKala Singh\n1968-01-01\n6377994745\n"
        "VCQPS7972L\nS/O: Nand Singh, Kaminpura\nSINGLE\nTRUE\n"
        "IFSC\nSBIN0031538\nTRANSACTIONS"
    )

    result = extract_fields("Bank Statement", text)

    assert result["account_holder_name"] == "Kala Singh"
    assert result["account_holder_name"] != "Holding Nature"
    assert result["account_number"] == "6368"


def test_bank_statement_welcome_header_beats_relation_and_transaction_text() -> None:
    result = extract_fields(
        "Bank Statement",
        """Account Summary
Welcome:
Mr. Kuldeep Singh
Mr. Kuldeep Singh
Not Available
S/O: Kala Singh, Ward No 11
Date of Statement: 31-07-2026
Account Number: 42833598283
STATEMENT OF ACCOUNT
State Bank of India
Balance
01/01/2026 WDL TFR 10.00 11,538.16
""",
    )

    assert result["account_holder_name"] == "Kuldeep Singh"
    assert result["account_holder_name"] != "WDL TFR"


def test_nach_status_screen_extracts_holder_and_register_success() -> None:
    text = (
        "NACH Mandate UPI Mandate\n9328577271\nANUPKUMAR CHETANBHAI SUTHAR\n"
        "CRN: GJ000030786\nSRN: APPLICANT\nREGISTER_SUCCESS\n2026-07-31 21:26:00"
    )

    result = extract_fields("NACH Form", text)

    assert result["registration_status"] == "registered"
    assert result["account_holder_name"] == "ANUPKUMAR CHETANBHAI SUTHAR"


def test_passbook_holder_allows_ocr_symbols_after_honorific() -> None:
    result = extract_fields(
        "Passbook",
        "Bank of Baroda\nAccount No 83770100000605\nA/C Holder\n"
        "MR- ★ ANUPKUMAR CHSTAHBHAI SUTHAR\nBranch Address: HARANIYAV",
    )

    assert result["account_holder_name"] == "ANUPKUMAR CHSTAHBHAI SUTHAR"


# ════════════════════════════════════════════
# BANK STATEMENT
# ════════════════════════════════════════════

class TestBankStatement:

    def _extract(self, text: str) -> dict:
        return extract_fields("Bank Statement", text)

    def test_account_number_and_ifsc_extracted(self) -> None:
        result = self._extract("Account Number: 123456789012\nIFSC: HDFC0001234")
        assert result["account_number"] == "123456789012"
        assert result["ifsc"] == "HDFC0001234"

    def test_profile_table_extracts_owner_and_statement_period(self) -> None:
        result = self._extract(
            "Statement From : 19 Jun 2025\nStatement To : 19 Jun 2026\n"
            "Bank\n: Punjab National Bank\nAccount Number\n: XXXXXXXXXXXX4386\n"
            "Name\nDoB\nMobile\nPAN\nCKYC\nPEERU LAL\n1994-05-18\n"
            "9000000001\nTSTAA0001T\nIFSC PUNB0007100"
        )
        assert result["account_holder_name"] == "Peeru Lal"
        assert result["bank_name"] == "Punjab National Bank"
        assert result["pan_number"] == "TSTAA0001T"
        assert result["statement_period_start"] == "2025-06-19"
        assert result["statement_period_end"] == "2026-06-19"

    def test_transaction_dates_supply_period_when_statement_header_is_absent(self) -> None:
        result = self._extract(
            "Account Number: 123456789012\n"
            "Transaction Date Narration Debit Credit Balance\n"
            "15/05/2026 Opening balance 0 0 1000\n"
            "11/06/2026 Cash deposit 0 500 1500\n"
            "29/07/2026 Transfer 200 0 1300"
        )

        assert result["statement_period_start"] == "2026-05-15"
        assert result["statement_period_end"] == "2026-07-29"
        assert result["_statement_date_evidence"] == {
            "source": "transaction_dates",
            "transaction_dates": ["2026-05-15", "2026-06-11", "2026-07-29"],
        }


# ════════════════════════════════════════════
# SALARY SLIP
# ════════════════════════════════════════════

class TestSalarySlip:

    def _extract(self, text: str) -> dict:
        return extract_fields("Salary Slip", text)

    def test_salary_fields_extracted(self) -> None:
        result = self._extract(
            "Employee Name: Neha Rao\n"
            "Company: ABC Pvt Ltd\n"
            "Salary Month: March 2026\n"
            "Gross Salary: Rs. 75,000\n"
            "Net Salary: Rs. 62,500"
        )
        assert result["applicant_name"] == "Neha Rao"
        assert result["salary_month"] == "March 2026"
        assert result["net_salary"] == "62500"


# ════════════════════════════════════════════
# FALSE-POSITIVE FIX: Name label rejection
# ════════════════════════════════════════════

class TestNameLabelRejection:
    """Ensure OCR form labels never leak through as extracted applicant names."""

    def _extract_aadhaar(self, text: str) -> dict:
        return extract_fields("Aadhaar", text)

    def _extract_pan(self, text: str) -> dict:
        return extract_fields("PAN Card", text)

    def test_gender_label_not_extracted_as_name(self) -> None:
        """'Gender' is a form label — must not be returned as applicant_name."""
        result = self._extract_aadhaar("Name\nGender\nMale\nDate of Birth\n1994-05-18")
        assert result.get("applicant_name") is None, (
            f"'Gender' leaked as applicant_name: {result.get('applicant_name')}"
        )

    def test_date_of_birth_label_not_extracted_as_name(self) -> None:
        """'Date of Birth' is a form label — must not be returned as applicant_name."""
        result = self._extract_aadhaar(
            "Name\nDate of Birth\nS/O: Ram Lal\nAddress: Village, Dist"
        )
        assert result.get("applicant_name") != "Date of Birth"

    def test_institution_label_not_extracted_as_name(self) -> None:
        """'institution' found in CRIF/CIBIL pages must not be returned as applicant_name."""
        result = self._extract_pan(
            "Permanent Account Number Card\nName\ninstitution\nFather's Name\nRam Lal"
        )
        assert result.get("applicant_name") != "institution"

    def test_timestamp_not_extracted_as_name(self) -> None:
        """Timestamps like '21 PM GMT +05:30' must be rejected as names."""
        result = self._extract_pan(
            "Name\n21 PM GMT +05:30\nPAN: TSTAA0001T"
        )
        assert result.get("applicant_name") is None

    def test_xml_namespace_not_extracted_as_name(self) -> None:
        """XML namespace strings from Aadhaar digital signatures must be rejected."""
        xml_noise = 'xmlns="http://www.w3.org/2000/09/xmldsig#">'
        result = self._extract_aadhaar(
            f"Name\n{xml_noise}\nAadhaar: 1234 5678 9012"
        )
        assert result.get("applicant_name") is None, (
            f"XML namespace leaked as applicant_name: {result.get('applicant_name')}"
        )

    def test_valid_name_still_extracted(self) -> None:
        """A genuine name after the Name label must still be extracted correctly."""
        result = self._extract_aadhaar(
            "Government of India\n"
            "Name: Peeru Lal\n"
            "Date of Birth: 18/05/1994\n"
            "1234 5678 9012"
        )
        assert result.get("applicant_name") == "Peeru Lal"

    @pytest.mark.parametrize(
        "label",
        ["VOTER ID", "RATION", "DRIVING", "पैन कार्ड", "मतदाता पहचान पत्र"],
    )
    def test_identity_column_label_not_extracted_as_name(self, label: str) -> None:
        result = extract_fields(
            "Application Form",
            f"APPLICANT NAME\n{label}\nAADHAAR\nPAN\nVOTER ID",
        )
        assert result.get("applicant_name") is None

    def test_digilocker_split_address_is_reconstructed(self) -> None:
        text = (
            "DigiLocker verified e-Aadhaar\nName\nDate of Birth\nGender\nAddress\n"
            "xxxxxxxx2791\nTika Ram Meena\n01-01-1963\nMale\nS/O: Nanga Ram\n"
            "304023\nRajasthan\nS/O: Nanga\nRam,Deoli,Uniara,Tonk,Rajasthan,30402\n3\n"
        )
        result = extract_fields("Aadhaar", text)
        assert result["address"] == "Deoli,Uniara,Tonk,Rajasthan,304023"
        assert result["related_person_name"] == "Nanga Ram"

    def test_address_column_headers_are_not_an_address(self) -> None:
        result = extract_fields(
            "Aadhaar",
            "Name\nPeeru Lal\nAddress\nLandmark Locality City / District Pin Code",
        )
        assert result.get("address") is None

    def test_xml_signature_stripped_from_aadhaar(self) -> None:
        """X509Certificate block in digital Aadhaar text must not pollute address."""
        text = (
            "Name: Radha Bai\n"
            "Address: Village Semli, Jhalawar, Rajasthan 326502\n"
            "EGOVERNANCE DIVISION 4th FLOOR</X509SubjectName>"
            "<X509Certificate>MIIHoDCCBoigAwIBAgIQQ57Nm==</X509Certificate>"
        )
        result = self._extract_aadhaar(text)
        addr = result.get("address") or ""
        assert "X509Certificate" not in addr
        assert "EGOVERNANCE" not in addr or "Village Semli" in addr


# ════════════════════════════════════════════
# FALSE-POSITIVE FIX: Date format verification
# ════════════════════════════════════════════

class TestDateVerification:
    """Ensure date format differences do not produce false positive mismatches."""

    def test_dd_monthname_yyyy_vs_yyyy_mm_dd_matches(self) -> None:
        """18-May-1994 and 1994-05-18 represent the same date — must be a MATCH."""
        from services.field_verification import verify_date
        result = verify_date("1994-05-18", "18-May-1994")
        assert result.match is True, (
            f"Same date in different formats should match, got: {result.mismatch_reason}"
        )

    def test_dd_slash_mm_yyyy_vs_db_format_matches(self) -> None:
        """18/05/1994 and 18-May-1994 must both parse to the same date."""
        from services.field_verification import verify_date
        result = verify_date("18/05/1994", "18-May-1994")
        assert result.match is True

    def test_bad_ocr_date_produces_low_confidence_not_high_severity(self) -> None:
        """When OCR garbles a date (unparseable), confidence must be low (< 0.5)
        so the anomaly is NOT escalated to HIGH severity by _verify_document_fields."""
        from services.field_verification import verify_date
        result = verify_date("GARBLED123", "18-May-1994")
        assert result.match is False
        assert result.confidence < 0.5, (
            f"Unparseable OCR date should have low confidence, got: {result.confidence}"
        )


def test_utility_bill_prefers_service_block_over_provider_header() -> None:
    fields = extract_fields(
        "Utility Bill",
        """UTTAR GUJARAT VIJ COMPANY LIMITED
ADDRESS : VISNAGAR ROAD
WEBSITE : www.ugvcl.com EMAIL : corporate@ugvcl.com
E-ELECTRICITY BILL : Apr,26
THE EXE ENGR GHB PH 2
B 402 PANDIT DINDAYAL-2
NR V NAGAR HATHIJAN
VILL: Ahmadabad City
DISTRICT: Ahmedabad
Sub-division Office
Bill Date 16-05-2026
""",
    )
    assert fields["address"] == (
        "B 402 PANDIT DINDAYAL-2 NR V NAGAR HATHIJAN "
        "VILL: Ahmadabad City DISTRICT: Ahmedabad"
    )
    assert "ugvcl" not in fields["address"].lower()


def test_passbook_stacked_name_and_branch_are_not_swapped() -> None:
    fields = extract_fields(
        "Passbook",
        """Bank of Baroda
SAVING ACCOUNT PASS BOOK
A/c No. :
Name :
83770100000605
Branch : ANUPKUMAR CHETANBHAI SUTHAR
HARANIYAV
IFSC Code : BARB0DBHARA
""",
    )
    assert fields["account_number"] == "83770100000605"
    assert fields["account_holder_name"] == "ANUPKUMAR CHETANBHAI SUTHAR"
    assert fields["branch"] == "HARANIYAV"


def test_aadhaar_address_removes_interleaved_uidai_authority_header() -> None:
    fields = extract_fields(
        "Aadhaar",
        """आधार
Address:
भारतीय विशिष्ट पहचान प्राधिकरण
Unique Identification Authority of India
पता:
S/O Teeka Ram Meena, 44, Ward No 02, Deoli, Tonk, Rajasthan-304023
3575 9300 0596
help@uidai.gov.in
""",
    )

    assert fields["address"] == (
        "S/O Teeka Ram Meena, 44, Ward No 02, Deoli, Tonk, Rajasthan-304023"
    )
    assert "authority" not in fields["address"].casefold()


def test_whole_application_extraction_never_uses_company_header_as_person() -> None:
    fields = extract_fields(
        "Application Form",
        """MS FINCAP PRIVATE LIMITED
Corporate Office: Jaipur
Customer Application Form
APPLICANT DETAILS
NAME
Batti Lal Meena
DATE OF BIRTH
02-12-1992
CO-APPLICANT ADDRESS
COMMUNICATION ADDRESS
NAME
ADDRESS
Tika Ram Meena
44 Ward 2 Deoli Rajasthan 304023
PERMANENT ADDRESS
NAME
ADDRESS
Tika Ram Meena
44 Ward 2 Deoli Rajasthan 304023
OFFICE ADDRESS
""",
    )

    assert fields["applicant_name"] == "Batti Lal Meena"
    assert fields["person_records"][0]["applicant_name"] == "Tika Ram Meena"
    assert all("FINCAP" not in str(record) for record in fields["person_records"])


def test_coapplicant_address_extracted_from_its_own_section() -> None:
    text = """APPLICANT DETAILS
NAME
Batti Lal Meena
DATE OF BIRTH
02-12-1992
PERMANENT ADDRESS
Permanent ADDRESS
ADDRESS
44 Ward 2 Deoli Rajasthan 304023
CO-APPLICANT ADDRESS
PERMANENT ADDRESS
NAME
Aaratiben Suthar
ADDRESS
81 Modi Vas Harnivav Gujarat 382435
"""
    fields = extract_fields("Application Form", text)
    
    assert fields["applicant_name"] == "Batti Lal Meena"
    assert fields["permanent_address"] == "44 Ward 2 Deoli Rajasthan 304023"
    
    co_records = [r for r in fields["person_records"] if r.get("applicant_name") == "Aaratiben Suthar"]
    assert len(co_records) == 1
    assert co_records[0]["permanent_address"] == "81 Modi Vas Harnivav Gujarat 382435"


def test_empty_guarantor_address_does_not_consume_next_section_heading() -> None:
    fields = extract_fields(
        "Application Form",
        """GUARANTOR DETAILS
GUARANTOR ADDRESS
COMMUNICATION ADDRESS
NAME
ADDRESS
PERMANENT ADDRESS
NAME
ADDRESS
GUARANTOR EMPLOYEMENT/BUSINESS DETAILS
Income Source
Organisation Name
""",
    )

    assert fields["current_address"] is None
    assert fields["permanent_address"] is None
    assert fields["communication_address"] is None


def test_application_form_rejects_flattened_address_label_soup() -> None:
    fields = extract_fields(
        "Application Form",
        """Application Form
Permanent Resi Address
of afferent from above
LJJPS7463 N if not available, please fill form 60/61
Driving License No.
Graduate Postgraduate
2FF KAMINPURA
RAJASTHAN
Aadhaar No 641
Professionally qualified (Doctors, CA, Engineers etc)
Mobile 8690456870
VANYANAMAR
335027
Business Constitution
""",
    )

    assert fields["permanent_address"] is None


def test_application_form_uses_layout_row_for_permanent_address() -> None:
    noisy_text = """Application Form
Permanent Resi Address
of afferent from above
LJJPS7463 N if not available, please fill form 60/61
Driving License No.
Graduate Postgraduate
Aadhaar No 641
Professionally qualified (Doctors, CA, Engineers etc)
Mobile 8690456870
335027
Business Constitution
"""
    structured_content = {
        "layout_regions": [
            {
                "text": "Permanent Resi Address",
                "confidence": 0.78,
                "bounding_box": {"vertices": [
                    {"x": 39, "y": 457}, {"x": 114, "y": 457},
                    {"x": 114, "y": 464}, {"x": 39, "y": 464},
                ]},
            },
            {
                "text": "OFF KAMINPURA",
                "confidence": 0.70,
                "bounding_box": {"vertices": [
                    {"x": 133, "y": 453}, {"x": 308, "y": 453},
                    {"x": 308, "y": 470}, {"x": 133, "y": 470},
                ]},
            },
            {
                "text": "VANWANAUAR",
                "confidence": 0.63,
                "bounding_box": {"vertices": [
                    {"x": 322, "y": 451}, {"x": 457, "y": 451},
                    {"x": 457, "y": 467}, {"x": 322, "y": 467},
                ]},
            },
            {
                "text": "PIN 335027 Tele",
                "confidence": 0.84,
                "bounding_box": {"vertices": [
                    {"x": 221, "y": 497}, {"x": 343, "y": 497},
                    {"x": 343, "y": 508}, {"x": 221, "y": 508},
                ]},
            },
            {
                "text": "Business Constitution",
                "confidence": 0.88,
                "bounding_box": {"vertices": [
                    {"x": 37, "y": 539}, {"x": 108, "y": 539},
                    {"x": 108, "y": 546}, {"x": 37, "y": 546},
                ]},
            },
        ],
    }

    fields = extract_fields(
        "Application Form",
        noisy_text,
        structured_content=structured_content,
    )

    assert fields["permanent_address"] == "OFF KAMINPURA VANWANAUAR 335027"


def test_lender_statement_of_account_is_not_blocked_as_amortization() -> None:
    fields = extract_fields(
        "Bank Statement",
        """AAVAS FINANCIERS LIMITED
Customer's Statement of Account
Name
TIKARAM MEENA
Loan Account No.
221205302480415
Principal Interest EMI Balance
Date Particulars Dr. Cr. Balance
Amount Received Mode NEFT Instrument No X
Txn Date 2026-01-01 Value Date 2026-01-01 Receipt No R1
""",
    )

    assert fields.get("_validation_blocked_reason") is None
    assert fields["account_holder_name"] == "TIKARAM MEENA"
    assert fields["account_number"] == "221205302480415"
