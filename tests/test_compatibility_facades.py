"""Compatibility checks for the maintained backend facades."""

from __future__ import annotations

import ast
import importlib
import logging
from pathlib import Path


def test_validation_facades_keep_existing_public_callables() -> None:
    checklist = importlib.import_module("services.checklist_engine")
    consistency = importlib.import_module("services.consistency_checks")
    extractor = importlib.import_module("services.field_extractor")
    ownership = importlib.import_module("services.person_ownership")
    pipeline = importlib.import_module("services.pipeline")

    assert callable(checklist.run_checks)
    assert callable(consistency.run_consistency_checks)
    assert callable(extractor.extract_fields)
    assert callable(ownership.resolve_person_owner)
    assert callable(pipeline.run_pipeline)


def test_consistency_owner_fallback_is_narrow_and_logged(monkeypatch, caplog) -> None:
    consistency = importlib.import_module("services.consistency_checks")
    calls: list[str] = []

    def _boom(_pages, _trusted):
        calls.append("assign")
        raise ValueError("simulated ownership failure")

    monkeypatch.setattr("services.person_ownership.assign_page_owners", _boom)
    pages = [
        {
            "page_number": 1,
            "person_id": "primary",
            "document_type": "PAN Card",
            "extracted_fields": {
                "pan_number": "TSTAA0001T",
                "applicant_name": "Peeru Lal",
            },
            "ocr_text": "PAN TSTAA0001T",
        }
    ]
    trusted = {
        "people": {
            "primary": {
                "pan_number": "TSTAA0001T",
                "applicant_name": "Peeru Lal",
            }
        }
    }

    with caplog.at_level(logging.WARNING, logger="services.consistency_checks"):
        anomalies = consistency.run_consistency_checks(pages, trusted)

    assert calls == ["assign"]
    assert isinstance(anomalies, list)
    assert "assign_page_owners failed before consistency checks" in caplog.text


def test_pipeline_facade_exports_have_no_duplicate_names() -> None:
    pipeline = importlib.import_module("services.pipeline")
    exports = pipeline.__all__

    assert len(exports) == len(set(exports))
    assert all(hasattr(pipeline, name) for name in exports)


def test_maintained_service_modules_do_not_redeclare_top_level_helpers() -> None:
    services_dir = Path(__file__).parents[1] / "services"

    for module_path in services_dir.rglob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert len(function_names) == len(set(function_names)), module_path
