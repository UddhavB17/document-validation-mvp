"""Exception aggregator.

Merges exception lists from multiple evaluation passes into a single,
deduplicated, priority-sorted list ready for the report generator.
"""

from __future__ import annotations

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

import json

from database.db import get_connection

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _sort_anomalies(anomalies: list[dict]) -> list[dict]:
    return sorted(
        anomalies,
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity", "LOW")).upper(), 3),
            item.get("page_number") or 10**9,
        ),
    )


def aggregate(
    pages: list[dict],
    anomalies: list[dict],
    ground_truth: dict,
    application_id: int | None = None,
) -> dict:
    sorted_anomalies = _sort_anomalies(anomalies)
    documents_found = sorted(
        {
            page.get("document_type")
            for page in pages
            if page.get("document_type") and page.get("document_type") != "Unknown"
        }
    )
    documents_missing = sorted(
        {
            anomaly.get("document_type")
            for anomaly in sorted_anomalies
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC") and anomaly.get("document_type")
        }
    )
    pages_with_issues = sorted(
        {anomaly.get("page_number") for anomaly in sorted_anomalies if anomaly.get("page_number") is not None}
    )

    if not sorted_anomalies:
        final_status = "CLEAN"
    elif any(str(anomaly.get("severity")).upper() == "HIGH" for anomaly in sorted_anomalies):
        final_status = "CRITICAL"
    else:
        final_status = "NEEDS_REVIEW"

    result = {
        "total_pages": len(pages),
        "digital_pages": sum(1 for page in pages if page.get("page_type") == "digital"),
        "scanned_pages": sum(1 for page in pages if page.get("page_type") == "scanned"),
        "ground_truth": ground_truth,
        "documents_found": documents_found,
        "documents_missing": documents_missing,
        "anomalies": sorted_anomalies,
        "pages_with_issues": pages_with_issues,
        "final_status": final_status,
    }

    if application_id is not None:
        save_aggregation(application_id, sorted_anomalies, final_status)

    return result


def save_aggregation(application_id: int, anomalies: list[dict], final_status: str) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM validation_results WHERE application_id = ?", (application_id,))
        for anomaly in anomalies:
            connection.execute(
                """
                INSERT INTO validation_results (
                    application_id,
                    rule_id,
                    severity,
                    document_type,
                    expected_value,
                    found_value,
                    page_number,
                    reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    anomaly.get("rule_id"),
                    anomaly.get("severity"),
                    anomaly.get("document_type"),
                    _stringify(anomaly.get("expected_value")),
                    _stringify(anomaly.get("found_value")),
                    anomaly.get("page_number"),
                    anomaly.get("reason"),
                ),
            )
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (final_status, application_id),
        )


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def aggregate_exceptions(*exception_groups: list[dict]) -> list[dict]:
    """Merge and sort exception groups.

    Args:
        *exception_groups: One or more lists of exception dicts produced
                           by the checklist engine or other validators.

    Returns:
        Single flat list sorted by severity (high → medium → low),
        then by document name for stable ordering.
    """
    aggregated: list[dict] = []
    for group in exception_groups:
        aggregated.extend(group)

    # Sort: severity first, then document name alphabetically
    aggregated.sort(
        key=lambda e: (
            _SEVERITY_ORDER.get(e.get("severity", "low"), 2),
            e.get("document", ""),
        )
    )
    return aggregated
