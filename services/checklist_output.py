"""Build reviewer-facing 44-item NDC checklist output."""

from __future__ import annotations

import time
from typing import Any

from database.models import (
    ChecklistItem,
    ChecklistProcessingMetadata,
    ChecklistSummary,
    ChecklistVerificationResponse,
)
from services.checklist_service import get_all_checklist_items
from services.checklist_engine import (
    _document_derived_system_data,
    _document_evidence_count,
    bank_statement_required_month_labels,
    condition_applies,
    system_flag_state,
)
from services.page_quality import confident_pages_for_types


def build_checklist_verification_response(
    *,
    loan_file_id: str,
    pages: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    product_type: str = "LAP",
    processing_metadata: dict[str, Any] | None = None,
    system_data: dict[str, Any] | None = None,
    include_narration: bool = False,
) -> ChecklistVerificationResponse:
    """Convert deterministic checklist output into the reviewer/API contract."""
    started_at = time.perf_counter()
    checklist_items = get_all_checklist_items(product_type)
    system_data = {**_document_derived_system_data(pages), **(system_data or {})}
    anomalies_by_sno = _anomalies_by_sno(anomalies)
    items = [
        _build_item(
            checklist_item=checklist_item,
            pages=pages,
            item_anomalies=anomalies_by_sno.get(int(checklist_item.get("s_no") or 0), []),
            system_data=system_data,
            include_narration=include_narration,
        )
        for checklist_item in sorted(checklist_items, key=lambda item: int(item.get("s_no") or 0))
    ]
    metadata = _processing_metadata(processing_metadata)
    if include_narration:
        metadata.narration_time_ms = max(
            metadata.narration_time_ms,
            int((time.perf_counter() - started_at) * 1000),
        )
    return ChecklistVerificationResponse(
        loan_file_id=str(loan_file_id),
        summary=_summary(items),
        items=items,
        processing_metadata=metadata,
    )


def _build_item(
    *,
    checklist_item: dict[str, Any],
    pages: list[dict[str, Any]],
    item_anomalies: list[dict[str, Any]],
    system_data: dict[str, Any],
    include_narration: bool,
) -> ChecklistItem:
    item_number = int(checklist_item.get("s_no") or 0)
    document_types = _document_types(checklist_item)
    matched_pages = confident_pages_for_types(pages, document_types)
    missing_anomalies = [
        anomaly
        for anomaly in item_anomalies
        if str(anomaly.get("rule_id") or "").startswith("MISSING_DOC")
    ]
    review_anomalies = [anomaly for anomaly in item_anomalies if anomaly not in missing_anomalies]
    applicability = condition_applies(checklist_item.get("applies_when"), system_data)
    system_state = (
        system_flag_state(checklist_item, system_data)
        if checklist_item.get("check_type") == "system_flag"
        else None
    )

    if applicability is False:
        status = "not_applicable"
        flagged_reason = None
    elif missing_anomalies:
        status = "missing"
        flagged_reason = _flagged_reason(missing_anomalies[0])
    elif review_anomalies:
        status = "needs_review"
        flagged_reason = _flagged_reason(review_anomalies[0])
    elif matched_pages or system_state is True:
        status = "verified"
        flagged_reason = None
    else:
        status = "unknown"
        flagged_reason = (
            "manual_review_required" if not checklist_item.get("ai_checkable") else "not_checked"
        )

    confidence, confidence_detail = _confidence_for_item(
        checklist_item=checklist_item,
        matched_pages=matched_pages,
        item_anomalies=item_anomalies,
        status=status,
        system_data=system_data,
    )
    extracted_fields = _merge_extracted_fields(matched_pages)
    if item_number == 17:
        bank_statement_pages = confident_pages_for_types(pages, ["Bank Statement"])
        required_months = bank_statement_required_month_labels(system_data)
        if bank_statement_pages and required_months:
            extracted_fields["required_statement_months"] = ", ".join(required_months)
            extracted_fields["statement_pages_evaluated_together"] = str(len(bank_statement_pages))
            extracted_fields["coverage_scope"] = "Collective, per bank account"
    if checklist_item.get("check_type") == "system_flag":
        field = str(checklist_item.get("system_field") or "system_status")
        value = system_data.get(field)
        if value not in (None, ""):
            extracted_fields[field] = str(value)
    extraction_source = (
        "llm_fallback"
        if any(_used_llm_fallback(page) for page in matched_pages)
        else "deterministic"
    )

    item = ChecklistItem(
        item_number=item_number,
        document_name=_document_name(checklist_item, document_types),
        status=status,
        confidence=confidence,
        confidence_detail=confidence_detail,
        extracted_fields=extracted_fields,
        extraction_source=extraction_source,
        flagged_reason=flagged_reason,
    )
    if include_narration and status not in {"verified", "not_applicable"}:
        from services.checklist_narration import narrate_checklist_item

        item.narration = narrate_checklist_item(item)
    return item


