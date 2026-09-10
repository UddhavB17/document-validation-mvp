"""Single entry point for all LLM calls: provider dispatch, retries, accounting.

Implemented by ``ws-g-gemini-llm``. Every caller passes a ``purpose`` so
``services.llm_accounting`` can attribute tokens and cost. ``provider ==
"none"`` short-circuits to ``None`` and records nothing.
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

ALLOWED_PROVIDERS = ("ollama", "openai", "openai_compatible", "gemini", "none")

DEFAULT_OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LOCAL_MODEL = "llama3.1"
DEFAULT_API_MODEL = "gpt-5.6-luna"

_DEFAULT_TIMEOUT = 60
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 3.0)


class LLMConfigError(RuntimeError):
    """Unknown LLM provider value. Raised at first use with the allowed list."""


class LLMTransientError(RuntimeError):
    """Timeouts, 429s and 5xx — safe to retry with backoff."""


class LLMPermanentError(RuntimeError):
    """4xx (other than 429) — retrying will not help."""


def call_llm_api(
    prompt: str,
    *,
    max_tokens: int = 450,
    timeout: int = 90,
    purpose: str = "summary_en",
    application_id: int | None = None,
    response_format: str = "text",
) -> str | None:
    """Send a single prompt to the configured LLM provider (legacy wrapper)."""
    return call_llm_messages(
        [{"role": "user", "content": prompt}],
        purpose=purpose,
        application_id=application_id,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format=response_format,  # type: ignore[arg-type]
        ollama_prompt=prompt,
    )


def call_llm_messages(
    messages: list[dict[str, str]],
    *,
    purpose: str,
    application_id: int | None = None,
    max_tokens: int = 450,
    timeout: int = _DEFAULT_TIMEOUT,
    response_format: str = "text",
    ollama_prompt: str | None = None,
) -> str | None:
    """Send chat messages to the configured provider with retries + accounting.

    ``response_format`` is ``"json"`` or ``"text"``. Returns the model text,
    or ``None`` when the provider is ``none`` or every attempt fails.
    """
    from services import llm_accounting

    provider = llm_provider()
    if provider == "none":
        return None
    if response_format not in {"json", "text"}:
        raise ValueError(f"response_format must be 'json' or 'text', got {response_format!r}")

    model = llm_model()
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            if provider == "gemini":
                result = _call_gemini(
                    messages, model=model, max_tokens=max_tokens, timeout=timeout,
                    response_format=response_format,
                )
                text, tokens_in, tokens_out, duration_ms = (
                    result["text"], result["tokens_in"], result["tokens_out"], result["duration_ms"],
                )
            elif provider == "ollama":
                text = _call_ollama(ollama_prompt or _messages_to_prompt(messages), timeout=timeout)
                tokens_in, tokens_out, duration_ms = 0, 0, int((time.monotonic() - started) * 1000)
            else:
                text = _call_openai_compatible(messages, max_tokens=max_tokens, timeout=timeout)
                tokens_in, tokens_out, duration_ms = 0, 0, int((time.monotonic() - started) * 1000)
            llm_accounting.record_call(
                provider, model, purpose, tokens_in, tokens_out, duration_ms,
                application_id, True,
            )
            return text
        except LLMPermanentError as exc:
            llm_accounting.record_call(
                provider, model, purpose, 0, 0, int((time.monotonic() - started) * 1000),
                application_id, False, str(exc),
            )
            logger.warning("LLM %s call failed permanently (purpose=%s): %s", provider, purpose, exc)
            return None
        except (LLMTransientError, requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            transient = exc
            llm_accounting.record_call(
                provider, model, purpose, 0, 0, int((time.monotonic() - started) * 1000),
                application_id, False, f"attempt {attempt}: {exc}",
            )
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_SECONDS[attempt - 1] if attempt - 1 < len(_BACKOFF_SECONDS) else 3.0
                logger.warning(
                    "LLM %s transient failure (attempt %d/%d, purpose=%s); retrying in %ss: %s",
                    provider, attempt, _MAX_ATTEMPTS, purpose, delay, transient,
                )
                time.sleep(delay)
        except Exception as exc:  # noqa: BLE001 - unexpected failure, no retry
            llm_accounting.record_call(
                provider, model, purpose, 0, 0, int((time.monotonic() - started) * 1000),
                application_id, False, str(exc),
            )
            logger.warning("LLM %s call failed (purpose=%s): %s", provider, purpose, exc)
            return None
    logger.warning("LLM %s call exhausted retries (purpose=%s): %s", provider, purpose, last_error)
    return None


def llm_provider() -> str:
    from services.config import get_setting

    db_val = get_setting("llm_provider")
    if db_val is not None and str(db_val).strip() != "":
        raw = str(db_val).strip().lower()
    else:
        import os

        raw = _clean_env_value(os.getenv("LLM_PROVIDER") or "").lower()

    if raw in {"", "ollama"}:
        return "ollama"
    if raw in {"local", "local_ollama"}:
        return "ollama"
    if raw == "openai":
        return "openai"
    if raw in {"api", "openai-api", "openai_compatible"}:
        return "openai_compatible"
    if raw == "gemini":
        return "gemini"
    if raw == "none":
        return "none"
    if raw == "auto":
        return "openai_compatible" if _api_key() else "ollama"
    raise LLMConfigError(f"Unknown LLM_PROVIDER={raw!r}. Allowed: {', '.join(ALLOWED_PROVIDERS)}")


def llm_model() -> str:
    from services.config import get_setting

    if llm_provider() == "gemini":
        from services.llm_gemini import gemini_model

        return gemini_model()

    import os

    if llm_provider() == "ollama":
        env_local = _clean_env_value(os.getenv("LOCAL_LLM_MODEL"))
        if env_local:
            return env_local

        db_val = get_setting("llm_model")
        if db_val is not None and str(db_val).strip() != "":
            return str(db_val).strip()

        return _clean_env_value(os.getenv("LLM_MODEL")) or DEFAULT_LOCAL_MODEL
    else:
        env_openai = _clean_env_value(os.getenv("OPENAI_MODEL"))
        if env_openai:
            return env_openai

        db_val = get_setting("llm_model")
        if db_val is not None and str(db_val).strip() != "":
            return str(db_val).strip()

        return _clean_env_value(os.getenv("LLM_MODEL")) or DEFAULT_API_MODEL


def llm_endpoint_label() -> str:
    if llm_provider() == "ollama":
        return _ollama_generate_url()
    if llm_provider() == "gemini":
        from services.llm_gemini import gemini_model

        return f"gemini:{gemini_model()}"
    return _chat_completions_url()


def has_api_key_configured() -> bool:
    return bool(_api_key())


def _call_gemini(
    messages: list[dict[str, str]],
    *,
    model: str,
    max_tokens: int,
    timeout: int,
    response_format: str,
) -> dict:
    from services import llm_gemini

    return llm_gemini.generate(
        messages, model=model, max_tokens=max_tokens, timeout=timeout,
        response_format=response_format,
    )


def _call_ollama(prompt: str, *, timeout: int) -> str | None:
    api_url = _ollama_generate_url()
    payload = {"model": llm_model(), "prompt": prompt, "stream": False}

    try:
        response = requests.post(api_url, json=payload, timeout=timeout)
    except (requests.Timeout, requests.ConnectionError):
        raise
    if response.status_code == 429 or 500 <= response.status_code <= 599:
        raise LLMTransientError(f"Ollama HTTP {response.status_code}")
    if 400 <= response.status_code < 500:
        raise LLMPermanentError(f"Ollama HTTP {response.status_code}: {response.text[:200]}")
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
        raise LLMPermanentError("No API key configured for OpenAI-compatible provider")

    payload = {
        "model": llm_model(),
        "messages": messages,
        "max_tokens": max_tokens,
    }
    try:
        response = requests.post(
            _chat_completions_url(),
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
    except (requests.Timeout, requests.ConnectionError):
        raise
    if response.status_code == 429 or 500 <= response.status_code <= 599:
        raise LLMTransientError(f"OpenAI-compatible HTTP {response.status_code}")
    if 400 <= response.status_code < 500:
        raise LLMPermanentError(f"OpenAI-compatible HTTP {response.status_code}: {response.text[:200]}")
    response.raise_for_status()
    return extract_response_text(response.json())


def _ollama_generate_url() -> str:
    import os

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
    import os

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
    import os

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
