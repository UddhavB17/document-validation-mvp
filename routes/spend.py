"""Total-spend endpoint (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from services.auth.dependencies import require_role
from services.spend import spend_summary

router = APIRouter(
    prefix="/admin/spend",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("")
def get_spend() -> dict:
    """Return total spend so far: LLM + billable Vision OCR, free tiers excluded."""
    return spend_summary()
