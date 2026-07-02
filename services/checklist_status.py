"""Build per-item MSFC checklist status for the reviewer UI."""

from __future__ import annotations

from typing import Any


def _document_types(item: dict[str, Any]) -> list[str]:
    document_type = item.get("document_type")
    if isinstance(document_type, list):
        return [str(value) for value in document_type]
    if document_type:
        return [str(document_type)]
    return []


def _pages_for_types(pages: list[dict[str, Any]], document_types: list[str]) -> list[int]:
    page_numbers: list[int] = []
    for page in pages:
        if page.get("document_type") in document_types and page.get("page_number") is not None:
            page_numbers.append(int(page["page_number"]))
    return sorted(set(page_numbers))


def build_checklist_status(
    checklist_items: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one row per checklist item with FOUND / MISSING status."""
    missing_by_sno = {
        int(anomaly["s_no"])
        for anomaly in anomalies
        if anomaly.get("s_no") is not None and str(anomaly.get("rule_id", "")).startswith("MISSING_DOC")
    }

    rows: list[dict[str, Any]] = []
    for item in sorted(checklist_items, key=lambda row: int(row.get("s_no") or 0)):
        s_no = int(item.get("s_no") or 0)
        document_types = _document_types(item)
        matched_pages = _pages_for_types(pages, document_types)
        if matched_pages:
            status = "FOUND"
        elif s_no in missing_by_sno:
            status = "MISSING"
        else:
            status = "NOT_CHECKED"

        rows.append(
            {
                "s_no": s_no,
                "category": item.get("category", ""),
                "description": item.get("description", ""),
                "document_types": ", ".join(document_types),
                "status": status,
                "pages": ", ".join(map(str, matched_pages)) if matched_pages else "-",
            }
        )
    return rows
