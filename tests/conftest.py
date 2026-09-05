"""Shared pytest fixtures (ws-i postgres cutover).

When ``DATABASE_URL`` is set (PostgreSQL): at session start run
``alembic upgrade head`` against it; before each test truncate all tables
(``TRUNCATE ... RESTART IDENTITY CASCADE`` over the table list from
``information_schema`` / ``pg_tables``, excluding ``alembic_version``).

When unset, keep the current SQLite temp-file behaviour untouched: this
module does nothing and each test's own ``monkeypatch`` of
``DATABASE_PATH`` continues to isolate SQLite files.
"""

from __future__ import annotations

import os

import pytest


def _postgres_url() -> str:
    raw = os.getenv("DATABASE_URL", "")
    raw = raw.strip() if isinstance(raw, str) else ""
    return raw if raw.startswith("postgresql") else ""


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@pytest.fixture(scope="session", autouse=True)
def _postgres_schema():
    """Create the Postgres schema once per session via alembic."""
    url = _postgres_url()
    if not url:
        yield
        return
    from alembic.config import Config

    from alembic import command

    # Build Config without alembic.ini so env.py skips fileConfig (which
    # would reconfigure root logging and break caplog in unrelated tests).
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url(url))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _postgres_truncate():
    """Truncate all Postgres tables before each test for isolation."""
    url = _postgres_url()
    if not url:
        yield
        return
    from sqlalchemy import create_engine, text

    engine = create_engine(_sqlalchemy_url(url), pool_pre_ping=True)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename != 'alembic_version'"
            )
        ).fetchall()
        tables = [str(row[0]) for row in rows]
        if tables:
            quoted = ", ".join(f'"{table}"' for table in tables)
            connection.execute(
                text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
            )
            connection.commit()
    engine.dispose()
    # Re-seed system_settings defaults so tests calling init_db() (a
    # connectivity check on Postgres) still see seeds, matching SQLite
    # behaviour where init_db() creates + seeds. Idempotent via ON CONFLICT.
    from database.db import get_connection, seed_defaults

    with get_connection() as connection:
        seed_defaults(connection)
    yield
