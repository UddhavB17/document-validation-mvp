"""Checklist matching logic."""

import os
from datetime import datetime
import re

from services import checklist_service
from services.config import effective_config
from services.page_quality import confident_pages_for_types, is_confident_document_match
from services.processing_policy import is_ocr_skipped_page

try:
    from rapidfuzz import fuzz
except Exception:
    from difflib import SequenceMatcher

    class fuzz:
        @staticmethod
        def ratio(left: str, right: str) -> int:
            return int(SequenceMatcher(None, left, right).ratio() * 100)


def _parse_date(value: object) -> datetime:
    try:
        from dateutil import parser

        return parser.parse(str(value))
    except Exception:
        return datetime.fromisoformat(str(value))


def build_anomaly(
    rule_id: str,
    s_no: int | None,
    severity: str,
    expected_value: object,
    found_value: object,
    reason: str,
    page_number: int | None = None,
    document_type: str | None = None,
    person_id: str | None = None,
) -> dict:
    return {
        "rule_id": rule_id,
        "s_no": s_no,
        "severity": severity,
        "document_type": document_type,
        "expected_value": expected_value,
        "found_value": found_value,
        "page_number": page_number,
        "person_id": person_id,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }


def check_presence_any(pages: list[dict], document_types: list[str]) -> dict:
    found_types = {
        document_type
        for document_type in document_types
        if any(is_confident_document_match(page, document_type) for page in pages)
    }
    found = any(document_type in found_types for document_type in document_types)

    if not found:
        return {
            "passed": False,
            "found_value": "None of required types found",
            "expected_value": f"Any one of: {', '.join(document_types)}",
        }

    matched = [document_type for document_type in document_types if document_type in found_types]
    return {"passed": True, "found_value": matched[0]}


def check_field_match(extracted_fields: dict, system_data: dict, field_names: list[str]) -> list[dict]:
    anomalies = []

    for field in field_names:
        system_val = system_data.get(field)
        extracted_val = extracted_fields.get(field)
        if system_val in (None, "") or extracted_val in (None, ""):
            continue

        if field in ["loan_amount", "emi", "tenure", "roi", "interest_rate"]:
            try:
                sys_num = float(str(system_val).replace(",", ""))
                ext_num = float(str(extracted_val).replace(",", ""))
                tolerance = sys_num * 0.01
                if abs(sys_num - ext_num) > tolerance:
                    anomalies.append({"field": field, "expected": system_val, "found": extracted_val})
            except Exception:
                continue
        elif field == "pan_number":
            if str(system_val).upper() != str(extracted_val).upper():
                anomalies.append({"field": field, "expected": system_val, "found": extracted_val})
        else:
            score = fuzz.ratio(str(system_val).lower(), str(extracted_val).lower())
            if score < 85:
                anomalies.append(
                    {
                        "field": field,
                        "expected": system_val,
                        "found": extracted_val,
                        "match_score": score,
                    }
                )

    return anomalies


def check_date_range(extracted_fields: dict, min_months: int) -> dict:
    date_val = extracted_fields.get("statement_period_end")
    if not date_val:
        return {"passed": False, "reason": "Statement date not found"}

    try:
        parsed = _parse_date(date_val)
        months_old = (datetime.now() - parsed).days / 30
        if months_old > min_months:
            return {
                "passed": False,
                "found_value": f"{int(months_old)} months old",
                "expected_value": f"Within {min_months} months",
            }
        return {"passed": True}
    except Exception:
        return {"passed": False, "reason": "Could not parse statement date"}


def check_presence_min_count(pages: list[dict], document_type: str, min_count: int) -> dict:
    found_pages = _find_pages(pages, document_type)
    if len(found_pages) >= min_count:
        return {
            "passed": True,
            "found_value": f"{len(found_pages)} page(s)",
            "expected_value": f"At least {min_count}",
        }
    return {
        "passed": False,
        "found_value": f"{len(found_pages)} page(s)",
        "expected_value": f"At least {min_count} page(s) of {document_type}",
    }


