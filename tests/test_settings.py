import pytest
from fastapi.testclient import TestClient
from main import app
import database.db as db
from database.db import get_connection
from services.config import get_setting
from services.llm_client import _api_key

def test_settings_api_and_masking(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "dmef.db"
    monkeypatch.setattr(db, "DATABASE_PATH", db_file)
    db.init_db()
    client = TestClient(app)

    res = client.get("/settings")
    assert res.status_code == 200
    settings = res.json()
    
    llm_key_setting = next(s for s in settings if s["config_key"] == "llm_api_key")
    ocr_key_setting = next(s for s in settings if s["config_key"] == "ocr_api_key")
    assert llm_key_setting["config_value"] == ""
    assert ocr_key_setting["config_value"] == ""

    res = client.patch("/settings/llm_api_key", json={"config_value": "sk-my-super-secret-key"})
    assert res.status_code == 200
    assert res.json()["config_value"] == "••••••••••••••••"

    with get_connection() as conn:
        row = conn.execute("SELECT config_value FROM system_settings WHERE config_key = 'llm_api_key'").fetchone()
        assert row["config_value"] == "sk-my-super-secret-key"

    res = client.get("/settings")
    assert res.status_code == 200
    settings = res.json()
    llm_key_setting = next(s for s in settings if s["config_key"] == "llm_api_key")
    assert llm_key_setting["config_value"] == "••••••••••••••••"

    res = client.patch("/settings/llm_api_key", json={"config_value": "••••••••••••••••"})
    assert res.status_code == 200
    assert res.json()["config_value"] == "••••••••••••••••"
    
    with get_connection() as conn:
        row = conn.execute("SELECT config_value FROM system_settings WHERE config_key = 'llm_api_key'").fetchone()
        assert row["config_value"] == "sk-my-super-secret-key"

    res = client.patch("/settings/required_fields.passport", json={"config_value": '["passport_number", "expiry"]'})
    assert res.status_code == 200
    assert res.json()["config_value"] == '["passport_number", "expiry"]'

    with get_connection() as conn:
        row = conn.execute("SELECT config_value, value_type FROM system_settings WHERE config_key = 'required_fields.passport'").fetchone()
        assert row is not None
        assert row["config_value"] == '["passport_number", "expiry"]'
        assert row["value_type"] == "json"


def test_api_key_enabled_disabled_logic(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "dmef.db"
    monkeypatch.setattr(db, "DATABASE_PATH", db_file)
    db.init_db()

    client = TestClient(app)

    # Enable LLM API Key and configure key
    client.patch("/settings/llm_api_key_enabled", json={"config_value": "true"})
    client.patch("/settings/llm_api_key", json={"config_value": "sk-configured-llm-key"})

    assert _api_key() == "sk-configured-llm-key"

    client.patch("/settings/llm_api_key_enabled", json={"config_value": "false"})
    assert _api_key() == ""

    client.patch("/settings/llm_api_key_enabled", json={"config_value": "true"})
    client.patch("/settings/llm_api_key", json={"config_value": ""})
    monkeypatch.setenv("LLM_API_KEY", "env-key-fallback")
    assert _api_key() == "env-key-fallback"
