"""Field-level verification against Graviton ground-truth records."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Literal

from rapidfuzz import fuzz

from database.models import DocumentVerificationReport, FieldVerificationResult, GravitonRecord
from services.llm_verifier import llm_verify_field


def verify_aadhaar(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify Aadhaar by exact comparison of normalized 12-digit values."""
    extracted_digits = _digits(extracted)
    db_digits = _digits(db_value)
    if not _has_values(extracted_digits, db_digits):
        return _failed("aadhaar_number", extracted, db_value, "exact", "Aadhaar value missing")
    if not re.fullmatch(r"\d{12}", extracted_digits) or not re.fullmatch(r"\d{12}", db_digits):
        return _failed("aadhaar_number", extracted, db_value, "exact", "Aadhaar must be exactly 12 digits")
    return _exact_result("aadhaar_number", extracted, db_value, extracted_digits == db_digits)


def verify_pan(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify PAN by exact comparison after uppercasing and whitespace removal."""
    extracted_pan = _normalize_pan(extracted)
    db_pan = _normalize_pan(db_value)
    if not _has_values(extracted_pan, db_pan):
        return _failed("pan_number", extracted, db_value, "exact", "PAN value missing")
    if not _valid_pan(extracted_pan) or not _valid_pan(db_pan):
        return _failed("pan_number", extracted, db_value, "exact", "PAN must match ABCDE1234F format")
    return _exact_result("pan_number", extracted, db_value, extracted_pan == db_pan)


def verify_phone(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify phone numbers by exact comparison of normalized 10-digit values."""
    extracted_phone = _normalize_phone(extracted)
    db_phone = _normalize_phone(db_value)
    if not _has_values(extracted_phone, db_phone):
        return _failed("phone_number", extracted, db_value, "exact", "Phone value missing")
    if not re.fullmatch(r"\d{10}", extracted_phone) or not re.fullmatch(r"\d{10}", db_phone):
        return _failed("phone_number", extracted, db_value, "exact", "Phone must be exactly 10 digits")
    return _exact_result("phone_number", extracted, db_value, extracted_phone == db_phone)


def verify_date(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify dates by parsing supported formats and comparing date values."""
    extracted_date = _parse_supported_date(extracted)
    db_date = _parse_supported_date(db_value)
    if extracted_date is None or db_date is None:
        return _failed("date_of_birth", extracted, db_value, "exact", "Date missing or unsupported format")
    return _exact_result("date_of_birth", extracted, db_value, extracted_date == db_date)


def verify_amount(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify loan amounts numerically with a one percent tolerance."""
    extracted_amount = _parse_amount(extracted)
    db_amount = _parse_amount(db_value)
    if extracted_amount is None or db_amount is None:
        return _failed("loan_amount", extracted, db_value, "exact", "Amount missing or invalid")
    tolerance = abs(db_amount) * 0.01
    matched = abs(extracted_amount - db_amount) <= tolerance
    confidence = 1.0 if matched else max(0.0, 1.0 - (abs(extracted_amount - db_amount) / max(abs(db_amount), 1.0)))
    return FieldVerificationResult(
        field_name="loan_amount",
        extracted_value=extracted,
        db_value=db_value,
        match=matched,
        confidence=round(confidence, 3),
        method="exact",
        mismatch_reason=None if matched else "Amount differs by more than 1%",
    )


def verify_name(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify applicant names using rapidfuzz token-sort similarity."""
    return _fuzzy_result(
        field_name="applicant_name",
        extracted=extracted,
        db_value=db_value,
        scorer=fuzz.token_sort_ratio,
        threshold=85,
        reason="Name similarity below threshold",
    )


def verify_address(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify addresses using rapidfuzz token-set similarity with abbreviation normalization."""
    return _fuzzy_result(
        field_name="address",
        extracted=_normalize_address(extracted),
        db_value=_normalize_address(db_value),
        scorer=fuzz.token_set_ratio,
        threshold=75,
        reason="Address similarity below threshold",
        original_extracted=extracted,
        original_db_value=db_value,
    )


def verify_pincode(extracted: str, db_value: str) -> FieldVerificationResult:
    """Verify PIN codes by exact comparison of normalized 6-digit values."""
    extracted_pin = _digits(extracted)
    db_pin = _digits(db_value)
    if not _has_values(extracted_pin, db_pin):
        return _failed("pin_code", extracted, db_value, "exact", "PIN code value missing")
    if not re.fullmatch(r"\d{6}", extracted_pin) or not re.fullmatch(r"\d{6}", db_pin):
        return _failed("pin_code", extracted, db_value, "exact", "PIN code must be exactly 6 digits")
    return _exact_result("pin_code", extracted, db_value, extracted_pin == db_pin)


def verify_all_fields(extracted: dict, record: GravitonRecord) -> DocumentVerificationReport:
    """Verify all supported extracted fields against a Graviton record."""
    raw_results = [
        verify_aadhaar(_field(extracted, "aadhaar_number", "aadhaar"), record.aadhaar_number),
        verify_pan(_field(extracted, "pan_number", "pan"), record.pan_number),
        verify_phone(_field(extracted, "phone_number", "phone"), record.phone_number),
        verify_date(_field(extracted, "date_of_birth", "dob"), record.date_of_birth),
        verify_amount(_field(extracted, "loan_amount", "amount"), record.loan_amount),
        verify_name(_field(extracted, "applicant_name", "name"), record.applicant_name),
        verify_address(_field(extracted, "address"), record.address),
        verify_pincode(_field(extracted, "pin_code", "pincode"), record.pin_code),
    ]

    field_results = [_maybe_llm_review(result) for result in raw_results]
    matched_fields = sum(1 for result in field_results if result.match)
    failed_fields = [result.field_name for result in field_results if not result.match]
    needs_manual_review = any(result.confidence < 0.75 for result in field_results)

    return DocumentVerificationReport(
        application_id=record.application_id,
        overall_match=not failed_fields,
        total_fields_checked=len(field_results),
        matched_fields=matched_fields,
        failed_fields=failed_fields,
        field_results=field_results,
        needs_manual_review=needs_manual_review,
    )


def _maybe_llm_review(result: FieldVerificationResult) -> FieldVerificationResult:
    if result.confidence >= 0.85:
        return result
    return llm_verify_field(
        field_name=result.field_name,
        extracted_value=result.extracted_value,
        db_value=result.db_value,
        current_result=result,
    )


def _exact_result(field_name: str, extracted: Any, db_value: Any, matched: bool) -> FieldVerificationResult:
    return FieldVerificationResult(
        field_name=field_name,
        extracted_value=extracted,
        db_value=db_value,
        match=matched,
        confidence=1.0 if matched else 0.0,
        method="exact",
        mismatch_reason=None if matched else "Exact values do not match",
    )


def _failed(
    field_name: str,
    extracted: Any,
    db_value: Any,
    method: Literal["exact", "fuzzy", "llm"],
    reason: str,
) -> FieldVerificationResult:
    return FieldVerificationResult(
        field_name=field_name,
        extracted_value=extracted,
        db_value=db_value,
        match=False,
        confidence=0.0,
        method=method,
        mismatch_reason=reason,
    )


def _fuzzy_result(
    *,
    field_name: str,
    extracted: str,
    db_value: str,
    scorer: Callable[[str, str], float],
    threshold: float,
    reason: str,
    original_extracted: str | None = None,
    original_db_value: str | None = None,
) -> FieldVerificationResult:
    if not _has_values(extracted, db_value):
        return _failed(
            field_name,
            original_extracted if original_extracted is not None else extracted,
            original_db_value if original_db_value is not None else db_value,
            "fuzzy",
            f"{field_name} value missing",
        )
    score = float(scorer(extracted, db_value))
    matched = score >= threshold
    return FieldVerificationResult(
        field_name=field_name,
        extracted_value=original_extracted if original_extracted is not None else extracted,
        db_value=original_db_value if original_db_value is not None else db_value,
        match=matched,
        confidence=round(score / 100.0, 3),
        method="fuzzy",
        mismatch_reason=None if matched else reason,
    )


def _field(extracted: dict, *names: str) -> str:
    for name in names:
        value = extracted.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _has_values(*values: str) -> bool:
    return all(str(value or "").strip() for value in values)


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_pan(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _valid_pan(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value))


def _normalize_phone(value: Any) -> str:
    digits = _digits(value)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    while digits.startswith("0") and len(digits) > 10:
        digits = digits[1:]
    return digits[-10:] if len(digits) >= 10 else digits


def _parse_supported_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_amount(value: Any) -> float | None:
    text = str(value or "").lower().strip()
    if not text:
        return None
    multiplier = 1.0
    if re.search(r"\b(?:lakh|lac)\b", text):
        multiplier = 100000.0
    cleaned = re.sub(r"(?:rs\.?|inr|₹|,|\s+)", "", text)
    cleaned = re.sub(r"(?:lakh|lac)s?", "", cleaned)
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return float(match.group(0)) * multiplier


def _normalize_address(value: Any) -> str:
    text = str(value or "").lower()
    replacements = {
        r"\bst\b": "street",
        r"\bstreet\b": "street",
        r"\brd\b": "road",
        r"\broad\b": "road",
        r"\bnr\b": "near",
        r"\bnear\b": "near",
        r"\bopp\b": "opposite",
        r"\bopposite\b": "opposite",
        r"\bdist\b": "district",
        r"\bdistrict\b": "district",
        r"\bnagar\b": "ngr",
        r"\bngr\b": "ngr",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
