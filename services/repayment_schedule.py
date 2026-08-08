"""Deterministic extraction and validation for amortisation schedules.

The document classifier is deliberately not used as the primary gate here.
Schedule continuation pages are commonly labelled as bank statements or NACH
forms because they contain dense columns of balances and payments.  Six-column
row structure plus loan arithmetic is a much stronger signal.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from typing import Any


_NUMBER = r"(?:\d[\d,]*(?:\.\d{1,2})?)"
_ROW_PATTERN = re.compile(
    rf"(?<![\d.])(\d{{1,3}})\s+(?:Rs\.?\s*|INR\s*|₹\s*)?({_NUMBER})"
    rf"\s+(?:Rs\.?\s*|INR\s*|₹\s*)?({_NUMBER})"
    rf"\s+(?:Rs\.?\s*|INR\s*|₹\s*)?({_NUMBER})"
    rf"\s+(?:Rs\.?\s*|INR\s*|₹\s*)?({_NUMBER})"
    rf"\s+(?:Rs\.?\s*|INR\s*|₹\s*)?({_NUMBER})(?![\d.])",
    re.IGNORECASE,
)

_SUMMARY_LABELS: dict[str, tuple[str, ...]] = {
    "loan_amount": (
        "sanctioned loan amount",
        "amount of facility",
    ),
    "total_interest": (
        "total interest amount to be charged during the entire",
        "total interest charge during the entire",
    ),
    "net_disbursement": (
        "net disbursed amount",
        "net disbursement amount",
    ),
    "total_repayment": (
        "total amount to be paid by the borrower",
        "total borrower repayment",
        "total repayment",
    ),
}

# A blank value cell must not borrow a number from the next semantic row.  KFS
# OCR frequently loses table borders, leaving (for example) ``Amount of
# Facility`` followed immediately by ``Rate of Interest 21.00``.
_SUMMARY_BOUNDARY_LABELS = tuple(
    dict.fromkeys(
        label
        for labels in _SUMMARY_LABELS.values()
        for label in labels
    )
) + (
    "loan term",
    "rate of interest",
    "monthly instalment",
    "monthly installment",
    "fee/ charges payable",
    "fee / charges payable",
    "annual percentage rate",
)


def parse_repayment_schedule_rows(text: Any) -> list[dict[str, Any]]:
    """Return six-column repayment rows when the page is schedule-like.

    A page is accepted when it has an explicit repayment-table heading or at
    least two candidate rows of which most satisfy both EMI-component and
    balance arithmetic.  This prevents ordinary bank-statement rows from being
    treated as an amortisation schedule.
    """
    normalized = _normalized_text(text)
    if not normalized:
        return []

    candidates: list[dict[str, Any]] = []
    for match in _ROW_PATTERN.finditer(normalized):
        values = [_number(value) for value in match.groups()[1:]]
        if any(value is None for value in values):
            continue
        opening, emi, principal, interest, closing = (float(value) for value in values)
        installment = int(match.group(1))
        if not _plausible_row(installment, opening, emi, principal, interest, closing):
            continue
        component_difference = round(emi - principal - interest, 2)
        balance_difference = round(opening - principal - closing, 2)
        candidates.append(
            {
                "installment_number": installment,
                "opening_balance": opening,
                "emi": emi,
                "principal": principal,
                "interest": interest,
                "closing_balance": closing,
                "component_difference": component_difference,
                "balance_difference": balance_difference,
                "component_valid": abs(component_difference) <= _money_tolerance(emi),
                "balance_valid": abs(balance_difference) <= _money_tolerance(opening),
            }
        )

    if not candidates:
        return []
    lowered = normalized.casefold()
    explicit_header = bool(
        re.search(r"repayment\s+schedule|amorti[sz]ation\s+schedule", lowered)
        and "emi" in lowered
    )
    valid_count = sum(
        1 for row in candidates if row["component_valid"] and row["balance_valid"]
    )
    if not explicit_header and (
        len(candidates) < 2 or valid_count / max(1, len(candidates)) < 0.60
    ):
        return []
    return candidates


def extract_repayment_summary(text: Any) -> dict[str, Any]:
    """Extract KFS/APR illustration values relevant to schedule validation."""
    raw = "".join(
        _ascii_digit(character)
        for character in unicodedata.normalize("NFKC", str(text or ""))
    )
    if not raw.strip():
        return {}
    lowered = raw.casefold()
    if not any(
        marker in lowered
        for marker in (
            "illustration for computation of apr",
            "key facts statement",
            "sanctioned loan amount",
            "total amount to be paid by the borrower",
        )
    ):
        return {}

    summary: dict[str, Any] = {}
    monthly = re.search(
        rf"\bmonthly\s+(?:rs\.?\s*|inr\s*|₹\s*)?({_NUMBER})\s*(?:&|and)\s*(\d{{1,3}})\b",
        raw,
        re.IGNORECASE,
    )
    if monthly:
        summary["emi"] = _number(monthly.group(1))
        summary["installment_count"] = int(monthly.group(2))

    tenure = re.search(
        r"loan\s+term\s*\(\s*in\s+months\s*\)[\s\S]{0,260}?\b(\d{1,3})\b",
        raw,
        re.IGNORECASE,
    )
    if tenure:
        summary["tenure"] = int(tenure.group(1))

    roi = re.search(
        rf"\brate\s+of\s+interest\b[\s\S]{{0,300}}?({_NUMBER})\s*%?",
        raw,
        re.IGNORECASE,
    )
    if roi:
        summary["roi"] = _number(roi.group(1))

    for field, labels in _SUMMARY_LABELS.items():
        value = _amount_after_any_label(raw, labels)
        if value is not None:
            summary[field] = value
    return {key: value for key, value in summary.items() if value is not None}


def attach_repayment_fields(
    extracted_fields: dict[str, Any], text: Any
) -> dict[str, Any]:
    """Attach structured schedule rows and missing KFS summary values."""
    result = dict(extracted_fields or {})
    rows = parse_repayment_schedule_rows(text)
    if rows:
        result["repayment_schedule_rows"] = rows
    for field, value in extract_repayment_summary(text).items():
        if result.get(field) in (None, "", [], {}):
            result[field] = value
    return result


def validate_repayment_schedules(
    pages: list[dict[str, Any]], trusted: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Validate schedule rows, totals, and trusted loan terms.

    Findings are emitted once per distinct schedule.  Exact duplicates in a
    package are intentionally collapsed.
    """
    schedules = collect_repayment_schedules(pages)
    expected = _trusted_loan_values(trusted or {})
    anomalies: list[dict[str, Any]] = []
    for schedule in schedules:
        rows = schedule["rows"]
        if len(rows) < 2:
            continue
        first_page = schedule["pages"][0]
        document_type = schedule.get("document_type") or "Repayment Schedule"
        base = {
            "s_no": 12,
            "document_type": document_type,
            "page_number": first_page,
            "person_id": None,
        }

        bad_components = [
            row["installment_number"] for row in rows if not row["component_valid"]
        ]
        if bad_components:
            anomalies.append(
                _anomaly(
                    "REPAYMENT_SCHEDULE_EMI_COMPONENT_MISMATCH",
                    "HIGH",
                    "Every EMI equals principal plus interest",
                    _row_list(bad_components),
                    base,
                    "Repayment schedule contains EMI rows whose principal and interest do not add up to the EMI.",
                )
            )

        bad_balances = [
            row["installment_number"] for row in rows if not row["balance_valid"]
        ]
        if bad_balances:
            anomalies.append(
                _anomaly(
                    "REPAYMENT_SCHEDULE_BALANCE_MISMATCH",
                    "HIGH",
                    "Closing balance equals opening balance minus principal",
                    _row_list(bad_balances),
                    base,
                    "Repayment schedule contains rows with inconsistent opening, principal, and closing balances.",
                )
            )

        continuity_failures: list[str] = []
        sequence_failures: list[str] = []
        for previous, current in zip(rows, rows[1:]):
            if current["installment_number"] != previous["installment_number"] + 1:
                sequence_failures.append(
                    f"{previous['installment_number']}→{current['installment_number']}"
                )
            if abs(previous["closing_balance"] - current["opening_balance"]) > _money_tolerance(
                previous["closing_balance"]
            ):
                continuity_failures.append(
                    f"{previous['installment_number']}→{current['installment_number']}"
                )
        if sequence_failures:
            anomalies.append(
                _anomaly(
                    "REPAYMENT_SCHEDULE_SEQUENCE_MISMATCH",
                    "HIGH",
                    "Consecutive installment numbers",
                    ", ".join(sequence_failures[:8]),
                    base,
                    "Repayment schedule has a missing, duplicate, or out-of-order installment row.",
                )
            )
        if continuity_failures:
            anomalies.append(
                _anomaly(
                    "REPAYMENT_SCHEDULE_CONTINUITY_MISMATCH",
                    "HIGH",
                    "Each opening balance equals the prior closing balance",
                    ", ".join(continuity_failures[:8]),
                    base,
                    "Repayment schedule balances do not carry forward consistently between installments.",
                )
            )

        complete = _schedule_is_complete(rows, sequence_failures)
        amortizing_rows = [row for row in rows if row["principal"] > _money_tolerance(row["emi"])]
        recurring_rows = amortizing_rows[:-1] if len(amortizing_rows) > 1 else amortizing_rows
        recurring_emi = _modal_money([row["emi"] for row in recurring_rows])
        trusted_emi = _number(expected.get("emi"))
        if recurring_emi is not None and trusted_emi is not None and not _close_money(
            recurring_emi, trusted_emi, relative=0.005
        ):
            anomalies.append(
                _anomaly(
                    "REPAYMENT_SCHEDULE_EMI_MISMATCH",
                    "HIGH",
                    _money(trusted_emi),
                    _money(recurring_emi),
                    base,
                    "Recurring EMI in the repayment schedule does not match the trusted JSON/database dump.",
                )
            )

        expected_count = _integer(
            expected.get("installment_count") or expected.get("tenure")
        )
        if complete and expected_count is not None and len(amortizing_rows) != expected_count:
            anomalies.append(
                _anomaly(
                    "REPAYMENT_SCHEDULE_INSTALLMENT_COUNT_MISMATCH",
                    "HIGH",
                    f"{expected_count} principal-repaying installment(s)",
                    f"{len(amortizing_rows)} principal-repaying installment(s); {len(rows)} total row(s)",
                    base,
                    "Repayment schedule installment count does not match the trusted JSON tenure/installment count. Interest-only pre-EMI rows are excluded from this count.",
                )
            )

        if complete:
            schedule_total = round(sum(row["emi"] for row in rows), 2)
            trusted_total = _number(expected.get("total_repayment"))
            summary_total = _number((schedule.get("summary") or {}).get("total_repayment"))
            comparison_total = trusted_total if trusted_total is not None else summary_total
            comparison_source = (
                "trusted JSON/database dump" if trusted_total is not None else "KFS/facility summary"
            )
            if comparison_total is not None and not _close_money(
                schedule_total, comparison_total, relative=0.001
            ):
                anomalies.append(
                    _anomaly(
                        "REPAYMENT_SCHEDULE_TOTAL_MISMATCH",
                        "HIGH",
                        f"{_money(comparison_total)} ({comparison_source})",
                        f"{_money(schedule_total)} (sum of EMI column)",
                        base,
                        "Total of all repayment-schedule EMI rows does not match the stated total repayment.",
                    )
                )

            principal_total = round(sum(row["principal"] for row in rows), 2)
            trusted_principal = _number(
                expected.get("loan_amount") or expected.get("sanction_amount")
            )
            if trusted_principal is not None and not _close_money(
                principal_total, trusted_principal, relative=0.001
            ):
                anomalies.append(
                    _anomaly(
                        "REPAYMENT_SCHEDULE_PRINCIPAL_MISMATCH",
                        "HIGH",
                        _money(trusted_principal),
                        _money(principal_total),
                        base,
                        "Principal repaid across the complete schedule does not equal the trusted loan amount.",
                    )
                )

            summary = schedule.get("summary") or {}
            summary_principal = _number(summary.get("loan_amount"))
            summary_interest = _number(summary.get("total_interest"))
            summary_repayment = _number(summary.get("total_repayment"))
            if (
                summary_principal is not None
                and summary_interest is not None
                and summary_repayment is not None
                and not _close_money(
                    summary_principal + summary_interest,
                    summary_repayment,
                    relative=0.001,
                )
            ):
                anomalies.append(
                    _anomaly(
                        "REPAYMENT_SUMMARY_TOTAL_MISMATCH",
                        "HIGH",
                        f"Loan + interest = {_money(summary_principal + summary_interest)}",
                        f"Stated total repayment = {_money(summary_repayment)}",
                        base,
                        "KFS/facility repayment summary is internally inconsistent before comparing it with JSON.",
                    )
                )
    return anomalies


