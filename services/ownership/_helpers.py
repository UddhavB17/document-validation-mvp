"""Low-level ownership helpers without service dependencies."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from services.person_names import name_similarity


def _relation_name_matches(observed: Any, expected: Any) -> bool:
    observed_tokens = re.findall(r"[a-z]+", str(observed or "").casefold())
    expected_tokens = re.findall(r"[a-z]+", str(expected or "").casefold())
    if not observed_tokens or not expected_tokens:
        return False
    width = len(expected_tokens)
    return any(
        name_similarity(" ".join(observed_tokens[index : index + width]), " ".join(expected_tokens))
        >= 0.85
        for index in range(0, max(1, len(observed_tokens) - width + 1))
    )


def first_value(values: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = values.get(alias)
        if value not in (None, ""):
            return value
    return None


def _words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _date_key(value: str) -> str:
    normalized = str(value or "").strip()
    for format_string in (
        "%d-%B-%Y",
        "%d-%b-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(normalized, format_string).date().isoformat()
        except ValueError:
            continue
    return _words(normalized).replace(" ", "")
