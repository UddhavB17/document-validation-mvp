"""Central registry for schema statements added by workstreams.

Streams that add tables (auth, llm_calls, …) put their ``CREATE TABLE`` /
``CREATE INDEX`` statements in their own module and call ``register(...)``
at import time; each module is imported once from ``database/__init__.py``.
``database/db.py:init_db()`` executes ``database.models.SCHEMA_STATEMENTS``
then ``all_statements()``.
"""

from __future__ import annotations

SCHEMA_SOURCES: list[list[str]] = []


def register(statements: list[str]) -> None:
    """Register one module's statements. Idempotent: same list stored once."""
    snapshot = list(statements)
    if snapshot not in SCHEMA_SOURCES:
        SCHEMA_SOURCES.append(snapshot)


def all_statements() -> list[str]:
    """Return every registered statement, in registration order."""
    return [statement for source in SCHEMA_SOURCES for statement in source]
