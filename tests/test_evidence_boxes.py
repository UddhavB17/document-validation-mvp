"""Evidence bounding-box resolution. Owned by ``ws-f-accuracy-ops-api``."""

from __future__ import annotations

from services.evidence_boxes import (
    attach_evidence_to_anomalies,
    evidence_for_value,
    find_value_bbox,
    page_words,
)


def _word(text: str, box: list[float], confidence: float = 0.9) -> dict:
    return {"t": text, "b": box, "c": confidence}


def test_exact_match_returns_word_box() -> None:
    words = [
        _word("INCOME", [0.0, 0.0, 0.2, 0.1]),
        _word("ABCDE1234F", [0.1, 0.4, 0.55, 0.44]),
    ]
    assert find_value_bbox(words, "ABCDE1234F") == [0.1, 0.4, 0.55, 0.44]


def test_digits_only_match_for_aadhaar() -> None:
    words = [
        _word("1234", [0.1, 0.1, 0.2, 0.15]),
        _word("5678", [0.21, 0.1, 0.31, 0.15]),
        _word("9012", [0.32, 0.1, 0.42, 0.15]),
    ]
    assert find_value_bbox(words, "1234 5678 9012") == [0.1, 0.1, 0.42, 0.15]


def test_value_split_across_words_returns_union_box() -> None:
    words = [
        _word("Applicant", [0.0, 0.0, 0.2, 0.1]),
        _word("Ramesh", [0.1, 0.3, 0.3, 0.36]),
        _word("Kumar", [0.31, 0.3, 0.5, 0.36]),
    ]
    assert find_value_bbox(words, "Ramesh Kumar") == [0.1, 0.3, 0.5, 0.36]


def test_absent_value_returns_none() -> None:
    words = [_word("Ramesh", [0.1, 0.3, 0.3, 0.36])]
    assert find_value_bbox(words, "ZZZZZ9999Z") is None
    assert find_value_bbox([], "Ramesh") is None
    assert find_value_bbox(words, "") is None


def test_attach_writes_evidence_json() -> None:
    pages = [
        {
            "page_number": 3,
            "words": [_word("ABCDE1234F", [0.12, 0.40, 0.55, 0.44])],
        }
    ]
    anomalies = [
        {
            "rule_id": "PAN_NUMBER_MISMATCH",
            "page_number": 3,
            "found_value": "ABCDE1234F",
            "expected_value": "XXXXX0000X",
        }
    ]
    attach_evidence_to_anomalies(anomalies, pages)
    evidence = anomalies[0].get("evidence_json")
    assert evidence is not None
    assert evidence["page"] == 3
    assert evidence["bbox"] == [0.12, 0.40, 0.55, 0.44]
    assert evidence["text"] == "ABCDE1234F"


def test_completed_page_words_produce_bbox() -> None:
    """End-to-end shape: a ``completed_page``-style dict with real OCR words.

    Guards the fx-integrate-df wiring where ``completed_page["words"]`` (the
    compact ``[{"t","b","c"}]`` list written by ``_build_page_records``) is
    the input evidence reads — not a hand-built list.
    """
    from services.pipeline.page_processing import _ocr_result_dict

    ocr_result = _ocr_result_dict(
        {
            "ocr_text": "INCOME TAX ABCDE1234F",
            "confidence": 0.9,
            "is_readable": True,
            # Shape produced by OCRResult.to_legacy_dict(): compact words plus
            # the small layout dict. Dict inputs pass through untouched.
            "words": [
                {"t": "INCOME", "b": [0.0, 0.0, 0.2, 0.1], "c": 0.9},
                {"t": "TAX", "b": [0.21, 0.0, 0.3, 0.1], "c": 0.9},
                {"t": "ABCDE1234F", "b": [0.1, 0.4, 0.55, 0.44], "c": 0.92},
            ],
            "structured_content": {
                "words": [
                    {"t": "INCOME", "b": [0.0, 0.0, 0.2, 0.1], "c": 0.9},
                    {"t": "TAX", "b": [0.21, 0.0, 0.3, 0.1], "c": 0.9},
                    {"t": "ABCDE1234F", "b": [0.1, 0.4, 0.55, 0.44], "c": 0.92},
                ]
            },
        }
    )
    completed_page = {
        "page_number": 1,
        "page_type": "scanned",
        "ocr_text": ocr_result.get("ocr_text", ""),
        "ocr_confidence": ocr_result.get("confidence", 0.0),
        "words": list(ocr_result.get("words") or []),
        "structured_content": ocr_result.get("structured_content"),
        "document_type": "PAN Card",
    }
    assert len(page_words(completed_page)) == 3
    anomalies = [
        {
            "rule_id": "TRUSTED_PAN_NUMBER_MISMATCH",
            "page_number": 1,
            "found_value": "ABCDE1234F",
            "expected_value": "XXXXX0000X",
        }
    ]
    attach_evidence_to_anomalies(anomalies, [completed_page])
    evidence = anomalies[0].get("evidence_json")
    assert evidence is not None
    assert evidence["page"] == 1
    assert evidence["bbox"] == [0.1, 0.4, 0.55, 0.44]


