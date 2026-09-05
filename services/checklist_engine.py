"""Checklist matching logic."""

import logging
import os
import re
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from math import ceil
from typing import Any

from dateutil.relativedelta import relativedelta

from services import checklist_service
from services.config import effective_config
from services.consistency_checks import run_consistency_checks
from services.page_quality import confident_pages_for_types, is_confident_document_match
from services.person_names import is_person_name_candidate
from services.processing_policy import is_ocr_skipped_page

LOGGER = logging.getLogger(__name__)

# ws-f accuracy: all name comparison routes through field_verification.verify_name
# (single threshold in services.person_names). Generic text similarity uses the
# local difflib helper below — never rapidfuzz directly in this module.


def _text_ratio(left: str, right: str) -> int:
    """Return 0-100 text similarity (SequenceMatcher; rapidfuzz-free)."""
    left_text, right_text = str(left or ""), str(right or "")
    if not left_text or not right_text:
        return 0
    return int(SequenceMatcher(None, left_text, right_text).ratio() * 100)


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


def check_field_match(
    extracted_fields: dict, system_data: dict, field_names: list[str]
) -> list[dict]:
    anomalies = []

    for field in field_names:
        system_val = system_data.get(field)
        extracted_val = extracted_fields.get(field)
        if system_val in (None, "") or extracted_val in (None, ""):
            continue
        if field in {"applicant_name", "borrower_name", "account_holder_name", "name"} and (
            not is_person_name_candidate(system_val) or not is_person_name_candidate(extracted_val)
        ):
            continue

        if field in ["loan_amount", "emi", "tenure", "roi", "interest_rate"]:
            try:
                sys_num = float(str(system_val).replace(",", ""))
                ext_num = float(str(extracted_val).replace(",", ""))
                tolerance = sys_num * 0.01
                if abs(sys_num - ext_num) > tolerance:
                    anomalies.append(
                        {"field": field, "expected": system_val, "found": extracted_val}
                    )
            except Exception:
                continue
        elif field == "pan_number":
            if str(system_val).upper() != str(extracted_val).upper():
                anomalies.append({"field": field, "expected": system_val, "found": extracted_val})
        else:
            if field in {"applicant_name", "borrower_name", "account_holder_name", "name"}:
                from services.field_verification import verify_name

                if not verify_name(str(system_val), str(extracted_val)).match:
                    anomalies.append(
                        {
                            "field": field,
                            "expected": system_val,
                            "found": extracted_val,
                        }
                    )
                continue
            score = _text_ratio(str(system_val).lower(), str(extracted_val).lower())
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


def calendar_months_between(earlier: date | datetime, later: date | datetime) -> int:
    """Whole calendar months from `earlier` to `later` (hand-rolled, no dep)."""
    if isinstance(earlier, datetime):
        earlier = earlier.date()
    if isinstance(later, datetime):
        later = later.date()
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(0, months)


def application_reference_date(*contexts: dict | None) -> date:
    """Application reference date for age/recency maths (never wall clock).

    Reads `applications.created_at` / manifest / system-data date keys; falls
    back to today only when no reference is available at all.
    """
    for context in contexts:
        if not isinstance(context, dict):
            continue
        manifest = context.get("manifest")
        sources = [context] + ([manifest] if isinstance(manifest, dict) else [])
        for source in sources:
            for key in (
                "reference_date",
                "created_at",
                "application_date",
                "application_opened_at",
                "application_open_date",
                "case_opened_at",
                "case_open_date",
                "case_login_date",
                "login_date",
            ):
                value = source.get(key)
                if value in (None, ""):
                    continue
                try:
                    parsed = _parse_date(value)
                except Exception:
                    continue
                return parsed.date() if isinstance(parsed, datetime) else parsed
    return datetime.now(UTC).date()


_STATEMENT_DATE_FIELDS = (
    "statement_period_end",
    "statement_date",
    "period_end",
    "statement_end_date",
)


