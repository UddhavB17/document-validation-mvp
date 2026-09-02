"""Optional LLM classifier that reviews extracted structured fields.

This module is intentionally isolated from the deterministic classifier.  The
pipeline may call it after normal classification and field extraction, but its
answer never replaces the deterministic document type.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from toon import decode, encode

from services.config import get_bool, get_float
from services.document_classifier import registry_document_types
from services.llm_client import call_llm_api, llm_endpoint_label, llm_model, llm_provider
from services.llm_page_classifier import llm_classification_trigger

logger = logging.getLogger(__name__)

REMOTE_DEFAULT_URL = "http://192.168.31.225:11434"
LOCAL_DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_0"
_MAX_TEXT_CHARS = 2500
_HEALTH_CACHE_SECONDS = 30.0
_health_cache: dict[str, tuple[bool, float]] = {}


def is_structured_llm_classifier_enabled() -> bool:
    import os

    raw_env = os.getenv("ENABLE_STRUCTURED_LLM_CLASSIFIER")
    if raw_env is not None:
        return raw_env.strip().lower() in ("1", "true", "yes", "on")

    from services.config import get_setting

    db_enabled = get_setting("llm_enabled")
    if db_enabled is not None:
        return bool(db_enabled)
    return get_bool("ENABLE_STRUCTURED_LLM_CLASSIFIER", False)


def classify_with_structured_llm(
    *,
    deterministic_document_type: str,
    structured_fields: dict[str, Any],
    ocr_text: str,
    ocr_confidence: float | None = None,
) -> dict[str, Any] | None:
    """Ask the configured LLM to classify from extracted TOON.

    Returns None whenever the feature is disabled or the LLM is unavailable.
    Any error is swallowed so normal classification continues unchanged.
    """
    if not is_structured_llm_classifier_enabled():
        return None

    trigger = llm_classification_trigger(deterministic_document_type, ocr_confidence)
    if trigger is None:
        return None

    base_url = _classifier_base_url()
    timeout = _classifier_timeout_seconds()
    if llm_provider() == "ollama" and not _is_ollama_available(base_url, timeout):
        _log_unavailable()
        return None

    prompt = build_structured_classifier_prompt(
        deterministic_document_type=deterministic_document_type,
        structured_fields=structured_fields,
        ocr_text=ocr_text,
    )
    try:
        response_text = _call_ollama_generate(
            base_url=base_url,
            model=_classifier_model(),
            prompt=prompt,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        _log_unavailable(exc)
        return None

    parsed = _parse_classifier_response(response_text or "")
    if not parsed:
        _log_unavailable("malformed response")
        return None

    document_type = str(parsed.get("document_type") or "").strip()
    valid_types = set(registry_document_types(include_unknown=True))
    valid_types.add("Unknown")
    if document_type not in valid_types:
        return None

    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "document_type": document_type,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(parsed.get("reason") or "").strip() or None,
        "model": _classifier_model(),
        "endpoint": base_url,
        "trigger": trigger,
    }


def build_structured_classifier_prompt(
    *,
    deterministic_document_type: str,
    structured_fields: dict[str, Any],
    ocr_text: str,
) -> str:
    types_list = ", ".join(f'"{item}"' for item in registry_document_types(include_unknown=True))
    fields_toon = encode(_public_structured_fields(structured_fields))
    return (
        "You are reviewing structured OCR extraction output from a Loan Against Property document packet.\n"
        "Identify the most likely document type from the provided TOON fields and OCR text.\n\n"
        "Use CERSAI Report for CERSAI, debtor-based search, or Central Registry of Securitisation pages. "
        "Do not call those pages CIBIL or CRIF unless the text explicitly says CIBIL or CRIF.\n\n"
        "Keep bank document types separate: Passbook is for passbook/pass book pages, "
        "Cheque is for cheque or cancelled cheque pages, PDC is only for post-dated/security cheques, "
        "and Bank Statement is only for statement/account-statement pages.\n\n"
        "Return only TOON:\n"
        "document_type: ...\nconfidence: 0.0\nreason: short reason\n\n"
        f"Known document types:\n{types_list}\n\n"
        f"Deterministic classifier result:\n{deterministic_document_type}\n\n"
        "Structured extracted fields (TOON):\n"
        f"{fields_toon}\n\n"
        "OCR text excerpt:\n"
        f"{(ocr_text or '').strip()[:_MAX_TEXT_CHARS]}"
    )


def _classifier_base_url() -> str:
    if llm_provider() != "ollama":
        return llm_endpoint_label()
    if get_bool("OLLAMA_CLASSIFIER_USE_LOCAL", False):
        return _normalize_base_url(os.getenv("LOCAL_OLLAMA_CLASSIFIER_URL") or LOCAL_DEFAULT_URL)
    return _normalize_base_url(
        os.getenv("OLLAMA_CLASSIFIER_URL")
        or os.getenv("REMOTE_OLLAMA_CLASSIFIER_URL")
        or REMOTE_DEFAULT_URL
    )


def _classifier_model() -> str:
    if llm_provider() != "ollama":
        return llm_model()
    return os.getenv("OLLAMA_CLASSIFIER_MODEL") or os.getenv("LOCAL_LLM_MODEL") or DEFAULT_MODEL


def _classifier_timeout_seconds() -> float:
    return get_float("OLLAMA_CLASSIFIER_TIMEOUT_SECONDS", 3.0, minimum=0.5, maximum=30.0)


def _normalize_base_url(url: str) -> str:
    cleaned = (url or REMOTE_DEFAULT_URL).strip().rstrip("/")
    if cleaned.endswith("/api/generate"):
        return cleaned[: -len("/api/generate")]
    return cleaned


def _is_ollama_available(base_url: str, timeout: float) -> bool:
    cached = _health_cache.get(base_url)
    now = time.monotonic()
    if cached and now - cached[1] < _HEALTH_CACHE_SECONDS:
        return cached[0]

    try:
        import requests

        response = requests.get(f"{base_url}/api/tags", timeout=timeout)
        available = response.ok
    except Exception:  # noqa: BLE001
        available = False

    _health_cache[base_url] = (available, now)
    return available


def _call_ollama_generate(*, base_url: str, model: str, prompt: str, timeout: float) -> str | None:
    if llm_provider() != "ollama":
        return call_llm_api(prompt, max_tokens=180, timeout=int(timeout))

    import requests

    response = requests.post(
        f"{base_url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("response") or payload.get("text") or payload.get("output")


def _parse_classifier_response(response_text: str) -> dict[str, Any] | None:
    stripped = response_text.strip()
    if not stripped:
        return None

    fence_match = re.search(r"```(?:toon|json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    candidate = fence_match.group(1).strip() if fence_match else stripped
    try:
        parsed = decode(candidate)
    except Exception:  # noqa: BLE001
        parsed = None
    if isinstance(parsed, dict) and parsed.get("document_type"):
        return parsed

    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) and parsed.get("document_type") else None


def _public_structured_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in (fields or {}).items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }


def _log_unavailable(error: object | None = None) -> None:
    message = (
        f"Configured LLM ({llm_provider()}) not available - continuing with standard classification"
    )
    if error:
        logger.warning("%s: %s", message, error)
    else:
        logger.warning(message)