def test_fast_ocr_bounding_boxes_only_yield_words() -> None:
    """Fast-OCR shape: provider boxes + image size, no structured words.

    Reproduces the Paddle fast path where ``OCRResult.structured_content``
    is ``None``, so ``to_legacy_dict()`` yields empty ``words``. The
    production overwrite path (``_ocr_result_dict`` applied after
    ``to_legacy_dict``, as in ``_build_page_records``) must derive compact
    words from the provider bounding boxes. No pre-built ``words`` list is
    injected anywhere in this test.
    """
    from services.ocr_router import OCRResult
    from services.pipeline.page_processing import _ocr_result_dict

    fast_result = OCRResult(
        text="INCOME TAX ABCDE1234F",
        confidence=0.9,
        route_used="fast",
        bounding_boxes=[
            {"text": "INCOME", "confidence": 0.9, "bbox": [0.0, 0.0, 200.0, 100.0]},
            {"text": "TAX", "confidence": 0.9, "bbox": [210.0, 0.0, 300.0, 100.0]},
            {
                "text": "ABCDE1234F",
                "confidence": 0.92,
                "bbox": [100.0, 400.0, 550.0, 440.0],
            },
        ],
        image_width=1000,
        image_height=1000,
    )
    # Fast path clears structured content (see _coerce_fast_result).
    assert fast_result.structured_content is None

    # Production overwrite path: to_legacy_dict() first (empty words) ...
    legacy = fast_result.to_legacy_dict()
    assert legacy["words"] == []
    assert legacy["structured_content"] is None

    # ... then _ocr_result_dict derives words from bounding boxes.
    ocr_metadata = _ocr_result_dict(legacy)
    assert len(ocr_metadata["words"]) == 3

    # Same completed_page shape _build_page_records writes in memory.
    completed_page = {
        "page_number": 1,
        "page_type": "scanned",
        "ocr_text": ocr_metadata.get("ocr_text", ""),
        "ocr_confidence": ocr_metadata.get("confidence", 0.0),
        "words": list(ocr_metadata.get("words") or []),
        "bounding_boxes": list(ocr_metadata.get("bounding_boxes") or []),
        "structured_content": ocr_metadata.get("structured_content"),
        "document_type": "PAN Card",
    }
    words = page_words(completed_page)
    assert len(words) == 3
    assert find_value_bbox(words, "ABCDE1234F") == [0.1, 0.4, 0.55, 0.44]
    anomalies = [
        {
            "rule_id": "TRUSTED_PAN_NUMBER_MISMATCH",
            "page_number": 1,
            "found_value": "ABCDE1234F",
            "expected_value": "XXXXX0000X",
        }
    ]
    attach_evidence_to_anomalies(anomalies, [completed_page])
    evidence = anomalies[0].get("evidence_json")
    assert evidence is not None
    assert evidence["page"] == 1
    assert evidence["bbox"] == [0.1, 0.4, 0.55, 0.44]


def test_page_words_reads_persisted_structures() -> None:
    """Pages rebuilt without top-level ``words`` still resolve evidence."""
    structured_page = {
        "page_number": 2,
        "structured_content": {
            "words": [_word("ABCDE1234F", [0.12, 0.40, 0.55, 0.44])],
        },
    }
    assert page_words(structured_page) != []
    assert evidence_for_value(structured_page, "ABCDE1234F") is not None
    provider_page = {
        "page_number": 3,
        "ocr_structure": {
            "bounding_boxes": [
                {"text": "ABCDE1234F", "bbox": [0.12, 0.40, 0.55, 0.44]},
            ]
        },
    }
    assert page_words(provider_page) != []
    assert evidence_for_value(provider_page, "ABCDE1234F") is not None
