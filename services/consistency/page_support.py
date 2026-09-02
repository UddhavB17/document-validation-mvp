"""Page-text support helpers for consistency checks."""

from __future__ import annotations

from typing import Any

from services.consistency.matching import _compact, _names_equivalent


def _page_text_supports_value(page_text: Any, expected: Any) -> bool:
    text = str(page_text or "")
    if not text or expected in (None, ""):
        return False
    if _compact(expected) and _compact(expected) in _compact(text):
        return True
    return _names_equivalent(expected, text)


def _find_supporting_page_number(
    pages: list[dict],
    current_page: dict,
    value: Any,
) -> int:
    """Find the page number in the same document that supports the value, or return current page number."""
    current_page_no = int(current_page.get("page_number") or 0)
    if value in (None, ""):
        return current_page_no
    if _page_text_supports_value(current_page.get("ocr_text"), value):
        return current_page_no

    doc_id = current_page.get("source_document_id")
    doc_type = current_page.get("document_type")

    candidates = []
    for p in pages:
        p_no = int(p.get("page_number") or 0)
        if p_no == current_page_no:
            continue
        if doc_id and p.get("source_document_id") == doc_id:
            candidates.append(p)
        elif (
            not doc_id and p.get("document_type") == doc_type and abs(p_no - current_page_no) <= 12
        ):
            candidates.append(p)

    for p in sorted(candidates, key=lambda item: int(item.get("page_number") or 0)):
        if _page_text_supports_value(p.get("ocr_text"), value):
            return int(p.get("page_number") or 0)

    return current_page_no
