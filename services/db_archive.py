"""Per-application database archive: DB rows -> object store JSON.

Neon (500 MB) holds hot text data only. Before retention prunes an old
application's rows (job inputs, telemetry, source blobs), this module
exports that application's full database footprint — findings, pages,
decisions, summaries, audit trail, job history, and object *references*
(keys and purposes, never blob bytes) — as one versioned JSON document in
the configured object store (local ``data/store`` or GCS bucket).

The archive uses purpose ``db_archive``. Like ``report``, that purpose is
never deleted by retention: it is the long-term copy other future uses
(re-training, audits, re-analysis) read back. Use
:func:`load_application_archive` to fetch and parse one back.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from database.db import get_connection
from services.config import get_int
from services.storage import get_store
from services.storage.refs import get_ref, record_ref

#: Format marker written into every archive envelope.
ARCHIVE_FORMAT = "dmef-db-archive/v1"

#: object_refs purpose for database archives. Never pruned by retention
#: (``services/retention.py`` only deletes ``SOURCE_PURPOSES`` + ``ocr_export``).
ARCHIVE_PURPOSE = "db_archive"

#: (table, filter column) pairs scoped to one application. Tables missing on
#: legacy databases are skipped, never fatal.
_ARCHIVE_TABLES: tuple[tuple[str, str], ...] = (
    ("applications", "id"),
    ("uploaded_files", "application_id"),
    ("ground_truth", "application_id"),
    ("intake_packages", "application_id"),
    ("pages", "application_id"),
    ("pages_meta", "application_id"),
    ("validation_results", "application_id"),
    ("reviewer_decisions", "application_id"),
    ("reviewer_summaries", "application_id"),
    ("document_verification_reports", "application_id"),
    ("pipeline_jobs", "application_id"),
    ("pipeline_job_inputs", "application_id"),
    ("pipeline_progress", "application_id"),
    ("pipeline_page_events", "application_id"),
    ("classification_review_log", "application_id"),
    ("audit_log", "application_id"),
    ("llm_calls", "application_id"),
)


def _table_exists(connection: Any, table: str) -> bool:
    try:
        with get_connection() as probe:
            probe.execute(f"SELECT 1 FROM {table} WHERE 1 = 0").fetchall()
    except Exception:  # noqa: BLE001 - legacy databases predate the table
        return False
    return True


def _rows_to_jsonable(rows: list[Any]) -> list[dict[str, Any]]:
    serializable: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, value in list(item.items()):
            if isinstance(value, (bytes, bytearray)):
                item[key] = bytes(value).decode("utf-8", errors="replace")
            elif isinstance(value, date):
                item[key] = value.isoformat()
        serializable.append(item)
    return serializable


def build_application_archive(application_id: int) -> dict[str, Any]:
    """Collect every database row belonging to ``application_id``.

    Returns the archive envelope (not yet persisted). Blob bytes are never
    included: ``object_refs`` rows are exported as metadata (keys, purposes,
    sizes) so a future reader knows which objects belong to the archive.
    """
    tables: dict[str, list[dict[str, Any]]] = {}
    with get_connection() as connection:
        for table, column in _ARCHIVE_TABLES:
            if not _table_exists(connection, table):
                continue
            try:
                if column == "id":
                    rows = connection.execute(
                        f"SELECT * FROM {table} WHERE id = ?", (application_id,)
                    ).fetchall()
                else:
                    rows = connection.execute(
                        f"SELECT * FROM {table} WHERE {column} = ?",
                        (application_id,),
                    ).fetchall()
            except Exception:  # noqa: BLE001 - unexpected shape; skip table
                continue
            tables[table] = _rows_to_jsonable(rows)
        # Intake documents belong to the app through their package.
        if _table_exists(connection, "intake_documents") and _table_exists(
            connection, "intake_packages"
        ):
            try:
                rows = connection.execute(
                    "SELECT d.* FROM intake_documents d "
                    "JOIN intake_packages p ON p.package_id = d.package_id "
                    "WHERE p.application_id = ?",
                    (application_id,),
                ).fetchall()
                tables["intake_documents"] = _rows_to_jsonable(rows)
            except Exception:  # noqa: BLE001 - unexpected shape; skip table
                pass
        # OCR route events carry a "app_id:page" document_id, not a column.
        if _table_exists(connection, "ocr_route_events"):
            try:
                rows = connection.execute(
                    "SELECT * FROM ocr_route_events WHERE document_id = ? OR document_id LIKE ?",
                    (str(application_id), f"{application_id}:%"),
                ).fetchall()
                tables["ocr_route_events"] = _rows_to_jsonable(rows)
            except Exception:  # noqa: BLE001 - unexpected shape; skip table
                pass
        # Object references: metadata only (storage keys + purposes + sizes).
        if _table_exists(connection, "object_refs"):
            try:
                rows = connection.execute(
                    "SELECT owner_table, owner_id, purpose, storage_key, "
                    "content_type, size_bytes, created_at FROM object_refs "
                    "WHERE (owner_table = 'applications' AND owner_id = ?) "
                    "OR (owner_table = 'intake_packages' AND owner_id IN "
                    "(SELECT package_id FROM intake_packages WHERE application_id = ?))",
                    (str(application_id), application_id),
                ).fetchall()
                tables["object_refs"] = _rows_to_jsonable(rows)
            except Exception:  # noqa: BLE001 - unexpected shape; skip table
                pass
    return {
        "format": ARCHIVE_FORMAT,
        "application_id": int(application_id),
        "exported_at": datetime.now(UTC).isoformat(),
        "tables": tables,
    }


def _archive_key(application_id: int, exported_at: str) -> str:
    stamp = exported_at.replace(":", "").replace("-", "").split(".")[0].replace("T", "-")
    return f"archives/application_{int(application_id)}/db-archive-{stamp}.json"


def export_application_archive(application_id: int, *, force: bool = False) -> dict[str, Any]:
    """Write ``application_id``'s database snapshot to the object store.

    Idempotent: when a ``db_archive`` reference already exists for the
    application it is returned unchanged unless ``force=True`` re-exports.
    Returns ``{"storage_key", "size_bytes", "tables", "reused"}``.
    """
    existing = get_ref("applications", application_id, ARCHIVE_PURPOSE)
    if existing is not None and not force:
        return {
            "storage_key": str(existing["storage_key"]),
            "size_bytes": existing.get("size_bytes"),
            "tables": {},
            "reused": True,
        }
    envelope = build_application_archive(application_id)
    payload = json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    key = _archive_key(application_id, str(envelope["exported_at"]))
    get_store().put(key, payload, "application/json")
    record_ref(
        "applications",
        application_id,
        ARCHIVE_PURPOSE,
        key,
        content_type="application/json",
        size_bytes=len(payload),
    )
    return {
        "storage_key": key,
        "size_bytes": len(payload),
        "tables": {name: len(rows) for name, rows in envelope["tables"].items()},
        "reused": False,
    }


def load_application_archive(storage_key: str) -> dict[str, Any]:
    """Fetch a previously exported archive from the object store and parse it."""
    raw = get_store().get(storage_key)
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict) or parsed.get("format") != ARCHIVE_FORMAT:
        raise ValueError(f"Not a DMEF database archive: {storage_key!r}")
    return parsed


def applications_missing_archive(limit: int = 500) -> list[int]:
    """Return application ids with no ``db_archive`` export yet.

    Covers both applications entering the archive window and already
    archived ones whose export failed on an earlier run (backfill), so a
    failed export is retried instead of silently skipped.
    """
    from services.retention import (  # deferred: retention imports this module
        _cutoff_text,
        _resolve_now,
    )

    source_days = get_int("DMEF_RETENTION_SOURCE_DAYS", 60, minimum=1)
    cutoff = _cutoff_text(_resolve_now(None) - timedelta(days=source_days))
    found: list[int] = []
    with get_connection() as connection:
        if not _table_exists(connection, "applications"):
            return found
        try:
            with get_connection() as probe:
                probe.execute("SELECT archived_at FROM applications WHERE 1 = 0").fetchall()
            has_archived_col = True
        except Exception:  # noqa: BLE001 - legacy databases predate the column
            has_archived_col = False
        window = (
            "(created_at < ? OR archived_at IS NOT NULL)" if has_archived_col else "created_at < ?"
        )
        try:
            rows = connection.execute(
                "SELECT id FROM applications "
                f"WHERE {window} AND NOT EXISTS ("
                "SELECT 1 FROM object_refs WHERE owner_table = 'applications' "
                "AND owner_id = CAST(applications.id AS TEXT) AND purpose = ?) "
                "ORDER BY id LIMIT ?",
                (cutoff, ARCHIVE_PURPOSE, int(limit)),
            ).fetchall()
        except Exception:  # noqa: BLE001 - legacy shape; nothing to archive
            return found
    return [int(row["id"]) for row in rows]
