"""Helpers for the ``object_refs`` table (contracts §2).

New code records every durable object here instead of writing legacy
``file_path`` columns. ``owner_table`` is ``'applications'`` or
``'intake_packages'``; ``purpose`` is one of ``source`` | ``manifest`` |
``normalized_pdf`` | ``ocr_export`` | ``report``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database.db import get_connection


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_ref(
    owner_table: str,
    owner_id: int | str,
    purpose: str,
    storage_key: str,
    content_type: str | None = None,
    size_bytes: int | None = None,
) -> None:
    """Insert or refresh one object reference (dialect neutral).

    Re-recording an existing key refreshes ``created_at`` so regenerating an
    export (e.g. the on-demand OCR JSON) restarts its retention window.
    """
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO object_refs (
                owner_table, owner_id, purpose, storage_key,
                content_type, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(storage_key) DO UPDATE SET
                owner_table = excluded.owner_table,
                owner_id = excluded.owner_id,
                purpose = excluded.purpose,
                content_type = excluded.content_type,
                size_bytes = excluded.size_bytes,
                created_at = excluded.created_at
            """,
            (
                owner_table,
                str(owner_id),
                purpose,
                storage_key,
                content_type,
                size_bytes,
                _utc_now_iso(),
            ),
        )


def get_ref(
    owner_table: str,
    owner_id: int | str,
    purpose: str,
) -> dict[str, Any] | None:
    """Return the newest reference for one owner/purpose, or ``None``."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT owner_table, owner_id, purpose, storage_key,
                   content_type, size_bytes, created_at
            FROM object_refs
            WHERE owner_table = ? AND owner_id = ? AND purpose = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (owner_table, str(owner_id), purpose),
        ).fetchone()
    return dict(row) if row is not None else None


def list_refs(owner_table: str, owner_id: int | str) -> list[dict[str, Any]]:
    """Return every reference for one owner, oldest first."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT owner_table, owner_id, purpose, storage_key,
                   content_type, size_bytes, created_at
            FROM object_refs
            WHERE owner_table = ? AND owner_id = ?
            ORDER BY id
            """,
            (owner_table, str(owner_id)),
        ).fetchall()
    return [dict(row) for row in rows]
