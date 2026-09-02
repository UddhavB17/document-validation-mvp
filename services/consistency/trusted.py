"""Consistency-check submodule."""

from __future__ import annotations

import re
from typing import Any

from services.consistency.constants import (
    ADDRESS_FIELDS,
    EXACT_FIELDS,
    HOLDER_NAME_FIELDS,
    LOAN_FIELDS,
    NAME_FIELDS,
    PERSON_FIELDS,
)
from services.consistency.matching import (
    _anomaly,
    _lookup,
    _matches,
    _trusted_address_variants,
)
from services.consistency.page_support import _page_text_supports_value
from services.person_names import (
    is_person_name_candidate,
)


def _trusted_matches(
    observations: list[dict], people: dict[str, dict], trusted: dict
) -> list[dict]:
    anomalies: list[dict] = []
    emitted: set[tuple[str, str, int | None]] = set()
    multi_person = len(people) > 1
    for obs in observations:
        person_id = obs["person_id"]
        field = obs["field"]
        # Ownership was resolved from the complete document/record before
        # observations were flattened. Never infer an owner from the very value
        # that is about to be reported as a mismatch. A unique, positive exact-ID
        # match may still correct an explicitly wrong page stamp.
        if (
            people
            and person_id in people
            and field in {"pan_number", "aadhaar_number", "aadhaar_last4"}
        ):
            exact_owner = _positive_exact_identity_owner(field, obs["value"], people)
            if exact_owner and exact_owner != person_id:
                person_id = exact_owner
                obs = {**obs, "person_id": exact_owner}

        if person_id in {"", "unassigned"} and field in PERSON_FIELDS:
            # Unresolved owner: do not invent a mismatch against anyone.
            # Single-person manifests still contain other people's documents
            # (guarantors, family); those pages surface as AUTO_OWNER_UNRESOLVED.
            continue
        person = people.get(person_id, {})
        if field in PERSON_FIELDS:
            expected = _lookup(person, field)
            # Never fall back to flat/primary trusted dump for person fields when
            # multiple people exist; that is the cross-person mismatch bug.
            if expected in (None, "") and not multi_person:
                expected = _lookup(trusted, field)
        else:
            expected = _lookup(trusted, field)
            if expected in (None, "") and field in LOAN_FIELDS:
                expected = _lookup(next(iter(people.values()), {}), field)
        address_records: list[dict | None] = [person]
        if not multi_person or person_id == "primary":
            # Flat/root person fields in the company dump describe the primary
            # borrower.  They must not become accepted address variants for a
            # co-applicant or guarantor in a multi-person manifest.
            address_records.append(trusted)
        address_variants = (
            _trusted_address_variants(*address_records) if field in ADDRESS_FIELDS else []
        )
        if address_variants and any(
            _matches("address", value, obs["value"]) for value in address_variants
        ):
            continue
        if expected in (None, "") and address_variants:
            expected = address_variants[0]
        if field in NAME_FIELDS and not is_person_name_candidate(expected):
            continue
        if expected in (None, "") or _matches(field, expected, obs["value"]):
            continue
        # Multi-KYC collage pages often extract the wrong card's address. If the
        # page OCR still contains the trusted address/prefix, do not flag it.
        if field in ADDRESS_FIELDS and _page_text_supports_value(obs.get("ocr_text"), expected):
            continue
        # Person PIN on the extracted address + short trusted relation prefix
        # is operationally consistent for rural KYC dumps.
        if field in ADDRESS_FIELDS:
            person_pin = str(person.get("pin_code") or "")
            found_pins = set(re.findall(r"\b[1-8]\d{5}\b", str(obs["value"])))
            expected_tokens = set(re.findall(r"[a-z0-9]+", str(expected).lower()))
            if person_pin and person_pin in found_pins and len(expected_tokens) <= 4:
                continue
        # If the extracted name matches another known person, this is ownership
        # noise rather than a trusted-data mismatch for the assigned person.
        if (
            field in HOLDER_NAME_FIELDS
            and people
            and any(
                other_id != person_id
                and _matches("applicant_name", other.get("applicant_name"), obs["value"])
                for other_id, other in people.items()
            )
        ):
            continue
        # A name that adds only the person's trusted father/mother tokens
        # ("Anupkumar Chetanbhai Suthar" for "Suthar Anupkumar") identifies
        # the same person in Indian naming conventions.
        if field in HOLDER_NAME_FIELDS and _name_matches_with_relatives(obs["value"], person):
            continue
        key = (person_id, field, obs["page_number"])
        if key in emitted:
            continue
        emitted.add(key)
        anomalies.append(
            _anomaly(
                f"TRUSTED_{field.upper()}_MISMATCH",
                "HIGH" if field in EXACT_FIELDS | NAME_FIELDS else "MEDIUM",
                expected,
                obs["value"],
                {**obs, "person_id": person_id},
                f"{field.replace('_', ' ').title()} does not match the trusted JSON/database dump.",
            )
        )
    return anomalies


def _name_matches_with_relatives(observed: Any, person: dict) -> bool:
    if not isinstance(person, dict) or not person:
        return False
    from services.person_ownership import name_matches_trusted_person

    return name_matches_trusted_person(observed, person)


def _positive_exact_identity_owner(field: str, value: Any, people: dict[str, dict]) -> str | None:
    matches = [
        person_id
        for person_id, person in people.items()
        if _lookup(person, field) not in (None, "")
        and _matches(field, _lookup(person, field), value)
    ]
    return matches[0] if len(matches) == 1 else None
