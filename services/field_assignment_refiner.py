"""Refine OCR field assignments with deterministic guards and optional LLM."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from requests import RequestException
from toon import decode, encode

from services.config import get_bool
from services.llm_client import llm_provider
from services.person_names import canonicalize_person_name, is_name_field
from services.validation_gates import is_aadhaar_verification_appendix
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
    "a/c holder name",
    "a/c number",
    "a/c numeber",
    "account number",
    "account type",
    "bank name",
    "bank branch",
    "खाता प्रकार",
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
    "CERSAI Report": ("applicant_name", "pan_number", "dob", "search_reference_number", "transaction_id", "report_date", "search_result"),
    "Cheque": ("account_holder_name", "account_number", "cheque_number", "ifsc", "cheque_date", "amount", "is_cancelled"),
    "CIBIL Report": ("applicant_name", "credit_score", "report_date"),
    "CRIF Report": ("applicant_name", "credit_score", "report_date"),
    "Driving License": ("applicant_name", "dl_number", "dob", "date_of_issue", "validity_date", "address"),
    "Loan Agreement": ("borrower_name", "loan_amount", "tenure", "emi", "roi", "agreement_date"),
    "PAN": ("applicant_name", "father_name", "dob", "pan_number"),
    "PAN Card": ("applicant_name", "father_name", "dob", "pan_number"),
    "Passbook": ("account_holder_name", "account_number", "ifsc", "customer_id", "passbook_issue_date"),
    "Sanction Letter": ("applicant_name", "loan_amount", "tenure", "emi", "roi"),
    "Voter ID": ("applicant_name", "voter_id_number", "dob", "address"),
}

_PRIMARY_FIELDS = {
    "Aadhaar": ("applicant_name", "address"),
    "Bank Statement": ("account_holder_name",),
    "CERSAI Report": ("applicant_name",),
    "Cheque": ("cheque_number", "account_number"),
    "CIBIL Report": ("applicant_name",),
    "CRIF Report": ("applicant_name",),
    "Driving License": ("applicant_name",),
    "PAN": ("applicant_name",),
    "PAN Card": ("applicant_name",),
    "Passbook": ("account_holder_name", "account_number"),
    "Voter ID": ("applicant_name",),
}


def refine_field_assignments(
    *,
    document_type: str,
    ocr_text: str,
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    """Clean impossible field values and ask the LLM only when assignment is weak."""
    if document_type == "Aadhaar" and (
        extracted_fields.get("_aadhaar_verification_appendix") is True
        or is_aadhaar_verification_appendix(ocr_text)
    ):
        # The certificate subject contains the signer's postal code.  Asking
        # the LLM to fill missing Aadhaar fields can misassign it to the holder.
        private_fields = {
            key: value
            for key, value in extracted_fields.items()
            if str(key).startswith("_")
        }
        return {**private_fields, "_aadhaar_verification_appendix": True}

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
    if is_name_field(field_name):
        return not canonicalize_person_name(text).valid or _looks_like_non_name(normalized)
    if field_name in {"address", "current_address", "permanent_address", "communication_address"}:
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
    if document_type == "CERSAI Report":
        # CERSAI result pages can contain every loan party plus the registry's
        # corporate PAN.  A generic field model must not choose one of those as
        # the debtor when deterministic Search Criteria extraction is missing.
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
    provider = llm_provider()
    metadata = {"source": provider, "model": _model(), "endpoint": base_url}
    if provider == "ollama" and not _is_ollama_available(base_url, timeout):
        return None, {**metadata, "error": "LLM unavailable"}

    try:
        response_text = _call_ollama_generate(
            base_url=base_url,
            model=_model(),
            prompt=_build_prompt(document_type, ocr_text, extracted_fields),
            timeout=timeout,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, RequestException) as exc:
        return None, {**metadata, "error": str(exc)}

    parsed = _parse_toon_object(response_text or "")
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
        "Return only TOON in this shape:\n"
        "fields:\n  field_name: value or null\nreason: short reason\nconfidence: 0.0\n\n"
        f"Document type: {document_type}\n"
        f"Expected fields: {expected_fields}\n"
        "Current extracted fields (TOON):\n"
        f"{encode(_public_fields(extracted_fields))}\n\n"
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


def _parse_toon_object(response_text: str) -> dict[str, Any] | None:
    stripped = response_text.strip()
    if not stripped:
        return None
    fence_match = re.search(r"```(?:toon|json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    candidate = fence_match.group(1).strip() if fence_match else stripped

    def _as_dict(value: Any) -> dict[str, Any] | None:
        return value if isinstance(value, dict) else None

    def _try_json(text: str) -> dict[str, Any] | None:
        try:
            return _as_dict(json.loads(text))
        except Exception:  # noqa: BLE001
            pass
        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            return None
        try:
            return _as_dict(json.loads(json_match.group(0)))
        except Exception:  # noqa: BLE001
            return None

    # JSON-looking payloads first: toon.decode() can "succeed" on JSON while
    # producing a useless key/value map, which would skip refinement entirely.
    if candidate.lstrip().startswith(("{", "[")):
        parsed = _try_json(candidate)
        if parsed is not None:
            return parsed

    try:
        parsed = _as_dict(decode(candidate))
        if parsed is not None:
            return parsed
    except Exception:  # noqa: BLE001
        pass

    return _try_json(candidate)


def _public_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in (fields or {}).items() if not str(key).startswith("_")}


def _model() -> str:
    return os.getenv("LLM_FIELD_ASSIGNMENT_MODEL") or os.getenv("OLLAMA_CLASSIFIER_MODEL") or DEFAULT_MODEL


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip(" :,-")


def _looks_like_non_name(normalized: str) -> bool:
    blocked = {
        "account", "address", "date of birth", "dob", "ifsc", "loan amount", "pin code",
        "source", "financer", "issuing authority", "ration card", "driving", "phone no",
        "c/o", "s/o", "w/o", "d/o", "c/o , s/o", "s/o , c/o", "relationship", "relations",
        "master policy holder", "name of grantor",
    }
    if normalized in blocked:
        return True
    if re.fullmatch(r"(?:c/?o|s/?o|w/?o|d/?o)(?:\s*[,/]\s*(?:c/?o|s/?o|w/?o|d/?o))*", normalized):
        return True
    compact = re.sub(r"[^a-z]", "", normalized)
    return compact in {"acnumber", "acnumeber", "accountnumber", "accountno", "coso", "soco", "null", "none"}


def _looks_like_address_placeholder(normalized: str) -> bool:
    if re.fullmatch(
        r"page\s*(?:no\.?\s*)?\d+\s*(?:of|/)\s*\d+\s*[.;:]?",
        normalized,
        re.IGNORECASE,
    ):
        return True
    placeholder_words = {"city", "code", "district", "landmark", "locality", "pin"}
    words = set(re.findall(r"[a-z]+", normalized))
    if len(words & placeholder_words) >= 4 and not re.search(r"\d", normalized):
        return True
    form_label_patterns = (
        r"\baadhaar\s+no\b",
        r"\bdriving\s+licen[cs]e\b",
        r"\bprofessionally\s+qualified\b",
        r"\bbusiness\s+constitution\b",
        r"\b(?:graduate|postgraduate|post\s+graduate)\b",
        r"\b(?:mobile|telephone|whatsapp)(?:\s+(?:number|no|contact))?\b",
    )
    return sum(bool(re.search(pattern, normalized)) for pattern in form_label_patterns) >= 2


def _coerce_confidence(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None
