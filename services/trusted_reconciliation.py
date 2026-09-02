"""Coverage matrix for trusted JSON/database fields versus document evidence."""

from __future__ import annotations

from collections import Counter
from typing import Any

from services.consistency_checks import (
    LOAN_FIELDS,
    PERSON_FIELDS,
    _canonical,
    _matches,
    _observations,
    _people,
)


_GLOBAL_COMPARABLE_FIELDS = LOAN_FIELDS | {
    "branch",
    "case_type",
}
_IGNORED_METADATA_FIELDS = {
    "schema_version",
    "source",
    "conversion_warnings",
    "person_id",
    "role",
}
_SENSITIVE_FIELDS = {
    "aadhaar_number",
    "aadhaar_last4",
    "pan_number",
    "account_number",
    "phone_number",
    "bank_linked_mobile",
}


def build_trusted_reconciliation(
    pages: list[dict[str, Any]], trusted: dict[str, Any] | None
) -> dict[str, Any]:
    """Return an auditable status for every scalar field in the trusted dump.

    ``NOT_OBSERVED`` is coverage information, not automatically an exception:
    many database-only workflow fields are not expected to be printed.  Real
    observed disagreements continue to be emitted by consistency checks.
    """
    trusted = trusted or {}
    people = _people(trusted)
    observations = _observations(pages, people)
    entries: list[dict[str, Any]] = []

    global_values = _global_values(trusted, people)
    for field, expected in sorted(global_values.items()):
        field_observations = [item for item in observations if item["field"] == field]
        entries.append(
            _entry(
                scope="loan",
                person_id=None,
                field=field,
                expected=expected,
                observations=field_observations,
                checkable=field in _GLOBAL_COMPARABLE_FIELDS,
            )
        )

    for person_id, person in sorted(people.items()):
        for raw_field, expected in sorted(person.items(), key=lambda item: str(item[0])):
            field = _canonical(str(raw_field))
            if field in _IGNORED_METADATA_FIELDS or expected in (None, "", [], {}):
                continue
            # Loan terms copied into the primary person record are reconciled
            # once at loan scope, not duplicated for every person.
            if field in LOAN_FIELDS and field not in PERSON_FIELDS:
                continue
            person_observations = [
                item
                for item in observations
                if item["field"] == field and item["person_id"] == person_id
            ]
            entries.append(
                _entry(
                    scope="person",
                    person_id=person_id,
                    field=field,
                    expected=expected,
                    observations=person_observations,
                    checkable=field in PERSON_FIELDS,
                )
            )

    counts = Counter(entry["status"] for entry in entries)
    checked = sum(counts[status] for status in ("MATCH", "MATCH_WITH_CONFLICTS", "MISMATCH"))
    return {
        "summary": {
            "trusted_fields": len(entries),
            "checkable_fields": len(entries) - counts["NOT_CHECKABLE"],
            "checked_fields": checked,
            "matched_fields": counts["MATCH"],
            "matched_with_conflicts": counts["MATCH_WITH_CONFLICTS"],
            "mismatched_fields": counts["MISMATCH"],
            "not_observed_fields": counts["NOT_OBSERVED"],
            "not_checkable_fields": counts["NOT_CHECKABLE"],
        },
        "fields": entries,
    }


def _global_values(trusted: dict[str, Any], people: dict[str, dict]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_field, value in trusted.items():
        if isinstance(value, (dict, list)) or value in (None, "", [], {}):
            continue
        field = _canonical(str(raw_field))
        if field in _IGNORED_METADATA_FIELDS:
            continue
        if people and field in PERSON_FIELDS and field not in _GLOBAL_COMPARABLE_FIELDS:
            # Normalized dumps repeat the primary person's fields at the root.
            # Reconcile those under their person scope only.
            continue
        result[field] = value

    primary = people.get("primary")
    if not isinstance(primary, dict):
        primary = next((person for person in people.values() if isinstance(person, dict)), {})
    for raw_field, value in primary.items():
        field = _canonical(str(raw_field))
        if (
            field in LOAN_FIELDS
            and field not in PERSON_FIELDS
            and value not in (None, "", [], {})
            and field not in result
        ):
            result[field] = value
    return result


def _entry(
    *,
    scope: str,
    person_id: str | None,
    field: str,
    expected: Any,
    observations: list[dict[str, Any]],
    checkable: bool,
) -> dict[str, Any]:
    if not checkable:
        status = "NOT_CHECKABLE"
    elif not observations:
        status = "NOT_OBSERVED"
    else:
        matches = [item for item in observations if _matches(field, expected, item["value"])]
        conflicts = [item for item in observations if item not in matches]
        if matches and conflicts:
            status = "MATCH_WITH_CONFLICTS"
        elif matches:
            status = "MATCH"
        else:
            status = "MISMATCH"

    evidence = [
        {
            "value": _display_value(field, item["value"]),
            "document_type": item.get("document_type"),
            "page_number": item.get("page_number"),
            "match": _matches(field, expected, item["value"]),
        }
        for item in observations[:12]
    ]
    entry: dict[str, Any] = {
        "scope": scope,
        "field": field,
        "status": status,
        "expected_value": _display_value(field, expected),
        "evidence": evidence,
    }
    if person_id is not None:
        entry["person_id"] = person_id
    return entry


def _display_value(field: str, value: Any) -> Any:
    if field not in _SENSITIVE_FIELDS or value in (None, ""):
        return value
    text = str(value)
    compact = "".join(character for character in text if character.isalnum())
    if len(compact) <= 4:
        return f"…{compact}"
    return f"{'*' * max(4, len(compact) - 4)}{compact[-4:]}"
