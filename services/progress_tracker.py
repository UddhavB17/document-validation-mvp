"""Helpers for persistent pipeline progress tracking."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from database.db import get_connection
from services.config import get_int

ACTIVE_PROGRESS_STATES = frozenset({"queued", "processing", "pause_requested"})
RETRYABLE_PROGRESS_STATES = frozenset(
    {"stale", "failed", "cancelled", "paused", "completed_with_warnings"}
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _audit(application_id: int, action: str, details: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (application_id, action, json.dumps(details)),
        )


def start_tracking(
    application_id: int,
    *,
    total_pages: int,
    digital_pages: int = 0,
    scanned_pages: int = 0,
    stage: str = "queued",
    message: str | None = None,
    resume: bool = False,
) -> None:
    now = _utc_now_iso()
    with get_connection() as connection:
        if resume:
            connection.execute(
                """
                UPDATE pipeline_progress
                SET stage = ?, total_pages = ?, digital_pages = ?, scanned_pages = ?,
                    status = 'processing', message = ?, error = NULL, completed_at = NULL,
                    updated_at = ?
                WHERE application_id = ?
                """,
                (
                    stage,
                    total_pages,
                    digital_pages,
                    scanned_pages,
                    message,
                    now,
                    application_id,
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO pipeline_progress (
                application_id,
                stage,
                total_pages,
                digital_pages,
                scanned_pages,
                processed_pages,
                current_page,
                percentage,
                status,
                message,
                started_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(application_id) DO UPDATE SET
                stage = excluded.stage,
                total_pages = excluded.total_pages,
                digital_pages = excluded.digital_pages,
                scanned_pages = excluded.scanned_pages,
                processed_pages = excluded.processed_pages,
                current_page = excluded.current_page,
                percentage = excluded.percentage,
                status = excluded.status,
                message = excluded.message,
                started_at = excluded.started_at,
                updated_at = excluded.updated_at,
                completed_at = NULL,
                error = NULL
            """,
            (
                application_id,
                stage,
                total_pages,
                digital_pages,
                scanned_pages,
                0,
                None,
                0.0,
                "processing",
                message,
                now,
                now,
            ),
        )
        connection.execute(
            "DELETE FROM pipeline_page_events WHERE application_id = ?", (application_id,)
        )


def update_stage(application_id: int, stage: str, message: str | None = None) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_progress
            SET stage = ?, message = ?, updated_at = ?
            WHERE application_id = ?
            """,
            (stage, message, _utc_now_iso(), application_id),
        )
    _audit(application_id, "pipeline_stage_changed", {"stage": stage, "message": message})


def touch_progress(application_id: int, message: str | None = None) -> None:
    """Refresh updated_at so long-running stages are not marked stale."""
    with get_connection() as connection:
        if message is None:
            connection.execute(
                """
                UPDATE pipeline_progress
                SET updated_at = ?
                WHERE application_id = ?
                """,
                (_utc_now_iso(), application_id),
            )
        else:
            connection.execute(
                """
                UPDATE pipeline_progress
                SET message = ?, updated_at = ?
                WHERE application_id = ?
                """,
                (message, _utc_now_iso(), application_id),
            )


def update_page_progress(
    application_id: int,
    *,
    processed_pages: int,
    total_pages: int,
    current_page: int | None = None,
    message: str | None = None,
) -> None:
    percentage = round((processed_pages / total_pages) * 100, 2) if total_pages > 0 else 100.0
    progress_message = message or f"Processed {processed_pages}/{total_pages} pages"
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_progress
            SET stage = ?,
                processed_pages = ?,
                total_pages = ?,
                current_page = ?,
                percentage = ?,
                status = ?,
                message = ?,
                updated_at = ?
            WHERE application_id = ?
            """,
            (
                "processing_pages",
                processed_pages,
                total_pages,
                current_page,
                percentage,
                "processing",
                progress_message,
                _utc_now_iso(),
                application_id,
            ),
        )


def record_page_completed(
    application_id: int,
    *,
    page_number: int,
    total_pages: int,
    page_type: str | None,
    document_type: str | None,
    elapsed_seconds: float | None,
    extracted_fields: dict[str, Any] | None = None,
    status: str = "completed",
    error: str | None = None,
) -> None:
    # ``extracted_fields`` is accepted for caller compatibility but never
    # persisted: page events carry status/timing only (ws-a data diet). The
    # argument is intentionally ignored.
    _ = extracted_fields
    completed_at = _utc_now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_page_events (
                application_id,
                page_number,
                total_pages,
                page_type,
                document_type,
                status,
                elapsed_seconds,
                error,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(application_id, page_number) DO UPDATE SET
                total_pages = excluded.total_pages,
                page_type = excluded.page_type,
                document_type = excluded.document_type,
                status = excluded.status,
                elapsed_seconds = excluded.elapsed_seconds,
                error = excluded.error,
                completed_at = excluded.completed_at
            """,
            (
                application_id,
                page_number,
                total_pages,
                page_type,
                document_type,
                status,
                elapsed_seconds,
                error,
                completed_at,
            ),
        )


def mark_page_started(
    application_id: int,
    *,
    current_page: int,
    total_pages: int,
    message: str | None = None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_progress
            SET stage = ?,
                current_page = ?,
                total_pages = ?,
                status = ?,
                message = ?,
                updated_at = ?
            WHERE application_id = ?
            """,
            (
                "processing_pages",
                current_page,
                total_pages,
                "processing",
                message or f"Working on page {current_page}; processed count unchanged",
                _utc_now_iso(),
                application_id,
            ),
        )


