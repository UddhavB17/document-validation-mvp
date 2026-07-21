"""Build a verification page index from the shared OCR/classification output."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from rapidfuzz import fuzz


IGNORED_DOCUMENT_TYPES = {
    "",
    "none",
    "unknown",
    "ocr skipped",
    "db data",
    "property image",
}

LOAN_LEVEL_DOCUMENT_TYPES = {
    "loan agreement",
    "sanction letter",
    "stamp duty",
    "insurance consent",
    "nach form",
}

FIELD_ALIASES = {
    "applicant_name": ("applicant_name", "borrower_name", "account_holder_name", "customer_name"),
    "date_of_birth": ("date_of_birth", "dob"),
    "pan_number": ("pan_number", "pan"),
    "aadhaar_number": ("aadhaar_number", "aadhaar", "aadhar"),
    "phone_number": ("phone_number", "phone", "mobile_number"),
    "pin_code": ("pin_code", "pincode"),
    "address": ("address",),
}

FIELD_WEIGHTS = {
    "aadhaar_number": 8.0,
    "pan_number": 8.0,
    "phone_number": 5.0,
    "date_of_birth": 5.0,
    "applicant_name": 4.0,
    "pin_code": 2.0,
    "address": 1.0,
}


def build_automatic_document_index(
    pages: list[dict[str, Any]],
    reference_data: dict[str, Any],
    *,
    source_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Infer contiguous document groups and their most likely person owner.

    ZIP source boundaries are respected, but a multi-document PDF inside a ZIP
    may still produce multiple groups when a new document heading is detected.
    """
    groups = _group_pages(pages, source_documents or [])
    documents: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []

    for group in groups:
        document_type = str(group["document_type"])
        person = _infer_person(group["pages_data"], reference_data, document_type)
        is_loan_level = document_type.strip().lower() in LOAN_LEVEL_DOCUMENT_TYPES

        if person["person_id"] is None:
            if is_loan_level and reference_data:
                default_id = "primary" if "primary" in reference_data else next(iter(reference_data))
                person = {
                    "person_id": default_id,
                    "confidence": 0.35,
                    "evidence": ["loan_level_document_default"],
                }
            else:
                anomalies.append(
                    _mapping_anomaly(
                        "AUTO_OWNER_UNRESOLVED",
                        group,
                        "The document type was identified, but no applicant identity matched trusted data.",
                    )
                )
                continue

        # Loan-level docs are intentionally assigned to primary with modest confidence.
        # Do not emit per-fragment LOW_CONFIDENCE noise for that default.
        loan_level_evidence = {"loan_level_document", "loan_level_document_default"}
        if (
            person["confidence"] < 0.60
            and len(reference_data) > 1
            and not is_loan_level
            and not loan_level_evidence.intersection(person["evidence"])
        ):
            anomalies.append(
                _mapping_anomaly(
                    "AUTO_OWNER_LOW_CONFIDENCE",
                    group,
                    f"Assigned to {person['person_id']} with limited identity evidence.",
                    person_id=str(person["person_id"]),
                )
            )

        documents.append(
            {
                "source_document_id": group["source_document_id"],
                "document_type": document_type,
                "applicant_role": person["person_id"],
                "pages": group["pages"],
                "required": False,
                "auto_mapping": {
                    "document_confidence": group["confidence"],
                    "owner_confidence": person["confidence"],
                    "owner_evidence": person["evidence"],
                    "detection_method": "automatic_page_classification",
                },
            }
        )

    classified_pages = {number for item in documents for number in item["pages"]}
    return {
        "documents": documents,
        "anomalies": anomalies,
        "classified_pages": sorted(classified_pages),
        "unclassified_pages": sorted(
            int(page.get("page_number") or 0)
            for page in pages
            if int(page.get("page_number") or 0) not in classified_pages
            and str(page.get("document_type") or "").strip().lower() not in {"db data"}
        ),
    }


