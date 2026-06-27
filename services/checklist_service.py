"""Checklist loader.

Reads the product-specific document checklist from a JSON file.
The checklist defines which documents are required and any field-level rules.

Expected JSON structure (minimum):
{
    "product_type": "Home Loan",
    "required_documents": ["PAN", "Aadhaar", "Bank Statement"],
    "field_rules": {
        "loan_amount": {"type": "number", "min": 100000}
    }
}
"""

import json
from pathlib import Path

DEFAULT_CHECKLIST_PATH = "data/checklist.json"


def load_checklist(path: str = DEFAULT_CHECKLIST_PATH) -> dict:
    """Load and return the checklist JSON from *path*.

    Raises:
        FileNotFoundError: if the checklist file does not exist.
        json.JSONDecodeError: if the file is not valid JSON.
    """
    checklist_path = Path(path)
    if not checklist_path.exists():
        raise FileNotFoundError(
            f"Checklist not found at '{checklist_path}'. "
            "Place a valid checklist JSON at that path before processing."
        )
    with checklist_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
