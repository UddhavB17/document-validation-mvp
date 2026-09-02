"""Environment-driven filesystem paths used by the backend.

Keeping path resolution here prevents individual routes and services from
quietly disagreeing about where runtime data belongs. Empty environment values
are treated as unset so a copied ``.env`` remains safe to edit.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_path(name: str, default: str) -> Path:
    value = os.getenv(name)
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return Path(default)


def database_path() -> Path:
    """Return the SQLite path, accepting the historical ``DATABASE_URL``."""
    explicit = os.getenv("DATABASE_PATH")
    if isinstance(explicit, str) and explicit.strip():
        return Path(explicit.strip())

    legacy_url = os.getenv("DATABASE_URL", "").strip()
    if legacy_url.startswith("sqlite:///"):
        return Path(legacy_url.removeprefix("sqlite:///"))
    return Path("data/dmef.db")


def upload_dir() -> Path:
    """Directory containing uploaded PDFs and ZIP intake packages."""
    return _env_path("UPLOAD_DIR", "data/uploads")


def processed_output_dir() -> Path:
    """Root directory for rendered pages and per-application OCR JSON."""
    return _env_path("PAGE_OUTPUT_DIR", "data/processed")


def report_output_dir() -> Path:
    """Directory for generated JSON and Excel reports."""
    return _env_path("REPORT_OUTPUT_DIR", "data/reports")


def checklist_json_path() -> Path:
    """Path to the product checklist definition."""
    return _env_path("CHECKLIST_JSON_PATH", "data/checklist.json")
