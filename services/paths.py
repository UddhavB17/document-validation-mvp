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


def _env_path(environment_name: str, default_path: str) -> Path:
    """Resolve a non-empty environment override, falling back to a default path."""
    environment_value = os.getenv(environment_name)
    if isinstance(environment_value, str) and environment_value.strip():
        return Path(environment_value.strip())
    return Path(default_path)


def database_path() -> Path:
    """Return the SQLite path, including support for historical ``DATABASE_URL``."""
    configured_path = os.getenv("DATABASE_PATH")
    if isinstance(configured_path, str) and configured_path.strip():
        return Path(configured_path.strip())

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
