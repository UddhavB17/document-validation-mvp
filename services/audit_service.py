"""Audit logging service."""

import json

from database.db import get_connection


def log_action(application_id: int, action: str, details: dict | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (application_id, action, json.dumps(details or {})),
        )


def get_audit_trail(application_id: int) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, application_id, action, details, timestamp
            FROM audit_log
            WHERE application_id = ?
            ORDER BY timestamp ASC
            """,
            (application_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def record_audit_event(action: str, metadata: dict | None = None) -> dict:
    return {"action": action, "metadata": metadata or {}}
