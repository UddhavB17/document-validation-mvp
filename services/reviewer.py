"""Reviewer exception handling, deterministic summaries, and persistence.

Large loan files can produce hundreds of per-page LOW severity flags
(UNCLASSIFIED_PAGE, LOW_OCR_CONFIDENCE, UNREADABLE_PAGE). Operations teams
need a short actionable list, not one row per scanned page.
"""

from __future__ import annotations

from collections import Counter
import json
from typing import Any

from database.db import get_connection

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

IDENTITY_RULES = {
    "AADHAAR_NUMBER_MISMATCH",
    "PAN_NUMBER_MISMATCH",
    "DATE_OF_BIRTH_MISMATCH",
}

# Per-page quality flags that should be summarized, not listed one-by-one.
_COLLAPSIBLE_RULES = frozenset(
    {
        "UNCLASSIFIED_PAGE",
        "LOW_OCR_CONFIDENCE",
        "UNREADABLE_PAGE",
    }
)

_SUMMARY_REASONS = {
    "UNCLASSIFIED_PAGE": "Pages could not be classified automatically",
    "LOW_OCR_CONFIDENCE": "OCR confidence below threshold on scanned pages",
    "UNREADABLE_PAGE": "Scanned pages flagged as blurry or unreadable",
}


def collapse_for_reviewer(anomalies: list[dict]) -> list[dict]:
    """Return a deduplicated list suitable for the reviewer UI."""
    actionable: list[dict] = []
    buckets: dict[str, list[dict]] = {rule: [] for rule in _COLLAPSIBLE_RULES}

    for anomaly in anomalies:
        rule_id = str(anomaly.get("rule_id") or "")
        if rule_id in _COLLAPSIBLE_RULES:
            buckets[rule_id].append(anomaly)
        else:
            actionable.append(anomaly)

    for rule_id, items in buckets.items():
        if not items:
            continue
        if len(items) == 1:
            actionable.append(items[0])
            continue
        pages = sorted({item.get("page_number") for item in items if item.get("page_number") is not None})
        severities = {str(item.get("severity", "LOW")).upper() for item in items}
        severity = "MEDIUM" if "MEDIUM" in severities else "LOW"
        page_preview = ", ".join(map(str, pages[:8]))
        if len(pages) > 8:
            page_preview += f", … (+{len(pages) - 8} more)"
        actionable.append(
            {
                "rule_id": f"{rule_id}_SUMMARY",
                "severity": severity,
                "document_type": items[0].get("document_type"),
                "expected_value": items[0].get("expected_value"),
                "found_value": f"{len(items)} page(s): {page_preview}" if pages else f"{len(items)} page(s)",
                "page_number": pages[0] if pages else None,
                "reason": f"{_SUMMARY_REASONS[rule_id]} ({len(items)} pages)",
                "collapsed_page_numbers": pages,
                "collapsed_count": len(items),
            }
        )

    return _sort_anomalies(actionable)


def summarize_for_display(anomalies: list[dict]) -> dict[str, int | list[dict]]:
    """Build counts for banners and metrics."""
    collapsed = collapse_for_reviewer(anomalies)
    high = [item for item in collapsed if str(item.get("severity", "")).upper() == "HIGH"]
    medium = [item for item in collapsed if str(item.get("severity", "")).upper() == "MEDIUM"]
    low = [item for item in collapsed if str(item.get("severity", "")).upper() == "LOW"]
    return {
        "reviewer_anomalies": collapsed,
        "reviewer_count": len(collapsed),
        "raw_count": len(anomalies),
        "high_count": len(high),
        "medium_count": len(medium),
        "low_count": len(low),
    }


def compute_final_status(anomalies: list[dict]) -> str:
    """Derive file status from actionable anomalies, not raw OCR noise."""
    collapsed = collapse_for_reviewer(anomalies)
    if not collapsed:
        return "CLEAN"
    if any(str(item.get("severity", "")).upper() == "HIGH" for item in collapsed):
        return "CRITICAL"
    return "NEEDS_REVIEW"


def _sort_anomalies(anomalies: list[dict]) -> list[dict]:
    return sorted(
        anomalies,
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity", "LOW")).upper(), 3),
            item.get("page_number") or 10**9,
            str(item.get("rule_id") or ""),
        ),
    )


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


def save_reviewer_summary(application_id: int, summary: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO reviewer_summaries (application_id, summary_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(application_id) DO UPDATE SET
                summary_json = excluded.summary_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (application_id, json.dumps(summary, ensure_ascii=False)),
        )


def load_reviewer_summary(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT summary_json FROM reviewer_summaries WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    if row is None:
        return None
    value = json.loads(str(row["summary_json"]))
    return value if isinstance(value, dict) else None
