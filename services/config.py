"""Runtime configuration with safe environment parsing."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from database.db import get_connection

logger = logging.getLogger(__name__)

T = TypeVar("T", int, float)

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


_PROFILE_DEFAULTS: dict[str, dict[str, float | int]] = {
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
    value = _configured_value(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUE_VALUES


def get_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    return _bounded_number(
        name,
        default,
        converter=int,
        minimum=minimum,
        maximum=maximum,
    )


def get_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    return _bounded_number(
        name,
        default,
        converter=float,
        minimum=minimum,
        maximum=maximum,
    )


def _configured_value(name: str) -> Any:
    """Read an environment override, then the matching database setting."""
    raw_environment_value = os.getenv(name)
    if raw_environment_value is not None:
        return raw_environment_value

    database_key = name.lower().replace("_", ".")
    return get_setting(database_key)


def _bounded_number(
    name: str,
    default: T,
    *,
    converter: Callable[[Any], T],
    minimum: T | None = None,
    maximum: T | None = None,
) -> T:
    """Parse and clamp a numeric setting from the configured sources."""
    configured_value = _configured_value(name)
    try:
        value = converter(configured_value) if configured_value is not None else default
    except (TypeError, ValueError):
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
    """Read a setting from environment, then ``system_settings``."""
    env_key = key.upper().replace(".", "_")
    env_val = os.getenv(env_key)
    if env_val is not None:
        normalized_value = env_val.strip().lower()
        if normalized_value in TRUE_VALUES:
            return True
        if normalized_value in FALSE_VALUES:
            return False
        if normalized_value.startswith(("[", "{")):
            try:
                return json.loads(env_val)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON value for setting %r; treating it as text", key)
        try:
            if "." in env_val:
                return float(env_val)
            return int(env_val)
        except (TypeError, ValueError):
            return env_val

    try:
        return _database_setting(key, default)
    except Exception as exc:
        logger.warning(
            "Failed to load setting %r from database: %s; using default %r",
            key,
            exc,
            default,
        )
    return default


def _database_setting(key: str, default: Any) -> Any:
    """Load and type-convert one value from the settings table."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT config_value, value_type FROM system_settings WHERE config_key = ?",
            (key,),
        ).fetchone()

    if row is None:
        return default

    raw_value = row["config_value"]
    value_type = row["value_type"]
    if value_type == "bool":
        return str(raw_value).strip().lower() in TRUE_VALUES
    if value_type == "int":
        return int(raw_value)
    if value_type == "float":
        return float(raw_value)
    if value_type == "json":
        return json.loads(raw_value)
    return raw_value
