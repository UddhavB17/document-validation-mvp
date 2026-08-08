from __future__ import annotations

import os
import sqlite3

import pytest

from database import db
from database.db import init_db
from services.ocr_router import OCRResult, OCRRouter, get_ocr_route_metrics, ocr_provider
from services.pipeline import _deterministic_routing_document_type


@pytest.fixture(autouse=True)
def _clear_low_memory_ocr_overrides(monkeypatch) -> None:
    """`.env` may enable DMEF_LOW_MEMORY for local laptops; keep unit tests deterministic."""
    monkeypatch.delenv("OCR_FORCE_FAST_PATH", raising=False)
    monkeypatch.delenv("DMEF_LOW_MEMORY", raising=False)
    monkeypatch.setenv("OCR_PROVIDER", "local")
    monkeypatch.setenv("DMEF_LOCAL_OCR_TEST_MODE", "true")

    # Unit tests drive OCR via OCR_PROVIDER; production Settings prefers DB.
    import services.config as config_mod
    import services.ocr_router as ocr_router_mod

    real_get_setting = config_mod.get_setting

    def _get_setting(key: str, default=None):
        if key == "ocr.provider":
            return os.getenv("OCR_PROVIDER") or default or "local"
        return real_get_setting(key, default)

    monkeypatch.setattr(config_mod, "get_setting", _get_setting)
    monkeypatch.setattr(ocr_router_mod, "get_setting", _get_setting)


def _fast_result(confidence: float = 0.96) -> OCRResult:
    return OCRResult(
        text="INCOME TAX DEPARTMENT ABCDE1234F",
        confidence=confidence,
        route_used="fast",
        bounding_boxes=[{"text": "ABCDE1234F", "confidence": confidence, "bbox": [1, 2, 3, 4]}],
    )


def test_local_ocr_requires_explicit_test_mode_when_database_selects_google(monkeypatch) -> None:
    import services.ocr_router as ocr_router_mod

    monkeypatch.setattr(ocr_router_mod, "get_setting", lambda _key, _default=None: "google_vision")
    monkeypatch.setenv("OCR_PROVIDER", "local")
    monkeypatch.delenv("DMEF_LOCAL_OCR_TEST_MODE", raising=False)
    assert ocr_provider() == "google_vision"

    monkeypatch.setenv("DMEF_LOCAL_OCR_TEST_MODE", "true")
    assert ocr_provider() == "local"


def test_legacy_local_database_setting_is_forced_to_google_outside_test_mode(monkeypatch) -> None:
    import services.ocr_router as ocr_router_mod

    monkeypatch.setattr(ocr_router_mod, "get_setting", lambda _key, _default=None: "local")
    monkeypatch.delenv("DMEF_LOCAL_OCR_TEST_MODE", raising=False)

    assert ocr_provider() == "google_vision"


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


def test_google_vision_provider_offloads_all_ocr(monkeypatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "google_vision")
    fast_calls: list[str] = []
    structured_calls: list[str] = []
    google_calls: list[str] = []
    router = OCRRouter(
        fast_processor=lambda path: fast_calls.append(str(path)) or _fast_result(),
        structured_processor=lambda path: structured_calls.append(str(path)) or _structured_result(),
        google_vision_processor=lambda path: google_calls.append(str(path)) or {
            "ocr_text": "Google Vision text",
            "confidence": 0.93,
            "bounding_boxes": [{"text": "Google", "bbox": []}],
            "layout_blocks": [{"type": "TEXT", "text": "Google Vision text"}],
        },
        event_recorder=lambda **_event: None,
    )

    result = router.process_page("page.png", "Bank Statement", 1)
    classification = router.process_fast_for_classification("page.png")

    assert result.route_used == "google_vision"
    assert result.text == "Google Vision text"
    assert result.to_legacy_dict()["ocr_pipeline"] == "Google Vision API"
    assert classification.route_used == "google_vision"
    assert fast_calls == []
    assert structured_calls == []
    assert google_calls == ["page.png", "page.png"]


