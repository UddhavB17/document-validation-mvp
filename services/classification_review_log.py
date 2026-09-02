"""Structured capture of low-confidence and confused classification cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from database.db import get_connection


def log_classification_review_event(
    *,
    application_id: int | None,
    page_number: int,
    predicted_type: str,
    confidence: float,
    reason: str,
    anchor_match_results: dict[str, Any] | None = None,
    llm_document_type: str | None = None,
) -> None:
    """Persist one classification case for later confusion-set review."""
    if application_id is None:
        return

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO classification_review_log (
                application_id,
                page_number,
                predicted_type,
                confidence,
                reason,
                anchor_match_results,
                llm_document_type,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                page_number,
                predicted_type,
                confidence,
                reason,
                json.dumps(anchor_match_results or {}, ensure_ascii=False),
                llm_document_type,
                datetime.now(UTC).isoformat(),
            ),
        )
