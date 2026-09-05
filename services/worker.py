"""Separate worker process that claims durable pipeline jobs one at a time."""

from __future__ import annotations

import signal
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from database.db import get_connection

WORKER_ID = uuid.uuid4().hex[:12]
_shutdown_requested = False
BACKOFF_SECONDS = (30, 120)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def request_shutdown(*_args: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def backoff_seconds(attempt: int) -> int:
    if attempt <= 1:
        return BACKOFF_SECONDS[0]
    return BACKOFF_SECONDS[1]


def failure_reason_for(exc: BaseException) -> str:
    message = str(exc).lower()
    if "quota" in message or ("ocr" in message and "limit" in message):
        return "OCR service quota exceeded. Try again later."
    if "password" in message:
        return "File is password protected and cannot be processed."
    if "corrupt" in message or "unreadable" in message:
        return "File is corrupted or unreadable."
    if "empty" in message and "zip" in message:
        return "ZIP package is empty."
    if "empty" in message:
        return "File is empty and cannot be processed."
    if "unsupported" in message:
        return "Unsupported file type."
    if "no secure recovery payload" in message or "recovery" in message:
        return "Processing failed after 3 attempts. Contact an administrator."
    detail = str(exc).strip().split("\n")[0][:160] if str(exc).strip() else ""
    if detail:
        return f"Processing failed after 3 attempts. Contact an administrator. ({detail})"
    return "Processing failed after 3 attempts. Contact an administrator."


def recover_stale_jobs(*, stale_minutes: int = 10) -> int:
    """Move crashed ``running`` jobs back to ``retrying`` without bumping attempt."""
    cutoff = (_utc_now() - timedelta(minutes=stale_minutes)).isoformat()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id FROM pipeline_jobs
            WHERE status = 'running' AND (heartbeat_at IS NULL OR heartbeat_at < ?)
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'retrying', control_state = 'running', next_run_at = NULL
                WHERE id = ?
                """,
                (row["id"],),
            )
        return len(rows)


def claim_next_job() -> dict[str, Any] | None:
    """Claim one queued/retrying job that is due. Returns the job row or None."""
    now_iso = _utc_now_iso()
    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except Exception:
            pass
        row = connection.execute(
            """
            SELECT id, application_id, job_type, status, attempt, max_attempts,
                   batch_id, control_state
            FROM pipeline_jobs
            WHERE status IN ('queued', 'retrying')
              AND (next_run_at IS NULL OR next_run_at <= ?)
            ORDER BY id LIMIT 1
            """,
            (now_iso,),
        ).fetchone()
        if row is None:
            return None
        job_id = int(row["id"])
        # The worker_id column may not exist on older checkouts; update core fields
        # and set heartbeat. Keep attempt increment + running transition atomic.
        try:
            connection.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'running', started_at = ?, attempt = attempt + 1,
                    heartbeat_at = ?
                WHERE id = ?
                """,
                (now_iso, now_iso, job_id),
            )
        except Exception:
            # Fallback if heartbeat column is missing (should not happen).
            connection.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'running', started_at = ?, attempt = attempt + 1
                WHERE id = ?
                """,
                (now_iso, job_id),
            )
        claimed = connection.execute(
            "SELECT * FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return dict(claimed) if claimed else None


def _heartbeat_loop(job_id: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(30.0):
        try:
            with get_connection() as connection:
                connection.execute(
                    "UPDATE pipeline_jobs SET heartbeat_at = ? WHERE id = ?",
                    (_utc_now_iso(), job_id),
                )
        except Exception:
            continue


def run_job_by_id(job: dict[str, Any]) -> None:
    from services.job_control import PipelineCancelled
    from services.pipeline import tasks as pipeline_tasks

    job_id = int(job["id"])
    job_type = str(job.get("job_type") or "")
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(job_id, stop_event), daemon=True
    )
    heartbeat.start()
    try:
        if "mapped" in job_type.lower():
            pipeline_tasks.run_mapped_job(job_id)
        else:
            # Dispatch on persisted manifest so plain/mapped routing survives
            # even when job_type was left as the default.
            try:
                routed_mapped = False
                with get_connection() as connection:
                    app_row = connection.execute(
                        "SELECT application_id FROM pipeline_jobs WHERE id = ?",
                        (job_id,),
                    ).fetchone()
                if app_row is not None:
                    from services.job_control import load_job_input

                    stored = load_job_input(int(app_row["application_id"]), job_id)
                    routed_mapped = isinstance(stored.get("mapped_manifest"), dict)
                if routed_mapped:
                    pipeline_tasks.run_mapped_job(job_id)
                else:
                    pipeline_tasks.run_pipeline_job(job_id)
            except PipelineCancelled:
                raise
            except Exception as dispatch_exc:
                # If dispatch itself failed, fall back to plain runner so the
                # error surfaces through the normal retry path.
                if "No secure recovery payload" in str(dispatch_exc):
                    raise
                try:
                    pipeline_tasks.run_pipeline_job(job_id)
                except Exception:
                    raise dispatch_exc from None
    except PipelineCancelled:
        return
    except Exception as exc:  # noqa: BLE001
        handle_job_exception(job_id, exc)
    finally:
        stop_event.set()


def handle_job_exception(job_id: int, exc: BaseException) -> None:
    from services.job_control import PipelineCancelled

    if isinstance(exc, PipelineCancelled):
        return
    now_iso = _utc_now_iso()
    with get_connection() as connection:
        job = connection.execute(
            "SELECT * FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if job is None:
        return
    attempt = int(job["attempt"] or 0)
    max_attempts = int(job["max_attempts"] or 3)
    application_id = int(job["application_id"])
    error_summary = str(exc).strip().split("\n")[0][:500] if str(exc).strip() else type(exc).__name__
    if attempt < max_attempts:
        wait = backoff_seconds(attempt)
        next_run = (_utc_now() + timedelta(seconds=wait)).isoformat()
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'retrying', error = ?, next_run_at = ?, heartbeat_at = ?
                WHERE id = ?
                """,
                (error_summary, next_run, now_iso, job_id),
            )
            connection.execute(
                """
                UPDATE pipeline_progress
                SET status = 'processing', stage = 'queued',
                    message = ?, updated_at = ?
                WHERE application_id = ?
                """,
                (f"Attempt {attempt} of {max_attempts} failed; retrying", now_iso, application_id),
            )
    else:
        reason = failure_reason_for(exc)
        with get_connection() as connection:
            connection.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'failed', control_state = 'failed', error = ?,
                    failure_reason = ?, completed_at = ?, heartbeat_at = ?
                WHERE id = ?
                """,
                (error_summary, reason, now_iso, now_iso, job_id),
            )
            connection.execute(
                "UPDATE applications SET status = ? WHERE id = ?",
                ("failed", application_id),
            )
            try:
                connection.execute(
                    """
                    UPDATE pipeline_progress
                    SET status = 'failed', stage = 'failed', error = ?,
                        message = ?, completed_at = ?, updated_at = ?
                    WHERE application_id = ?
                    """,
                    (reason, reason, now_iso, now_iso, application_id),
                )
            except Exception:
                pass
            # Mirror failure onto any intake package linked to this application.
            try:
                connection.execute(
                    "UPDATE intake_packages SET status = 'failed' WHERE application_id = ?",
                    (application_id,),
                )
            except Exception:
                pass
            connection.execute(
                "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
                (application_id, "pipeline_failed", reason),
            )


def process_once() -> bool:
    job = claim_next_job()
    if job is None:
        return False
    run_job_by_id(job)
    return True


def run_worker(poll_seconds: float = 2.0, once: bool = False) -> None:
    """Claim → run → finalize loop. ``once`` processes a single job."""
    global _shutdown_requested
    try:
        signal.signal(signal.SIGTERM, request_shutdown)
    except (ValueError, OSError):
        pass
    recover_stale_jobs()
    if once:
        process_once()
        return
    while not _shutdown_requested:
        claimed = process_once()
        if _shutdown_requested:
            break
        if not claimed:
            time.sleep(poll_seconds)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="DMEF durable pipeline worker")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    run_worker(poll_seconds=args.poll_seconds, once=args.once)


if __name__ == "__main__":
    main()
