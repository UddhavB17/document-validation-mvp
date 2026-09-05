"""Upload API routes."""

import json
import logging
import re
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError

from database.db import get_connection, init_db
from services.auth.dependencies import require_role
from services.company_dump_adapter import (
    CompanyDumpConversionError,
    convert_company_database_dump,
    is_company_database_dump,
)
from services.file_validator import (
    max_file_size_bytes,
    validate_file,
    validate_package_upload,
    validate_upload,
)
from services.job_control import PipelineCancelled
from services.job_runner import enqueue, submit_job
from services.paths import job_work_dir, upload_dir
from services.pipeline import run_pipeline
from services.pipeline.input_preparation import cleanup_job_source
from services.progress_tracker import (
    create_pipeline_job,  # noqa: F401  # kept: tests call upload_route.create_pipeline_job
    get_progress,
    start_tracking,
)
from services.storage import get_store
from services.storage.refs import get_ref, record_ref
from services.verification_manifest import VerificationManifest
from services.zip_package import (
    PackageValidationError,
    normalize_zip_package,
)

router = APIRouter(
    prefix="/upload", tags=["upload"], dependencies=[Depends(require_role("admin"))]
)
# Compat shim: historical staging root. New code stages uploads under
# DMEF_JOB_WORK_DIR and persists bytes through the object store, so nothing
# is written here. Kept so existing monkeypatching (UPLOAD_DIR) keeps working.
UPLOAD_DIR = upload_dir()
LOGGER = logging.getLogger(__name__)


def _new_upload_work_dir(prefix: str) -> Path:
    """Create a per-upload scratch dir under ``DMEF_JOB_WORK_DIR``."""
    work_dir = job_work_dir() / f"{prefix}-{uuid4().hex}"
    work_dir.mkdir(parents=True, exist_ok=False)
    return work_dir


def _cleanup_work_dir(path: Path | None) -> None:
    """Remove a job-scoped work dir; legacy/test paths are never touched."""
    if path is not None:
        cleanup_job_source(path if path.is_dir() else path.parent)


def _safe_stemmed_name(filename: str, default_suffix: str) -> str:
    """Sanitize an upload filename while preserving its extension."""
    base = Path(filename or "").name or f"upload{default_suffix}"
    suffix = Path(base).suffix.lower() or default_suffix
    return f"{_safe_name(Path(base).stem) or 'upload'}{suffix}"


def _application_source_key(application_id: int, filename: str) -> str:
    return f"applications/{application_id}/source/{_safe_stemmed_name(filename, '.pdf')}"


def _intake_source_key(package_id: str, filename: str) -> str:
    return f"intake/{package_id}/{_safe_stemmed_name(filename, '.zip')}"


def _store_bytes(key: str, data: bytes, content_type: str) -> None:
    store = get_store()
    stream = BytesIO(data)
    store.put(key, stream, content_type or "application/octet-stream")


