from services.low_memory import apply_low_memory_defaults, low_memory_enabled, ocr_force_fast_path


def test_low_memory_forces_fast_ocr_and_disables_llms(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_LOW_MEMORY", "true")
    monkeypatch.delenv("OCR_FORCE_FAST_PATH", raising=False)
    monkeypatch.setenv("ENABLE_LLM_PAGE_CLASSIFIER", "true")
    monkeypatch.setenv("PADDLE_STRUCTURE_USE_TABLE_RECOGNITION", "true")

    apply_low_memory_defaults()

    assert low_memory_enabled() is True
    assert ocr_force_fast_path() is True
    assert __import__("os").environ["OCR_FORCE_FAST_PATH"] == "true"
    assert __import__("os").environ["ENABLE_LLM_PAGE_CLASSIFIER"] == "false"
    assert __import__("os").environ["PADDLE_STRUCTURE_USE_TABLE_RECOGNITION"] == "false"
