"""Optional LLM review for low-confidence field verification.

Implemented by ``ws-g-gemini-llm``: verification goes through the shared
``services.llm_client`` entry point (retries + ``llm_calls`` accounting) and
the model answers in JSON. TOON encodes the prompt input side.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from toon import encode

from database.models import FieldVerificationResult
from services.config import get_bool
from services.llm_client import call_llm_messages

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a document verification assistant for an Indian NBFC. "
    "Determine if two values refer to the same entity despite OCR errors, "
    "formatting differences, or abbreviations. Be strict - when in doubt, "
    "return match: false. Never guess on ID numbers like Aadhaar or PAN."
)


def verify_field_with_llm(
    field_name: str, extracted: str, db_value: str
) -> FieldVerificationResult:
    """Verify one low-confidence field using the configured LLM provider."""
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
        response_text = call_llm_messages(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_verifier_prompt(field_name, extracted, db_value)},
            ],
            purpose="verification",
            max_tokens=200,
            timeout=60,
            response_format="json",
        )
        parsed = _parse_verifier_response(response_text or "")
        if parsed is None:
            return fallback
        return FieldVerificationResult(
            field_name=field_name,
            extracted_value=extracted,
            db_value=db_value,
            match=bool(parsed["match"]),
            confidence=float(parsed["confidence"]),
            method="llm",
            mismatch_reason=parsed.get("mismatch_reason"),
        )
    except (
        ImportError,
        AttributeError,
        RuntimeError,
        OSError,
        ValueError,
        ValidationError,
        TypeError,
    ) as exc:
        logger.debug("LLM field verification failed: %s", exc)
        return fallback

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


def _build_verifier_prompt(field_name: str, extracted: str, db_value: str) -> str:
    """Prompt input in TOON; the model must answer in JSON."""
    return (
        "Decide whether the OCR value and the ground-truth value refer to the same entity.\n"
        'Answer in JSON only: {"match": true/false, "confidence": 0.0-1.0, '
        '"mismatch_reason": "short reason or null"}\n\n'
        "Values to compare (TOON):\n"
        f"{encode({'field_name': field_name, 'extracted_value': extracted, 'db_value': db_value})}\n"
    )


def _parse_verifier_response(response_text: str) -> dict[str, Any] | None:
    """Parse the verifier answer with ``json.loads`` plus a schema check."""
    cleaned = response_text.strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(parsed, dict)
        or type(parsed.get("match")) is not bool
        or type(parsed.get("confidence")) not in (int, float)
    ):
        return None
    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    return {
        "match": bool(parsed["match"]),
        "confidence": confidence,
        "mismatch_reason": parsed.get("mismatch_reason"),
    }


def _has_values(*values: Any) -> bool:
    return all(str(value or "").strip() for value in values)
