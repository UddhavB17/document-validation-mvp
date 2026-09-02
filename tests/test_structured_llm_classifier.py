from services.structured_llm_classifier import (
    _parse_classifier_response,
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
    assert "Return only TOON" in prompt


def test_structured_parser_accepts_fenced_json_from_small_local_model() -> None:
    parsed = _parse_classifier_response(
        '```json\n{"document_type":"PAN Card","confidence":0.88,"reason":"PAN found"}\n```'
    )

    assert parsed == {
        "document_type": "PAN Card",
        "confidence": 0.88,
        "reason": "PAN found",
    }


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
    monkeypatch.setattr(
        "services.structured_llm_classifier._is_ollama_available", lambda *_args: False
    )

    result = classify_with_structured_llm(
        deterministic_document_type="Unknown",
        structured_fields={"generic_pan_numbers": ["ABCDE1234F"]},
        ocr_text="PAN card ABCDE1234F",
        ocr_confidence=0.95,
    )

    assert result is None


def test_structured_llm_successful_response(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", "true")
    monkeypatch.setenv("OLLAMA_CLASSIFIER_MODEL", "qwen2.5:7b-instruct-q4_0")
    monkeypatch.setattr(
        "services.structured_llm_classifier._is_ollama_available", lambda *_args: True
    )
    monkeypatch.setattr(
        "services.structured_llm_classifier._call_ollama_generate",
        lambda **_kwargs: "document_type: PAN Card\nconfidence: 0.87\nreason: PAN number found",
    )

    result = classify_with_structured_llm(
        deterministic_document_type="PAN",
        structured_fields={"pan_number": "ABCDE1234F"},
        ocr_text="Income Tax Department Permanent Account Number ABCDE1234F",
        ocr_confidence=0.40,
    )

    assert result is not None
    assert result["document_type"] == "PAN Card"
    assert result["confidence"] == 0.87
    assert result["model"] == "qwen2.5:7b-instruct-q4_0"
    assert result["trigger"] == "low_ocr_confidence"


def test_structured_llm_skips_known_page_with_good_ocr(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", "true")
    monkeypatch.setenv("LLM_CLASSIFIER_OCR_THRESHOLD", "0.65")
    monkeypatch.setattr(
        "services.structured_llm_classifier._is_ollama_available",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("LLM availability must not be checked")
        ),
    )

    result = classify_with_structured_llm(
        deterministic_document_type="PAN Card",
        structured_fields={"pan_number": "ABCDE1234F"},
        ocr_text="Income Tax Department Permanent Account Number ABCDE1234F",
        ocr_confidence=0.95,
    )

    assert result is None
