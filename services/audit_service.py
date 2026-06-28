"""Audit service.

Records every significant action performed on an application into the
audit_log table in SQLite. Provides an immutable trail for compliance.

Actions to record (examples):
  - "file_uploaded"
  - "partner_json_received"
  - "checklist_evaluated"
  - "report_generated"
  - "decision_overridden"
"""

from __future__ import annotations

from datetime import datetime, timezone

from database.db import get_connection


def record_audit_event(
    action: str,
    application_id: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """Insert an audit event into the database and return the recorded row.

    Args:
        action:         Short action label (see module docstring examples).
        application_id: Optional FK to the applications table.
        metadata:       Arbitrary JSON-serialisable metadata dict.

    Returns:
        Dict representation of the inserted audit event.
    """
    import json

    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata or {})

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_log (application_id, action, metadata, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (application_id, action, meta_json, now),
        )
        row_id = cursor.lastrowid

    return {
        "id": row_id,
        "application_id": application_id,
        "action": action,
        "metadata": metadata or {},
        "created_at": now,
    }
