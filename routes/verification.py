"""Verification report API routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from database.db import get_connection, init_db
from database.models import ChecklistVerificationResponse
from services.checklist_output import build_checklist_verification_response
from services.verification_report_store import load_verification_report

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/checklist/{application_id}", response_model=ChecklistVerificationResponse)
def get_checklist_verification(
    application_id: int,
    include_narration: bool = False,
) -> ChecklistVerificationResponse:
    """Return the 44-item deterministic NDC checklist output for an application."""
    init_db()
    stored = _load_application_checklist_inputs(application_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
    return build_checklist_verification_response(
        loan_file_id=stored["loan_file_id"],
        pages=stored["pages"],
        anomalies=stored["anomalies"],
        product_type=stored["product_type"],
        include_narration=include_narration,
    )


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


def _load_application_checklist_inputs(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        application = connection.execute(
            "SELECT id, loan_id, product_type FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if application is None:
            return None
        pages = connection.execute(
            "SELECT * FROM pages WHERE application_id = ? ORDER BY page_number",
            (application_id,),
        ).fetchall()
        anomalies = connection.execute(
            "SELECT * FROM validation_results WHERE application_id = ?",
            (application_id,),
        ).fetchall()

    return {
        "loan_file_id": str(application["loan_id"] or application_id),
        "product_type": str(application["product_type"] or "LAP"),
        "pages": [_coerce_page(row) for row in pages],
        "anomalies": [dict(row) for row in anomalies],
    }


def _coerce_page(row: Any) -> dict[str, Any]:
    payload = dict(row)
    try:
        decoded = json.loads(payload.get("extracted_fields") or "{}")
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    payload["extracted_fields"] = decoded if isinstance(decoded, dict) else {}
    return payload
