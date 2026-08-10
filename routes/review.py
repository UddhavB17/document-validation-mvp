"""Read-only reviewer API routes used by the Next.js UI."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response

from database.db import get_connection, init_db
from services.checklist_service import get_ai_checkable_items, get_all_checklist_items, get_human_review_items
from services.checklist_status import build_checklist_status
from services.ocr_json_export import build_ocr_document_json
from services.progress_tracker import get_progress
from services.job_control import JobControlError, request_control
from services.reprocessing import (
    ReprocessConflictError,
    queue_application_reprocess,
    restart_application,
    resume_application,
)
from services.reviewer import load_reviewer_summary, summarize_for_display

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
            progress = get_progress(int(item["id"]))
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
            item["business_issues"] = summary["business_count"]
            item["processing_warnings"] = summary["processing_warning_count"]
            item["pipeline_status"] = (
                progress.get("operational_status") if progress else "not_started"
            )
            item["pipeline_retryable"] = bool(progress and progress.get("retryable"))
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
        "progress": get_progress(application_id),
    }


@router.get("/applications/{application_id}/source-pdf", summary="View the original PDF evidence")
def get_application_source_pdf(application_id: int) -> FileResponse:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT file_path, original_filename
            FROM uploaded_files
            WHERE application_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    if row is None or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Source PDF not found")
    file_path = Path(str(row["file_path"]))
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=str(row["original_filename"] or file_path.name),
        content_disposition_type="inline",
    )


@router.get(
    "/applications/{application_id}/source-page/{page_number}",
    summary="Render one source PDF page for evidence review",
)
def get_application_source_page(application_id: int, page_number: int) -> Response:
    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be one or greater")
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT file_path FROM uploaded_files
            WHERE application_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    if row is None or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Source PDF not found")
    file_path = Path(str(row["file_path"]))
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Source PDF not found")

    import fitz

    try:
        with fitz.open(file_path) as document:
            if page_number > document.page_count:
                raise HTTPException(status_code=404, detail="Source page not found")
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image_bytes = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Source PDF could not be rendered") from exc
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/applications/{application_id}/reprocess", summary="Retry a stale or failed PDF pipeline")
def reprocess_application(application_id: int) -> dict[str, Any]:
    init_db()
    try:
        return queue_application_reprocess(application_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ReprocessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _authorize_job_control(request: Request, token: str | None) -> None:
    """Require a configured control token, or limit development mode to localhost."""
    configured = os.getenv("DMEF_JOB_CONTROL_TOKEN", "").strip()
    if configured:
        if token is None or not secrets.compare_digest(token, configured):
            raise HTTPException(status_code=403, detail="Invalid job-control credentials")
        return
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Job control is restricted to localhost")


@router.post("/applications/{application_id}/pause", summary="Pause at the next safe boundary")
def pause_application(
    application_id: int,
    request: Request,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return request_control(application_id, "pause")
    except JobControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/cancel", summary="Cancel at the next safe boundary")
def cancel_application(
    application_id: int,
    request: Request,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return request_control(application_id, "cancel")
    except JobControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/resume", summary="Resume from the last checkpoint")
def resume_pipeline_application(
    application_id: int,
    request: Request,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return resume_application(application_id)
    except (JobControlError, ReprocessConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


@router.post("/applications/{application_id}/restart", summary="Start a new controlled attempt")
def restart_pipeline_application(
    application_id: int,
    request: Request,
    from_checkpoint: bool = True,
    refresh_cached_ocr: bool = False,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return restart_application(
            application_id,
            from_checkpoint=from_checkpoint,
            refresh_cached_ocr=refresh_cached_ocr,
        )
    except ReprocessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


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
