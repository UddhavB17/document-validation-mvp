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
    import os
    raw_env = os.getenv("ENABLE_LLM_PAGE_CLASSIFIER")
    if raw_env is not None:
        return raw_env.strip().lower() in ("1", "true", "yes", "on")

    from services.config import get_setting
    db_enabled = get_setting("llm_enabled")
    if db_enabled is not None:
        return bool(db_enabled)
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


def normalize_llm_document_type(doc_type: str) -> str:
    """Normalize and map loose LLM document type names to exact registry values."""
    cleaned = str(doc_type or "").strip().lower()
    if not cleaned or cleaned in {"none", "unknown", "null"}:
        return "None"

    # Direct match check (ignoring case/whitespace)
    for valid_type in VALID_DOCUMENT_TYPES:
        if valid_type.strip().lower() == cleaned:
            return valid_type

    # Common aliases & substring matches
    if "aadhaar" in cleaned or "aadhar" in cleaned:
        return "Aadhaar"
    if "pan" in cleaned:
        return "PAN Card"
    if "passport" in cleaned:
        return "Passport"
    if "driving" in cleaned or "licence" in cleaned or "license" in cleaned:
        return "Driving License"
    if "voter" in cleaned:
        return "Voter ID"
    if "mnrega" in cleaned:
        return "MNREGA Job Card"
    if "npr" in cleaned:
        return "NPR Letter"
    if "utility" in cleaned or "electricity" in cleaned or "bill" in cleaned:
        return "Utility Bill"
    if "bank statement" in cleaned or "statement" in cleaned:
        return "Bank Statement"
    if "passbook" in cleaned or "pass book" in cleaned:
        return "Passbook"
    if "cheque" in cleaned:
        return "Cheque"
    if "pdc" in cleaned:
        return "PDC"
    if "cibil" in cleaned:
        return "CIBIL Report"
    if "crif" in cleaned:
        return "CRIF Report"
    if "cersai" in cleaned:
        return "CERSAI Report"
    if "loan agreement" in cleaned or "agreement" in cleaned:
        return "Loan Agreement"
    if "sanction" in cleaned:
        return "Sanction Letter"
    if "stamp" in cleaned:
        return "Stamp Duty"
    if "technical" in cleaned:
        return "Technical Report"
    if "valuation" in cleaned:
        return "Valuation Report"
    if "nach" in cleaned:
        return "NACH Form"

    return "None"


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

    raw_document_type = str(parsed.get("document_type") or "None")
    document_type = normalize_llm_document_type(raw_document_type)
    
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
        "Respond with TOON (Token-Oriented Object Notation) format only, no markdown, no json:\n"
        "document_type: \"...\"\n"
        "confidence: 0.0\n"
        "reason: \"short reason\"\n\n"
        "Page text:\n"
        f"{text}"
    )


def _parse_classifier_response(response_text: str) -> dict[str, Any] | None:
    cleaned = response_text.strip()
    if not cleaned:
        return None

    # Strip markdown code blocks (handling both toon, json, or generic code fences)
    fence_match = re.search(r"```(?:toon|json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        from toon import decode
        parsed = decode(cleaned)
        if isinstance(parsed, dict) and parsed.get("document_type"):
            return parsed
    except Exception:
        pass
    return None