def _numeric(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(re.sub(r"[^0-9.-]", "", str(value)))
    except (TypeError, ValueError):
        return None


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
        return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[operator]
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


# Backward-compatible internal alias used by older tests/imports.
_condition_applies = condition_applies


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
            or str(person.get("role") or "").lower() in {"applicant", "primary", "primary_applicant"}
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
    return build_anomaly(
        rule_id=f"APPLICABILITY_UNKNOWN_S{s_no}",
        s_no=s_no,
        severity="LOW",
        expected_value=item.get("condition_description") or "Applicability input available",
        found_value="Required system value not supplied",
        reason=f"Could not determine whether checklist item {s_no} applies.",
        document_type=document_type,
    )


def system_flag_state(item: dict, system_data: dict) -> bool | None:
    field = str(item.get("system_field") or "")
    aliases = list(item.get("system_field_aliases") or [])
    value = _condition_value(field, aliases, system_data)
    if value in (None, ""):
        return None
    return str(value).strip().lower() in {
        "1", "true", "yes", "y", "on", "checked", "complete", "completed"
    }


def _system_flag_anomaly(item: dict, system_data: dict) -> dict | None:
    state = system_flag_state(item, system_data)
    field = str(item.get("system_field") or "")
    if state is None:
        return build_anomaly(
            rule_id=f"SYSTEM_VALUE_UNKNOWN_S{item.get('s_no')}",
            s_no=item.get("s_no"),
            severity="LOW",
            expected_value=f"{field}=true",
            found_value="System value not supplied",
            reason=item.get("description", ""),
            document_type=item.get("document_type"),
        )
    if state:
        return None
    return _missing_presence_anomaly(item, document_type=str(item.get("document_type") or item.get("description") or "System check"))


def _pages_for_person(pages: list[dict], person_id: str) -> list[dict]:
    return [
        page for page in pages
        if str(page.get("person_id") or page.get("applicant_role") or "") == person_id
    ]


def _missing_presence_anomaly(item: dict, *, document_type: str, person_id: str | None = None) -> dict:
    s_no = item.get("s_no")
    expected = "Document present"
    if person_id:
        expected += f" for {person_id}"
    return build_anomaly(
        rule_id=f"MISSING_DOC_S{s_no}" + (f"_{person_id}" if person_id else ""),
        s_no=s_no,
        severity=item.get("severity_if_missing", "MEDIUM"),
        expected_value=expected,
        found_value="Not found in file",
        reason=item.get("description", ""),
        document_type=document_type,
        person_id=person_id,
    )


def _accuracy_checks_enabled() -> bool:
    return os.getenv("ENABLE_ACCURACY_CHECKS", "true").lower() in {"1", "true", "yes", "on"}


def _run_presence_checks(
    pages: list[dict],
    items: list[dict],
    system_data: dict,
) -> list[dict]:
    anomalies: list[dict] = []

    for item in items:
        check_type = item["check_type"]
        s_no = item.get("s_no")
        description = item.get("description", "")
        severity = item.get("severity_if_missing", "MEDIUM")
        document_type = item.get("document_type")

        applies = condition_applies(item.get("applies_when"), system_data)
        if applies is None:
            document_label = " / ".join(str(value) for value in _document_types(document_type) if value)
            anomalies.append(_applicability_unknown_anomaly(item, document_type=document_label))
            continue
        if applies is False:
            continue

        if check_type == "system_flag":
            anomaly = _system_flag_anomaly(item, system_data)
            if anomaly is not None:
                anomalies.append(anomaly)
            continue

        scoped_people = _scoped_people(item.get("scope"), system_data)
        if scoped_people:
            types = document_type if isinstance(document_type, list) else [document_type]
            for person_id in scoped_people:
                person_pages = _pages_for_person(pages, person_id)
                if item.get("check_type") == "presence_all":
                    missing_types = [doc_type for doc_type in types if not _find_pages(person_pages, doc_type)]
                    for missing_type in missing_types:
                        anomalies.append(_missing_presence_anomaly(item, document_type=missing_type, person_id=person_id))
                elif not check_presence_any(person_pages, types)["passed"]:
                    anomalies.append(
                        _missing_presence_anomaly(item, document_type=", ".join(types), person_id=person_id)
                    )
            continue

        if check_type == "presence":
            found = bool(_find_pages(pages, document_type))
            if not found:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"MISSING_DOC_S{s_no}",
                        s_no=s_no,
                        severity=severity,
                        expected_value="Document present",
                        found_value="Not found in file",
                        reason=description,
                        document_type=document_type,
                    )
                )

        elif check_type == "presence_any":
            result = check_presence_any(pages, document_type)
            if not result["passed"]:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"MISSING_DOC_S{s_no}",
                        s_no=s_no,
                        severity=severity,
                        expected_value=result["expected_value"],
                        found_value=result["found_value"],
                        reason=description,
                        document_type=", ".join(document_type),
                    )
                )

        elif check_type == "presence_min_count":
            min_count = int(item.get("min_count") or 1)
            result = check_presence_min_count(pages, document_type, min_count)
            if not result["passed"]:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"MISSING_DOC_S{s_no}",
                        s_no=s_no,
                        severity=severity,
                        expected_value=result["expected_value"],
                        found_value=result["found_value"],
                        reason=description,
                        document_type=document_type,
                    )
                )

        elif check_type == "presence_all":
            for required_type in document_type:
                if not _find_pages(pages, required_type):
                    anomalies.append(_missing_presence_anomaly(item, document_type=required_type))

        elif check_type == "requirements":
            applicability_unknown_reported = False
            for requirement in item.get("requirements") or []:
                requirement_applies = condition_applies(requirement.get("applies_when"), system_data)
                if requirement_applies is None:
                    if not applicability_unknown_reported:
                        anomalies.append(
                            _applicability_unknown_anomaly(
                                item, document_type=str(requirement.get("document_type") or "")
                            )
                        )
                        applicability_unknown_reported = True
                    continue
                if requirement_applies is False:
                    continue
                required_type = str(requirement.get("document_type") or "")
                requirement_item = {**item, **requirement}
                requirement_scope = requirement.get("scope") or item.get("scope")
                required_people = _scoped_people(requirement_scope, system_data)
                requirement_check_type = str(requirement.get("check_type") or "presence")
                minimum = int(requirement.get("min_count") or 1)
                if required_people:
                    for person_id in required_people:
                        person_pages = _pages_for_person(pages, person_id)
                        found_count = len(_find_pages(person_pages, required_type))
                        if found_count < minimum:
                            anomalies.append(
                                build_anomaly(
                                    rule_id=f"MISSING_DOC_S{s_no}_{person_id}",
                                    s_no=s_no,
                                    severity=requirement_item.get("severity_if_missing", severity),
                                    expected_value=(
                                        f"At least {minimum} {required_type} document(s) for {person_id}"
                                        if requirement_check_type == "presence_min_count" or minimum > 1
                                        else f"Document present for {person_id}"
                                    ),
                                    found_value=f"{found_count} found",
                                    reason=description,
                                    document_type=required_type,
                                    person_id=person_id,
                                )
                            )
                else:
                    found_count = len(_find_pages(pages, required_type))
                    if found_count < minimum:
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"MISSING_DOC_S{s_no}",
                                s_no=s_no,
                                severity=requirement_item.get("severity_if_missing", severity),
                                expected_value=(
                                    f"At least {minimum} {required_type} document(s)"
                                    if requirement_check_type == "presence_min_count" or minimum > 1
                                    else "Document present"
                                ),
                                found_value=f"{found_count} found",
                                reason=description,
                                document_type=required_type,
                            )
                        )

    return anomalies


