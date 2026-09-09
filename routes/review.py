"""Read-only reviewer API routes used by the Next.js UI."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from database.db import init_db
from services.auth.dependencies import get_current_user, require_role
from services.checklist_service import (
    get_ai_checkable_items,
    get_all_checklist_items,
    get_human_review_items,
)
from services.checklist_status import build_checklist_status
from services.job_control import JobControlError, request_control
from services.ocr_json_export import build_ocr_document_json
from services.progress_tracker import get_progress
from services.reprocessing import (
    ReprocessConflictError,
    queue_application_reprocess,
    restart_application,
    resume_application,
)
from services.review.comparison_matrix import build_comparison_matrix_and_relationships
from services.review.document_summaries import build_document_summaries
from services.review.repository import (
    load_application_review_data,
    load_latest_decision,
    load_latest_uploaded_file,
    load_saved_document_ocr_json,
    load_today_activity,
)
from services.review.worklist import build_worklist
from services.reviewer import load_reviewer_summary, summarize_for_display

router = APIRouter(prefix="/review", tags=["review"], dependencies=[Depends(get_current_user)])
LOGGER = logging.getLogger(__name__)

# In-memory LRU of rendered evidence pages, keyed by
# (application_id, page, dpi, highlight, source_sha256), capped at 64 pages.
_PAGE_CACHE: OrderedDict[tuple[int, int, int, str, str], bytes] = OrderedDict()
_PAGE_CACHE_LOCK = threading.Lock()
_PAGE_CACHE_SIZE = 64


def _page_cache_get(key: tuple[int, int, int, str, str]) -> bytes | None:
    with _PAGE_CACHE_LOCK:
        hit = _PAGE_CACHE.get(key)
        if hit is not None:
            _PAGE_CACHE.move_to_end(key)
        return hit


def _page_cache_put(key: tuple[int, int, int, str, str], image: bytes) -> None:
    with _PAGE_CACHE_LOCK:
        _PAGE_CACHE[key] = image
        _PAGE_CACHE.move_to_end(key)
        while len(_PAGE_CACHE) > _PAGE_CACHE_SIZE:
            _PAGE_CACHE.popitem(last=False)


def _application_source_bytes(application_id: int) -> tuple[bytes, str]:
    """Return ``(pdf_bytes, filename)`` for an application, store first.

    New uploads are served from the object store via ``object_refs``
    (``source``, falling back to ``normalized_pdf``). Legacy rows that still
    carry a ``file_path`` on disk are served from there so the archive stays
    readable (contracts §2).
    """
    from services.storage import get_store
    from services.storage.refs import get_ref

    ref = get_ref("applications", application_id, "source") or get_ref(
        "applications", application_id, "normalized_pdf"
    )
    if ref is not None:
        try:
            pdf_bytes = get_store().get(str(ref["storage_key"]))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Source PDF not found") from exc
        filename = Path(str(ref["storage_key"])).name
        row = load_latest_uploaded_file(application_id) or {}
        return pdf_bytes, str(row.get("original_filename") or filename)
    row = load_latest_uploaded_file(application_id)
    if row is None or not row.get("file_path"):
        raise HTTPException(status_code=404, detail="Source PDF not found")
    file_path = Path(str(row["file_path"]))
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return file_path.read_bytes(), str(row.get("original_filename") or file_path.name)


@router.get("/worklist")
def get_worklist() -> dict[str, list[dict[str, Any]]]:
    """Return the reviewer worklist for the Next.js UI."""
    init_db()
    return build_worklist()


@router.get("/activity/today", dependencies=[Depends(require_role("admin"))])
def get_today_activity() -> dict[str, Any]:
    """Return today's reviewer decision summary."""
    init_db()
    decision_rows = load_today_activity()
    return {
        "total": len(decision_rows),
        "accepted": sum(1 for row in decision_rows if row["decision"] == "ACCEPT"),
        "overridden": sum(1 for row in decision_rows if row["decision"] == "OVERRIDE"),
        "sent_back": sum(1 for row in decision_rows if row["decision"] == "REQUEST_DOCS"),
        "rows": decision_rows,
    }


