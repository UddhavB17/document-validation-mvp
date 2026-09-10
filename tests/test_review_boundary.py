"""Tests for the review route/service boundary and API payload shapes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

import database.db as db
from database.db import get_connection, init_db
from main import app
from services.review.comparison_matrix import (
    build_comparison_matrix_and_relationships,
    find_source_pages_for_value,
    resolve_field_status,
)
from services.review.worklist import build_worklist


def _use_temp_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")


def _insert_application(
    *,
    loan_id: str,
    applicant_name: str = "Ramesh Kumar",
    product_type: str = "LAP",
    status: str = "NEEDS_REVIEW",
    created_at: str | None = None,
) -> int:
    with get_connection() as connection:
        if created_at is None:
            row = connection.execute(
                """
                INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
                VALUES (?, ?, ?, ?, ?)
                RETURNING id
                """,
                (loan_id, applicant_name, product_type, "Delhi", status),
            ).fetchone()
        else:
            row = connection.execute(
                """
                INSERT INTO applications (loan_id, applicant_name, product_type, branch, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (loan_id, applicant_name, product_type, "Delhi", status, created_at),
            ).fetchone()
        return int(row["id"])


def _insert_ground_truth(application_id: int, raw_json: dict) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO ground_truth (application_id, raw_json, extracted_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (application_id, json.dumps(raw_json)),
        )


def _insert_page(
    application_id: int,
    *,
    page_number: int,
    document_type: str,
    ocr_text: str = "",
    extracted_fields: dict | None = None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pages (
                application_id, page_number, page_type, document_type, ocr_text, extracted_fields
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                page_number,
                "digital",
                document_type,
                ocr_text,
                json.dumps(extracted_fields or {}),
            ),
        )


