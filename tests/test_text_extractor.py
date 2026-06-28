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

        text = "PAN1: ABCDE1234F and PAN2: XYZPQ9876K"
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

    def test_no_name_label_returns_none(self) -> None:
        """Text without a name label must return None."""
        from services.text_extractor import _extract_applicant_name

        assert _extract_applicant_name("Loan Amount: 3,00,000\nPAN: XYZPQ9876K") is None


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
            "PAN: QWERT5678Y\n"
            "Loan Amount: 3,00,000\n"
            "Mobile: 8765432109\n"
            "Address: 45 Park Avenue, Mumbai\n"
            "Product: MSME\n"
        )
        pdf_path = tmp_path / "mixed.pdf"
        _make_mixed_pdf(pdf_path, digital_text=digital_text, scanned_pages=2)

        result = extract_ground_truth(pdf_path)

        assert result["applicant_name"] == "Sunita Rao"
        assert result["pan_number"] == "QWERT5678Y"
        assert result["loan_amount"] == "300000"
