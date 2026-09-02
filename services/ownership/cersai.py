"""Person-ownership submodule."""

from __future__ import annotations

import re
from typing import Any

from services.cersai import (
    DEBTOR_BASED as CERSAI_DEBTOR_BASED,
)
from services.cersai import (
    report_search_type as detect_cersai_report_search_type,
)
from services.cersai import (
    search_type as detect_cersai_search_type,
)
from services.ownership._helpers import first_value
from services.ownership.constants import FIELD_ALIASES
from services.ownership.matching import _score_people
from services.ownership.observations import identity_observations


def _as_page_list(
    pages: list[dict[str, Any]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(pages, dict):
        return [pages]
    return [page for page in (pages or []) if isinstance(page, dict)]


def _cersai_search_type(pages: list[dict[str, Any]]) -> str:
    """Read subtype from extraction metadata first, then intrinsic OCR text."""
    return detect_cersai_report_search_type(pages)


def _cersai_debtor_identity_page(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one identity record containing only CERSAI search-subject fields."""
    combined_text = "\n".join(str(page.get("ocr_text") or "") for page in pages)
    extracted: dict[str, Any] = {}
    if combined_text.strip():
        # Lazy import avoids making the general extractor depend on ownership.
        from services.field_extractor import extract_fields

        extracted = extract_fields("CERSAI Report", combined_text)

    debtor_name = extracted.get("debtor_name")
    debtor_pan = extracted.get("debtor_pan_number")
    debtor_dob = extracted.get("debtor_date_of_birth")
    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            continue
        if detect_cersai_search_type(page.get("ocr_text"), fields) != CERSAI_DEBTOR_BASED:
            continue
        debtor_name = debtor_name or fields.get("debtor_name") or fields.get("applicant_name")
        debtor_pan = debtor_pan or fields.get("debtor_pan_number") or fields.get("pan_number")
        debtor_dob = (
            debtor_dob
            or fields.get("debtor_date_of_birth")
            or fields.get("date_of_birth")
            or fields.get("dob")
        )

    subject_fields = {
        "cersai_search_type": CERSAI_DEBTOR_BASED,
        "debtor_name": debtor_name,
        "debtor_pan_number": debtor_pan,
        "debtor_date_of_birth": debtor_dob,
        "applicant_name": debtor_name,
        "pan_number": debtor_pan,
        "date_of_birth": debtor_dob,
    }
    return {
        "document_type": "CERSAI Report",
        "ocr_text": "",
        "extracted_fields": subject_fields,
    }


def _resolve_cersai_debtor_owner(
    pages: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a debtor-based report by debtor PAN, then debtor identity."""
    subject_page = _cersai_debtor_identity_page(pages)
    observations = identity_observations([subject_page])
    observed_pans = {
        re.sub(r"\s+", "", str(value or "")).upper()
        for value in observations.get("pan_number") or []
        if re.fullmatch(
            r"[A-Z]{5}\d{4}[A-Z]",
            re.sub(r"\s+", "", str(value or "")).upper(),
        )
    }
    if observed_pans:
        pan_matches = {
            person_id
            for person_id, person in people.items()
            if re.sub(
                r"\s+",
                "",
                str(first_value(person, FIELD_ALIASES["pan_number"]) or ""),
            ).upper()
            in observed_pans
        }
        if len(pan_matches) == 1:
            return {
                "person_id": next(iter(pan_matches)),
                "confidence": 1.0,
                "evidence": ["cersai_debtor_pan_number", "pan_number"],
            }
        return {
            "person_id": None,
            "confidence": 0.0,
            "evidence": [
                "cersai_debtor_pan_ambiguous"
                if pan_matches
                else "cersai_debtor_pan_not_in_trusted_data"
            ],
        }

    identity = _score_people([subject_page], people)
    if identity.get("best_id"):
        return {
            "person_id": identity["best_id"],
            "confidence": identity["confidence"],
            "evidence": sorted(
                set(
                    [
                        *(identity.get("evidence") or []),
                        "cersai_debtor_identity",
                    ]
                )
            ),
        }
    return {
        "person_id": None,
        "confidence": 0.0,
        "evidence": ["cersai_debtor_identity_unresolved"],
    }


def _cersai_document_groups(pages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group contiguous CERSAI pages so result pages inherit the debtor owner."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_source: str | None = None
    current_has_search = False

    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        if str(page.get("document_type") or "").strip().casefold() != "cersai report":
            if current:
                groups.append(current)
            current = []
            current_source = None
            current_has_search = False
            continue

        source = (
            str(
                page.get("source_document_id")
                or page.get("document_instance_id")
                or page.get("report_id")
                or ""
            ).strip()
            or None
        )
        fields = page.get("extracted_fields")
        fields = fields if isinstance(fields, dict) else {}
        page_has_search = bool(
            re.search(r"\bsearch\s+criteria\s+entered\b", str(page.get("ocr_text") or ""), re.I)
            or fields.get("debtor_name")
            or fields.get("debtor_pan_number")
        )
        source_changed = bool(current and current_source and source and current_source != source)
        starts_next_report = bool(current and current_has_search and page_has_search)
        if source_changed or starts_next_report:
            groups.append(current)
            current = []
            current_has_search = False

        current.append(page)
        current_source = source or current_source
        current_has_search = current_has_search or page_has_search

    if current:
        groups.append(current)
    return groups
