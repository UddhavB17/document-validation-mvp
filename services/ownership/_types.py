"""Stable internal types for person ownership resolution."""

from __future__ import annotations

from typing import TypedDict


class OwnerResolution(TypedDict, total=False):
    person_id: str | None
    confidence: float
    evidence: list[str]
    source_role: str | None


class TrustedPersonRecord(TypedDict, total=False):
    applicant_name: str
    pan_number: str
    aadhaar_number: str
    role: str
