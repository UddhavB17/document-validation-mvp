"""Upload API routes."""

from datetime import datetime
import json
from pathlib import Path
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from database.db import get_connection, init_db
from services.file_validator import max_file_size_bytes, validate_file, validate_upload
from services.job_runner import submit_job
from services.progress_tracker import (
    create_pipeline_job,
    get_progress,
    mark_failed,
    mark_completed,
    mark_job_completed,
    mark_job_failed,
    mark_job_started,
    start_tracking,
)
from services.pipeline import run_pipeline
from services.mapped_verification import run_mapped_verification

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


class MappedDocument(BaseModel):
    """Trusted routing information for one document in the uploaded PDF."""

    document_type: str = Field(min_length=1)
    pages: list[int] = Field(min_length=1)
    applicant_role: str = "primary"
    expected_fields: dict[str, object] | None = None
    required: bool = True

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, value: list[int]) -> list[int]:
        if any(page < 1 for page in value):
            raise ValueError("page numbers are one-based and must be positive")
        return list(dict.fromkeys(value))


class MappedManifest(BaseModel):
    """Company reference data plus explicit PDF page/document mapping."""

    loan_id: str = Field(min_length=1)
    applicant_name: str | None = None
    coapplicant_name: str | None = None
    product_type: str = "LAP"
    branch: str | None = None
    reference_data: dict[str, object]
    documents: list[MappedDocument] = Field(min_length=1)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned.strip("_") or "loan"


async def _save_upload_stream(file: UploadFile, file_path: Path) -> int:
    """Stream an upload to disk with a running size limit."""
    bytes_written = 0
    limit = max_file_size_bytes()
    try:
        with file_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > limit:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File too large, max {limit // (1024 * 1024)}MB",
                    )
                output.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    return bytes_written


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


@router.post("/mapped", summary="Verify mapped PDF pages against trusted company JSON")
async def upload_mapped_file(
    manifest: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, object]:
    """Queue deterministic verification without page classification or LLM decisions."""
    init_db()
    try:
        parsed = MappedManifest.model_validate(json.loads(manifest))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid manifest JSON: {exc}") from exc

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_path = UPLOAD_DIR / f"{_safe_name(parsed.loan_id)}_{timestamp}.pdf"
    file_size_bytes = await _save_upload_stream(file, file_path)
    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=validation["error"])

    highest_page = max(page for item in parsed.documents for page in item.pages)
    if highest_page > int(validation["total_pages"]):
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"Mapped page {highest_page} exceeds PDF page count {validation['total_pages']}",
        )

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (
                loan_id, applicant_name, coapplicant_name, product_type, branch, status
            ) VALUES (?, ?, ?, ?, ?, 'processing')
            """,
            (
                parsed.loan_id,
                parsed.applicant_name,
                parsed.coapplicant_name,
                parsed.product_type,
                parsed.branch,
            ),
        )
        application_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, 'mapped_file_uploaded', ?)
            """,
            (application_id, f"Uploaded {file.filename} with {len(parsed.documents)} mapped document(s)"),
        )
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, file_size_kb,
                total_pages, digital_pages, scanned_pages
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                str(file_path),
                file.filename,
                round(file_size_bytes / 1024, 2),
                validation["total_pages"],
                validation["digital_pages"],
                validation["scanned_pages"],
            ),
        )

    mapped_pages = sorted({page for item in parsed.documents for page in item.pages})
    start_tracking(
        application_id,
        total_pages=len(mapped_pages),
        digital_pages=0,
        scanned_pages=len(mapped_pages),
        stage="queued",
        message=f"Queued {len(mapped_pages)} mapped page(s) for deterministic verification",
    )
    job_id = create_pipeline_job(application_id)
    submit_job(
        _run_mapped_pipeline_task,
        job_id,
        str(file_path),
        application_id,
        parsed.model_dump(),
    )
    return {
        "application_id": application_id,
        "job_id": job_id,
        "loan_id": parsed.loan_id,
        "status": "processing",
        "pipeline_status": "queued",
        "mapped_pages": mapped_pages,
        "progress_url": f"/upload/{application_id}/progress",
        "summary_url": f"/verification/summary/{application_id}",
    }


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

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_path = UPLOAD_DIR / f"{_safe_name(loan_id)}_{timestamp}.pdf"
    file_size_bytes = await _save_upload_stream(file, file_path)

    validation = validate_file(file_path, file_size_bytes)
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
                round(file_size_bytes / 1024, 2),
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
    start_tracking(
        application_id,
        total_pages=validation["total_pages"],
        digital_pages=validation["digital_pages"],
        scanned_pages=validation["scanned_pages"],
        stage="queued",
        message="Upload accepted and queued",
    )
    job_id = create_pipeline_job(application_id)

    submit_job(
        _run_pipeline_task,
        job_id,
        str(file_path),
        application_id,
        system_data,
        product_type,
    )

    return {
        "application_id": application_id,
        "job_id": job_id,
        "loan_id": loan_id,
        "status": "processing",
        "pipeline_status": "queued",
        "pipeline_outcome": "queued",
        "progress_url": f"/upload/{application_id}/progress",
        "total_pages": validation["total_pages"],
        "digital_pages": validation["digital_pages"],
        "scanned_pages": validation["scanned_pages"],
        "documents_found": [],
        "documents_missing": [],
        "anomaly_count": 0,
    }


def _run_pipeline_task(
    job_id: int,
    file_path: str,
    application_id: int,
    system_data: dict,
    product_type: str,
) -> None:
    try:
        mark_job_started(job_id)
        result = run_pipeline(
            file_path,
            application_id,
            system_data=system_data,
            product_type=product_type,
        )
        if result.get("pipeline_status") == "failed":
            mark_job_failed(job_id, "Pipeline completed with failed outcome")
        else:
            mark_job_completed(job_id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(job_id, str(exc))
        mark_failed(application_id, str(exc))
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


def _run_mapped_pipeline_task(
    job_id: int,
    file_path: str,
    application_id: int,
    manifest: dict[str, object],
) -> None:
    try:
        mark_job_started(job_id)
        result = run_mapped_verification(file_path, application_id, manifest)
        mark_job_completed(job_id)
        mark_completed(application_id, str(result["final_status"]), "completed")
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(job_id, str(exc))
        mark_failed(application_id, str(exc))
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


@router.get("/{application_id}/progress", summary="Get upload processing progress")
def upload_progress(application_id: int) -> dict[str, object]:
    init_db()
    progress = get_progress(application_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found for application")
    return progress
