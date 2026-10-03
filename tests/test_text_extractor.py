"""Tests for services/text_extractor.py – DMEF ground-truth extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# PDF helpers (reused from pdf_processor test style)
# ---------------------------------------------------------------------------


def _make_pdf_with_text(path: Path, text: str) -> None:
    """Create a single-page PDF whose page contains *text*."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    # insert_text wraps at the page margin; use a high y to leave room
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _make_blank_pdf(path: Path, pages: int = 1) -> None:
    """Create a PDF with *pages* blank (scanned) pages."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def _make_mixed_pdf(path: Path, digital_text: str, scanned_pages: int = 1) -> None:
    """One digital page followed by *scanned_pages* blank pages."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), digital_text)
    for _ in range(scanned_pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------
# Unit tests: extract_digital_text
# ---------------------------------------------------------------------------


def test_extract_digital_text_returns_text_for_digital_page(tmp_path: Path) -> None:
    """extract_digital_text should return non-empty string for a digital page."""
    fitz = pytest.importorskip("fitz")
    from services.text_extractor import extract_digital_text

    long_text = "A" * 60  # well above the 50-char threshold
    pdf_path = tmp_path / "digital.pdf"
    _make_pdf_with_text(pdf_path, long_text)

    doc = fitz.open(str(pdf_path))
    try:
        result = extract_digital_text(doc[0])
    finally:
        doc.close()

    assert len(result) > 50


def test_extract_digital_text_returns_empty_for_scanned_page(tmp_path: Path) -> None:
    """extract_digital_text should return '' for a blank (scanned) page."""
    fitz = pytest.importorskip("fitz")
    from services.text_extractor import extract_digital_text

    pdf_path = tmp_path / "scanned.pdf"
    _make_blank_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    try:
        result = extract_digital_text(doc[0])
    finally:
        doc.close()

    assert result == ""


# ---------------------------------------------------------------------------
# Unit tests: individual field extractors (pure-text, no PDF needed)
# ---------------------------------------------------------------------------


class TestExtractPanFromDigitalText:
    """test_extract_pan_from_digital_text – PAN regex extraction."""

    def test_valid_pan_extracted(self) -> None:
        """A correctly formatted PAN must be returned as-is."""
        from services.text_extractor import _extract_pan_number

        text = "Applicant details:\nPAN: ABCDE1234F\nAddress: 123 Main St"
        assert _extract_pan_number(text) == "ABCDE1234F"

    def test_first_pan_returned_when_multiple_present(self) -> None:
        """When multiple PANs appear, the first match is returned."""
        from services.text_extractor import _extract_pan_number

        text = "PAN1: ABCDE1234F and PAN2: TSTPA7024Z"
        result = _extract_pan_number(text)
        assert result == "ABCDE1234F"

    def test_no_pan_returns_none(self) -> None:
        """Text without a PAN pattern must return None."""
        from services.text_extractor import _extract_pan_number

        assert _extract_pan_number("No PAN information here.") is None

    def test_partial_pan_not_matched(self) -> None:
        """Patterns that don't fully match PAN format must be ignored."""
        from services.text_extractor import _extract_pan_number

        # Only 4 digits instead of required 5 uppercase + 4 digits + 1 uppercase
        assert _extract_pan_number("ABCDE123F is invalid") is None


class TestExtractApplicantName:
    """test_extract_applicant_name – name extraction from labelled lines."""

    def test_name_after_applicant_name_label(self) -> None:
        """Name following 'Applicant Name:' label must be extracted."""
        from services.text_extractor import _extract_applicant_name

        text = "Applicant Name: Ramesh Kumar\nBranch: Delhi"
        assert _extract_applicant_name(text) == "Ramesh Kumar"

    def test_name_after_borrower_name_label(self) -> None:
        """Name following 'Borrower Name:' label must be extracted."""
        from services.text_extractor import _extract_applicant_name

        text = "Borrower Name: Priya Sharma\nLoan Amount: 5,00,000"
        assert _extract_applicant_name(text) == "Priya Sharma"

    def test_name_after_name_of_applicant_label(self) -> None:
        """Name following 'Name of Applicant:' label must be extracted."""
        from services.text_extractor import _extract_applicant_name

        text = "Name of Applicant: Suresh Babu\nPAN: ABCDE1234F"
        assert _extract_applicant_name(text) == "Suresh Babu"

    def test_name_on_next_line(self) -> None:
        """When the label and name are on separate lines, name must still be found."""
        from services.text_extractor import _extract_applicant_name

        text = "Applicant Name\nMohit Singh\nAddress: 456 Park Lane"
        assert _extract_applicant_name(text) == "Mohit Singh"

    def test_name_from_crif_for_line(self) -> None:
        """CRIF-style 'For NAME' header should be treated as applicant name."""
        from services.text_extractor import _extract_applicant_name

        text = "Credit Information Report\nFor VEERU LAL\nName:\nVEERU LAL"
        assert _extract_applicant_name(text) == "VEERU LAL"

    def test_for_active_accounts_is_not_applicant_name(self) -> None:
        """Later explanatory phrases must not override the report subject."""
        from services.text_extractor import _extract_applicant_name

        text = (
            "Credit Information Report\n"
            "For VEERU LAL\n"
            "Account Summary\n"
            "Tip: Current Balance is considered only for ACTIVE accounts."
        )
        assert _extract_applicant_name(text) == "VEERU LAL"

    def test_hindi_label_is_skipped_when_name_is_next_line(self) -> None:
        """A Hindi label must not be stored as the applicant name."""
        from services.text_extractor import _extract_applicant_name

        text = "Applicant Name\nआवेदक का नाम\nVeeru Lal"
        assert _extract_applicant_name(text) == "Veeru Lal"

    def test_no_name_label_returns_none(self) -> None:
        """Text without a name label must return None."""
        from services.text_extractor import _extract_applicant_name

        assert _extract_applicant_name("Loan Amount: 3,00,000\nPAN: TSTPA7024Z") is None


class TestExtractApplicantNameByLayout:
    @staticmethod
    def _cell(text, x0, y0, x1, y1, page=0):
        return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "page": page}

    def test_pairs_label_with_value_to_the_right(self):
        from services.text_extractor import _extract_applicant_name_by_layout

        cells = [
            self._cell("Masked Aadhaar number", 23, 222, 135, 232),
            self._cell("Name", 23, 258, 50, 268),
            self._cell("Date of Birth", 23, 282, 79, 292),
            self._cell("Gender", 23, 306, 57, 316),
            self._cell("Sudha Bai", 147, 260, 199, 270),
            self._cell("01-01-1962", 147, 284, 204, 294),
            self._cell("Female", 147, 307, 184, 317),
        ]
        assert _extract_applicant_name_by_layout(cells) == "Sudha Bai"

    def test_label_block_without_values_returns_none(self):
        from services.text_extractor import _extract_applicant_name_by_layout

        cells = [
            self._cell("Name", 23, 258, 50, 268),
            self._cell("Date of Birth", 23, 282, 79, 292),
            self._cell("Gender", 23, 306, 57, 316),
            self._cell("c/o , s/o", 23, 330, 58, 340),
        ]
        assert _extract_applicant_name_by_layout(cells) is None

    def test_specific_label_wins_over_generic_name(self):
        from services.text_extractor import _extract_applicant_name_by_layout

        cells = [
            self._cell("Name", 23, 100, 50, 110),
            self._cell("Nominee Person", 147, 100, 220, 110),
            self._cell("Applicant Name", 23, 140, 110, 150),
            self._cell("Ramesh Kumar", 147, 140, 230, 150),
        ]
        assert _extract_applicant_name_by_layout(cells) == "Ramesh Kumar"

    def test_value_on_different_page_is_ignored(self):
        from services.text_extractor import _extract_applicant_name_by_layout

        cells = [
            self._cell("Name", 23, 258, 50, 268, page=0),
            self._cell("Some Value", 147, 260, 220, 270, page=1),
        ]
        assert _extract_applicant_name_by_layout(cells) is None


