"""Persistence helpers for document verification reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from database.db import get_connection
from database.models import DocumentVerificationReport


def save_verification_report(application_id: int, report: DocumentVerificationReport) -> None:
    """Store the latest verification report for an application."""
    payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO document_verification_reports (
                application_id,
                report_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(application_id) DO UPDATE SET
                report_json = excluded.report_json,
                updated_at = excluded.updated_at
            """,
            (application_id, payload, now, now),
        )


def load_verification_report(application_id: int) -> DocumentVerificationReport | None:
    """Load the latest verification report for an application, if present."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT report_json
            FROM document_verification_reports
            WHERE application_id = ?
            """,
            (application_id,),
        ).fetchone()

    if row is None:
        return None
    payload = json.loads(str(row["report_json"]))
    return DocumentVerificationReport.model_validate(payload)
