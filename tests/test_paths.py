"""Regression tests for the shared backend filesystem configuration."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from services import paths
from services.ocr_json_export import save_ocr_document_json
from services.review.repository import load_saved_document_ocr_json


def test_path_helpers_honor_environment_overrides(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "runtime" / "review.db"
    uploads = tmp_path / "incoming"
    processed = tmp_path / "processed"
    reports = tmp_path / "reports"
    checklist = tmp_path / "rules.json"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("UPLOAD_DIR", str(uploads))
    monkeypatch.setenv("PAGE_OUTPUT_DIR", str(processed))
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(reports))
    monkeypatch.setenv("CHECKLIST_JSON_PATH", str(checklist))

    configured_paths = importlib.reload(paths)

    assert configured_paths.database_path() == database
    assert configured_paths.upload_dir() == uploads
    assert configured_paths.processed_output_dir() == processed
    assert configured_paths.report_output_dir() == reports
    assert configured_paths.checklist_json_path() == checklist


def test_ocr_writer_and_review_loader_share_processed_override(monkeypatch, tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    monkeypatch.setenv("PAGE_OUTPUT_DIR", str(processed))
    importlib.reload(paths)

    target = save_ocr_document_json(
        41,
        [{"page_number": 1, "document_type": "PAN Card", "extracted_fields": {}}],
    )

    assert target == processed / "application_41" / "document_ocr_data.json"
    assert load_saved_document_ocr_json(41) == json.loads(target.read_text(encoding="utf-8"))
