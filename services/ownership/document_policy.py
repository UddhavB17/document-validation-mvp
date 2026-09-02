"""Person-ownership submodule."""

from __future__ import annotations

from typing import Any

from services.cersai import (
    DEBTOR_BASED as CERSAI_DEBTOR_BASED,
)
from services.ownership._helpers import first_value
from services.ownership.cersai import _as_page_list, _cersai_search_type
from services.ownership.constants import (
    FIELD_ALIASES,
    LOAN_LEVEL_DOCUMENT_TYPES,
    PERSON_SCOPED_DOCUMENT_TYPES,
)
from services.ownership.observations import _banking_holder_name_observations
from services.person_names import is_person_name_candidate


def people_from_trusted(trusted: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = (trusted or {}).get("people") or (trusted or {}).get("reference_data") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def document_requires_person_owner(
    document_type: str,
    pages: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> bool:
    """Return whether this document must resolve to a trusted person."""
    type_key = str(document_type or "").strip().casefold()
    if type_key == "cersai report":
        return _cersai_search_type(_as_page_list(pages)) == CERSAI_DEBTOR_BASED
    return type_key in PERSON_SCOPED_DOCUMENT_TYPES


def document_is_loan_level(
    document_type: str,
    pages: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> bool:
    """Return whether ownership is loan/property-level rather than person-level."""
    type_key = str(document_type or "").strip().casefold()
    if type_key == "cersai report":
        return _cersai_search_type(_as_page_list(pages)) != CERSAI_DEBTOR_BASED
    return type_key in LOAN_LEVEL_DOCUMENT_TYPES


def bank_statement_has_holder_evidence(page: dict[str, Any]) -> bool:
    """Return whether a bank statement contains an actual holder-name candidate."""
    fields = page.get("extracted_fields")
    fields = fields if isinstance(fields, dict) else {}
    holder = first_value(fields, FIELD_ALIASES["applicant_name"])
    if holder not in (None, "") and is_person_name_candidate(holder):
        return True
    return any(
        is_person_name_candidate(candidate)
        for candidate in _banking_holder_name_observations(str(page.get("ocr_text") or ""))
    )
