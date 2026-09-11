"""Operations routes for non-technical users. Owned by ``ws-f-accuracy-ops-api``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from database.db import get_connection
from services.auth.dependencies import get_current_user

router = APIRouter(
    prefix="/ops", tags=["ops"], dependencies=[Depends(get_current_user)]
)


@router.get("/applications/{application_id}")
def get_ops_application(application_id: int) -> dict[str, Any]:
    """Return the operator-facing payload for one application (§5)."""
    from services.ops_presentation import build_ops_payload

    try:
        return build_ops_payload(application_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")


@router.get("/worklist")
def get_ops_worklist() -> dict[str, list[dict[str, Any]]]:
    """Return operations worklist rows (no technical fields)."""
    # TODO(ws-d): scope this listing to the caller's role/ownership.
    with get_connection() as connection:
        try:
            rows = connection.execute(
                "SELECT * FROM applications ORDER BY id DESC"
            ).fetchall()
        except Exception:
            return {"applications": []}
        applications = [dict(row) for row in rows]
        counts: dict[int, int] = {}
        try:
            for row in connection.execute(
                "SELECT application_id, COUNT(*) AS n FROM validation_results "
                "WHERE COALESCE(status, '') != ? GROUP BY application_id",
                ("dismissed_by_llm",),
            ).fetchall():
                counts[int(row["application_id"])] = int(row["n"])
        except Exception:
            counts = {}
    items = []
    for application in applications:
        try:
            app_id = int(application.get("id"))
        except (TypeError, ValueError):
            continue
        status = str(application.get("status") or "")
        items.append(
            {
                "application_id": app_id,
                "loan_id": application.get("loan_id"),
                "applicant_name": application.get("applicant_name"),
                "status": status,
                "findings_count": counts.get(app_id, 0),
                "updated_at": application.get("updated_at"),
            }
        )
    return {"applications": items}
