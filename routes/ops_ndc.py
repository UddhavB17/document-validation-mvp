"""Operations NDC checklist state routes (tmp/user-portal-ux).

Manual ticks for the paper checklist live in ``ops_ndc_checks``; system
ticks come from the pipeline checklist at read time. Completing every row
unlocks the normal ACCEPT decision (which sets status ``verified``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.db import get_connection
from services.auth.dependencies import CurrentUser, get_current_user
from services.ops_ndc import NDC_ROLES, build_ndc_state

router = APIRouter(
    prefix="/ops", tags=["ops"], dependencies=[Depends(get_current_user)]
)


class NdcCheckRequest(BaseModel):
    s_no: int
    role: str
    checked: bool


@router.get("/applications/{application_id}/ndc")
def get_ndc_state(application_id: int) -> dict:
    try:
        return build_ndc_state(application_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")


@router.put("/applications/{application_id}/ndc")
def set_ndc_check(
    application_id: int,
    payload: NdcCheckRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    role = payload.role.strip().lower()
    if role not in NDC_ROLES:
        raise HTTPException(status_code=400, detail="Role must be cso or cops")
    if payload.s_no < 1 or payload.s_no > 44:
        raise HTTPException(status_code=400, detail="s_no must be between 1 and 44")

    with get_connection() as connection:
        exists = connection.execute(
            "SELECT id FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Application not found")
        if payload.checked:
            checked_at = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT INTO ops_ndc_checks (application_id, s_no, role, checked_by, checked_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(application_id, s_no, role) DO UPDATE SET
                    checked_by = excluded.checked_by,
                    checked_at = excluded.checked_at
                """,
                (application_id, payload.s_no, role, user.id, checked_at),
            )
        else:
            connection.execute(
                "DELETE FROM ops_ndc_checks WHERE application_id = ? AND s_no = ? AND role = ?",
                (application_id, payload.s_no, role),
            )

    try:
        return build_ndc_state(application_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Application not found")
