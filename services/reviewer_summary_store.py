"""Persistence for deterministic reviewer summaries."""

from __future__ import annotations

import json
from typing import Any

from database.db import get_connection


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
