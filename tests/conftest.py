"""Shared fixtures for Postgres and queue/batch tests.

When ``DATABASE_URL`` is set (PostgreSQL): at session start run
``alembic upgrade head`` against it; before each test truncate all tables
(``TRUNCATE ... RESTART IDENTITY CASCADE`` over the table list from
``information_schema`` / ``pg_tables``, excluding ``alembic_version``).

When unset, keep the current SQLite temp-file behaviour untouched: this
module does nothing and each test's own ``monkeypatch`` of
``DATABASE_PATH`` continues to isolate SQLite files.

``ws-d-auth`` owns the ``auth_headers`` fixture: it boots an isolated SQLite
file, runs ``bootstrap_admin()``, and logs in, so route tests can call
protected endpoints. The fixture is explicit (not autouse).
"""

from __future__ import annotations

import os

os.environ.setdefault("DMEF_INLINE_WORKER", "1")
os.environ.setdefault("DMEF_AUTH_SECRET", "pytest-auth-secret-do-not-use-in-prod")
os.environ.setdefault("DMEF_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("DMEF_BOOTSTRAP_ADMIN_PASSWORD", "Str0ngPassw0rd!")

import pytest


@pytest.fixture
def auth_headers(tmp_path, monkeypatch):
    """Return ``{"Authorization": "Bearer …"}`` for the bootstrap admin.

    Explicit (not autouse): tests for protected routes request it directly.
    Boots an isolated SQLite file, runs ``bootstrap_admin()``, and logs in.
    """
    import database.db as db
    import routes.auth as auth_routes
    from database.db import init_db
    from main import app
    from services.auth.bootstrap import bootstrap_admin

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()
    bootstrap_admin()
    auth_routes._LOGIN_ATTEMPTS.clear()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/auth/login",
        json={
            "email": os.environ.get(
                "DMEF_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com"
            ),
            "password": os.environ.get(
                "DMEF_BOOTSTRAP_ADMIN_PASSWORD", "Str0ngPassw0rd!"
            ),
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


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
