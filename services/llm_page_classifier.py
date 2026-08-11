"""Local LLM fallback for page-level document classification."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from services.config import get_bool, get_float, get_int
from services.document_classifier import registry_document_types
from services.llm_client import call_llm_api

VALID_DOCUMENT_TYPES = tuple(registry_document_types(include_unknown=True))

_MAX_TEXT_CHARS = 3500

# Hard evidence phrases that must appear in OCR before the LLM label is trusted.
# Form 97 / Form 60 is ONLY a non-PAN declaration — never a catch-all loan page.
_EVIDENCE_REQUIRED: dict[str, tuple[str, ...]] = {
    "Form 97": (
        "form 97",
        "form no 97",
        "form no. 97",
        "form60",
        "form 60",
        "form no 60",
        "form no. 60",
        "declaration in lieu of pan",
        "declaration in lieu of permanent account",
    ),
    "PAN Card": (
        "permanent account number",
        "income tax department",
        "pan card",
        "आयकर विभाग",
    ),
    "Aadhaar": (
        "aadhaar",
        "aadhar",
        "uidai",
        "unique identification",
        "आधार",
        "यूआईडीएआई",
    ),
    "Voter ID": (
        "election commission",
        "voter id",
        "electors photo identity",
        "epic",
        "मतदाता",
    ),
    "CIBIL Report": ("cibil", "transunion"),
    "CRIF Report": ("crif", "high mark"),
    "CERSAI Report": ("cersai", "central registry of securitisation", "debtor based search"),
    "Income Tax Return": (
        "income tax return",
        "itr acknowledgement",
        "assessment year",
        "return of income",
        "total income",
    ),
    "Stamp Duty": (
        "stamp duty",
        "non judicial",
        "non-judicial",
        "e-stamp",
        "stamp paper",
        "india non judicial",
        "गैर न्यायिक",
    ),
    "Utility Bill": (
        "electricity bill",
        "water bill",
        "gas bill",
        "utility bill",
        "vidyut",
        "jvvnl",
        "consumer no",
        "due date",
        "बिजली",
        "विद्युत",
        "bill month",
        "bill month",
        "bill number",
    ),
}


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


def llm_classifier_max_pages_per_file() -> int:
    return get_int("LLM_CLASSIFIER_MAX_PAGES_PER_FILE", 300, minimum=0)


def llm_classifier_ocr_threshold() -> float:
    """OCR confidence below which a known page may trigger LLM classification."""
    return get_float("LLM_CLASSIFIER_OCR_THRESHOLD", 0.65, minimum=0.0, maximum=1.0)


def llm_classification_trigger(
    document_type: object,
    ocr_confidence: float | None,
) -> str | None:
    """Return why this page is eligible for LLM classification, if at all.

    LLM classification is deliberately limited to pages the deterministic
    classifier could not identify and scanned pages whose OCR confidence is
    below the configured threshold.  Deterministic classification confidence
    alone is not an eligibility signal.
    """
    normalized_type = str(document_type or "").strip().casefold()
    if normalized_type in {"", "none", "unknown", "null"}:
        return "unknown_document_type"

    if ocr_confidence is None:
        return None
    try:
        confidence = float(ocr_confidence)
    except (TypeError, ValueError):
        return None
    if confidence < llm_classifier_ocr_threshold():
        return "low_ocr_confidence"
    return None


def is_llm_classification_candidate(
    document_type: object,
    ocr_confidence: float | None,
) -> bool:
    """Return whether this page is allowed to reach an LLM classifier."""
    return llm_classification_trigger(document_type, ocr_confidence) is not None


def needs_llm_classification(
    rule_result: dict[str, Any],
    ocr_confidence: float | None,
) -> bool:
    return is_llm_classification_candidate(
        rule_result.get("document_type"),
        ocr_confidence,
    )


def llm_prediction_has_evidence(document_type: str, text: str) -> bool:
    """Reject LLM labels that are not corroborated by OCR phrases."""
    normalized_type = normalize_llm_document_type(document_type)
    if normalized_type in {"", "None"}:
        return True
    required = _EVIDENCE_REQUIRED.get(normalized_type)
    if not required:
        return True
    haystack = _normalize_evidence_text(text)
    return any(_contains_evidence(haystack, phrase) for phrase in required)


def normalize_llm_document_type(doc_type: str) -> str:
    """Normalize and map loose LLM document type names to exact registry values."""
    cleaned = str(doc_type or "").strip().lower()
    if not cleaned or cleaned in {"none", "unknown", "null"}:
        return "None"

    # Direct match check (ignoring case/whitespace)
    for valid_type in VALID_DOCUMENT_TYPES:
        if valid_type.strip().lower() == cleaned:
            return valid_type

    # Prefer specific aliases before broad substring matches.
    if "form 97" in cleaned or "form97" in cleaned or "form 60" in cleaned or "form60" in cleaned:
        return "Form 97"
    if "aadhaar" in cleaned or "aadhar" in cleaned:
        return "Aadhaar"
    if cleaned in {"pan", "pan card"} or "pan card" in cleaned or cleaned.endswith(" pan"):
        return "PAN Card"
    if "passport" in cleaned:
        return "Passport"
    if "driving" in cleaned or "licence" in cleaned or "license" in cleaned:
        return "Driving License"
    if "voter" in cleaned:
        return "Voter ID"
    if "mnrega" in cleaned or "nrega" in cleaned:
        return "MNREGA Job Card"
    if "npr" in cleaned:
        return "NPR Letter"
    if "electricity" in cleaned or "utility bill" in cleaned or "water bill" in cleaned or "gas bill" in cleaned:
        return "Utility Bill"
    if "bank statement" in cleaned or "account statement" in cleaned:
        return "Bank Statement"
    if "passbook" in cleaned or "pass book" in cleaned:
        return "Passbook"
    if "cheque" in cleaned:
        return "Cheque"
    if cleaned == "pdc" or "post dated" in cleaned or "post-dated" in cleaned:
        return "PDC"
    if "cibil" in cleaned:
        return "CIBIL Report"
    if "crif" in cleaned:
        return "CRIF Report"
    if "cersai" in cleaned:
        return "CERSAI Report"
    if "facility agreement" in cleaned:
        return "Facility Agreement"
    if "loan agreement" in cleaned:
        return "Loan Agreement"
    if "sanction" in cleaned:
        return "Sanction Letter"
    if "stamp" in cleaned or "non judicial" in cleaned or "non-judicial" in cleaned:
        return "Stamp Duty"
    if "technical" in cleaned:
        return "Technical Report"
    if "valuation" in cleaned:
        return "Valuation Report"
    if "nach" in cleaned:
        return "NACH Form"
    if "application form" in cleaned or "loan application" in cleaned:
        return "Application Form"
    if cleaned == "cam" or "credit approval memo" in cleaned or "credit appraisal memo" in cleaned:
        return "CAM"

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

    if not llm_prediction_has_evidence(document_type, cleaned):
        return {
            "document_type": "None",
            "confidence": 0.0,
            "reason": f"Rejected {document_type}: OCR lacks required evidence phrases",
            "rejected_document_type": document_type,
        }

    confidence = parsed.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.85

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
        "Use \"None\" when the page is blank, unreadable, or you are unsure.\n"
        "CRITICAL: \"Form 97\" (and old \"Form 60\") is ONLY a declaration in lieu of PAN. "
        "Choose Form 97 only when the page title/body literally says Form 97 / Form No. 97 / "
        "Form 60 / declaration in lieu of PAN. Never use Form 97 for loan agreements, "
        "sanction letters, stamp papers, electricity bills, application forms, or bureau reports.\n"
        "If a PAN card image/text is present, choose \"PAN Card\", not Form 97.\n"
        "Choose \"Income Tax Return\" only when the page contains return-specific evidence such as "
        "Income Tax Return, ITR acknowledgement, assessment year, return of income, or total income. "
        "A PAN heading and PAN number alone are \"PAN Card\".\n"
        "Electricity/water/gas invoices are \"Utility Bill\". Non-judicial stamp papers are \"Stamp Duty\".\n"
        "Do not merge credit bureaus: choose \"CIBIL Report\" only for TransUnion CIBIL/CIBIL pages, "
        "and choose \"CRIF Report\" only for CRIF High Mark/CRIF pages.\n"
        "Choose \"CERSAI Report\" for CERSAI, debtor-based search, or Central Registry of Securitisation pages.\n"
        "Do not merge bank documents: choose \"Passbook\" for passbook/pass book pages, "
        "\"Cheque\" for cheque or cancelled cheque pages, \"PDC\" only for post-dated/security cheques, "
        "and \"Bank Statement\" only for statement/account-statement pages.\n"
        "Respond with TOON (Token-Oriented Object Notation) format only, no markdown, no json:\n"
        "document_type: \"...\"\n"
        "confidence: 0.9\n"
        "reason: \"short reason\"\n\n"
        "Page text:\n"
        f"{text}"
    )


def _normalize_evidence_text(value: str) -> str:
    lowered = unicodedata.normalize("NFKC", str(value or "")).casefold()
    lowered = lowered.replace("\u2013", "-").replace("\u2014", "-")
    normalized = "".join(
        character
        if character.isalnum() or character == "." or unicodedata.category(character).startswith("M")
        else " "
        for character in lowered
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_evidence(haystack: str, phrase: str) -> bool:
    needle = _normalize_evidence_text(phrase)
    if not needle:
        return False
    return needle in haystack


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

    # Small local models occasionally return valid JSON despite an explicit
    # TOON-only instruction. Accept the equivalent object instead of discarding
    # an otherwise usable classification.
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and parsed.get("document_type"):
            return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return None
