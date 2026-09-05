"""Evidence bounding-box resolution. Owned by ``ws-f-accuracy-ops-api``."""

from __future__ import annotations

from services.evidence_boxes import attach_evidence_to_anomalies, find_value_bbox


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
