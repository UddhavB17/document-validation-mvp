"""Exception aggregator.

Merges exception lists from multiple evaluation passes into a single,
deduplicated, priority-sorted list ready for the report generator.
"""

from __future__ import annotations

import json
from typing import cast

from database.db import get_connection
from services.processing_policy import is_internal_document_type
from services.reviewer import compute_final_status

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _sort_anomalies(anomalies: list[dict]) -> list[dict]:
    return sorted(
        anomalies,
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity", "LOW")).upper(), 3),
            cast(int, item.get("page_number") or 10**9),
        ),
    )


def _dedupe_anomalies(anomalies: list[dict]) -> list[dict]:
    """Collapse the same finding emitted by overlapping validation passes."""
    result: list[dict] = []
    seen: set[tuple[object, ...]] = set()
    for anomaly in anomalies:
        key = (
            anomaly.get("rule_id"),
            anomaly.get("page_number"),
            anomaly.get("person_id") or anomaly.get("applicant_role"),
            anomaly.get("document_type") or anomaly.get("document"),
            anomaly.get("field_name"),
            _stringify(anomaly.get("expected_value")),
            _stringify(anomaly.get("found_value")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(anomaly)
    return result


def aggregate(
    pages: list[dict],
    anomalies: list[dict],
    ground_truth: dict,
    application_id: int | None = None,
) -> dict:
    sorted_anomalies = _sort_anomalies(_dedupe_anomalies(anomalies))
    documents_found = sorted(
        {
            cast(str, page.get("document_type"))
            for page in pages
            if (
                page.get("document_type")
                and page.get("document_type") != "Unknown"
                and not is_internal_document_type(page.get("document_type"))
            )
        }
    )
    documents_missing = sorted(
        {
            cast(str, anomaly.get("document_type"))
            for anomaly in sorted_anomalies
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC")
            and anomaly.get("document_type")
        }
    )
    pages_with_issues = sorted(
        {
            cast(int, anomaly.get("page_number"))
            for anomaly in sorted_anomalies
            if anomaly.get("page_number") is not None
        }
    )

    # ws-f accuracy: missing-document presence anomalies stay in the active
    # list (operations needs them) tagged with category="MISSING_DOCUMENT"
    # instead of being stripped.
    active_anomalies = []
    for anomaly in sorted_anomalies:
        if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC"):
            anomaly = {**anomaly, "category": "MISSING_DOCUMENT"}
        active_anomalies.append(anomaly)

    if not active_anomalies:
        final_status = "CLEAN"
    else:
        final_status = compute_final_status(active_anomalies)

    result = {
        "total_pages": len(pages),
        "digital_pages": sum(1 for page in pages if page.get("page_type") == "digital"),
        "scanned_pages": sum(1 for page in pages if page.get("page_type") == "scanned"),
        "ground_truth": ground_truth,
        "documents_found": documents_found,
        "documents_missing": documents_missing,
        "anomalies": active_anomalies,
        "pages_with_issues": pages_with_issues,
        "final_status": final_status,
    }

    if application_id is not None:
        save_aggregation(application_id, active_anomalies, final_status)

    return result


def save_aggregation(application_id: int, anomalies: list[dict], final_status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM validation_results WHERE application_id = ?", (application_id,)
        )
        if anomalies:
            connection.execute(
                """
                INSERT INTO validation_results (
                    application_id,
                    rule_id,
                    s_no,
                    severity,
                    document_type,
                    expected_value,
                    found_value,
                    page_number,
                    reason,
                    evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        application_id,
                        anomaly.get("rule_id"),
                        anomaly.get("s_no"),
                        anomaly.get("severity"),
                        anomaly.get("document_type"),
                        _stringify(anomaly.get("expected_value")),
                        _stringify(anomaly.get("found_value")),
                        anomaly.get("page_number"),
                        anomaly.get("reason"),
                        _stringify(anomaly.get("evidence_json")),
                    )
                    for anomaly in anomalies
                ],
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
    aggregated = _dedupe_anomalies(aggregated)
    aggregated.sort(
        key=lambda e: (
            _SEVERITY_ORDER.get(str(e.get("severity", "low")).lower(), 2),
            e.get("document", ""),
        )
    )
    return aggregated
