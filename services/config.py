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
        "ocr_hard_timeout_seconds": 60,
    },
    "balanced": {
        "min_classification_confidence": 0.60,
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
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        logger.warning("Invalid integer for %s=%r; using %s", name, raw, default)
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_float(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        logger.warning("Invalid float for %s=%r; using %s", name, raw, default)
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_profile() -> str:
    profile = os.getenv("DMEF_CONFIG_PROFILE", "balanced").strip().lower()
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
