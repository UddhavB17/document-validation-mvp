from services.bureau_anchors import classify_credit_bureau_by_anchors
from services.page_classification import classify_page_text


def test_cibil_anchor_wins_for_transunion_cibil_header() -> None:
    result = classify_credit_bureau_by_anchors(
        "TransUnion CIBIL\nCredit Information Report\nCIBIL Score 782\nControl Number 123456"
    )

    assert result["document_type"] == "CIBIL Report"
    assert result["confidence"] >= 0.75


def test_crif_anchor_wins_for_high_mark_header() -> None:
    result = classify_credit_bureau_by_anchors(
        "CRIF High Mark\nCredit Information Report\nCredit Score 744"
    )

    assert result["document_type"] == "CRIF Report"
    assert result["confidence"] >= 0.75


def test_page_classification_uses_anchors_before_llm(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_PAGE_CLASSIFIER", "true")
    monkeypatch.setattr(
        "services.page_classification.classify_page_with_llm",
        lambda _text: {"document_type": "CRIF Report", "confidence": 0.99},
    )

    classification, metadata = classify_page_text(
        "TransUnion CIBIL\nCredit Information Report\nCIBIL Score 781\nControl Number 99"
    )

    assert classification["document_type"] == "CIBIL Report"
    assert metadata["source"] == "anchors"
