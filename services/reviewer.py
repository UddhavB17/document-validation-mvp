"""Reviewer exception handling, deterministic summaries, and persistence.

Large loan files can produce hundreds of per-page / per-group flags
(UNCLASSIFIED_PAGE, AUTO_OWNER_*, LOAN_AMOUNT_NOT_FOUND, …). Operations teams
need a short actionable list, not one row per scanned page or document fragment.
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

# Noise that should be summarized, not listed one-by-one.
_COLLAPSIBLE_RULES = frozenset(
    {
        "UNCLASSIFIED_PAGE",
        "LOW_OCR_CONFIDENCE",
        "UNREADABLE_PAGE",
        "AUTO_OWNER_UNRESOLVED",
        "AUTO_OWNER_LOW_CONFIDENCE",
        "LOAN_AMOUNT_NOT_FOUND",
        "APPLICANT_NAME_NOT_FOUND",
        "PIN_CODE_NOT_FOUND",
        "DATE_OF_BIRTH_NOT_FOUND",
        "ADDRESS_NOT_FOUND",
        "PHONE_NUMBER_NOT_FOUND",
        "AADHAAR_NUMBER_NOT_FOUND",
        "PAN_NUMBER_NOT_FOUND",
    }
)

# Checklist / field rules that often fire once per page of the same document.
_COLLAPSIBLE_PREFIXES = (
    "FIELD_MISMATCH_S",
    "STATUS_CHECK_S",
    "PERIOD_CHECK_S",
    "APPLICABILITY_UNKNOWN_S",
)

_SUMMARY_REASONS = {
    "UNCLASSIFIED_PAGE": "Pages could not be classified automatically",
    "LOW_OCR_CONFIDENCE": "OCR confidence below threshold on scanned pages",
    "UNREADABLE_PAGE": "Scanned pages flagged as blurry or unreadable",
    "AUTO_OWNER_UNRESOLVED": "Document groups could not be matched to an applicant",
    "AUTO_OWNER_LOW_CONFIDENCE": "Document groups assigned to an applicant with weak identity evidence",
    "LOAN_AMOUNT_NOT_FOUND": "Loan amount missing from mapped loan documents",
    "APPLICANT_NAME_NOT_FOUND": "Applicant name missing from mapped documents",
    "PIN_CODE_NOT_FOUND": "PIN code missing from mapped documents",
    "DATE_OF_BIRTH_NOT_FOUND": "Date of birth missing from mapped documents",
    "ADDRESS_NOT_FOUND": "Address missing from mapped documents",
    "PHONE_NUMBER_NOT_FOUND": "Phone number missing from mapped documents",
    "AADHAAR_NUMBER_NOT_FOUND": "Aadhaar number missing from mapped documents",
    "PAN_NUMBER_NOT_FOUND": "PAN number missing from mapped documents",
}


def collapse_for_reviewer(anomalies: list[dict]) -> list[dict]:
    """Return a deduplicated list suitable for the reviewer UI."""
    actionable: list[dict] = []
    buckets: dict[str, list[dict]] = {}

    for anomaly in anomalies:
        rule_id = str(anomaly.get("rule_id") or "")
        bucket_key = _collapse_bucket_key(rule_id)
        if bucket_key is None:
            actionable.append(anomaly)
            continue
        buckets.setdefault(bucket_key, []).append(anomaly)

    for bucket_key, items in buckets.items():
        if not items:
            continue
        if len(items) == 1:
            actionable.append(items[0])
            continue
        actionable.append(_build_summary(bucket_key, items))

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
    collapsed = collapse_for_reviewer(anomalies)
    review_anomalies = [item for item in collapsed if _needs_review(item)]
    pages = sorted(
        {
            int(page)
            for item in review_anomalies
            for page in _pages_from_anomaly(item)
        }
    )
    severity_counts = Counter(str(item.get("severity") or "LOW").upper() for item in review_anomalies)
    rule_ids = {str(item.get("rule_id") or "").removesuffix("_SUMMARY") for item in review_anomalies}
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
            f"Found {len(review_anomalies)} review item(s) "
            f"(collapsed from {len(anomalies)} raw flags) across {len(pages)} page(s)."
        )

    return {
        "overall_status": overall_status,
        "message": message,
        "recommendation": recommendation,
        "total_pages": total_pages,
        "checked_fields": checked_fields,
        "matched_fields": matched_fields,
        "anomaly_count": len(review_anomalies),
        "raw_anomaly_count": len(anomalies),
        "severity_counts": {
            "high": severity_counts["HIGH"],
            "medium": severity_counts["MEDIUM"],
            "low": severity_counts["LOW"],
        },
        "pages_to_review": pages[:80],
        "review_items": [_review_item(item) for item in review_anomalies],
    }


def _collapse_bucket_key(rule_id: str) -> str | None:
    if rule_id in _COLLAPSIBLE_RULES:
        return rule_id
    for prefix in _COLLAPSIBLE_PREFIXES:
        if rule_id.startswith(prefix):
            return rule_id
    if rule_id.endswith("_MISMATCH") and rule_id not in IDENTITY_RULES:
        return rule_id
    return None


def _build_summary(rule_id: str, items: list[dict]) -> dict:
    pages = sorted(
        {
            int(page)
            for item in items
            for page in _pages_from_anomaly(item)
        }
    )
    severities = {str(item.get("severity", "LOW")).upper() for item in items}
    if "HIGH" in severities:
        severity = "HIGH"
    elif "MEDIUM" in severities:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    doc_types = Counter(
        str(item.get("document_type") or "Unknown") for item in items if item.get("document_type")
    )
    doc_preview = ", ".join(f"{name}×{count}" for name, count in doc_types.most_common(4))
    page_preview = ", ".join(map(str, pages[:8]))
    if len(pages) > 8:
        page_preview += f", … (+{len(pages) - 8} more)"

    found_parts = [f"{len(items)} occurrence(s)"]
    if page_preview:
        found_parts.append(f"pages {page_preview}")
    if doc_preview:
        found_parts.append(doc_preview)

    reason = _SUMMARY_REASONS.get(rule_id)
    if reason is None:
        reason = items[0].get("reason") or f"Repeated {rule_id} flags"
    reason = f"{reason} ({len(items)} occurrences)"

    return {
        "rule_id": f"{rule_id}_SUMMARY",
        "severity": severity,
        "document_type": items[0].get("document_type"),
        "person_id": items[0].get("person_id"),
        "field_name": items[0].get("field_name"),
        "expected_value": items[0].get("expected_value"),
        "found_value": "; ".join(found_parts),
        "page_number": pages[0] if pages else None,
        "reason": reason,
        "collapsed_page_numbers": pages,
        "collapsed_count": len(items),
        "collapsed_document_types": dict(doc_types),
    }


def _pages_from_anomaly(item: dict[str, Any]) -> list[int]:
    collapsed = item.get("collapsed_page_numbers")
    if isinstance(collapsed, list) and collapsed:
        return [int(page) for page in collapsed if page is not None]
    page = item.get("page_number")
    if page in (None, ""):
        return []
    return [int(page)]


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
        "collapsed_count": anomaly.get("collapsed_count"),
    }


def _field_from_rule(rule_id: Any) -> str | None:
    value = str(rule_id or "").removesuffix("_SUMMARY")
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
