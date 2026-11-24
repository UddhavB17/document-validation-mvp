"""Evidence-backed review comparisons, independent of optional OCR exports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.consistency_checks import ADDRESS_FIELDS, _matches, _observations
from services.field_extractor import (
    _extract_labeled_apr_row,
    _extract_permanent_address_after_current_residence,
)
from services.identity_matching import address_component_conflict
from services.person_ownership import assign_page_owners
from services.review.types import FieldStatus


def comparison_observations(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    # Ownership and validation helpers mutate their input. Never change the
    # public review summaries or let private provenance escape in the response.
    evidence = deepcopy(pages)
    aliases = {"phone": "phone_number", "pincode": "pin_code", "pan": "pan_number"}
    for page in evidence:
        fields = page.setdefault("extracted_fields", {})
        document_type = str(page.get("document_type") or "").casefold()
        if document_type == "kfs" and fields.get("apr") in (None, ""):
            apr = _extract_labeled_apr_row(page.get("ocr_text") or "")
            if apr is not None:
                fields["apr"] = apr
        if (
            document_type == "application form"
            and not fields.get("permanent_address")
            and not fields.get("person_records")
        ):
            # Older saved results can have the address in OCR without an
            # extracted field. Reuse the form fallback and normal ownership gates.
            recovered = _extract_permanent_address_after_current_residence(
                page.get("ocr_text") or ""
            )
            if recovered:
                fields["permanent_address"] = recovered
        records = [fields, *(fields.get("person_records") or [])]
        for record in records:
            if not isinstance(record, dict):
                continue
            for alias, canonical in aliases.items():
                if record.get(canonical) in (None, "") and record.get(alias) not in (None, ""):
                    record[canonical] = record[alias]
                    # Aliases must retain the original field's reliability gate.
                    provenance = record.get("_field_provenance") or {}
                    if alias in provenance:
                        provenance.setdefault(canonical, provenance[alias])
    assign_page_owners(evidence, {"people": people})
    return _observations(
        evidence,
        people,
        included_fields={
            "loan_id",
            "application_number",
            "sanction_amount",
            "loan_amount",
            "roi",
            "apr",
            "tenure",
            "emi",
            "installment_count",
            "branch",
            "product_type",
            "case_type",
            "applicant_name",
            "pan_number",
            "date_of_birth",
            "phone_number",
            "address",
            "permanent_address",
            "communication_address",
            "current_address",
            "pin_code",
            "aadhaar_last4",
            "gender",
            "father_name",
        },
    )


def observed_field(
    observations: list[dict],
    field_name: str,
    expected: Any,
    person_id: str | None = None,
    *,
    alternate_addresses: tuple[Any, ...] = (),
) -> tuple[str | None, list[int], FieldStatus]:
    aliases = {
        "loan_id": {"loan_id", "application_number"},
        "address": {"address", "permanent_address"},
        "permanent_address": {"address", "permanent_address"},
    }
    field_names = aliases.get(field_name, {field_name})
    candidates = [
        row
        for row in observations
        if row["field"] in field_names
        and (person_id is None or row["person_id"] == person_id)
        and isinstance(row["value"], (str, int, float))
    ]
    if alternate_addresses:
        # An unlabelled address may be the person's documented current or
        # mailing address. Don't treat it as a conflicting permanent address.
        candidates = [
            row
            for row in candidates
            if row["field"] != "address"
            or _matches(field_name, expected, row["value"])
            or not any(_matches(field_name, option, row["value"]) for option in alternate_addresses)
        ]
    if not candidates:
        return None, [], "attention"
    # A clear unit/component disagreement is stronger than a partial or matching
    # OCR source. Prefer that source so the reviewer sees the contradiction.
    explicit_conflict = next(
        (
            row
            for row in candidates
            if (field_name in ADDRESS_FIELDS and address_component_conflict(expected, row["value"]))
            or (
                row.get("source_type") == "legal_party"
                and not _matches(field_name, expected, row["value"])
            )
        ),
        None,
    )

    # Selection is deterministic and independent of the expected value except
    # for the explicit, source-backed address conflict above.
    extracted = str((explicit_conflict or candidates[0])["value"])
    source_pages = sorted({int(row["page_number"]) for row in candidates if row["page_number"]})
    if explicit_conflict:
        preferred_page = int(explicit_conflict.get("page_number") or 0)
        if preferred_page in source_pages:
            source_pages.remove(preferred_page)
            source_pages.insert(0, preferred_page)
        return extracted, source_pages, "mismatch"
    matches = [_matches(field_name, expected, row["value"]) for row in candidates]
    conflicts = any(not _matches(field_name, extracted, row["value"]) for row in candidates[1:])
    status: FieldStatus = "match"
    if not any(matches):
        status = "mismatch"
    elif not all(matches) or conflicts:
        status = "attention"
    return extracted, source_pages, status
