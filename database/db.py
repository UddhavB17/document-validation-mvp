"""SQLite connection helpers."""

import sqlite3
from pathlib import Path

DATABASE_PATH = Path("data/dmef.db")


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH)
