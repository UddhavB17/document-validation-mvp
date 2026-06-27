"""Upload API routes."""

from datetime import datetime
from pathlib import Path
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from database.db import get_connection, init_db
from services.file_validator import validate_file

router = APIRouter(prefix="/upload", tags=["upload"])
UPLOAD_DIR = Path("data/uploads")


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned.strip("_") or "loan"


@router.post("")
async def upload_file(
    loan_id: str = Form(...),
    applicant_name: str = Form(...),
    coapplicant_name: str | None = Form(None),
    product_type: str = Form(...),
    branch: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, object]:
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    file_bytes = await file.read()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_path = UPLOAD_DIR / f"{_safe_name(loan_id)}_{timestamp}.pdf"
    file_path.write_bytes(file_bytes)

    validation = validate_file(file_path, len(file_bytes))
    if not validation["valid"]:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=validation["error"])

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (
                loan_id,
                applicant_name,
                coapplicant_name,
                product_type,
                branch
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (loan_id, applicant_name, coapplicant_name, product_type, branch),
        )
        application_id = cursor.lastrowid

        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id,
                file_path,
                original_filename,
                file_size_kb,
                total_pages,
                digital_pages,
                scanned_pages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                str(file_path),
                file.filename,
                round(len(file_bytes) / 1024, 2),
                validation["total_pages"],
                validation["digital_pages"],
                validation["scanned_pages"],
            ),
        )

        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (application_id, "file_uploaded", f"Uploaded {file.filename}"),
        )

    return {
        "application_id": application_id,
        "loan_id": loan_id,
        "status": "uploaded",
        "total_pages": validation["total_pages"],
        "digital_pages": validation["digital_pages"],
        "scanned_pages": validation["scanned_pages"],
    }