def latest_statement_date(pages: list[dict], fields: tuple[str, ...] = _STATEMENT_DATE_FIELDS):
    """Latest parsable statement date across ALL pages of a document."""
    latest = None
    for page in pages:
        extracted = page.get("extracted_fields") or {} if isinstance(page, dict) else {}
        for field in fields:
            value = extracted.get(field)
            if value in (None, ""):
                continue
            try:
                parsed = _parse_date(value)
            except Exception:
                continue
            parsed_date = parsed.date() if isinstance(parsed, datetime) else parsed
            if latest is None or parsed_date > latest:
                latest = parsed_date
    return latest


def is_bank_statement_old(
    latest: date | datetime | str | None,
    reference: date | datetime | str | None,
    max_months: int = 3,
) -> bool:
    """True when the latest statement date is older than `max_months`.

    Calendar months via ``relativedelta``; any leftover days round up, so a
    statement dated 2026-05-30 is old against reference 2026-09-04
    (3 months + 5 days) while 2026-06-15 (2 months + 20 days) is not.
    """
    if latest in (None, "") or reference in (None, ""):
        return False
    try:
        latest_date = _parse_date(latest)
        reference_date = _parse_date(reference)
    except Exception:
        return False
    if isinstance(latest_date, datetime):
        latest_date = latest_date.date()
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()
    if reference_date < latest_date:
        return False
    delta = relativedelta(reference_date, latest_date)
    months = delta.years * 12 + delta.months + (1 if delta.days > 0 else 0)
    return months > int(max_months)


def check_date_range(
    extracted_fields: dict,
    min_months: int,
    reference_date: date | datetime | str | None = None,
) -> dict:
    date_val = extracted_fields.get("statement_period_end")
    if not date_val:
        return {"passed": False, "reason": "Statement date not found"}

    try:
        parsed = _parse_date(date_val)
        parsed_date = parsed.date() if isinstance(parsed, datetime) else parsed
        reference = (
            _parse_date(reference_date).date()
            if reference_date not in (None, "")
            else application_reference_date(extracted_fields)
        )
        if isinstance(reference, datetime):
            reference = reference.date()
        months_old = calendar_months_between(parsed_date, reference)
        if months_old > min_months:
            return {
                "passed": False,
                "found_value": f"{int(months_old)} months old",
                "expected_value": f"Within {min_months} months",
            }
        return {"passed": True}
    except Exception:
        return {"passed": False, "reason": "Could not parse statement date"}


def check_date_range_for_pages(
    doc_pages: list[dict],
    min_months: int,
    reference_date: date | datetime | str | None = None,
) -> dict:
    """Statement recency over the latest date found on ANY page of the document."""
    latest = latest_statement_date(doc_pages)
    if latest is None:
        return {"passed": False, "reason": "Statement date not found"}
    try:
        reference = (
            _parse_date(reference_date).date()
            if reference_date not in (None, "")
            else datetime.now(UTC).date()
        )
        if isinstance(reference, datetime):
            reference = reference.date()
        months_old = calendar_months_between(latest, reference)
        if months_old > min_months:
            return {
                "passed": False,
                "found_value": f"{int(months_old)} months old",
                "expected_value": f"Within {min_months} months",
            }
        return {"passed": True}
    except Exception:
        return {"passed": False, "reason": "Could not parse statement date"}


_APPLICATION_DATE_FIELDS = (
    "application_date",
    "application_opened_at",
    "application_open_date",
    "case_opened_at",
    "case_open_date",
    "case_login_date",
    "login_date",
)


def _date_value(value: object) -> date:
    raw = str(value).strip()
    if re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", raw):
        normalized = re.sub(r"[.-]", "/", raw)
        for date_format in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(normalized, date_format).date()
            except ValueError:
                continue
    return _parse_date(value).date()


def _application_date(system_data: dict, item: dict) -> tuple[date | None, str | None]:
    fields = item.get("anchor_fields") or _APPLICATION_DATE_FIELDS
    for field_name in fields:
        value = system_data.get(field_name)
        if value in (None, ""):
            continue
        try:
            return _date_value(value), str(field_name)
        except Exception:
            return None, str(field_name)
    return None, None


