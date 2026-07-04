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

    def test_unknown_document_type_returns_empty(self) -> None:
        result = extract_fields("Unknown Document", "some text")
        assert result == {}


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

    def test_statement_period_extracted(self) -> None:
        result = self._extract("Statement Period: 01/01/2026 to 31/03/2026")
        assert result["statement_period_start"] == "2026-01-01"
        assert result["statement_period_end"] == "2026-03-31"

    def test_statement_end_date_fallback(self) -> None:
        result = self._extract("Statement Date: 30/04/2026")
        assert result["statement_period_end"] == "2026-04-30"


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
        assert result["employee_name"] == "Neha Rao"
        assert result["employer_name"] == "ABC Pvt Ltd"
        assert result["salary_month"] == "March 2026"
        assert result["gross_salary"] == "75000"
        assert result["net_salary"] == "62500"
