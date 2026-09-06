"""Direct object access for the local storage backend (owned by ``ws-b-storage-db``)."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from services.auth.dependencies import require_role
from services.storage import LocalObjectStore

# fx-integrate-df: loan PDFs are served here; admin-only (contracts §6).
# One-line cross-stream edit (file owned by ws-b-storage-db).
router = APIRouter(
    prefix="/storage", tags=["storage"], dependencies=[Depends(require_role("admin"))]
)


@router.get("/{key:path}", summary="Serve one object from the local store")
def serve_stored_object(key: str) -> StreamingResponse:
    if not key or key.startswith("/") or ".." in key:
        raise HTTPException(status_code=400, detail="Invalid storage key")
    store = LocalObjectStore()
    if not store.exists(key):
        raise HTTPException(status_code=404, detail="Object not found")
    media_type, _ = mimetypes.guess_type(key)
    return StreamingResponse(
        store.open(key),
        media_type=media_type or "application/octet-stream",
    )