class PartnerPayload(BaseModel):
    """JSON structure produced by the OCR/extraction partner."""

    loan_id: str
    applicant_name: str | None = None
    coapplicant_name: str | None = None
    product_type: str = "LAP"
    branch: str | None = None
    application_date: str | None = None
    digital_text: dict
    scanned_docs: dict


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
        created = connection.execute(
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
            RETURNING id
            """,
            (
                payload.loan_id,
                payload.applicant_name,
                payload.coapplicant_name,
                payload.product_type,
                payload.branch,
                "processing",
            ),
        ).fetchone()
        if created is None:
            raise HTTPException(status_code=500, detail="Failed to create application")
        application_id = int(created["id"])
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (
                application_id,
                "partner_json_ingested",
                f"Ingested partner JSON for {payload.loan_id}",
            ),
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
            "application_date": payload.application_date,
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
        "anomaly_count": result.get("actionable_anomaly_count", len(result["anomalies"])),
        "raw_anomaly_count": len(result["anomalies"]),
    }


@router.post("/file", summary="Validate raw PDF file only")
async def validate_uploaded_file(file: UploadFile) -> dict[str, object]:
    validation = validate_upload(file.filename or "", file_size_bytes=file.size or 0)
    if not validation["is_valid"]:
        raise HTTPException(status_code=422, detail=validation["errors"])
    return {"filename": file.filename, "validation": validation}


@router.post("/mapped", summary="Verify mapped PDF pages against trusted company JSON")
async def upload_mapped_file(
    manifest: str | None = Form(None),
    case_type: Literal["Normal Case", "BT Case"] = Form("Normal Case"),
    file: UploadFile = File(...),
) -> dict[str, object]:
    """Queue shared PDF processing plus trusted mapped JSON comparison."""
    init_db()

    work_dir = _new_upload_work_dir("mapped")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    uploaded_name = file.filename or "mapped_upload"
    file_path: Path | None = None

    if Path(uploaded_name).suffix.lower() == ".zip":
        try:
            file_path, manifest_text, original_filename = await _save_mapped_zip_package(
                file, manifest, timestamp
            )
        except Exception:
            _cleanup_work_dir(work_dir)
            raise
    else:
        if not manifest or not manifest.strip():
            _cleanup_work_dir(work_dir)
            raise HTTPException(
                status_code=422, detail="Manifest JSON is required for mapped PDF upload"
            )
        file_path = work_dir / f"mapped_{timestamp}.pdf"
        try:
            await _save_upload_stream(file, file_path)
        except Exception:
            _cleanup_work_dir(work_dir)
            raise
        manifest_text = manifest
        original_filename = uploaded_name

    try:
        parsed = _parse_manifest(manifest_text)
        parsed.case_type = case_type
    except HTTPException:
        _cleanup_work_dir(file_path.parent)
        _cleanup_work_dir(work_dir)
        raise

    file_size_bytes = file_path.stat().st_size
    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        _cleanup_work_dir(file_path.parent)
        _cleanup_work_dir(work_dir)
        raise HTTPException(status_code=400, detail=validation["error"])

    try:
        result = _queue_mapped_verification(
            parsed,
            file_path=file_path,
            original_filename=original_filename,
            file_size_bytes=file_size_bytes,
            validation=validation,
            audit_action="mapped_file_uploaded",
        )
    except Exception:
        _cleanup_work_dir(file_path.parent)
        _cleanup_work_dir(work_dir)
        raise
    _cleanup_work_dir(file_path.parent)
    _cleanup_work_dir(work_dir)
    return result


@router.post("/package", summary="Prepare an unordered ZIP package for page mapping")
async def upload_zip_package(
    file: UploadFile = File(...),
    background: bool = False,
) -> dict[str, object]:
    """Safely normalize ZIP-contained PDFs/images and return stable page ranges."""
    validation = validate_package_upload(file.filename or "", file_size_bytes=file.size or 0)
    if not validation["is_valid"]:
        raise HTTPException(status_code=422, detail=validation["errors"])

    init_db()
    package_id = uuid4().hex
    source_filename = file.filename or "documents.zip"
    package_dir = job_work_dir() / f"package-{package_id}"
    package_dir.mkdir(parents=True, exist_ok=False)
    zip_path = package_dir / "source.zip"
    try:
        await _save_upload_stream(file, zip_path)
        if background:
            _write_package_preparation_progress(
                package_dir,
                {
                    "package_id": package_id,
                    "status": "queued",
                    "stage": "queued",
                    "message": "ZIP uploaded; waiting to scan package contents",
                    "processed_files": 0,
                    "total_files": 0,
                },
            )
            submit_job(
                _prepare_zip_package_task,
                package_id,
                source_filename,
                zip_path,
                package_dir,
            )
            return {
                "package_id": package_id,
                "source_filename": source_filename,
                "status": "queued",
                "progress_url": f"/upload/package/{package_id}/preparation",
            }
        normalized = normalize_zip_package(zip_path, package_dir)
        pdf_path = Path(str(normalized["normalized_pdf_path"]))
        pdf_validation = validate_file(pdf_path, pdf_path.stat().st_size)
        if not pdf_validation["valid"]:
            raise PackageValidationError(str(pdf_validation["error"]))
        zip_key, normalized_pdf_key = _store_intake_package(
            package_id, source_filename, zip_path, pdf_path, package_dir
        )
        _persist_intake_package(
            package_id,
            source_filename,
            zip_key,
            normalized_pdf_key,
            normalized,
        )
        # Sync path only: staging lives in DMEF_JOB_WORK_DIR; later steps
        # read via the store. (Background cleanup happens in the task.)
        _cleanup_work_dir(package_dir)
    except (PackageValidationError, ValueError) as exc:
        _cleanup_work_dir(package_dir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        _cleanup_work_dir(package_dir)
        raise

    return {
        "package_id": package_id,
        "source_filename": source_filename,
        "status": "prepared",
        "total_files": normalized["total_files"],
        "total_pages": normalized["total_pages"],
        "documents": normalized["documents"],
        "verify_url": f"/upload/package/{package_id}/verify",
    }


def _store_intake_package(
    package_id: str,
    source_filename: str,
    zip_path: Path,
    normalized_pdf_path: Path,
    package_dir: Path,
) -> tuple[str, str]:
    """Upload ZIP artifacts to the object store and record ``object_refs``."""
    zip_bytes = zip_path.read_bytes()
    pdf_bytes = normalized_pdf_path.read_bytes()
    zip_key = _intake_source_key(package_id, source_filename)
    normalized_pdf_key = f"intake/{package_id}/normalized.pdf"
    manifest_key = f"intake/{package_id}/manifest.json"
    _store_bytes(zip_key, zip_bytes, "application/zip")
    _store_bytes(normalized_pdf_key, pdf_bytes, "application/pdf")
    manifest_path = package_dir / "package.json"
    if manifest_path.is_file():
        _store_bytes(manifest_key, manifest_path.read_bytes(), "application/json")
        record_ref(
            "intake_packages",
            package_id,
            "manifest",
            manifest_key,
            content_type="application/json",
            size_bytes=manifest_path.stat().st_size,
        )
    record_ref(
        "intake_packages",
        package_id,
        "source",
        zip_key,
        content_type="application/zip",
        size_bytes=len(zip_bytes),
    )
    record_ref(
        "intake_packages",
        package_id,
        "normalized_pdf",
        normalized_pdf_key,
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
    )
    return zip_key, normalized_pdf_key


@router.get(
    "/package/{package_id}/preparation",
    summary="Get ZIP preparation progress and per-file logs",
)
def get_zip_preparation_progress(package_id: str) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{32}", package_id):
        raise HTTPException(status_code=404, detail="ZIP package not found")
    progress_path = job_work_dir() / f"package-{package_id}" / "preparation_progress.json"
    if progress_path.is_file():
        try:
            return json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=503, detail="ZIP progress is being updated") from exc
    # Staging is deleted after preparation; rebuild the terminal state from
    # the persisted intake rows + stored manifest.
    row = _get_package_row(package_id)
    if row["status"] != "prepared":
        raise HTTPException(status_code=404, detail="ZIP preparation progress not found")
    documents = _load_intake_manifest_documents(package_id)
    return {
        "package_id": package_id,
        "source_filename": row["source_filename"],
        "status": "prepared",
        "stage": "completed",
        "message": (
            f"ZIP preparation complete: {row['total_files']} file(s), "
            f"{row['total_pages']} internal page(s)"
        ),
        "processed_files": row["total_files"],
        "total_files": row["total_files"],
        "current_file": None,
        "total_pages": row["total_pages"],
        "documents": documents,
        "verify_url": f"/upload/package/{package_id}/verify",
        "events": [
            {
                "stage": "file_completed",
                "message": f"Normalized {document.get('original_filename')}",
                "processed_files": position,
                "total_files": len(documents),
                "current_file": document.get("original_filename"),
                "document": document,
                "elapsed_seconds": None,
                "timestamp": None,
            }
            for position, document in enumerate(documents, start=1)
        ],
    }


def _load_intake_manifest_documents(package_id: str) -> list[dict[str, object]]:
    """Load ZIP inventory documents from the stored manifest, else from DB rows."""
    ref = get_ref("intake_packages", package_id, "manifest")
    if ref is not None:
        try:
            payload = json.loads(get_store().get(str(ref["storage_key"])).decode("utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
            return [dict(item) for item in payload["documents"]]
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT source_document_id, original_filename, file_type,
                   source_size_bytes, page_count,
                   internal_page_start, internal_page_end
            FROM intake_documents
            WHERE package_id = ?
            ORDER BY internal_page_start
            """,
            (package_id,),
        ).fetchall()
    documents = []
    for row in rows:
        start = int(row["internal_page_start"])
        end = int(row["internal_page_end"])
        documents.append(
            {
                "source_document_id": row["source_document_id"],
                "original_filename": row["original_filename"],
                "file_type": row["file_type"],
                "source_size_bytes": row["source_size_bytes"],
                "page_count": row["page_count"],
                "internal_page_start": start,
                "internal_page_end": end,
                "pages": list(range(start, end + 1)),
            }
        )
    return documents


