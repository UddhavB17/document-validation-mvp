"""Shared HTTP client for local Ollama and API-key LLM providers."""

from __future__ import annotations

import os

import requests


DEFAULT_OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LOCAL_MODEL = "llama3.1"
DEFAULT_API_MODEL = "gpt-5.6-luna"


def call_llm_api(prompt: str, *, max_tokens: int = 450, timeout: int = 90) -> str | None:
    """Send a single prompt to the configured LLM provider."""
    return call_llm_messages(
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        timeout=timeout,
        ollama_prompt=prompt,
    )


def call_llm_messages(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 450,
    timeout: int = 90,
    ollama_prompt: str | None = None,
) -> str | None:
    """Send chat messages to the configured provider.

    Environment switch:
    - LLM_PROVIDER=auto uses an API key when present, otherwise local Ollama.
    - LLM_PROVIDER=ollama keeps the current local Ollama behavior.
    - LLM_PROVIDER=openai or openai_compatible uses an API key and a
      /chat/completions-compatible endpoint.
    """
    provider = llm_provider()
    if provider == "none":
        return None
    if provider == "ollama":
        return _call_ollama(ollama_prompt or _messages_to_prompt(messages), timeout=timeout)
    return _call_openai_compatible(messages, max_tokens=max_tokens, timeout=timeout)


def llm_provider() -> str:
    from services.config import get_setting
    db_val = get_setting("llm_provider")
    if db_val is not None:
        provider = str(db_val).strip().lower()
    else:
        provider = _clean_env_value(os.getenv("LLM_PROVIDER") or "auto").lower()

    if provider in {"", "auto"}:
        return "openai_compatible" if _api_key() else "ollama"
    if provider in {"local", "local_ollama"}:
        return "ollama"
    if provider in {"api", "openai-api", "openai_compatible"}:
        return "openai_compatible"
    if provider in {"openai", "ollama", "none"}:
        return provider
    return "ollama"


def llm_model() -> str:
    from services.config import get_setting

    if llm_provider() == "ollama":
        env_local = _clean_env_value(os.getenv("LOCAL_LLM_MODEL"))
        if env_local:
            return env_local

        db_val = get_setting("llm_model")
        if db_val is not None:
            return str(db_val).strip()

        return (
            _clean_env_value(os.getenv("LLM_MODEL"))
            or DEFAULT_LOCAL_MODEL
        )
    else:
        env_openai = _clean_env_value(os.getenv("OPENAI_MODEL"))
        if env_openai:
            return env_openai

        db_val = get_setting("llm_model")
        if db_val is not None:
            return str(db_val).strip()

        return (
            _clean_env_value(os.getenv("LLM_MODEL"))
            or DEFAULT_API_MODEL
        )


def llm_endpoint_label() -> str:
    if llm_provider() == "ollama":
        return _ollama_generate_url()
    return _chat_completions_url()


def has_api_key_configured() -> bool:
    return bool(_api_key())


def _call_ollama(prompt: str, *, timeout: int) -> str | None:
    api_url = _ollama_generate_url()
    payload = {"model": llm_model(), "prompt": prompt, "stream": False}

    response = requests.post(api_url, json=payload, timeout=timeout)
    response.raise_for_status()
    return extract_response_text(response.json())


def _call_openai_compatible(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    timeout: int,
) -> str | None:
    api_key = _api_key()
    if not api_key:
        return None

    payload = {
        "model": llm_model(),
        "messages": messages,
        "max_tokens": max_tokens,
    }
    response = requests.post(
        _chat_completions_url(),
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return extract_response_text(response.json())


def _ollama_generate_url() -> str:
    configured = (
        _clean_env_value(os.getenv("LLM_API_URL"))
        or _clean_env_value(os.getenv("LOCAL_LLM_API_URL"))
        or _clean_env_value(os.getenv("OPEN_SOURCE_LLM_API_URL"))
        or DEFAULT_OLLAMA_GENERATE_URL
    )
    cleaned = configured.rstrip("/")
    if cleaned.endswith("/api/chat"):
        return cleaned[: -len("/api/chat")] + "/api/generate"
    if cleaned.endswith("/api/generate"):
        return cleaned
    return cleaned + "/api/generate"


def _chat_completions_url() -> str:
    configured = (
        _clean_env_value(os.getenv("LLM_API_URL"))
        or _clean_env_value(os.getenv("LLM_API_BASE_URL"))
        or _clean_env_value(os.getenv("OPENAI_BASE_URL"))
        or DEFAULT_OPENAI_BASE_URL
    )
    cleaned = configured.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return cleaned + "/chat/completions"
    return cleaned + "/v1/chat/completions"


def _api_key() -> str:
    from services.config import get_setting
    enabled = get_setting("llm_api_key_enabled", True)
    if not enabled:
        return ""
    db_val = get_setting("llm_api_key")
    if db_val:
        val_str = str(db_val).strip()
        if val_str:
            return val_str
    return (
        _clean_env_value(os.getenv("LLM_API_KEY"))
        or _clean_env_value(os.getenv("OPENAI_API_KEY"))
        or ""
    )


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(
        f"{str(message.get('role') or 'user').upper()}: {message.get('content') or ''}"
        for message in messages
    )


def _clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    if " #" in cleaned:
        cleaned = cleaned.split(" #", 1)[0].strip()
    return cleaned


def extract_response_text(payload: dict) -> str | None:
    if payload.get("response"):
        return payload["response"]
    if payload.get("text"):
        return payload["text"]
    if payload.get("output"):
        return payload["output"]

    choices = payload.get("choices") or []
    if choices:
        first_choice = choices[0]
        message = first_choice.get("message") or {}
        return message.get("content") or first_choice.get("text")

    return None
