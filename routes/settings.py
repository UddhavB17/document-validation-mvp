"""Settings API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database.db import get_connection

router = APIRouter(prefix="/settings", tags=["settings"])
SETTING_COLUMNS = "config_key, config_value, value_type, category, label, description"


class SettingUpdatePayload(BaseModel):
    config_value: str


@router.get("")
def get_all_settings() -> list[dict[str, Any]]:
    """Return all configurable application settings."""
    with get_connection() as connection:
        rows = connection.execute(f"SELECT {SETTING_COLUMNS} FROM system_settings").fetchall()
    return [dict(row) for row in rows]


@router.patch("/{config_key}")
def update_setting(config_key: str, payload: SettingUpdatePayload) -> dict[str, str]:
    """Update one existing setting and return its persisted value."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM system_settings WHERE config_key = ?",
            (config_key,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Setting {config_key} not found")

        connection.execute(
            """
            UPDATE system_settings
            SET config_value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE config_key = ?
            """,
            (payload.config_value, config_key),
        )

    return {
        "status": "success",
        "config_key": config_key,
        "config_value": payload.config_value,
    }