def _insert_anomaly(
    application_id: int,
    *,
    rule_id: str,
    severity: str = "HIGH",
    page_number: int | None = None,
    reason: str = "",
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO validation_results (
                application_id, rule_id, severity, page_number, reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (application_id, rule_id, severity, page_number, reason),
        )


def test_worklist_empty_applications(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()

    payload = build_worklist()

    assert payload == {"items": []}


def test_full_review_reuses_settings_across_page_confidence_checks(tmp_path, monkeypatch) -> None:
    from routes.review import get_application_review

    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="REVIEW-SPEED")
    for page_number in range(1, 31):
        _insert_page(
            application_id, page_number=page_number, document_type="PAN",
            extracted_fields={"pan_number": "ABCDE1234F"},
        )
    settings_queries = []
    execute = db._Connection.execute

    def counted(self, sql, params=()):
        if "SELECT" in sql.upper() and "system_settings" in sql:
            settings_queries.append(sql)
        return execute(self, sql, params)

    monkeypatch.setattr(db._Connection, "execute", counted)
    response = get_application_review(application_id)
    assert len(response["pages"]) == 30
    assert response["checklist"]["found"] > 0
    assert len(settings_queries) == 1
    assert all("ocr_text" not in page for page in response["pages"])


def test_worklist_orders_by_created_at_desc(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    older_id = _insert_application(loan_id="OLD-1", created_at="2026-01-01 10:00:00")
    newer_id = _insert_application(loan_id="NEW-1", created_at="2026-02-01 10:00:00")

    payload = build_worklist()

    assert [item["id"] for item in payload["items"]] == [newer_id, older_id]
    assert [item["loan_id"] for item in payload["items"]] == ["NEW-1", "OLD-1"]


def test_worklist_uses_batched_repository_queries(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    monkeypatch.delenv("DMEF_STALE_JOB_MINUTES", raising=False)
    for index in range(20):
        application_id = _insert_application(loan_id=f"BATCH-{index}")
        _insert_anomaly(application_id, rule_id="PAN_NUMBER_MISMATCH", page_number=1)
        _insert_anomaly(application_id, rule_id="ADDRESS_NOT_FOUND")
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO pipeline_progress (application_id, status, updated_at) VALUES (?, ?, ?)",
                (application_id, "processing", datetime.now(UTC).isoformat()),
            )

    queries = []
    connections = []
    execute = db._Connection.execute
    enter = db._Connection.__enter__

    def counted_execute(self, sql, params=()):
        queries.append(sql)
        return execute(self, sql, params)

    def counted_enter(self):
        connections.append(self)
        return enter(self)

    monkeypatch.setattr(db._Connection, "execute", counted_execute)
    monkeypatch.setattr(db._Connection, "__enter__", counted_enter)
    payload = build_worklist()

    assert len(payload["items"]) == 20
    assert all(item["issues"] == 2 for item in payload["items"])
    assert all(item["pipeline_status"] == "processing" for item in payload["items"])
    assert len(queries) == 3  # application/progress join, findings, settings snapshot
    assert len(connections) == 2  # data transaction, settings transaction
    assert sum("system_settings" in sql for sql in queries) == 1


def test_worklist_refreshes_progress_and_settings_on_each_request(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    monkeypatch.delenv("DMEF_STALE_JOB_MINUTES", raising=False)
    application_id = _insert_application(loan_id="FRESH-1")
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO pipeline_progress (application_id, status, updated_at) VALUES (?, ?, ?)",
            (application_id, "processing", (datetime.now(UTC) - timedelta(minutes=10)).isoformat()),
        )
        connection.execute(
            "INSERT INTO system_settings (config_key, config_value, value_type) VALUES (?, ?, ?)",
            ("dmef.stale.job.minutes", "30", "int"),
        )
    assert build_worklist()["items"][0]["pipeline_status"] == "processing"

    with get_connection() as connection:
        connection.execute(
            "UPDATE system_settings SET config_value = ? WHERE config_key = ?",
            ("5", "dmef.stale.job.minutes"),
        )
    assert build_worklist()["items"][0]["pipeline_status"] == "stale"

    with get_connection() as connection:
        connection.execute(
            "UPDATE pipeline_progress SET status = ? WHERE application_id = ?",
            ("completed", application_id),
        )
    assert build_worklist()["items"][0]["pipeline_status"] == "completed"


def test_worklist_item_payload_shape(tmp_path, monkeypatch, auth_headers) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="SHAPE-1")
    _insert_anomaly(application_id, rule_id="PAN_NUMBER_MISMATCH", page_number=1)
    client = TestClient(app)

    response = client.get("/review/worklist", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"items"}
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert set(item.keys()) == {
        "id",
        "loan_id",
        "applicant_name",
        "product_type",
        "status",
        "created_at",
        "issues",
        "reviewer_issues",
        "business_issues",
        "processing_warnings",
        "pipeline_status",
        "pipeline_retryable",
        "pipeline_processed_pages",
        "pipeline_total_pages",
        "pipeline_percentage",
    }
    assert item["loan_id"] == "SHAPE-1"
    assert item["pipeline_status"] == "not_started"
    assert item["pipeline_retryable"] is False
    assert item["pipeline_processed_pages"] is None
    assert item["pipeline_total_pages"] is None
    assert item["pipeline_percentage"] is None
    assert item["issues"] >= 1
    assert item["reviewer_issues"] >= 1


def test_worklist_item_carries_processing_progress_counts(
    tmp_path, monkeypatch, auth_headers
) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="PROG-1")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_progress
                (application_id, status, processed_pages, total_pages, percentage)
            VALUES (?, ?, ?, ?, ?)
            """,
            (application_id, "processing", 264, 891, 29.6),
        )
    client = TestClient(app)

    response = client.get("/review/worklist", headers=auth_headers)

    assert response.status_code == 200
    item = next(row for row in response.json()["items"] if row["loan_id"] == "PROG-1")
    assert item["pipeline_processed_pages"] == 264
    assert item["pipeline_total_pages"] == 891
    assert item["pipeline_percentage"] == 29.6


def test_comparison_matrix_empty_ground_truth(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="EMPTY-GT")

    result = build_comparison_matrix_and_relationships(
        application_id,
        {
            "application": {"id": application_id, "loan_id": "EMPTY-GT"},
            "ground_truth": {},
            "pages": [],
            "anomalies": [],
            "uploaded_file": {},
            "page_events": [],
            "documents_found": [],
            "document_pages": {},
            "documents_missing": [],
        },
    )

    assert result == {
        "comparison_matrix": {"core_parameters": [], "applicants": []},
        "relationships": [],
    }


def test_comparison_matrix_multiple_people_and_missing_values(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="MULTI-1")
    raw_json = {
        "loan_id": "MULTI-1",
        "loan_amount": "500000",
        "people": {
            "primary": {
                "person_id": "primary",
                "role": "primary",
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
                "date_of_birth": "1990-01-01",
                "relationship": "Self",
            },
            "coapp_1": {
                "person_id": "coapp_1",
                "role": "coapplicant",
                "applicant_name": "Sita Kumar",
                "pan_number": "TSTPA7009Z",
                "relationship": "WIFE",
                "father_name": "Ramesh Kumar",
            },
        },
    }
    _insert_ground_truth(application_id, raw_json)
    _insert_page(
        application_id,
        page_number=1,
        document_type="PAN Card",
        ocr_text="ABCDE1234F",
        extracted_fields={"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"},
    )
    _insert_page(
        application_id,
        page_number=2,
        document_type="PAN Card",
        ocr_text="TSTPA7009Z",
        extracted_fields={"applicant_name": "Sita Kumar"},
    )

    data = {
        "application": {"id": application_id, "loan_id": "MULTI-1"},
        "ground_truth": {"raw_json": json.dumps(raw_json)},
        "pages": [
            {
                "page_number": 1,
                "document_type": "PAN Card",
                "ocr_text": "ABCDE1234F",
                "page_type": "digital",
                "extracted_fields": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"},
            },
            {
                "page_number": 2,
                "document_type": "PAN Card",
                "ocr_text": "TSTPA7009Z",
                "page_type": "digital",
                "extracted_fields": {"applicant_name": "Sita Kumar"},
            },
        ],
        "anomalies": [],
        "uploaded_file": {},
        "page_events": [],
        "documents_found": ["PAN Card"],
        "document_pages": {"PAN Card": [1, 2]},
        "documents_missing": [],
    }

    result = build_comparison_matrix_and_relationships(
        application_id,
        data,
        ocr_data={
            "documents": [
                {"applicant_role": "primary", "pages": [1]},
                {"applicant_role": "coapp_1", "pages": [2]},
            ],
            "combined_extracted_fields": {},
        },
    )

    applicants = result["comparison_matrix"]["applicants"]
    assert len(applicants) == 2
    assert applicants[0]["applicant_role"] == "primary"
    assert applicants[0]["applicant_label"] == "Primary Applicant"
    assert applicants[1]["applicant_role"] == "co_applicant"
    assert applicants[1]["applicant_label"] == "Co-applicant 1"

    primary_pan = next(
        field for field in applicants[0]["fields"] if field["field_name"] == "pan_number"
    )
    coapp_pan = next(
        field for field in applicants[1]["fields"] if field["field_name"] == "pan_number"
    )
    assert primary_pan["extracted_value"] == "ABCDE1234F"
    assert coapp_pan["extracted_value"] is None
    assert coapp_pan["status"] == "attention"

    core_loan = next(
        field
        for field in result["comparison_matrix"]["core_parameters"]
        if field["field_name"] == "loan_amount"
    )
    assert core_loan["expected_value"] == "500000"
    assert core_loan["extracted_value"] is None
    assert core_loan["status"] == "attention"

    relationship_names = {node["name"] for node in result["relationships"]}
    assert "Ramesh Kumar" in relationship_names
    assert "Sita Kumar" in relationship_names


def test_comparison_matrix_respects_anomaly_status(tmp_path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="ANOM-1")
    raw_json = {
        "loan_id": "ANOM-1",
        "people": {
            "primary": {
                "role": "primary",
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
            }
        },
    }
    anomalies = [
        {
            "rule_id": "PAN_NUMBER_MISMATCH",
            "severity": "HIGH",
            "page_number": 1,
            "reason": "primary",
        }
    ]
    data = {
        "application": {"id": application_id, "loan_id": "ANOM-1"},
        "ground_truth": {"raw_json": json.dumps(raw_json)},
        "pages": [
            {
                "page_number": 1,
                "document_type": "PAN Card",
                "ocr_text": "TSTPA7023Z",
                "page_type": "digital",
                "extracted_fields": {"applicant_name": "Ramesh Kumar", "pan_number": "TSTPA7023Z"},
            }
        ],
        "anomalies": anomalies,
        "uploaded_file": {},
        "page_events": [],
        "documents_found": [],
        "document_pages": {},
        "documents_missing": [],
    }

    result = build_comparison_matrix_and_relationships(
        application_id,
        data,
        ocr_data={
            "documents": [{"applicant_role": "primary", "pages": [1]}],
            "combined_extracted_fields": {},
        },
    )
    pan_field = next(
        field
        for field in result["comparison_matrix"]["applicants"][0]["fields"]
        if field["field_name"] == "pan_number"
    )
    assert pan_field["field_name"] == "pan_number"
    assert pan_field["status"] == "mismatch"
    assert (
        resolve_field_status(
            "primary",
            "pan_number",
            "ABCDE1234F",
            "TSTPA7023Z",
            anomalies,
            {1: "primary"},
        )
        == "mismatch"
    )


def test_find_source_pages_skips_short_values() -> None:
    pages = [{"page_number": 1, "extracted_fields": {"loan_id": "AB"}, "_ocr_clean": "ab"}]
    assert find_source_pages_for_value(pages, "AB", "loan_id") == []


def test_application_review_payload_shape(tmp_path, monkeypatch, auth_headers) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    application_id = _insert_application(loan_id="REVIEW-1")
    raw_json = {
        "loan_id": "REVIEW-1",
        "loan_amount": "100000",
        "applicant_name": "Ramesh Kumar",
        "pan_number": "ABCDE1234F",
    }
    _insert_ground_truth(application_id, raw_json)
    _insert_page(
        application_id,
        page_number=1,
        document_type="Application Form",
        extracted_fields={"loan_amount": "100000", "applicant_name": "Ramesh Kumar"},
    )
    client = TestClient(app)

    response = client.get(f"/review/applications/{application_id}", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) >= {
        "application",
        "uploaded_file",
        "ground_truth",
        "anomalies",
        "pages",
        "page_events",
        "documents_found",
        "document_pages",
        "documents_missing",
        "summary",
        "reviewer_summary",
        "manual_review_items",
        "checklist",
        "ai_checklist",
        "latest_decision",
        "progress",
        "comparison_matrix",
        "relationships",
        "documents",
    }
    assert payload["comparison_matrix"]["core_parameters"]
    assert payload["comparison_matrix"]["applicants"]
    assert isinstance(payload["relationships"], list)
    assert isinstance(payload["documents"], list)
    assert payload["summary"]["raw_count"] == 0
    assert payload["latest_decision"] is None


def test_application_review_not_found(tmp_path, monkeypatch, auth_headers) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    init_db()
    client = TestClient(app)

    response = client.get("/review/applications/99999", headers=auth_headers)

    assert response.status_code == 404
