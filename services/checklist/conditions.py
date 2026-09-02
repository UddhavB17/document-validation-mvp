"""Checklist engine submodule."""

from __future__ import annotations

from services.checklist.anomaly_builder import build_anomaly
from services.checklist.page_helpers import _missing_presence_anomaly, _numeric


def _condition_value(field: str, aliases: list[str], system_data: dict) -> object:
    """Resolve a condition field, including values derived from borrower data."""
    for key in [field, *aliases]:
        value = system_data.get(key)
        if value not in (None, ""):
            return value

    people = _people(system_data)
    if field in {"borrower_count", "people_count"} and people:
        if field == "people_count":
            return len(people)
        return sum(
            1
            for person in people.values()
            if str(person.get("role") or "").strip().lower() not in {"guarantor", "gtr"}
        )
    if field == "has_guarantor" and people:
        return any(
            str(person.get("role") or "").strip().lower() in {"guarantor", "gtr"}
            for person in people.values()
        )
    if field == "pdc_person_count" and people:
        return len(_scoped_people("pdc_people", system_data))
    return None


def condition_applies(condition: dict | None, system_data: dict) -> bool | None:
    """Return True/False for a known condition, or None when data is unavailable."""
    if not condition:
        return True
    if "all" in condition:
        results = [condition_applies(item, system_data) for item in condition.get("all") or []]
        if any(result is False for result in results):
            return False
        return None if any(result is None for result in results) else True
    if "any" in condition:
        results = [condition_applies(item, system_data) for item in condition.get("any") or []]
        if any(result is True for result in results):
            return True
        return None if any(result is None for result in results) else False
    if "not" in condition:
        result = condition_applies(condition.get("not"), system_data)
        return None if result is None else not result
    if "coalesce" in condition:
        for item in condition.get("coalesce") or []:
            result = condition_applies(item, system_data)
            if result is not None:
                return result
        return None

    field = str(condition.get("field") or "")
    value = _condition_value(field, list(condition.get("field_aliases") or []), system_data)
    if value in (None, ""):
        return None
    expected = condition.get("value")
    operator = str(condition.get("operator") or "eq").lower()
    if operator in {">field", ">=field", "<field", "<=field"}:
        expected = _condition_value(
            str(condition.get("value_field") or ""),
            list(condition.get("value_field_aliases") or []),
            system_data,
        )
        left = _numeric(value)
        right = _numeric(expected)
        if left is None or right is None:
            return None
        return {
            ">field": left > right,
            ">=field": left >= right,
            "<field": left < right,
            "<=field": left <= right,
        }[operator]
    if operator in {">", ">=", "<", "<="}:
        left = _numeric(value)
        right = _numeric(expected)
        if left is None or right is None:
            return None
        return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[
            operator
        ]
    if operator in {"in", "not_in"}:
        values = {str(item).strip().lower() for item in (expected or [])}
        result = str(value).strip().lower() in values
        return result if operator == "in" else not result
    if operator in {"truthy", "is_true"}:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
    if operator in {"falsy", "is_false"}:
        return str(value).strip().lower() in {"0", "false", "no", "n", "off"}
    if operator in {"ne", "!=", "not_eq"}:
        return str(value).strip().lower() != str(expected).strip().lower()
    return str(value).strip().lower() == str(expected).strip().lower()


def _people(system_data: dict) -> dict[str, dict]:
    raw = system_data.get("people") or system_data.get("reference_data")
    if isinstance(raw, dict) and any(isinstance(value, dict) for value in raw.values()):
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}
    return {}


def _scoped_people(scope: str | None, system_data: dict) -> dict[str, dict]:
    people = _people(system_data)
    if not people or scope not in {"each_borrower", "each_person", "banking_people", "pdc_people"}:
        return {}
    if scope == "banking_people":
        selected = {
            person_id: person
            for person_id, person in people.items()
            if person_id == "primary"
            or str(person.get("role") or "").lower()
            in {"applicant", "primary", "primary_applicant"}
            or bool(person.get("income_earner"))
            or bool(person.get("repayment_contributor"))
        }
        return selected or people
    if scope == "pdc_people":
        return {
            person_id: person
            for person_id, person in people.items()
            if str(person.get("role") or "").strip().lower() in {"guarantor", "gtr"}
            or (
                str(person.get("role") or "").strip().lower() == "coapplicant"
                and (
                    bool(person.get("income_earner"))
                    or str(person.get("gender") or "").strip().lower() in {"female", "f"}
                )
            )
        }
    if scope == "each_borrower":
        return {
            person_id: person
            for person_id, person in people.items()
            if str(person.get("role") or "").strip().lower() not in {"guarantor", "gtr"}
        }
    return people


def _applicability_unknown_anomaly(item: dict, *, document_type: str | None = None) -> dict:
    s_no = item.get("s_no")
    anomaly = build_anomaly(
        rule_id=f"APPLICABILITY_UNKNOWN_S{s_no}",
        s_no=s_no,
        severity="LOW",
        expected_value=item.get("condition_description") or "Applicability input available",
        found_value="Required system value not supplied",
        reason=f"Could not determine whether checklist item {s_no} applies.",
        document_type=document_type,
    )
    anomaly["status"] = "INTAKE_REQUIREMENT"
    anomaly["source"] = "trusted_json_or_system_input"
    anomaly["is_pdf_error"] = False
    return anomaly


def system_flag_state(item: dict, system_data: dict) -> bool | None:
    field = str(item.get("system_field") or "")
    aliases = list(item.get("system_field_aliases") or [])
    value = _condition_value(field, aliases, system_data)
    if value in (None, ""):
        return None
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "checked",
        "complete",
        "completed",
    }


def _system_flag_anomaly(item: dict, system_data: dict) -> dict | None:
    state = system_flag_state(item, system_data)
    field = str(item.get("system_field") or "")
    if state is None:
        anomaly = build_anomaly(
            rule_id=f"SYSTEM_VALUE_UNKNOWN_S{item.get('s_no')}",
            s_no=item.get("s_no"),
            severity="LOW",
            expected_value=f"{field}=true",
            found_value="System value not supplied",
            reason=item.get("description", ""),
            document_type=item.get("document_type"),
        )
        anomaly["status"] = "INTAKE_REQUIREMENT"
        anomaly["source"] = "trusted_json_or_system_input"
        anomaly["is_pdf_error"] = False
        return anomaly
    if state:
        return None
    return _missing_presence_anomaly(
        item,
        document_type=str(item.get("document_type") or item.get("description") or "System check"),
    )