def _stage_intake_pdf(package_id: str, row: object) -> Path:
    """Stage the intake normalized PDF from the store into a verify work dir."""
    mapping = dict(row)  # type: ignore[arg-type]
    candidate = str(mapping.get("normalized_pdf_path") or "")
    pdf_bytes: bytes | None = None
    ref = get_ref("intake_packages", package_id, "normalized_pdf")
    if ref is not None:
        try:
            pdf_bytes = get_store().get(str(ref["storage_key"]))
        except Exception:
            pdf_bytes = None
    if pdf_bytes is None and candidate:
        local = Path(candidate)
        if local.is_file():
            pdf_bytes = local.read_bytes()
    if pdf_bytes is None:
        raise HTTPException(
            status_code=410, detail="Prepared ZIP package files are no longer available"
        )
    work_dir = job_work_dir() / f"verify-{package_id}-{uuid4().hex}"
    work_dir.mkdir(parents=True, exist_ok=False)
    staged = work_dir / "normalized.pdf"
    staged.write_bytes(pdf_bytes)
    return staged


@router.get("/package/{package_id}", summary="Get prepared ZIP package inventory")
def get_zip_package(package_id: str) -> dict[str, object]:
    row = _get_package_row(package_id)
    return {
        "package_id": package_id,
        "source_filename": row["source_filename"],
        "status": row["status"],
        "total_files": row["total_files"],
        "total_pages": row["total_pages"],
        "documents": _load_intake_manifest_documents(package_id),
        "verify_url": f"/upload/package/{package_id}/verify",
    }


@router.post("/package/{package_id}/verify", summary="Verify a prepared ZIP package")
async def verify_zip_package(
    package_id: str,
    manifest: str = Form(...),
    case_type: Literal["Normal Case", "BT Case"] = Form("Normal Case"),
) -> dict[str, object]:
    """Apply a confirmed manifest to the package's normalized internal PDF."""
    init_db()
    parsed = _parse_manifest(manifest)
    parsed.case_type = case_type
    row = _get_package_row(package_id)
    if row["status"] in {"verifying", "processing"}:
        raise HTTPException(status_code=409, detail="ZIP package verification is already running")

    _validate_package_mapping(package_id, parsed)
    pdf_path = _stage_intake_pdf(package_id, row)
    pdf_validation = validate_file(pdf_path, pdf_path.stat().st_size)
    if not pdf_validation["valid"]:
        _cleanup_work_dir(pdf_path.parent)
        raise HTTPException(status_code=422, detail=pdf_validation["error"])

    with get_connection() as connection:
        updated = connection.execute(
            """
            UPDATE intake_packages SET status = 'verifying'
            WHERE package_id = ? AND status NOT IN ('verifying', 'processing')
            """,
            (package_id,),
        )
        if updated.rowcount != 1:
            _cleanup_work_dir(pdf_path.parent)
            raise HTTPException(
                status_code=409, detail="ZIP package verification has already started"
            )
    try:
        result = _queue_mapped_verification(
            parsed,
            file_path=pdf_path,
            original_filename=str(row["source_filename"]),
            file_size_bytes=pdf_path.stat().st_size,
            validation=pdf_validation,
            audit_action="mapped_package_verification_queued",
            audit_detail=(
                f"Prepared ZIP package {package_id} with {row['total_files']} source document(s)"
            ),
            package_id=package_id,
        )
    except Exception:
        _cleanup_work_dir(pdf_path.parent)
        with get_connection() as connection:
            connection.execute(
                "UPDATE intake_packages SET status = 'prepared' WHERE package_id = ?",
                (package_id,),
            )
        raise

    result["package_id"] = package_id
    result["source_documents"] = int(row["total_files"])
    # The staged verify copy is job-scoped; the pipeline resolves via the store.
    _cleanup_work_dir(pdf_path.parent)
    return result


