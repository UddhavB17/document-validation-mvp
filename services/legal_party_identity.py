"""High-confidence borrower DOB evidence from property memorandum parties."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from dateutil import parser

from services.person_names import is_person_name_candidate
from services.person_ownership import name_matches_trusted_person

_MIN_OCR_CONFIDENCE = 0.90
_MAX_PARTY_BLOCK_CHARS = 450

_MEMORANDUM_MARKER_RE = re.compile(
    r"(?:\bmemorandum\b[\s\S]{0,160}\b(?:deposit\s+of\s+title\s+deeds|title\s+deeds)\b|"
    r"\bexecuted\s+this\s+memorandum\b[\s\S]{0,100}\bterms\s+and\s+conditions\b)",
    re.IGNORECASE,
)
_FIRST_PARTY_MARKER_RE = re.compile(
    r'(?:"\s*THE\s+FIRST\s+PARTIES\s*/\s*OWNERS\s*"|'
    r"\(\s*THE\s+FIRST\s+PARTIES\s*/\s*OWNERS\s*\)\s*:?\s*)",
    re.IGNORECASE,
)
_RELATIONSHIP_RE = re.compile(
    r"\b(?:w\s*/\s*o|s\s*/\s*o|d\s*/\s*o|c\s*/\s*o|wife\s+of|"
    r"son\s+of|daughter\s+of|care\s+of)\b",
    re.IGNORECASE,
)
_DOB_RE = re.compile(
    r"\b(?:DOB|DATE\s+OF\s+BIRTH)\s*[:\-–]?\s*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b",
    re.IGNORECASE,
)
_MASKED_AADHAAR_RE = re.compile(
    r"\b(?:AADHAAR|AADHAR)\s*(?:NO\.?|NUMBER)?\s*[:#\-]?\s*"
    r"(?:[X*•][\s-]*){8,12}(\d{4})\b",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"^(?:smt|shri|sh|mr|mrs|ms|miss|dr)\.?\s+", re.IGNORECASE)
_EXCLUDED_PARTY_CONTEXT_RE = re.compile(
    r"\b(?:witness(?:es)?|lender|authorized\s+person|authorised\s+person)\b",
    re.IGNORECASE,
)
LEGAL_PARTY_DOCUMENT_TYPES = frozenset(
    {
        "property document",
        "loan agreement",
        "memorandum",
        "memorandum by deposit of title deeds",
        "memorandum of deposit of title deeds",
        "title deed memorandum",
    }
)


def legal_party_birth_dates(
    pages: list[dict[str, Any]], people: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract DOB observations tied to a uniquely matched first-party identity.

    The page owner is deliberately ignored. A result requires a high-quality
    memorandum page, a formatted first-parties/owners marker, a nearby name and
    labelled DOB, and a masked Aadhaar last-four that uniquely corroborates the
    same trusted profile.
    """
    if not isinstance(people, dict) or not people:
        return []

    observations: list[dict[str, Any]] = []
    for page in pages or []:
        if not isinstance(page, dict) or not _eligible_page(page):
            continue
        text = str(page.get("ocr_text") or "")
        if not text or not _MEMORANDUM_MARKER_RE.search(text):
            continue

        page_results: dict[tuple[str, str], dict[str, Any]] = {}
        for marker in _FIRST_PARTY_MARKER_RE.finditer(text):
            start = max(0, marker.start() - _MAX_PARTY_BLOCK_CHARS)
            prefix = text[start : marker.start()]
            identity_line = _last_named_relationship_line(prefix)
            if identity_line is None:
                continue
            name, line_offset = identity_line
            block = prefix[line_offset:]
            if not _has_party_identification_intro(prefix[:line_offset]):
                continue
            if _EXCLUDED_PARTY_CONTEXT_RE.search(block):
                continue

            dob_matches = list(_DOB_RE.finditer(block))
            aadhaar_matches = list(_MASKED_AADHAAR_RE.finditer(block))
            if len(dob_matches) != 1 or len(aadhaar_matches) != 1:
                continue
            birth_date = _normalize_birth_date(dob_matches[0].group(1))
            if birth_date is None:
                continue
            aadhaar_last4 = aadhaar_matches[0].group(1)
            matched_people = [
                (str(person_id), person)
                for person_id, person in people.items()
                if isinstance(person, dict)
                and name_matches_trusted_person(name, person)
                and _trusted_aadhaar_last4_matches(person, aadhaar_last4)
            ]
            if len(matched_people) != 1:
                continue

            person_id, _person = matched_people[0]
            page_number = page.get("page_number")
            page_result = {
                "person_id": person_id,
                "field": "date_of_birth",
                "value": birth_date,
                "document_type": str(page.get("document_type") or page.get("provided_document_type") or ""),
                "page_number": page_number,
                "ocr_text": text,
                "page_type": page.get("page_type"),
            }
            page_results[(person_id, birth_date)] = page_result
        observations.extend(page_results.values())
    return observations