def _find_pages(pages: list[dict], document_type: str) -> list[dict]:
    return confident_pages_for_types(pages, [document_type])


def _find_pages_any_confidence(pages: list[dict], document_type: str) -> list[dict]:
    return [page for page in pages if page.get("document_type") == document_type]


def _document_types(value: str | list[str]) -> list[str]:
    return value if isinstance(value, list) else [value]


def _matching_pages(pages: list[dict], document_type: str | list[str]) -> list[dict]:
    return confident_pages_for_types(pages, _document_types(document_type))


def _field_from_pages(pages: list[dict], *field_names: str) -> tuple[object | None, dict | None]:
    for page in pages:
        fields = page.get("extracted_fields") or {}
        for field_name in field_names:
            if fields.get(field_name) not in (None, ""):
                return fields[field_name], page
    return None, None


def _normalized_status(value: object) -> str:
    return re.sub(r"[^a-z]+", " ", str(value or "").lower()).strip()


def _page_status(page: dict, field_names: list[str]) -> str:
    fields = page.get("extracted_fields") or {}
    for field_name in field_names:
        if fields.get(field_name) not in (None, ""):
            return _normalized_status(fields[field_name])
    return _normalized_status(page.get("ocr_text"))


def _is_positive_status(page: dict, accepted: list[str], rejected: list[str], fields: list[str]) -> bool:
    status = _page_status(page, fields)
    if any(term.lower() in status for term in rejected):
        return False
    return any(term.lower() in status for term in accepted)


