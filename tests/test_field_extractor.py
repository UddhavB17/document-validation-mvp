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
8107058694
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
    assert result["phone_number"] == "8107058694"
    assert result["tenure"] == 60
    assert result["requested_amount"] == "275000"
    assert result["roi"] == pytest.approx(26.0)


def test_cam_extracts_person_scoped_mobile_rows() -> None:
    text = """CREDIT APPROVAL MEMO
APPLICATION DETAILS
PERSONAL DETAILS
Applicant
Peeru Lal
8107058694
18-May-1994
32
Coapplicant
Unkar  Lal
9509341692
05-June-1961
65
Coapplicant
Radha  Bai
9509341692
01-January-
1962
64
"""
    records = extract_fields("CAM", text)["person_records"]
    assert records == [
        {"applicant_name": "Peeru Lal", "phone_number": "8107058694", "date_of_birth": "1994-05-18"},
        {"applicant_name": "Unkar Lal", "phone_number": "9509341692", "date_of_birth": "1961-06-05"},
        {"applicant_name": "Radha Bai", "phone_number": "9509341692", "date_of_birth": "1962-01-01"},
    ]


def test_cam_extracts_person_scoped_kyc_address_and_scores() -> None:
    text = """CREDIT APPROVAL MEMO
KYC DOCUMENTS
Applicant
Peeru Lal
XXXXXXXX9108
BCXPL9010K
CoApplicant
Radha  Bai
********1187
JGZPB3257C
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
    assert {"applicant_name": "Peeru Lal", "aadhaar_last4": "9108", "pan_number": "BCXPL9010K"} in records
    assert any(record.get("permanent_address", "").startswith("W/O: Ukar Lal") for record in records)
    assert {"applicant_name": "Peeru Lal", "crif_score": "786"} in records
    assert {"applicant_name": "Radha Bai", "cibil_score": "714"} in records
    assert not any(record.get("crif_score") == "NA" for record in records)


def test_application_form_keeps_coapplicant_kyc_rows_person_scoped() -> None:
    text = """CO-APPLICANT KYC DETAILS
APPLICANT NAME
AADHAAR
PAN
Unkar  Lal
XXXXXXXX7326
BBEPL4329P
Not Provided
Radha  Bai
********1187
JGZPB3257C
Not Provided
"""
    result = extract_fields("Application Form", text)
    assert result["pan_number"] is None
    assert result["person_records"] == [
        {"applicant_name": "Unkar Lal", "aadhaar_last4": "7326", "pan_number": "BBEPL4329P"},
        {"applicant_name": "Radha Bai", "aadhaar_last4": "1187", "pan_number": "JGZPB3257C"},
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


def test_pan_extracts_name_when_ocr_prefixes_name_label() -> None:
    text = "Permanent Account Number JGZPB3257C HName Radha Bai a9 Date 01/01/1962 of Birth"
    assert extract_fields("PAN", text)["applicant_name"] == "Radha Bai"


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
9509341692
FATHER
No
Radha  Bai
01-January-
1962
Ukar Lal
7339781668
MOTHER
No
"""
    records = extract_fields("Application Form", text)["person_records"]
    assert [record["applicant_name"] for record in records] == ["Unkar Lal", "Radha Bai"]
    assert [record["phone_number"] for record in records] == ["9509341692", "7339781668"]


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
BCXPL9010K
Date Of Birth
1994-12-05
Search Output Details
No Match Found
"""
    result = extract_fields("CERSAI Report", text)
    assert result["applicant_name"] == "PEERU LAL"
    assert result["pan_number"] == "BCXPL9010K"
    assert result["date_of_birth"] == "1994-12-05"


def test_asset_cersai_does_not_expose_cersai_corporate_pan_as_borrower_pan() -> None:
    result = extract_fields(
        "CERSAI Report",
        "Asset Based Search Report\nCERSAI Details\nPAN\nAAECC5770G\nSearch Criteria Entered\nAsset Category\nImmovable",
    )
    assert result["pan_number"] is None


def test_pdc_counts_unique_cheque_numbers_from_repeated_ocr() -> None:
    result = extract_fields(
        "PDC",
        '"865981"326024025 "865982"326024025 "865983"326024025 865981326024025',
    )
    assert result["cheque_numbers"] == ["865981", "865982", "865983"]
    assert result["cheque_count"] == 3


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
        "Unique Identification Authority of India Address: W/O: Ukar Lal, Semlibakta, Jhalawar, Rajasthan 326502 2271 5385 1187 help@uidai.gov.in",
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
            "Permanent JGZPB3257C Account Number नामWName Radha Bai "
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
            '<UidData uid="xxxxxxxx9108"><Poi dob="18-05-1994" gender="M" name="Peeru Lal"/>'
            '<Poa co="S/O: Unkar Lal" country="India" dist="Jhalawar" pc="326502" '
            'state="Rajasthan" street="mehar basti" vtc="Semlibakta"/>'
            '<X509SubjectName>postalCode=110003,O=DIGITAL INDIA CORPORATION</X509SubjectName>'
        )
        result = self._extract(text)
        assert result["applicant_name"] == "Peeru Lal"
        assert result["aadhaar_last4"] == "9108"
        assert result["address"].startswith("S/O: Unkar Lal")
        assert "DIGITAL INDIA" not in result["address"]
        assert result["related_person_name"] == "Unkar Lal"


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
            "8107058694\nBCXPL9010K\nIFSC PUNB0007100"
        )
        assert result["account_holder_name"] == "Peeru Lal"
        assert result["bank_name"] == "Punjab National Bank"
        assert result["pan_number"] == "BCXPL9010K"
        assert result["statement_period_start"] == "2025-06-19"
        assert result["statement_period_end"] == "2026-06-19"


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
            "Name\n21 PM GMT +05:30\nPAN: BCXPL9010K"
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
