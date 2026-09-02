"""Tests for environment-driven filesystem path resolution."""

from __future__ import annotations

import importlib

import pytest


def _reload_paths(monkeypatch: pytest.MonkeyPatch, *, clear_env: bool = False) -> object:
    """Reload services.paths after optionally clearing path-related env vars."""
    if clear_env:
        for name in (
            "DATABASE_PATH",
            "DATABASE_URL",
            "UPLOAD_DIR",
            "PAGE_OUTPUT_DIR",
            "REPORT_OUTPUT_DIR",
            "CHECKLIST_JSON_PATH",
        ):
            monkeypatch.delenv(name, raising=False)
    import services.paths as paths

    return importlib.reload(paths)


def test_database_path_defaults_to_data_dmef_db(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _reload_paths(monkeypatch, clear_env=True)
    assert paths.database_path().as_posix() == "data/dmef.db"


def test_database_path_honors_database_path_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", "tmp/custom.db")
    paths = _reload_paths(monkeypatch)
    assert paths.database_path().as_posix() == "tmp/custom.db"


def test_database_path_accepts_legacy_sqlite_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/legacy.db")
    paths = _reload_paths(monkeypatch)
    assert paths.database_path().as_posix() == "tmp/legacy.db"


def test_database_path_prefers_database_path_over_legacy_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", "tmp/explicit.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/legacy.db")
    paths = _reload_paths(monkeypatch)
    assert paths.database_path().as_posix() == "tmp/explicit.db"


def test_upload_dir_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", "tmp/uploads")
    paths = _reload_paths(monkeypatch)
    assert paths.upload_dir().as_posix() == "tmp/uploads"


def test_processed_output_dir_defaults_to_data_processed(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _reload_paths(monkeypatch, clear_env=True)
    assert paths.processed_output_dir().as_posix() == "data/processed"


def test_report_output_dir_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPORT_OUTPUT_DIR", "tmp/reports")
    paths = _reload_paths(monkeypatch)
    assert paths.report_output_dir().as_posix() == "tmp/reports"


def test_checklist_json_path_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECKLIST_JSON_PATH", "fixtures/checklist.json")
    paths = _reload_paths(monkeypatch)
    assert paths.checklist_json_path().as_posix() == "fixtures/checklist.json"
