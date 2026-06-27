"""Exception aggregator.

Merges exception lists from multiple evaluation passes into a single,
deduplicated, priority-sorted list ready for the report generator.
"""

from __future__ import annotations

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


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
