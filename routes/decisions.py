"""Reviewer decision API routes."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database.db import get_connection, init_db
from services.audit_service import log_action

router = APIRouter(prefix="/decision", tags=["decision"])

VALID_DECISIONS = {"ACCEPT", "OVERRIDE", "REQUEST_DOCS"}
STATUS_BY_DECISION = {
    "ACCEPT": "verified",
    "OVERRIDE": "verified_with_override",
    "REQUEST_DOCS": "incomplete",
}


class DecisionRequest(BaseModel):
    application_id: int
    decision: str
    reviewer_note: str


@router.get("/{application_id}", summary="Get latest decision for an application")
def get_decision(application_id: int) -> dict[str, object]:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT application_id, decision, reviewer_note, decided_at
            FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

    if row is None:
        return {"application_id": application_id, "decision": "pending"}
    return dict(row)


@router.post("")
def create_decision(payload: DecisionRequest) -> dict[str, object]:
    init_db()
    decision = payload.decision.upper()
    reviewer_note = payload.reviewer_note.strip()

    if decision not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail="Decision must be ACCEPT, OVERRIDE, or REQUEST_DOCS")

    if len(reviewer_note) <= 10:
        raise HTTPException(status_code=400, detail="Reviewer note must be more than 10 characters")

    decided_at = datetime.now().isoformat()
    new_status = STATUS_BY_DECISION[decision]

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM applications WHERE id = ?",
            (payload.application_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Application not found")

        connection.execute(
            """
            INSERT INTO reviewer_decisions (application_id, decision, reviewer_note, decided_at)
            VALUES (?, ?, ?, ?)
            """,
            (payload.application_id, decision, reviewer_note, decided_at),
        )
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (new_status, payload.application_id),
        )

    log_action(
        payload.application_id,
        "reviewer_decision_made",
        {"decision": decision, "reviewer_note": reviewer_note, "new_status": new_status},
    )

    return {
        "application_id": payload.application_id,
        "decision": decision,
        "new_status": new_status,
        "decided_at": decided_at,
    }
