"""Refine OCR field assignments with deterministic guards and optional Ollama."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from requests import RequestException

from services.config import get_bool
from services.structured_llm_classifier import (
    DEFAULT_MODEL,
    _call_ollama_generate,
    _classifier_base_url,
    _classifier_timeout_seconds,
    _is_ollama_available,
)

_MAX_TEXT_CHARS = 3500

_LABEL_VALUES = {
    "date of birth",
    "dob",
    "name",
    "applicant name",
    "borrower name",
    "account holder",
    "account holder name",
    "address",
    "landmark",
    "locality",
    "city",
    "city / district",
    "district",
    "pin code",
    "landmark locality city / district pin code",
}

_PROTECTED_EXACT_FIELDS = {
    "aadhaar_number",
    "account_number",
    "ifsc",
    "pan_number",
}

_EXPECTED_FIELDS = {
    "Aadhaar": ("applicant_name", "aadhaar_number", "dob", "address", "pin_code"),
    "Bank Statement": ("account_holder_name", "account_number", "ifsc", "statement_period_start", "statement_period_end"),
    "CIBIL Report": ("applicant_name", "credit_score", "report_date"),
    "CRIF Report": ("applicant_name", "credit_score", "report_date"),
    "Driving License": ("applicant_name", "dl_number", "dob", "validity_date", "address"),
    "Loan Agreement": ("borrower_name", "loan_amount", "tenure", "emi", "roi", "agreement_date"),
    "PAN": ("applicant_name", "father_name", "dob", "pan_number"),
    "PAN Card": ("applicant_name", "father_name", "dob", "pan_number"),
    "Sanction Letter": ("applicant_name", "loan_amount", "tenure", "emi", "roi"),
    "Voter ID": ("applicant_name", "voter_id_number", "dob", "address"),
}

_PRIMARY_FIELDS = {
    "Aadhaar": ("applicant_name", "address"),
    "Bank Statement": ("account_holder_name",),
    "CIBIL Report": ("applicant_name",),
    "CRIF Report": ("applicant_name",),
    "Driving License": ("applicant_name",),
    "PAN": ("applicant_name",),
    "PAN Card": ("applicant_name",),
    "Voter ID": ("applicant_name",),
}


def refine_field_assignments(
    *,
    document_type: str,
    ocr_text: str,
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    """Clean impossible field values and ask Ollama only when assignment is weak."""
    cleaned_fields, deterministic_changes = _remove_suspicious_values(extracted_fields)
    if not _should_call_llm(document_type, cleaned_fields, deterministic_changes):
        return _with_assignment_metadata(cleaned_fields, deterministic_changes, llm_metadata=None)

    llm_fields, llm_metadata = _assign_with_llm(
        document_type=document_type,
        ocr_text=ocr_text,
        extracted_fields=cleaned_fields,
    )
    if not llm_fields:
        return _with_assignment_metadata(cleaned_fields, deterministic_changes, llm_metadata=llm_metadata)

    refined_fields, llm_changes = _merge_llm_fields(cleaned_fields, llm_fields)
    return _with_assignment_metadata(
        refined_fields,
        deterministic_changes,
        llm_metadata={**(llm_metadata or {}), "changes": llm_changes},
    )


def is_suspicious_assignment(field_name: str, value: Any) -> bool:
    """Return True when a value looks like a label, placeholder, or wrong field."""
    text = str(value or "").strip()
    if not text:
        return False
    normalized = _normalize_text(text)
    if normalized in _LABEL_VALUES:
        return True
    if field_name in {"applicant_name", "borrower_name", "account_holder_name"}:
        return _looks_like_non_name(normalized)
    if field_name == "address":
        return _looks_like_address_placeholder(normalized)
    return False


def _remove_suspicious_values(fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    cleaned = dict(fields)
    changes: dict[str, dict[str, Any]] = {}
    for field_name, value in list(_public_fields(fields).items()):
        if is_suspicious_assignment(field_name, value):
            cleaned[field_name] = None
            changes[field_name] = {"from": value, "to": None, "reason": "label_or_placeholder_value"}
    return cleaned, changes


def _should_call_llm(
    document_type: str,
    fields: dict[str, Any],
    deterministic_changes: dict[str, dict[str, Any]],
) -> bool:
    if not get_bool("ENABLE_LLM_FIELD_ASSIGNMENT", False):
        return False
    if not document_type or document_type in {"Unknown", "Property Image", "OCR Skipped"}:
        return False
    if deterministic_changes:
        return True
    primary_fields = _PRIMARY_FIELDS.get(document_type, ())
    return any(fields.get(field) in (None, "", [], {}) for field in primary_fields)


def _assign_with_llm(
    *,
    document_type: str,
    ocr_text: str,
    extracted_fields: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    base_url = _classifier_base_url()
    timeout = _classifier_timeout_seconds()
    metadata = {"source": "ollama", "model": _model(), "endpoint": base_url}
    if not _is_ollama_available(base_url, timeout):
        return None, {**metadata, "error": "Ollama unavailable"}

    try:
        response_text = _call_ollama_generate(
            base_url=base_url,
            model=_model(),
            prompt=_build_prompt(document_type, ocr_text, extracted_fields),
            timeout=timeout,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, RequestException) as exc:
        return None, {**metadata, "error": str(exc)}

    parsed = _parse_json_object(response_text or "")
    if not parsed:
        return None, {**metadata, "error": "Malformed LLM field assignment response"}
    fields = parsed.get("fields")
    if not isinstance(fields, dict):
        return None, {**metadata, "error": "LLM response did not include fields"}
    return fields, {
        **metadata,
        "reason": str(parsed.get("reason") or "").strip() or None,
        "confidence": _coerce_confidence(parsed.get("confidence")),
    }


def _build_prompt(document_type: str, ocr_text: str, extracted_fields: dict[str, Any]) -> str:
    expected_fields = ", ".join(_EXPECTED_FIELDS.get(document_type, ())) or "relevant fields"
    return (
        "You are assigning OCR text into JSON fields for Indian loan documents.\n"
        "Correct only field assignment mistakes. Do not invent values.\n"
        "If a value is not clearly present in the OCR text, return null.\n"
        "Never guess ID numbers such as PAN, Aadhaar, account number, or IFSC.\n"
        "Bad examples: applicant_name must not be 'Date of Birth'; address must not be "
        "'Landmark Locality City / District Pin Code'.\n\n"
        "Return only JSON in this shape:\n"
        '{"fields": {"field_name": "value or null"}, "reason": "short reason", "confidence": 0.0}\n\n'
        f"Document type: {document_type}\n"
        f"Expected fields: {expected_fields}\n"
        "Current extracted fields:\n"
        f"{json.dumps(_public_fields(extracted_fields), ensure_ascii=False, sort_keys=True)}\n\n"
        "OCR text:\n"
        f"{(ocr_text or '').strip()[:_MAX_TEXT_CHARS]}"
    )


def _merge_llm_fields(
    current_fields: dict[str, Any],
    llm_fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    merged = dict(current_fields)
    changes: dict[str, dict[str, Any]] = {}
    for field_name, proposed_value in llm_fields.items():
        field_name = str(field_name)
        if field_name.startswith("_"):
            continue
        current_value = merged.get(field_name)
        cleaned_value = _clean_llm_value(field_name, proposed_value)
        if cleaned_value in (None, ""):
            continue
        if _can_replace(field_name, current_value):
            merged[field_name] = cleaned_value
            changes[field_name] = {"from": current_value, "to": cleaned_value}
    return merged, changes


def _can_replace(field_name: str, current_value: Any) -> bool:
    if field_name in _PROTECTED_EXACT_FIELDS and current_value not in (None, "", [], {}):
        return False
    return current_value in (None, "", [], {}) or is_suspicious_assignment(field_name, current_value)


def _clean_llm_value(field_name: str, value: Any) -> Any:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    if not text or is_suspicious_assignment(field_name, text):
        return None
    if field_name == "pan_number":
        normalized = re.sub(r"\s+", "", text).upper()
        return normalized if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", normalized) else None
    if field_name == "aadhaar_number":
        digits = re.sub(r"\D", "", text)
        return digits if re.fullmatch(r"\d{12}", digits) else None
    if field_name == "ifsc":
        normalized = re.sub(r"\s+", "", text).upper()
        return normalized if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", normalized) else None
    return text


def _with_assignment_metadata(
    fields: dict[str, Any],
    deterministic_changes: dict[str, dict[str, Any]],
    *,
    llm_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if not deterministic_changes and not llm_metadata:
        return fields
    updated = dict(fields)
    updated["_field_assignment"] = {
        "deterministic_changes": deterministic_changes,
        "llm": llm_metadata,
    }
    return updated


def _parse_json_object(response_text: str) -> dict[str, Any] | None:
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
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _public_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in (fields or {}).items() if not str(key).startswith("_")}


def _model() -> str:
    return os.getenv("LLM_FIELD_ASSIGNMENT_MODEL") or os.getenv("OLLAMA_CLASSIFIER_MODEL") or DEFAULT_MODEL


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip(" :,-")


def _looks_like_non_name(normalized: str) -> bool:
    blocked = {"account", "address", "date of birth", "dob", "ifsc", "loan amount", "pin code"}
    return normalized in blocked


def _looks_like_address_placeholder(normalized: str) -> bool:
    placeholder_words = {"city", "code", "district", "landmark", "locality", "pin"}
    words = set(re.findall(r"[a-z]+", normalized))
    return len(words & placeholder_words) >= 4 and not re.search(r"\d", normalized)


def _coerce_confidence(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None
