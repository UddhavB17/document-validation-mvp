"""Build checklist anomaly dicts."""

from __future__ import annotations

from datetime import datetime


def build_anomaly(
    rule_id: str,
    s_no: int | None,
    severity: str,
    expected_value: object,
    found_value: object,
    reason: str,
    page_number: int | None = None,
    document_type: str | None = None,
    person_id: str | None = None,
) -> dict:
    return {
        "rule_id": rule_id,
        "s_no": s_no,
        "severity": severity,
        "document_type": document_type,
        "expected_value": expected_value,
        "found_value": found_value,
        "page_number": page_number,
        "person_id": person_id,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
