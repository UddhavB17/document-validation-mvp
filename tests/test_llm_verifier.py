import json

import pytest

from database.models import FieldVerificationResult
from services.llm_verifier import llm_verify_field


@pytest.mark.parametrize("match", ["false", "true", 0, 1, None, [], {}])
def test_malformed_llm_match_preserves_deterministic_mismatch(monkeypatch, match):
    monkeypatch.setattr("services.llm_verifier.get_bool", lambda *_: True)
    monkeypatch.setattr(
        "services.llm_verifier.call_llm_messages",
        lambda *args, **kwargs: json.dumps({"match": match, "confidence": 0.99}),
    )
    current = FieldVerificationResult(
        field_name="applicant_name",
        extracted_value="Alice",
        db_value="Bob",
        match=False,
        confidence=0.4,
        method="fuzzy",
    )

    result = llm_verify_field(
        field_name="applicant_name",
        extracted_value="Alice",
        db_value="Bob",
        current_result=current,
    )

    assert result is current


@pytest.mark.parametrize("confidence", [None, True, "invalid", "NaN", "Infinity", "-Infinity"])
def test_page_classifiers_do_not_promote_invalid_confidence(monkeypatch, confidence):
    from services.llm_page_classifier import classify_page_with_llm
    from services.structured_llm_classifier import classify_with_structured_llm

    response = json.dumps({"document_type": "PAN Card", "confidence": confidence})
    monkeypatch.setattr(
        "services.llm_page_classifier.call_llm_messages", lambda *args, **kwargs: response
    )
    monkeypatch.setattr(
        "services.structured_llm_classifier.is_structured_llm_classifier_enabled", lambda: True
    )
    monkeypatch.setattr("services.structured_llm_classifier.llm_provider", lambda: "none")
    monkeypatch.setattr("services.structured_llm_classifier.llm_endpoint_label", lambda: "test")
    monkeypatch.setattr("services.structured_llm_classifier.llm_model", lambda: "test")
    monkeypatch.setattr(
        "services.structured_llm_classifier._call_ollama_generate", lambda **kwargs: response
    )

    page = classify_page_with_llm("Income Tax Department Permanent Account Number")
    structured = classify_with_structured_llm(
        deterministic_document_type="Unknown", structured_fields={}, ocr_text="PAN card"
    )

    assert page["confidence"] == 0.0
    assert structured["confidence"] == 0.0
