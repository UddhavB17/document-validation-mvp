"""Recover strongly evidenced trusted fields from raw OCR text.

The resolver never copies a value from trusted JSON into extracted output.  It
uses that value only to locate an independently observed OCR token inside an
appropriate labelled field block, and abstains when the evidence is weak or
ambiguous.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from services.field_verification import (
    verify_aadhaar,
    verify_address,
    verify_date,
    verify_name,
    verify_pan,
    verify_phone,
    verify_pincode,
)
from services.person_names import is_person_name_candidate


RECOVERABLE_TRUSTED_FIELDS = frozenset(
    {
        "aadhaar_number",
        "pan_number",
        "phone_number",
        "date_of_birth",
        "applicant_name",
        "address",
        "pin_code",
    }
)

_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}"
    r"|\d{1,2}(?:st|nd|rd|th)?[\s\-/]+[A-Za-z]+[\s\-/]+\d{4}"
    r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_PAN_PATTERN = re.compile(r"\b[A-Z]{5}\s*\d{4}\s*[A-Z]\b", re.IGNORECASE)
_AADHAAR_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]?){11}\d(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d(?:[\s-]?\d){8}(?!\d)")
_PIN_PATTERN = re.compile(r"(?<!\d)[1-8]\d{5}(?!\d)")

_DOB_LABEL = re.compile(
    r"\b(?:date\s+of\s+birth|birth\s+date|d\s*\.?\s*o\s*\.?\s*b\.?|dob)\b",
    re.IGNORECASE,
)
_PAN_LABEL = re.compile(r"\b(?:permanent\s+account\s+number|pan(?:\s+number|\s+no\.?)?)\b", re.I)
_AADHAAR_LABEL = re.compile(r"\b(?:aadhaar|aadhar|uid)(?:\s+number|\s+no\.?)?\b", re.I)
_PHONE_LABEL = re.compile(r"\b(?:mobile|phone|contact)(?:\s+number|\s+no\.?)?\b", re.I)
_PIN_LABEL = re.compile(r"\b(?:pin|postal|zip)(?:\s+code|\s+number|\s+no\.?)?\b", re.I)
_NAME_LABEL = re.compile(
    r"\b(?:(?:applicant|borrower|customer|account\s+holder|card\s+holder|"
    r"licen[cs]e\s+holder)\s+)?name\b",
    re.IGNORECASE,
)
_ADDRESS_LABEL = re.compile(
    r"\b(?:(?:current|permanent|communication|residential|mailing)\s+)?address\b",
    re.IGNORECASE,
)
_NEXT_FIELD_LABEL = re.compile(
    r"^\s*(?:name|applicant\s+name|date\s+of\s+birth|dob|pan|aadhaar|aadhar|"
    r"mobile|phone|gender|signature|date\s+of\s+issue|validity|account\s+(?:no|number))\b",
    re.IGNORECASE,
)
_RELATED_NAME_LABEL = re.compile(
    r"\b(?:father|mother|husband|wife|nominee|guarantor|co[-\s]?applicant)\b",
    re.IGNORECASE,
)
_UNRELATED_ADDRESS_LABEL = re.compile(
    r"\b(?:property|branch|bank|office|employer|guarantor|nominee)\s+address\b",
    re.IGNORECASE,
)

_ADDRESS_GENERIC_TOKENS = {
    "address",
    "current",
    "permanent",
    "communication",
    "residential",
    "mailing",
    "india",
    "state",
    "district",
    "dist",
    "road",
    "street",
    "village",
    "post",
    "po",
    "so",
    "wo",
    "do",
    "co",
}


def resolve_trusted_candidate(
    field: str,
    expected_value: Any,
    text: str,
) -> dict[str, Any] | None:
    """Return one strongly supported OCR candidate for a trusted field.

    The returned ``observed_value`` is always text found in ``text``.  ``None``
    means the OCR did not contain a sufficiently anchored, unique candidate.
    """
    field_key = str(field or "").strip().casefold()
    expected = str(expected_value or "").strip()
    if field_key not in RECOVERABLE_TRUSTED_FIELDS or not expected or not str(text or "").strip():
        return None

    if field_key == "date_of_birth":
        return _resolve_pattern_candidate(
            text,
            expected,
            label=_DOB_LABEL,
            pattern=_DATE_PATTERN,
            verifier=verify_date,
            max_lines=8,
            anchor="date_of_birth_label",
        )
    if field_key == "pan_number":
        return _resolve_pattern_candidate(
            text,
            expected,
            label=_PAN_LABEL,
            pattern=_PAN_PATTERN,
            verifier=verify_pan,
            max_lines=4,
            anchor="pan_label",
        )
    if field_key == "aadhaar_number":
        return _resolve_pattern_candidate(
            text,
            expected,
            label=_AADHAAR_LABEL,
            pattern=_AADHAAR_PATTERN,
            verifier=verify_aadhaar,
            max_lines=4,
            anchor="aadhaar_label",
        )
    if field_key == "phone_number":
        return _resolve_pattern_candidate(
            text,
            expected,
            label=_PHONE_LABEL,
            pattern=_PHONE_PATTERN,
            verifier=verify_phone,
            max_lines=3,
            anchor="phone_label",
        )
    if field_key == "pin_code":
        return _resolve_pattern_candidate(
            text,
            expected,
            label=_PIN_LABEL,
            pattern=_PIN_PATTERN,
            verifier=verify_pincode,
            max_lines=3,
            anchor="pin_code_label",
        )
    if field_key == "applicant_name":
        return _resolve_name(text, expected)
    if field_key == "address":
        return _resolve_address(text, expected)
    return None


def _resolve_pattern_candidate(
    text: str,
    expected: str,
    *,
    label: re.Pattern[str],
    pattern: re.Pattern[str],
    verifier: Callable[[str, str], Any],
    max_lines: int,
    anchor: str,
) -> dict[str, Any] | None:
    matches: list[tuple[str, int]] = []
    for block in _label_blocks(text, label, max_lines=max_lines):
        for match in pattern.finditer(block["text"]):
            observed = _clean_observed(match.group(0))
            verification = verifier(observed, expected)
            if verification.match and float(verification.confidence) >= 0.95:
                matches.append((observed, int(block["line_number"])))
    unique = _unique_candidates(matches)
    if len(unique) != 1:
        return None
    observed, line_number = unique[0]
    return {
        "observed_value": observed,
        "confidence": 0.98,
        "anchor": anchor,
        "line_number": line_number,
        "match_method": "normalized_exact",
    }


def _resolve_name(text: str, expected: str) -> dict[str, Any] | None:
    if not is_person_name_candidate(expected):
        return None
    matches: list[tuple[str, int]] = []
    for block in _label_blocks(
        text,
        _NAME_LABEL,
        max_lines=2,
        reject_label=_RELATED_NAME_LABEL,
        stop_at_next_field=True,
    ):
        observed = _find_expected_span(block["text"], expected)
        if observed is None:
            expected_compact = _compact(expected)
            for line in block["parts"]:
                cleaned = _clean_observed(line)
                if expected_compact and _compact(cleaned) == expected_compact:
                    observed = cleaned
                    break
        if observed is None or not is_person_name_candidate(observed):
            continue
        result = verify_name(observed, expected)
        if result.match and float(result.confidence) >= 0.95:
            matches.append((observed, int(block["line_number"])))
    unique = _unique_candidates(matches)
    if len(unique) != 1:
        return None
    observed, line_number = unique[0]
    return {
        "observed_value": observed,
        "confidence": 0.97,
        "anchor": "applicant_name_label",
        "line_number": line_number,
        "match_method": "normalized_exact",
    }


def _resolve_address(text: str, expected: str) -> dict[str, Any] | None:
    blocks = _label_blocks(
        text,
        _ADDRESS_LABEL,
        max_lines=6,
        reject_label=_UNRELATED_ADDRESS_LABEL,
        stop_at_next_field=True,
    )
    matches: list[tuple[str, int, float]] = []
    for block in blocks:
        exact = _find_expected_span(block["text"], expected)
        if exact is not None:
            matches.append((exact, int(block["line_number"]), 0.97))
            continue

        best: tuple[str, int, float] | None = None
        parts = [part for part in block["parts"] if part]
        for end in range(1, len(parts) + 1):
            candidate = _clean_observed(" ".join(parts[:end]))
            score = _address_recovery_score(candidate, expected)
            if score is None:
                continue
            item = (candidate, int(block["line_number"]), score)
            if best is None or (item[2], -len(item[0])) > (best[2], -len(best[0])):
                best = item
        if best is not None:
            matches.append(best)

    by_value: dict[str, tuple[str, int, float]] = {}
    for observed, line_number, confidence in matches:
        key = _compact(observed)
        current = by_value.get(key)
        if current is None or confidence > current[2]:
            by_value[key] = (observed, line_number, confidence)
    if len(by_value) != 1:
        return None
    observed, line_number, confidence = next(iter(by_value.values()))
    return {
        "observed_value": observed,
        "confidence": round(confidence, 3),
        "anchor": "address_label",
        "line_number": line_number,
        "match_method": "normalized_exact" if confidence >= 0.97 else "strong_address_match",
    }


def _label_blocks(
    text: str,
    label: re.Pattern[str],
    *,
    max_lines: int,
    reject_label: re.Pattern[str] | None = None,
    stop_at_next_field: bool = False,
) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(text or "").splitlines()]
    blocks: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        match = label.search(line)
        if match is None or (reject_label is not None and reject_label.search(line)):
            continue
        parts: list[str] = []
        same_line = line[match.end() :].strip(" :-/|\t")
        if same_line:
            parts.append(same_line)
        for candidate in lines[index + 1 : index + 1 + max_lines]:
            if stop_at_next_field and _NEXT_FIELD_LABEL.search(candidate):
                break
            if candidate:
                parts.append(candidate)
        if parts:
            blocks.append(
                {
                    "line_number": index + 1,
                    "parts": parts,
                    "text": "\n".join(parts),
                }
            )
    return blocks


def _find_expected_span(text: str, expected: str) -> str | None:
    tokens = re.findall(r"[A-Za-z0-9]+", expected)
    if len(tokens) < 2:
        return None
    pattern = re.compile(
        r"(?<![A-Za-z0-9])"
        + r"[^A-Za-z0-9]+".join(re.escape(token) for token in tokens)
        + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return _clean_observed(match.group(0)) if match else None


def _address_recovery_score(candidate: str, expected: str) -> float | None:
    if len(candidate) > 260:
        return None
    result = verify_address(candidate, expected)
    if not result.match or float(result.confidence) < 0.88:
        return None
    candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate.casefold()))
    expected_tokens = set(re.findall(r"[a-z0-9]+", expected.casefold()))
    expected_pins = set(re.findall(r"\b[1-8]\d{5}\b", expected))
    candidate_pins = set(re.findall(r"\b[1-8]\d{5}\b", candidate))
    if expected_pins and not expected_pins.intersection(candidate_pins):
        return None
    distinctive = {
        token
        for token in expected_tokens
        if token not in _ADDRESS_GENERIC_TOKENS and len(token) >= 2 and not token.isdigit()
    }
    shared = distinctive.intersection(candidate_tokens)
    required = max(2, min(4, len(distinctive)))
    if len(shared) < required or len(shared) / max(1, len(distinctive)) < 0.7:
        return None
    if len(candidate_tokens) > max(12, int(len(expected_tokens) * 2.2)):
        return None
    return min(0.94, float(result.confidence))


def _unique_candidates(matches: list[tuple[str, int]]) -> list[tuple[str, int]]:
    unique: dict[str, tuple[str, int]] = {}
    for observed, line_number in matches:
        unique.setdefault(_compact(observed), (observed, line_number))
    return list(unique.values())


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _clean_observed(value: Any) -> str:
    return " ".join(str(value or "").strip(" :-/|\t\r\n").split())
