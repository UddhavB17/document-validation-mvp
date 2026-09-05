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

#: Jobs in these statuses are terminal and eligible for pruning. Active jobs
#: (queued/running/retrying, plus paused/cancelled/stale) are never deleted.
TERMINAL_JOB_STATUSES = ("completed", "failed")

# --- fx-schema: stale-job subquery (terminal only, newest N kept per app) ---
_STALE_JOBS_SUBQUERY = (
    "SELECT id FROM ("
    "SELECT id, ROW_NUMBER() OVER "
    "(PARTITION BY application_id ORDER BY id DESC) AS rn "
    "FROM pipeline_jobs WHERE status IN ('completed','failed')"
    ") AS stale_ranked WHERE rn > ?"
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


def _has_column(table: str, column: str) -> bool:
    """Return True when ``table.column`` exists (probed outside the txn)."""
    try:
        with get_connection() as probe:
            probe.execute(f"SELECT {column} FROM {table} WHERE 1 = 0").fetchall()
    except Exception:  # noqa: BLE001 - legacy databases predate the column
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
        # --- fx-schema: IN (SELECT ...) avoids thousands of bound params ---
        if _table_exists(connection, "pipeline_job_inputs") and _table_exists(
            connection, "pipeline_jobs"
        ):
            if dry_run:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM pipeline_job_inputs "
                    "WHERE job_id IN (SELECT id FROM pipeline_jobs WHERE status = ?)",
                    ("completed",),
                ).fetchone()
                result["pipeline_job_inputs_deleted"] = int(row["count"])
            else:
                cursor = connection.execute(
                    "DELETE FROM pipeline_job_inputs "
                    "WHERE job_id IN (SELECT id FROM pipeline_jobs WHERE status = ?)",
                    ("completed",),
                )
                result["pipeline_job_inputs_deleted"] = int(cursor.rowcount or 0)

        # 2. Keep the newest N terminal jobs per application.
        # --- fx-schema: terminal-only filter + pre-delete FK nulling ---
        if _table_exists(connection, "pipeline_jobs"):
            stale_filter = _STALE_JOBS_SUBQUERY
            if dry_run:
                try:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM pipeline_jobs "
                        f"WHERE id IN ({stale_filter})",
                        (max_attempts,),
                    ).fetchone()
                    result["pipeline_jobs_deleted"] = int(row["count"])
                except Exception:  # noqa: BLE001 - unexpected shape; skip pruning
                    pass
            else:
                try:
                    if _has_column("pipeline_jobs", "parent_job_id"):
                        connection.execute(
                            "UPDATE pipeline_jobs SET parent_job_id = NULL "
                            f"WHERE parent_job_id IN ({stale_filter})",
                            (max_attempts,),
                        )
                    cursor = connection.execute(
                        f"DELETE FROM pipeline_jobs WHERE id IN ({stale_filter})",
                        (max_attempts,),
                    )
                    result["pipeline_jobs_deleted"] = int(cursor.rowcount or 0)
                except Exception:  # noqa: BLE001 - unexpected shape; skip pruning
                    pass

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
        has_archived_col = _has_column("applications", "archived_at")
        if _table_exists(connection, "applications") and has_archived_col:
            if dry_run:
                try:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM applications "
                        "WHERE created_at < ? AND archived_at IS NULL",
                        (source_cutoff,),
                    ).fetchone()
                    result["applications_archived"] = int(row["count"])
                except Exception:  # noqa: BLE001 - legacy table; counts stand
                    pass
            else:
                try:
                    cursor = connection.execute(
                        "UPDATE applications SET archived_at = ? "
                        "WHERE created_at < ? AND archived_at IS NULL",
                        (archived_at, source_cutoff),
                    )
                    result["applications_archived"] = int(cursor.rowcount or 0)
                except Exception:  # noqa: BLE001 - legacy table; counts stand
                    pass

        # 6. Count (dry-run) or collect (real run) archived source keys
        # via object_refs. Keys live in object_refs (owner_table/owner_id),
        # never in uploaded_files.storage_key or intake_packages.*_key.
        # --- fx-schema: object_refs lookup with IN (SELECT ...) ---
        source_keys: list[str] = []
        if _table_exists(connection, "object_refs") and has_archived_col:
            try:
                if dry_run:
                    row = connection.execute(
                        "SELECT COUNT(*) AS count FROM object_refs WHERE "
                        "(owner_table = 'applications' AND owner_id IN "
                        "(SELECT CAST(id AS TEXT) FROM applications "
                        "WHERE created_at < ? AND archived_at IS NULL)) "
                        "OR (owner_table = 'intake_packages' AND owner_id IN "
                        "(SELECT package_id FROM intake_packages WHERE application_id IN "
                        "(SELECT id FROM applications "
                        "WHERE created_at < ? AND archived_at IS NULL)))",
                        (source_cutoff, source_cutoff),
                    ).fetchone()
                    result["source_keys_deleted"] = int(row["count"])
                elif result["applications_archived"]:
                    rows = connection.execute(
                        "SELECT storage_key FROM object_refs WHERE "
                        "(owner_table = 'applications' AND owner_id IN "
                        "(SELECT CAST(id AS TEXT) FROM applications "
                        "WHERE archived_at = ?)) "
                        "OR (owner_table = 'intake_packages' AND owner_id IN "
                        "(SELECT package_id FROM intake_packages WHERE application_id IN "
                        "(SELECT id FROM applications WHERE archived_at = ?)))",
                        (archived_at, archived_at),
                    ).fetchall()
                    for key_row in rows:
                        key = key_row["storage_key"]
                        if isinstance(key, str) and key and not key.startswith("/"):
                            if ".." not in key:
                                source_keys.append(key)
            except Exception:  # noqa: BLE001 - legacy shape; no source keys
                pass

    deleted = 0
    if source_keys and not dry_run:
        store = get_store()
        for key in source_keys:
            try:
                store.delete(key)
                deleted += 1
            except Exception:  # noqa: BLE001 - best effort per key
                continue
    if not dry_run:
        result["source_keys_deleted"] = deleted
    return result
