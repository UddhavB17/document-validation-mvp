"""Runtime configuration with safe environment parsing."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_PROFILE_DEFAULTS = {
    "fast": {
        "min_classification_confidence": 0.50,
        "min_scanned_ocr_confidence": 0.60,
        "min_checklist_matches_for_loan_file": 1,
        "max_unknown_ratio_for_unsupported_file": 0.75,
        "page_failure_threshold": 3,
        "ocr_soft_timeout_seconds": 20,
        "ocr_hard_timeout_seconds": 100,
    },
    "balanced": {
        "min_classification_confidence": 0.70,
        "min_scanned_ocr_confidence": 0.70,
        "min_checklist_matches_for_loan_file": 2,
        "max_unknown_ratio_for_unsupported_file": 0.60,
        "page_failure_threshold": 2,
        "ocr_soft_timeout_seconds": 30,
        "ocr_hard_timeout_seconds": 90,
    },
    "strict": {
        "min_classification_confidence": 0.75,
        "min_scanned_ocr_confidence": 0.80,
        "min_checklist_matches_for_loan_file": 3,
        "max_unknown_ratio_for_unsupported_file": 0.50,
        "page_failure_threshold": 1,
        "ocr_soft_timeout_seconds": 45,
        "ocr_hard_timeout_seconds": 120,
    },
}


def get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    db_key = name.lower().replace("_", ".")
    db_val = get_setting(db_key)
    if db_val is not None:
        return bool(db_val)
    return default


def get_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is not None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    else:
        db_key = name.lower().replace("_", ".")
        db_val = get_setting(db_key)
        if db_val is not None:
            try:
                value = int(db_val)
            except (TypeError, ValueError):
                value = default
        else:
            value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_float(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
    else:
        db_key = name.lower().replace("_", ".")
        db_val = get_setting(db_key)
        if db_val is not None:
            try:
                value = float(db_val)
            except (TypeError, ValueError):
                value = default
        else:
            value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_profile() -> str:
    raw = os.getenv("DMEF_CONFIG_PROFILE")
    if raw is not None:
        profile = raw.strip().lower()
    else:
        db_val = get_setting("classification_profile")
        if db_val is not None:
            profile = str(db_val).strip().lower()
        else:
            profile = "balanced"
    if profile not in _PROFILE_DEFAULTS:
        logger.warning("Unknown DMEF_CONFIG_PROFILE=%r; using balanced", profile)
        return "balanced"
    return profile


def _profile_value(key: str) -> float | int:
    return _PROFILE_DEFAULTS[get_profile()][key]


@dataclass(frozen=True)
class EffectiveConfig:
    profile: str
    min_classification_confidence: float
    min_scanned_ocr_confidence: float
    min_checklist_matches_for_loan_file: int
    max_unknown_ratio_for_unsupported_file: float
    page_failure_threshold: int
    ocr_soft_timeout_seconds: int
    ocr_hard_timeout_seconds: int


def effective_config() -> EffectiveConfig:
    return EffectiveConfig(
        profile=get_profile(),
        min_classification_confidence=get_float(
            "MIN_CLASSIFICATION_CONFIDENCE",
            float(_profile_value("min_classification_confidence")),
            minimum=0.0,
            maximum=1.0,
        ),
        min_scanned_ocr_confidence=get_float(
            "MIN_SCANNED_OCR_CONFIDENCE",
            float(_profile_value("min_scanned_ocr_confidence")),
            minimum=0.0,
            maximum=1.0,
        ),
        min_checklist_matches_for_loan_file=get_int(
            "MIN_CHECKLIST_MATCHES_FOR_LOAN_FILE",
            int(_profile_value("min_checklist_matches_for_loan_file")),
            minimum=1,
        ),
        max_unknown_ratio_for_unsupported_file=get_float(
            "MAX_UNKNOWN_RATIO_FOR_UNSUPPORTED_FILE",
            float(_profile_value("max_unknown_ratio_for_unsupported_file")),
            minimum=0.0,
            maximum=1.0,
        ),
        page_failure_threshold=get_int(
            "PAGE_PROCESSING_FAILURE_THRESHOLD",
            int(_profile_value("page_failure_threshold")),
            minimum=1,
        ),
        ocr_soft_timeout_seconds=get_int(
            "OCR_SOFT_TIMEOUT_SECONDS",
            int(_profile_value("ocr_soft_timeout_seconds")),
            minimum=1,
        ),
        ocr_hard_timeout_seconds=get_int(
            "OCR_HARD_TIMEOUT_SECONDS",
            int(_profile_value("ocr_hard_timeout_seconds")),
            minimum=1,
        ),
    )


def log_effective_config() -> None:
    config = effective_config()
    logger.info("DMEF effective config: %s", config)


def get_setting(key: str, default: Any = None) -> Any:
    """Read a setting from environment first (for overrides/tests), then system_settings DB table, with fallback to default."""
    import json
    
    env_key = key.upper().replace(".", "_")
    env_val = os.getenv(env_key)
    if env_val is not None:
        val_lower = env_val.strip().lower()
        if val_lower in {"true", "yes", "on", "1"}:
            return True
        if val_lower in {"false", "no", "off", "0"}:
            return False
        if val_lower.startswith("[") or val_lower.startswith("{"):
            try:
                return json.loads(env_val)
            except Exception:
                pass
        try:
            if "." in env_val:
                return float(env_val)
            return int(env_val)
        except ValueError:
            return env_val

    from database.db import get_connection
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT config_value, value_type FROM system_settings WHERE config_key = ?",
                (key,)
            ).fetchone()
            if row:
                val = row["config_value"]
                val_type = row["value_type"]
                if val_type == "bool":
                    return val.strip().lower() in ("1", "true", "yes", "on")
                elif val_type == "int":
                    return int(val)
                elif val_type == "float":
                    return float(val)
                elif val_type == "json":
                    return json.loads(val)
                return val
    except Exception as exc:
        logger.warning("Failed to load setting %r from database: %s; using default %r", key, exc, default)
    
    return default
