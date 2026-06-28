"""Tests for services.pdf_processor – DMEF PDF structure detection."""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_digital_pdf(path: Path, pages: int = 1) -> None:
    """Create a real PDF with selectable text (> 50 chars per page)."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page()
        pg.insert_text(
            (72, 72),
            f"Page {i + 1}: Digital loan application content. "
            "Applicant details, PAN, loan amount, branch, and address are present.",
        )
    doc.save(str(path))
    doc.close()


def _make_scanned_pdf(path: Path, pages: int = 1) -> None:
    """Create a real PDF with blank pages (no selectable text → scanned)."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def _make_mixed_pdf(
    path: Path,
    digital_count: int = 2,
    scanned_count: int = 3,
) -> None:
    """Create a PDF with a mix of digital and blank (scanned) pages."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(digital_count):
        pg = doc.new_page()
        pg.insert_text(
            (72, 72),
            f"Digital page {i + 1}: loan applicant details, PAN, address, amount.",
        )
    for _ in range(scanned_count):
        doc.new_page()
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------
# Tests: detect_page_type
# ---------------------------------------------------------------------------


def test_detect_digital_page(tmp_path: Path) -> None:
    """A page with > 50 characters of text must be classified as 'digital'."""
    fitz = pytest.importorskip("fitz")
    from services.pdf_processor import detect_page_type

    pdf_path = tmp_path / "digital.pdf"
    _make_digital_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    try:
        result = detect_page_type(doc[0])
    finally:
        doc.close()

    assert result == "digital"


def test_detect_scanned_page(tmp_path: Path) -> None:
    """A blank page (0-character text body) must be classified as 'scanned'."""
    fitz = pytest.importorskip("fitz")
    from services.pdf_processor import detect_page_type

    pdf_path = tmp_path / "scanned.pdf"
    _make_scanned_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    try:
        result = detect_page_type(doc[0])
    finally:
        doc.close()

    assert result == "scanned"


# ---------------------------------------------------------------------------
# Tests: convert_page_to_image
# ---------------------------------------------------------------------------


def test_convert_to_image_creates_file(tmp_path: Path) -> None:
    """convert_page_to_image must save a PNG and return its path."""
    fitz = pytest.importorskip("fitz")
    from services.pdf_processor import convert_page_to_image

    pdf_path = tmp_path / "page.pdf"
    _make_scanned_pdf(pdf_path)

    output_path = tmp_path / "output" / "page_0001.png"
    doc = fitz.open(str(pdf_path))
    try:
        returned_path = convert_page_to_image(doc[0], output_path)
    finally:
        doc.close()

    # The file must exist and the return value must point to it.
    assert Path(returned_path).exists(), "PNG file was not created"
    assert Path(returned_path).suffix.lower() == ".png"
    assert Path(returned_path).stat().st_size > 0, "PNG file is empty"


# ---------------------------------------------------------------------------
# Tests: process_pdf_structure
# ---------------------------------------------------------------------------


def test_structure_counts_correct(tmp_path: Path) -> None:
    """process_pdf_structure must report correct digital/scanned totals."""
    pytest.importorskip("fitz")
    from services.pdf_processor import process_pdf_structure

    DIGITAL = 2
    SCANNED = 3
    pdf_path = tmp_path / "mixed.pdf"
    output_dir = tmp_path / "images"
    _make_mixed_pdf(pdf_path, digital_count=DIGITAL, scanned_count=SCANNED)

    result = process_pdf_structure(pdf_path, output_dir)

    assert result["total_pages"] == DIGITAL + SCANNED
    assert result["digital_pages"] == DIGITAL
    assert result["scanned_pages"] == SCANNED
    assert len(result["pages"]) == DIGITAL + SCANNED

    # Digital pages must have image_path == None
    digital_entries = [p for p in result["pages"] if p["page_type"] == "digital"]
    assert all(p["image_path"] is None for p in digital_entries)

    # Scanned pages must have a valid PNG path
    scanned_entries = [p for p in result["pages"] if p["page_type"] == "scanned"]
    assert len(scanned_entries) == SCANNED
    for entry in scanned_entries:
        assert entry["image_path"] is not None
        assert Path(entry["image_path"]).exists(), (
            f"Expected PNG {entry['image_path']} to exist"
        )

    # Page numbers must be 1-based and sequential
    page_numbers = [p["page_number"] for p in result["pages"]]
    assert page_numbers == list(range(1, DIGITAL + SCANNED + 1))
