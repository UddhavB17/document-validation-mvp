import pytest

import database.db as db
from database.db import init_db
from routes.settings import SettingUpdatePayload, update_setting
from services.env_sync import sync_llm_setting_to_env
from services.job_control import DEPRECATED_SECRETS_KEY_ENV, SECRETS_KEY_ENV


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "env_sync.db")
    for var in (SECRETS_KEY_ENV, DEPRECATED_SECRETS_KEY_ENV, "DMEF_JOB_INPUT_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    init_db()
    return tmp_path


def test_sync_llm_provider_updates_env_file(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_PROVIDER=ollama\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setenv("DMEF_ENV_FILE", str(env_path))

    keys = sync_llm_setting_to_env("llm_provider", "gemini", provider_hint="gemini", model_hint="gemini-2.5-flash")

    assert "LLM_PROVIDER" in keys
    assert env_path.read_text(encoding="utf-8").splitlines()[0] == "LLM_PROVIDER=gemini"
    import os

    assert os.getenv("LLM_PROVIDER") == "gemini"
    assert os.getenv("GEMINI_MODEL") == "gemini-2.5-flash"


def test_settings_patch_syncs_llm_model(isolated_db, monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("DMEF_ENV_FILE", str(env_path))
    monkeypatch.delenv("LLM_MODEL", raising=False)

    update_setting("llm_provider", SettingUpdatePayload(config_value="gemini"))
    update_setting("llm_model", SettingUpdatePayload(config_value="gemini-3.8-flash"))

    import os

    assert os.getenv("LLM_MODEL") == "gemini-3.8-flash"
    assert os.getenv("GEMINI_MODEL") == "gemini-3.8-flash"
    assert "GEMINI_MODEL=gemini-3.8-flash" in env_path.read_text(encoding="utf-8")
