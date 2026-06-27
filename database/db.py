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
    """Open (and create if missing) the SQLite database.

    Row factory is set so that rows can be accessed by column name.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
