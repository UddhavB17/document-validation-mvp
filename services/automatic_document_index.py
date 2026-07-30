"""Build a verification page index from the shared OCR/classification output."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from services.person_ownership import (
    LOAN_LEVEL_DOCUMENT_TYPES,
    MULTI_PERSON_DOCUMENT_TYPES,
    PERSON_SCOPED_DOCUMENT_TYPES,
    resolve_person_owner,
)

from services.person_names import is_person_name_candidate, name_similarity
from services.validation_gates import field_reliable_for_validation


IGNORED_DOCUMENT_TYPES = {
    "",
    "none",
    "unknown",
    "ocr skipped",
    "db data",
    "property image",
    "house photo",
    "workplace photo",
    "photo evidence",
    "kyc card photo",
    "ration card photo",
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
        if float(group.get("confidence") or 0.0) < 0.50:
            anomalies.append(
                _mapping_anomaly(
                    "AUTO_DOCUMENT_TYPE_LOW_CONFIDENCE",
                    group,
                    "Document type confidence was too low for trusted JSON field comparison.",
                )
            )
            continue
        type_key = document_type.strip().lower()
        is_loan_level = type_key in LOAN_LEVEL_DOCUMENT_TYPES
        requires_person = type_key in PERSON_SCOPED_DOCUMENT_TYPES
        is_multi_person = type_key in MULTI_PERSON_DOCUMENT_TYPES
        if is_multi_person and reference_data:
            default_id = "primary" if "primary" in reference_data else next(iter(reference_data))
            person = {
                "person_id": default_id,
                "confidence": 1.0,
                "evidence": ["multi_person_document_container"],
            }
        else:
            person = resolve_person_owner(group["pages_data"], reference_data, document_type)

        if person["person_id"] is None:
            # Person-scoped docs (PAN/Aadhaar/CIBIL/…) must not fall back to primary.
            if requires_person:
                anomalies.append(
                    _mapping_anomaly(
                        "AUTO_OWNER_UNRESOLVED",
                        group,
                        "The document type was identified, but no applicant identity matched trusted data.",
                    )
                )
                continue
            if is_loan_level and reference_data:
                default_id = "primary" if "primary" in reference_data else next(iter(reference_data))
                person = {
                    "person_id": default_id,
                    "confidence": 0.35,
                    "evidence": ["loan_level_document_default"],
                }
            elif reference_data:
                default_id = "primary" if "primary" in reference_data else next(iter(reference_data))
                person = {
                    "person_id": default_id,
                    "confidence": 1.0,
                    "evidence": ["document_not_person_scoped"],
                }

        # Loan-level docs are intentionally assigned to primary with modest confidence.
        # Do not emit per-fragment LOW_CONFIDENCE noise for that default.
        loan_level_evidence = {
            "loan_level_document", "loan_level_document_default", "document_not_person_scoped"
        }
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
                    "multi_person_document": is_multi_person,
                    "detection_method": (
                        "zip_source_document_classification"
                        if group.get("zip_source_id") else "automatic_page_classification"
                    ),
                    "source_document_id": group.get("zip_source_id"),
                    "source_filename": group.get("original_filename"),
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
    if source_documents:
        return _group_zip_sources_as_documents(pages, source_documents)

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


def _group_zip_sources_as_documents(
    pages: list[dict[str, Any]], source_documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Treat every ZIP member as one complete document candidate."""
    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if page.get("page_number") is not None
    }
    groups: list[dict[str, Any]] = []
    for source in source_documents:
        source_id = str(source.get("source_document_id") or "")
        start = int(source.get("internal_page_start") or 0)
        end = int(source.get("internal_page_end") or 0)
        source_pages = [
            pages_by_number[number]
            for number in range(start, end + 1)
            if number in pages_by_number
        ]
        if not source_pages:
            continue
        document_type, confidence = _select_source_document_type(source_pages, source)
        if document_type.strip().lower() in IGNORED_DOCUMENT_TYPES:
            continue
        groups.append(
            {
                "source_document_id": source_id or f"auto-{start:04d}-{_slug(document_type)}",
                "zip_source_id": source_id,
                "original_filename": source.get("original_filename"),
                "file_type": source.get("file_type"),
                "document_type": document_type,
                "pages": [
                    int(page.get("page_number") or 0)
                    for page in source_pages
                    if int(page.get("page_number") or 0)
                ],
                "pages_data": source_pages,
                "confidence": confidence,
            }
        )
    return groups


def _select_source_document_type(
    pages: list[dict[str, Any]], source: dict[str, Any]
) -> tuple[str, float]:
    weighted_votes: Counter[str] = Counter()
    confidences_by_type: dict[str, list[float]] = {}
    for page in pages:
        document_type = _effective_document_type(page)
        type_key = document_type.strip().lower()
        if type_key in IGNORED_DOCUMENT_TYPES:
            continue
        confidence = float(page.get("classification_confidence") or 0.0)
        weighted_votes[document_type] += max(confidence, 0.01)
        confidences_by_type.setdefault(document_type, []).append(confidence)
    if not weighted_votes:
        fallback = _source_type_from_filename(str(source.get("original_filename") or ""))
        return (fallback, 0.55) if fallback else ("Unknown", 0.0)
    document_type = weighted_votes.most_common(1)[0][0]
    confidences = confidences_by_type.get(document_type) or [0.0]
    return document_type, round(sum(confidences) / len(confidences), 3)


def _source_type_from_filename(filename: str) -> str | None:
    text = filename.lower()
    if "application" in text or "app form" in text or "loan form" in text:
        return "Application Form"
    if "aadhaar" in text or "aadhar" in text:
        return "Aadhaar"
    if re.search(r"\bpan\b", text):
        return "PAN"
    if "bank" in text or "statement" in text:
        return "Bank Statement"
    if "agreement" in text:
        return "Loan Agreement"
    if "sanction" in text:
        return "Sanction Letter"
    return None


def _effective_document_type(page: dict[str, Any]) -> str:
    fields = page.get("extracted_fields")
    if isinstance(fields, dict):
        llm = fields.get("_structured_llm_classification")
        if isinstance(llm, dict):
            llm_type = str(llm.get("document_type") or "").strip()
            if llm_type.lower() not in {"", "none", "unknown"}:
                return llm_type
    return str(page.get("document_type") or "Unknown").strip()



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
        # Ownership uncertainty is processing-quality information. It should
        # not compete with borrower/document discrepancies in the operations
        # queue; unresolved fragments remain visible as a collapsed LOW item.
        "severity": "LOW",
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
