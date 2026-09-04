"""Lightweight review polling endpoints (ws-a data diet).

The frontend polls ``GET /review/applications/{id}/status`` while a job runs
instead of the full review payload, so this response carries progress only
and stays under 5 KB. Per-page OCR text is fetched explicitly via
``GET /review/applications/{id}/pages/{n}/text``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from database.db import get_connection
from services.review.repository import load_page_text

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/applications/{application_id}/status")
def get_application_status(application_id: int) -> dict[str, Any]:
    """Return compact processing status for frontend polling (<= 5 KB)."""
    with get_connection() as connection:
        application_row = connection.execute(
            "SELECT id, status, updated_at FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if application_row is None:
            raise HTTPException(status_code=404, detail="Application not found")
        progress_row = connection.execute(
            """
            SELECT stage, percentage, processed_pages, total_pages, updated_at
            FROM pipeline_progress
            WHERE application_id = ?
            """,
            (application_id,),
        ).fetchone()
        job_row = connection.execute(
            """
            SELECT id, status, attempt, failure_reason
            FROM pipeline_jobs
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    application = dict(application_row)
    progress = dict(progress_row) if progress_row else {}
    job = dict(job_row) if job_row else None
    total_pages = int(progress.get("total_pages") or 0)
    completed_pages = int(progress.get("processed_pages") or 0)
    return {
        "application_id": application["id"],
        "status": application.get("status"),
        "progress": {
            "stage": progress.get("stage"),
            "percentage": progress.get("percentage", 0),
            "completed_pages": completed_pages,
            "total_pages": total_pages,
        },
        "updated_at": progress.get("updated_at") or application.get("updated_at"),
        "job": (
            {
                "id": job.get("id"),
                "status": job.get("status"),
                "attempt": job.get("attempt"),
                "failure_reason": job.get("failure_reason"),
            }
            if job is not None
            else None
        ),
    }


@router.get("/applications/{application_id}/pages/{page_number}/text")
def get_application_page_text(application_id: int, page_number: int) -> dict[str, Any]:
    """Return one page's OCR text with confidence and document type."""
    # TODO(ws-d): require_role("admin")
    page = load_page_text(application_id, page_number)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page
