"""Load checklist JSON supplied by the system."""

import json
from pathlib import Path

CHECKLIST_PATH = Path("data/checklist.json")


def _read_checklist(path: str | Path = CHECKLIST_PATH) -> dict:
    checklist_path = Path(path)
    if not checklist_path.exists():
        raise FileNotFoundError(f"Checklist JSON not found at {checklist_path}")

    with checklist_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_checklist(product_type: str, path: str | Path = CHECKLIST_PATH) -> dict:
    checklist = _read_checklist(path)
    if checklist.get("product_type") == product_type:
        return checklist
    if product_type in checklist:
        return checklist[product_type]
    raise ValueError(f"No checklist configured for product_type={product_type}")


def get_ai_checkable_items(product_type: str, path: str | Path = CHECKLIST_PATH) -> list[dict]:
    checklist = load_checklist(product_type, path)
    return [item for item in checklist.get("checklist_items", []) if item.get("ai_checkable")]


def get_human_review_items(product_type: str, path: str | Path = CHECKLIST_PATH) -> list[dict]:
    checklist = load_checklist(product_type, path)
    return checklist.get("human_review_items", [])