def _completed_month_window(anchor: date, minimum_months: float) -> tuple[date, date]:
    """Return the complete calendar months immediately before *anchor*."""
    months = max(1, ceil(minimum_months))
    required_end = anchor.replace(day=1) - timedelta(days=1)
    month_index = required_end.year * 12 + required_end.month - 1 - (months - 1)
    required_start = date(month_index // 12, month_index % 12 + 1, 1)
    return required_start, required_end


def _statement_account_key(page: dict, known_accounts: set[str]) -> tuple[str, str]:
    fields = page.get("extracted_fields") or {}
    account_number = re.sub(r"\D", "", str(fields.get("account_number") or ""))
    if account_number:
        return "account", account_number

    if len(known_accounts) == 1:
        return "account", next(iter(known_accounts))

    instance_id = str(
        page.get("source_document_id") or page.get("document_instance_id") or ""
    ).strip()
    if instance_id:
        return "document", instance_id
    person_id = str(page.get("person_id") or page.get("applicant_role") or "unassigned")
    return "unknown", person_id


def _statement_date_evidence(
    page: dict,
) -> tuple[list[tuple[date, date]], set[tuple[int, int]], bool]:
    """Return explicit ranges, transaction months, and whether date evidence was invalid."""
    fields = page.get("extracted_fields") or {}
    metadata = fields.get("_statement_date_evidence")
    metadata = metadata if isinstance(metadata, dict) else {}
    source = str(metadata.get("source") or "statement_period")
    ranges: list[tuple[date, date]] = []
    transaction_months: set[tuple[int, int]] = set()
    invalid = False

    for value in metadata.get("transaction_dates") or []:
        try:
            parsed = _date_value(value)
        except Exception:
            invalid = True
            continue
        transaction_months.add((parsed.year, parsed.month))

    start_value = fields.get("statement_period_start")
    end_value = fields.get("statement_period_end")
    if start_value in (None, "") and end_value in (None, ""):
        return ranges, transaction_months, invalid
    if start_value in (None, "") or end_value in (None, ""):
        return ranges, transaction_months, True
    try:
        start, end = _date_value(start_value), _date_value(end_value)
    except Exception:
        return ranges, transaction_months, True
    if end < start:
        return ranges, transaction_months, True
    if source == "transaction_dates":
        transaction_months.update({(start.year, start.month), (end.year, end.month)})
    else:
        ranges.append((start, end))
    return ranges, transaction_months, invalid


def _ranges_cover_window(
    ranges: list[tuple[date, date]],
    required_start: date,
    required_end: date,
) -> bool:
    if not ranges:
        return False
    merged: list[list[date]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return any(start <= required_start and end >= required_end for start, end in merged)


def _required_months(required_start: date, required_end: date) -> set[tuple[int, int]]:
    months: set[tuple[int, int]] = set()
    cursor = required_start
    while cursor <= required_end:
        months.add((cursor.year, cursor.month))
        month_index = cursor.year * 12 + cursor.month
        cursor = date(month_index // 12, month_index % 12 + 1, 1)
    return months


def _month_label(month: tuple[int, int]) -> str:
    return date(month[0], month[1], 1).strftime("%B %Y")


def bank_statement_required_month_labels(
    system_data: dict,
    minimum_months: float = 3,
) -> list[str]:
    """Return reviewer-facing labels for complete months before application."""
    anchor, _ = _application_date(system_data, {})
    if anchor is None:
        return []
    required_start, required_end = _completed_month_window(anchor, minimum_months)
    return [_month_label(month) for month in sorted(_required_months(required_start, required_end))]


def _bank_period_anomaly(
    *,
    pages: list[dict],
    item: dict,
    system_data: dict,
) -> dict | None:
    minimum = float(item.get("min_months") or 0)
    anchor, anchor_field = _application_date(system_data, item)
    expected_label = f"{minimum:g} complete months immediately before the application date"
    first_page = pages[0] if pages else {}
    if anchor is None:
        found = f"Invalid {anchor_field}" if anchor_field else "Application date not available"
        return build_anomaly(
            rule_id=f"PERIOD_DATE_UNVERIFIABLE_S{item.get('s_no')}",
            s_no=item.get("s_no"),
            severity=item.get("severity_if_fail", "MEDIUM"),
            expected_value=expected_label,
            found_value=found,
            reason="Bank-statement recency cannot be verified without a valid company application date.",
            page_number=first_page.get("page_number"),
            document_type=str(first_page.get("document_type") or item.get("document_type")),
        )

    required_start, required_end = _completed_month_window(anchor, minimum)
    required_months = _required_months(required_start, required_end)
    ordered_required_months = sorted(required_months)
    expected_value = "Required months: " + ", ".join(
        _month_label(month) for month in ordered_required_months
    )
    known_accounts: set[str] = set()
    for page in pages:
        fields = page.get("extracted_fields") or {}
        account_number = re.sub(r"\D", "", str(fields.get("account_number") or ""))
        if account_number:
            known_accounts.add(account_number)

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    invalid_evidence = False
    for page in pages:
        key = _statement_account_key(page, known_accounts)
        group = groups.setdefault(
            key,
            {"ranges": [], "transaction_months": set()},
        )
        ranges, transaction_months, invalid = _statement_date_evidence(page)
        group["ranges"].extend(ranges)
        group["transaction_months"].update(transaction_months)
        invalid_evidence = invalid_evidence or invalid

    covered_by_group: list[set[tuple[int, int]]] = []
    for group in groups.values():
        ranges = group["ranges"]
        covered_months = required_months.intersection(group["transaction_months"])
        for year, month in ordered_required_months:
            month_start = date(year, month, 1)
            next_month_index = year * 12 + month
            month_end = date(
                next_month_index // 12,
                next_month_index % 12 + 1,
                1,
            ) - timedelta(days=1)
            if _ranges_cover_window(ranges, month_start, month_end):
                covered_months.add((year, month))
        covered_by_group.append(covered_months)
        if required_months.issubset(covered_months):
            return None

    best_covered = max(covered_by_group, key=len, default=set())
    missing_months = required_months - best_covered
    if best_covered:
        found_value = (
            "Covered months: "
            + ", ".join(_month_label(month) for month in sorted(best_covered))
            + "; missing months: "
            + ", ".join(_month_label(month) for month in sorted(missing_months))
        )
    else:
        found_value = "No required-month coverage found; missing months: " + ", ".join(
            _month_label(month) for month in ordered_required_months
        )

    has_date_evidence = any(
        group["ranges"] or group["transaction_months"] for group in groups.values()
    )
    rule_prefix = (
        "PERIOD_DATE_UNVERIFIABLE" if invalid_evidence or not has_date_evidence else "PERIOD_CHECK"
    )
    reason = (
        "Bank-statement dates could not be verified; manual review is required."
        if rule_prefix == "PERIOD_DATE_UNVERIFIABLE" or invalid_evidence
        else item.get("description", "")
    )
    return build_anomaly(
        rule_id=f"{rule_prefix}_S{item.get('s_no')}",
        s_no=item.get("s_no"),
        severity=item.get("severity_if_fail", "MEDIUM"),
        expected_value=expected_value,
        found_value=found_value,
        reason=reason,
        page_number=first_page.get("page_number"),
        document_type=str(first_page.get("document_type") or item.get("document_type")),
        person_id=first_page.get("person_id"),
    )


def check_presence_min_count(pages: list[dict], document_type: str, min_count: int) -> dict:
    found_pages = _find_pages(pages, document_type)
    found_count, unit = _document_evidence_count(found_pages, document_type)
    if found_count >= min_count:
        return {
            "passed": True,
            "found_value": f"{found_count} {unit}",
            "expected_value": f"At least {min_count}",
        }
    return {
        "passed": False,
        "found_value": f"{found_count} {unit}",
        "expected_value": f"At least {min_count} {unit} of {document_type}",
    }


def _document_evidence_count(pages: list[dict], document_type: str) -> tuple[int, str]:
    """Count physical evidence, not PDF pages, when a document exposes items."""
    if document_type == "PDC":
        cheque_numbers = {
            str(number)
            for page in pages
            for number in ((page.get("extracted_fields") or {}).get("cheque_numbers") or [])
            if number not in (None, "")
        }
        if cheque_numbers:
            return len(cheque_numbers), "cheque(s)"
    return len(pages), "page(s)"


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


def _pages_for_person(pages: list[dict], person_id: str) -> list[dict]:
    return [
        page
        for page in pages
        if str(page.get("person_id") or page.get("applicant_role") or "") == person_id
    ]


def _missing_presence_anomaly(
    item: dict, *, document_type: str, person_id: str | None = None
) -> dict:
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
        # Some manual checklist controls live in the source system or a CSO
        # workflow rather than in the uploaded PDF.  Keep them visible in the
        # 44-item checklist, but do not treat absent PDF evidence as proof that
        # the control failed.
        if item.get("automated_presence_check", True) is False:
            continue

        check_type = item["check_type"]
        s_no = item.get("s_no")
        description = item.get("description", "")
        severity = item.get("severity_if_missing", "MEDIUM")
        document_type = item.get("document_type")

        applies = condition_applies(item.get("applies_when"), system_data)
        if applies is None:
            document_label = " / ".join(
                str(value) for value in _document_types(document_type) if value
            )
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
                    missing_types = [
                        doc_type for doc_type in types if not _find_pages(person_pages, doc_type)
                    ]
                    for missing_type in missing_types:
                        anomalies.append(
                            _missing_presence_anomaly(
                                item, document_type=missing_type, person_id=person_id
                            )
                        )
                elif item.get("check_type") == "presence_min_count":
                    minimum = int(item.get("min_count") or 1)
                    found_count = sum(
                        _document_evidence_count(_find_pages(person_pages, doc_type), doc_type)[0]
                        for doc_type in types
                    )
                    if found_count < minimum:
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"MISSING_DOC_S{s_no}_{person_id}",
                                s_no=s_no,
                                severity=severity,
                                expected_value=f"At least {minimum} document(s) for {person_id}",
                                found_value=f"{found_count} found",
                                reason=description,
                                document_type=", ".join(types),
                                person_id=person_id,
                            )
                        )
                elif item.get("check_type") == "consistency_only":
                    continue
                elif not check_presence_any(person_pages, types)["passed"]:
                    anomalies.append(
                        _missing_presence_anomaly(
                            item, document_type=", ".join(types), person_id=person_id
                        )
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

        elif check_type == "consistency_only":
            if not _matching_pages(pages, document_type):
                anomalies.append(
                    _missing_presence_anomaly(
                        item,
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )
            continue

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
                requirement_applies = condition_applies(
                    requirement.get("applies_when"), system_data
                )
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
                        found_count = _document_evidence_count(
                            _find_pages(person_pages, required_type), required_type
                        )[0]
                        if found_count < minimum:
                            anomalies.append(
                                build_anomaly(
                                    rule_id=f"MISSING_DOC_S{s_no}_{person_id}",
                                    s_no=s_no,
                                    severity=requirement_item.get("severity_if_missing", severity),
                                    expected_value=(
                                        f"At least {minimum} {required_type} document(s) for {person_id}"
                                        if requirement_check_type == "presence_min_count"
                                        or minimum > 1
                                        else f"Document present for {person_id}"
                                    ),
                                    found_value=f"{found_count} found",
                                    reason=description,
                                    document_type=required_type,
                                    person_id=person_id,
                                )
                            )
                else:
                    found_count = _document_evidence_count(
                        _find_pages(pages, required_type), required_type
                    )[0]
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
    text = str(page.get("ocr_text") or "")
    if (
        page.get("document_type") == "OTC PDD Document"
        and re.search(
            r"\brequest\s+legal\s+(?:otc\s*/?\s*pdd|pdd\s*/?\s*otc)\s+approval\b",
            text,
            re.IGNORECASE,
        )
        and re.search(r"(?mi)^\s*ok\s*$", text)
    ):
        return "approved"
    return _normalized_status(text)


def _is_positive_status(
    page: dict, accepted: list[str], rejected: list[str], fields: list[str]
) -> bool:
    status = _page_status(page, fields)
    if any(term.lower() in status for term in rejected):
        return False
    return any(term.lower() in status for term in accepted)


def _has_explicit_status_field(page: dict, fields: list[str]) -> bool:
    extracted = page.get("extracted_fields") or {}
    return any(extracted.get(name) not in (None, "") for name in fields)


def _status_looks_like_full_page_fallback(page: dict, fields: list[str]) -> bool:
    """True when status was inferred from whole-page OCR rather than a status field."""
    if _has_explicit_status_field(page, fields):
        return False
    status = _page_status(page, fields)
    return len(status) > 80


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
                people = _people(system_data)
                multi_person = len(people) > 1
                for page in doc_pages:
                    person_id = str(page.get("person_id") or page.get("applicant_role") or "")
                    if person_id in {"", "unassigned", "unknown"}:
                        # Ownership unresolved — do not compare against primary dump.
                        continue
                    if multi_person and person_id not in people:
                        continue
                    expected_data = people[person_id] if person_id in people else system_data
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
                # Statement period end is the latest parsable date on ANY page
                # of the document, measured against the application reference
                # date (never the wall clock).
                result = check_date_range_for_pages(
                    doc_pages,
                    item["min_months"],
                    application_reference_date(system_data, item),
                )
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
            if doc_pages:
                anomaly = _bank_period_anomaly(
                    pages=doc_pages,
                    item=item,
                    system_data=system_data,
                )
                if anomaly is not None:
                    anomalies.append(anomaly)

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
                            rule_id=f"FIELD_VALUE_MISSING_S{s_no}",
                            s_no=s_no,
                            severity="LOW",
                            expected_value="Utility-bill date available",
                            found_value="Date not extracted",
                            reason=description,
                            page_number=page.get("page_number"),
                            document_type=str(page.get("document_type")),
                        )
                    )
                    continue
                try:
                    # Calendar months against the application reference date.
                    parsed_date = _parse_date(date_value)
                    if isinstance(parsed_date, datetime):
                        parsed_date = parsed_date.date()
                    age_months = calendar_months_between(
                        parsed_date, application_reference_date(system_data, item)
                    )
                except Exception:
                    age_months = maximum + 1
                if age_months > maximum:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_fail", "HIGH"),
                            expected_value=f"Not older than {maximum:g} months",
                            found_value=f"{max(0, age_months):.1f} months old",
                            reason=description,
                            page_number=page.get("page_number"),
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
                            rule_id=f"DATE_CHECK_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_fail", "HIGH"),
                            expected_value=f"On or before {expected_value}",
                            found_value=found_value,
                            reason=description,
                            page_number=(found_page or {}).get("page_number"),
                            document_type=" / ".join(_document_types(document_type)),
                        )
                    )

        elif check_type == "field_less_than":
            doc_pages = _matching_pages(pages, document_type)
            found_value, found_page = _field_from_pages(doc_pages, *item.get("document_fields", []))
            expected_value = system_data.get(item.get("system_field"))
            found_number, expected_number = _numeric(found_value), _numeric(expected_value)
            if (
                found_number is not None
                and expected_number is not None
                and found_number >= expected_number
            ):
                anomalies.append(
                    build_anomaly(
                        rule_id=f"FIELD_RELATION_S{s_no}",
                        s_no=s_no,
                        severity=item.get("severity_if_fail", "MEDIUM"),
                        expected_value=f"Less than {expected_value}",
                        found_value=found_value,
                        reason=description,
                        page_number=(found_page or {}).get("page_number"),
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )

        elif check_type == "required_status":
            doc_pages = _matching_pages(pages, document_type)
            accepted = item.get("accepted_statuses") or [
                "clear",
                "cleared",
                "positive",
                "approved",
                "registered",
            ]
            rejected = item.get("rejected_statuses") or [
                "not clear",
                "not cleared",
                "negative",
                "rejected",
                "pending",
            ]
            status_fields = item.get("status_fields") or ["status"]

            # Partition pages: those that pass vs those that fail the status check.
            passing_pages = [
                page
                for page in doc_pages
                if _is_positive_status(page, accepted, rejected, status_fields)
            ]
            # If ANY page in the document group has a passing status, treat the
            # whole document as cleared — no anomaly needed.
            if passing_pages:
                pass  # at least one page confirms clearance
            else:
                failing_pages = [page for page in doc_pages if page not in passing_pages]
                if failing_pages:
                    first = failing_pages[0]
                    # Check if the failing page relied on full OCR text (no dedicated
                    # status field found) AND has low OCR confidence.
                    first_has_status_field = _has_explicit_status_field(first, status_fields)
                    first_ocr_conf = float(first.get("ocr_confidence") or 1.0)
                    low_conf_fallback = not first_has_status_field and first_ocr_conf < 0.60
                    # Valuation/report cover pages rarely embed "cleared/approved" wording.
                    # Do not HIGH-fail just because whole-page OCR lacks those tokens.
                    unverifiable_fallback = (
                        not first_has_status_field
                        and all(
                            _status_looks_like_full_page_fallback(page, status_fields)
                            for page in failing_pages
                        )
                        and not any(
                            term.lower() in _page_status(page, status_fields)
                            for page in failing_pages
                            for term in rejected
                        )
                    )

                    page_preview = ", ".join(
                        str(page.get("page_number"))
                        for page in failing_pages[:6]
                        if page.get("page_number") is not None
                    )
                    if len(failing_pages) > 6:
                        page_preview += f", … (+{len(failing_pages) - 6} more)"

                    if low_conf_fallback or unverifiable_fallback:
                        # Cannot verify status reliably — emit a softer warning instead
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"STATUS_UNVERIFIABLE_S{s_no}",
                                s_no=s_no,
                                severity="LOW",
                                expected_value=" / ".join(accepted),
                                found_value=(
                                    (
                                        f"OCR confidence {first_ocr_conf:.0%} — status field not extractable"
                                        if low_conf_fallback
                                        else "No explicit clearance status field on valuation/report pages"
                                    )
                                    + (
                                        f" across {len(failing_pages)} page(s): {page_preview}"
                                        if len(failing_pages) > 1
                                        else ""
                                    )
                                ),
                                reason=f"{description} (status not explicitly extractable; manual review)",
                                page_number=first.get("page_number"),
                                document_type=str(first.get("document_type") or document_type),
                            )
                        )
                    else:
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"STATUS_CHECK_S{s_no}",
                                s_no=s_no,
                                severity=item.get("severity_if_fail", "HIGH"),
                                expected_value=" / ".join(accepted),
                                found_value=(
                                    f"{_page_status(first, status_fields)[:120] or 'Status not found'}"
                                    + (
                                        f" across {len(failing_pages)} page(s): {page_preview}"
                                        if len(failing_pages) > 1
                                        else ""
                                    )
                                ),
                                reason=description,
                                page_number=first.get("page_number"),
                                document_type=str(first.get("document_type") or document_type),
                            )
                        )

        elif check_type == "distinct_positive_count":
            doc_pages = _matching_pages(pages, document_type)
            positive_pages = [
                page
                for page in doc_pages
                if _is_positive_status(
                    page,
                    item.get("accepted_statuses") or ["positive", "clear", "cleared", "approved"],
                    item.get("rejected_statuses")
                    or ["negative", "rejected", "not clear", "not cleared"],
                    item.get("status_fields") or ["status", "report_status"],
                )
            ]
            distinct_count = len({_distinct_document_key(page) for page in positive_pages})
            minimum = int(item.get("min_count") or 1)
            if distinct_count < minimum:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"COUNT_STATUS_CHECK_S{s_no}",
                        s_no=s_no,
                        severity=item.get("severity_if_fail", "HIGH"),
                        expected_value=f"At least {minimum} distinct positive report(s)",
                        found_value=f"{distinct_count} distinct positive report(s)",
                        reason=description,
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )

    return anomalies