def collect_repayment_schedules(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect contiguous schedule pages and collapse identical document copies."""
    row_pages: list[dict[str, Any]] = []
    summaries: list[tuple[int, dict[str, Any]]] = []
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        page_number = int(page.get("page_number") or 0)
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            fields = {}
        rows = fields.get("repayment_schedule_rows")
        if not isinstance(rows, list) or not rows:
            rows = parse_repayment_schedule_rows(page.get("ocr_text"))
        rows = [row for row in rows if isinstance(row, dict)]
        summary = extract_repayment_summary(page.get("ocr_text"))
        if summary:
            summaries.append((page_number, summary))
        if rows:
            row_pages.append(
                {
                    "page_number": page_number,
                    "document_type": page.get("provided_document_type")
                    or page.get("document_type")
                    or "Repayment Schedule",
                    "rows": rows,
                }
            )

    groups: list[dict[str, Any]] = []
    for item in row_pages:
        if not groups or not _continues_schedule(groups[-1], item):
            groups.append(
                {
                    "pages": [item["page_number"]],
                    "document_type": item["document_type"],
                    "rows": list(item["rows"]),
                }
            )
            continue
        groups[-1]["pages"].append(item["page_number"])
        existing = {
            (row["installment_number"], row["opening_balance"], row["emi"])
            for row in groups[-1]["rows"]
        }
        groups[-1]["rows"].extend(
            row
            for row in item["rows"]
            if (row["installment_number"], row["opening_balance"], row["emi"])
            not in existing
        )

    unique: list[dict[str, Any]] = []
    fingerprints: set[tuple[Any, ...]] = set()
    for group in groups:
        group["rows"] = sorted(group["rows"], key=lambda row: row["installment_number"])
        closest = [
            (page_number, summary)
            for page_number, summary in summaries
            if group["pages"][0] - 5 <= page_number <= group["pages"][0]
        ]
        if closest:
            group["summary"] = max(closest, key=lambda item: item[0])[1]
        fingerprint = _schedule_fingerprint(group["rows"])
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        unique.append(group)
    return unique


def _continues_schedule(group: dict[str, Any], item: dict[str, Any]) -> bool:
    if item["page_number"] - group["pages"][-1] > 2:
        return False
    previous = group["rows"][-1]
    current = item["rows"][0]
    if current["installment_number"] == previous["installment_number"] + 1:
        return True
    return (
        current["installment_number"] == previous["installment_number"]
        and _close_money(current["opening_balance"], previous["opening_balance"])
    )


def _schedule_fingerprint(rows: list[dict[str, Any]]) -> tuple[Any, ...]:
    return (
        rows[0]["installment_number"],
        round(rows[0]["opening_balance"], 2),
        rows[-1]["installment_number"],
        round(rows[-1]["closing_balance"], 2),
        len(rows),
        round(sum(row["emi"] for row in rows), 2),
    )


def _schedule_is_complete(rows: list[dict[str, Any]], sequence_failures: list[str]) -> bool:
    if not rows or rows[0]["installment_number"] != 1 or sequence_failures:
        return False
    return abs(rows[-1]["closing_balance"]) <= _money_tolerance(rows[0]["opening_balance"])


def _trusted_loan_values(trusted: dict[str, Any]) -> dict[str, Any]:
    values = {
        key: value
        for key, value in trusted.items()
        if not isinstance(value, (dict, list)) and value not in (None, "")
    }
    people = trusted.get("people") or trusted.get("reference_data") or {}
    if isinstance(people, dict):
        primary = people.get("primary")
        if not isinstance(primary, dict):
            primary = next((item for item in people.values() if isinstance(item, dict)), {})
        for key, value in primary.items():
            if values.get(key) in (None, "") and value not in (None, ""):
                values[key] = value
    return values


def _amount_after_any_label(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        match = re.search(re.escape(label), text, re.IGNORECASE)
        if not match:
            continue
        body = text[match.end() : match.end() + 1100]
        boundaries = [
            boundary.start()
            for boundary in (
                re.search(r"(?:^|\n)\s*(?:[2-9]|1[0-2])\.\s", body),
                _next_summary_label(body),
            )
            if boundary is not None
        ]
        if boundaries:
            body = body[: min(boundaries)]
        values = [
            value
            for raw in re.findall(r"(?<![\w.])(?:Rs\.?\s*|INR\s*|₹\s*)?(\d[\d,]*\.\d{1,2})(?![\w.])", body, re.I)
            if (value := _number(raw)) is not None
        ]
        if values:
            # The first currency-style decimal after the English label is the
            # table value.  Using the last one can wander into schedule rows
            # when the table and amortisation schedule share a page.
            return values[0]
    return None


def _next_summary_label(text: str) -> re.Match[str] | None:
    alternatives = [
        r"\s+".join(re.escape(part) for part in label.split())
        for label in _SUMMARY_BOUNDARY_LABELS
    ]
    return re.search(rf"\b(?:{'|'.join(alternatives)})\b", text, re.IGNORECASE)


def _plausible_row(
    installment: int,
    opening: float,
    emi: float,
    principal: float,
    interest: float,
    closing: float,
) -> bool:
    if not 1 <= installment <= 600 or opening <= 0 or emi <= 0:
        return False
    if min(principal, interest, closing) < 0:
        return False
    if principal > opening * 1.05 + 10 or closing > opening * 1.05 + 10:
        return False
    if emi > opening * 1.25 + 10:
        return False
    return True


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(_ascii_digit(character) for character in text)
    text = text.replace("|", " ").replace("¦", " ")
    return re.sub(r"\s+", " ", text).strip()


def _ascii_digit(character: str) -> str:
    if not character.isdecimal() or "0" <= character <= "9":
        return character
    try:
        return str(unicodedata.digit(character))
    except (TypeError, ValueError):
        return character


def _number(value: Any) -> float | None:
    try:
        return float(re.sub(r"[^0-9.-]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(round(number))


def _money_tolerance(value: float) -> float:
    return max(1.0, abs(float(value)) * 0.0001)


def _close_money(left: float, right: float, *, relative: float = 0.0001) -> bool:
    return abs(left - right) <= max(1.0, abs(right) * relative)


def _modal_money(values: list[float]) -> float | None:
    if not values:
        return None
    rounded = [round(value, 2) for value in values]
    counts = Counter(rounded)
    most_common = counts.most_common()
    if most_common and most_common[0][1] > 1:
        return float(most_common[0][0])
    return float(statistics.median(rounded))


def _money(value: float) -> str:
    return f"INR {value:,.2f}"


def _row_list(values: list[int]) -> str:
    shown = ", ".join(str(value) for value in values[:12])
    return f"Rows {shown}" + (f" (+{len(values) - 12} more)" if len(values) > 12 else "")


def _anomaly(
    rule_id: str,
    severity: str,
    expected: Any,
    found: Any,
    base: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        **base,
        "severity": severity,
        "expected_value": expected,
        "found_value": found,
        "reason": reason,
    }
