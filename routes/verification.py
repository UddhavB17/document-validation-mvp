"""Verification report API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database.db import init_db
from services.verification_report_store import load_verification_report

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/{application_id}")
def get_verification_report(application_id: int) -> dict[str, object]:
    """Return the stored document verification report for an application."""
    init_db()
    report = load_verification_report(application_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No verification report found for application {application_id}",
        )
    return report.model_dump(mode="json")
