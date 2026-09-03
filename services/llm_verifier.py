"""Optional Ollama-backed LLM review for low-confidence field verification."""

from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError

from database.models import FieldVerificationResult
from services.config import get_bool
from services.structured_llm_classifier import (
    LOCAL_DEFAULT_URL as _LOCAL_DEFAULT_URL,
)
from services.structured_llm_classifier import (
    REMOTE_DEFAULT_URL as _REMOTE_DEFAULT_URL,
)

_DEFAULT_MODEL = "qwen2.5:7b"
_SYSTEM_PROMPT = (
    "You are a document verification assistant for an Indian NBFC. "
    "Determine if two values refer to the same entity despite OCR errors, "
    "formatting differences, or abbreviations. Be strict - when in doubt, "
    "return match: false. Never guess on ID numbers like Aadhaar or PAN."
)


def verify_field_with_llm(
    field_name: str, extracted: str, db_value: str
) -> FieldVerificationResult:
    """Verify one low-confidence field using local Ollama and Instructor."""
    fallback = FieldVerificationResult(
        field_name=field_name,
        extracted_value=extracted,
        db_value=db_value,
        match=False,
        confidence=0.0,
        method="llm",
        mismatch_reason="LLM verifier unavailable or returned invalid output",
    )
    if not _has_values(extracted, db_value):
        return FieldVerificationResult(
            field_name=field_name,
            extracted_value=extracted,
            db_value=db_value,
            match=False,
            confidence=0.0,
            method="llm",
            mismatch_reason="One or both values are missing",
        )

    try:
        client = _instructor_ollama_client()
        result = client.chat(
            model=_field_verifier_model(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Field name: {field_name}\n"
                        f"OCR extracted value: {extracted}\n"
                        f"Graviton ground-truth value: {db_value}\n"
                        "Return only the structured verification result. "
                        'Set method to "llm" and confidence between 0.0 and 1.0.'
                    ),
                },
            ],
            response_model=FieldVerificationResult,
        )
    except (
        ImportError,
        AttributeError,
        RuntimeError,
        OSError,
        ValueError,
        ValidationError,
        TypeError,
    ):
        return fallback

    try:
        return FieldVerificationResult(
            field_name=field_name,
            extracted_value=extracted,
            db_value=db_value,
            match=bool(result.match),
            confidence=float(result.confidence),
            method="llm",
            mismatch_reason=result.mismatch_reason,
        )
    except (TypeError, ValueError, ValidationError):
        return fallback


def batch_llm_verify(fields: list[dict]) -> list[FieldVerificationResult]:
    """Verify multiple low-confidence fields sequentially with Ollama."""
    results: list[FieldVerificationResult] = []
    for field in fields:
        results.append(
            verify_field_with_llm(
                field_name=str(field.get("field_name") or ""),
                extracted=str(field.get("extracted") or ""),
                db_value=str(field.get("db_value") or ""),
            )
        )
    return results


def llm_verify_field(
    *,
    field_name: str,
    extracted_value: Any,
    db_value: Any,
    current_result: FieldVerificationResult,
) -> FieldVerificationResult:
    """Ask the configured LLM to review one low-confidence text-field match.

    The current deterministic/fuzzy result is returned unchanged when LLM
    verification is disabled, unavailable, or returns malformed data.
    """
    if current_result.method == "exact":
        return current_result

    if not get_bool("ENABLE_LLM_FIELD_VERIFIER", False):
        return current_result

    llm_result = verify_field_with_llm(
        field_name=field_name,
        extracted=str(extracted_value or ""),
        db_value=str(db_value or ""),
    )
    if llm_result.confidence <= 0 and not llm_result.match:
        return current_result
    return llm_result


def _instructor_ollama_client() -> Any:
    import instructor
    import ollama

    raw_client = ollama.Client(host=_ollama_host())
    return instructor.from_ollama(raw_client, mode=instructor.Mode.JSON)


def _field_verifier_model() -> str:
    return (
        os.getenv("LLM_FIELD_VERIFIER_MODEL")
        or os.getenv("OLLAMA_FIELD_VERIFIER_MODEL")
        or os.getenv("LOCAL_LLM_MODEL")
        or os.getenv("LLM_MODEL")
        or _DEFAULT_MODEL
    )


def _ollama_host() -> str:
    if get_bool("OLLAMA_CLASSIFIER_USE_LOCAL", False):
        configured = (
            os.getenv("OLLAMA_HOST")
            or os.getenv("LOCAL_OLLAMA_CLASSIFIER_URL")
            or os.getenv("LOCAL_LLM_API_URL")
            or _LOCAL_DEFAULT_URL
        )
        return _normalize_ollama_base_url(configured, default=_LOCAL_DEFAULT_URL)

    configured = (
        os.getenv("OLLAMA_HOST")
        or os.getenv("OLLAMA_CLASSIFIER_URL")
        or os.getenv("REMOTE_OLLAMA_CLASSIFIER_URL")
        or os.getenv("LOCAL_LLM_API_URL")
        or _REMOTE_DEFAULT_URL
    )
    return _normalize_ollama_base_url(configured, default=_REMOTE_DEFAULT_URL)


def _normalize_ollama_base_url(url: str, *, default: str) -> str:
    configured = url or default
    cleaned = configured.rstrip("/")
    if cleaned.endswith("/api/generate"):
        return cleaned[: -len("/api/generate")]
    return cleaned


def _has_values(*values: Any) -> bool:
    return all(str(value or "").strip() for value in values)
