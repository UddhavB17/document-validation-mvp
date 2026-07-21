"""Upload API routes."""

from datetime import datetime
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import logging
import re
import shutil
import time
from uuid import uuid4
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from database.db import get_connection, init_db
from services.file_validator import (
    max_file_size_bytes,
    validate_file,
    validate_package_upload,
    validate_upload,
)
from services.company_dump_adapter import (
    CompanyDumpConversionError,
    convert_company_database_dump,
    is_company_database_dump,
)
from services.job_runner import submit_job
from services.progress_tracker import (
    create_pipeline_job,
    get_progress,
    mark_failed,
    mark_job_completed,
    mark_job_failed,
    mark_job_started,
    start_tracking,
)
from services.pipeline import run_pipeline
from services.verification_manifest import VerificationManifest
from services.zip_package import PackageValidationError, load_package_metadata, normalize_zip_package

router = APIRouter(prefix="/upload", tags=["upload"])
UPLOAD_DIR = Path("data/uploads")
LOGGER = logging.getLogger(__name__)


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
    file: UploadFile = File(...),
) -> dict[str, object]:
    """Queue shared PDF processing plus trusted mapped JSON comparison."""
    init_db()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    uploaded_name = file.filename or "mapped_upload"

    if Path(uploaded_name).suffix.lower() == ".zip":
        file_path, manifest_text, original_filename = await _save_mapped_zip_package(file, manifest, timestamp)
    else:
        if not manifest or not manifest.strip():
            raise HTTPException(status_code=422, detail="Manifest JSON is required for mapped PDF upload")
        file_path = UPLOAD_DIR / f"mapped_{timestamp}.pdf"
        await _save_upload_stream(file, file_path)
        manifest_text = manifest
        original_filename = uploaded_name

    try:
        parsed = VerificationManifest.model_validate(json.loads(manifest_text))
    except (json.JSONDecodeError, ValueError) as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Invalid manifest JSON: {exc}") from exc

    final_file_path = UPLOAD_DIR / f"{_safe_name(parsed.loan_id)}_{timestamp}.pdf"
    if file_path != final_file_path:
        file_path.replace(final_file_path)
        file_path = final_file_path

    file_size_bytes = file_path.stat().st_size
    validation = validate_file(file_path, file_size_bytes)
    if not validation["valid"]:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=validation["error"])

    try:
        return _queue_mapped_verification(
            parsed,
            file_path=file_path,
            original_filename=file.filename or "mapped.pdf",
            file_size_bytes=file_size_bytes,
            validation=validation,
            audit_action="mapped_file_uploaded",
        )
    except Exception:
        file_path.unlink(missing_ok=True)
        raise


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
    package_dir = UPLOAD_DIR / "packages" / package_id
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
                file.filename or "documents.zip",
                zip_path,
                package_dir,
            )
            return {
                "package_id": package_id,
                "source_filename": file.filename,
                "status": "queued",
                "progress_url": f"/upload/package/{package_id}/preparation",
            }
        normalized = normalize_zip_package(zip_path, package_dir)
        pdf_path = Path(str(normalized["normalized_pdf_path"]))
        pdf_validation = validate_file(pdf_path, pdf_path.stat().st_size)
        if not pdf_validation["valid"]:
            raise PackageValidationError(str(pdf_validation["error"]))
        _persist_intake_package(
            package_id,
            file.filename or "documents.zip",
            zip_path,
            normalized,
        )
    except (PackageValidationError, ValueError) as exc:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise

    return {
        "package_id": package_id,
        "source_filename": file.filename,
        "status": "prepared",
        "total_files": normalized["total_files"],
        "total_pages": normalized["total_pages"],
        "documents": normalized["documents"],
        "verify_url": f"/upload/package/{package_id}/verify",
    }


@router.get(
    "/package/{package_id}/preparation",
    summary="Get ZIP preparation progress and per-file logs",
)
def get_zip_preparation_progress(package_id: str) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{32}", package_id):
        raise HTTPException(status_code=404, detail="ZIP package not found")
    progress_path = UPLOAD_DIR / "packages" / package_id / "preparation_progress.json"
    if not progress_path.is_file():
        raise HTTPException(status_code=404, detail="ZIP preparation progress not found")
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="ZIP progress is being updated") from exc


@router.get("/package/{package_id}", summary="Get prepared ZIP package inventory")
def get_zip_package(package_id: str) -> dict[str, object]:
    row = _get_package_row(package_id)
    metadata = load_package_metadata(Path(row["normalized_pdf_path"]).parent)
    return {
        "package_id": package_id,
        "source_filename": row["source_filename"],
        "status": row["status"],
        "total_files": row["total_files"],
        "total_pages": row["total_pages"],
        "documents": metadata["documents"],
        "verify_url": f"/upload/package/{package_id}/verify",
    }


