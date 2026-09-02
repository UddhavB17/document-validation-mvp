"""Checklist loader for system-supplied MSFC checklist JSON."""

import json
from pathlib import Path

from services.paths import checklist_json_path

CHECKLIST_PATH = checklist_json_path()


def _read_checklist(path: str | Path = CHECKLIST_PATH) -> dict:
    checklist_path = Path(path)
    if not checklist_path.exists():
        raise FileNotFoundError(f"Checklist JSON not found at {checklist_path}")

    with checklist_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_checklist(product_type: str = "LAP", path: str | Path = CHECKLIST_PATH) -> dict:
    """Return the full checklist dict for a product type."""
    checklist = _read_checklist(path)
    if checklist.get("product_type") == product_type:
        return checklist
    if product_type in checklist:
        return checklist[product_type]
    raise ValueError(f"No checklist configured for product_type={product_type}")


def get_ai_checkable_items(product_type: str = "LAP", path: str | Path = CHECKLIST_PATH) -> list[dict]:
    checklist = load_checklist(product_type, path)
    return [item for item in checklist.get("checklist_items", []) if item.get("ai_checkable") and item.get("enabled", True)]


def get_accuracy_check_items(product_type: str = "LAP", path: str | Path = CHECKLIST_PATH) -> list[dict]:
    checklist = load_checklist(product_type, path)
    return [item for item in checklist.get("accuracy_check_items", []) if item.get("ai_checkable") and item.get("enabled", True)]


def get_all_checklist_items(product_type: str = "LAP", path: str | Path = CHECKLIST_PATH) -> list[dict]:
    checklist = load_checklist(product_type, path)
    return [item for item in checklist.get("checklist_items", []) if item.get("enabled", True)]


def get_human_review_items(product_type: str = "LAP", path: str | Path = CHECKLIST_PATH) -> list[dict]:
    checklist = load_checklist(product_type, path)
    explicit_items = list(checklist.get("human_review_items", []))
    derived_items = [
        {
            "s_no": item.get("s_no"),
            "description": item.get("description"),
            "category": item.get("category"),
            "document_type": item.get("document_type"),
            "reason": item.get("manual_review_reason")
            or item.get("applicability_note")
            or "Physical-only, conditional, or system-status item; verify manually.",
        }
        for item in checklist.get("checklist_items", [])
        if not item.get("ai_checkable") and item.get("enabled", True)
    ]
    seen: set[int | str | None] = set()
    merged: list[dict] = []
    for item in [*explicit_items, *derived_items]:
        key = item.get("s_no") or item.get("description")
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