def _distinct_document_key(page: dict) -> str:
    return str(
        page.get("source_document_id")
        or page.get("document_instance_id")
        or page.get("report_id")
        or f"page:{page.get('page_number')}"
    )


def _run_accuracy_checks(
    pages: list[dict],
    ground_truth: dict,
    system_data: dict,
    items: list[dict],
) -> list[dict]:
    anomalies: list[dict] = []

    for item in items:
        check_type = item["check_type"]
        s_no = item.get("s_no")
        description = item.get("description", "")
        document_type = item.get("document_type")

        applies = condition_applies(item.get("applies_when"), system_data)
        if applies is not True:
            continue

        if check_type == "presence_and_match":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                emitted_fields: set[str] = set()
                for page in doc_pages:
                    expected_data = system_data
                    person_id = str(page.get("person_id") or page.get("applicant_role") or "")
                    people = _people(system_data)
                    if person_id and person_id in people:
                        expected_data = people[person_id]
                    mismatches = check_field_match(
                        page.get("extracted_fields", {}), expected_data, [item["match_field"]]
                    )
                    for mismatch in mismatches:
                        field_key = f"{person_id}:{mismatch['field']}"
                        if field_key in emitted_fields:
                            continue
                        emitted_fields.add(field_key)
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"FIELD_MISMATCH_S{s_no}",
                                s_no=s_no,
                                severity=item.get("severity_if_mismatch", "HIGH"),
                                expected_value=str(mismatch["expected"]),
                                found_value=str(mismatch["found"]),
                                reason=f"{document_type} field mismatch: {mismatch['field']}",
                                page_number=page.get("page_number"),
                                document_type=" / ".join(_document_types(document_type)),
                                person_id=person_id or None,
                            )
                        )

        elif check_type == "field_match":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                emitted_fields: set[str] = set()
                for page in doc_pages:
                    mismatches = check_field_match(
                        page.get("extracted_fields", {}), system_data, item.get("match_fields", [])
                    )
                    for mismatch in mismatches:
                        field_name = str(mismatch["field"])
                        if field_name in emitted_fields:
                            continue
                        emitted_fields.add(field_name)
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"FIELD_MISMATCH_S{s_no}",
                                s_no=s_no,
                                severity=item.get("severity_if_mismatch", "HIGH"),
                                expected_value=str(mismatch["expected"]),
                                found_value=str(mismatch["found"]),
                                reason=f"Loan document field mismatch: {mismatch['field']}",
                                page_number=page.get("page_number"),
                                document_type=str(page.get("document_type") or document_type),
                            )
                        )

        elif check_type == "date_range":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                result = check_date_range(doc_pages[0].get("extracted_fields", {}), item["min_months"])
                if not result["passed"]:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_fail", "MEDIUM"),
                            expected_value=result.get("expected_value", ""),
                            found_value=result.get("found_value", ""),
                            reason=result.get("reason", description),
                            page_number=doc_pages[0].get("page_number"),
                            document_type=document_type,
                        )
                    )

        elif check_type == "period_minimum_months":
            doc_pages = _matching_pages(pages, document_type)
            minimum = float(item.get("min_months") or 0)
            for page in doc_pages:
                fields = page.get("extracted_fields") or {}
                start = fields.get(item.get("start_field", "statement_period_start"))
                end = fields.get(item.get("end_field", "statement_period_end"))
                if start in (None, "") or end in (None, ""):
                    continue
                try:
                    covered_months = (_parse_date(end) - _parse_date(start)).days / 30
                except Exception:
                    covered_months = -1
                if covered_months < minimum:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"PERIOD_CHECK_S{s_no}", s_no=s_no,
                            severity=item.get("severity_if_fail", "MEDIUM"),
                            expected_value=f"At least {minimum:g} months of account history",
                            found_value=f"{max(0, covered_months):.1f} months",
                            reason=description, page_number=page.get("page_number"),
                            document_type=str(page.get("document_type") or document_type),
                            person_id=page.get("person_id"),
                        )
                    )

        elif check_type == "document_age_max_months":
            doc_pages = _matching_pages(pages, document_type)
            maximum = float(item.get("max_months") or 0)
            for page in doc_pages:
                fields = page.get("extracted_fields") or {}
                date_value = next(
                    (
                        fields.get(field_name)
                        for field_name in item.get("document_fields", [])
                        if fields.get(field_name) not in (None, "")
                    ),
                    None,
                )
                if date_value in (None, ""):
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"FIELD_VALUE_MISSING_S{s_no}", s_no=s_no,
                            severity="LOW", expected_value="Utility-bill date available",
                            found_value="Date not extracted", reason=description,
                            page_number=page.get("page_number"), document_type=str(page.get("document_type")),
                        )
                    )
                    continue
                try:
                    age_months = (datetime.now() - _parse_date(date_value)).days / 30
                except Exception:
                    age_months = maximum + 1
                if age_months > maximum:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}", s_no=s_no,
                            severity=item.get("severity_if_fail", "HIGH"),
                            expected_value=f"Not older than {maximum:g} months",
                            found_value=f"{max(0, age_months):.1f} months old",
                            reason=description, page_number=page.get("page_number"),
                            document_type=str(page.get("document_type")),
                        )
                    )

        elif check_type == "date_not_after":
            doc_pages = _matching_pages(pages, document_type)
            found_value, found_page = _field_from_pages(doc_pages, *item.get("document_fields", []))
            expected_value = system_data.get(item.get("system_field"))
            if found_value not in (None, "") and expected_value not in (None, ""):
                try:
                    passed = _parse_date(found_value).date() <= _parse_date(expected_value).date()
                except Exception:
                    passed = False
                if not passed:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}", s_no=s_no,
                            severity=item.get("severity_if_fail", "HIGH"),
                            expected_value=f"On or before {expected_value}", found_value=found_value,
                            reason=description, page_number=(found_page or {}).get("page_number"),
                            document_type=" / ".join(_document_types(document_type)),
                        )
                    )

        elif check_type == "field_less_than":
            doc_pages = _matching_pages(pages, document_type)
            found_value, found_page = _field_from_pages(doc_pages, *item.get("document_fields", []))
            expected_value = system_data.get(item.get("system_field"))
            found_number, expected_number = _numeric(found_value), _numeric(expected_value)
            if found_number is not None and expected_number is not None and found_number >= expected_number:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"FIELD_RELATION_S{s_no}", s_no=s_no,
                        severity=item.get("severity_if_fail", "MEDIUM"),
                        expected_value=f"Less than {expected_value}", found_value=found_value,
                        reason=description, page_number=(found_page or {}).get("page_number"),
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )

        elif check_type == "required_status":
            doc_pages = _matching_pages(pages, document_type)
            accepted = item.get("accepted_statuses") or ["clear", "cleared", "positive", "approved", "registered"]
            rejected = item.get("rejected_statuses") or ["not clear", "not cleared", "negative", "rejected", "pending"]
            failing_pages = [
                page for page in doc_pages
                if not _is_positive_status(page, accepted, rejected, item.get("status_fields") or ["status"])
            ]
            if failing_pages:
                first = failing_pages[0]
                page_preview = ", ".join(
                    str(page.get("page_number")) for page in failing_pages[:6] if page.get("page_number") is not None
                )
                if len(failing_pages) > 6:
                    page_preview += f", … (+{len(failing_pages) - 6} more)"
                anomalies.append(
                    build_anomaly(
                        rule_id=f"STATUS_CHECK_S{s_no}", s_no=s_no,
                        severity=item.get("severity_if_fail", "HIGH"),
                        expected_value=" / ".join(accepted),
                        found_value=(
                            f"{_page_status(first, item.get('status_fields') or ['status'])[:120] or 'Status not found'}"
                            + (f" across {len(failing_pages)} page(s): {page_preview}" if len(failing_pages) > 1 else "")
                        ),
                        reason=description, page_number=first.get("page_number"),
                        document_type=str(first.get("document_type") or document_type),
                    )
                )

        elif check_type == "distinct_positive_count":
            doc_pages = _matching_pages(pages, document_type)
            positive_pages = [
                page for page in doc_pages
                if _is_positive_status(
                    page,
                    item.get("accepted_statuses") or ["positive", "clear", "cleared", "approved"],
                    item.get("rejected_statuses") or ["negative", "rejected", "not clear", "not cleared"],
                    item.get("status_fields") or ["status", "report_status"],
                )
            ]
            distinct_count = len({_distinct_document_key(page) for page in positive_pages})
            minimum = int(item.get("min_count") or 1)
            if distinct_count < minimum:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"COUNT_STATUS_CHECK_S{s_no}", s_no=s_no,
                        severity=item.get("severity_if_fail", "HIGH"),
                        expected_value=f"At least {minimum} distinct positive report(s)",
                        found_value=f"{distinct_count} distinct positive report(s)",
                        reason=description, document_type=" / ".join(_document_types(document_type)),
                    )
                )

    return anomalies



