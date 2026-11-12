import pytest
from fastapi import HTTPException

import database.db as db
from database.db import get_connection, init_db
from routes.settings import SettingUpdatePayload, get_all_settings, update_setting
from services.admin_setting_schema import validate_setting_value


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "settings.db")
    monkeypatch.delenv("DMEF_JOB_INPUT_KEY_FILE", raising=False)
    monkeypatch.delenv("DMEF_SECRETS_KEY", raising=False)
    monkeypatch.delenv("SECRETS_KEY", raising=False)
    init_db()
    return tmp_path


@pytest.mark.parametrize(
    ("key", "value_type", "value", "expected"),
    [
        ("min_confidence", "float", "0.85", "0.85"),
        ("llm_enabled", "bool", "YES", "true"),
        ("google.vision.timeout.seconds", "int", "120", "120"),
        ("required_fields.pan", "json", '["pan_number"]', '["pan_number"]'),
        ("llm_model", "str", "custom-model-v1", "custom-model-v1"),
    ],
)
def test_valid_setting_values_are_canonicalized(key, value_type, value, expected):
    assert validate_setting_value(key, value_type, value) == expected


@pytest.mark.parametrize(
    ("key", "value_type", "value"),
    [
        ("min_confidence", "float", "1.1"),
        ("google.vision.timeout.seconds", "int", "2"),
        ("google.vision.auth", "str", "magic"),
        ("llm_enabled", "bool", "sometimes"),
        ("required_fields.pan", "json", '{"pan_number": true}'),
        ("min_confidence", "float", "NaN"),
    ],
)
def test_invalid_setting_values_are_rejected(key, value_type, value):
    with pytest.raises(ValueError):
        validate_setting_value(key, value_type, value)


def test_update_setting_rejects_out_of_range_value(isolated_db):
    with pytest.raises(HTTPException) as error:
        update_setting("min_confidence", SettingUpdatePayload(config_value="2"))

    assert error.value.status_code == 422


def test_settings_expose_runtime_override_and_editor_constraints(isolated_db, monkeypatch):
    monkeypatch.setenv("MIN_CLASSIFICATION_CONFIDENCE", "0.9")
    settings = {setting["config_key"]: setting for setting in get_all_settings()}

    assert settings["min_confidence"]["minimum"] == 0.4
    assert settings["min_confidence"]["maximum"] == 0.95
    assert settings["min_confidence"]["effective_value"] == "0.9"
    assert settings["min_confidence"]["env_override_active"] is True


def test_classifier_threshold_setting_is_readable_from_database(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE system_settings SET config_value = ? WHERE config_key = ?",
            ("0.93", "min_confidence"),
        )

    settings = {setting["config_key"]: setting for setting in get_all_settings()}
    assert settings["min_confidence"]["effective_value"] == "0.93"


def test_validation_tolerance_settings_affect_field_verification(isolated_db):
    from services.field_verification import verify_amount

    assert verify_amount("102", "100").match is False
    with get_connection() as connection:
        connection.execute(
            "UPDATE system_settings SET config_value = ? WHERE config_key = ?",
            ("2.0", "validation.amount_tolerance_percent"),
        )
    assert verify_amount("102", "100").match is True


def test_classifier_uses_admin_minimum_confidence_setting(isolated_db, monkeypatch):
    import services.document_classifier as classifier

    monkeypatch.setattr(
        classifier,
        "load_document_type_registry",
        lambda: {"min_confidence": 0.5, "document_types": [{"type": "Example"}]},
    )
    monkeypatch.setattr(
        classifier,
        "_score_rule",
        lambda *_args, **_kwargs: {
            "document_type": "Example",
            "confidence": 0.8,
            "matched_signals": [],
            "priority": 0,
        },
    )
    with get_connection() as connection:
        connection.execute(
            "UPDATE system_settings SET config_value = ? WHERE config_key = ?",
            ("0.9", "min_confidence"),
        )

    assert classifier.classify_page_with_candidates("plain text")["document_type"] == "None"
    monkeypatch.setenv("MIN_CLASSIFICATION_CONFIDENCE", "0.7")
    assert classifier.classify_page_with_candidates("plain text")["document_type"] == "Example"
