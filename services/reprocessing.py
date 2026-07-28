"""Safe recovery for stale or failed PDF pipeline jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from database.db import get_connection
from services.job_runner import submit_job
from services.pipeline import run_pipeline
from services.progress_tracker import (
    RETRYABLE_PROGRESS_STATES,
    create_pipeline_job,
    get_progress,
    mark_failed,
    mark_job_completed,
    mark_job_failed,
    mark_job_started,
    start_tracking,
)


class ReprocessConflictError(RuntimeError):
    """Raised when an application cannot safely be queued again."""


def queue_application_reprocess(application_id: int) -> dict[str, Any]:
    progress = get_progress(application_id)
    operational_status = str((progress or {}).get("operational_status") or "not_started")
    if operational_status not in RETRYABLE_PROGRESS_STATES:
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

    if application is None:
        raise LookupError("Application not found")
    if uploaded is None or not uploaded["file_path"]:
        raise FileNotFoundError("The original uploaded PDF is not available for reprocessing.")

    file_path = Path(str(uploaded["file_path"]))
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise FileNotFoundError("The original uploaded PDF is not available for reprocessing.")

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

    start_tracking(
        application_id,
        total_pages=int(uploaded["total_pages"] or 0),
        digital_pages=int(uploaded["digital_pages"] or 0),
        scanned_pages=int(uploaded["scanned_pages"] or 0),
        stage="queued",
        message="Recovery run accepted and queued",
    )
    job_id = create_pipeline_job(application_id, job_type="pdf_reprocess")
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
                json.dumps({"job_id": job_id, "previous_pipeline_status": operational_status}),
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
    )
    return {
        "application_id": application_id,
        "job_id": job_id,
        "status": "processing",
        "pipeline_status": "queued",
        "previous_pipeline_status": operational_status,
    }


def _run_reprocess_task(
    job_id: int,
    file_path: str,
    application_id: int,
    system_data: dict[str, Any],
    product_type: str,
    mapped_manifest: dict[str, Any] | None,
) -> None:
    try:
        mark_job_started(job_id)
        result = run_pipeline(
            file_path,
            application_id,
            system_data=system_data,
            product_type=product_type,
            mapped_manifest=mapped_manifest,
        )
        if result.get("pipeline_status") == "failed":
            mark_job_failed(job_id, "Recovery pipeline completed with failed outcome")
        else:
            mark_job_completed(job_id)
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


def _decode_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
