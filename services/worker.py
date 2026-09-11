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


def _claim_select_sql(job_id: int | None = None) -> str:
    """Return the dialect-branched dequeue SELECT (contracts §4).

    Postgres uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers never
    claim the same row; SQLite uses the same query without the clause inside
    ``BEGIN IMMEDIATE``.
    """
    import database.db as db_module

    base = """
            SELECT id, application_id, job_type, status, attempt, max_attempts,
                   batch_id, control_state
            FROM pipeline_jobs
            WHERE status IN ('queued', 'retrying')
              AND (next_run_at IS NULL OR next_run_at <= ?)
            """
    if job_id is not None:
        base += " AND id = ? AND control_state = 'running'"
    base += " ORDER BY id LIMIT 1"
    if db_module.dialect() == "postgresql":
        return base + " FOR UPDATE SKIP LOCKED"
    return base


def recover_stale_jobs(*, stale_minutes: int = 10) -> int:
    """Move crashed ``running`` jobs back to ``retrying`` without bumping attempt.

    Jobs that already exhausted ``max_attempts`` are marked ``failed`` (with
    the application/intake mirrored) so the next claim does not grant a run
    beyond the budget.
    """
    cutoff = (_utc_now() - timedelta(minutes=stale_minutes)).isoformat()
    now_iso = _utc_now_iso()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, application_id, attempt, max_attempts
            FROM pipeline_jobs
            WHERE status = 'running' AND (heartbeat_at IS NULL OR heartbeat_at < ?)
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            attempt = int(row["attempt"] or 0)
            max_attempts = int(row["max_attempts"] or 3)
            if attempt >= max_attempts:
                reason = "Processing failed after 3 attempts. Contact an administrator."
                connection.execute(
                    """
                    UPDATE pipeline_jobs
                    SET status = 'failed', control_state = 'failed',
                        error = ?, failure_reason = ?,
                        completed_at = ?, heartbeat_at = ?
                    WHERE id = ?
                    """,
                    (
                        "Worker heartbeat expired after exhausting attempts",
                        reason,
                        now_iso,
                        now_iso,
                        row["id"],
                    ),
                )
                connection.execute(
                    "UPDATE applications SET status = ? WHERE id = ?",
                    ("failed", int(row["application_id"])),
                )
                try:
                    connection.execute(
                        """
                        UPDATE pipeline_progress
                        SET status = 'failed', stage = 'failed', error = ?,
                            message = ?, completed_at = ?, updated_at = ?
                        WHERE application_id = ?
                        """,
                        (
                            reason,
                            reason,
                            now_iso,
                            now_iso,
                            int(row["application_id"]),
                        ),
                    )
                except Exception:
                    pass
                try:
                    connection.execute(
                        "UPDATE intake_packages SET status = 'failed' WHERE application_id = ?",
                        (int(row["application_id"]),),
                    )
                except Exception:
                    pass
                connection.execute(
                    "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
                    (int(row["application_id"]), "pipeline_failed", reason),
                )
            else:
                connection.execute(
                    """
                    UPDATE pipeline_jobs
                    SET status = 'retrying', control_state = 'running', next_run_at = NULL
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
        return len(rows)


def claim_next_job(job_id: int | None = None) -> dict[str, Any] | None:
    """Claim one queued/retrying job that is due. Returns the job row or None."""
    import database.db as db_module

    now_iso = _utc_now_iso()
    is_postgres = db_module.dialect() == "postgresql"
    with get_connection() as connection:
        if not is_postgres:
            # SQLite: serialize claims. Postgres uses FOR UPDATE SKIP LOCKED
            # instead (see _claim_select_sql); never run BEGIN IMMEDIATE there.
            connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            _claim_select_sql(job_id),
            (now_iso,) if job_id is None else (now_iso, job_id),
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
        _touch_idle_heartbeat()


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
            # even when job_type was left as the default. Execute exactly one
            # runner per claim: a pipeline exception belongs to the retry
            # policy, not a second immediate run through a different runner.
            from services.job_control import load_job_input

            stored = load_job_input(int(job["application_id"]), job_id)
            if isinstance(stored.get("mapped_manifest"), dict):
                pipeline_tasks.run_mapped_job(job_id)
            else:
                pipeline_tasks.run_pipeline_job(job_id)
    except PipelineCancelled:
        return
    except Exception as exc:  # noqa: BLE001
        handle_job_exception(job_id, exc)
    finally:
        stop_event.set()
        from services.pipeline.input_preparation import cleanup_job_source, job_source_dir

        cleanup_job_source(job_source_dir(job_id))


def handle_job_exception(job_id: int, exc: BaseException) -> None:
    from services.job_control import PipelineCancelled, PipelineFailedError

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
    # Clean pipeline failures are terminal: never retry, mark failed once.
    is_terminal = isinstance(exc, PipelineFailedError)
    if not is_terminal and attempt < max_attempts:
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


def _default_poll_seconds() -> float:
    """Poll interval from ``DMEF_WORKER_POLL_SECONDS`` (contracts §7)."""
    try:
        from services.config import get_float
    except Exception:
        return 2.0
    try:
        return float(get_float("DMEF_WORKER_POLL_SECONDS", 2.0, minimum=0.1))
    except Exception:
        return 2.0


def _touch_idle_heartbeat() -> None:
    """Update the singleton worker heartbeat row. Never raises."""
    try:
        from database.worker_heartbeat import update_heartbeat

        update_heartbeat(WORKER_ID)
    except Exception:
        return


def start_health_server(port: int):
    """Start a minimal ``GET /health`` server for Cloud Run probes.

    Returns the ``HTTPServer`` instance (already serving on a daemon
    thread). Only answers ``GET /health`` with the worker heartbeat JSON;
    every other path is 404. Never raises: on bind failure returns None.
    """
    import json
    from http.server import BaseHTTPRequestHandler, HTTPServer

    def _payload() -> dict:
        try:
            from database.worker_heartbeat import get_heartbeat

            heartbeat = get_heartbeat()
        except Exception:
            heartbeat = {"last_heartbeat": None, "status": "stale"}
        return {
            "status": "ok",
            "worker_id": WORKER_ID,
            "worker": heartbeat,
        }

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path != "/health":
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"not_found"}')
                return
            body = json.dumps(_payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    try:
        server = HTTPServer(("0.0.0.0", int(port)), _Handler)
    except Exception:
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def run_worker(
    poll_seconds: float | None = None, once: bool = False, job_id: int | None = None
) -> None:
    """Claim → run → finalize loop. ``once`` processes a single job."""
    global _shutdown_requested
    try:
        signal.signal(signal.SIGTERM, request_shutdown)
    except (ValueError, OSError):
        pass
    effective_poll = (
        float(poll_seconds) if poll_seconds is not None else _default_poll_seconds()
    )
    if job_id is not None:
        # An explicitly scoped worker must never recover or dequeue other jobs.
        # Claims still use the same transaction/row lock as the regular worker.
        while not _shutdown_requested:
            job = claim_next_job(job_id)
            if job is not None:
                run_job_by_id(job)
                if once:
                    return
            with get_connection() as connection:
                state = connection.execute(
                    "SELECT status, control_state FROM pipeline_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
            if (
                state is None
                or state["status"] not in {"queued", "retrying"}
                or state["control_state"] != "running"
                or once
            ):
                return
            time.sleep(effective_poll)
        return
    recover_stale_jobs()
    _touch_idle_heartbeat()
    last_idle_touch = time.monotonic()
    if once:
        process_once()
        return
    while not _shutdown_requested:
        claimed = process_once()
        if _shutdown_requested:
            break
        # Dedicated heartbeat every 30 s even when idle (ws-j).
        now = time.monotonic()
        if claimed:
            _touch_idle_heartbeat()
            last_idle_touch = now
        elif now - last_idle_touch >= 30.0:
            _touch_idle_heartbeat()
            last_idle_touch = now
        if not claimed:
            time.sleep(effective_poll)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="DMEF durable pipeline worker")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument(
        "--job-id", type=int, default=None,
        help="Process only this queued job and its retries; skip global stale recovery",
    )
    parser.add_argument(
        "--serve-health",
        type=int,
        default=None,
        metavar="PORT",
        help="Start a minimal GET /health server for Cloud Run probes",
    )
    args = parser.parse_args()
    if args.serve_health is not None:
        start_health_server(args.serve_health)
    run_worker(
        poll_seconds=args.poll_seconds
        if args.poll_seconds is not None
        else _default_poll_seconds(),
        once=args.once,
        job_id=args.job_id,
    )


if __name__ == "__main__":
    main()
