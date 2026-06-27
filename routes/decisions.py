"""Decision API routes.

Exposes:
  GET  /decision/{application_id}   – fetch current decision for an application
  POST /decision/{application_id}   – override / record a manual decision
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/decision", tags=["decision"])


# ── Pydantic schemas ──────────────────────────

class DecisionOverride(BaseModel):
    """Manual reviewer decision recorded against an application."""

    decision: str           # e.g. "approve" | "reject" | "refer"
    reviewer_id: str
    notes: str | None = None


# ── Endpoints ─────────────────────────────────

@router.get("/{application_id}", summary="Get decision for an application")
def get_decision(application_id: int) -> dict[str, object]:
    """Return the current system decision for the given application.

    TODO: query DB decisions table.
    """
    return {"application_id": application_id, "decision": "pending"}


@router.post("/{application_id}", summary="Record a manual decision override")
def create_decision(application_id: int, payload: DecisionOverride) -> dict[str, object]:
    """Persist a reviewer's manual decision and trigger audit logging.

    TODO: write to DB, call audit_service.record_audit_event().
    """
    return {
        "application_id": application_id,
        "decision": payload.decision,
        "reviewer_id": payload.reviewer_id,
        "status": "recorded",
    }
