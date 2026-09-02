"""Database access for review routes and services."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from database.db import get_connection

from services.review.types import AnomalyRow, ApplicationReviewData, PageRow
from services.progress_tracker import RETRYABLE_PROGRESS_STATES, operational_progress_status


def coerce_json_row(row: Any) -> PageRow:
    payload = dict(row)
    raw_fields = payload.get("extracted_fields")
    try:
        decoded = json.loads(raw_fields) if raw_fields else {}
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    payload["extracted_fields"] = decoded if isinstance(decoded, dict) else {}
    return payload  # type: ignore[return-value]


def load_application_review_data(application_id: int) -> ApplicationReviewData | None:
    with get_connection() as connection:
        application = connection.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if application is None:
            return None
        uploaded_file = connection.execute(
            "SELECT * FROM uploaded_files WHERE application_id = ? ORDER BY uploaded_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        ground_truth = connection.execute(
            "SELECT * FROM ground_truth WHERE application_id = ? ORDER BY extracted_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        anomalies = connection.execute(
            "SELECT * FROM validation_results WHERE application_id = ?",
            (application_id,),
        ).fetchall()
        pages = connection.execute(
            "SELECT * FROM pages WHERE application_id = ? ORDER BY page_number",
            (application_id,),
        ).fetchall()
        page_events = connection.execute(
            """
            SELECT page_number, total_pages, page_type, document_type, status,
                   elapsed_seconds, error, extracted_fields, completed_at
            FROM pipeline_page_events
            WHERE application_id = ?
            ORDER BY page_number
            """,
            (application_id,),
        ).fetchall()

    page_dicts: list[dict[str, object]] = [coerce_json_row(row) for row in pages]
    anomaly_dicts: list[dict[str, object]] = [dict(row) for row in anomalies]
    document_pages: dict[str, list[int]] = {}
    for page in page_dicts:
        doc_type = page.get("document_type")
        if doc_type and doc_type != "Unknown":
            document_pages.setdefault(str(doc_type), []).append(page.get("page_number"))  # type: ignore[arg-type]

    return {
        "application": dict(application),
        "uploaded_file": dict(uploaded_file) if uploaded_file else {},
        "ground_truth": dict(ground_truth) if ground_truth else {},
        "anomalies": anomaly_dicts,
        "pages": page_dicts,
        "page_events": [coerce_json_row(row) for row in page_events],
        "documents_found": sorted(document_pages),
        "document_pages": document_pages,
        "documents_missing": [
            anomaly.get("document_type")
            for anomaly in anomaly_dicts
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC") and anomaly.get("document_type")
        ],
    }


def load_latest_decision(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, application_id, decision, reviewer_note, decided_at
            FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    return dict(row) if row else None


def load_saved_document_ocr_json(application_id: int) -> dict[str, Any] | None:
    path = Path("data/processed") / f"application_{application_id}" / "document_ocr_data.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def list_application_rows_ordered_by_created_at() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, loan_id, applicant_name, product_type, status, created_at
            FROM applications
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def load_validation_results_by_application_ids(
    application_ids: list[int],
) -> dict[int, list[AnomalyRow]]:
    if not application_ids:
        return {}
    placeholders = ",".join("?" for _ in application_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT application_id, severity, rule_id, page_number, reason,
                   document_type, expected_value, found_value
            FROM validation_results
            WHERE application_id IN ({placeholders})
            """,
            application_ids,
        ).fetchall()

    grouped: dict[int, list[AnomalyRow]] = defaultdict(list)
    for row in rows:
        application_id = int(row["application_id"])
        grouped[application_id].append(dict(row))  # type: ignore[arg-type]
    return grouped


def load_pipeline_progress_by_application_ids(
    application_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not application_ids:
        return {}
    placeholders = ",".join("?" for _ in application_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT application_id, status, updated_at
            FROM pipeline_progress
            WHERE application_id IN ({placeholders})
            """,
            application_ids,
        ).fetchall()

    progress_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        payload = dict(row)
        application_id = int(payload.pop("application_id"))
        operational_status = operational_progress_status(payload)
        progress_by_id[application_id] = {
            "operational_status": operational_status,
            "retryable": operational_status in RETRYABLE_PROGRESS_STATES,
        }
    return progress_by_id
