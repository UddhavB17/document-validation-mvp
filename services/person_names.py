"""Validation and comparison helpers for person-name candidates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

NAME_FIELD_ALIASES = {
    "name",
    "full_name",
    "applicant_name",
    "borrower_name",
    "account_holder_name",
    "customer_name",
    "coapplicant_name",
    "co_applicant_name",
    "father_name",
    "husband_name",
    "mother_name",
    "related_person_name",
}

_LABEL_ONLY_VALUES = {
    "applicant name",
    "borrower name",
    "name of applicant",
    "consumer name",
    "elector's name",
    "electors name",
    "customer name",
    "card holder name",
    "account holder name",
    "father's name",
    "fathers name",
    "mother's name",
    "mothers name",
    "husband's name",
    "husband name",
    "wife's name",
    "wife name",
    "work",
    "work profile",
    "job role",
    "phone number",
    "phone no",
    "name",
    "applicant",
    "co-applicant",
    "coapplicant",
    "borrower",
    "guarantor",
    "voter id",
    "pan card",
    "aadhaar card",
    "driving licence",
    "driving license",
    "आवेदक का नाम",
    "निर्वाचक का नाम",
    "पति का नाम",
    "पिता का नाम",
    "माता का नाम",
    "संगठन का नाम",
    "सं/ठन का नाम",
    "सं/ठन का",
    "खाताधारक का नाम",
    "संगठन का",
    "पता",
    "आधार",
    "पैन कार्ड",
    "मतदाता पहचान पत्र",
    "ड्राइविंग लाइसेंस",
    "नाम",
    "लिंग",
    "जन्म की तारीख",
    "फोन नंबर",
    "नौकरी भूमिका",
    "અરજદારનું નામ",
    "ખાતાધારકનું નામ",
    "નામ",
    "સરનામું",
}

# Bilingual form labels leak into name values when OCR flattens label/value
# tables.  Any candidate containing one of these Devanagari/Gujarati label
# words is form furniture, not a person (genuine Indic names never contain
# the literal words "name"/"address"/"Aadhaar"/"organisation").
_INDIC_LABEL_TOKENS = {
    "नाम",
    "पता",
    "आधार",
    "पैन",
    "मतदाता",
    "पहचान",
    "कार्ड",
    "संगठन",
    "खाताधारक",
    "आवेदक",
    "हस्ताक्षर",
    "विवरण",
    "संख्या",
    "नंबर",
    "रुपये",
    "रूपये",
    "નામ",
    "સરનામું",
    "આધાર",
    "અરજદારનું",
    "ખાતાધારકનું",
    "સહી",
}

_PLACEHOLDER_VALUES = {
    "na",
    "n/a",
    "nil",
    "none",
    "null",
    "unknown",
    "not known",
    "not provided",
    "not available",
    "primary applicant",
    "individual",
}

_REJECTED_PHRASES = {
    "a credit facility",
    "credit facility",
    "no declaration about name",
    "declaration about name",
}

_REJECTED_KEYWORDS = {
    "address",
    "ward",
    "village",
    "vill",
    "gram",
    "panchayat",
    "tehsil",
    "taluka",
    "district",
    "dist",
    "state",
    "country",
    "pin",
    "pincode",
    "locality",
    "landmark",
    "city",
    "post",
    "po",
    "police",
    "station",
    "road",
    "street",
    "colony",
    "nagar",
    "branch",
    "bank",
    "account",
    "number",
    "signature",
    "date",
    "gender",
    "mobile",
    "phone",
    "email",
    "pan",
    "aadhaar",
    "voter",
    "id",
    "ration",
    "driving",
    "licence",
    "license",
    "passport",
    "uidai",
    "office",
    "form",
    "report",
    "institution",
    "male",
    "female",
    "transgender",
    # Generic non-name vocabulary that appears as form labels/section headings
    # on financial documents and leaks into name extraction.
    "landline",
    "rupees",
    "rupee",
    "business",
    "constitution",
    "organisation",
    "organization",
    # Legal-entity markers. A lender/company header can look like a plausible
    # multi-token human name after OCR, but these tokens make the entity type
    # explicit and must never enter person ownership or identity comparison.
    "company",
    "private",
    "limited",
    "ltd",
    "pvt",
    "llp",
    "corporation",
    "corp",
    "incorporated",
    "transaction",
    "transcation",
}

# Locality tokens observed in application 75 false positives. These remain
# address evidence; by themselves they should not become applicant identities.
_AUDITED_LOCALITY_TOKENS = {
    "semali",
    "semah",
    "semli",
    "semlibakta",
    "bakhta",
    "bakhata",
    "bakta",
    "jhalawar",
    "pachpahad",
    "sulia",
    "suilia",
    "pachpahar",
    "rajasthan",
}

_RELATIONSHIP_MARKER_RE = re.compile(
    r"^(?:[sdfwc]\s*/?\s*o|son\s+of|daughter\s+of|wife\s+of|"
    r"husband\s+of|father\s+of|care\s+of|c\s*o)\.?\s*[:\-–]?$",
    re.IGNORECASE,
)
_RELATIONSHIP_PREFIX_RE = re.compile(
    r"^(?:[sdfwc]\s*/?\s*o|son\s+of|daughter\s+of|wife\s+of|"
    r"husband\s+of|father\s+of|care\s+of|c\s*o)\.?\s*[:\-–]\s+",
    re.IGNORECASE,
)
_HONORIFIC_RE = re.compile(r"^\s*(?:mr|mrs|ms|miss|shri|smt|dr|श्री|श्रीमती)\.?\s+", re.IGNORECASE)


@dataclass(frozen=True)
class NameCandidate:
    value: str | None
    valid: bool
    reason: str | None = None


def canonicalize_person_name(value: Any) -> NameCandidate:
    """Return a canonical person-name value or a rejection reason."""
    raw = str(value or "").strip()
    candidate = re.sub(r"\s+", " ", raw.strip(" :\t\r\n"))
    if not candidate:
        return NameCandidate(None, False, "blank")

    candidate = _strip_leading_label(candidate)
    candidate = _HONORIFIC_RE.sub("", candidate).strip()
    normalized = _normalize_for_rules(candidate)
    if not normalized:
        return NameCandidate(None, False, "blank")
    if normalized in {_normalize_for_rules(label) for label in _LABEL_ONLY_VALUES}:
        return NameCandidate(None, False, "field_label")
    if any(piece.strip(" :,.–—\-/()[]|'\"") in _INDIC_LABEL_TOKENS for piece in candidate.split()):
        return NameCandidate(None, False, "indic_field_label")
    if normalized in _PLACEHOLDER_VALUES:
        return NameCandidate(None, False, "placeholder")
    if any(phrase in normalized for phrase in _REJECTED_PHRASES):
        return NameCandidate(None, False, "non_name_phrase")
    if _RELATIONSHIP_MARKER_RE.fullmatch(candidate):
        return NameCandidate(None, False, "relationship_marker")
    if _RELATIONSHIP_PREFIX_RE.match(candidate):
        return NameCandidate(None, False, "relationship_or_care_of_value")
    if re.search(r"\d", candidate):
        return NameCandidate(None, False, "contains_digits")
    if any(
        part in candidate.lower() for part in ("xmlns", "http://", "https://", "<", ">", "=", "/>")
    ):
        return NameCandidate(None, False, "metadata_or_markup")
    if not any(character.isalpha() for character in candidate):
        return NameCandidate(None, False, "no_letters")
    if len(candidate) < 3 or len(candidate) > 70:
        return NameCandidate(None, False, "length")

    tokens = _latin_tokens(candidate)
    if tokens:
        if any(token in _REJECTED_KEYWORDS for token in tokens):
            return NameCandidate(None, False, "address_or_field_keyword")
        locality_hits = sum(1 for token in tokens if token in _AUDITED_LOCALITY_TOKENS)
        if locality_hits and locality_hits >= max(1, len(tokens) - 1):
            return NameCandidate(None, False, "address_locality")
        if len(tokens) == 1 and len(tokens[0]) <= 3:
            return NameCandidate(None, False, "too_short_single_token")

    punctuation = sum(
        1
        for character in candidate
        if not (
            character.isalnum()
            or character.isspace()
            or unicodedata.category(character).startswith("M")
            or character in ".'-"
        )
    )
    if punctuation > 1:
        return NameCandidate(None, False, "malformed")

    return NameCandidate(candidate, True, None)


def is_person_name_candidate(value: Any) -> bool:
    return canonicalize_person_name(value).valid


def is_name_field(field: Any) -> bool:
    key = re.sub(r"[^a-z0-9]+", "_", str(field or "").lower()).strip("_")
    return key in NAME_FIELD_ALIASES


def comparable_name(value: Any) -> str:
    candidate = canonicalize_person_name(value)
    text = candidate.value if candidate.valid else str(value or "")
    return _compact_unicode(_HONORIFIC_RE.sub("", text).casefold())


def names_match(left: Any, right: Any, *, threshold: float = 0.90) -> bool:
    if not is_person_name_candidate(left) or not is_person_name_candidate(right):
        return False
    return name_similarity(left, right) >= threshold


def name_similarity(left: Any, right: Any) -> float:
    a = comparable_name(left)
    b = comparable_name(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def has_independent_identity_anchor(fields: dict[str, Any]) -> bool:
    """Return true when a page has identity evidence stronger than name text."""
    for field in (
        "pan_number",
        "aadhaar_number",
        "aadhaar_last4",
        "phone_number",
        "date_of_birth",
        "dob",
    ):
        value = fields.get(field)
        if value not in (None, "", [], {}):
            return True
    return False


def _strip_leading_label(value: str) -> str:
    match = re.match(
        r"^(?:applicant|borrower|customer|consumer|account\s+holder|card\s+holder)"
        r"\s*(?:name)?\s*[:\-–]\s*(.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return value


def _normalize_for_rules(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"[^\w\s/'-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip(" :-")


def _latin_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z]+", value.casefold())


def _compact_unicode(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").casefold()
        if character.isalnum() or unicodedata.category(character).startswith("M")
    )