def run_checks(
    pages: list[dict],
    ground_truth: dict,
    system_data: dict | None,
    product_type: str,
) -> list[dict]:
    system_data = system_data or ground_truth or {}
    checklist_items = checklist_service.get_all_checklist_items(product_type)
    relevance_anomaly = _non_loan_relevance_anomaly(pages, checklist_items)
    if relevance_anomaly is not None:
        return [relevance_anomaly]
    anomalies = _run_presence_checks(pages, checklist_items, system_data)

    if _accuracy_checks_enabled():
        accuracy_items = checklist_service.get_accuracy_check_items(product_type)
        anomalies.extend(_run_accuracy_checks(pages, ground_truth, system_data, accuracy_items))

    anomalies.extend(_run_quality_checks(pages, ground_truth))
    return anomalies


def _non_loan_relevance_anomaly(
    pages: list[dict],
    presence_items: list[dict],
) -> dict | None:
    """Return one anomaly when uploaded file appears unrelated to loan processing.

    We only short-circuit when:
    - there are pages, and
    - no required checklist document type is detected anywhere, and
    - almost all pages are unclassified/unknown.
    """
    if not pages:
        return None

    expected_types: set[str] = set()
    for item in presence_items:
        document_type = item.get("document_type")
        if isinstance(document_type, str) and document_type:
            expected_types.add(document_type)
        elif isinstance(document_type, list):
            expected_types.update(str(value) for value in document_type if value)

    if not expected_types:
        return None

    doc_types = [str(page.get("document_type") or "").strip() for page in pages]
    matched_expected = sum(
        1
        for page in pages
        for expected_type in expected_types
        if is_confident_document_match(page, expected_type)
    )
    unknown_count = sum(1 for item in doc_types if item in {"", "Unknown", "None"})
    unknown_ratio = unknown_count / max(1, len(doc_types))

    config = effective_config()
    min_expected_matches = config.min_checklist_matches_for_loan_file
    max_unknown_ratio = config.max_unknown_ratio_for_unsupported_file

    # Keep valid loan files unaffected: only block weak, mostly-unclassified uploads.
    if matched_expected >= min_expected_matches or unknown_ratio < max_unknown_ratio:
        return None

    return build_anomaly(
        rule_id="UNSUPPORTED_DOCUMENT_TYPE",
        s_no=None,
        severity="HIGH",
        expected_value="Loan-file documents matching checklist",
        found_value=(
            f"Only {matched_expected} confident checklist document match(es) "
            f"across {len(pages)} pages"
        ),
        reason="Uploaded PDF appears unrelated to the loan checklist workflow.",
        page_number=1,
        document_type="Unsupported",
    )


