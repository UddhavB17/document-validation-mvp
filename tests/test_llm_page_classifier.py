from services.llm_client import call_llm_api, extract_response_text, llm_provider
from services.llm_page_classifier import (
    _parse_classifier_response,
    classify_page_with_llm,
    is_llm_page_classifier_enabled,
    needs_llm_classification,
)
from services.page_classification import LlmClassifierBudget, classify_page_text


def test_extract_response_text_handles_ollama_payload() -> None:
    assert extract_response_text({"response": "Bank Statement"}) == "Bank Statement"


def test_parse_classifier_response_from_json() -> None:
    payload = '{"document_type": "Bank Statement", "confidence": 0.91, "reason": "HDFC header"}'
    parsed = _parse_classifier_response(payload)
    assert parsed is not None
    assert parsed["document_type"] == "Bank Statement"
    assert parsed["confidence"] == 0.91


def test_parse_classifier_response_from_markdown_fence() -> None:
    payload = '```json\n{"document_type": "PAN Card", "confidence": 0.88}\n```'
    parsed = _parse_classifier_response(payload)
    assert parsed is not None
    assert parsed["document_type"] == "PAN Card"


def test_needs_llm_classification_for_unknown_page() -> None:
    assert needs_llm_classification({"document_type": "None", "confidence": 0.0}, None) is True


def test_needs_llm_classification_for_low_rule_confidence() -> None:
    assert needs_llm_classification({"document_type": "Bank Statement", "confidence": 0.4}, None) is True


def test_needs_llm_classification_skips_high_confidence() -> None:
    assert needs_llm_classification({"document_type": "PAN Card", "confidence": 1.0}, 0.95) is False


def test_classify_page_text_uses_llm_when_unknown(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_PAGE_CLASSIFIER", "true")
    monkeypatch.setattr(
        "services.page_classification.classify_page_with_llm",
        lambda _text: {
            "document_type": "Bank Statement",
            "confidence": 0.86,
            "reason": "Account statement layout",
        },
    )

    classification, metadata = classify_page_text(
        "HDFC Bank\nAccount Statement\nPeriod: 01/01/2024 to 31/03/2024",
        ocr_confidence=0.55,
        llm_budget=LlmClassifierBudget(5),
    )

    assert classification["document_type"] == "Bank Statement"
    assert metadata["source"] == "llm"
    assert metadata["llm_document_type"] == "Bank Statement"


def test_classify_page_text_keeps_rules_when_llm_disabled() -> None:
    classification, metadata = classify_page_text(
        "Income Tax Department\nPermanent Account Number ABCDE1234F",
        llm_budget=None,
    )

    assert classification["document_type"] == "PAN Card"
    assert metadata["source"] == "rules"


def test_classify_page_with_llm_returns_none_on_api_failure(monkeypatch) -> None:
    def _raise(_prompt: str, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("services.llm_page_classifier.call_llm_api", _raise)
    assert classify_page_with_llm("some page text") is None


def test_is_llm_page_classifier_enabled_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LLM_PAGE_CLASSIFIER", "true")
    assert is_llm_page_classifier_enabled() is True


def test_call_llm_api_uses_local_endpoint(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "ok"}

    def fake_post(url: str, json: dict, timeout: int):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LOCAL_LLM_API_URL", "http://localhost:11434/api/generate")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "llama3.1")
    monkeypatch.setattr("services.llm_client.requests.post", fake_post)

    assert call_llm_api("hello") == "ok"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"]["model"] == "llama3.1"


def test_call_llm_api_uses_api_key_provider(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "api ok"}}]}

    def fake_post(url: str, json: dict, headers: dict, timeout: int):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_API_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr("services.llm_client.requests.post", fake_post)

    assert call_llm_api("hello") == "api ok"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "gpt-5.6-luna"
    assert captured["json"]["messages"][0]["content"] == "hello"


def test_llm_provider_auto_switches_when_api_key_is_present(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_provider() == "ollama"

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    assert llm_provider() == "openai_compatible"
