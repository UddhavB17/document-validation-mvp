"""Operations-focused processing policy for large loan packets.

By default every scanned page is OCR'd. Set ``DMEF_MAX_SCANNED_OCR_PAGES`` or
``DMEF_FULL_SCAN_OCR=false`` to sample large packets when runtime must be bounded.
"""

from __future__ import annotations

import math
from typing import Any

from services.config import get_bool, get_int

OCR_SKIPPED_DOCUMENT_TYPE = "OCR Skipped"
INTERNAL_DOCUMENT_TYPES = frozenset({OCR_SKIPPED_DOCUMENT_TYPE})


def max_scanned_pages_for_ocr() -> int:
    """Return the scanned-page OCR budget when sampling is enabled.

    Ignored when :func:`full_scan_ocr_enabled` is True. Use a positive budget
    with ``DMEF_FULL_SCAN_OCR=false`` to sample front, middle, and tail pages.
    """
    return get_int("DMEF_MAX_SCANNED_OCR_PAGES", 30, minimum=0)


def full_scan_ocr_enabled() -> bool:
    """Return True when every scanned page should be OCR-rendered."""
    return get_bool("DMEF_FULL_SCAN_OCR", True) or max_scanned_pages_for_ocr() == 0


def selected_scanned_page_numbers(page_structure: list[dict[str, Any]]) -> set[int]:
    """Choose scanned pages for OCR using a front/tail/even-sample strategy."""
    scanned_pages = [
        int(page["page_number"])
        for page in page_structure
        if page.get("page_type") == "scanned"
    ]
    if not scanned_pages:
        return set()

    if full_scan_ocr_enabled():
        return set(scanned_pages)

    budget = max_scanned_pages_for_ocr()
    if len(scanned_pages) <= budget:
        return set(scanned_pages)

    front_count = min(budget, max(1, math.ceil(budget * 0.60)))
    remaining_budget = max(0, budget - front_count)
    tail_count = min(remaining_budget, max(0, math.floor(budget * 0.20)))
    middle_count = max(0, budget - front_count - tail_count)

    selected = set(scanned_pages[:front_count])
    if tail_count:
        selected.update(scanned_pages[-tail_count:])

    middle_end = -tail_count if tail_count else None
    middle = scanned_pages[front_count:middle_end]
    if middle and middle_count > 0:
        if len(middle) <= middle_count:
            selected.update(middle)
        else:
            step = len(middle) / middle_count
            for index in range(middle_count):
                selected.add(middle[min(len(middle) - 1, int(index * step))])

    return set(sorted(selected))


def build_ocr_skipped_fields(page_number: int, total_scanned_pages: int) -> dict[str, Any]:
    return {
        "_ocr_skipped": True,
        "reason": (
            "Skipped by large-file OCR budget. This page remains available for "
            "manual review or full-scan fallback."
        ),
        "page_number": page_number,
        "total_scanned_pages": total_scanned_pages,
        "ocr_budget": max_scanned_pages_for_ocr(),
    }


def is_internal_document_type(document_type: object) -> bool:
    return str(document_type or "") in INTERNAL_DOCUMENT_TYPES


def is_ocr_skipped_page(page: dict[str, Any]) -> bool:
    extracted_fields = page.get("extracted_fields") or {}
    return (
        page.get("document_type") == OCR_SKIPPED_DOCUMENT_TYPE
        or (isinstance(extracted_fields, dict) and bool(extracted_fields.get("_ocr_skipped")))
    )