def _run_quality_checks(pages: list[dict], ground_truth: dict) -> list[dict]:
    anomalies: list[dict] = []
    pan_pages = _find_pages_any_confidence(pages, "PAN")
    ocr_threshold = float(effective_config().min_scanned_ocr_confidence)
    image_heavy_types = {
        "property image",
        "gps",
        "photo",
        "screenshot",
        "ocr skipped",
    }

    for page in pages:
        if is_ocr_skipped_page(page):
            continue

        page_number = page.get("page_number")
        document_type = page.get("document_type")
        doc_type_key = str(document_type or "").strip().lower()
        if doc_type_key in image_heavy_types:
            continue

        if page.get("is_readable") is False:
            anomalies.append(
                build_anomaly(
                    "UNREADABLE_PAGE",
                    None,
                    "MEDIUM",
                    "Clear scan",
                    "Blurry or unreadable",
                    "Page scan quality too low for OCR",
                    page_number,
                    document_type,
                )
            )

        confidence = page.get("ocr_confidence", page.get("confidence"))
        if page.get("page_type") == "scanned" and confidence is not None and confidence < ocr_threshold:
            anomalies.append(
                build_anomaly(
                    "LOW_OCR_CONFIDENCE",
                    None,
                    "LOW",
                    f"Confidence above {ocr_threshold:.0%}",
                    f"{confidence:.0%} confidence",
                    "OCR confidence below acceptable threshold",
                    page_number,
                    document_type,
                )
            )

        if document_type in (None, "Unknown"):
            anomalies.append(
                build_anomaly(
                    "UNCLASSIFIED_PAGE",
                    None,
                    "LOW",
                    "Known document type",
                    "Unknown",
                    "Page could not be classified",
                    page_number,
                    document_type,
                )
            )

    if pan_pages:
        pan_fields = pan_pages[0].get("extracted_fields", {})
        pan_number = pan_fields.get("pan_number")
        if pan_number and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]{1}", str(pan_number).upper()):
            anomalies.append(
                build_anomaly(
                    "INVALID_PAN_FORMAT",
                    None,
                    "HIGH",
                    "Valid PAN format",
                    pan_number,
                    "PAN number format is invalid",
                    pan_pages[0].get("page_number"),
                    "PAN",
                )
            )

        ground_pan = ground_truth.get("pan_number")
        if ground_pan and pan_number and str(ground_pan).upper() != str(pan_number).upper():
            anomalies.append(
                build_anomaly(
                    "PAN_NUMBER_MISMATCH",
                    None,
                    "HIGH",
                    ground_pan,
                    pan_number,
                    "PAN number differs from digital application form",
                    pan_pages[0].get("page_number"),
                    "PAN",
                )
            )

        ground_name = ground_truth.get("applicant_name")
        pan_name = pan_fields.get("applicant_name")
        if ground_name and pan_name:
            score = fuzz.ratio(str(ground_name).strip().lower(), str(pan_name).strip().lower())
            if 75 <= score < 90:
                anomalies.append(
                    build_anomaly(
                        "BORDERLINE_NAME_MATCH",
                        None,
                        "MEDIUM",
                        ground_name,
                        pan_name,
                        f"Name match score {score}%, review needed",
                        pan_pages[0].get("page_number"),
                        "PAN",
                    )
                )
            elif score < 75:
                anomalies.append(
                    build_anomaly(
                        "NAME_MISMATCH",
                        None,
                        "HIGH",
                        ground_name,
                        pan_name,
                        f"Name match score {score}%, likely mismatch",
                        pan_pages[0].get("page_number"),
                        "PAN",
                    )
                )

    for bank_page in _find_pages(pages, "Bank Statement"):
        result = check_date_range(bank_page.get("extracted_fields", {}), 6)
        if not result["passed"] and result.get("found_value"):
            anomalies.append(
                build_anomaly(
                    "STATEMENT_TOO_OLD",
                    None,
                    "MEDIUM",
                    result.get("expected_value", "Recent statement"),
                    result.get("found_value", ""),
                    "Bank statement is older than allowed recency window",
                    bank_page.get("page_number"),
                    "Bank Statement",
                )
            )

    return anomalies


def evaluate_checklist(checklist: dict, extracted_documents: dict) -> list[dict]:
    required_docs = checklist.get("required_documents", [])
    found_docs = set(extracted_documents.keys())
    return [
        {"document": doc_name, "issue": "missing"}
        for doc_name in required_docs
        if doc_name not in found_docs
    ]
