import json

from services.pipeline import _build_page_records
from services.processing_policy import OCR_SKIPPED_DOCUMENT_TYPE, selected_scanned_page_numbers


def _scanned_pages(count: int) -> list[dict]:
    return [
        {"page_number": page_number, "page_type": "scanned", "image_path": f"page_{page_number}.png"}
        for page_number in range(1, count + 1)
    ]


def test_selected_scanned_page_numbers_samples_large_packet(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "5")

    selected = selected_scanned_page_numbers(_scanned_pages(20))

    assert len(selected) == 5
    assert {1, 2, 3}.issubset(selected)
    assert 20 in selected


def test_build_page_records_skips_scanned_pages_outside_budget(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "2")
    ocr_calls: list[str] = []

    def fake_ocr(image_path: str) -> dict:
        ocr_calls.append(image_path)
        return {"ocr_text": "Permanent Account Number ABCDE1234F", "is_readable": True, "confidence": 0.95}

    monkeypatch.setattr("services.pipeline.run_ocr_on_page", fake_ocr)

    pages = _build_page_records(_scanned_pages(5), {})

    skipped = [page for page in pages if page["document_type"] == OCR_SKIPPED_DOCUMENT_TYPE]
    assert len(ocr_calls) == 2
    assert len(skipped) == 3
    skipped_fields = json.dumps(skipped[0]["extracted_fields"])
    assert "_ocr_skipped" in skipped_fields
