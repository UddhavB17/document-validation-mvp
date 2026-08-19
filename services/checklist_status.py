"""Build per-item MSFC checklist status for the reviewer UI."""

from __future__ import annotations

from typing import Any

from services.page_quality import confident_pages_for_types
from services.checklist_engine import (
    _document_derived_system_data,
    condition_applies,
    system_flag_state,
)


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
    """Return one reviewer-safe status row per configured checklist item with detailed reasons."""
    missing_by_sno = {
        int(anomaly["s_no"])
        for anomaly in anomalies
        if anomaly.get("s_no") is not None and str(anomaly.get("rule_id", "")).startswith("MISSING_DOC")
    }
    review_by_sno = {
        int(anomaly["s_no"])
        for anomaly in anomalies
        if anomaly.get("s_no") is not None and int(anomaly["s_no"]) not in missing_by_sno
    }

    anomalies_by_sno: dict[int, list[dict[str, Any]]] = {}
    for anomaly in anomalies:
        sno = anomaly.get("s_no")
        if sno is not None:
            try:
                sno_int = int(sno)
                anomalies_by_sno.setdefault(sno_int, []).append(anomaly)
            except (ValueError, TypeError):
                pass

    system_data = {**_document_derived_system_data(pages), **(system_data or {})}
    rows: list[dict[str, Any]] = []
    for item in sorted(checklist_items, key=lambda row: int(row.get("s_no") or 0)):
        s_no = int(item.get("s_no") or 0)
        document_types = _document_types(item)
        matched_pages = _pages_for_types(pages, document_types)
        applicability = condition_applies(item.get("applies_when"), system_data)
        system_state = system_flag_state(item, system_data) if item.get("check_type") == "system_flag" else None
        if applicability is False:
            status = "NOT_APPLICABLE"
        elif s_no in missing_by_sno:
            status = "MISSING"
        elif s_no in review_by_sno:
            status = "NEEDS_REVIEW"
        elif not item.get("ai_checkable") or item.get("manual_subcheck_required"):
            status = "NOT_CHECKED"
        elif matched_pages or system_state is True:
            status = "FOUND"
        else:
            status = "NOT_CHECKED"

        # Construct explanation reason
        reason = ""
        if status == "FOUND":
            if item.get("check_type") == "system_flag" and system_state is True:
                reason = "Verified: System validation passed successfully."
            else:
                reason = f"Verified: Document presence detected on page(s) {', '.join(map(str, matched_pages))}."
        elif status == "NOT_APPLICABLE":
            cond_desc = item.get("condition_description")
            reason = f"Not applicable: {cond_desc}" if cond_desc else "Not applicable under current conditions."
        elif status == "MISSING":
            doc_type_str = ", ".join(document_types) if document_types else item.get("document_type", "Required document")
            reason = f"Cannot be verified: Required document '{doc_type_str}' is missing from the upload."
        elif status == "NEEDS_REVIEW":
            sno_anoms = anomalies_by_sno.get(s_no, [])
            if sno_anoms:
                anom_reasons = "; ".join(str(anom.get("reason", "Anomaly detected")) for anom in sno_anoms)
                reason = f"Cannot be verified: Flagged for review. Reason(s): {anom_reasons}"
            else:
                reason = "Cannot be verified: Flagged for manual review due to anomalies."
        elif status == "NOT_CHECKED":
            if not item.get("ai_checkable"):
                manual_reason = item.get("manual_review_reason")
                reason = f"Cannot be verified automatically: {manual_reason}" if manual_reason else "Cannot be verified automatically: Requires physical/manual verification."
            elif item.get("manual_subcheck_required"):
                manual_reason = item.get("manual_review_reason")
                reason = f"Cannot be verified automatically: AI check completed, but manual subcheck is required. {manual_reason or ''}".strip()
            else:
                reason = "Cannot be verified automatically: Requires manual confirmation."

        rows.append(
            {
                "s_no": s_no,
                "category": item.get("category", ""),
                "description": item.get("description", ""),
                "document_types": ", ".join(document_types),
                "status": status,
                "pages": ", ".join(map(str, matched_pages)) if matched_pages else "-",
                "reason": reason,
            }
        )
    return rows
