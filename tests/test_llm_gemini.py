"""Gemini provider tests (ws-g-gemini-llm). The google-genai SDK is faked."""

from __future__ import annotations

import pytest

import services.llm_client as llm_client
import services.llm_gemini as llm_gemini
from services.llm_client import LLMConfigError


class _FakeUsage:
    def __init__(self, prompt_token_count: int, candidates_token_count: int):
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class _FakeCandidate:
    def __init__(self, finish_reason: str = "STOP"):
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, text: str, tokens_in: int = 11, tokens_out: int = 7):
        self.text = text
        self.usage_metadata = _FakeUsage(tokens_in, tokens_out)
        self.candidates = [_FakeCandidate()]


class _FakeModels:
    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    def generate_content(self, *, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class _FakeClient:
    def __init__(self, script):
        self.models = _FakeModels(script)


def _api_error(code: int):
    from google.genai import errors

    return errors.APIError(code, {"error": {"code": code, "status": "E", "message": "boom"}})


def test_gemini_success_parses_usage_and_json_mode(monkeypatch) -> None:
    record: list[dict] = []
    holder: dict = {}

    def fake_build():
        client = _FakeClient([_FakeResponse('{"en": "hi"}')])
        holder["client"] = client
        return client

    monkeypatch.setattr(llm_gemini, "_build_client", fake_build)
    monkeypatch.setattr(llm_client, "llm_provider", lambda: "gemini")
    monkeypatch.setattr(llm_client, "llm_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(
        "services.llm_accounting.record_call",
        lambda provider, model, purpose, t_in, t_out, ms, app_id, ok, error=None: record.append(
            {"purpose": purpose, "tokens_in": t_in, "tokens_out": t_out, "ok": ok}
        ),
    )

    text = llm_client.call_llm_messages(
        [{"role": "user", "content": "summarize"}],
        purpose="summary_en",
        max_tokens=400,
        timeout=60,
        response_format="json",
    )
    assert text == '{"en": "hi"}'
    assert record == [{"purpose": "summary_en", "tokens_in": 11, "tokens_out": 7, "ok": True}]
    sent_config = holder["client"].models.calls[0]["config"]
    assert sent_config.response_mime_type == "application/json"


def test_gemini_429_retries_then_succeeds(monkeypatch) -> None:
    record: list[dict] = []
    holder: dict = {}

    def fake_build():
        if "client" not in holder:
            holder["client"] = _FakeClient([_api_error(429), _FakeResponse("recovered")])
        return holder["client"]

    monkeypatch.setattr(llm_gemini, "_build_client", fake_build)
    monkeypatch.setattr(llm_client, "llm_provider", lambda: "gemini")
    monkeypatch.setattr(llm_client, "llm_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(
        "services.llm_accounting.record_call",
        lambda *args, **kwargs: record.append({"ok": args[7] if len(args) > 7 else kwargs.get("ok")}),
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    text = llm_client.call_llm_messages(
        [{"role": "user", "content": "hello"}],
        purpose="eval",
        response_format="text",
    )
    assert text == "recovered"
    assert [entry["ok"] for entry in record] == [False, True]
    assert len(holder["client"].models.calls) == 2


def test_gemini_permanent_400_does_not_retry(monkeypatch) -> None:
    record: list[dict] = []
    holder: dict = {}

    def fake_build():
        client = _FakeClient([_api_error(400)])
        holder["client"] = client
        return client

    monkeypatch.setattr(llm_gemini, "_build_client", fake_build)
    monkeypatch.setattr(llm_client, "llm_provider", lambda: "gemini")
    monkeypatch.setattr(llm_client, "llm_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(
        "services.llm_accounting.record_call",
        lambda *args, **kwargs: record.append({"ok": args[7] if len(args) > 7 else kwargs.get("ok")}),
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("must not sleep")))

    assert (
        llm_client.call_llm_messages(
            [{"role": "user", "content": "hello"}],
            purpose="verification",
            response_format="json",
        )
        is None
    )
    assert [entry["ok"] for entry in record] == [False]
    assert len(holder["client"].models.calls) == 1


def test_unknown_provider_raises_config_error(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    monkeypatch.setattr("services.config.get_setting", lambda _key, _default=None: None)
    with pytest.raises(LLMConfigError) as excinfo:
        llm_client.llm_provider()
    assert "ollama" in str(excinfo.value) and "gemini" in str(excinfo.value) and "none" in str(excinfo.value)


def test_provider_none_returns_none_and_records_nothing(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "llm_provider", lambda: "none")
    calls: list = []
    monkeypatch.setattr("services.llm_accounting.record_call", lambda *a, **k: calls.append(a))
    assert llm_client.call_llm_messages([{"role": "user", "content": "x"}], purpose="summary_en") is None
    assert calls == []
