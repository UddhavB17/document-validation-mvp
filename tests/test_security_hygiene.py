"""Security-hygiene tests (ws-h).

Covers: ``POST /shutdown`` removal, ``CORS_ORIGINS`` wiring, Fernet
encryption of secret settings at rest (+ masking in ``GET /settings``),
production startup failing without ``DMEF_SECRETS_KEY``, and consistent
env-over-database settings precedence.
"""

from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import database.db as db
from database.db import get_connection, init_db
from routes.settings import (
    SECRET_PLACEHOLDER,
    SettingUpdatePayload,
    get_all_settings,
    update_setting,
)
from services.config import get_setting
from services.job_control import (
    DEPRECATED_SECRETS_KEY_ENV,
    SECRETS_KEY_ENV,
    ensure_secrets_key,
)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "hygiene.db")
    for var in (SECRETS_KEY_ENV, DEPRECATED_SECRETS_KEY_ENV, "DMEF_JOB_INPUT_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    init_db()
    return tmp_path


def test_shutdown_route_is_gone() -> None:
    import main

    client = TestClient(main.app)
    assert client.post("/shutdown").status_code == 404
    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/health" in paths
    assert "/shutdown" not in paths


def test_cors_reflects_cors_origins_env(monkeypatch) -> None:
    import main

    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://ops.example.com")
    reloaded = importlib.reload(main)
    try:
        client = TestClient(reloaded.app)
        allowed = client.get("/health", headers={"Origin": "https://app.example.com"})
        assert allowed.headers.get("access-control-allow-origin") == "https://app.example.com"
        denied = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in denied.headers
    finally:
        monkeypatch.undo()
        importlib.reload(main)


def test_health_reports_database_and_storage(isolated_db, monkeypatch) -> None:
    import main
    from database import worker_heartbeat

    monkeypatch.setattr(
        worker_heartbeat,
        "get_heartbeat",
        lambda: {
            "last_heartbeat": "2026-01-01T00:00:00+00:00",
            "status": "ok",
        },
    )
    client = TestClient(main.app)
    response = client.get("/health")
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["version"] == main.app.version
    # --- fx-schema: flat database contract (string, never a nested dict) ---
    assert payload["database"] == "ok"
    assert isinstance(payload["database"], str)
    assert payload["database_dialect"] in {"sqlite", "postgresql"}
    assert payload["storage"] == "ok"
    assert isinstance(payload["worker"], dict)
    assert payload["worker"]["status"] == "ok"


def test_health_is_degraded_when_worker_is_stale(isolated_db, monkeypatch) -> None:
    import main
    from database import worker_heartbeat

    monkeypatch.setattr(
        worker_heartbeat,
        "get_heartbeat",
        lambda: {"last_heartbeat": None, "status": "stale"},
    )
    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_health_fails_when_database_is_unreachable(isolated_db, monkeypatch) -> None:
    import main

    def broken_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "get_connection", broken_connection)
    response = TestClient(main.app).get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["database"] == "error"


def test_health_fails_when_storage_is_unreachable(isolated_db, monkeypatch) -> None:
    import main

    class BrokenStore:
        def exists(self, _key: str) -> bool:
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(main, "get_store", lambda: BrokenStore())
    response = TestClient(main.app).get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["storage"] == "error"


def test_secret_setting_round_trips_encrypted(isolated_db, monkeypatch) -> None:
    monkeypatch.setenv(SECRETS_KEY_ENV, Fernet.generate_key().decode("ascii"))

    plaintext = "super-secret-vision-key"
    response = update_setting("google.vision.api_key", SettingUpdatePayload(config_value=plaintext))
    assert response["config_value"] == SECRET_PLACEHOLDER
    assert response["is_set"] is True

    with get_connection() as conn:
        stored = conn.execute(
            "SELECT config_value FROM system_settings WHERE config_key = 'google.vision.api_key'"
        ).fetchone()["config_value"]
    assert stored != plaintext
    assert plaintext not in stored

    assert get_setting("google.vision.api_key") == plaintext


def test_get_settings_never_contains_secret_plaintext(isolated_db, monkeypatch) -> None:
    monkeypatch.setenv(SECRETS_KEY_ENV, Fernet.generate_key().decode("ascii"))

    plaintext = "another-secret-key-value"
    update_setting("google.vision.api_key", SettingUpdatePayload(config_value=plaintext))

    rows = get_all_settings()
    assert rows, "expected seeded settings"
    dumped = repr(rows)
    assert plaintext not in dumped
    by_key = {row["config_key"]: row for row in rows}
    secret_row = by_key["google.vision.api_key"]
    assert secret_row["is_secret"] is True
    assert secret_row["is_set"] is True
    assert secret_row["config_value"] == SECRET_PLACEHOLDER


def test_production_without_key_fails_startup_check(isolated_db, monkeypatch) -> None:
    monkeypatch.setenv("DMEF_ENV", "production")
    for var in (SECRETS_KEY_ENV, DEPRECATED_SECRETS_KEY_ENV, "DMEF_JOB_INPUT_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="DMEF_SECRETS_KEY"):
        ensure_secrets_key()


def test_non_production_without_key_uses_ephemeral_key(isolated_db, monkeypatch) -> None:
    monkeypatch.delenv("DMEF_ENV", raising=False)
    for var in (SECRETS_KEY_ENV, DEPRECATED_SECRETS_KEY_ENV, "DMEF_JOB_INPUT_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    key = ensure_secrets_key()
    assert isinstance(key, bytes)
    assert ensure_secrets_key() == key  # stable within the process


def test_deprecated_key_alias_still_works(monkeypatch) -> None:
    monkeypatch.delenv(SECRETS_KEY_ENV, raising=False)
    monkeypatch.setenv(DEPRECATED_SECRETS_KEY_ENV, Fernet.generate_key().decode("ascii"))
    assert isinstance(ensure_secrets_key(), bytes)


def test_env_wins_over_database_consistently(isolated_db, monkeypatch) -> None:
    update_setting("llm_model", SettingUpdatePayload(config_value="db-model"))

    monkeypatch.setenv("LLM_MODEL", "env-model")
    assert get_setting("llm_model") == "env-model"

    monkeypatch.setenv("LLM_MODEL", "   ")
    assert get_setting("llm_model") == "db-model"

    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert get_setting("llm_model") == "db-model"
