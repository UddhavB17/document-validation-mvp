"""Tests for services/file_validator.py."""

import pytest

from services.file_validator import MAX_FILE_SIZE_BYTES, validate_upload


# ── Extension checks ──────────────────────────

def test_validate_upload_accepts_pdf() -> None:
    result = validate_upload("loan-file.pdf")
    assert result["is_valid"] is True
    assert result["errors"] == []


def test_validate_upload_accepts_pdf_uppercase() -> None:
    result = validate_upload("LOAN-FILE.PDF")
    assert result["is_valid"] is True


def test_validate_upload_rejects_docx() -> None:
    result = validate_upload("loan-file.docx")
    assert result["is_valid"] is False
    assert any("PDF" in err for err in result["errors"])


def test_validate_upload_rejects_empty_filename() -> None:
    result = validate_upload("")
    assert result["is_valid"] is False


def test_validate_upload_rejects_no_extension() -> None:
    result = validate_upload("loanfile")
    assert result["is_valid"] is False


# ── Size checks ───────────────────────────────

def test_validate_upload_accepts_file_within_size_limit() -> None:
    result = validate_upload("loan.pdf", file_size_bytes=1024)
    assert result["is_valid"] is True


def test_validate_upload_rejects_oversized_file() -> None:
    result = validate_upload("loan.pdf", file_size_bytes=MAX_FILE_SIZE_BYTES + 1)
    assert result["is_valid"] is False
    assert any("limit" in err for err in result["errors"])
