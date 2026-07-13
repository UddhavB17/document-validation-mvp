"""Deterministic reviewer summary and escalation recommendations."""

from __future__ import annotations

from collections import Counter
from typing import Any


IDENTITY_RULES = {
    "AADHAAR_NUMBER_MISMATCH",
    "PAN_NUMBER_MISMATCH",
    "DATE_OF_BIRTH_MISMATCH",
}


def build_reviewer_summary(
    *,
    total_pages: int,
    anomalies: list[dict[str, Any]],
    checked_fields: int = 0,
    matched_fields: int = 0,
) -> dict[str, Any]:
    """Return an auditable, non-LLM recommendation for the final reviewer."""
    review_anomalies = [item for item in anomalies if _needs_review(item)]
    pages = sorted(
        {
            int(item["page_number"])
            for item in review_anomalies
            if item.get("page_number") not in (None, "")
        }
    )
    severity_counts = Counter(str(item.get("severity") or "LOW").upper() for item in review_anomalies)
    rule_ids = {str(item.get("rule_id") or "") for item in review_anomalies}
    high_count = severity_counts["HIGH"]
    processing_failure = bool(
        rule_ids & {"PAGE_PROCESSING_ERROR", "OCR_BUDGET_PARTIAL_SCAN", "DOCUMENT_NOT_READABLE"}
    )
    identity_mismatch = bool(rule_ids & IDENTITY_RULES)

    if processing_failure or high_count >= 3 or len(pages) >= max(8, total_pages // 3):
        overall_status = "FULL_MANUAL_REVIEW"
        recommendation = (
            "Several serious anomalies or incomplete processing results were found. "
            "Completely check the loan file before making a decision."
        )
    elif identity_mismatch or high_count > 0:
        overall_status = "HIGH_RISK"
        recommendation = (
            "Check every listed page and the corresponding original identity document. "
            "Do not approve the file until the high-severity differences are resolved."
        )
    elif review_anomalies:
        overall_status = "LIMITED_REVIEW"
        recommendation = "Review only the listed pages and confirm the flagged fields."
    else:
        overall_status = "CLEAN"
        recommendation = "No system-detected exception requires manual page review."

    if not review_anomalies:
        message = f"All {checked_fields} checked field(s) matched the trusted data."
    else:
        message = (
            f"Checked {checked_fields} field(s): {matched_fields} matched and "
            f"{max(0, checked_fields - matched_fields)} require attention. "
            f"Found {len(review_anomalies)} review item(s) across {len(pages)} page(s)."
        )

    return {
        "overall_status": overall_status,
        "message": message,
        "recommendation": recommendation,
        "total_pages": total_pages,
        "checked_fields": checked_fields,
        "matched_fields": matched_fields,
        "anomaly_count": len(review_anomalies),
        "severity_counts": {
            "high": severity_counts["HIGH"],
            "medium": severity_counts["MEDIUM"],
            "low": severity_counts["LOW"],
        },
        "pages_to_review": pages,
        "review_items": [_review_item(item) for item in review_anomalies],
    }


def _needs_review(anomaly: dict[str, Any]) -> bool:
    return str(anomaly.get("rule_id") or "") not in {"", "MATCH"}


def _review_item(anomaly: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_number": anomaly.get("page_number"),
        "person_id": anomaly.get("person_id"),
        "matched_person_id": anomaly.get("matched_person_id"),
        "document_type": anomaly.get("document_type"),
        "field": anomaly.get("field_name") or _field_from_rule(anomaly.get("rule_id")),
        "status": anomaly.get("status") or "MANUAL_REVIEW_REQUIRED",
        "severity": str(anomaly.get("severity") or "LOW").upper(),
        "reason": anomaly.get("reason") or anomaly.get("found_value"),
        "expected_masked": _mask(anomaly.get("expected_value")),
        "extracted_masked": _mask(anomaly.get("found_value")),
    }


def _field_from_rule(rule_id: Any) -> str | None:
    value = str(rule_id or "")
    for suffix in ("_MISMATCH", "_NOT_FOUND", "_NOT_READABLE", "_LOW_CONFIDENCE"):
        if value.endswith(suffix):
            return value[: -len(suffix)].lower()
    return None


def _mask(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    compact = "".join(text.split())
    if len(compact) <= 4:
        return "*" * len(compact)
    return f"{'*' * min(8, len(compact) - 4)}{compact[-4:]}"
