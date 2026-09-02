from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database.db import get_connection

router = APIRouter(prefix="/settings", tags=["settings"])

SECRET_PLACEHOLDER = "********"


class SettingUpdatePayload(BaseModel):
    config_value: str = ""
    clear_secret: bool = False


def _is_secret(row: dict) -> bool:
    value_type = str(row.get("value_type") or "").lower()
    key = str(row.get("config_key") or "").lower()
    return value_type == "secret" or key.endswith("api_key") or key.endswith("token")


def _serialize_setting(row) -> dict:
    data = dict(row)
    is_secret = _is_secret(data)
    raw_value = str(data.get("config_value") or "")
    data["is_secret"] = is_secret
    data["has_value"] = bool(raw_value.strip()) if is_secret else True
    if is_secret:
        data["config_value"] = SECRET_PLACEHOLDER if raw_value.strip() else ""
    return data


@router.get("")
def get_all_settings():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT config_key, config_value, value_type, category, label, description
            FROM system_settings
            ORDER BY category, config_key
            """
        ).fetchall()
    return [_serialize_setting(row) for row in rows]


@router.patch("/{config_key}")
def update_setting(config_key: str, payload: SettingUpdatePayload):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT config_key, config_value, value_type, category, label, description FROM system_settings WHERE config_key = ?",
            (config_key,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Setting {config_key} not found")

        row_data = dict(row)
        is_secret = _is_secret(row_data)
        incoming = payload.config_value or ""

        if is_secret and payload.clear_secret:
            new_value = ""
        elif is_secret and incoming.strip() in {"", SECRET_PLACEHOLDER}:
            new_value = row_data.get("config_value") or ""
        else:
            new_value = incoming

        conn.execute(
            "UPDATE system_settings SET config_value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE config_key = ?",
            (new_value, config_key),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT config_key, config_value, value_type, category, label, description FROM system_settings WHERE config_key = ?",
            (config_key,),
        ).fetchone()
    return {"status": "success", **_serialize_setting(updated)}
