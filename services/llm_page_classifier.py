"""Local LLM fallback for page-level document classification."""

from __future__ import annotations

import json
import re
from typing import Any

from services.config import get_bool, get_float, get_int
from services.document_classifier import registry_document_types
from services.llm_client import call_llm_api

VALID_DOCUMENT_TYPES = tuple(registry_document_types(include_unknown=True))

_MAX_TEXT_CHARS = 3500


def is_llm_page_classifier_enabled() -> bool:
    return get_bool("ENABLE_LLM_PAGE_CLASSIFIER", False)


def llm_classifier_min_confidence() -> float:
    return get_float("LLM_CLASSIFIER_MIN_CONFIDENCE", 0.75, minimum=0.0, maximum=1.0)


def llm_classifier_max_pages_per_file() -> int:
    return get_int("LLM_CLASSIFIER_MAX_PAGES_PER_FILE", 100, minimum=0)


def llm_classifier_ocr_threshold() -> float:
    """Pages with OCR confidence below this may trigger LLM classification."""
    return get_float("LLM_CLASSIFIER_OCR_THRESHOLD", 0.65, minimum=0.0, maximum=1.0)


def needs_llm_classification(
    rule_result: dict[str, Any],
    ocr_confidence: float | None,
) -> bool:
    document_type = str(rule_result.get("document_type") or "")
    confidence = float(rule_result.get("confidence") or 0.0)

    if document_type in {"", "None"}:
        return True
    if confidence < llm_classifier_min_confidence():
        return True
    if ocr_confidence is not None and ocr_confidence < llm_classifier_ocr_threshold():
        return True
    return False


def classify_page_with_llm(text: str) -> dict[str, Any] | None:
    """Classify page text using the local LLM. Returns None on failure."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    prompt = _build_classifier_prompt(cleaned[:_MAX_TEXT_CHARS])
    try:
        response_text = call_llm_api(prompt, max_tokens=120, timeout=120)
    except Exception:
        return None

    if not response_text:
        return None

    parsed = _parse_classifier_response(response_text)
    if not parsed:
        return None

    document_type = str(parsed.get("document_type") or "None")
    if document_type not in VALID_DOCUMENT_TYPES:
        return None

    confidence = parsed.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.7

    confidence_value = max(0.0, min(1.0, confidence_value))
    return {
        "document_type": document_type,
        "confidence": confidence_value,
        "reason": str(parsed.get("reason") or "").strip() or None,
    }


def _build_classifier_prompt(text: str) -> str:
    types_list = ", ".join(f'"{item}"' for item in VALID_DOCUMENT_TYPES)
    return (
        "You classify one page from an Indian NBFC loan file.\n"
        f"Choose exactly one document_type from this list: {types_list}.\n"
        "Use \"None\" only when the page is blank, unreadable, or not a loan document.\n"
        "Do not merge credit bureaus: choose \"CIBIL Report\" only for TransUnion CIBIL/CIBIL pages, "
        "and choose \"CRIF Report\" only for CRIF High Mark/CRIF pages.\n"
        "Choose \"CERSAI Report\" for CERSAI, debtor-based search, or Central Registry of Securitisation pages.\n"
        "Do not merge bank documents: choose \"Passbook\" for passbook/pass book pages, "
        "\"Cheque\" for cheque or cancelled cheque pages, \"PDC\" only for post-dated/security cheques, "
        "and \"Bank Statement\" only for statement/account-statement pages.\n"
        "Respond with JSON only, no markdown:\n"
        '{"document_type": "...", "confidence": 0.0, "reason": "short reason"}\n\n'
        "Page text:\n"
        f"{text}"
    )


def _parse_classifier_response(response_text: str) -> dict[str, Any] | None:
    stripped = response_text.strip()
    if not stripped:
        return None

    candidates = [stripped]
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.insert(0, fence_match.group(1))

    brace_match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("document_type"):
            return payload
    return None