def _anomalies_by_sno(anomalies: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for anomaly in anomalies:
        if anomaly.get("s_no") is None:
            continue
        grouped.setdefault(int(anomaly["s_no"]), []).append(anomaly)
    return grouped


def _document_types(item: dict[str, Any]) -> list[str]:
    document_type = item.get("document_type")
    if isinstance(document_type, list):
        return [str(value) for value in document_type if value]
    if document_type:
        return [str(document_type)]
    return []


def _document_name(checklist_item: dict[str, Any], document_types: list[str]) -> str:
    if document_types:
        return " / ".join(document_types)
    return str(checklist_item.get("description") or f"Checklist item {checklist_item.get('s_no')}")


def _confidence_for_item(
    *,
    checklist_item: dict[str, Any],
    matched_pages: list[dict[str, Any]],
    item_anomalies: list[dict[str, Any]],
    status: str,
    system_data: dict[str, Any],
) -> tuple[str, str]:
    document_types = _document_types(checklist_item)
    primary_type = document_types[0] if len(document_types) == 1 else ""
    matched_count, unit = _document_evidence_count(matched_pages, primary_type)
    required_pages = int(checklist_item.get("min_count") or 1)
    applicable_minimums = [
        int(requirement.get("min_count") or 1)
        for requirement in checklist_item.get("requirements") or []
        if condition_applies(requirement.get("applies_when"), system_data) is True
    ]
    if applicable_minimums:
        required_pages = max(applicable_minimums)
    if status == "missing":
        if item_anomalies:
            return "low", _anomaly_detail(item_anomalies[0])
        return "low", f"matched {matched_count} of {required_pages} expected {unit}"
    if status == "not_applicable":
        return "high", str(
            checklist_item.get("condition_description") or "condition is false; item not applicable"
        )
    if status == "verified" and checklist_item.get("check_type") == "system_flag":
        return "high", "confirmed by system checklist status"
    if status == "unknown":
        return "low", "no deterministic checklist rule could verify this item"
    if item_anomalies:
        return "medium", _anomaly_detail(item_anomalies[0])

    confidences = [
        float(page.get("classification_confidence"))
        for page in matched_pages
        if page.get("classification_confidence") not in (None, "")
    ]
    if not confidences:
        return "medium", f"matched {matched_count} of {required_pages} expected {unit}"

    minimum_confidence = min(confidences)
    detail = (
        f"matched {matched_count} of {required_pages} expected {unit}; "
        f"lowest classification confidence {minimum_confidence:.0%}"
    )
    if minimum_confidence >= 0.85 and matched_count >= required_pages:
        return "high", detail
    return "medium", detail


def _anomaly_detail(anomaly: dict[str, Any]) -> str:
    expected = anomaly.get("expected_value")
    found = anomaly.get("found_value")
    reason = anomaly.get("reason") or anomaly.get("rule_id") or "deterministic rule failed"
    if expected not in (None, "") or found not in (None, ""):
        return f"{reason}; expected {expected or '-'}, found {found or '-'}"
    return str(reason)


def _merge_extracted_fields(pages: list[dict[str, Any]]) -> dict[str, str | None]:
    merged: dict[str, str | None] = {}
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        fields = page.get("extracted_fields") or {}
        if not isinstance(fields, dict):
            continue
        for field_name, value in fields.items():
            if str(field_name).startswith("_") or value in ([], {}):
                continue
            merged.setdefault(str(field_name), None if value is None else str(value))
    return merged


def _used_llm_fallback(page: dict[str, Any]) -> bool:
    fields = page.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        return False
    fallback = fields.get("_llm_field_extraction")
    return isinstance(fallback, dict) and fallback.get("status") == "fields_extracted"


def _flagged_reason(anomaly: dict[str, Any]) -> str:
    rule_id = str(anomaly.get("rule_id") or "").strip().lower()
    if rule_id:
        return rule_id
    reason = str(anomaly.get("reason") or "needs_manual_review").strip().lower()
    return "_".join(reason.split())[:80]


def _summary(items: list[ChecklistItem]) -> ChecklistSummary:
    return ChecklistSummary(
        total=len(items),
        verified=sum(1 for item in items if item.status == "verified"),
        needs_review=sum(1 for item in items if item.status == "needs_review"),
        missing=sum(1 for item in items if item.status == "missing"),
        unknown=sum(1 for item in items if item.status == "unknown"),
        not_applicable=sum(1 for item in items if item.status == "not_applicable"),
    )


def _processing_metadata(metadata: dict[str, Any] | None) -> ChecklistProcessingMetadata:
    metadata = metadata or {}
    return ChecklistProcessingMetadata(
        ocr_time_ms=int(float(metadata.get("ocr_time_ms") or 0)),
        classification_time_ms=int(float(metadata.get("classification_time_ms") or 0)),
        narration_time_ms=int(float(metadata.get("narration_time_ms") or 0)),
    )
