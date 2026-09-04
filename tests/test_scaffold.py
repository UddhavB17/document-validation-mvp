"""Scaffold smoke tests (ws-0).

Verifies that every stub module is importable, the four new routers exist
with no endpoints yet, ``LocalObjectStore`` round-trips, the schema
registry is idempotent, and ``init_db()`` still works on temp SQLite.
"""

from __future__ import annotations

import io

import pytest


def test_stub_imports() -> None:
    """Every stub module created by ws-0 must be importable."""
    import database.schema_registry  # noqa: F401
    import routes.admin_users  # noqa: F401
    import routes.auth  # noqa: F401
    import routes.ops  # noqa: F401
    import routes.review_pages  # noqa: F401
    import services.auth.dependencies  # noqa: F401
    import services.evidence_boxes  # noqa: F401
    import services.llm_gemini  # noqa: F401
    import services.ops_presentation  # noqa: F401
    import services.pipeline.tasks  # noqa: F401
    import services.retention  # noqa: F401
    import services.storage  # noqa: F401
    import services.worker  # noqa: F401


def test_router_prefixes_empty() -> None:
    """New routers exist with the contracted prefixes and no endpoints yet."""
    from routes import admin_users, auth, ops, review_pages

    assert auth.router.prefix == "/auth"
    assert admin_users.router.prefix == "/admin/users"
    assert ops.router.prefix == "/ops"
    assert review_pages.router.prefix == "/review"
    for module in (auth, admin_users, ops):
        assert list(module.router.routes) == []
    # ws-a data diet: review_pages serves the polling status + page-text
    # endpoints so the frontend stops polling the full review payload.
    assert sorted(
        route.path for route in review_pages.router.routes
    ) == sorted(
        [
            "/review/applications/{application_id}/status",
            "/review/applications/{application_id}/pages/{page_number}/text",
        ]
    )


def test_auth_dependencies_raise_501() -> None:
    """Auth dependency stubs fail closed until ws-d implements them."""
    from fastapi import HTTPException

    from services.auth.dependencies import get_current_user, require_role

    with pytest.raises(HTTPException) as exc_info:
        get_current_user()
    assert exc_info.value.status_code == 501
    assert callable(require_role("admin"))


def test_pipeline_task_stubs_raise_not_implemented(tmp_path, monkeypatch) -> None:
    """Behaviour stubs raise until their owning workstream implements them."""
    from services import evidence_boxes, llm_gemini, ops_presentation, worker

    with pytest.raises(NotImplementedError):
        worker.run_worker(once=True)
    with pytest.raises(NotImplementedError):
        ops_presentation.build_ops_payload(1)
    with pytest.raises(NotImplementedError):
        llm_gemini.generate("hello", model="m", timeout=60)
    with pytest.raises(NotImplementedError):
        evidence_boxes.find_value_bbox([], "value")


def test_retention_implemented_by_ws_a(tmp_path, monkeypatch) -> None:
    """ws-a data diet: run_retention reports per-action counts (dry run)."""
    import database.db as db_module
    from database.db import init_db
    from services.retention import run_retention

    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "retention-scaffold.db")
    init_db()
    result = run_retention(dry_run=True)
    assert result["dry_run"] is True
    assert result["pipeline_job_inputs_deleted"] == 0
    assert result["applications_archived"] == 0


def test_local_object_store_round_trip(tmp_path, monkeypatch) -> None:
    """LocalObjectStore put/get/open/exists/delete/list/signed_url works."""
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path))
    monkeypatch.delenv("DMEF_STORAGE_BACKEND", raising=False)

    from services.storage import GcsObjectStore, LocalObjectStore, get_store

    store = LocalObjectStore()
    key = "applications/12/source/a.pdf"
    assert store.put(key, b"hello", "application/pdf") == key
    assert store.get(key) == b"hello"
    assert store.exists(key)
    with store.open(key) as handle:
        assert handle.read() == b"hello"
    assert store.signed_url(key) == f"/storage/{key}"
    assert store.signed_url(key, expires_seconds=60) == f"/storage/{key}"
    assert key in store.list("applications/12/")
    assert store.list("applications/12/") == sorted(store.list("applications/12/"))

    stream_key = "jobs/1/chunk.bin"
    assert store.put(stream_key, io.BytesIO(b"streamed"), "application/octet-stream")
    assert store.get(stream_key) == b"streamed"

    store.delete(key)
    assert not store.exists(key)
    store.delete(key)  # deleting a missing key is a no-op

    for bad_key in ("", "/absolute/key", "../escape", "a/../b", "a/.."):
        with pytest.raises(ValueError):
            store.put(bad_key, b"x", "text/plain")
    with pytest.raises(ValueError):
        store.signed_url("/absolute/key")

    assert isinstance(get_store(), LocalObjectStore)
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "gcs")
    gcs_store = get_store()
    assert isinstance(gcs_store, GcsObjectStore)
    with pytest.raises(NotImplementedError):
        gcs_store.get(stream_key)


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


def test_init_db_temp_sqlite(tmp_path, monkeypatch) -> None:
    """init_db() (plus registered statements) works on a temp SQLite file."""
    import database.db as db_module

    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "scaffold-test.db")
    db_module.init_db()
    db_module.init_db()  # second run must be a no-op
    with db_module.get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS n FROM applications").fetchone()
        assert row["n"] == 0
