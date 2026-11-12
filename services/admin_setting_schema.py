"""Validation rules for values editable through the admin settings API."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingRule:
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: tuple[str, ...] = ()


SETTING_RULES: dict[str, SettingRule] = {
    "llm_enabled": SettingRule(allowed_values=("true", "false")),
    "llm_provider": SettingRule(
        allowed_values=("ollama", "openai", "openai_compatible", "gemini", "none")
    ),
    "ocr.provider": SettingRule(allowed_values=("google_vision",)),
    "google.vision.auth": SettingRule(allowed_values=("auto", "api_key", "adc")),
    "google.vision.feature": SettingRule(
        allowed_values=("DOCUMENT_TEXT_DETECTION", "TEXT_DETECTION")
    ),
    "min_confidence": SettingRule(minimum=0.4, maximum=0.95),
    "google.vision.timeout.seconds": SettingRule(minimum=5, maximum=300),
    "google.vision.max_attempts": SettingRule(minimum=1, maximum=10),
    "validation.name_fuzzy_threshold": SettingRule(minimum=50, maximum=100),
    "validation.amount_tolerance_percent": SettingRule(minimum=0, maximum=10),
    "validation.date_tolerance_days": SettingRule(minimum=0, maximum=30),
}


def setting_metadata(config_key: str, value_type: str) -> dict[str, Any]:
    """Return server-owned editor constraints for a setting."""
    rule = SETTING_RULES.get(config_key, SettingRule())
    return {
        "minimum": rule.minimum,
        "maximum": rule.maximum,
        "allowed_values": list(rule.allowed_values),
    }


def validate_setting_value(config_key: str, value_type: str, value: str) -> str:
    """Validate and canonicalize a setting value, raising ValueError on failure."""
    normalized_type = str(value_type or "str").strip().lower()
    rule = SETTING_RULES.get(config_key, SettingRule())

    if normalized_type == "secret":
        if len(value) > 8192:
            raise ValueError("Secret values must be 8,192 characters or fewer")
        return value
    if normalized_type in {"bool", "boolean"}:
        lowered = value.strip().lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("Enter true or false")
        canonical = "true" if lowered in {"true", "1", "yes", "on"} else "false"
        _validate_allowed(config_key, canonical, rule)
        return canonical
    if normalized_type in {"int", "integer"}:
        try:
            parsed = int(value.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a whole number") from exc
        _validate_range(parsed, rule)
        return str(parsed)
    if normalized_type in {"float", "number", "decimal"}:
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a number") from exc
        if not math.isfinite(parsed):
            raise ValueError("Enter a finite number")
        _validate_range(parsed, rule)
        return str(parsed)
    if normalized_type == "json":
        try:
            parsed_json = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter valid JSON") from exc
        if not isinstance(parsed_json, list) or len(parsed_json) > 100:
            raise ValueError("This setting must be a list with at most 100 entries")
        if any(not isinstance(item, str) or len(item) > 100 for item in parsed_json):
            raise ValueError("List entries must be text values of at most 100 characters")
        return json.dumps(parsed_json, ensure_ascii=False)
    if normalized_type in {"str", "string", "text"}:
        if len(value) > 8000:
            raise ValueError("Text values must be 8,000 characters or fewer")
        _validate_allowed(config_key, value.strip(), rule)
        return value
    raise ValueError(f"Unsupported setting type: {normalized_type}")


def _validate_allowed(config_key: str, value: str, rule: SettingRule) -> None:
    if rule.allowed_values and value not in rule.allowed_values:
        choices = ", ".join(rule.allowed_values)
        raise ValueError(f"{config_key} must be one of: {choices}")


def _validate_range(value: int | float, rule: SettingRule) -> None:
    if rule.minimum is not None and value < rule.minimum:
        raise ValueError(f"Value must be at least {rule.minimum:g}")
    if rule.maximum is not None and value > rule.maximum:
        raise ValueError(f"Value must be at most {rule.maximum:g}")
