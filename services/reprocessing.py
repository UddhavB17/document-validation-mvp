"""Safe recovery for stale or failed PDF pipeline jobs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from database.db import get_connection
from services.config import get_int
from services.job_control import (
    JobInputUnavailableError,
    PipelineCancelled,
    load_job_input,
    request_control,
)
from services.job_runner import enqueue, submit_job
from services.pipeline import run_pipeline
from services.progress_tracker import (
    RETRYABLE_PROGRESS_STATES,
    get_progress,
    mark_failed,
    mark_job_completed,
    mark_job_failed,
    mark_job_started,
    start_tracking,
)


class ReprocessConflictError(RuntimeError):
    """Raised when an application cannot safely be queued again."""


def resume_application(application_id: int) -> dict[str, Any]:
    """Resume a live paused worker or recover a paused job after a process crash."""
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, heartbeat_at FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
    if job is not None and str(job["status"]) in {"paused", "pause_requested"}:
        if _heartbeat_is_recent(job["heartbeat_at"]):
            return request_control(application_id, "resume")
        return queue_application_reprocess(application_id, resume=True)
    if job is not None and str(job["status"]) in {"queued", "running"}:
        if _heartbeat_is_recent(job["heartbeat_at"]):
            raise ReprocessConflictError("The pipeline worker is still active.")
        _mark_worker_stale(application_id)
        return queue_application_reprocess(application_id, resume=True)
    progress = get_progress(application_id)
    status = str((progress or {}).get("operational_status") or "not_started")
    if status in {"stale", "failed", "cancelled", "completed_with_warnings"}:
        return queue_application_reprocess(application_id, resume=True)
    raise ReprocessConflictError(
        f"Application cannot be resumed while pipeline status is {status}."
    )


def restart_application(
    application_id: int,
    *,
    from_checkpoint: bool = True,
    refresh_cached_ocr: bool = False,
) -> dict[str, Any]:
    """Create a new attempt after the previous worker is no longer active."""
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, heartbeat_at FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
    if job is not None and str(job["status"]) in {"queued", "running", "pause_requested", "paused"}:
        if _heartbeat_is_recent(job["heartbeat_at"]):
            raise ReprocessConflictError("Cancel the active worker before starting a new attempt.")
        _mark_worker_stale(application_id)
    return queue_application_reprocess(
        application_id,
        resume=from_checkpoint,
        allow_completed_restart=True,
        refresh_cached_ocr=refresh_cached_ocr,
    )


def queue_application_reprocess(
    application_id: int,
    *,
    resume: bool = True,
    allow_completed_restart: bool = False,
    refresh_cached_ocr: bool = False,
) -> dict[str, Any]:
    progress = get_progress(application_id)
    operational_status = str((progress or {}).get("operational_status") or "not_started")
    allowed_states = set(RETRYABLE_PROGRESS_STATES)
    if allow_completed_restart:
        allowed_states.add("completed")
    if operational_status not in allowed_states:
        raise ReprocessConflictError(
            f"Application cannot be reprocessed while pipeline status is {operational_status}."
        )

    with get_connection() as connection:
        application = connection.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        uploaded = connection.execute(
            """
            SELECT file_path, total_pages, digital_pages, scanned_pages
            FROM uploaded_files
            WHERE application_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        ground_truth_row = connection.execute(
            """
            SELECT raw_json FROM ground_truth
            WHERE application_id = ?
            ORDER BY extracted_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        previous_job = connection.execute(
            "SELECT id FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()

    if application is None:
        raise LookupError("Application not found")
    if uploaded is None:
        raise FileNotFoundError("The original uploaded PDF is not available for reprocessing.")

    try:
        recovery = load_job_input(application_id)
    except JobInputUnavailableError:
        recovery = None
        ground_truth = _decode_object(ground_truth_row["raw_json"] if ground_truth_row else None)
        system_data = {
            **ground_truth,
            "loan_id": application["loan_id"],
            "applicant_name": application["applicant_name"],
            "coapplicant_name": application["coapplicant_name"],
            "product_type": application["product_type"] or "LAP",
            "branch": application["branch"],
        }
        mapped_manifest = None
        if isinstance(ground_truth.get("reference_data"), dict):
            mapped_manifest = {
                "loan_id": application["loan_id"],
                "product_type": application["product_type"] or "LAP",
                "branch": application["branch"],
                "reference_data": ground_truth["reference_data"],
                "documents": [],
            }
        package_id = None
        generate_llm_summary = None
    else:
        system_data = dict(recovery.get("system_data") or {})
        mapped_manifest = recovery.get("mapped_manifest")
        package_id = str(recovery.get("package_id") or "") or None
        generate_llm_summary = recovery.get("generate_llm_summary")

    # Resolve a real file for enqueue: store-backed uploads have NULL
    # file_path, so stage the durable bytes from object_refs via the store.
    # Legacy archive rows with a live file_path keep working.
    recovery_hint = str((recovery or {}).get("source_path") or "") or None
    file_path = _resolve_reprocess_source(
        application_id,
        uploaded["file_path"] if uploaded else None,
        recovery_hint,
        package_id,
    )

    start_tracking(
        application_id,
        total_pages=int(uploaded["total_pages"] or 0),
        digital_pages=int(uploaded["digital_pages"] or 0),
        scanned_pages=int(uploaded["scanned_pages"] or 0),
        stage="queued",
        message="Checkpoint recovery accepted and queued"
        if resume
        else "Restart accepted and queued",
        resume=resume,
    )
    if not resume:
        with get_connection() as connection:
            connection.execute("DELETE FROM pages WHERE application_id = ?", (application_id,))
    parent_job_id = int(previous_job["id"]) if previous_job else None
    kind = "mapped_reprocess" if mapped_manifest is not None else "pdf_reprocess"
    job_id = enqueue(
        kind,
        application_id,
        {
            "source_path": str(file_path),
            "system_data": system_data,
            "product_type": str(application["product_type"] or "LAP"),
            "mapped_manifest": mapped_manifest,
            "package_id": package_id,
            "generate_llm_summary": generate_llm_summary,
            "resume": resume,
            "refresh_cached_ocr": refresh_cached_ocr,
        },
    )
    # Preserve parent linkage for audit trails.
    with get_connection() as connection:
        connection.execute(
            "UPDATE pipeline_jobs SET parent_job_id = ? WHERE id = ?",
            (parent_job_id, job_id),
        )
    with get_connection() as connection:
        connection.execute(
            "UPDATE applications SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ("processing", application_id),
        )
        connection.execute(
            "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
            (
                application_id,
                "pipeline_reprocess_queued",
                json.dumps(
                    {
                        "job_id": job_id,
                        "parent_job_id": parent_job_id,
                        "previous_pipeline_status": operational_status,
                        "resume_from_checkpoint": resume,
                        "refresh_cached_ocr": refresh_cached_ocr,
                    }
                ),
            ),
        )

    submit_job(
        _run_reprocess_task,
        job_id,
        str(file_path),
        application_id,
        system_data,
        str(application["product_type"] or "LAP"),
        mapped_manifest,
        package_id,
        generate_llm_summary,
        resume,
        refresh_cached_ocr,
    )
    # The staged reprocess copy is job-scoped; the worker reloads via the
    # store, so remove it (legacy paths are never touched).
    try:
        if "reprocess-" in str(file_path):
            from services.pipeline.input_preparation import cleanup_job_source

            cleanup_job_source(Path(file_path).parent)
    except Exception:
        pass

    return {
        "application_id": application_id,
        "job_id": job_id,
        "status": "processing",
        "pipeline_status": "queued",
        "previous_pipeline_status": operational_status,
        "resume_from_checkpoint": resume,
        "refresh_cached_ocr": refresh_cached_ocr,
    }


def _run_reprocess_task(
    job_id: int,
    file_path: str,
    application_id: int,
    system_data: dict[str, Any],
    product_type: str,
    mapped_manifest: dict[str, Any] | None,
    package_id: str | None,
    generate_llm_summary: bool | None,
    resume: bool,
    refresh_cached_ocr: bool = False,
) -> None:
    try:
        mark_job_started(job_id)
        result = run_pipeline(
            file_path,
            application_id,
            system_data=system_data,
            product_type=product_type,
            mapped_manifest=mapped_manifest,
            source_documents=_load_package_source_documents(package_id),
            generate_llm_summary=generate_llm_summary,
            job_id=job_id,
            resume=resume,
            refresh_cached_ocr=refresh_cached_ocr,
        )
        if result.get("pipeline_status") == "failed":
            mark_job_failed(job_id, "Recovery pipeline completed with failed outcome")
            if package_id:
                with get_connection() as connection:
                    connection.execute(
                        """
                        UPDATE intake_packages
                        SET status = 'failed'
                        WHERE package_id = ? AND application_id = ?
                        """,
                        (package_id, application_id),
                    )
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
    except PipelineCancelled:
        return
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(job_id, str(exc))
        mark_failed(application_id, str(exc))
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("pipeline_failed", application_id),
            )
            connection.execute(
                "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
                (application_id, "pipeline_reprocess_failed", str(exc)),
            )
            if package_id:
                connection.execute(
                    "UPDATE intake_packages SET status = 'failed' WHERE package_id = ? AND application_id = ?",
                    (package_id, application_id),
                )


def _resolve_reprocess_source(
    application_id: int,
    legacy_file_path: Any | None,
    recovery_hint: str | None,
    package_id: str | None,
) -> Path:
    """Return a live PDF path for reprocess enqueue, preferring the store.

    Store-backed uploads record ``file_path`` as NULL; their bytes live in
    the object store under ``object_refs``. Stage those bytes into
    ``DMEF_JOB_WORK_DIR`` so ``enqueue`` can hash a real file and the worker
    can reload it after this process is gone.
    """
    if recovery_hint:
        candidate = Path(recovery_hint)
        if candidate.is_file() and candidate.suffix.lower() == ".pdf":
            return candidate
    from uuid import uuid4

    from services.paths import job_work_dir
    from services.storage import get_store
    from services.storage.refs import get_ref

    ref = get_ref("applications", application_id, "source") or get_ref(
        "applications", application_id, "normalized_pdf"
    )
    if ref is None and package_id:
        ref = get_ref("intake_packages", package_id, "normalized_pdf")
    if ref is not None:
        try:
            pdf_bytes = get_store().get(str(ref["storage_key"]))
        except Exception:
            pdf_bytes = None
        if pdf_bytes:
            staging = job_work_dir() / f"reprocess-{application_id}-{uuid4().hex}" / "source.pdf"
            staging.parent.mkdir(parents=True, exist_ok=False)
            staging.write_bytes(pdf_bytes)
            return staging
    if legacy_file_path:
        candidate = Path(str(legacy_file_path))
        if candidate.is_file() and candidate.suffix.lower() == ".pdf":
            return candidate
    raise FileNotFoundError("The original uploaded PDF is not available for reprocessing.")


def _load_package_source_documents(package_id: str | None) -> list[dict[str, Any]]:
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


def _decode_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _heartbeat_is_recent(value: Any, *, seconds: int | None = None) -> bool:
    if not value:
        return False
    try:
        heartbeat = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    grace_seconds = seconds or get_int("DMEF_JOB_HEARTBEAT_GRACE_SECONDS", 180, minimum=30)
    return (datetime.now(UTC) - heartbeat).total_seconds() <= grace_seconds


def _mark_worker_stale(application_id: int) -> None:
    now = datetime.now(UTC).isoformat()
    with get_connection() as connection:
        job = connection.execute(
            "SELECT id, status FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        if job is None:
            return
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = 'stale', control_state = 'stale', completed_at = ?
            WHERE id = ?
            """,
            (now, job["id"]),
        )
        connection.execute(
            """
            UPDATE pipeline_progress
            SET status = 'failed', stage = 'stale', message = 'Worker heartbeat expired; recovery is available',
                error = 'Worker heartbeat expired', completed_at = ?, updated_at = ?
            WHERE application_id = ?
            """,
            (now, now, application_id),
        )
        connection.execute(
            "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
            (
                application_id,
                "pipeline_worker_stale",
                json.dumps({"job_id": int(job["id"]), "previous_status": str(job["status"])}),
            ),
        )