def _parse_manifest(raw_manifest: str) -> VerificationManifest:
    try:
        try:
            payload = json.loads(raw_manifest)
        except json.JSONDecodeError:
            payload = convert_company_database_dump(raw_manifest)
        if is_company_database_dump(payload):
            payload = convert_company_database_dump(payload)
        return VerificationManifest.model_validate(payload)
    except ValidationError as exc:
        # Surface Pydantic field errors verbatim so users see exactly which field failed
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (json.JSONDecodeError, CompanyDumpConversionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid manifest: {exc}") from exc


def _queue_mapped_verification(
    parsed: VerificationManifest,
    *,
    file_path: Path,
    original_filename: str,
    file_size_bytes: int,
    validation: dict[str, object],
    audit_action: str,
    audit_detail: str | None = None,
    package_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, object]:
    mapped_pages = sorted({page for item in parsed.document_index for page in item.pages})
    automatic_mapping = not parsed.document_index
    highest_page = max(mapped_pages, default=0)
    if highest_page > int(validation["total_pages"]):
        raise HTTPException(
            status_code=422,
            detail=f"Mapped page {highest_page} exceeds PDF page count {validation['total_pages']}",
        )

    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (
                loan_id, applicant_name, coapplicant_name, product_type, branch, status
            ) VALUES (?, ?, ?, ?, ?, 'processing')
            RETURNING id
            """,
            (
                parsed.loan_id,
                parsed.people.get("primary").applicant_name
                if parsed.people.get("primary")
                else None,
                _first_coapplicant_name(parsed),
                parsed.product_type,
                parsed.branch,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="Failed to create application")
        application_id = int(row["id"])
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (
                application_id,
                audit_action,
                audit_detail
                or f"Uploaded {original_filename} with {len(parsed.document_index)} mapped document(s)",
            ),
        )
        if package_id:
            connection.execute(
                """
                UPDATE intake_packages
                SET status = 'processing', application_id = ?, verified_at = NULL
                WHERE package_id = ?
                """,
                (application_id, package_id),
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
                None,
                original_filename,
                round(file_size_bytes / 1024, 2),
                validation["total_pages"],
                validation["digital_pages"],
                validation["scanned_pages"],
            ),
        )

    # Persist the source PDF through the object store (never under data/uploads).
    pdf_bytes = file_path.read_bytes()
    storage_key = _application_source_key(application_id, original_filename)
    try:
        _store_bytes(storage_key, pdf_bytes, "application/pdf")
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to store uploaded PDF") from exc
    record_ref(
        "applications",
        application_id,
        "source",
        storage_key,
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
    )

    covers_entire_pdf = automatic_mapping or len(mapped_pages) == int(validation["total_pages"])
    initial_digital_pages = int(validation["digital_pages"]) if covers_entire_pdf else 0
    initial_scanned_pages = int(validation["scanned_pages"]) if covers_entire_pdf else 0
    start_tracking(
        application_id,
        total_pages=int(validation["total_pages"]) if automatic_mapping else len(mapped_pages),
        digital_pages=initial_digital_pages,
        scanned_pages=initial_scanned_pages,
        stage="queued",
        message=(
            f"Queued {validation['total_pages']} page(s) for automatic identification and verification"
            if automatic_mapping
            else f"Queued {len(mapped_pages)} mapped page(s) for deterministic verification"
        ),
    )
    job_id = -1
    manifest_payload = parsed.pipeline_payload()
    reference_data = manifest_payload.get("reference_data") or {}
    primary_reference = reference_data.get("primary") if isinstance(reference_data, dict) else {}
    primary_reference = primary_reference if isinstance(primary_reference, dict) else {}
    recovery_system_data = {
        **primary_reference,
        "loan_id": manifest_payload.get("loan_id"),
        "product_type": manifest_payload.get("product_type") or "LAP",
        "branch": manifest_payload.get("branch"),
        "application_date": manifest_payload.get("application_date"),
        "reference_data": reference_data,
        "people": reference_data,
        "case_type": manifest_payload.get("case_type") or "Normal Case",
    }
    try:
        job_id = enqueue(
            "mapped_pipeline",
            application_id,
            {
                "source_path": str(file_path),
                "system_data": recovery_system_data,
                "product_type": parsed.product_type,
                "mapped_manifest": manifest_payload,
                "package_id": package_id,
                "generate_llm_summary": True,
            },
            batch_id=batch_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Upload accepted but failed to queue securely for processing",
        ) from exc
    submit_job(
        _run_mapped_pipeline_task,
        job_id,
        str(file_path),
        application_id,
        manifest_payload,
        package_id,
    )
    return {
        "application_id": application_id,
        "job_id": job_id,
        "loan_id": parsed.loan_id,
        "status": "processing",
        "pipeline_status": "queued",
        "mapped_pages": mapped_pages,
        "automatic_mapping": automatic_mapping,
        "progress_url": f"/upload/{application_id}/progress",
        "summary_url": f"/verification/summary/{application_id}",
        "people": sorted(parsed.people),
        "manifest_schema_version": parsed.schema_version,
    }


async def _save_mapped_zip_package(
    file: UploadFile,
    manifest_override: str | None,
    timestamp: str,
) -> tuple[Path, str, str]:
    package_bytes = await _read_upload_bytes(file)
    try:
        archive = zipfile.ZipFile(BytesIO(package_bytes))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="ZIP file is corrupted or unreadable") from exc

    with archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and not PurePosixPath(member.filename).name.startswith(".")
            and "__MACOSX" not in PurePosixPath(member.filename).parts
        ]
        pdf_members = [
            member for member in members if PurePosixPath(member.filename).suffix.lower() == ".pdf"
        ]
        json_members = [
            member for member in members if PurePosixPath(member.filename).suffix.lower() == ".json"
        ]

        if not manifest_override and len(json_members) != 1:
            raise HTTPException(
                status_code=422,
                detail="Mapped ZIP must contain exactly one JSON manifest file, or paste manifest JSON in the form",
            )
        manifest_text = manifest_override or archive.read(json_members[0]).decode("utf-8")
        manifest_payload = _decode_manifest_payload(manifest_text)
        pdf_member = _select_pdf_member(pdf_members, manifest_payload)

        original_filename = PurePosixPath(pdf_member.filename).name
        pdf_bytes = archive.read(pdf_member)
        if not pdf_bytes:
            raise HTTPException(status_code=400, detail="Mapped ZIP PDF file is empty")
        if len(pdf_bytes) > max_file_size_bytes():
            raise HTTPException(
                status_code=400,
                detail=f"File too large, max {max_file_size_bytes() // (1024 * 1024)}MB",
            )

    file_path = job_work_dir() / f"mapped-{timestamp}-{uuid4().hex}" / "source.pdf"
    file_path.parent.mkdir(parents=True, exist_ok=False)
    file_path.write_bytes(pdf_bytes)
    return file_path, manifest_text, original_filename


def _decode_manifest_payload(manifest_text: str) -> dict[str, object]:
    """Parse manifest text into a raw dict for PDF member selection.

    Handles both standard JSON manifests and raw database dumps.
    Full Pydantic validation happens later via ``_parse_manifest``.
    """
    stripped = manifest_text.strip()
    if stripped.startswith(("{", "[")):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            try:
                payload = convert_company_database_dump(stripped)
            except CompanyDumpConversionError as exc:
                raise HTTPException(
                    status_code=422, detail=f"Invalid manifest JSON/database dump: {exc}"
                ) from exc
    else:
        # Raw database dump — convert and use the resulting dict
        try:
            payload = convert_company_database_dump(stripped)
        except CompanyDumpConversionError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Manifest must be a JSON object")
    return payload


def _select_pdf_member(
    pdf_members: list[zipfile.ZipInfo],
    manifest_payload: dict[str, object],
) -> zipfile.ZipInfo:
    if len(pdf_members) == 1:
        return pdf_members[0]

    pdf_names = [member.filename for member in pdf_members]
    if not pdf_members:
        raise HTTPException(
            status_code=422,
            detail="Mapped ZIP does not contain a PDF file. Add one PDF loan packet to the ZIP.",
        )

    requested_pdf = _manifest_pdf_selector(manifest_payload)
    if requested_pdf:
        requested = requested_pdf.replace("\\", "/").strip().lower()
        matches = [
            member
            for member in pdf_members
            if member.filename.lower() == requested
            or PurePosixPath(member.filename).name.lower() == requested
        ]
        if len(matches) == 1:
            return matches[0]
        raise HTTPException(
            status_code=422,
            detail=f"Manifest pdf_file '{requested_pdf}' did not match exactly one PDF in the ZIP. Found PDFs: {', '.join(pdf_names)}",
        )

    raise HTTPException(
        status_code=422,
        detail=(
            "Mapped ZIP contains multiple PDF files. Add a top-level "
            f"'pdf_file' value to the manifest. Found PDFs: {', '.join(pdf_names)}"
        ),
    )


def _manifest_pdf_selector(manifest_payload: dict[str, object]) -> str | None:
    for key in ("pdf_file", "pdf_filename", "source_pdf", "loan_pdf"):
        value = manifest_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _read_upload_bytes(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    bytes_read = 0
    limit = max_file_size_bytes()
    while chunk := await file.read(1024 * 1024):
        bytes_read += len(chunk)
        if bytes_read > limit:
            raise HTTPException(
                status_code=400, detail=f"File too large, max {limit // (1024 * 1024)}MB"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _persist_intake_package(
    package_id: str,
    source_filename: str,
    zip_key: str,
    normalized_pdf_key: str,
    normalized: dict[str, object],
) -> None:
    """Persist intake rows; path columns hold object-store keys (contracts §2)."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO intake_packages (
                package_id, source_filename, source_zip_path, normalized_pdf_path,
                total_files, total_pages, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'prepared')
            """,
            (
                package_id,
                source_filename,
                zip_key,
                normalized_pdf_key,
                normalized["total_files"],
                normalized["total_pages"],
            ),
        )
        for document in normalized["documents"]:
            connection.execute(
                """
                INSERT INTO intake_documents (
                    package_id, source_document_id, original_filename, file_type,
                    source_size_bytes, page_count, internal_page_start, internal_page_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    package_id,
                    document["source_document_id"],
                    document["original_filename"],
                    document["file_type"],
                    document["source_size_bytes"],
                    document["page_count"],
                    document["internal_page_start"],
                    document["internal_page_end"],
                ),
            )


