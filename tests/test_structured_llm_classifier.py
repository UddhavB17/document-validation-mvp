from services.structured_llm_classifier import (
    build_structured_classifier_prompt,
    classify_with_structured_llm,
)


def test_prompt_contains_structured_fields_and_deterministic_result() -> None:
    prompt = build_structured_classifier_prompt(
        deterministic_document_type="PAN",
        structured_fields={"pan_number": "ABCDE1234F", "_classification": {"source": "rules"}},
        ocr_text="Income Tax Department Permanent Account Number",
    )

    assert "Deterministic classifier result:" in prompt
    assert "PAN" in prompt
    assert "ABCDE1234F" in prompt
    assert "_classification" not in prompt
    assert "Return only JSON" in prompt


def test_structured_llm_disabled_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", "false")

    result = classify_with_structured_llm(
        deterministic_document_type="PAN",
        structured_fields={"pan_number": "ABCDE1234F"},
        ocr_text="PAN card",
    )

    assert result is None


def test_structured_llm_unavailable_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", "true")
    monkeypatch.setattr("services.structured_llm_classifier._is_ollama_available", lambda *_args: False)

    result = classify_with_structured_llm(
        deterministic_document_type="PAN",
        structured_fields={"pan_number": "ABCDE1234F"},
        ocr_text="PAN card",
    )

    assert result is None


def test_structured_llm_successful_response(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", "true")
    monkeypatch.setenv("OLLAMA_CLASSIFIER_MODEL", "qwen2.5:7b-instruct-q4_0")
    monkeypatch.setattr("services.structured_llm_classifier._is_ollama_available", lambda *_args: True)
    monkeypatch.setattr(
        "services.structured_llm_classifier._call_ollama_generate",
        lambda **_kwargs: '{"document_type": "PAN Card", "confidence": 0.87, "reason": "PAN number found"}',
    )

    result = classify_with_structured_llm(
        deterministic_document_type="PAN",
        structured_fields={"pan_number": "ABCDE1234F"},
        ocr_text="Income Tax Department Permanent Account Number ABCDE1234F",
    )

    assert result is not None
    assert result["document_type"] == "PAN Card"
    assert result["confidence"] == 0.87
    assert result["model"] == "qwen2.5:7b-instruct-q4_0"
