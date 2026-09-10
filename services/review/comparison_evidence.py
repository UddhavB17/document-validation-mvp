"""Evidence-backed review comparisons, independent of optional OCR exports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.consistency_checks import _matches, _observations
from services.person_ownership import assign_page_owners
from services.review.types import FieldStatus


def comparison_observations(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    # Ownership and validation helpers mutate their input. Never change the
    # public review summaries or let private provenance escape in the response.
    evidence = deepcopy(pages)
    aliases = {"phone": "phone_number", "pincode": "pin_code", "pan": "pan_number"}
    for page in evidence:
        fields = page.setdefault("extracted_fields", {})
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
            "pin_code",
            "aadhaar_last4",
            "gender",
            "father_name",
        },
    )


def observed_field(
    observations: list[dict], field_name: str, expected: Any, person_id: str | None = None
) -> tuple[str | None, list[int], FieldStatus]:
    aliases = {
        "loan_id": {"loan_id", "application_number"},
        "address": {"address", "permanent_address", "communication_address"},
    }
    field_names = aliases.get(field_name, {field_name})
    candidates = [
        row
        for row in observations
        if row["field"] in field_names
        and (person_id is None or row["person_id"] == person_id)
        and isinstance(row["value"], (str, int, float))
    ]
    if not candidates:
        return None, [], "attention"
    # Selection is deterministic and independent of the expected value. Keep
    # conflicting sources visible instead of choosing whichever happens to match.
    extracted = str(candidates[0]["value"])
    source_pages = sorted({int(row["page_number"]) for row in candidates if row["page_number"]})
    matches = [_matches(field_name, expected, row["value"]) for row in candidates]
    conflicts = any(not _matches(field_name, extracted, row["value"]) for row in candidates[1:])
    status: FieldStatus = "match"
    if not any(matches):
        status = "mismatch"
    elif not all(matches) or conflicts:
        status = "attention"
    return extracted, source_pages, status
