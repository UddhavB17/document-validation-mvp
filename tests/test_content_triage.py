from services.content_triage import triage_page_content


def test_photo_triage_for_near_zero_ocr_text() -> None:
    result = triage_page_content(
        page_type="scanned",
        text="",
        ocr_confidence=0.12,
        ocr_metadata={"image_width": 1600, "image_height": 1200, "char_count": 0},
    )

    assert result["category"] == "photo"
    assert result["confidence"] >= 0.90


def test_printed_scan_triage_for_dense_high_confidence_text() -> None:
    result = triage_page_content(
        page_type="scanned",
        text="Loan Application Form Applicant Name Ramesh Kumar " * 5,
        ocr_confidence=0.91,
        ocr_metadata={"image_width": 1000, "image_height": 1400},
    )

    assert result["category"] == "printed_scan"


def test_handwritten_triage_for_sparse_low_confidence_text() -> None:
    result = triage_page_content(
        page_type="scanned",
        text="rent paid 4500",
        ocr_confidence=0.48,
        ocr_metadata={"image_width": 1000, "image_height": 1400},
    )

    assert result["category"] == "handwritten"
