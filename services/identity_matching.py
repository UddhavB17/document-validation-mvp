"""Canonical identity-field matching independent of ownership resolution."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
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
        return (
            address_component_conflict(left, right) is None
            and fuzz.token_set_ratio(_words(left), _words(right)) >= 75
        )
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


_ADDRESS_IDENTIFIER = r"([a-z]?\s*[-/]?\s*\d{1,5}(?:\s*[-/]\s*\d{1,5})?[a-z]?)(?![a-z0-9])"
_ADDRESS_COMPONENT_LABELS = (
    ("occupancy", r"flat|apartment|apt|house|unit|door|room|quarter|h\s*\.?\s*no\.?"),
    ("plot", "plot"),
    ("block", "block"),
    ("ward", "ward"),
    ("sector", "sector"),
)
_ADDRESS_COMPONENT_PATTERNS = tuple(
    (
        component,
        re.compile(
            rf"\b(?:{labels})\s*(?:(?:number|no)\.?\s*)?[:#]?\s*{_ADDRESS_IDENTIFIER}"
        ),
    )
    for component, labels in _ADDRESS_COMPONENT_LABELS
)
_NUMBERED_LOCALITY = re.compile(r"\b(\d{1,3})\s*([a-z])\b")
_ADDRESS_PIN = re.compile(r"\b[1-8]\d{5}\b")


def explicit_address_units(value: Any) -> dict[str, set[str]]:
    """Find explicit unit or locality identifiers without guessing from bare numbers."""
    text = str(value or "").casefold()
    result: dict[str, set[str]] = defaultdict(set)
    for component, pattern in _ADDRESS_COMPONENT_PATTERNS:
        for match in pattern.finditer(text):
            identifier = re.sub(r"[^a-z0-9]", "", match.group(1))
            if component in {"ward", "sector"} and identifier.isdigit():
                identifier = identifier.lstrip("0") or "0"
            result[component].add(identifier)

    # Some trusted dumps begin with an unlabelled flat number, e.g. B-402.
    leading = re.match(r"^\s*([a-z])\s*[-/]?\s*(\d{1,5}[a-z]?)\b", text)
    if leading:
        result["occupancy"].add(f"{leading.group(1)}{leading.group(2)}")
    return result


def address_component_conflict(left: Any, right: Any) -> str | None:
    """Return the first explicitly identified component that disagrees."""
    left_units = explicit_address_units(left)
    right_units = explicit_address_units(right)
    labelled_conflict = next(
        (
            component
            for component, _ in _ADDRESS_COMPONENT_LABELS
            if component in left_units
            and component in right_units
            and left_units[component].isdisjoint(right_units[component])
        ),
        None,
    )
    if labelled_conflict:
        return labelled_conflict
    if _numbered_localities_conflict(str(left or "").casefold(), str(right or "").casefold()):
        return "locality identifier"
    return None


def _numbered_localities_conflict(left: str, right: str) -> bool:
    """Compare standalone locality codes inside the same numbered address area."""
    if not set(_ADDRESS_PIN.findall(left)) & set(_ADDRESS_PIN.findall(right)):
        return False
    left_parts = [_words(part) for part in left.split(",") if part.strip()]
    right_parts = [_words(part) for part in right.split(",") if part.strip()]
    shared_places = {part for part in set(left_parts) & set(right_parts) if part.isalpha()}
    if len(shared_places) < 2:
        return False

    left_codes = set(_NUMBERED_LOCALITY.findall(left))
    right_codes = set(_NUMBERED_LOCALITY.findall(right))
    if not left_codes & right_codes:
        return False

    left_only = numbered_locality_identifiers(left) - right_codes
    right_only = numbered_locality_identifiers(right) - left_codes
    return (
        len(left_only) == len(right_only) == 1
        and next(iter(left_only))[1] == next(iter(right_only))[1]
    )


def numbered_locality_identifiers(value: Any) -> set[tuple[str, str]]:
    """Read locality codes written as their own comma-delimited address component."""
    return {
        match.groups()
        for part in str(value or "").casefold().split(",")
        if (match := _NUMBERED_LOCALITY.fullmatch(part.strip()))
    }


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
