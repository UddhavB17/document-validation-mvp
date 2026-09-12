"""Persistence boundary tests for provider text that PostgreSQL cannot store."""

from __future__ import annotations

from services.pipeline.persistence import _strip_nuls


def test_strip_nuls_recursively_preserves_structured_fields() -> None:
    value = {
        "ocr_text": "before\x00after",
        "nested\x00key": ["one", {"value": "two\x00three"}],
        "number": 7,
    }

    assert _strip_nuls(value) == {
        "ocr_text": "before after",
        "nested key": ["one", {"value": "two three"}],
        "number": 7,
    }


def test_strip_nuls_leaves_clean_values_unchanged() -> None:
    value = {"name": "Applicant", "confidence": 0.91, "items": [1, 2]}

    assert _strip_nuls(value) == value
