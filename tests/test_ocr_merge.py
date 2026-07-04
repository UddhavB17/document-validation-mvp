"""Tests for Hindi + English OCR merge helpers."""

from services.ocr_engine import _merge_ocr_texts


def test_merge_ocr_texts_deduplicates_lines() -> None:
    merged = _merge_ocr_texts(
        [
            "Applicant Name: Ramesh Kumar\nPAN: ABCDE1234F",
            "Applicant Name: Ramesh Kumar\nLoan Amount: 500000",
        ]
    )
    assert "Applicant Name: Ramesh Kumar" in merged
    assert "PAN: ABCDE1234F" in merged
    assert "Loan Amount: 500000" in merged
    assert merged.count("Applicant Name: Ramesh Kumar") == 1


def test_merge_ocr_texts_keeps_hindi_and_english() -> None:
    merged = _merge_ocr_texts(
        [
            "HDFC Bank Passbook",
            "एचडीएफसी बैंक पासबुक",
        ]
    )
    assert "HDFC Bank Passbook" in merged
    assert "एचडीएफसी बैंक पासबुक" in merged
