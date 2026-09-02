"""Resolve filesystem paths from environment variables.

Precedence for each path:
1. A non-empty environment variable (set in the shell or ``.env``).
2. The documented default below.

``database/db.py`` and upload/report/pipeline modules import these helpers so
local setups keep working when ``.env`` is copied from ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_path(name: str, default: str) -> Path:
    raw = os.getenv(name)
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip())
    return Path(default)


def database_path() -> Path:
    """SQLite database file.

    Prefer ``DATABASE_PATH``. ``DATABASE_URL=sqlite:///...`` is accepted for
    older ``.env`` files that still use SQLAlchemy-style URLs.
    """
    explicit = os.getenv("DATABASE_PATH")
    if isinstance(explicit, str) and explicit.strip():
        return Path(explicit.strip())

    legacy_url = os.getenv("DATABASE_URL", "").strip()
    if legacy_url.startswith("sqlite:///"):
        return Path(legacy_url.removeprefix("sqlite:///"))

    return Path("data/dmef.db")


def upload_dir() -> Path:
    """Directory for uploaded PDFs and ZIP intake packages."""
    return _env_path("UPLOAD_DIR", "data/uploads")


def processed_output_dir() -> Path:
    """Root for per-application pipeline artifacts (page PNGs, OCR JSON)."""
    return _env_path("PAGE_OUTPUT_DIR", "data/processed")


def report_output_dir() -> Path:
    """Directory for generated Excel/JSON reviewer reports."""
    return _env_path("REPORT_OUTPUT_DIR", "data/reports")


def checklist_json_path() -> Path:
    """Product checklist JSON consumed by the checklist engine."""
    return _env_path("CHECKLIST_JSON_PATH", "data/checklist.json")
