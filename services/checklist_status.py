"""Build per-item MSFC checklist status for the reviewer UI."""

from __future__ import annotations

from typing import Any

from services.checklist_engine import condition_applies, system_flag_state
from services.document_presence import assess_document_presence, review_presence_findings
from services.page_quality import confident_pages_for_types


def _document_types(item: dict[str, Any]) -> list[str]:
    document_type = item.get("document_type")
    if isinstance(document_type, list):
        return [str(value) for value in document_type]
    if document_type:
        return [str(document_type)]
    return []


def _pages_for_types(pages: list[dict[str, Any]], document_types: list[str]) -> list[int]:
    page_numbers = [
        int(page["page_number"])
        for page in confident_pages_for_types(pages, document_types)
        if page.get("page_number") is not None
    ]
    return sorted(set(page_numbers))


def build_checklist_status(
    checklist_items: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    system_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return one row per checklist item with FOUND / MISSING status."""
    anomalies = review_presence_findings(pages, anomalies, checklist_items)
    missing_by_sno = {
        int(anomaly["s_no"])
        for anomaly in anomalies
        if anomaly.get("s_no") is not None
        and str(anomaly.get("rule_id", "")).startswith("MISSING_DOC")
    }
    review_by_sno = {
        int(a["s_no"]) for a in anomalies
        if a.get("s_no") is not None and not str(a.get("rule_id", "")).startswith("MISSING_DOC")
    }

    system_data = system_data or {}
    rows: list[dict[str, Any]] = []
    for item in sorted(checklist_items, key=lambda row: int(row.get("s_no") or 0)):
        s_no = int(item.get("s_no") or 0)
        document_types = _document_types(item)
        matched_pages = _pages_for_types(pages, document_types)
        assessment = assess_document_presence(pages, document_types)
        applicability = condition_applies(item.get("applies_when"), system_data)
        system_state = (
            system_flag_state(item, system_data)
            if item.get("check_type") == "system_flag"
            else None
        )
        if applicability is False:
            status = "not_applicable"
        elif s_no in missing_by_sno:
            status = "required_and_missing"
        elif s_no in review_by_sno or (assessment.candidate_pages and not matched_pages):
            status = "manual_review"
        elif matched_pages or system_state is True:
            status = "required_and_present"
        elif applicability is None or system_state is None:
            status = "not_evaluated_by_engine"
        else:
            status = "manual_review"

        rows.append(
            {
                "s_no": s_no,
                "category": item.get("category", ""),
                "description": item.get("description", ""),
                "document_types": ", ".join(document_types),
                "status": status,
                "pages": ", ".join(map(str, sorted(set(matched_pages + assessment.review_pages)))) or "-",
            }
        )
    return rows
