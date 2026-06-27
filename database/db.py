"""SQLite connection helpers."""

import sqlite3
from pathlib import Path

DATABASE_PATH = Path("data/dmef.db")


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    from database.models import INDEX_STATEMENTS, SCHEMA_STATEMENTS

    with get_connection() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
