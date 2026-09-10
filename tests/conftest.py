"""Shared fixtures for Postgres and queue/batch tests.

When ``DATABASE_URL`` is set (PostgreSQL): at session start run
``alembic upgrade head`` against it; before each test truncate all tables
(``TRUNCATE ... RESTART IDENTITY CASCADE`` over the table list from
``information_schema`` / ``pg_tables``, excluding ``alembic_version``).

SAFETY: the truncate step wipes the whole database, so a remote Postgres
(Neon, Cloud SQL, …) is refused unless ``DMEF_ALLOW_REMOTE_TEST_DB=1`` is
set explicitly. Localhost Postgres (CI service, ``docker-compose.dev.yml``)
and SQLite temp files always work. This prevents a local ``pytest`` run
with a production ``.env`` in place from destroying real data.

When unset, keep the current SQLite temp-file behaviour untouched: this
module does nothing and each test's own ``monkeypatch`` of
``DATABASE_PATH`` continues to isolate SQLite files.

``ws-d-auth`` owns the ``auth_headers`` fixture: it boots an isolated SQLite
file, runs ``bootstrap_admin()``, and logs in, so route tests can call
protected endpoints. The fixture is explicit (not autouse).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

os.environ.setdefault("DMEF_INLINE_WORKER", "1")
os.environ.setdefault("DMEF_AUTH_SECRET", "pytest-auth-secret-do-not-use-in-prod")
os.environ.setdefault("DMEF_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("DMEF_BOOTSTRAP_ADMIN_PASSWORD", "Str0ngPassw0rd!")

import pytest

#: Hosts that are always safe to truncate during tests.
_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

#: Opt-in that lifts the remote-database refusal below. Never set this in
#: a checked-in file; export it only for throwaway databases.
REMOTE_TEST_DB_OPT_IN_ENV = "DMEF_ALLOW_REMOTE_TEST_DB"


def remote_test_db_url(url: str | None = None) -> str:
    """Return ``url`` when it points at a non-local Postgres test DB.

    Returns ``""`` for SQLite/empty URLs, localhost Postgres, and when the
    ``DMEF_ALLOW_REMOTE_TEST_DB=1`` opt-in is set. Anything else (e.g. a
    Neon ``*-pooler.*`` host picked up from a local ``.env``) is returned
    so the caller can refuse to run.
    """
    raw = url if url is not None else os.getenv("DATABASE_URL", "")
    raw = raw.strip() if isinstance(raw, str) else ""
    if not raw.startswith("postgresql"):
        return ""
    if os.getenv(REMOTE_TEST_DB_OPT_IN_ENV) == "1":
        return ""
    try:
        host = (urlparse(raw).hostname or "").lower()
    except ValueError:
        return raw
    if host in _LOCAL_DB_HOSTS:
        return ""
    return raw


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
            "email": os.environ.get("DMEF_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com"),
            "password": os.environ.get("DMEF_BOOTSTRAP_ADMIN_PASSWORD", "Str0ngPassw0rd!"),
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
def _guard_remote_test_database():
    """Refuse to run the suite against a remote database by accident.

    The per-test truncate below wipes every table, so pointing ``pytest``
    at Neon (e.g. via a production ``.env`` left in place) would destroy
    real data. Abort with a clear message unless the operator explicitly
    opted in with ``DMEF_ALLOW_REMOTE_TEST_DB=1``.
    """
    blocked = remote_test_db_url()
    if blocked:
        host = (urlparse(blocked).hostname or "unknown host").lower()
        pytest.exit(
            "Refusing to run tests against remote database host "
            f"'{host}': the suite truncates every table before each test. "
            "Unset DATABASE_URL (SQLite temp files) or use localhost "
            "Postgres, or export DMEF_ALLOW_REMOTE_TEST_DB=1 for a "
            "throwaway database you intend to wipe.",
            returncode=2,
        )
    yield


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
            connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
            connection.commit()
    engine.dispose()
    # Re-seed system_settings defaults so tests calling init_db() (a
    # connectivity check on Postgres) still see seeds, matching SQLite
    # behaviour where init_db() creates + seeds. Idempotent via ON CONFLICT.
    from database.db import get_connection, seed_defaults

    with get_connection() as connection:
        seed_defaults(connection)
    yield
