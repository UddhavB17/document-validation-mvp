import json

from services.pipeline import _build_page_records
from services.processing_policy import (
    OCR_SKIPPED_DOCUMENT_TYPE,
    full_scan_ocr_enabled,
    selected_scanned_page_numbers,
)
from services.exception_aggregator import aggregate


def _scanned_pages(count: int) -> list[dict]:
    return [
        {"page_number": page_number, "page_type": "scanned", "image_path": f"page_{page_number}.png"}
        for page_number in range(1, count + 1)
    ]


def test_selected_scanned_page_numbers_defaults_to_full_scan(monkeypatch) -> None:
    monkeypatch.delenv("DMEF_FULL_SCAN_OCR", raising=False)
    monkeypatch.delenv("DMEF_MAX_SCANNED_OCR_PAGES", raising=False)

    selected = selected_scanned_page_numbers(_scanned_pages(12))

    assert full_scan_ocr_enabled() is True
    assert selected == set(range(1, 13))


def test_selected_scanned_page_numbers_samples_large_packet(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_FULL_SCAN_OCR", "false")
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "5")

    selected = selected_scanned_page_numbers(_scanned_pages(20))

    assert len(selected) == 5
    assert {1, 2, 3}.issubset(selected)
    assert 20 in selected


def test_selected_scanned_page_numbers_handles_600_page_packet_by_budget(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_FULL_SCAN_OCR", "false")
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "30")

    selected = selected_scanned_page_numbers(_scanned_pages(600))

    assert len(selected) == 30
    assert {1, 2, 3, 4, 5}.issubset(selected)
    assert {595, 596, 597, 598, 599, 600}.issubset(selected)


def test_selected_scanned_page_numbers_can_full_scan_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_FULL_SCAN_OCR", "true")
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "30")

    selected = selected_scanned_page_numbers(_scanned_pages(600))

    assert full_scan_ocr_enabled() is True
    assert len(selected) == 600
    assert selected == set(range(1, 601))


def test_zero_ocr_budget_means_full_scan(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "0")
    monkeypatch.delenv("DMEF_FULL_SCAN_OCR", raising=False)

    selected = selected_scanned_page_numbers(_scanned_pages(12))

    assert full_scan_ocr_enabled() is True
    assert selected == set(range(1, 13))


def test_build_page_records_skips_scanned_pages_outside_budget(monkeypatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "local")
    monkeypatch.setenv("DMEF_FULL_SCAN_OCR", "false")
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "2")
    import services.config as config_mod
    import services.ocr_router as ocr_router_mod

    real_get_setting = config_mod.get_setting

    def _get_setting(key: str, default=None):
        if key == "ocr.provider":
            return "local"
        return real_get_setting(key, default)

    monkeypatch.setattr(config_mod, "get_setting", _get_setting)
    monkeypatch.setattr(ocr_router_mod, "get_setting", _get_setting)
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


def test_internal_ocr_skipped_pages_are_not_documents_found() -> None:
    result = aggregate(
        pages=[
            {"document_type": "PAN", "page_type": "scanned"},
            {"document_type": OCR_SKIPPED_DOCUMENT_TYPE, "page_type": "scanned"},
        ],
        anomalies=[],
        ground_truth={},
    )

    assert result["documents_found"] == ["PAN"]
