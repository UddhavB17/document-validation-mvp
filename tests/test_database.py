import sqlite3

import pytest

from database import db


def test_get_connection_closes_connection_after_context_exit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "connection.db")

    with db.get_connection() as connection:
        # DROP first so this file can also share one PostgreSQL database.
        connection.execute("DROP TABLE IF EXISTS example")
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_get_connection_rolls_back_and_closes_on_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "rollback.db")

    with db.get_connection() as connection:
        # DROP first so this file can also share one PostgreSQL database.
        connection.execute("DROP TABLE IF EXISTS example")
        connection.execute("CREATE TABLE example (value TEXT)")

    with pytest.raises(RuntimeError, match="abort transaction"):
        with db.get_connection() as failed_connection:
            failed_connection.execute("INSERT INTO example (value) VALUES ('discard me')")
            raise RuntimeError("abort transaction")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        failed_connection.execute("SELECT 1")

    with db.get_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM example").fetchone()[0]

    assert count == 0


def test_schema_registry_idempotent() -> None:
    """Registering the same statement list twice stores it once."""
    from database import schema_registry

    before = len(schema_registry.all_statements())
    statements = ["CREATE TABLE IF NOT EXISTS ws0_probe (id INTEGER PRIMARY KEY)"]
    schema_registry.register(statements)
    schema_registry.register(list(statements))
    matches = [s for s in schema_registry.all_statements() if "ws0_probe" in s]
    assert len(matches) == 1
    assert len(schema_registry.all_statements()) == before + 1