def _prepare_zip_package_task(
    package_id: str,
    source_filename: str,
    zip_path: Path,
    package_dir: Path,
) -> None:
    """Normalize one uploaded ZIP while publishing frontend-safe progress events."""

    def publish(event: dict[str, object]) -> None:
        _write_package_preparation_progress(
            package_dir,
            {
                "package_id": package_id,
                "status": "preparing",
                **event,
            },
            append_event=True,
        )

    try:
        publish(
            {
                "stage": "scanning_archive",
                "message": "Scanning ZIP entries and validating supported file types",
                "processed_files": 0,
                "total_files": 0,
            }
        )
        normalized = normalize_zip_package(
            zip_path,
            package_dir,
            progress_callback=publish,
        )
        pdf_path = Path(str(normalized["normalized_pdf_path"]))
        pdf_validation = validate_file(pdf_path, pdf_path.stat().st_size)
        if not pdf_validation["valid"]:
            raise PackageValidationError(str(pdf_validation["error"]))
        zip_key, normalized_pdf_key = _store_intake_package(
            package_id, source_filename, zip_path, pdf_path, package_dir
        )
        _persist_intake_package(
            package_id, source_filename, zip_key, normalized_pdf_key, normalized
        )
        _write_package_preparation_progress(
            package_dir,
            {
                "package_id": package_id,
                "source_filename": source_filename,
                "status": "prepared",
                "stage": "completed",
                "message": (
                    f"ZIP preparation complete: {normalized['total_files']} file(s), "
                    f"{normalized['total_pages']} internal page(s)"
                ),
                "processed_files": normalized["total_files"],
                "total_files": normalized["total_files"],
                "current_file": None,
                "total_pages": normalized["total_pages"],
                "documents": normalized["documents"],
                "verify_url": f"/upload/package/{package_id}/verify",
            },
            append_event=True,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("ZIP preparation failed for package %s", package_id)
        _write_package_preparation_progress(
            package_dir,
            {
                "package_id": package_id,
                "status": "failed",
                "stage": "failed",
                "message": "ZIP preparation failed",
                "error": str(exc),
            },
            append_event=True,
        )
    finally:
        # Staging lives only in DMEF_JOB_WORK_DIR; the terminal state is
        # readable via the store/DB fallback in get_zip_preparation_progress.
        _cleanup_work_dir(package_dir)


def _write_package_preparation_progress(
    package_dir: Path,
    update: dict[str, object],
    *,
    append_event: bool = False,
) -> None:
    progress_path = package_dir / "preparation_progress.json"
    payload: dict[str, object] = {}
    if progress_path.is_file():
        try:
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    events = list(payload.get("events") or [])
    payload.update(update)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if append_event:
        events.append(
            {
                "stage": update.get("stage"),
                "message": update.get("message"),
                "processed_files": update.get("processed_files"),
                "total_files": update.get("total_files"),
                "current_file": update.get("current_file"),
                "document": update.get("document"),
                "elapsed_seconds": update.get("elapsed_seconds"),
                "timestamp": payload["updated_at"],
            }
        )
    payload["events"] = events
    temporary_path = package_dir / f"preparation_progress.{uuid4().hex}.tmp"
    temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        for attempt in range(8):
            try:
                temporary_path.replace(progress_path)
                return
            except PermissionError:
                if attempt == 7:
                    LOGGER.warning(
                        "Skipping one ZIP progress update because Windows kept %s locked",
                        progress_path,
                    )
                    return
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary_path.unlink(missing_ok=True)


def _get_package_row(package_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", package_id):
        raise HTTPException(status_code=404, detail="ZIP package not found")
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM intake_packages WHERE package_id = ?",
            (package_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="ZIP package not found")
    return row


def _validate_package_mapping(package_id: str, manifest: VerificationManifest) -> None:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT source_document_id, internal_page_start, internal_page_end
            FROM intake_documents WHERE package_id = ?
            """,
            (package_id,),
        ).fetchall()
    sources = {
        str(row["source_document_id"]): (
            int(row["internal_page_start"]),
            int(row["internal_page_end"]),
        )
        for row in rows
    }
    for item in manifest.document_index:
        if not item.pages:
            continue
        if not item.source_document_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Mapped {item.document_type} pages require source_document_id from the ZIP inventory"
                ),
            )
        page_range = sources.get(item.source_document_id)
        if page_range is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown ZIP source_document_id: {item.source_document_id}",
            )
        outside = [page for page in item.pages if not page_range[0] <= page <= page_range[1]]
        if outside:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Pages {outside} do not belong to ZIP source {item.source_document_id} "
                    f"(expected {page_range[0]}-{page_range[1]})"
                ),
            )


def _first_coapplicant_name(manifest: VerificationManifest) -> str | None:
    for person_id, person in manifest.people.items():
        if person_id != "primary" and person.applicant_name:
            return person.applicant_name
    return None


@router.post("")
async def upload_file(
    loan_id: str = Form(...),
    applicant_name: str = Form(...),
    coapplicant_name: str | None = Form(None),
    product_type: str = Form(...),
    branch: str = Form(...),
    case_type: Literal["Normal Case", "BT Case"] = Form("Normal Case"),
    application_date: str | None = Form(None),
    file: UploadFile = File(...),
) -> dict[str, object]:
    init_db()
    work_dir = _new_upload_work_dir("upload")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_path = work_dir / f"{_safe_name(loan_id)}_{timestamp}.pdf"
    try:
        file_size_bytes = await _save_upload_stream(file, file_path)
    except Exception:
        _cleanup_work_dir(work_dir)
        raise

    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        _cleanup_work_dir(work_dir)
        raise HTTPException(status_code=400, detail=validation["error"])

    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (
                loan_id,
                applicant_name,
                coapplicant_name,
                product_type,
                branch
            )
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            (loan_id, applicant_name, coapplicant_name, product_type, branch),
        ).fetchone()
        if row is None:
            _cleanup_work_dir(work_dir)
            raise HTTPException(status_code=500, detail="Failed to create application")
        application_id = int(row["id"])

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
                None,
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

    # Persist the source PDF through the object store (never under data/uploads).
    pdf_bytes = file_path.read_bytes()
    storage_key = _application_source_key(application_id, file.filename or "upload.pdf")
    try:
        _store_bytes(storage_key, pdf_bytes, file.content_type or "application/pdf")
    except Exception as exc:
        _cleanup_work_dir(work_dir)
        raise HTTPException(status_code=500, detail="Failed to store uploaded PDF") from exc
    record_ref(
        "applications",
        application_id,
        "source",
        storage_key,
        content_type=file.content_type or "application/pdf",
        size_bytes=len(pdf_bytes),
    )

    system_data = {
        "loan_id": loan_id,
        "applicant_name": applicant_name,
        "coapplicant_name": coapplicant_name,
        "product_type": product_type,
        "branch": branch,
        "case_type": case_type,
        "application_date": application_date,
        "people": {
            "primary": {"role": "primary", "applicant_name": applicant_name},
            **(
                {"coapplicant_1": {"role": "coapplicant", "applicant_name": coapplicant_name}}
                if coapplicant_name
                else {}
            ),
        },
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
    job_id = -1
    try:
        job_id = enqueue(
            "pdf_pipeline",
            application_id,
            {
                "source_path": str(file_path),
                "system_data": system_data,
                "product_type": product_type,
            },
        )
    except Exception as exc:
        _cleanup_work_dir(work_dir)
        raise HTTPException(
            status_code=500,
            detail="Upload accepted but failed to queue securely for processing",
        ) from exc
    submit_job(
        _run_pipeline_task,
        job_id,
        str(file_path),
        application_id,
        system_data,
        product_type,
    )
    # The staged upload copy is job-scoped; the pipeline resolves via the store.
    _cleanup_work_dir(work_dir)

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
    """Legacy entry point kept for tests; body lives in services.pipeline.tasks."""
    from services.pipeline import tasks as pipeline_tasks

    try:
        pipeline_tasks._do_pipeline_work(
            job_id, file_path, application_id, system_data, product_type,
            run_fn=run_pipeline,
        )
    except PipelineCancelled:
        return


def _run_mapped_pipeline_task(
    job_id: int,
    file_path: str,
    application_id: int,
    manifest: dict[str, object],
    package_id: str | None = None,
) -> None:
    """Legacy entry point kept for tests; body lives in services.pipeline.tasks."""
    from services.pipeline import tasks as pipeline_tasks

    reference_data = manifest.get("reference_data") or {}
    primary = reference_data.get("primary") if isinstance(reference_data, dict) else {}
    primary = primary if isinstance(primary, dict) else {}
    system_data = {
        **primary,
        "loan_id": manifest.get("loan_id"),
        "product_type": manifest.get("product_type") or "LAP",
        "branch": manifest.get("branch"),
        "application_date": manifest.get("application_date"),
        "reference_data": reference_data,
        "people": reference_data,
        "case_type": manifest.get("case_type") or "Normal Case",
    }
    try:
        pipeline_tasks._do_pipeline_work(
            job_id,
            file_path,
            application_id,
            system_data,
            str(manifest.get("product_type") or "LAP"),
            mapped_manifest=manifest,
            package_id=package_id,
            generate_llm_summary=True,
            run_fn=run_pipeline,
        )
    except PipelineCancelled:
        return


def _load_package_source_documents(package_id: str | None) -> list[dict[str, object]]:
    if not package_id:
        return []
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT source_document_id, original_filename, file_type, page_count,
                   internal_page_start, internal_page_end
            FROM intake_documents
            WHERE package_id = ?
            ORDER BY internal_page_start
            """,
            (package_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/{application_id}/progress", summary="Get upload processing progress")
def upload_progress(application_id: int) -> dict[str, object]:
    progress = get_progress(application_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found for application")
    return progress


# --- batch ---


def _record_batch_rejection(batch_id: str, filename: str, reason: str) -> None:
    """Persist one rejected batch file (table owned by the schema registry).

    Insert errors propagate to the caller (logged and re-raised there) so a
    failing rejection write is never silently swallowed.
    """
    from datetime import UTC, datetime

    with get_connection() as connection:
        connection.execute(
            "INSERT INTO batch_rejections (id, batch_id, filename, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (uuid4().hex, batch_id, filename, reason, datetime.now(UTC).isoformat()),
        )


def _load_batch_rejections(batch_id: str) -> list[dict[str, object]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT filename, reason FROM batch_rejections WHERE batch_id = ? ORDER BY created_at, filename",
            (batch_id,),
        ).fetchall()
    return [{"filename": str(row["filename"]), "reason": str(row["reason"])} for row in rows]


@router.post("/batch", summary="Upload up to ten files as one batch")
async def upload_batch(
    files: list[UploadFile] = File(...),
    product_type: str = Form("LAP"),
    branch: str = Form(""),
    applicant_name: str = Form(""),
    case_type: Literal["Normal Case", "BT Case"] = Form("Normal Case"),
) -> dict[str, object]:
    """Create one application + one job per file sharing a batch_id."""
    init_db()
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="A batch accepts at most 10 files")
    batch_id = uuid4().hex

    # Index sidecar manifests by stem: <name>.pdf + <name>.manifest.json
    manifests: dict[str, bytes] = {}
    for item in files:
        name = (item.filename or "").lower()
        if name.endswith(".manifest.json"):
            stem = Path(item.filename or "").name[: -len(".manifest.json")]
            manifests[stem.lower()] = await item.read()

    items: list[dict[str, object]] = []
    for item in files:
        filename = item.filename or "upload.pdf"
        lowered = filename.lower()
        if lowered.endswith(".manifest.json"):
            continue
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        # Basic filename validation before touching disk.
        if lowered.endswith(".pdf"):
            precheck = validate_upload(filename, file_size_bytes=item.size or 0)
            if not precheck["is_valid"]:
                items.append(
                    {
                        "filename": filename,
                        "application_id": None,
                        "job_id": None,
                        "status": "rejected",
                        "reason": "; ".join(str(e) for e in precheck["errors"]),
                    }
                )
                continue
        elif lowered.endswith(".zip"):
            precheck = validate_package_upload(filename, file_size_bytes=item.size or 0)
            if not precheck["is_valid"]:
                items.append(
                    {
                        "filename": filename,
                        "application_id": None,
                        "job_id": None,
                        "status": "rejected",
                        "reason": "; ".join(str(e) for e in precheck["errors"]),
                    }
                )
                continue
        else:
            items.append(
                {
                    "filename": filename,
                    "application_id": None,
                    "job_id": None,
                    "status": "rejected",
                    "reason": "Only PDF files accepted",
                }
            )
            continue
        try:
            if lowered.endswith(".zip"):
                result_item = await _batch_single_mapped_zip(
                    item, batch_id, timestamp, case_type
                )
                items.append(result_item)
                continue
            stem = Path(filename).stem
            sidecar = manifests.get(stem.lower())
            if sidecar is not None:
                result_item = await _batch_single_pdf_with_manifest(
                    item,
                    sidecar,
                    filename,
                    batch_id,
                    timestamp,
                    case_type,
                )
                items.append(result_item)
                continue
            result_item = await _batch_single_plain_pdf(
                item,
                filename,
                batch_id,
                timestamp,
                product_type,
                branch,
                applicant_name,
                case_type,
            )
            items.append(result_item)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            items.append(
                {
                    "filename": filename,
                    "application_id": None,
                    "job_id": None,
                    "status": "rejected",
                    "reason": detail,
                }
            )
        except Exception as exc:  # noqa: BLE001
            items.append(
                {
                    "filename": filename,
                    "application_id": None,
                    "job_id": None,
                    "status": "rejected",
                    "reason": str(exc)[:300],
                }
            )
    # Persist rejections so GET /upload/batch/{id} can show them.
    # Insert failures are logged and re-raised, never swallowed: the table
    # is created by init_db() via the schema registry, so a failure here is
    # a real DB problem the operator must see.
    for entry in items:
        if entry.get("status") == "rejected":
            try:
                _record_batch_rejection(
                    batch_id, str(entry.get("filename") or "upload.pdf"), str(entry.get("reason") or "")
                )
            except Exception:
                LOGGER.exception(
                    "Failed to persist batch rejection for batch %s", batch_id
                )
                raise
    return {"batch_id": batch_id, "items": items}


@router.get("/batch/{batch_id}", summary="Get per-file batch status")
def get_batch_status(batch_id: str) -> dict[str, object]:
    init_db()
    if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    with get_connection() as connection:
        jobs = connection.execute(
            """
            SELECT id, application_id, status, attempt, max_attempts,
                   failure_reason, error
            FROM pipeline_jobs
            WHERE batch_id = ?
            ORDER BY id
            """,
            (batch_id,),
        ).fetchall()
        rejected_rows = connection.execute(
            "SELECT filename, reason FROM batch_rejections WHERE batch_id = ? ORDER BY created_at, filename",
            (batch_id,),
        ).fetchall()
        if not jobs and not rejected_rows:
            raise HTTPException(status_code=404, detail="Batch not found")
        items: list[dict[str, object]] = []
        for job in jobs:
            app_id = int(job["application_id"])
            uploaded = connection.execute(
                """
                SELECT original_filename FROM uploaded_files
                WHERE application_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (app_id,),
            ).fetchone()
            progress = connection.execute(
                "SELECT percentage, status FROM pipeline_progress WHERE application_id = ?",
                (app_id,),
            ).fetchone()
            status = str(job["status"])
            items.append(
                {
                    "application_id": app_id,
                    "filename": str(uploaded["original_filename"])
                    if uploaded and uploaded["original_filename"]
                    else f"application_{app_id}.pdf",
                    "status": status,
                    "attempt": int(job["attempt"] or 0),
                    "max_attempts": int(job["max_attempts"] or 3),
                    "failure_reason": job["failure_reason"] if job["failure_reason"] else None,
                    "progress_percentage": float(progress["percentage"])
                    if progress and progress["percentage"] is not None
                    else 0.0,
                    "review_ready": status == "completed",
                }
            )
        for rejected in rejected_rows:
            reason = str(rejected["reason"] or "")
            items.append(
                {
                    "application_id": None,
                    "job_id": None,
                    "filename": str(rejected["filename"]),
                    "status": "rejected",
                    "reason": reason,
                    "attempt": 0,
                    "max_attempts": 3,
                    "failure_reason": reason or None,
                    "progress_percentage": 0.0,
                    "review_ready": False,
                }
            )
    return {"batch_id": batch_id, "items": items}


async def _batch_single_plain_pdf(
    item: UploadFile,
    filename: str,
    batch_id: str,
    timestamp: str,
    product_type: str,
    branch: str,
    applicant_name: str,
    case_type: str,
    batch_dir: Path | None = None,
) -> dict[str, object]:
    # Batch PDFs are staged under DMEF_JOB_WORK_DIR (never UPLOAD_DIR) and
    # persisted through the object store, same key layout as single /upload.
    _ = batch_dir  # legacy param ignored; kept for backward compatibility
    work_dir = _new_upload_work_dir("batch")
    file_path = work_dir / f"{_safe_name(Path(filename).stem)}_{timestamp}.pdf"
    try:
        file_size_bytes = await _save_upload_stream(item, file_path)
    except Exception:
        _cleanup_work_dir(work_dir)
        raise
    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        _cleanup_work_dir(work_dir)
        return {
            "filename": filename,
            "application_id": None,
            "job_id": None,
            "status": "rejected",
            "reason": str(validation["error"]),
        }
    loan_id = Path(filename).stem[:64] or f"BATCH-{timestamp}"
    resolved_applicant = applicant_name.strip() or loan_id
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (loan_id, resolved_applicant, product_type, branch),
        ).fetchone()
        application_id = int(row["id"])
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, file_size_kb,
                total_pages, digital_pages, scanned_pages
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                None,
                filename,
                round(file_size_bytes / 1024, 2),
                validation["total_pages"],
                validation["digital_pages"],
                validation["scanned_pages"],
            ),
        )
        connection.execute(
            "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
            (application_id, "file_uploaded", f"Batch {batch_id}: uploaded {filename}"),
        )
    # Persist bytes through the object store before enqueue.
    pdf_bytes = file_path.read_bytes()
    storage_key = _application_source_key(application_id, filename)
    try:
        _store_bytes(storage_key, pdf_bytes, "application/pdf")
    except Exception as exc:
        _cleanup_work_dir(work_dir)
        raise HTTPException(status_code=500, detail="Failed to store uploaded PDF") from exc
    record_ref(
        "applications",
        application_id,
        "source",
        storage_key,
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
    )
    system_data = {
        "loan_id": loan_id,
        "applicant_name": resolved_applicant,
        "product_type": product_type,
        "branch": branch,
        "case_type": case_type,
        "people": {"primary": {"role": "primary", "applicant_name": resolved_applicant}},
    }
    with get_connection() as connection:
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?", ("processing", application_id)
        )
    start_tracking(
        application_id,
        total_pages=int(validation["total_pages"]),  # type: ignore[arg-type]
        digital_pages=int(validation["digital_pages"]),  # type: ignore[arg-type]
        scanned_pages=int(validation["scanned_pages"]),  # type: ignore[arg-type]
        stage="queued",
        message=f"Batch {batch_id}: upload accepted and queued",
    )
    try:
        job_id = enqueue(
            "pdf_pipeline",
            application_id,
            {
                "source_path": str(file_path),
                "system_data": system_data,
                "product_type": product_type,
            },
            batch_id=batch_id,
        )
    except Exception as exc:
        _cleanup_work_dir(work_dir)
        raise HTTPException(
            status_code=500, detail="Upload accepted but failed to queue securely"
        ) from exc
    submit_job(
        _run_pipeline_task,
        job_id,
        str(file_path),
        application_id,
        system_data,
        product_type,
    )
    # Staged copy is job-scoped; the worker reloads via the store.
    _cleanup_work_dir(work_dir)
    return {
        "filename": filename,
        "application_id": application_id,
        "job_id": job_id,
        "status": "queued",
    }


async def _batch_single_pdf_with_manifest(
    item: UploadFile,
    manifest_bytes: bytes,
    filename: str,
    batch_id: str,
    timestamp: str,
    case_type: str,
    batch_dir: Path | None = None,
) -> dict[str, object]:
    _ = batch_dir  # legacy param ignored; staging lives under DMEF_JOB_WORK_DIR
    work_dir = _new_upload_work_dir("batch")
    file_path = work_dir / f"{_safe_name(Path(filename).stem)}_{timestamp}.pdf"
    try:
        await _save_upload_stream(item, file_path)
    except Exception:
        _cleanup_work_dir(work_dir)
        raise
    try:
        manifest_text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        _cleanup_work_dir(work_dir)
        raise HTTPException(status_code=422, detail="Manifest file is not valid UTF-8") from exc
    try:
        parsed = _parse_manifest(manifest_text)
        parsed.case_type = case_type  # type: ignore[assignment]
    except HTTPException:
        _cleanup_work_dir(work_dir)
        raise
    file_size_bytes = file_path.stat().st_size
    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        _cleanup_work_dir(work_dir)
        return {
            "filename": filename,
            "application_id": None,
            "job_id": None,
            "status": "rejected",
            "reason": str(validation["error"]),
        }
    try:
        result = _queue_mapped_verification(
            parsed,
            file_path=file_path,
            original_filename=filename,
            file_size_bytes=file_size_bytes,
            validation=validation,
            audit_action="mapped_file_uploaded",
            audit_detail=f"Batch {batch_id}: uploaded {filename} with manifest",
            batch_id=batch_id,
        )
    except Exception:
        _cleanup_work_dir(work_dir)
        raise
    # Staged copy is job-scoped; the worker reloads via the store.
    _cleanup_work_dir(work_dir)
    return {
        "filename": filename,
        "application_id": result["application_id"],
        "job_id": result["job_id"],
        "status": "queued",
    }


async def _batch_single_mapped_zip(
    item: UploadFile,
    batch_id: str,
    timestamp: str,
    case_type: str,
    batch_dir: Path | None = None,
) -> dict[str, object]:
    _ = batch_dir  # legacy param ignored; staging lives under DMEF_JOB_WORK_DIR
    filename = item.filename or "package.zip"
    package_bytes = await _read_upload_bytes(item)
    try:
        archive = zipfile.ZipFile(BytesIO(package_bytes))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="ZIP file is corrupted or unreadable") from exc
    with archive:
        members = [
            m
            for m in archive.infolist()
            if not m.is_dir()
            and not PurePosixPath(m.filename).name.startswith(".")
            and "__MACOSX" not in PurePosixPath(m.filename).parts
        ]
        pdf_members = [
            m for m in members if PurePosixPath(m.filename).suffix.lower() == ".pdf"
        ]
        json_members = [
            m for m in members if PurePosixPath(m.filename).suffix.lower() == ".json"
        ]
        if len(json_members) != 1 or not pdf_members:
            raise HTTPException(
                status_code=422,
                detail="Mapped ZIP must contain one PDF and one JSON manifest",
            )
        manifest_text = archive.read(json_members[0]).decode("utf-8")
        manifest_payload = _decode_manifest_payload(manifest_text)
        pdf_member = _select_pdf_member(pdf_members, manifest_payload)
        pdf_bytes = archive.read(pdf_member)
        if not pdf_bytes:
            raise HTTPException(status_code=400, detail="Mapped ZIP PDF file is empty")
    work_dir = _new_upload_work_dir("batch")
    file_path = work_dir / f"mapped_package_{timestamp}.pdf"
    file_path.write_bytes(pdf_bytes)
    original_filename = PurePosixPath(pdf_member.filename).name
    try:
        parsed = _parse_manifest(manifest_text)
        parsed.case_type = case_type  # type: ignore[assignment]
    except HTTPException:
        _cleanup_work_dir(work_dir)
        raise
    file_size_bytes = file_path.stat().st_size
    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        _cleanup_work_dir(work_dir)
        return {
            "filename": filename,
            "application_id": None,
            "job_id": None,
            "status": "rejected",
            "reason": str(validation["error"]),
        }
    try:
        result = _queue_mapped_verification(
            parsed,
            file_path=file_path,
            original_filename=original_filename,
            file_size_bytes=file_size_bytes,
            validation=validation,
            audit_action="mapped_file_uploaded",
            audit_detail=f"Batch {batch_id}: mapped ZIP {filename}",
            batch_id=batch_id,
        )
    except Exception:
        _cleanup_work_dir(work_dir)
        raise
    # Staged copy is job-scoped; the worker reloads via the store.
    _cleanup_work_dir(work_dir)
    return {
        "filename": filename,
        "application_id": result["application_id"],
        "job_id": result["job_id"],
        "status": "queued",
    }
