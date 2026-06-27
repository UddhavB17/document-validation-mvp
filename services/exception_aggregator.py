"""Aggregate validation exceptions into reviewer-ready output."""


def aggregate_exceptions(*exception_groups: list[dict]) -> list[dict]:
    aggregated: list[dict] = []
    for group in exception_groups:
        aggregated.extend(group)
    return aggregated
