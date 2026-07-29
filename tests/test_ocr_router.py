from __future__ import annotations

import pytest

from database import db
from database.db import init_db
from services.ocr_router import OCRResult, OCRRouter, get_ocr_route_metrics
from services.pipeline import _deterministic_routing_document_type


@pytest.fixture(autouse=True)
def _clear_low_memory_ocr_overrides(monkeypatch) -> None:
    """`.env` may enable DMEF_LOW_MEMORY for local laptops; keep unit tests deterministic."""
    monkeypatch.delenv("OCR_FORCE_FAST_PATH", raising=False)
    monkeypatch.delenv("DMEF_LOW_MEMORY", raising=False)


def _fast_result(confidence: float = 0.96) -> OCRResult:
    return OCRResult(
        text="INCOME TAX DEPARTMENT ABCDE1234F",
        confidence=confidence,
        route_used="fast",
        bounding_boxes=[{"text": "ABCDE1234F", "confidence": confidence, "bbox": [1, 2, 3, 4]}],
    )


def _structured_result() -> dict:
    return {
        "ocr_text": "Date Description Debit Credit Balance",
        "confidence": 0.94,
        "header_text": "ACCOUNT STATEMENT",
        "layout_blocks": [{"type": "title", "text": "ACCOUNT STATEMENT"}],
        "tables": [{"pred_html": "<table><tr><td>Date</td></tr></table>"}],
        "structure_json": [{"page_index": 0}],
    }


def test_low_memory_force_fast_skips_structured_even_for_bank_statement(monkeypatch) -> None:
    monkeypatch.setenv("OCR_FORCE_FAST_PATH", "true")
    structured_calls: list[str] = []
    router = OCRRouter(
        fast_processor=lambda _path: _fast_result(0.55),
        structured_processor=lambda path: structured_calls.append(str(path)) or _structured_result(),
        confidence_threshold=0.85,
        event_recorder=lambda **_event: None,
    )

    result = router.process_page("statement.png", "Bank Statement", 3)

    assert result.route_used == "fast"
    assert result.escalated is False
    assert structured_calls == []


def test_pan_uses_fast_path_from_registry() -> None:
    structured_calls: list[str] = []
    router = OCRRouter(
        fast_processor=lambda _path: _fast_result(),
        structured_processor=lambda path: structured_calls.append(str(path)) or _structured_result(),
        event_recorder=lambda **_event: None,
    )

    result = router.process_page("pan.png", "PAN Card", 1)

    assert result.route_used == "fast"
    assert result.structured_content is None
    assert result.bounding_boxes[0]["text"] == "ABCDE1234F"
    assert structured_calls == []


def test_bank_statement_uses_structured_path_and_preserves_table() -> None:
    fast_calls: list[str] = []
    router = OCRRouter(
        fast_processor=lambda path: fast_calls.append(str(path)) or _fast_result(),
        structured_processor=lambda _path: _structured_result(),
        event_recorder=lambda **_event: None,
    )

    result = router.process_page("statement.png", "Bank Statement", 3)

    assert result.route_used == "structured"
    assert result.structured_content is not None
    assert result.structured_content["tables"][0]["pred_html"].startswith("<table>")
    assert fast_calls == []


def test_low_confidence_fast_path_escalates_and_logs() -> None:
    events: list[dict] = []
    router = OCRRouter(
        fast_processor=lambda _path: _fast_result(0.71),
        structured_processor=lambda _path: _structured_result(),
        confidence_threshold=0.85,
        event_recorder=lambda **event: events.append(event),
    )

    result = router.process_page("aadhaar.png", "Aadhaar", 2, doc_id="loan-42")

    assert result.route_used == "structured"
    assert result.escalated is True
    assert result.original_confidence == pytest.approx(0.71)
    assert [event["event_type"] for event in events] == ["escalation", "processing"]
    assert events[0]["reason"] == "low_fast_path_confidence"


def test_tabular_flag_forces_structured_even_if_route_says_fast() -> None:
    router = OCRRouter(event_recorder=lambda **_event: None)

    decision = router.decide_route(
        {"document_type": "Custom Form", "ocr_route": "fast", "has_tabular_data": True}
    )

    assert decision.route == "structured"
    assert "has_tabular_data=true" in decision.rationale


def test_unspecified_document_type_defaults_to_structured() -> None:
    router = OCRRouter(event_recorder=lambda **_event: None)

    assert router.decide_route("New Future Document").route == "structured"


def test_continuation_inherits_parent_route() -> None:
    router = OCRRouter(event_recorder=lambda **_event: None)

    decision = router.decide_route("Unknown", inherited_route="fast")

    assert decision.route == "fast"
    assert "inherited" in decision.rationale


def test_route_timing_and_escalation_are_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "routing.db")
    init_db()
    router = OCRRouter(
        fast_processor=lambda _path: _fast_result(0.70),
        structured_processor=lambda _path: _structured_result(),
        confidence_threshold=0.85,
    )

    router.process_page("aadhaar.png", "Aadhaar", 7, doc_id="application-77")

    metrics = get_ocr_route_metrics("application-77")
    assert metrics[0]["route_used"] == "structured"
    assert metrics[0]["page_count"] == 1
    assert metrics[0]["escalation_count"] == 1


def test_llm_classification_cannot_select_fast_route() -> None:
    routing_type = _deterministic_routing_document_type(
        document_type="PAN",
        detection_method="detected",
        classification_metadata={
            "source": "llm",
            "rule_document_type": "None",
            "rule_confidence": 0.0,
        },
    )

    assert routing_type == "Unknown"
    assert OCRRouter(event_recorder=lambda **_event: None).decide_route(routing_type).route == "structured"
