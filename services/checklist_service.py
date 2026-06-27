"""Load checklist JSON supplied by the system."""

import json
from pathlib import Path


def load_checklist(path: str = "data/checklist.json") -> dict:
    checklist_path = Path(path)
    with checklist_path.open("r", encoding="utf-8") as file:
        return json.load(file)
