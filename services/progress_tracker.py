"""Helpers for persistent pipeline progress tracking."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from database.db import get_connection


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
) -> None:
    now = _utc_now_iso()
    with get_connection() as connection:
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
    if row is None:
        return None

    payload = dict(row)
    eta_seconds = _estimate_eta_seconds(payload)
    payload["eta_seconds"] = eta_seconds
    payload["last_processed_page"] = payload.pop("current_page")
    payload["progress_text"] = f"{payload['processed_pages']}/{payload['total_pages']} pages processed"
    payload["pipeline_outcome"] = payload["status"]
    return payload


def create_pipeline_job(application_id: int, job_type: str = "pdf_pipeline") -> int:
    now = _utc_now_iso()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO pipeline_jobs (application_id, job_type, status, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (application_id, job_type, "queued", now),
        )
        return int(cursor.lastrowid)


def mark_job_started(job_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = ?, started_at = ?
            WHERE id = ?
            """,
            ("running", _utc_now_iso(), job_id),
        )


def mark_job_completed(job_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = ?, completed_at = ?
            WHERE id = ?
            """,
            ("completed", _utc_now_iso(), job_id),
        )


def mark_job_failed(job_id: int, error: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = ?, error = ?, completed_at = ?
            WHERE id = ?
            """,
            ("failed", error, _utc_now_iso(), job_id),
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
    now = datetime.now(timezone.utc)
    elapsed_seconds = max(1.0, (now - started).total_seconds())
    seconds_per_page = elapsed_seconds / processed_pages
    remaining_pages = max(0, total_pages - processed_pages)
    return int(round(seconds_per_page * remaining_pages))
