"""Upload API routes."""

from fastapi import APIRouter, UploadFile

from services.file_validator import validate_upload

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("")
async def upload_file(file: UploadFile) -> dict[str, object]:
    validation = validate_upload(file.filename or "")
    return {"filename": file.filename, "validation": validation}
