"""Gemini LLM provider backed by ``google-genai``.

Implemented by ``ws-g-gemini-llm``. Auth: ``GEMINI_API_KEY`` when set,
otherwise Application Default Credentials (Vertex AI) with
``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_LOCATION``. Env is read only
through ``services.config.get_setting`` — no new ``os.getenv`` here.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Retry-policy exceptions live in the client so every provider shares them.
from services.llm_client import LLMPermanentError, LLMTransientError  # noqa: E402

__all__ = [
    "LLMPermanentError",
    "LLMTransientError",
    "DEFAULT_GEMINI_MODEL",
    "KNOWN_GEMINI_MODELS",
    "gemini_model",
    "generate",
    "list_models",
]

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
KNOWN_GEMINI_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
)


def _get_setting(key: str, default: Any = None) -> Any:
    from services.config import get_setting

    try:
        value = get_setting(key, default)
    except Exception:  # noqa: BLE001 - config unavailable (unit tests)
        return default
    return default if value is None else value


def gemini_model() -> str:
    # --- fx-schema: honour DB llm_model with env still winning (contracts §7) ---
    raw = (
        _get_setting("GEMINI_MODEL", "")
        or _get_setting("LLM_MODEL", "")
        or _get_setting("llm_model", "")
    )
    cleaned = str(raw or "").strip()
    return cleaned or DEFAULT_GEMINI_MODEL


def _build_client() -> Any:
    from google import genai

    api_key = str(_get_setting("GEMINI_API_KEY", "") or "").strip()
    if api_key:
        return genai.Client(api_key=api_key)
    project = str(_get_setting("GOOGLE_CLOUD_PROJECT", "") or "").strip()
    location = str(_get_setting("GOOGLE_CLOUD_LOCATION", "") or "us-central1").strip()
    if project:
        return genai.Client(vertexai=True, project=project, location=location)
    # No key and no project: let the SDK try ADC on its own; surface a
    # permanent error only if the call itself fails.
    return genai.Client()


def _messages_to_contents(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    contents: list[dict[str, str]] = []
    for message in messages or []:
        role = str(message.get("role") or "user").strip().lower()
        text = str(message.get("content") or "")
        contents.append(
            {"role": "model" if role in {"assistant", "model"} else "user", "parts": [{"text": text}]}
        )
    return contents


def _map_exception(exc: Exception) -> LLMTransientError | LLMPermanentError:
    code: int | None = getattr(exc, "code", None)
    message = str(exc)
    if code == 429 or "429" in message[:12] or "RESOURCE_EXHAUSTED" in message:
        return LLMTransientError(f"Gemini rate limited (429): {exc}")
    if code is not None and 500 <= code <= 599:
        return LLMTransientError(f"Gemini server error ({code}): {exc}")
    if code is not None and 400 <= code < 500:
        return LLMPermanentError(f"Gemini request error ({code}): {exc}")
    lowered = message.lower()
    if any(
        token in lowered
        for token in ("timeout", "timed out", "temporarily", "unavailable", "internal error", "500", "502", "503", "504", "overloaded")
    ):
        return LLMTransientError(f"Gemini transient failure: {exc}")
    status = str(getattr(exc, "status", "") or "").upper()
    if status in {"UNAVAILABLE", "DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED", "ABORTED"}:
        return LLMTransientError(f"Gemini transient failure ({status}): {exc}")
    return LLMPermanentError(f"Gemini request failed: {exc}")


def generate(
    messages: list[dict[str, str]],
    *,
    model: str,
    max_tokens: int,
    timeout: int,
    response_format: str = "text",
) -> dict[str, Any]:
    """Call Gemini and return text, token usage, model, timing and finish reason."""
    from google.genai import types

    started = time.monotonic()
    try:
        client = _build_client()
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if response_format == "json" else "text/plain",
        )
        try:
            # DMEF only makes short classification/extraction/summary calls:
            # disable thinking so the output budget is spent on visible text,
            # not hidden reasoning (which is also billed as output tokens).
            config.thinking_config = types.ThinkingConfig(thinking_budget=0)
        except Exception:  # noqa: BLE001 - older SDKs or models without the field
            logger.debug("Gemini thinking_budget unsupported; continuing", exc_info=True)
        try:
            http_options = types.HttpOptions(timeout=timeout * 1000)
            config.http_options = http_options
        except Exception:  # noqa: BLE001 - older SDKs ignore per-call timeouts
            logger.debug("Gemini HttpOptions timeout unsupported; continuing", exc_info=True)
        response = client.models.generate_content(
            model=model,
            contents=_messages_to_contents(messages),  # type: ignore[arg-type]
            config=config,
        )
    except (LLMTransientError, LLMPermanentError):
        raise
    except Exception as exc:  # noqa: BLE001 - map SDK exceptions to retry policy
        raise _map_exception(exc) from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        text = response.text or ""
    except Exception:  # noqa: BLE001 - empty candidate set
        text = ""
    usage = getattr(response, "usage_metadata", None)
    tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
    tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
    finish_reason: str | None = None
    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish_reason = str(getattr(candidates[0], "finish_reason", "") or "") or None
    except Exception:  # noqa: BLE001 - finish reason is informational only
        finish_reason = None
    return {
        "text": text,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": model,
        "duration_ms": duration_ms,
        "finish_reason": finish_reason,
    }


def list_models() -> list[str]:
    """Return usable Gemini model ids for the settings dropdown and eval script."""
    try:
        client = _build_client()
        names: list[str] = []
        for item in client.models.list():
            name = str(getattr(item, "name", "") or "")
            short = name.split("/")[-1] if name else ""
            if short.startswith("gemini-"):
                names.append(short)
        if names:
            return sorted(set(names))
    except Exception as exc:  # noqa: BLE001 - offline / no credentials
        logger.debug("Gemini list_models unavailable: %s", exc)
    return list(KNOWN_GEMINI_MODELS)
