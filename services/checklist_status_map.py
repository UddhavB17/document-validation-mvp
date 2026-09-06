"""Single shared document/checklist status model for DMEF.

Owns the new 5-value checklist status enum, the 4-value OCR status enum,
and the exhaustive legacy -> new mapping. Any unmapped legacy value raises
instead of silently passing through.
"""

from __future__ import annotations

from typing import Literal

DocumentChecklistStatus = Literal[
    "required_and_present",
    "required_and_missing",
    "not_applicable",
    "not_evaluated_by_engine",
    "manual_review",
]

OcrStatus = Literal["success", "failed", "no_text_extracted", "not_applicable"]

CHECKLIST_STATUSES: tuple[str, ...] = (
    "required_and_present",
    "required_and_missing",
    "not_applicable",
    "not_evaluated_by_engine",
    "manual_review",
)

OCR_STATUSES: tuple[str, ...] = (
    "success",
    "failed",
    "no_text_extracted",
    "not_applicable",
)

LEGACY_CHECKLIST_MAP: dict[str, str] = {
    "verified": "required_and_present",
    "missing": "required_and_missing",
    "not_applicable": "not_applicable",
    "needs_review": "manual_review",
    "unknown": "manual_review",
}


def map_legacy_checklist_status(value: str) -> str:
    """Map one legacy checklist status to the new enum, raising on unknown input."""
    if value not in LEGACY_CHECKLIST_MAP:
        raise ValueError(f"unmapped legacy checklist status: {value!r}")
    return LEGACY_CHECKLIST_MAP[value]