@router.get(
    "/applications/{application_id}",
    dependencies=[Depends(require_role("admin"))],
)
def get_application_review(application_id: int) -> dict[str, Any]:
    """Return the full reviewer detail payload for one application."""
    init_db()
    data = load_application_review_data(application_id)
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
    failed_ai_snos = {
        anomaly.get("s_no") for anomaly in anomalies if anomaly.get("s_no") is not None
    }

    ocr_data = load_saved_document_ocr_json(application_id)
    matrix_and_rels = build_comparison_matrix_and_relationships(
        application_id,
        data,
        ocr_data=ocr_data,
    )
    documents = build_document_summaries(data.get("document_pages") or {}, anomalies)

    return {
        **data,
        "summary": summary,
        "reviewer_summary": reviewer_summary,
        "manual_review_items": manual_items,
        "checklist": {
            "total": len(checklist_rows),
            "found": len([row for row in checklist_rows if row["status"] == "required_and_present"]),
            "missing": len([row for row in checklist_rows if row["status"] == "required_and_missing"]),
            "not_checked": len(
                [row for row in checklist_rows if row["status"] in {"not_evaluated_by_engine", "manual_review"}]
            ),
            "rows": checklist_rows,
        },
        "ai_checklist": {
            "passed": len([item for item in ai_items if item.get("s_no") not in failed_ai_snos]),
            "total": len(ai_items),
        },
        "latest_decision": load_latest_decision(application_id),
        "progress": get_progress(application_id),
        "comparison_matrix": matrix_and_rels["comparison_matrix"],
        "relationships": matrix_and_rels["relationships"],
        "documents": documents,
    }


@router.get(
    "/applications/{application_id}/source-pdf",
    summary="View the original PDF evidence",
    dependencies=[Depends(require_role("admin"))],
)
def get_application_source_pdf(application_id: int) -> StreamingResponse:
    init_db()
    pdf_bytes, filename = _application_source_bytes(application_id)

    def _stream() -> Any:
        yield pdf_bytes

    return StreamingResponse(
        _stream(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get(
    "/applications/{application_id}/source-page/{page_number}",
    summary="Render one source PDF page for evidence review",
)
def get_application_source_page(
    application_id: int,
    page_number: int,
    highlight: str | None = None,
    dpi: int = Query(default=150, ge=72, le=288),
) -> Response:
    from services.pdf_processor import render_source_page

    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be one or greater")
    init_db()
    pdf_bytes, _ = _application_source_bytes(application_id)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    cache_key = (application_id, page_number, dpi, highlight or "", digest)
    cached = _page_cache_get(cache_key)
    if cached is not None:
        return Response(
            content=cached,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=300"},
        )
    try:
        image_bytes = render_source_page(pdf_bytes, page_number, dpi=dpi, highlight=highlight)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Source page not found") from exc
    except ValueError as exc:
        LOGGER.warning(
            "Could not render source PDF page %s for application %s",
            page_number,
            application_id,
            exc_info=exc,
        )
        raise HTTPException(status_code=422, detail="Source PDF could not be rendered") from exc
    _page_cache_put(cache_key, image_bytes)
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post(
    "/applications/{application_id}/reprocess",
    summary="Retry a stale or failed PDF pipeline",
    dependencies=[Depends(require_role("admin"))],
)
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


@router.post(
    "/applications/{application_id}/pause",
    summary="Pause at the next safe boundary",
    dependencies=[Depends(require_role("admin"))],
)
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


@router.post(
    "/applications/{application_id}/cancel",
    summary="Cancel at the next safe boundary",
    dependencies=[Depends(require_role("admin"))],
)
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


@router.post(
    "/applications/{application_id}/resume",
    summary="Resume from the last checkpoint",
    dependencies=[Depends(require_role("admin"))],
)
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


@router.post(
    "/applications/{application_id}/restart",
    summary="Start a new controlled attempt",
    dependencies=[Depends(require_role("admin"))],
)
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


@router.get(
    "/applications/{application_id}/ocr-json",
    dependencies=[Depends(require_role("admin"))],
)
def get_application_ocr_json(application_id: int) -> dict[str, Any]:
    """Build the OCR JSON payload on demand and persist it to the object store."""
    import json

    from services.storage import get_store
    from services.storage.refs import record_ref

    init_db()
    data = load_application_review_data(application_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Application not found")
    payload = build_ocr_document_json(
        application_id,
        data.get("pages") or [],
        page_events=data.get("page_events") or [],
    )
    storage_key = f"applications/{application_id}/ocr-export.json"
    try:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        get_store().put(storage_key, encoded, "application/json")
        record_ref(
            "applications",
            application_id,
            "ocr_export",
            storage_key,
            content_type="application/json",
            size_bytes=len(encoded),
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Could not persist OCR export for application %s", application_id, exc_info=exc
        )
    return payload