@router.post("/package/{package_id}/verify", summary="Verify a prepared ZIP package")
async def verify_zip_package(
    package_id: str,
    manifest: str = Form(...),
) -> dict[str, object]:
    """Apply a confirmed manifest to the package's normalized internal PDF."""
    init_db()
    parsed = _parse_manifest(manifest)
    row = _get_package_row(package_id)
    if row["status"] in {"verifying", "processing"}:
        raise HTTPException(status_code=409, detail="ZIP package verification is already running")

    _validate_package_mapping(package_id, parsed)
    pdf_path = Path(row["normalized_pdf_path"])
    if not pdf_path.is_file():
        raise HTTPException(status_code=410, detail="Prepared ZIP package files are no longer available")
    pdf_validation = validate_file(pdf_path, pdf_path.stat().st_size)
    if not pdf_validation["valid"]:
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
            raise HTTPException(status_code=409, detail="ZIP package verification has already started")
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
        with get_connection() as connection:
            connection.execute(
                "UPDATE intake_packages SET status = 'prepared' WHERE package_id = ?",
                (package_id,),
            )
        raise

    result["package_id"] = package_id
    result["source_documents"] = int(row["total_files"])
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
    except (json.JSONDecodeError, CompanyDumpConversionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid manifest JSON: {exc}") from exc


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
        cursor = connection.execute(
            """
            INSERT INTO applications (
                loan_id, applicant_name, coapplicant_name, product_type, branch, status
            ) VALUES (?, ?, ?, ?, ?, 'processing')
            """,
            (
                parsed.loan_id,
                parsed.people.get("primary").applicant_name if parsed.people.get("primary") else None,
                _first_coapplicant_name(parsed),
                parsed.product_type,
                parsed.branch,
            ),
        )
        application_id = int(cursor.lastrowid)
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
                str(file_path),
                original_filename,
                round(file_size_bytes / 1024, 2),
                validation["total_pages"],
                validation["digital_pages"],
                validation["scanned_pages"],
            ),
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
    job_id = create_pipeline_job(application_id)
    submit_job(
        _run_mapped_pipeline_task,
        job_id,
        str(file_path),
        application_id,
        parsed.pipeline_payload(),
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
        pdf_members = [member for member in members if PurePosixPath(member.filename).suffix.lower() == ".pdf"]
        json_members = [member for member in members if PurePosixPath(member.filename).suffix.lower() == ".json"]

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
            raise HTTPException(status_code=400, detail=f"File too large, max {max_file_size_bytes() // (1024 * 1024)}MB")

    file_path = UPLOAD_DIR / f"mapped_package_{timestamp}.pdf"
    file_path.write_bytes(pdf_bytes)
    return file_path, manifest_text, original_filename


def _decode_manifest_payload(manifest_text: str) -> dict[str, object]:
    try:
        payload = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid manifest JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Manifest JSON must be an object")
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
            raise HTTPException(status_code=400, detail=f"File too large, max {limit // (1024 * 1024)}MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _persist_intake_package(
    package_id: str,
    source_filename: str,
    zip_path: Path,
    normalized: dict[str, object],
) -> None:
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
                str(zip_path),
                str(normalized["normalized_pdf_path"]),
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
        _persist_intake_package(package_id, source_filename, zip_path, normalized)
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
    package_id: str | None = None,
) -> None:
    try:
        mark_job_started(job_id)
        reference_data = manifest.get("reference_data") or {}
        primary = reference_data.get("primary") if isinstance(reference_data, dict) else {}
        primary = primary if isinstance(primary, dict) else {}
        system_data = {
            **primary,
            "loan_id": manifest.get("loan_id"),
            "product_type": manifest.get("product_type") or "LAP",
            "branch": manifest.get("branch"),
        }
        result = run_pipeline(
            file_path,
            application_id,
            system_data=system_data,
            product_type=str(manifest.get("product_type") or "LAP"),
            generate_llm_summary=True,
            mapped_manifest=manifest,
            source_documents=_load_package_source_documents(package_id),
        )
        if result.get("pipeline_status") == "failed":
            mark_job_failed(job_id, "Pipeline completed with failed outcome")
        else:
            mark_job_completed(job_id)
        if package_id:
            with get_connection() as connection:
                connection.execute(
                    """
                    UPDATE intake_packages
                    SET status = 'completed', verified_at = CURRENT_TIMESTAMP
                    WHERE package_id = ? AND application_id = ?
                    """,
                    (package_id, application_id),
                )
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
            if package_id:
                connection.execute(
                    """
                    UPDATE intake_packages SET status = 'failed'
                    WHERE package_id = ? AND application_id = ?
                    """,
                    (package_id, application_id),
                )


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
    init_db()
    progress = get_progress(application_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress not found for application")
    return progress
