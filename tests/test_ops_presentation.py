"""Operations payload builder. Owned by ``ws-f-accuracy-ops-api`` (contracts §5)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

import database.db as db
from database.db import get_connection, init_db
from services.checklist_engine import is_bank_statement_old
from services.ops_presentation import build_ops_payload, rule_to_code


class _Text(BaseModel):
    model_config = ConfigDict(extra="forbid")

    en: str
    hi: str


class _Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    bbox: list[float] | None
    text: str


class _Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    title: _Text
    detail: _Text
    pages: list[int]
    evidence: _Evidence | None


class _VerifyPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    document: _Text
    problem: _Text


class _ChecklistRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s_no: int
    description: str
    status: str
    pages: list[int]


class _Checklist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    found: int
    missing: int
    not_checked: int
    rows: list[_ChecklistRow]


class _Processing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str | None
    percentage: float
    attempt: int
    failure_reason: str | None


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: int
    loan_id: str | None
    applicant_name: str | None
    status: str
    processing: _Processing
    summary: _Text
    top_findings: list[_Finding]
    pages_to_verify: list[_VerifyPage]
    checklist: _Checklist


def _walk_keys(value: object, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            _walk_keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _walk_keys(item, found)


@pytest.fixture()
def ops_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "ops.db")
    init_db()
    anomalies = json.loads(
        Path("tests/fixtures/ops/anomalies.json").read_text()
    )
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO applications (loan_id, applicant_name, product_type, status)"
            " VALUES (?, ?, ?, ?)",
            ("LN-001", "Suthar Anupkumar", "LAP", "needs_review"),
        )
        app_id = connection.execute(
            "SELECT id FROM applications WHERE loan_id = ?", ("LN-001",)
        ).fetchone()["id"]
        for anomaly in anomalies:
            connection.execute(
                "INSERT INTO validation_results (application_id, rule_id, s_no,"
                " severity, document_type, expected_value, found_value,"
                " page_number, reason, evidence_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    app_id,
                    anomaly.get("rule_id"),
                    anomaly.get("s_no"),
                    anomaly.get("severity"),
                    anomaly.get("document_type"),
                    anomaly.get("expected_value"),
                    anomaly.get("found_value"),
                    anomaly.get("page_number"),
                    anomaly.get("reason"),
                    json.dumps(anomaly.get("evidence_json"))
                    if anomaly.get("evidence_json") is not None
                    else None,
                ),
            )
    return int(app_id)


def test_payload_validates_and_stays_small(ops_db) -> None:
    payload = build_ops_payload(ops_db)
    _Payload.model_validate(payload)
    assert len(json.dumps(payload, ensure_ascii=False)) <= 50 * 1024


def test_top_findings_capped_and_hindi_present(ops_db) -> None:
    payload = build_ops_payload(ops_db)
    assert len(payload["top_findings"]) <= 5
    assert payload["top_findings"], "fixture anomalies must map to findings"
    codes = [finding["code"] for finding in payload["top_findings"]]
    assert "NAME_MISMATCH" in codes
    assert "ID_MISMATCH" in codes
    for finding in payload["top_findings"]:
        assert finding["title"]["hi"].strip()
        assert finding["detail"]["hi"].strip()
    assert payload["summary"]["en"].strip()
    assert payload["summary"]["hi"].strip()


def test_no_internal_keys_leak(ops_db) -> None:
    payload = build_ops_payload(ops_db)
    keys: set[str] = set()
    _walk_keys(payload, keys)
    assert "rule_id" not in keys
    assert "ocr_text" not in keys
    assert "structured_content" not in keys


def test_needs_review_status(ops_db) -> None:
    assert build_ops_payload(ops_db)["status"] == "needs_review"


def test_rule_to_code_families() -> None:
    assert rule_to_code("TRUSTED_APPLICANT_NAME_MISMATCH") == "NAME_MISMATCH"
    assert rule_to_code("TRUSTED_PAN_NUMBER_MISMATCH") == "ID_MISMATCH"
    assert rule_to_code("INVALID_PAN_FORMAT") == "ID_MISMATCH"
    assert rule_to_code("AADHAAR_ADDRESS_MISMATCH") == "ADDRESS_MISMATCH"
    assert rule_to_code("MISSING_DOC_S12") == "MISSING_DOCUMENT"
    assert rule_to_code("PERIOD_CHECK_S17") == "BANK_STATEMENT_OLD"
    assert rule_to_code("DATE_CHECK_S6") == "BANK_STATEMENT_OLD"
    assert rule_to_code("DOCUMENT_NOT_READABLE") == "PAGE_UNREADABLE"
    assert rule_to_code("LOW_CONFIDENCE_PAGE") == "OCR_FAILED"
    assert rule_to_code("PAN_NUMBER_NOT_FOUND") == "DATA_MISSING"
    assert rule_to_code("AADHAAR_NUMBER_EXTRACTION_UNRELIABLE") == "DATA_MISSING"
    assert rule_to_code("PAGE_PROCESSING_ERROR") == "PROCESSING_ERROR"
    assert rule_to_code("UNCLASSIFIED_PAGE") is None
    assert rule_to_code("BORDERLINE_NAME_MATCH") == "NAME_MISMATCH"


def test_bank_statement_recency_acceptance() -> None:
    assert is_bank_statement_old("2026-05-30", date(2026, 9, 4)) is True
    assert is_bank_statement_old("2026-06-15", date(2026, 9, 4)) is False
