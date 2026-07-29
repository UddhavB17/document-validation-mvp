"""Assign each loan-file page to the correct trusted person before comparisons.

Cross-person TRUSTED_* anomalies happen when co-applicant OCR (Unkar / Radha)
is compared against primary.  Ownership is resolved from identity evidence
(PAN, Aadhaar, phone, DOB, name) — not from a family tree.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

try:  # pragma: no cover - rapidfuzz is the preferred scorer
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    class fuzz:  # type: ignore[no-redef]
        @staticmethod
        def token_sort_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100

        @staticmethod
        def token_set_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100


LOAN_LEVEL_DOCUMENT_TYPES = frozenset(
    {
        "loan agreement",
        "facility agreement",
        "sanction letter",
        "stamp duty",
        "insurance consent",
        "insurance consent letter",
        "nach form",
        "cersai report",
        "legal report",
        "legal clearance report",
        "technical report",
        "technical clearance report",
        "valuation report",
        "property document",
        "property image",
        "no objection certificate",
        "noc",
        "divorce decree",
        "death certificate",
        "affidavit",
        "cam",
        "kfs",
        "key fact statement",
    }
)

# Must never silently default to primary when identity does not match.
PERSON_SCOPED_DOCUMENT_TYPES = frozenset(
    {
        "aadhaar",
        "pan",
        "pan card",
        "voter id",
        "driving license",
        "passport",
        "application form",
        "cibil report",
        "crif report",
        "bank statement",
        "passbook",
        "cheque",
        "salary slip",
        "income tax return",
        "form 97",
        "mnrega job card",
        "npr letter",
    }
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "applicant_name": ("applicant_name", "borrower_name", "account_holder_name", "customer_name"),
    "date_of_birth": ("date_of_birth", "dob"),
    "pan_number": ("pan_number", "pan"),
    "aadhaar_number": ("aadhaar_number", "aadhaar_last4", "aadhaar", "aadhar"),
    "phone_number": ("phone_number", "phone", "mobile_number"),
    "pin_code": ("pin_code", "pincode"),
    "address": ("address",),
}

FIELD_WEIGHTS = {
    "aadhaar_number": 8.0,
    "pan_number": 8.0,
    "phone_number": 5.0,
    "date_of_birth": 5.0,
    "applicant_name": 6.0,
    "pin_code": 2.0,
    "address": 1.0,
}

STRONG_ID_FIELDS = frozenset({"pan_number", "aadhaar_number", "phone_number"})


def people_from_trusted(trusted: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = (trusted or {}).get("people") or (trusted or {}).get("reference_data") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def resolve_person_owner(
    pages: list[dict[str, Any]] | dict[str, Any],
    reference_data: dict[str, Any],
    document_type: str = "",
    *,
    provided_person_id: str | None = None,
) -> dict[str, Any]:
    """Score trusted people against extracted identity and pick a clear winner.

    Returns ``{"person_id", "confidence", "evidence"}``.  ``person_id`` is
    ``None`` when ownership cannot be established for a person-scoped doc.
    """
    page_list = [pages] if isinstance(pages, dict) else list(pages or [])
    people = {
        str(key): value
        for key, value in (reference_data or {}).items()
        if isinstance(value, dict)
    }
    if not people:
        return {"person_id": None, "confidence": 0.0, "evidence": []}

    type_key = str(document_type or "").strip().lower()
    if not type_key and page_list:
        type_key = str(page_list[0].get("document_type") or "").strip().lower()

    identity = _score_people(page_list, people)
    provided = str(provided_person_id or "").strip() or None

    if provided and provided in people:
        if not _strong_id_contradicts(identity, provided, people):
            evidence = list(identity.get("evidence_by_person", {}).get(provided, []))
            evidence.append("provided_mapping")
            confidence = 0.7
            if identity["best_id"] == provided:
                confidence = max(confidence, float(identity["confidence"]))
            elif identity["scores"].get(provided, 0.0):
                confidence = max(confidence, 0.85)
            return {
                "person_id": provided,
                "confidence": round(min(1.0, confidence), 3),
                "evidence": sorted(set(evidence)),
            }
        # Strong ID points at someone else — prefer identity over bad mapping.
        if identity["best_id"]:
            return {
                "person_id": identity["best_id"],
                "confidence": identity["confidence"],
                "evidence": identity["evidence"] + ["overrode_provided_mapping"],
            }

    if identity["best_id"]:
        return {
            "person_id": identity["best_id"],
            "confidence": identity["confidence"],
            "evidence": identity["evidence"],
        }

    if len(people) == 1:
        only_id = next(iter(people))
        return {"person_id": only_id, "confidence": 0.5, "evidence": ["single_person_manifest"]}

    # Person-scoped types must not silently fall back to primary.
    if type_key in PERSON_SCOPED_DOCUMENT_TYPES:
        return {"person_id": None, "confidence": 0.0, "evidence": []}

    if type_key in LOAN_LEVEL_DOCUMENT_TYPES and "primary" in people:
        return {"person_id": "primary", "confidence": 0.4, "evidence": ["loan_level_document"]}

    return {"person_id": None, "confidence": 0.0, "evidence": []}


def assign_page_owners(
    pages: list[dict[str, Any]],
    trusted: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Stamp ``person_id`` on each page using identity evidence.

    Mutates pages in place and returns them.  Person-scoped pages that cannot
    be owned become ``unassigned`` instead of defaulting to primary.
    """
    people = people_from_trusted(trusted)
    if not people:
        for page in pages:
            if not page.get("person_id") and not page.get("applicant_role"):
                page["person_id"] = "unassigned"
        return pages

    for page in pages:
        existing = str(page.get("person_id") or page.get("applicant_role") or "").strip()
        provided = existing if existing and existing not in {"unassigned", "unknown"} else None
        # Manifest/ZIP mapping may live on the page or in extraction metadata.
        fields = page.get("extracted_fields") if isinstance(page.get("extracted_fields"), dict) else {}
        mapped = fields.get("_mapped_extraction") if isinstance(fields, dict) else None
        if isinstance(mapped, dict) and mapped.get("person_id"):
            provided = str(mapped.get("person_id"))
        zip_cls = fields.get("_zip_source_classification") if isinstance(fields, dict) else None
        if isinstance(zip_cls, dict) and zip_cls.get("predicted_person_id"):
            provided = provided or str(zip_cls.get("predicted_person_id"))

        document_type = str(page.get("document_type") or "")
        owner = resolve_person_owner(
            [page],
            people,
            document_type,
            provided_person_id=provided,
        )
        type_key = document_type.strip().lower()
        person_id = owner.get("person_id")

        if person_id is None:
            if type_key in PERSON_SCOPED_DOCUMENT_TYPES or len(people) > 1:
                person_id = "unassigned"
            elif "primary" in people:
                person_id = "primary"
                owner = {
                    "person_id": person_id,
                    "confidence": 0.35,
                    "evidence": ["loan_level_document_default"],
                }
            else:
                person_id = "unassigned"

        page["person_id"] = person_id
        page["applicant_role"] = person_id
        ownership_meta = {
            "person_id": person_id,
            "confidence": owner.get("confidence", 0.0),
            "evidence": owner.get("evidence", []),
        }
        if isinstance(fields, dict):
            fields = dict(fields)
            fields["_ownership"] = ownership_meta
            page["extracted_fields"] = fields
        else:
            page["extracted_fields"] = {"_ownership": ownership_meta}

    return pages