def _eligible_page(page: dict[str, Any]) -> bool:
    document_type = _canonical_document_type(
        page.get("document_type") or page.get("provided_document_type")
    )
    if document_type not in LEGAL_PARTY_DOCUMENT_TYPES:
        return False
    if page.get("is_readable") is False or page.get("ocr_status") in {
        "failed",
        "no_text_extracted",
    }:
        return False
    page_type = str(page.get("page_type") or "").strip().casefold()
    if page_type not in {"scanned", "digital"}:
        return False
    classification_confidence = page.get("classification_confidence")
    try:
        class_confidence = float(classification_confidence)
    except (TypeError, ValueError):
        class_confidence = None
    if class_confidence is not None and class_confidence < 0.80:
        return False

    ocr_confidence = page.get("ocr_confidence")
    if page_type == "scanned" or ocr_confidence not in (None, ""):
        try:
            if float(ocr_confidence) < _MIN_OCR_CONFIDENCE:
                return False
        except (TypeError, ValueError):
            return False
    elif class_confidence is None or class_confidence < 0.80:
        # Embedded digital text has no OCR score; require a confident document
        # classification before using it as identity evidence.
        return False
    return True


def _canonical_document_type(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _last_named_relationship_line(prefix: str) -> tuple[str, int] | None:
    candidate_line: tuple[str, int] | None = None
    for line_match in re.finditer(r"(?m)^[ \t]*([^\r\n]+)", prefix):
        line = line_match.group(1).strip()
        relation = _RELATIONSHIP_RE.search(line)
        if relation is None:
            continue
        candidate = line[: relation.start()].strip(" \t,.;:()[]{}\"'“”")
        candidate = _TITLE_RE.sub("", candidate).strip(" \t,.;:()[]{}\"'“”")
        if not candidate or not is_person_name_candidate(candidate):
            continue
        candidate_line = (
            candidate,
            line_match.start(1)
            + len(line_match.group(1))
            - len(line_match.group(1).lstrip()),
        )
    return candidate_line


def _has_party_identification_intro(prefix: str) -> bool:
    """Require a recent party-introduction or execution cue before the name."""
    return bool(
        re.search(
            r"\bbetween\b|\bexecuted\s+this\s+memorandum\b",
            prefix[-220:],
            re.IGNORECASE,
        )
    )


def _trusted_aadhaar_last4_matches(person: dict[str, Any], last4: str) -> bool:
    digits = re.sub(r"\D", "", str(last4 or ""))
    if len(digits) != 4:
        return False
    expected_values: set[str] = set()
    for raw_key, value in person.items():
        key = re.sub(r"[^a-z0-9]+", "", str(raw_key).casefold())
        if key not in {"aadhaarnumber", "aadhaar", "aadharnumber", "aadhar", "aadhaarlast4"}:
            continue
        candidate_digits = re.sub(r"\D", "", str(value or ""))
        if len(candidate_digits) >= 4:
            expected_values.add(candidate_digits[-4:])
    return expected_values == {digits}


def _normalize_birth_date(value: str) -> str | None:
    try:
        parsed = parser.parse(value, dayfirst=True, yearfirst=False).date()
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed < date(1900, 1, 1) or parsed > date.today():
        return None
    return parsed.isoformat()
