from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database.db import get_connection

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingUpdatePayload(BaseModel):
    config_value: str


@router.get("")
def get_all_settings():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT config_key, config_value, value_type, category, label, description FROM system_settings"
        ).fetchall()
    return [dict(row) for row in rows]


@router.patch("/{config_key}")
def update_setting(config_key: str, payload: SettingUpdatePayload):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM system_settings WHERE config_key = ?",
            (config_key,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Setting {config_key} not found")

        conn.execute(
            "UPDATE system_settings SET config_value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE config_key = ?",
            (payload.config_value, config_key)
        )
        conn.commit()
    return {"status": "success", "config_key": config_key, "config_value": payload.config_value}
