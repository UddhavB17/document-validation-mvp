"""Decision API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/decision", tags=["decision"])


@router.post("")
def create_decision(payload: dict) -> dict[str, object]:
    return {"status": "received", "payload": payload}
