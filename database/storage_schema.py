"""Object-reference table (owned by ``ws-b-storage-db``).

``object_refs`` maps domain rows to object-store keys so new code never
writes legacy ``file_path`` columns. Registered through the schema registry
(contracts §3); the Postgres baseline owns the equivalent DDL in alembic.
"""

from __future__ import annotations

from database import schema_registry

STORAGE_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS object_refs (
        id INTEGER PRIMARY KEY,
        owner_table TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        purpose TEXT NOT NULL,
        storage_key TEXT NOT NULL UNIQUE,
        content_type TEXT,
        size_bytes INTEGER,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_object_refs_owner
    ON object_refs(owner_table, owner_id)
    """,
]

schema_registry.register(STORAGE_SCHEMA_STATEMENTS)
