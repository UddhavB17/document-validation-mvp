"""Schema parity: Postgres baseline matches SQLite init_db (ws-i).

Table and column *names* from ``alembic upgrade head`` on Postgres equal
those from ``init_db()`` on SQLite (compare sets; ignore types).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect


def _sqlite_schema(tmp_path, monkeypatch) -> dict[str, set[str]]:
    import database.db as db_module

    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_module._Engines.clear()
    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "parity-sqlite.db")
    db_module.init_db()
    engine = create_engine(f"sqlite:///{tmp_path / 'parity-sqlite.db'}")
    inspector = inspect(engine)
    schema = {
        table: set(inspector.get_columns(table) and [c["name"] for c in inspector.get_columns(table)])
        for table in inspector.get_table_names()
    }
    engine.dispose()
    db_module._Engines.clear()
    return schema


def _postgres_schema() -> dict[str, set[str]]:
    url = os.getenv("DATABASE_URL", "").strip()
    assert url.startswith("postgresql"), "DATABASE_URL must be set for parity check"
    sa_url = (
        "postgresql+psycopg://" + url.removeprefix("postgresql://")
        if url.startswith("postgresql://")
        else url
    )
    engine = create_engine(sa_url)
    inspector = inspect(engine)
    schema = {
        table: set(c["name"] for c in inspector.get_columns(table))
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }
    engine.dispose()
    return schema


def test_schema_parity_postgres_matches_sqlite(tmp_path, monkeypatch) -> None:
    """Postgres (alembic) and SQLite (init_db) expose the same tables/columns."""
    original_url = os.getenv("DATABASE_URL", "")
    try:
        sqlite_schema = _sqlite_schema(tmp_path, monkeypatch)
    finally:
        if original_url:
            monkeypatch.setenv("DATABASE_URL", original_url)
        else:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        import database.db as db_module

        db_module._Engines.clear()

    assert sqlite_schema, "SQLite schema should not be empty"
    # Baseline tables that must exist on both dialects.
    expected_tables = {
        "applications",
        "uploaded_files",
        "intake_packages",
        "intake_documents",
        "ground_truth",
        "pages",
        "validation_results",
        "reviewer_decisions",
        "pages_meta",
        "audit_log",
        "pipeline_progress",
        "pipeline_jobs",
        "pipeline_job_inputs",
        "pipeline_page_events",
        "classification_review_log",
        "ocr_route_events",
        "document_verification_reports",
        "reviewer_summaries",
        "system_settings",
        "llm_calls",
        "object_refs",
    }
    for expected in expected_tables:
        assert expected in sqlite_schema, f"SQLite missing table {expected}"

    if not original_url.strip().startswith("postgresql"):
        pytest.skip("DATABASE_URL not set; Postgres parity checked in CI Postgres job")

    postgres_schema = _postgres_schema()
    # Compare baseline tables only. Ephemeral probe tables are ignored on
    # both sides: ``example``/``wsb_probe_*`` on Postgres (truncated but not
    # dropped by the shared-DB fixture) and ``ws0_probe`` on SQLite
    # (registered by test_schema_registry_idempotent before this test runs).
    sqlite_baseline = {
        table: cols for table, cols in sqlite_schema.items() if table in expected_tables
    }
    postgres_baseline = {
        table: cols for table, cols in postgres_schema.items() if table in expected_tables
    }
    assert set(postgres_baseline) == set(sqlite_baseline), (
        "table mismatch:\n"
        f"  only in Postgres: {sorted(set(postgres_baseline) - set(sqlite_baseline))}\n"
        f"  only in SQLite: {sorted(set(sqlite_baseline) - set(postgres_baseline))}\n"
        f"  ignored Postgres ephemeral: {sorted(set(postgres_schema) - set(sqlite_baseline))}\n"
        f"  ignored SQLite ephemeral: {sorted(set(sqlite_schema) - set(sqlite_baseline))}"
    )
    for table in sqlite_baseline:
        assert postgres_baseline[table] == sqlite_baseline[table], (
            f"column mismatch in {table}:\n"
            f"  only in Postgres: {sorted(postgres_baseline[table] - sqlite_baseline[table])}\n"
            f"  only in SQLite: {sorted(sqlite_baseline[table] - postgres_baseline[table])}"
        )
