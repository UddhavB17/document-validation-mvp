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
    
    settings = []
    for row in rows:
        d = dict(row)
        if "api_key" in d["config_key"] and d["config_value"]:
            d["config_value"] = "••••••••••••••••"
        settings.append(d)
    return settings


@router.patch("/{config_key}")
def update_setting(config_key: str, payload: SettingUpdatePayload):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT config_value FROM system_settings WHERE config_key = ?",
            (config_key,)
        ).fetchone()

        if "api_key" in config_key and payload.config_value == "••••••••••••••••":
            current_val = row["config_value"] if row else ""
            returned_val = "••••••••••••••••" if current_val else ""
            return {"status": "success", "config_key": config_key, "config_value": returned_val}

        if not row:
            val_type = "json" if config_key.startswith("required_fields.") else "str"
            category = "fields" if config_key.startswith("required_fields.") else "general"
            label = config_key.replace("required_fields.", "").replace("_", " ").title() + " Required Fields" if config_key.startswith("required_fields.") else config_key
            desc = f"Required validation fields config for {label}." if config_key.startswith("required_fields.") else "Custom setting."
            
            conn.execute(
                """
                INSERT INTO system_settings 
                (config_key, config_value, value_type, category, label, description, updated_at) 
                VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """,
                (config_key, payload.config_value, val_type, category, label, desc)
            )
        else:
            conn.execute(
                "UPDATE system_settings SET config_value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE config_key = ?",
                (payload.config_value, config_key)
            )
        conn.commit()

    returned_val = payload.config_value
    if "api_key" in config_key and returned_val:
        returned_val = "••••••••••••••••"

    return {"status": "success", "config_key": config_key, "config_value": returned_val}
