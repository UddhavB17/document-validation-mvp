"""Batch-rejection table (``fx-hygiene``, contracts §3).

Rejected batch files (wrong type, failed validation) are persisted so
``GET /upload/batch/{id}`` can surface them. Registered with the schema
registry at import time; imported once from ``database/__init__.py`` so
``database/db.py:init_db()`` creates the table alongside the core schema.
The Postgres equivalent lives in ``alembic/versions/0005_batch_rejections.py``.
"""

from __future__ import annotations

from database.schema_registry import register

BATCH_REJECTIONS_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS batch_rejections (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_batch_rejections_batch ON batch_rejections(batch_id)",
]

register(BATCH_REJECTIONS_STATEMENTS)
