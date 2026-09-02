"""Checklist anomaly and result types."""

from __future__ import annotations

from typing import Any, TypedDict


class ChecklistAnomaly(TypedDict, total=False):
    rule_id: str
    s_no: int | None
    severity: str
    document_type: str | None
    expected_value: Any
    found_value: Any
    page_number: int | None
    person_id: str | None
    reason: str
    timestamp: str
