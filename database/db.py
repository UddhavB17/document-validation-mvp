"""SQLite connection helpers.

The database file lives at DATABASE_PATH (default: data/dmef.db).
Override by setting DATABASE_PATH in your .env file.
"""

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/dmef.db"))


def get_connection() -> sqlite3.Connection:
    """Open the SQLite database and return rows addressable by column name."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_db() -> None:
    """Create all DMEF tables and indexes if they do not already exist."""
    from database.models import INDEX_STATEMENTS, MIGRATION_STATEMENTS, SCHEMA_STATEMENTS

    with get_connection() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        for statement in MIGRATION_STATEMENTS:
            try:
                connection.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
