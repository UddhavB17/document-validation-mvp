"""Stable internal types for consistency checks."""

from __future__ import annotations

from typing import Any, TypedDict


class ConsistencyObservation(TypedDict, total=False):
    person_id: str
    field: str
    value: Any
    document_type: str
    page_number: int
    ocr_text: str


class ConsistencyAnomaly(TypedDict, total=False):
    rule_id: str
    severity: str
    expected_value: Any
    found_value: Any
    reason: str
    page_number: int
    document_type: str
    person_id: str
