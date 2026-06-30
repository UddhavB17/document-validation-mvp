"""Upload API routes."""

from datetime import datetime
from pathlib import Path
import re

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from database.db import get_connection, init_db
from services.file_validator import validate_file, validate_upload
from services.pipeline import run_pipeline

router = APIRouter(prefix="/upload", tags=["upload"])
UPLOAD_DIR = Path("data/uploads")


class PartnerPayload(BaseModel):
    """JSON structure produced by the OCR/extraction partner."""

    loan_id: str
    applicant_name: str | None = None
    coapplicant_name: str | None = None
    product_type: str = "LAP"
    branch: str | None = None
    digital_text: dict
    scanned_docs: dict


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned.strip("_") or "loan"


@router.post("/json", summary="Ingest partner OCR JSON payload")
async def ingest_partner_json(payload: PartnerPayload) -> dict[str, object]:
    init_db()
    from services.pipeline import run_partner_json_pipeline

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (
                loan_id,
                applicant_name,
                coapplicant_name,
                product_type,
                branch,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.loan_id,
                payload.applicant_name,
                payload.coapplicant_name,
                payload.product_type,
                payload.branch,
                "processing",
            ),
        )
        application_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (application_id, "partner_json_ingested", f"Ingested partner JSON for {payload.loan_id}"),
        )

    result = run_partner_json_pipeline(
        payload.model_dump(),
        application_id,
        system_data={
            "loan_id": payload.loan_id,
            "applicant_name": payload.applicant_name,
            "coapplicant_name": payload.coapplicant_name,
            "product_type": payload.product_type,
            "branch": payload.branch,
        },
        product_type=payload.product_type,
    )

    return {
        "application_id": application_id,
        "loan_id": payload.loan_id,
        "digital_fields_received": list(payload.digital_text.keys()),
        "scanned_docs_received": list(payload.scanned_docs.keys()),
        "status": result["final_status"],
        "pipeline_status": result["pipeline_status"],
        "documents_found": result["documents_found"],
        "documents_missing": result["documents_missing"],
        "anomaly_count": len(result["anomalies"]),
    }


@router.post("/file", summary="Validate raw PDF file only")
async def validate_uploaded_file(file: UploadFile) -> dict[str, object]:
    validation = validate_upload(file.filename or "", file_size_bytes=file.size or 0)
    if not validation["is_valid"]:
        raise HTTPException(status_code=422, detail=validation["errors"])
    return {"filename": file.filename, "validation": validation}


@router.post("")
async def upload_file(
    background_tasks: BackgroundTasks,
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

    system_data = {
        "loan_id": loan_id,
        "applicant_name": applicant_name,
        "coapplicant_name": coapplicant_name,
        "product_type": product_type,
        "branch": branch,
    }
    with get_connection() as connection:
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            ("processing", application_id),
        )

    background_tasks.add_task(
        _run_pipeline_task,
        str(file_path),
        application_id,
        system_data,
        product_type,
    )

    return {
        "application_id": application_id,
        "loan_id": loan_id,
        "status": "processing",
        "pipeline_status": "queued",
        "total_pages": validation["total_pages"],
        "digital_pages": validation["digital_pages"],
        "scanned_pages": validation["scanned_pages"],
        "documents_found": [],
        "documents_missing": [],
        "anomaly_count": 0,
    }


def _run_pipeline_task(
    file_path: str,
    application_id: int,
    system_data: dict,
    product_type: str,
) -> None:
    try:
        run_pipeline(
            file_path,
            application_id,
            system_data=system_data,
            product_type=product_type,
        )
    except Exception as exc:  # noqa: BLE001
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET status = ? WHERE id = ?",
                ("pipeline_failed", application_id),
            )
            connection.execute(
                """
                INSERT INTO audit_log (application_id, action, details)
                VALUES (?, ?, ?)
                """,
                (application_id, "pipeline_failed", str(exc)),
            )