def ownership_anomalies_for_unassigned(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit LOW AUTO_OWNER_UNRESOLVED for person-scoped pages left unassigned."""
    anomalies: list[dict[str, Any]] = []
    for page in pages:
        person_id = str(page.get("person_id") or "")
        document_type = str(page.get("document_type") or "Unknown")
        if person_id != "unassigned":
            continue
        if document_type.strip().lower() not in PERSON_SCOPED_DOCUMENT_TYPES:
            continue
        anomalies.append(
            {
                "rule_id": "AUTO_OWNER_UNRESOLVED",
                "s_no": None,
                "severity": "LOW",
                "document_type": document_type,
                "person_id": None,
                "matched_person_id": None,
                "field_name": None,
                "status": "MANUAL_REVIEW_REQUIRED",
                "expected_value": "Automatic person assignment",
                "found_value": None,
                "page_number": page.get("page_number"),
                "reason": (
                    "The document type was identified, but no applicant identity "
                    "matched trusted data."
                ),
            }
        )
    return anomalies


def _score_people(
    pages: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    observations = identity_observations(pages)
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {person_id: [] for person_id in people}
    for person_id, trusted in people.items():
        for field, found_values in observations.items():
            expected = first_value(trusted, FIELD_ALIASES[field])
            if expected in (None, ""):
                continue
            if any(identity_matches(field, found, expected) for found in found_values):
                scores[person_id] += FIELD_WEIGHTS[field]
                evidence[person_id].append(field)

    ranked = scores.most_common()
    if ranked:
        best_id, best_score = ranked[0]
        tied = [person_id for person_id, score in ranked if score == best_score]
        if len(tied) > 1 and "primary" in tied:
            # Shared family OCR (passbook front pages) often mentions father + applicant.
            # Prefer primary when scores are otherwise tied.
            best_id = "primary"
            second_score = 0.0
        else:
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score > second_score or (len(tied) > 1 and best_id == "primary"):
            confidence = min(1.0, 0.45 + (best_score / 12.0))
            return {
                "best_id": best_id,
                "confidence": round(confidence, 3),
                "evidence": sorted(set(evidence[best_id])),
                "scores": dict(scores),
                "evidence_by_person": evidence,
            }
    return {
        "best_id": None,
        "confidence": 0.0,
        "evidence": [],
        "scores": dict(scores),
        "evidence_by_person": evidence,
    }


def _strong_id_contradicts(
    identity: dict[str, Any],
    provided: str,
    people: dict[str, dict[str, Any]],
) -> bool:
    """True when exact PAN/Aadhaar/phone evidence belongs to a different person."""
    best_id = identity.get("best_id")
    if not best_id or best_id == provided:
        return False
    evidence = set(identity.get("evidence_by_person", {}).get(best_id, []))
    if not evidence.intersection(STRONG_ID_FIELDS):
        return False
    provided_score = float(identity.get("scores", {}).get(provided, 0.0))
    best_score = float(identity.get("scores", {}).get(best_id, 0.0))
    return best_score > provided_score


def identity_observations(pages: list[dict[str, Any]]) -> dict[str, list[Any]]:
    observations: dict[str, list[Any]] = {field: [] for field in FIELD_ALIASES}
    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            # Allow passing a bare fields dict as a synthetic page.
            if isinstance(page, dict) and any(key in page for key in ("applicant_name", "pan_number", "dob")):
                fields = page
            else:
                continue
        candidates = [fields]
        mapped = fields.get("_mapped_extraction")
        if isinstance(mapped, dict):
            candidates.append(mapped)
        for candidate in candidates:
            for canonical, aliases in FIELD_ALIASES.items():
                for alias in aliases:
                    value = candidate.get(alias)
                    if value not in (None, "", [], {}):
                        observations[canonical].append(value)
        # Fall back to OCR text for names/PANs when extractors miss passbook/statement labels.
        ocr_text = str(page.get("ocr_text") or fields.get("ocr_text") or "")
        if ocr_text:
            observations["applicant_name"].append(ocr_text)
            for match in re.finditer(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", ocr_text.upper()):
                observations["pan_number"].append(match.group(0))
            for match in re.finditer(r"\b[6-9]\d{9}\b", ocr_text):
                observations["phone_number"].append(match.group(0))
    return observations


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
        score = fuzz.token_sort_ratio(_words(left), _words(right))
        if score >= 85:
            return True
        # OCR haystack (passbook/statement pages) — look for the trusted name inside.
        left_tokens = re.findall(r"[a-z0-9]+", left.lower())
        right_tokens = re.findall(r"[a-z0-9]+", right.lower())
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
