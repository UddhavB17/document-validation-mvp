"""Date parsing helpers for checklist rules."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from math import ceil

_APPLICATION_DATE_FIELDS = (
    "application_date",
    "application_opened_at",
    "application_open_date",
    "case_opened_at",
    "case_open_date",
    "case_login_date",
    "login_date",
)


def _parse_date(value: object) -> datetime:
    try:
        from dateutil import parser

        return parser.parse(str(value))
    except Exception:
        return datetime.fromisoformat(str(value))


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
