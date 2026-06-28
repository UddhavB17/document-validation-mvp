"""Upload API routes.

Accepts:
  POST /upload          – receive partner JSON payload (OCR output)
  POST /upload/file     – receive raw PDF (validation only; OCR handled externally)
"""

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from services.file_validator import validate_upload

router = APIRouter(prefix="/upload", tags=["upload"])


# ── Pydantic schemas ──────────────────────────

class PartnerPayload(BaseModel):
    """JSON structure produced by the OCR/extraction partner.

    The PDF is split into two sections:
    - digital_text  : dict of fields extracted from the loan application form pages.
    - scanned_docs  : dict mapping document name → extracted text / metadata.
    """

    loan_id: str
    digital_text: dict          # form fields from the first few digital pages
    scanned_docs: dict          # classified scanned document images from remaining pages


# ── Endpoints ─────────────────────────────────

@router.post("/json", summary="Ingest partner OCR JSON payload")
async def ingest_partner_json(payload: PartnerPayload) -> dict[str, object]:
    """Receive structured JSON from the OCR partner and queue it for processing.

    TODO: persist to DB, trigger checklist evaluation pipeline.
    """
    # Placeholder – will call checklist_engine and persist results
    return {
        "loan_id": payload.loan_id,
        "digital_fields_received": list(payload.digital_text.keys()),
        "scanned_docs_received": list(payload.scanned_docs.keys()),
        "status": "queued",
    }


@router.post("/file", summary="Upload raw PDF for file-level validation only")
async def upload_file(file: UploadFile) -> dict[str, object]:
    """Validate a PDF upload at the file level (size, mime type).

    The actual content extraction is performed by the OCR partner separately.
    """
    validation = validate_upload(file.filename or "")
    if not validation["is_valid"]:
        raise HTTPException(status_code=422, detail=validation["errors"])
    return {"filename": file.filename, "validation": validation}
