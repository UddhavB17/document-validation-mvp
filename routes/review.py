"""Read-only reviewer API routes used by the Next.js UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from database.db import get_connection, init_db
from services.checklist_service import get_ai_checkable_items, get_all_checklist_items, get_human_review_items
from services.checklist_status import build_checklist_status
from services.ocr_json_export import build_ocr_document_json
from services.reviewer_exceptions import summarize_for_display
from services.reviewer_summary_store import load_reviewer_summary

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/worklist")
def get_worklist() -> dict[str, list[dict[str, Any]]]:
    """Return the reviewer worklist for the Next.js UI."""
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, loan_id, applicant_name, product_type, status, created_at
            FROM applications
            ORDER BY created_at DESC
            """
        ).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            anomalies = connection.execute(
                """
                SELECT severity, rule_id, page_number, reason, document_type, expected_value, found_value
                FROM validation_results
                WHERE application_id = ?
                """,
                (item["id"],),
            ).fetchall()
            summary = summarize_for_display([dict(anomaly) for anomaly in anomalies])
            item["issues"] = summary["raw_count"]
            item["reviewer_issues"] = summary["reviewer_count"]
            items.append(item)

    return {"items": items}


@router.get("/activity/today")
def get_today_activity() -> dict[str, Any]:
    """Return today's reviewer decision summary."""
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                reviewer_decisions.id,
                reviewer_decisions.application_id,
                applications.loan_id,
                reviewer_decisions.decision,
                reviewer_decisions.decided_at
            FROM reviewer_decisions
            JOIN applications ON applications.id = reviewer_decisions.application_id
            WHERE date(reviewer_decisions.decided_at) = date('now', 'localtime')
            ORDER BY reviewer_decisions.decided_at DESC
            """
        ).fetchall()

    decision_rows = [dict(row) for row in rows]
    return {
        "total": len(decision_rows),
        "accepted": sum(1 for row in decision_rows if row["decision"] == "ACCEPT"),
        "overridden": sum(1 for row in decision_rows if row["decision"] == "OVERRIDE"),
        "sent_back": sum(1 for row in decision_rows if row["decision"] == "REQUEST_DOCS"),
        "rows": decision_rows,
    }


@router.get("/applications/{application_id}")
def get_application_review(application_id: int) -> dict[str, Any]:
    """Return the full reviewer detail payload for one application."""
    init_db()
    data = _load_application_result(application_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Application not found")

    application = data["application"]
    product_type = str(application.get("product_type") or "LAP")
    anomalies = data["anomalies"]
    summary = summarize_for_display(anomalies)
    reviewer_summary = load_reviewer_summary(application_id)
    checklist_items = get_all_checklist_items(product_type)
    checklist_rows = build_checklist_status(checklist_items, data["pages"], anomalies)
    manual_items = get_human_review_items(product_type)
    ai_items = get_ai_checkable_items(product_type)
    failed_ai_snos = {anomaly.get("s_no") for anomaly in anomalies if anomaly.get("s_no") is not None}

    return {
        **data,
        "summary": summary,
        "reviewer_summary": reviewer_summary,
        "manual_review_items": manual_items,
        "checklist": {
            "total": len(checklist_rows),
            "found": len([row for row in checklist_rows if row["status"] == "FOUND"]),
            "missing": len([row for row in checklist_rows if row["status"] == "MISSING"]),
            "not_checked": len([row for row in checklist_rows if row["status"] == "NOT_CHECKED"]),
            "rows": checklist_rows,
        },
        "ai_checklist": {
            "passed": len([item for item in ai_items if item.get("s_no") not in failed_ai_snos]),
            "total": len(ai_items),
        },
        "latest_decision": _load_latest_decision(application_id),
    }


@router.get("/applications/{application_id}/ocr-json")
def get_application_ocr_json(application_id: int) -> dict[str, Any]:
    """Return the OCR JSON payload for frontend download."""
    data = _load_application_result(application_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Application not found")
    saved = _load_saved_document_ocr_json(application_id)
    if saved is not None:
        return saved
    return build_ocr_document_json(
        application_id,
        data.get("pages") or [],
        page_events=data.get("page_events") or [],
    )


def _load_application_result(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        application = connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
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
        anomalies = connection.execute("SELECT * FROM validation_results WHERE application_id = ?", (application_id,)).fetchall()
        pages = connection.execute("SELECT * FROM pages WHERE application_id = ? ORDER BY page_number", (application_id,)).fetchall()
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

    page_dicts = [_coerce_json_row(row) for row in pages]
    anomaly_dicts = [dict(row) for row in anomalies]
    document_pages: dict[str, list[int]] = {}
    for page in page_dicts:
        doc_type = page.get("document_type")
        if doc_type and doc_type != "Unknown":
            document_pages.setdefault(str(doc_type), []).append(page.get("page_number"))

    return {
        "application": dict(application),
        "uploaded_file": dict(uploaded_file) if uploaded_file else {},
        "ground_truth": dict(ground_truth) if ground_truth else {},
        "anomalies": anomaly_dicts,
        "pages": page_dicts,
        "page_events": [_coerce_json_row(row) for row in page_events],
        "documents_found": sorted(document_pages),
        "document_pages": document_pages,
        "documents_missing": [
            anomaly.get("document_type")
            for anomaly in anomaly_dicts
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC") and anomaly.get("document_type")
        ],
    }


def _load_latest_decision(application_id: int) -> dict[str, Any] | None:
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


def _coerce_json_row(row: Any) -> dict[str, Any]:
    payload = dict(row)
    raw_fields = payload.get("extracted_fields")
    try:
        decoded = json.loads(raw_fields) if raw_fields else {}
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    payload["extracted_fields"] = decoded if isinstance(decoded, dict) else {}
    return payload


def _load_saved_document_ocr_json(application_id: int) -> dict[str, Any] | None:
    path = Path("data/processed") / f"application_{application_id}" / "document_ocr_data.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
