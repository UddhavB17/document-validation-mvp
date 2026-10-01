"""Smoke tests for the refactored pipeline package boundaries."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("confidence_key", ["confidence", "ocr_confidence"])
def test_partner_pages_preserve_explicit_zero_confidence(confidence_key) -> None:
    from services.pipeline.partner import _build_partner_pages

    pages = _build_partner_pages(
        {"pan": {"text": "Permanent Account Number ABCDE1234F", confidence_key: 0.0}}
    )

    assert pages[0]["ocr_confidence"] == 0.0
    assert pages[0]["classification_confidence"] == 0.0


def test_pipeline_public_facade_exports_expected_symbols() -> None:
    pipeline = importlib.import_module("services.pipeline")
    for symbol in (
        "run_pipeline",
        "run_partner_json_pipeline",
        "run_ocr_on_page",
        "_build_page_records",
        "_save_ground_truth",
        "_save_pages",
        "_smooth_page_classifications",
        "_infer_document_type_from_filename",
        "DOCUMENT_TYPE_ALIASES",
    ):
        assert hasattr(pipeline, symbol), symbol


def test_internal_modules_do_not_import_package_facade() -> None:
    package_source = importlib.import_module("services.pipeline").__file__
    assert package_source is not None

    package_dir = Path(package_source).parent
    for source_path in sorted(package_dir.glob("*.py")):
        if source_path.name == "__init__.py":
            continue

        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        facade_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                facade_imports.extend(
                    alias.name for alias in node.names if alias.name == "services.pipeline"
                )
            elif isinstance(node, ast.ImportFrom) and node.module == "services.pipeline":
                facade_imports.append(node.module)

        assert not facade_imports, source_path.name
