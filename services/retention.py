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
from services.db_archive import applications_missing_archive, export_application_archive
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

#: Source-like purposes that are deleted once their application is archived
#: (and no non-terminal job still needs them). ``ocr_export`` rows expire on
#: their own age (``DMEF_RETENTION_EXPORT_DAYS``); ``report`` rows are
#: reviewer data and are never deleted here.
SOURCE_PURPOSES = ("source", "manifest", "normalized_pdf")

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


def _parse_ts(raw: Any) -> datetime | None:
    """Parse a stored timestamp in either retention format.

    Retention writes space-separated UTC (``_cutoff_text``) while
    ``record_ref`` writes ISO-8601; both must compare correctly. ``None``
    means unparseable — callers keep such rows instead of deleting them.
    """
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _active_job_guard(table_exists: bool) -> str:
    """SQL fragment excluding applications with resumable (non-terminal) jobs.

    ``queued/running/retrying/paused/stale/cancelled`` jobs may resume, so
    their application's source objects are never deletion candidates.
    """
    if not table_exists:
        return ""
    return (
        " AND NOT EXISTS (SELECT 1 FROM pipeline_jobs j"
        " WHERE j.application_id = applications.id"
        " AND j.status NOT IN ('completed','failed'))"
    )


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


def run_retention(now: Any = None, dry_run: bool = True) -> dict:
    """Delete expired rows/files per the retention budgets.

    Returns counts per action. With ``dry_run=True`` nothing is deleted and
    no application is marked archived.
    """
    moment = _resolve_now(now)
    max_attempts = get_int("DMEF_RETENTION_JOB_ATTEMPTS", 3, minimum=1)
    telemetry_days = get_int("DMEF_RETENTION_TELEMETRY_DAYS", 30, minimum=1)
    source_days = get_int("DMEF_RETENTION_SOURCE_DAYS", 60, minimum=1)
    export_days = get_int("DMEF_RETENTION_EXPORT_DAYS", 7, minimum=1)
    telemetry_cutoff = _cutoff_text(moment - timedelta(days=telemetry_days))
    source_cutoff = _cutoff_text(moment - timedelta(days=source_days))
    export_cutoff = moment - timedelta(days=export_days)
    archived_at = _cutoff_text(moment)

    result: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "applications_db_archived": 0,
        "db_archive_bytes": 0,
        "pipeline_job_inputs_deleted": 0,
        "pipeline_jobs_deleted": 0,
        "telemetry_deleted": {"ocr_route_events": 0, "classification_review_log": 0},
        "audit_log_deleted": 0,
        "applications_archived": 0,
        "source_keys_deleted": 0,
        "ocr_exports_deleted": 0,
    }

    # 0. Database archive first: snapshot each archivable application without
    # a db_archive export into the object store BEFORE any pruning below
    # deletes job inputs, telemetry, or source blobs. Failures are skipped
    # (the next run backfills them); reports and db_archive exports are
    # never deletion candidates in the steps that follow.
    try:
        archive_candidates = applications_missing_archive()
    except Exception:  # noqa: BLE001 - archiving is best-effort; pruning proceeds
        archive_candidates = []
    if dry_run:
        result["applications_db_archived"] = len(archive_candidates)
    else:
        archived_bytes = 0
        for application_id in archive_candidates:
            try:
                exported = export_application_archive(application_id)
            except Exception:  # noqa: BLE001 - row kept missing so next run retries
                continue
            if not exported.get("reused"):
                result["applications_db_archived"] += 1
                archived_bytes += int(exported.get("size_bytes") or 0)
        result["db_archive_bytes"] = archived_bytes

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

        # 6. Collect (real run) or count (dry-run) archived source keys via
        # object_refs. Only source-like purposes of archived applications
        # with no resumable job are candidates; failed store deletions keep
        # their row so the next run retries them, while successful deletions
        # remove the row (idempotent subsequent runs). Dry-run counts both
        # not-yet-archived candidates and already-archived retry leftovers.
        # --- fx-schema: object_refs lookup with IN (SELECT ...) ---
        source_candidates: list[dict[str, Any]] = []
        has_refs = _table_exists(connection, "object_refs")
        has_packages = _table_exists(connection, "intake_packages")
        has_jobs = _table_exists(connection, "pipeline_jobs")
        if has_refs and has_archived_col:
            job_guard = _active_job_guard(has_jobs)
            purposes = ",".join("?" for _ in SOURCE_PURPOSES)
            app_filter_new = (
                "SELECT CAST(id AS TEXT) FROM applications "
                "WHERE (archived_at IS NOT NULL"
                " OR (created_at < ? AND archived_at IS NULL))"
                f"{job_guard}"
            )
            count_sql = (
                "SELECT COUNT(*) AS count FROM object_refs WHERE purpose IN "
                f"({purposes}) AND ((owner_table = 'applications' AND owner_id IN "
                f"({app_filter_new}))"
            )
            collect_sql = (
                "SELECT id, storage_key FROM object_refs WHERE purpose IN "
                f"({purposes}) AND ((owner_table = 'applications' AND owner_id IN "
                "(SELECT CAST(id AS TEXT) FROM applications "
                f"WHERE archived_at IS NOT NULL{job_guard}))"
            )
            if has_packages:
                count_sql += (
                    " OR (owner_table = 'intake_packages' AND owner_id IN "
                    "(SELECT package_id FROM intake_packages WHERE application_id IN "
                    f"(SELECT id FROM applications WHERE (archived_at IS NOT NULL OR "
                    "(created_at < ? AND archived_at IS NULL))"
                    f"{job_guard})))"
                )
                collect_sql += (
                    " OR (owner_table = 'intake_packages' AND owner_id IN "
                    "(SELECT package_id FROM intake_packages WHERE application_id IN "
                    "(SELECT id FROM applications "
                    f"WHERE archived_at IS NOT NULL{job_guard})))"
                )
            count_sql += ")"
            collect_sql += ")"
            if dry_run:
                params: tuple[Any, ...] = (
                    (*SOURCE_PURPOSES, source_cutoff)
                    + ((source_cutoff,) if has_packages else ())
                )
                row = connection.execute(count_sql, params).fetchone()
                result["source_keys_deleted"] = int(row["count"])
            else:
                rows = connection.execute(
                    collect_sql, tuple(SOURCE_PURPOSES)
                ).fetchall()
                for key_row in rows:
                    key = key_row["storage_key"]
                    if (
                        isinstance(key, str)
                        and key
                        and not key.startswith("/")
                        and ".." not in key
                    ):
                        source_candidates.append(
                            {"id": key_row["id"], "storage_key": key}
                        )

        # 7. OCR-export expiry (DMEF_RETENTION_EXPORT_DAYS). Exports are
        # regenerable on demand; any ocr_export ref older than the window is
        # deleted regardless of application age. Age is compared in Python
        # because refs are written in ISO-8601 (record_ref) as well as the
        # space-separated retention format. Regenerating an export refreshes
        # its row (record_ref updates created_at), restarting the window.
        export_candidates: list[dict[str, Any]] = []
        if has_refs:
            export_rows = connection.execute(
                "SELECT id, storage_key, created_at FROM object_refs "
                "WHERE purpose = ?",
                ("ocr_export",),
            ).fetchall()
            for export_row in export_rows:
                created = _parse_ts(export_row["created_at"])
                if created is None or created >= export_cutoff:
                    continue
                key = export_row["storage_key"]
                if (
                    isinstance(key, str)
                    and key
                    and not key.startswith("/")
                    and ".." not in key
                ):
                    export_candidates.append(
                        {"id": export_row["id"], "storage_key": key}
                    )
            if dry_run:
                result["ocr_exports_deleted"] = len(export_candidates)

    if dry_run:
        return result

    store = get_store()
    sources_deleted = 0
    for candidate in source_candidates:
        try:
            store.delete(candidate["storage_key"])
        except Exception:  # noqa: BLE001 - row kept so a later run retries
            continue
        with get_connection() as cleanup:
            cleanup.execute(
                "DELETE FROM object_refs WHERE id = ?", (candidate["id"],)
            )
        sources_deleted += 1
    result["source_keys_deleted"] = sources_deleted

    exports_deleted = 0
    for candidate in export_candidates:
        try:
            store.delete(candidate["storage_key"])
        except Exception:  # noqa: BLE001 - row kept so a later run retries
            continue
        with get_connection() as cleanup:
            cleanup.execute(
                "DELETE FROM object_refs WHERE id = ?", (candidate["id"],)
            )
        exports_deleted += 1
    result["ocr_exports_deleted"] = exports_deleted
    return result