def run_checks(
    pages: list[dict],
    ground_truth: dict,
    system_data: dict | None,
    product_type: str,
) -> list[dict]:
    from services.person_ownership import assign_page_owners, ownership_anomalies_for_unassigned

    system_data = {
        **(ground_truth or {}),
        **_document_derived_system_data(pages),
        **(system_data or {}),
    }
    if "people" not in system_data and isinstance(system_data.get("reference_data"), dict):
        system_data["people"] = system_data["reference_data"]
    # Resolve page owners before presence/accuracy/consistency so TRUSTED_*
    # never compares co-applicant OCR against primary by accident.
    assign_page_owners(pages, system_data)
    checklist_items = checklist_service.get_all_checklist_items(product_type)
    relevance_anomaly = _non_loan_relevance_anomaly(pages, checklist_items)
    if relevance_anomaly is not None:
        return [relevance_anomaly]
    anomalies = _run_presence_checks(pages, checklist_items, system_data)

    if _accuracy_checks_enabled():
        accuracy_items = checklist_service.get_accuracy_check_items(product_type)
        anomalies.extend(_run_accuracy_checks(pages, ground_truth, system_data, accuracy_items))

        anomalies.extend(run_consistency_checks(pages, system_data))

    anomalies.extend(_run_quality_checks(pages, ground_truth))
    anomalies.extend(ownership_anomalies_for_unassigned(pages))
    return anomalies


