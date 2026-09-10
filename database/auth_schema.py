"""Authentication tables for ``ws-d-auth`` (contracts §6).

Registered with the schema registry from ``database/__init__.py`` so
``database/db.py:init_db()`` creates these tables alongside the core schema.
"""

from __future__ import annotations

from database.schema_registry import register

AUTH_SCHEMA_STATEMENTS: list[str] = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TEXT NOT NULL,
        created_by INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS user_passwords (
        user_id INTEGER PRIMARY KEY,
        password_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
]

register(AUTH_SCHEMA_STATEMENTS)
