"""Versioned, data-driven stamp-duty evaluation.

Document classification only establishes that a page is a stamp certificate.
Whether the amount is sufficient depends on jurisdiction, instrument, execution
date, and sometimes a value such as consideration or secured amount. Legal or
compliance owners supply the rule records; this module never guesses a rate.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from functools import lru_cache
import json
import os
from pathlib import Path
import re
from typing import Any


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "stamp_duty_rules.json"


@lru_cache(maxsize=4)
def load_stamp_duty_rules(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load legal/compliance-approved rules without embedding guessed rates."""
    rules_path = Path(path or os.getenv("STAMP_DUTY_RULES_PATH") or DEFAULT_RULES_PATH)
    if not rules_path.exists():
        return []
    with rules_path.open("r", encoding="utf-8") as source:
        payload = json.load(source)
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        raise ValueError(f"Stamp-duty rules file {rules_path} must contain a rules array")
    return [rule for rule in rules if isinstance(rule, dict)]


def evaluate_stamp_duty(
    observed: dict[str, Any],
    context: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    state = _key(observed.get("stamp_jurisdiction_state") or context.get("stamp_jurisdiction_state"))
    instrument = _instrument_key(observed.get("stamp_article") or context.get("stamp_article"))
    execution_date = _date(observed.get("stamp_date") or context.get("execution_date"))
    paid = _decimal(observed.get("stamp_duty_amount"))
    if not state or not instrument or execution_date is None or paid is None:
        return {
            "status": "INSUFFICIENT_INPUTS",
            "jurisdiction": state or None,
            "instrument": instrument or None,
        }

    matching = [
        rule
        for rule in rules
        if _key(rule.get("jurisdiction")) == state
        and _instrument_matches(instrument, rule.get("instrument_codes"))
        and _rule_is_effective(rule, execution_date)
    ]
    if len(matching) != 1:
        return {
            "status": "RULE_NOT_CONFIGURED" if not matching else "AMBIGUOUS_RULES",
            "jurisdiction": state,
            "instrument": instrument,
            "matching_rule_count": len(matching),
        }

    rule = matching[0]
    expected = _expected_amount(rule, observed, context)
    if expected is None:
        return {
            "status": "INSUFFICIENT_INPUTS",
            "jurisdiction": state,
            "instrument": instrument,
            "rule_id": rule.get("rule_id"),
        }
    return {
        "status": "COMPLIANT" if paid >= expected else "UNDERPAID",
        "jurisdiction": state,
        "instrument": instrument,
        "paid_amount": _decimal_string(paid),
        "expected_amount": _decimal_string(expected),
        "rule_id": rule.get("rule_id"),
        "effective_from": rule.get("effective_from"),
        "effective_to": rule.get("effective_to"),
        "source_url": rule.get("source_url"),
    }


def _expected_amount(
    rule: dict[str, Any], observed: dict[str, Any], context: dict[str, Any]
) -> Decimal | None:
    calculation = rule.get("calculation")
    if not isinstance(calculation, dict):
        return None
    kind = str(calculation.get("kind") or "").strip().casefold()
    if kind == "flat":
        amount = _decimal(calculation.get("amount"))
    elif kind == "percentage":
        base_field = str(calculation.get("base_field") or "stamp_consideration_amount")
        base = _decimal(observed.get(base_field) or context.get(base_field))
        rate = _decimal(calculation.get("rate_percent"))
        amount = base * rate / Decimal("100") if base is not None and rate is not None else None
    else:
        return None
    if amount is None:
        return None
    minimum = _decimal(calculation.get("minimum"))
    maximum = _decimal(calculation.get("maximum"))
    if minimum is not None:
        amount = max(amount, minimum)
    if maximum is not None:
        amount = min(amount, maximum)
    rounding = str(calculation.get("rounding") or "none").casefold()
    if rounding == "ceil_rupee":
        amount = amount.quantize(Decimal("1"), rounding=ROUND_CEILING)
    elif rounding == "nearest_rupee":
        amount = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return amount.normalize()


def _rule_is_effective(rule: dict[str, Any], value: date) -> bool:
    start = _date(rule.get("effective_from"))
    end = _date(rule.get("effective_to"))
    return (start is None or start <= value) and (end is None or value <= end)


def _instrument_matches(instrument: str, values: Any) -> bool:
    configured = values if isinstance(values, list) else [values]
    return any(
        _instrument_key(value) in {"*", instrument}
        for value in configured
        if value not in (None, "")
    )


def _instrument_key(value: Any) -> str:
    if str(value or "").strip() == "*":
        return "*"
    return re.sub(r"^article", "", _key(value))


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _decimal(value: Any) -> Decimal | None:
    cleaned = re.sub(r"[^0-9.-]+", "", str(value or ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _decimal_string(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
