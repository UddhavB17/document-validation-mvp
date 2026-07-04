"""Collapse OCR noise into reviewer-friendly exception lists.

Large loan files can produce hundreds of per-page LOW severity flags
(UNCLASSIFIED_PAGE, LOW_OCR_CONFIDENCE, UNREADABLE_PAGE). Operations teams
need a short actionable list, not one row per scanned page.
"""

from __future__ import annotations

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

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
