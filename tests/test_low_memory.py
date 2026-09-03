import os

import pytest

from services.low_memory import apply_low_memory_defaults, low_memory_enabled, ocr_force_fast_path


@pytest.fixture(autouse=True)
def _restore_environment_after_test():
    """The production helper writes defaults directly to os.environ."""
    original = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original)


def test_low_memory_forces_fast_ocr_but_preserves_explicit_page_llm(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_LOW_MEMORY", "true")
    monkeypatch.delenv("OCR_FORCE_FAST_PATH", raising=False)
    monkeypatch.setenv("ENABLE_LLM_PAGE_CLASSIFIER", "true")
    monkeypatch.setenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", "true")
    monkeypatch.setenv("PADDLE_STRUCTURE_USE_TABLE_RECOGNITION", "true")

    apply_low_memory_defaults()

    assert low_memory_enabled() is True
    assert ocr_force_fast_path() is True
    assert __import__("os").environ["OCR_FORCE_FAST_PATH"] == "true"
    assert __import__("os").environ["ENABLE_LLM_PAGE_CLASSIFIER"] == "true"
    assert __import__("os").environ["ENABLE_STRUCTURED_LLM_CLASSIFIER"] == "true"
    assert __import__("os").environ["PADDLE_STRUCTURE_USE_TABLE_RECOGNITION"] == "false"


def test_low_memory_disables_page_llm_when_not_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_LOW_MEMORY", "true")
    monkeypatch.delenv("ENABLE_LLM_PAGE_CLASSIFIER", raising=False)
    monkeypatch.delenv("ENABLE_STRUCTURED_LLM_CLASSIFIER", raising=False)

    apply_low_memory_defaults()

    assert __import__("os").environ["ENABLE_LLM_PAGE_CLASSIFIER"] == "false"
    assert __import__("os").environ["ENABLE_STRUCTURED_LLM_CLASSIFIER"] == "false"
