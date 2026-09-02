"""Checklist engine submodule."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from services.checklist._dates import (
    _application_date,
    _completed_month_window,
    _date_value,
)
from services.checklist.anomaly_builder import build_anomaly


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
