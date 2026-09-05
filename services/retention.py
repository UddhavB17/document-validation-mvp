"""Retention job: source files, exports, telemetry (ws-a data diet).

``run_retention(now=None, dry_run=True)`` returns counts per action without
changing anything when ``dry_run`` is True. All SQL is dialect-neutral
(contracts §1): cut-off timestamps are computed in Python and compared as
``TEXT`` in ``YYYY-MM-DD HH:MM:SS`` form, matching ``CURRENT_TIMESTAMP``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from database.db import get_connection
from services.config import get_int
from services.storage import get_store

#: Audit actions that are never pruned: reviewer (user) actions kept for
#: accountability and job-lifecycle events kept for operations debugging.
#: Everything else older than ``DMEF_RETENTION_TELEMETRY_DAYS`` is telemetry.
RETAINED_AUDIT_ACTIONS = frozenset(
    {
        "reviewer_decision_made",
        "decision_undone",
        "reviewer_override",
        "manual_review_completed",
        "pipeline_started",
        "pipeline_completed",
        "pipeline_failed",
        "pipeline_stage_changed",
        "pipeline_completed_with_warnings",
        "job_paused",
        "job_resumed",
        "job_cancelled",
        "job_restarted",
        "job_failed",
        "reprocess_queued",
        "pause_requested",
        "cancel_requested",
        "resume_requested",
        "restart_requested",
    }
)


def _resolve_now(now: Any) -> datetime:
    if isinstance(now, datetime):
        resolved = now
    elif isinstance(now, str) and now.strip():
        resolved = datetime.fromisoformat(now.strip().replace("Z", "+00:00"))
    else:
        resolved = datetime.now(UTC)
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=UTC)
    return resolved


def _cutoff_text(moment: datetime) -> str:
    """Space-separated UTC timestamp, comparable with ``CURRENT_TIMESTAMP``."""
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _table_exists(connection: Any, table: str) -> bool:
    # Probe in a separate connection: on Postgres a failed statement aborts
    # the caller's transaction, so legacy-table probes must not run inside it.
    try:
        with get_connection() as probe:
            probe.execute(f"SELECT 1 FROM {table} WHERE 1 = 0").fetchall()
    except Exception:  # noqa: BLE001 - missing table on legacy databases
        return False
    return True


def _column_values(
    connection: Any, table: str, column: str, where: str, params: tuple[Any, ...]
) -> list[Any] | None:
    """Return one column's values, or ``None`` when table/column is missing.

    The probe runs in a separate connection so a missing-column error on
    Postgres does not abort the caller's transaction (and roll back its
    pending deletes). ``connection`` is kept for signature compatibility.
    """
    _ = connection
    try:
        with get_connection() as probe:
            rows = probe.execute(
                f"SELECT {column} FROM {table} WHERE {where}", params
            ).fetchall()
    except Exception:  # noqa: BLE001 - legacy databases predate diet columns
        return None
    return [row[column] for row in rows]


def run_retention(now: Any = None, dry_run: bool = True) -> dict:
    """Delete expired rows/files per the retention budgets.

    Returns counts per action. With ``dry_run=True`` nothing is deleted and
    no application is marked archived.
    """
    moment = _resolve_now(now)
    max_attempts = get_int("DMEF_RETENTION_JOB_ATTEMPTS", 3, minimum=1)
    telemetry_days = get_int("DMEF_RETENTION_TELEMETRY_DAYS", 30, minimum=1)
    source_days = get_int("DMEF_RETENTION_SOURCE_DAYS", 60, minimum=1)
    telemetry_cutoff = _cutoff_text(moment - timedelta(days=telemetry_days))
    source_cutoff = _cutoff_text(moment - timedelta(days=source_days))
    archived_at = _cutoff_text(moment)

    result: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "pipeline_job_inputs_deleted": 0,
        "pipeline_jobs_deleted": 0,
        "telemetry_deleted": {"ocr_route_events": 0, "classification_review_log": 0},
        "audit_log_deleted": 0,
        "applications_archived": 0,
        "source_keys_deleted": 0,
    }

    with get_connection() as connection:
        # 1. Inputs of completed jobs are never read again.
        if _table_exists(connection, "pipeline_job_inputs"):
            completed_ids = _column_values(
                connection, "pipeline_jobs", "id", "status = ?", ("completed",)
            )
            if completed_ids:
                placeholders = ",".join("?" for _ in completed_ids)
                if dry_run:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM pipeline_job_inputs "
                        f"WHERE job_id IN ({placeholders})",
                        tuple(completed_ids),
                    ).fetchone()
                    result["pipeline_job_inputs_deleted"] = int(row["count"])
                else:
                    cursor = connection.execute(
                        "DELETE FROM pipeline_job_inputs "
                        f"WHERE job_id IN ({placeholders})",
                        tuple(completed_ids),
                    )
                    result["pipeline_job_inputs_deleted"] = int(cursor.rowcount or 0)

        # 2. Keep the newest N jobs per application.
        if _table_exists(connection, "pipeline_jobs"):
            try:
                job_rows = connection.execute(
                    "SELECT application_id, id FROM pipeline_jobs "
                    "ORDER BY application_id ASC, id DESC"
                ).fetchall()
            except Exception:  # noqa: BLE001 - unexpected shape; skip pruning
                job_rows = []
            seen: dict[Any, int] = {}
            stale_ids: list[Any] = []
            for row in job_rows:
                application_id = row["application_id"]
                seen[application_id] = seen.get(application_id, 0) + 1
                if seen[application_id] > max_attempts:
                    stale_ids.append(row["id"])
            if stale_ids:
                result["pipeline_jobs_deleted"] = len(stale_ids)
                if not dry_run:
                    placeholders = ",".join("?" for _ in stale_ids)
                    cursor = connection.execute(
                        f"DELETE FROM pipeline_jobs WHERE id IN ({placeholders})",
                        tuple(stale_ids),
                    )
                    result["pipeline_jobs_deleted"] = int(cursor.rowcount or 0)

        # 3. Telemetry older than the telemetry window.
        for table in ("ocr_route_events", "classification_review_log"):
            if not _table_exists(connection, table):
                continue
            if dry_run:
                try:
                    row = connection.execute(
                        f"SELECT COUNT(*) AS count FROM {table} WHERE created_at < ?",
                        (telemetry_cutoff,),
                    ).fetchone()
                except Exception:  # noqa: BLE001 - unexpected shape; skip
                    continue
                result["telemetry_deleted"][table] = int(row["count"])
            else:
                try:
                    cursor = connection.execute(
                        f"DELETE FROM {table} WHERE created_at < ?",
                        (telemetry_cutoff,),
                    )
                except Exception:  # noqa: BLE001 - unexpected shape; skip
                    continue
                result["telemetry_deleted"][table] = int(cursor.rowcount or 0)

        # 4. Audit log older than the window, except retained user/job actions.
        if _table_exists(connection, "audit_log"):
            retained = sorted(RETAINED_AUDIT_ACTIONS)
            placeholders = ",".join("?" for _ in retained)
            try:
                if dry_run:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM audit_log "
                        f"WHERE timestamp < ? AND action NOT IN ({placeholders})",
                        (telemetry_cutoff, *retained),
                    ).fetchone()
                    result["audit_log_deleted"] = int(row["count"])
                else:
                    cursor = connection.execute(
                        "DELETE FROM audit_log "
                        f"WHERE timestamp < ? AND action NOT IN ({placeholders})",
                        (telemetry_cutoff, *retained),
                    )
                    result["audit_log_deleted"] = int(cursor.rowcount or 0)
            except Exception:  # noqa: BLE001 - unexpected shape; skip
                pass

        # 5. Archive applications older than the source window.
        archive_ids: list[Any] = []
        if _table_exists(connection, "applications"):
            candidates = _column_values(
                connection,
                "applications",
                "id",
                "created_at < ? AND (archived_at IS NULL)",
                (source_cutoff,),
            )
            if candidates is None:
                # Legacy table without archived_at: fall back to age only and
                # add the column lazily via the diet migration path.
                candidates = _column_values(
                    connection, "applications", "id", "created_at < ?", (source_cutoff,)
                )
            archive_ids = list(candidates or [])
            result["applications_archived"] = len(archive_ids)
            if archive_ids and not dry_run:
                placeholders = ",".join("?" for _ in archive_ids)
                try:
                    connection.execute(
                        "UPDATE applications SET archived_at = ? "
                        f"WHERE id IN ({placeholders})",
                        (archived_at, *tuple(archive_ids)),
                    )
                except Exception:  # noqa: BLE001 - legacy table; counts stand
                    pass

        # 6. Delete archived source keys from the object store (real run only).
        source_keys: list[str] = []
        if archive_ids and not dry_run:
            placeholders = ",".join("?" for _ in archive_ids)
            params = tuple(archive_ids)
            upload_keys = _column_values(
                connection,
                "uploaded_files",
                "storage_key",
                f"application_id IN ({placeholders})",
                params,
            )
            if upload_keys is None:
                upload_keys = _column_values(
                    connection,
                    "uploaded_files",
                    "file_path",
                    f"application_id IN ({placeholders})",
                    params,
                )
            package_columns = (
                "source_zip_key",
                "normalized_pdf_key",
                "source_zip_path",
                "normalized_pdf_path",
            )
            package_keys: list[Any] = []
            for column in package_columns:
                values = _column_values(
                    connection,
                    "intake_packages",
                    column,
                    f"application_id IN ({placeholders})",
                    params,
                )
                if values is None:
                    continue
                package_keys.extend(values)
            for key in list(upload_keys or []) + package_keys:
                if isinstance(key, str) and key and not key.startswith("/"):
                    if ".." not in key:
                        source_keys.append(key)

    deleted = 0
    if source_keys and not dry_run:
        store = get_store()
        for key in source_keys:
            try:
                store.delete(key)
                deleted += 1
            except Exception:  # noqa: BLE001 - best effort per key
                continue
    result["source_keys_deleted"] = deleted
    return result