def mark_completed(application_id: int, final_status: str, outcome: str = "completed") -> None:
    now = _utc_now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_progress
            SET stage = ?,
                status = ?,
                processed_pages = total_pages,
                percentage = 100.0,
                message = ?,
                completed_at = ?,
                updated_at = ?
            WHERE application_id = ?
            """,
            (
                "completed",
                outcome,
                f"Pipeline finished with status {final_status} ({outcome})",
                now,
                now,
                application_id,
            ),
        )
    _audit(application_id, "pipeline_completed", {"final_status": final_status, "outcome": outcome})


def mark_failed(application_id: int, error: str) -> None:
    now = _utc_now_iso()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_progress
            SET stage = ?,
                status = ?,
                error = ?,
                message = ?,
                completed_at = ?,
                updated_at = ?
            WHERE application_id = ?
            """,
            ("failed", "failed", error, "Pipeline failed", now, now, application_id),
        )


def get_progress(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT application_id, stage, total_pages, digital_pages, scanned_pages,
                   processed_pages, current_page, percentage, status, message, error,
                   started_at, updated_at, completed_at
            FROM pipeline_progress
            WHERE application_id = ?
            """,
            (application_id,),
        ).fetchone()
        page_rows = connection.execute(
            """
            SELECT page_number, total_pages, page_type, document_type, status,
                    elapsed_seconds, error, completed_at
            FROM pipeline_page_events
            WHERE application_id = ?
            ORDER BY page_number
            """,
            (application_id,),
        ).fetchall()
    if row is None:
        return None

    payload = dict(row)
    completed_pages = [dict(page_row) for page_row in page_rows]
    operational_status = operational_progress_status(payload)
    eta_seconds = _estimate_eta_seconds({**payload, "status": operational_status})
    payload["eta_seconds"] = eta_seconds
    payload["last_processed_page"] = payload.pop("current_page")
    payload["progress_text"] = (
        f"{payload['processed_pages']}/{payload['total_pages']} pages processed"
    )
    payload["pipeline_outcome"] = payload["status"]
    payload["operational_status"] = operational_status
    payload["is_stale"] = operational_status == "stale"
    payload["retryable"] = operational_status in RETRYABLE_PROGRESS_STATES
    payload["completed_pages"] = completed_pages
    return payload


def operational_progress_status(progress: dict[str, Any] | None) -> str:
    """Return a reviewer-friendly pipeline state, including stale detection."""
    if not progress:
        return "not_started"
    status = str(progress.get("status") or "queued").lower()
    if status == "partial_failed":
        return "completed_with_warnings"
    if status in {"completed", "failed", "paused", "cancelled"}:
        return status
    if status in ACTIVE_PROGRESS_STATES and _is_stale_timestamp(progress.get("updated_at")):
        return "stale"
    if status in ACTIVE_PROGRESS_STATES:
        return status
    return status


def _is_stale_timestamp(value: Any) -> bool:
    if not value:
        return False
    try:
        updated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    stale_minutes = get_int("DMEF_STALE_JOB_MINUTES", 30, minimum=1)
    return (datetime.now(UTC) - updated).total_seconds() > stale_minutes * 60


def create_pipeline_job(
    application_id: int,
    job_type: str = "pdf_pipeline",
    *,
    parent_job_id: int | None = None,
) -> int:
    now = _utc_now_iso()
    with get_connection() as connection:
        attempt = int(
            connection.execute(
                "SELECT COALESCE(MAX(attempt), 0) + 1 FROM pipeline_jobs WHERE application_id = ?",
                (application_id,),
            ).fetchone()[0]
        )
        cursor = connection.execute(
            """
            INSERT INTO pipeline_jobs (
                application_id, job_type, status, control_state, attempt,
                parent_job_id, heartbeat_at, created_at
            )
            VALUES (?, ?, 'queued', 'running', ?, ?, ?, ?)
            RETURNING id
            """,
            (application_id, job_type, attempt, parent_job_id, now, now),
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("Failed to create pipeline job")
        return int(created["id"])


def mark_job_started(job_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = CASE
                    WHEN control_state = 'pause_requested' THEN 'pause_requested'
                    WHEN control_state = 'cancel_requested' THEN 'cancel_requested'
                    ELSE 'running'
                END,
                started_at = ?, heartbeat_at = ?
            WHERE id = ?
            """,
            (_utc_now_iso(), _utc_now_iso(), job_id),
        )


def mark_job_completed(job_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = ?, control_state = 'completed', completed_at = ?, heartbeat_at = ?
            WHERE id = ?
            """,
            ("completed", _utc_now_iso(), _utc_now_iso(), job_id),
        )


def mark_job_failed(job_id: int, error: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = ?, control_state = 'failed', error = ?, completed_at = ?, heartbeat_at = ?
            WHERE id = ?
            """,
            ("failed", error, _utc_now_iso(), _utc_now_iso(), job_id),
        )


def _estimate_eta_seconds(progress: dict[str, Any]) -> int | None:
    if progress.get("status") != "processing":
        return 0
    processed_pages = int(progress.get("processed_pages") or 0)
    total_pages = int(progress.get("total_pages") or 0)
    started_at = progress.get("started_at")
    if processed_pages <= 0 or total_pages <= 0 or not started_at:
        return None

    try:
        started = datetime.fromisoformat(str(started_at))
    except ValueError:
        return None
    now = datetime.now(UTC)
    elapsed_seconds = max(1.0, (now - started).total_seconds())
    seconds_per_page = elapsed_seconds / processed_pages
    remaining_pages = max(0, total_pages - processed_pages)
    return int(round(seconds_per_page * remaining_pages))
