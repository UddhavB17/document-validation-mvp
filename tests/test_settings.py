from __future__ import annotations

from database import db
from database.db import get_connection, init_db
from routes.settings import SECRET_PLACEHOLDER, SettingUpdatePayload, get_all_settings, update_setting
from services.ocr_router import ocr_provider


def _settings_by_key() -> dict[str, dict]:
    return {row["config_key"]: row for row in get_all_settings()}


def test_ocr_settings_are_seeded_and_google_api_key_is_masked(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "settings.db")
    init_db()

    settings = _settings_by_key()

    assert settings["ocr.provider"]["config_value"] == "local"
    assert settings["google.vision.api_key"]["is_secret"] is True
    assert settings["google.vision.api_key"]["has_value"] is False
    assert settings["google.vision.api_key"]["config_value"] == ""
    assert settings["google.vision.timeout.seconds"]["config_value"] == "60"


def test_secret_update_stores_google_api_key_without_returning_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "settings.db")
    init_db()

    response = update_setting("google.vision.api_key", SettingUpdatePayload(config_value="fake-google-key"))

    assert response["config_value"] == SECRET_PLACEHOLDER
    assert response["has_value"] is True
    with get_connection() as conn:
        stored = conn.execute(
            "SELECT config_value FROM system_settings WHERE config_key = 'google.vision.api_key'"
        ).fetchone()["config_value"]
    assert stored == "fake-google-key"

    update_setting("google.vision.api_key", SettingUpdatePayload(config_value=SECRET_PLACEHOLDER))
    with get_connection() as conn:
        still_stored = conn.execute(
            "SELECT config_value FROM system_settings WHERE config_key = 'google.vision.api_key'"
        ).fetchone()["config_value"]
    assert still_stored == "fake-google-key"

    cleared = update_setting("google.vision.api_key", SettingUpdatePayload(config_value="", clear_secret=True))
    assert cleared["config_value"] == ""
    assert cleared["has_value"] is False


def test_ocr_provider_can_be_controlled_from_settings_when_env_is_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "settings.db")
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    init_db()

    assert ocr_provider() == "local"

    update_setting("ocr.provider", SettingUpdatePayload(config_value="google_vision"))

    assert ocr_provider() == "google_vision"