def test_google_vision_reuses_classification_result_for_final_routing(monkeypatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "google_vision")
    google_calls: list[str] = []
    events: list[dict] = []
    router = OCRRouter(
        fast_processor=lambda _path: pytest.fail("local fast OCR must not run"),
        structured_processor=lambda _path: pytest.fail("local structured OCR must not run"),
        google_vision_processor=lambda path: google_calls.append(str(path)) or {
            "ocr_text": "Loan Application Form Applicant Name Ramesh Kumar",
            "confidence": 0.94,
        },
        event_recorder=lambda **event: events.append(event),
    )

    preliminary = router.process_fast_for_classification("page.png")
    result = router.process_page(
        "page.png",
        "Application Form",
        1,
        doc_id="application-1",
        preliminary_fast_result=preliminary,
    )

    assert google_calls == ["page.png"]
    assert result.route_used == "google_vision"
    assert events[0]["requested_route"] == "google_vision"


def test_init_db_migrates_legacy_ocr_route_constraint(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DATABASE_PATH", database_path)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE ocr_route_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            document_type TEXT,
            page_number INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('processing', 'escalation')),
            requested_route TEXT NOT NULL CHECK(requested_route IN ('fast', 'structured')),
            route_used TEXT NOT NULL CHECK(route_used IN ('fast', 'structured')),
            reason TEXT,
            original_confidence REAL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """INSERT INTO ocr_route_events
           (document_id, page_number, event_type, requested_route, route_used)
           VALUES ('old', 1, 'processing', 'fast', 'fast')"""
    )
    connection.execute(
        """
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            page_number INTEGER,
            page_type TEXT CHECK(page_type IN ('digital', 'scanned')),
            image_path TEXT,
            is_readable BOOLEAN,
            ocr_text TEXT,
            ocr_confidence REAL,
            ocr_route TEXT CHECK(ocr_route IN ('fast', 'structured')),
            ocr_escalated BOOLEAN NOT NULL DEFAULT 0,
            ocr_processing_time_ms INTEGER NOT NULL DEFAULT 0,
            structured_content TEXT,
            document_type TEXT,
            classification_confidence REAL,
            detection_method TEXT DEFAULT 'detected',
            detected_page_number INTEGER,
            extracted_fields TEXT
        )
        """
    )
    connection.execute(
        """INSERT INTO pages
           (application_id, page_number, page_type, ocr_route)
           VALUES (1, 1, 'scanned', 'fast')"""
    )
    connection.commit()
    connection.close()

    init_db()
    with db.get_connection() as migrated:
        migrated.execute(
            """INSERT INTO ocr_route_events
               (document_id, page_number, event_type, requested_route, route_used)
               VALUES ('new', 2, 'processing', 'google_vision', 'google_vision')"""
        )
        assert migrated.execute("SELECT COUNT(*) FROM ocr_route_events").fetchone()[0] == 2
        migrated.execute(
            """INSERT INTO applications (loan_id, status)
               VALUES ('LEGACY-TEST', 'processing')"""
        )
        application_id = migrated.execute("SELECT id FROM applications").fetchone()[0]
        migrated.execute(
            """INSERT INTO pages
               (application_id, page_number, page_type, ocr_route)
               VALUES (?, 2, 'scanned', 'google_vision')""",
            (application_id,),
        )
        assert migrated.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2
        pages_sql = migrated.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pages'"
        ).fetchone()[0]
        assert "google_vision" in pages_sql


def test_auto_ocr_provider_keeps_local_without_google_credentials(monkeypatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "auto")
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    router = OCRRouter(
        fast_processor=lambda _path: _fast_result(),
        structured_processor=lambda _path: _structured_result(),
        event_recorder=lambda **_event: None,
    )

    assert router.decide_route("PAN Card").route == "fast"
