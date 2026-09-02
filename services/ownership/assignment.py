"""Person-ownership submodule."""

from __future__ import annotations

import re
from typing import Any

from services.cersai import (
    ASSET_BASED as CERSAI_ASSET_BASED,
)
from services.cersai import (
    DEBTOR_BASED as CERSAI_DEBTOR_BASED,
)
from services.ownership.cersai import _cersai_document_groups, _cersai_search_type
from services.ownership.constants import FIELD_ALIASES, PERSON_SCOPED_DOCUMENT_TYPES
from services.ownership.document_policy import (
    bank_statement_has_holder_evidence,
    document_requires_person_owner,
    people_from_trusted,
)
from services.ownership.matching import first_value


def _resolve_person_owner(*args, **kwargs):
    from services.ownership.resolution import resolve_person_owner

    return resolve_person_owner(*args, **kwargs)


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
        asset_pages = {
            id(page)
            for group in _cersai_document_groups(pages)
            if _cersai_search_type(group) == CERSAI_ASSET_BASED
            for page in group
        }
        for page in pages:
            if id(page) in asset_pages:
                page["person_id"] = None
                page["applicant_role"] = None
                fields = page.get("extracted_fields")
                fields = dict(fields) if isinstance(fields, dict) else {}
                fields["_ownership"] = {
                    "person_id": None,
                    "confidence": 1.0,
                    "evidence": ["cersai_asset_based"],
                    "cersai_search_type": CERSAI_ASSET_BASED,
                    "document_scope": "loan_level",
                }
                page["extracted_fields"] = fields
                continue
            if not page.get("person_id") and not page.get("applicant_role"):
                page["person_id"] = "unassigned"
        return pages

    cersai_group_owners: dict[int, dict[str, Any]] = {}
    cersai_group_types: dict[int, str] = {}
    for group in _cersai_document_groups(pages):
        group_type = _cersai_search_type(group)
        if group_type not in {CERSAI_DEBTOR_BASED, CERSAI_ASSET_BASED}:
            continue
        group_owner = _resolve_person_owner(group, people, "CERSAI Report")
        for grouped_page in group:
            cersai_group_owners[id(grouped_page)] = group_owner
            cersai_group_types[id(grouped_page)] = group_type

    for page in pages:
        existing = str(page.get("person_id") or page.get("applicant_role") or "").strip()
        provided = existing if existing and existing not in {"unassigned", "unknown"} else None
        # Manifest/ZIP mapping may live on the page or in extraction metadata.
        fields = (
            page.get("extracted_fields") if isinstance(page.get("extracted_fields"), dict) else {}
        )
        ownership = fields.get("_ownership") if isinstance(fields, dict) else None
        provided_person_is_document_scope = bool(
            isinstance(ownership, dict)
            and str(ownership.get("person_id") or "").strip() == provided
            and ownership.get("document_scope") == "single_person"
            and "document_index" in set(ownership.get("evidence") or [])
        )
        mapped = fields.get("_mapped_extraction") if isinstance(fields, dict) else None
        if isinstance(mapped, dict) and mapped.get("person_id"):
            provided = str(mapped.get("person_id"))
        zip_cls = fields.get("_zip_source_classification") if isinstance(fields, dict) else None
        if isinstance(zip_cls, dict) and zip_cls.get("predicted_person_id"):
            provided = provided or str(zip_cls.get("predicted_person_id"))

        document_type = str(page.get("document_type") or "")
        if id(page) in cersai_group_owners:
            owner = dict(cersai_group_owners[id(page)])
        else:
            owner = _resolve_person_owner(
                [page],
                people,
                document_type,
                provided_person_id=provided,
                provided_person_is_document_scope=provided_person_is_document_scope,
                source_filename=str(page.get("source_filename") or "") or None,
            )
        type_key = document_type.strip().lower()
        person_id = owner.get("person_id")
        cersai_group_type = cersai_group_types.get(id(page))
        is_asset_based_cersai = cersai_group_type == CERSAI_ASSET_BASED
        requires_person = (
            cersai_group_type == CERSAI_DEBTOR_BASED
            or document_requires_person_owner(document_type, [page])
        )

        if person_id is None and not is_asset_based_cersai:
            if requires_person or type_key in PERSON_SCOPED_DOCUMENT_TYPES or len(people) > 1:
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
            "source_role": owner.get("source_role"),
        }
        if cersai_group_type:
            ownership_meta["cersai_search_type"] = cersai_group_type
        if owner.get("document_scope"):
            ownership_meta["document_scope"] = owner["document_scope"]
        if provided_person_is_document_scope:
            # Keep the provenance durable across the checklist's intentional
            # second ownership pass inside consistency checks.
            ownership_meta["document_scope"] = "single_person"
            ownership_meta["evidence"] = sorted(
                set([*(ownership_meta.get("evidence") or []), "document_index"])
            )
        if isinstance(fields, dict):
            fields = dict(fields)
            fields["_ownership"] = ownership_meta
            page["extracted_fields"] = fields
        else:
            page["extracted_fields"] = {"_ownership": ownership_meta}

    return pages


def source_role_from_filename(value: Any) -> str | None:
    """Return an applicant role from an explicit ZIP path segment.

    Segment matching is intentional: ``Co-Applicant`` must never be caught by
    a naive substring check for ``Applicant``.
    """
    segments = re.split(r"[/\\\\]+", str(value or ""))
    for segment in segments:
        key = re.sub(r"[^a-z0-9]+", "", segment.casefold())
        if key.startswith("coapplicant") or key.startswith("coborrower"):
            return "coapplicant"
        if key.startswith("guarantor"):
            return "guarantor"
        if key == "applicant" or key.startswith("primaryapplicant"):
            return "primary"
    return None


def _filename_person_name_owner(
    value: Any,
    people: dict[str, dict[str, Any]],
) -> str | None:
    """Resolve a unique full trusted name explicitly present in a basename."""
    basename = re.split(r"[/\\]+", str(value or ""))[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", basename)
    stem_tokens = re.findall(r"[a-z0-9]+", stem.casefold())
    matches: list[str] = []
    for person_id, person in people.items():
        expected = first_value(person, FIELD_ALIASES["applicant_name"])
        name_tokens = re.findall(r"[a-z0-9]+", str(expected or "").casefold())
        if len(name_tokens) < 2:
            continue
        width = len(name_tokens)
        if any(
            stem_tokens[index : index + width] == name_tokens
            for index in range(len(stem_tokens) - width + 1)
        ):
            matches.append(person_id)
    return matches[0] if len(matches) == 1 else None


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
        if not document_requires_person_owner(document_type, page):
            continue
        if (
            document_type.strip().casefold() == "bank statement"
            and not bank_statement_has_holder_evidence(page)
        ):
            # Checklist item 17 validates recent account history. A statement
            # that genuinely omits the holder name must not fail that rule via
            # an unrelated automatic-ownership warning.
            continue
        fields = (
            page.get("extracted_fields") if isinstance(page.get("extracted_fields"), dict) else {}
        )
        ownership = fields.get("_ownership") if isinstance(fields, dict) else {}
        if isinstance(ownership, dict) and "source_role_not_in_trusted_data" in set(
            ownership.get("evidence") or []
        ):
            # The automatic index emits a single role-level trusted-data scope
            # item; avoid an additional unresolved-owner warning per page.
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
