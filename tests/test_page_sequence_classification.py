from services.pipeline import _assign_sequential_document_type


def _apply_sequence(raw_results: list[dict], texts: list[str] | None = None) -> list[dict]:
    current_type = "Unknown"
    current_confidence = 0.0
    current_detected_page = None
    assigned = []
    texts = texts or [""] * len(raw_results)

    for index, raw in enumerate(raw_results, start=1):
        result = _assign_sequential_document_type(
            page_number=index,
            text=texts[index - 1],
            classification=raw,
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
        )
        assigned.append(result)
        if result["detection_method"] == "detected":
            current_type = result["document_type"]
            current_confidence = result["confidence"]
            current_detected_page = index

    return assigned


def test_continuation_pages_inherit_from_first_detected_page() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Technical Report", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
        ]
    )

    assert [page["document_type"] for page in assigned] == ["Technical Report"] * 5
    assert assigned[0]["detection_method"] == "detected"
    assert [page["detection_method"] for page in assigned[1:]] == ["inherited"] * 4
    assert [page["detected_page_number"] for page in assigned] == [1, 1, 1, 1, 1]


def test_high_confidence_type_change_starts_new_document_boundary() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "Technical Report", "confidence": 0.95},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "Aadhaar", "confidence": 0.91},
            {"document_type": "None", "confidence": 0.0},
        ]
    )

    assert [page["document_type"] for page in assigned] == [
        "Technical Report",
        "Technical Report",
        "Aadhaar",
        "Aadhaar",
    ]
    assert assigned[2]["detection_method"] == "detected"
    assert assigned[3]["detected_page_number"] == 3


def test_sequence_starting_unknown_does_not_inherit_until_first_detection() -> None:
    assigned = _apply_sequence(
        [
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "None", "confidence": 0.0},
            {"document_type": "Bank Statement", "confidence": 0.9},
            {"document_type": "None", "confidence": 0.0},
        ]
    )

    assert [page["document_type"] for page in assigned] == [
        "Unknown",
        "Unknown",
        "Bank Statement",
        "Bank Statement",
    ]
    assert assigned[0]["detection_method"] == "unknown"
    assert assigned[1]["detection_method"] == "unknown"
    assert assigned[3]["detection_method"] == "inherited"
