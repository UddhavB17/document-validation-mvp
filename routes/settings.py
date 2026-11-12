from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.db import get_connection
from services.admin_setting_schema import setting_metadata, validate_setting_value
from services.auth.dependencies import require_role
from services.config import is_secret_setting
from services.env_sync import effective_setting_metadata, sync_llm_setting_to_env
from services.job_control import encrypt_secret

router = APIRouter(
    prefix="/settings", tags=["settings"], dependencies=[Depends(require_role("admin"))]
)

# Secret values are never returned by this API; a set secret reads back as
# the placeholder below plus ``is_set: true``. (``has_value`` is the legacy
# alias kept for the current Settings UI.)
SECRET_PLACEHOLDER = "***"


class SettingUpdatePayload(BaseModel):
    config_value: str = ""
    clear_secret: bool = False


def _is_secret(row: dict) -> bool:
    return is_secret_setting(str(row.get("config_key") or ""), row.get("value_type"))


def _serialize_setting(row) -> dict:
    data = dict(row)
    is_secret = _is_secret(data)
    raw_value = str(data.get("config_value") or "")
    has_value = bool(raw_value.strip())
    data["is_secret"] = is_secret
    # ``is_set`` is the contracted flag; ``has_value`` stays for the UI.
    data["is_set"] = has_value if is_secret else True
    data["has_value"] = has_value if is_secret else True
    if is_secret:
        data["config_value"] = SECRET_PLACEHOLDER if has_value else ""
    config_key = str(data.get("config_key") or "")
    data.update(setting_metadata(config_key, str(data.get("value_type") or "str")))
    meta = effective_setting_metadata(
        config_key,
        str(data.get("value_type") or "str"),
        str(data.get("config_value") or ""),
    )
    if meta and not is_secret:
        data.update(meta)
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
    if config_key == "llm.review_system_prompt" and len(payload.config_value) > 8000:
        raise HTTPException(
            status_code=422,
            detail="The report system prompt additions must be 8,000 characters or fewer",
        )
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
        elif is_secret and incoming.strip() in {"", SECRET_PLACEHOLDER, "********"}:
            # "********" is the pre-hygiene placeholder; keep stored value.
            new_value = row_data.get("config_value") or ""
        elif is_secret and incoming.strip():
            # Secrets are encrypted at rest; the API never sees plaintext back.
            try:
                incoming = validate_setting_value(
                    config_key, str(row_data.get("value_type") or "secret"), incoming
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            new_value = encrypt_secret(incoming)
        else:
            try:
                new_value = validate_setting_value(
                    config_key, str(row_data.get("value_type") or "str"), incoming
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        conn.execute(
            "UPDATE system_settings SET config_value = ?, updated_at = ? WHERE config_key = ?",
            (new_value, datetime.now(UTC).isoformat(), config_key),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT config_key, config_value, value_type, category, label, description FROM system_settings WHERE config_key = ?",
            (config_key,),
        ).fetchone()
    if not is_secret and config_key in {"llm_provider", "llm_model"}:
        provider_row = None
        model_row = None
        if config_key == "llm_provider":
            provider_hint = str(new_value)
            with get_connection() as conn:
                model_row = conn.execute(
                    "SELECT config_value FROM system_settings WHERE config_key = ?",
                    ("llm_model",),
                ).fetchone()
            model_hint = str(model_row["config_value"] or "") if model_row else None
            sync_llm_setting_to_env(
                config_key,
                str(new_value),
                provider_hint=provider_hint,
                model_hint=model_hint,
            )
        else:
            with get_connection() as conn:
                provider_row = conn.execute(
                    "SELECT config_value FROM system_settings WHERE config_key = ?",
                    ("llm_provider",),
                ).fetchone()
            provider_hint = str(provider_row["config_value"] or "") if provider_row else None
            sync_llm_setting_to_env(
                config_key,
                str(new_value),
                provider_hint=provider_hint,
                model_hint=str(new_value),
            )
    return {"status": "success", **_serialize_setting(updated)}
