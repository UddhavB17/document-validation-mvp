"""Worker heartbeat table (owned by ``ws-j-deploy-smoke``).

One row (``id = 1``) updated by the worker loop every 30 s even when idle
(contracts §1 dialect-neutral: ISO timestamps from Python, ``?``
placeholders, ``ON CONFLICT`` upsert). ``main.py`` ``/health`` and
``routes/admin_ops.py`` read it; when the table is empty they fall back to
``MAX(pipeline_jobs.heartbeat_at)``. Registered through the schema registry
(contracts §3); the Postgres DDL lives in
``alembic/versions/0002_worker_heartbeat.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database import schema_registry

WORKER_HEARTBEAT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS worker_heartbeat (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        worker_id TEXT,
        heartbeat_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]

schema_registry.register(WORKER_HEARTBEAT_STATEMENTS)

#: Heartbeat older than this is reported as ``stale`` by ``/health``.
STALE_AFTER_SECONDS = 120


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def update_heartbeat(worker_id: str, now_iso: str | None = None) -> None:
    """Upsert the singleton heartbeat row. Never raises."""
    try:
        from database.db import get_connection

        stamp = now_iso or _utc_now_iso()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO worker_heartbeat (id, worker_id, heartbeat_at, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    heartbeat_at = excluded.heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (worker_id, stamp, stamp),
            )
    except Exception:
        # Heartbeat must never break the worker loop or health checks.
        return


def _parse_stamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def get_heartbeat() -> dict[str, Any]:
    """Return ``{"last_heartbeat": iso|None, "status": "ok|stale"}``.

    Prefers the dedicated ``worker_heartbeat`` row; falls back to
    ``MAX(pipeline_jobs.heartbeat_at)`` on legacy databases. Missing table
    or empty data reports ``stale`` with ``last_heartbeat`` ``None``.
    """
    last: str | None = None
    try:
        from database.db import get_connection

        with get_connection() as connection:
            try:
                row = connection.execute(
                    "SELECT heartbeat_at FROM worker_heartbeat WHERE id = ?",
                    (1,),
                ).fetchone()
                if row is not None and row["heartbeat_at"]:
                    last = str(row["heartbeat_at"])
            except Exception:
                last = None
            if last is None:
                try:
                    fallback = connection.execute(
                        "SELECT MAX(heartbeat_at) AS last_heartbeat FROM pipeline_jobs"
                    ).fetchone()
                    if fallback is not None and fallback["last_heartbeat"]:
                        last = str(fallback["last_heartbeat"])
                except Exception:
                    last = None
    except Exception:
        last = None
    if last is None:
        return {"last_heartbeat": None, "status": "stale"}
    parsed = _parse_stamp(last)
    if parsed is None:
        return {"last_heartbeat": last, "status": "stale"}
    age = (datetime.now(UTC) - parsed).total_seconds()
    if age < 0:
        age = 0
    status = "ok" if age <= STALE_AFTER_SECONDS else "stale"
    return {"last_heartbeat": last, "status": status}
