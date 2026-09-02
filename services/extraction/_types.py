"""Stable internal types for field extraction."""

from __future__ import annotations

from typing import Any, TypedDict


class ExtractedFields(TypedDict, total=False):
    """Common keys returned by per-document extractors.

    OCR/LLM payloads may include additional dynamic keys; this TypedDict
    documents the stable cross-match contract and frequent identity fields.
    """

    loan_amount: str
    tenure: int
    emi: str
    roi: float
    applicant_name: str
    borrower_name: str
    pan_number: str
    aadhaar_number: str
    person_records: list[dict[str, Any]]
