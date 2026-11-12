"""Canonical identity-field matching independent of ownership resolution."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from services.person_names import is_person_name_candidate, name_similarity

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - rapidfuzz is the preferred scorer
    from rapidfuzz import fuzz
except ImportError as exc:  # pragma: no cover
    from difflib import SequenceMatcher

    LOGGER.warning("rapidfuzz is unavailable; using the slower identity scorer fallback: %s", exc)

    class fuzz:  # type: ignore[no-redef]
        @staticmethod
        def token_set_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100


def first_value(values: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = values.get(alias)
        if value not in (None, ""):
            return value
    return None


def identity_matches(field: str, found: Any, expected: Any) -> bool:
    left = str(found or "").strip()
    right = str(expected or "").strip()
    if not left or not right:
        return False
    if field == "applicant_name":
        left_tokens = re.findall(r"[a-z0-9]+", left.lower())
        right_tokens = re.findall(r"[a-z0-9]+", right.lower())
        is_haystack = len(left_tokens) >= max(4, len(right_tokens) + 2)
        if not is_haystack and (
            not is_person_name_candidate(left) or not is_person_name_candidate(right)
        ):
            return False
        if not is_haystack and name_similarity(left, right) >= 0.85:
            return True
        if len(left_tokens) >= max(4, len(right_tokens) + 2) and right_tokens:
            compact_right = "".join(right_tokens)
            compact_left = "".join(left_tokens)
            if len(compact_right) >= 4 and compact_right in compact_left:
                return True
            if len(right_tokens) >= 2:
                pattern = r"\b" + r"\s+".join(re.escape(tok) for tok in right_tokens) + r"\b"
                if re.search(pattern, left.lower()):
                    return True
        return False
    if field == "address":
        return fuzz.token_set_ratio(_words(left), _words(right)) >= 75
    if field == "date_of_birth":
        return _date_key(left) == _date_key(right)
    if field in {"aadhaar_number", "phone_number", "pin_code"}:
        left_digits = _digits(left)
        right_digits = _digits(right)
        if field == "aadhaar_number" and len(left_digits) >= 4 and len(right_digits) >= 4:
            return left_digits[-4:] == right_digits[-4:]
        return left_digits == right_digits and bool(left_digits)
    if field == "pan_number":
        return re.sub(r"\s+", "", left).upper() == re.sub(r"\s+", "", right).upper()
    if field == "account_number":
        left_digits = _digits(left)
        right_digits = _digits(right)
        return len(left_digits) >= 8 and len(right_digits) >= 8 and left_digits == right_digits
    return _words(left) == _words(right)


def _words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _date_key(value: str) -> str:
    normalized = str(value or "").strip()
    for format_string in (
        "%d-%B-%Y",
        "%d-%b-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(normalized, format_string).date().isoformat()
        except ValueError:
            continue
    return _words(normalized).replace(" ", "")