# ---------------------------------------------------------------------------
# Integration tests: extract_ground_truth
# ---------------------------------------------------------------------------


class TestMissingFieldsReturnNone:
    """test_missing_fields_return_none – absent fields must be None, not errors."""

    def test_all_fields_none_when_text_has_no_keywords(self, tmp_path: Path) -> None:
        """A digital page with generic text must return None for all named fields."""
        pytest.importorskip("fitz")
        from services.text_extractor import extract_ground_truth

        # Enough text to be classified as digital (> 50 chars), but no keywords
        generic = (
            "This document does not contain any structured loan fields. "
            "It is simply a placeholder used for testing purposes only."
        )
        pdf_path = tmp_path / "generic.pdf"
        _make_pdf_with_text(pdf_path, generic)

        result = extract_ground_truth(pdf_path)

        assert result["applicant_name"] is None
        assert result["pan_number"] is None
        assert result["loan_amount"] is None
        assert result["phone"] is None
        assert result["address"] is None
        assert result["product_type"] is None
        assert len(result["raw_text"]) > 0  # raw text must still be present

    def test_scanned_only_pdf_returns_empty_raw_text(self, tmp_path: Path) -> None:
        """A fully scanned PDF must produce empty raw_text and all-None fields."""
        pytest.importorskip("fitz")
        from services.text_extractor import extract_ground_truth

        pdf_path = tmp_path / "scanned_only.pdf"
        _make_blank_pdf(pdf_path, pages=3)

        result = extract_ground_truth(pdf_path)

        assert result["raw_text"] == ""
        assert result["applicant_name"] is None
        assert result["pan_number"] is None

    def test_partial_fields_extracted_rest_none(self, tmp_path: Path) -> None:
        """Only present fields are populated; missing ones remain None."""
        pytest.importorskip("fitz")
        from services.text_extractor import extract_ground_truth

        # Include PAN and phone but no name label or loan amount
        text = (
            "Customer information for loan processing.\n"
            "PAN: ABCDE1234F\n"
            "Mobile: 9876543210\n"
            "This document is issued by the lending institution for record.\n"
        )
        pdf_path = tmp_path / "partial.pdf"
        _make_pdf_with_text(pdf_path, text)

        result = extract_ground_truth(pdf_path)

        assert result["pan_number"] == "ABCDE1234F"
        assert result["phone"] == "9876543210"
        assert result["applicant_name"] is None
        assert result["loan_amount"] is None

    def test_full_document_extracts_all_fields(self, tmp_path: Path) -> None:
        """A rich digital page must yield all six structured fields."""
        pytest.importorskip("fitz")
        from services.text_extractor import extract_ground_truth

        text = (
            "Applicant Name: Ramesh Kumar\n"
            "PAN: ABCDE1234F\n"
            "Loan Amount: 5,00,000\n"
            "Phone: 9876543210\n"
            "Address: 123 Main Street, Delhi - 110001\n"
            "Product Type: LAP\n"
        )
        pdf_path = tmp_path / "full.pdf"
        _make_pdf_with_text(pdf_path, text)

        result = extract_ground_truth(pdf_path)

        assert result["applicant_name"] == "Ramesh Kumar"
        assert result["pan_number"] == "ABCDE1234F"
        assert result["loan_amount"] == "500000"
        assert result["phone"] == "9876543210"
        assert result["address"] is not None and "Main Street" in result["address"]
        assert result["product_type"] is not None and "LAP" in result["product_type"]

    def test_mixed_pdf_skips_scanned_pages(self, tmp_path: Path) -> None:
        """Scanned pages must be skipped; only digital page text is used."""
        pytest.importorskip("fitz")
        from services.text_extractor import extract_ground_truth

        digital_text = (
            "Applicant Name: Sunita Rao\n"
            "PAN: TSTPA7012Z\n"
            "Loan Amount: 3,00,000\n"
            "Mobile: 8765432109\n"
            "Address: 45 Park Avenue, Mumbai\n"
            "Product: MSME\n"
        )
        pdf_path = tmp_path / "mixed.pdf"
        _make_mixed_pdf(pdf_path, digital_text=digital_text, scanned_pages=2)

        result = extract_ground_truth(pdf_path)

        assert result["applicant_name"] == "Sunita Rao"
        assert result["pan_number"] == "TSTPA7012Z"
        assert result["loan_amount"] == "300000"


def test_clean_xml_and_metadata() -> None:
    from services.text_extractor import clean_xml_and_metadata

    raw_text = (
        "Applicant Name: Ramesh Kumar\n"
        "Address: 123 Main St\n"
        "EGOVERNANCE DIVISION 4th FLOOR ELECTRONICS NIKETAN 6,ST=Delhi,L=South Delhi,OU=NATIONAL E GOVERNANCE DEPARTMENT</X509SubjectName><X509Certificate>MIIHoDCCBoigAwIBAgIQQ57Nm//OnytCGpUn9iXWUTANBgkqhkiG9w0BAQsFAD\n"
        "<SignatureValue>some_long_base64_signature_value</SignatureValue>\n"
        "<KeyInfo>some key details</KeyInfo>\n"
        "Jhalawar, Rajasthan, India, 326502\n"
    )

    cleaned = clean_xml_and_metadata(raw_text)

    # XML elements/lines should be skipped/stripped
    assert "X509Certificate" not in cleaned
    assert "SignatureValue" not in cleaned
    assert "KeyInfo" not in cleaned
    assert "Ramesh Kumar" in cleaned
    assert "123 Main St" in cleaned
    assert "Jhalawar, Rajasthan, India, 326502" in cleaned
