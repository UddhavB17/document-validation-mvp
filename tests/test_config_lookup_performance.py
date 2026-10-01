"""Settings lookup latency must not scale with per-page helper calls."""

from contextlib import contextmanager

import pytest

import database.db as db
from services import config


@pytest.fixture
def settings_store(monkeypatch):
    rows = {
        "test.speed": {"config_key": "test.speed", "config_value": "3", "value_type": "int"},
    }
    calls = []

    class Cursor:
        def __init__(self, values):
            self.values = values

        def fetchone(self):
            return self.values[0] if self.values else None

        def fetchall(self):
            return self.values

    class Connection:
        def execute(self, sql, params=()):
            calls.append(sql)
            if params:
                return Cursor([rows[params[0]].copy()] if params[0] in rows else [])
            return Cursor([row.copy() for row in rows.values()])

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(db, "get_connection", connect)
    monkeypatch.delenv("TEST_SPEED", raising=False)
    monkeypatch.delenv("TEST_MISSING", raising=False)
    return rows, calls


def test_environment_override_never_opens_database(monkeypatch):
    def unavailable():
        pytest.fail("Environment override must not open a database connection")

    monkeypatch.setattr(db, "get_connection", unavailable)
    monkeypatch.setenv("TEST_SPEED", "7")
    assert config.get_setting("test.speed") == 7


def test_pipeline_snapshot_bounds_queries_and_preserves_defaults(settings_store):
    _, calls = settings_store
    with config.cached_settings():
        for _ in range(50):
            assert config.get_setting("test.speed") == 3
            assert config.get_setting("test.missing", "first") == "first"
            assert config.get_setting("test.missing", "second") == "second"
    assert len(calls) == 1


def test_database_edits_visible_after_expiry_and_outside_scope(settings_store, monkeypatch):
    rows, calls = settings_store
    clock = [10.0]
    monkeypatch.setattr(config.time, "monotonic", lambda: clock[0])
    with config.cached_settings():
        assert config.get_setting("test.speed") == 3
        rows["test.speed"]["config_value"] = "8"
        assert config.get_setting("test.speed") == 3
        clock[0] = 15.0
        assert config.get_setting("test.speed") == 8
        assert len(calls) == 2
    rows["test.speed"]["config_value"] = "9"
    assert config.get_setting("test.speed") == 9


def test_environment_changes_win_immediately_inside_snapshot(settings_store, monkeypatch):
    with config.cached_settings():
        assert config.get_setting("test.speed") == 3
        monkeypatch.setenv("TEST_SPEED", "12")
        assert config.get_setting("test.speed") == 12
        monkeypatch.setenv("TEST_SPEED", " ")
        assert config.get_setting("test.speed") == 3


def test_scope_restored_after_failure_and_nested_scopes(settings_store):
    rows, _ = settings_store
    with config.cached_settings():
        assert config.get_setting("test.speed") == 3
        rows["test.speed"]["config_value"] = "4"
        with pytest.raises(RuntimeError), config.cached_settings():
            assert config.get_setting("test.speed") == 4
            raise RuntimeError("pipeline failed")
        assert config.get_setting("test.speed") == 3
    assert config.get_setting("test.speed") == 4


def test_snapshot_preserves_secret_decryption(settings_store, monkeypatch):
    rows, _ = settings_store
    rows["test.speed"].update(config_value="encrypted-placeholder", value_type="secret")
    monkeypatch.setattr(config, "_decrypt_stored_secret", lambda key, value: "decrypted")
    with config.cached_settings():
        assert config.get_setting("test.speed") == "decrypted"
        monkeypatch.setattr(config, "_decrypt_stored_secret", lambda key, value: None)
        assert config.get_setting("test.speed", "fallback") == "fallback"


def test_snapshot_retries_failed_refresh_without_caching_default(settings_store, monkeypatch):
    connect = db.get_connection

    @contextmanager
    def unavailable():
        raise RuntimeError("temporary outage")
        yield  # pragma: no cover

    with config.cached_settings():
        monkeypatch.setattr(db, "get_connection", unavailable)
        assert config.get_setting("test.speed", 42) == 42
        monkeypatch.setattr(db, "get_connection", connect)
        assert config.get_setting("test.speed") == 3


def test_final_checklist_bounds_settings_reads_for_large_packet(settings_store, monkeypatch):
    from services import checklist_engine

    _, calls = settings_store
    monkeypatch.setattr(config.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(checklist_engine.checklist_service, "get_all_checklist_items", lambda _: [{
        "s_no": 1, "document_type": "Sanction Letter", "check_type": "PRESENCE",
        "mandatory": True, "severity_if_fail": "HIGH",
    }])
    monkeypatch.setattr(checklist_engine, "_accuracy_checks_enabled", lambda: False)
    pages = [{
        "page_number": number, "page_type": "digital", "document_type": "Sanction Letter",
        "classification_confidence": 0.99, "extracted_fields": {},
    } for number in range(1, 892)]
    assert checklist_engine.run_checks(pages, {}, {}, "LAP") == []
    assert len(calls) == 1


def test_final_report_bounds_settings_reads_for_large_packet(settings_store, monkeypatch):
    from services.checklist_output import build_checklist_verification_response
    from services.checklist_service import get_all_checklist_items

    _, calls = settings_store
    monkeypatch.setattr(config.time, "monotonic", lambda: 10.0)
    pages = [{
        "page_number": number, "page_type": "digital", "document_type": "Loan Agreement",
        "classification_confidence": 0.99, "extracted_fields": {},
    } for number in range(1, 892)]
    report = build_checklist_verification_response(
        loan_file_id="synthetic", pages=pages, anomalies=[],
    )
    assert len(report.items) == len(get_all_checklist_items("LAP"))
    assert len(calls) == 1
