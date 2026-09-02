"""Reviewer decision API routes."""

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database.db import get_connection, init_db
from services.audit_service import log_action
from services.reviewer import compute_final_status

router = APIRouter(prefix="/decision", tags=["decision"])

VALID_DECISIONS = {"ACCEPT", "OVERRIDE", "REQUEST_DOCS"}
STATUS_BY_DECISION = {
    "ACCEPT": "verified",
    "OVERRIDE": "verified_with_override",
    "REQUEST_DOCS": "incomplete",
}
UNDO_WINDOW_MINUTES = 10


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
            SELECT id, application_id, decision, reviewer_note, decided_at
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
        raise HTTPException(
            status_code=400, detail="Decision must be ACCEPT, OVERRIDE, or REQUEST_DOCS"
        )

    if len(reviewer_note) <= 10:
        raise HTTPException(status_code=400, detail="Reviewer note must be more than 10 characters")

    decided_at = datetime.now().isoformat()
    new_status = STATUS_BY_DECISION[decision]

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id, status FROM applications WHERE id = ?",
            (payload.application_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Application not found")

        previous_status = existing["status"]
        cursor = connection.execute(
            """
            INSERT INTO reviewer_decisions (application_id, decision, reviewer_note, decided_at)
            VALUES (?, ?, ?, ?)
            """,
            (payload.application_id, decision, reviewer_note, decided_at),
        )
        decision_id = cursor.lastrowid
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (new_status, payload.application_id),
        )

    log_action(
        payload.application_id,
        "reviewer_decision_made",
        {
            "decision": decision,
            "reviewer_note": reviewer_note,
            "new_status": new_status,
            "previous_status": previous_status,
            "decision_id": decision_id,
        },
    )

    return {
        "decision_id": decision_id,
        "application_id": payload.application_id,
        "decision": decision,
        "new_status": new_status,
        "decided_at": decided_at,
        "previous_status": previous_status,
    }


@router.post("/{decision_id}/undo", summary="Undo a recent reviewer decision")
def undo_decision(decision_id: int) -> dict[str, object]:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, application_id, decision, decided_at
            FROM reviewer_decisions
            WHERE id = ?
            """,
            (decision_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Decision not found")

        decided_at = datetime.fromisoformat(str(row["decided_at"]))
        if datetime.now() - decided_at > timedelta(minutes=UNDO_WINDOW_MINUTES):
            raise HTTPException(status_code=400, detail="Undo window expired, contact supervisor")

        application_id = int(row["application_id"])
        anomalies = connection.execute(
            "SELECT severity, rule_id FROM validation_results WHERE application_id = ?",
            (application_id,),
        ).fetchall()
        restored_status = compute_final_status([dict(item) for item in anomalies])

        connection.execute("DELETE FROM reviewer_decisions WHERE id = ?", (decision_id,))
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (restored_status, application_id),
        )

    log_action(
        application_id,
        "decision_undone",
        {"decision_id": decision_id, "restored_status": restored_status},
    )
    return {
        "decision_id": decision_id,
        "application_id": application_id,
        "restored_status": restored_status,
    }