def _group_pages(
    pages: list[dict[str, Any]], source_documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source_by_page: dict[int, str] = {}
    for source in source_documents:
        source_id = str(source.get("source_document_id") or "")
        start = int(source.get("internal_page_start") or 0)
        end = int(source.get("internal_page_end") or 0)
        for page_number in range(start, end + 1):
            source_by_page[page_number] = source_id

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        page_number = int(page.get("page_number") or 0)
        document_type = _effective_document_type(page)
        if document_type.strip().lower() in IGNORED_DOCUMENT_TYPES:
            current = None
            continue
        source_id = source_by_page.get(page_number)
        starts_document = page.get("detected_page_number") == page_number
        is_loan_level = document_type.strip().lower() in LOAN_LEVEL_DOCUMENT_TYPES
        # Loan agreements / sanction letters often mis-detect every page as "page 1".
        # Do not fragment those within the same ZIP member.
        split_on_heading = (
            starts_document
            and page_number not in (current or {}).get("pages", [])
            and not is_loan_level
        )
        new_group = (
            current is None
            or current["document_type"] != document_type
            or current.get("zip_source_id") != source_id
            or split_on_heading
        )
        if new_group:
            generated_id = source_id or f"auto-{page_number:04d}-{_slug(document_type)}"
            current = {
                "source_document_id": generated_id,
                "zip_source_id": source_id,
                "document_type": document_type,
                "pages": [],
                "pages_data": [],
                "confidences": [],
            }
            groups.append(current)
        current["pages"].append(page_number)
        current["pages_data"].append(page)
        current["confidences"].append(float(page.get("classification_confidence") or 0.0))

    for group in groups:
        confidences = group.pop("confidences")
        group["confidence"] = round(sum(confidences) / max(len(confidences), 1), 3)
    return groups


def _effective_document_type(page: dict[str, Any]) -> str:
    fields = page.get("extracted_fields")
    if isinstance(fields, dict):
        llm = fields.get("_structured_llm_classification")
        if isinstance(llm, dict):
            llm_type = str(llm.get("document_type") or "").strip()
            if llm_type.lower() not in {"", "none", "unknown"}:
                return llm_type
    return str(page.get("document_type") or "Unknown").strip()


def _infer_person(
    pages: list[dict[str, Any]], reference_data: dict[str, Any], document_type: str
) -> dict[str, Any]:
    people = {str(key): value for key, value in reference_data.items() if isinstance(value, dict)}
    if not people:
        return {"person_id": None, "confidence": 0.0, "evidence": []}

    observations = _identity_observations(pages)
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {person_id: [] for person_id in people}
    for person_id, trusted in people.items():
        for field, found_values in observations.items():
            expected = _first_value(trusted, FIELD_ALIASES[field])
            if expected in (None, ""):
                continue
            if any(_identity_matches(field, found, expected) for found in found_values):
                scores[person_id] += FIELD_WEIGHTS[field]
                evidence[person_id].append(field)

    ranked = scores.most_common()
    if ranked:
        best_id, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score > second_score:
            confidence = min(1.0, 0.45 + (best_score / 12.0))
            return {
                "person_id": best_id,
                "confidence": round(confidence, 3),
                "evidence": sorted(set(evidence[best_id])),
            }

    if len(people) == 1:
        only_id = next(iter(people))
        return {"person_id": only_id, "confidence": 0.5, "evidence": ["single_person_manifest"]}
    if document_type.strip().lower() in LOAN_LEVEL_DOCUMENT_TYPES and "primary" in people:
        return {"person_id": "primary", "confidence": 0.4, "evidence": ["loan_level_document"]}
    return {"person_id": None, "confidence": 0.0, "evidence": []}


def _identity_observations(pages: list[dict[str, Any]]) -> dict[str, list[Any]]:
    observations: dict[str, list[Any]] = {field: [] for field in FIELD_ALIASES}
    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
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
    return observations


def _first_value(values: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = values.get(alias)
        if value not in (None, ""):
            return value
    return None


def _identity_matches(field: str, found: Any, expected: Any) -> bool:
    left = str(found or "").strip()
    right = str(expected or "").strip()
    if not left or not right:
        return False
    if field == "applicant_name":
        return fuzz.token_sort_ratio(_words(left), _words(right)) >= 85
    if field == "address":
        return fuzz.token_set_ratio(_words(left), _words(right)) >= 75
    if field == "date_of_birth":
        return _date_key(left) == _date_key(right)
    if field in {"aadhaar_number", "phone_number", "pin_code"}:
        return _digits(left) == _digits(right) and bool(_digits(left))
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


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "document"


def _mapping_anomaly(
    rule_id: str,
    group: dict[str, Any],
    reason: str,
    *,
    person_id: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "s_no": None,
        "severity": "MEDIUM",
        "document_type": group["document_type"],
        "person_id": person_id,
        "matched_person_id": None,
        "field_name": None,
        "status": "MANUAL_REVIEW_REQUIRED",
        "expected_value": "Automatic person assignment",
        "found_value": None,
        "page_number": group["pages"][0],
        "reason": reason,
    }
