"""Sync selected runtime settings to the local ``.env`` file and ``os.environ``.

Admin settings saves update the database first; this module keeps the gitignored
``.env`` aligned so API and worker processes agree on LLM configuration without
requiring a manual edit. Env path: ``DMEF_ENV_FILE`` (default ``.env``).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")

_LLM_SETTING_TO_ENV: dict[str, str] = {
    "llm_provider": "LLM_PROVIDER",
    "llm_model": "LLM_MODEL",
}


def env_file_path() -> Path:
    raw = os.getenv("DMEF_ENV_FILE", ".env")
    return Path(raw.strip() or ".env")


def _quote_env_value(value: str) -> str:
    cleaned = value.strip()
    if cleaned == "":
        return ""
    if any(ch in cleaned for ch in " #\t\"'\\"):
        escaped = cleaned.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return cleaned


def _set_process_env(key: str, value: str) -> None:
    stripped = value.strip()
    if stripped:
        os.environ[key] = stripped
    else:
        os.environ.pop(key, None)


def _upsert_env_file(path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    out: list[str] = []
    for line in lines:
        match = _ENV_LINE.match(line.strip())
        if not match:
            out.append(line)
            continue
        key = match.group("key")
        if key in updates:
            seen.add(key)
            rendered = _quote_env_value(updates[key])
            out.append(f"{key}={rendered}" if rendered else f"{key}=")
        else:
            out.append(line)

    for key, value in updates.items():
        if key in seen:
            continue
        rendered = _quote_env_value(value)
        out.append(f"{key}={rendered}" if rendered else f"{key}=")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def sync_llm_setting_to_env(
    config_key: str,
    config_value: str,
    *,
    provider_hint: str | None = None,
    model_hint: str | None = None,
) -> list[str]:
    """Mirror one LLM setting save to env + ``.env``. Returns updated env keys."""
    env_key = _LLM_SETTING_TO_ENV.get(config_key)
    if env_key is None:
        return []

    value = str(config_value or "").strip()
    updates: dict[str, str] = {env_key: value}

    provider = str(provider_hint or os.getenv("LLM_PROVIDER") or "").strip().lower()
    if config_key == "llm_provider":
        provider = value.lower()

    model = str(model_hint or os.getenv("LLM_MODEL") or os.getenv("GEMINI_MODEL") or "").strip()
    if config_key == "llm_model":
        model = value

    if provider == "gemini" and model:
        updates["GEMINI_MODEL"] = model
    if config_key == "llm_model" and value:
        updates["LLM_MODEL"] = value

    updated_keys: list[str] = []
    for key, env_val in updates.items():
        _set_process_env(key, env_val)
        updated_keys.append(key)

    env_path = env_file_path()
    try:
        _upsert_env_file(env_path, updates)
        logger.info("Synced LLM settings to %s (%s)", env_path, ", ".join(updated_keys))
    except OSError as exc:
        logger.warning("Could not write %s (%s); in-process env was still updated", env_path, exc)

    return updated_keys


def effective_setting_metadata(config_key: str) -> dict[str, str | bool] | None:
    """Return effective runtime value metadata for display in the settings API."""
    if config_key not in _LLM_SETTING_TO_ENV:
        return None
    env_key = _LLM_SETTING_TO_ENV[config_key]
    raw_env = os.getenv(env_key)
    env_active = isinstance(raw_env, str) and raw_env.strip() != ""
    try:
        if config_key == "llm_provider":
            from services.llm_client import llm_provider

            effective = llm_provider()
        elif config_key == "llm_model":
            from services.llm_client import llm_model

            effective = llm_model()
        else:
            return None
    except Exception:
        effective = ""
    return {
        "effective_value": str(effective),
        "env_override_active": env_active,
    }