def _document_derived_system_data(pages: list[dict]) -> dict[str, object]:
    """Derive conditional checklist inputs from explicit document evidence."""
    for page in pages:
        fields = page.get("extracted_fields") or {}
        status = fields.get("nach_status")
        if status in (None, ""):
            continue
        normalized = _normalized_status(status)
        if any(term in normalized for term in ("not registered", "not done", "failed", "inactive")):
            return {"nach_registered": False}
        if any(term in normalized for term in ("done", "registered", "active", "approved")):
            return {"nach_registered": True}
    return {}


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
    primary_id = str(ground_truth.get("person_id") or "primary")
    pan_pages = [
        page
        for page in _find_pages_any_confidence(pages, "PAN")
        if str(page.get("person_id") or page.get("applicant_role") or "") == primary_id
    ]
    ocr_threshold = float(effective_config().min_scanned_ocr_confidence)
    image_heavy_types = {
        "property image",
        "gps",
        "photo",
        "screenshot",
        "ocr skipped",
        "house photo",
        "workplace photo",
        "kyc card photo",
        "ration card photo",
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
        if (
            page.get("page_type") == "scanned"
            and confidence is not None
            and confidence < ocr_threshold
        ):
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
            ocr_text = str(page.get("ocr_text") or "").strip()
            # Blank / nearly blank trailing pages are not actionable unclassified docs.
            if len(re.sub(r"\s+", "", ocr_text)) < 40:
                continue
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
            try:
                from services.person_ownership import name_matches_trusted_person

                primary_record = (
                    (ground_truth.get("people") or {}).get(primary_id)
                    or (ground_truth.get("reference_data") or {}).get(primary_id)
                    or ground_truth
                )
                if name_matches_trusted_person(pan_name, primary_record):
                    pan_name = None
            except Exception:
                pass
        if ground_name and pan_name:
            from services.field_verification import verify_name

            name_result = verify_name(str(ground_name), str(pan_name))
            score = int(round(name_result.confidence * 100))
            if 75 <= score < 90 and not name_result.match:
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

    return anomalies


def evaluate_checklist(checklist: dict, extracted_documents: dict) -> list[dict]:
    required_docs = checklist.get("required_documents", [])
    found_docs = set(extracted_documents.keys())
    return [
        {"document": doc_name, "issue": "missing"}
        for doc_name in required_docs
        if doc_name not in found_docs
    ]
