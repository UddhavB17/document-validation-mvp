"""Durable pipeline task entry points consumed by the worker process.

Each function loads everything it needs from the ``pipeline_jobs`` row and
``pipeline_job_inputs`` so a job can be re-run after a process crash without
access to the original request objects.
"""

from __future__ import annotations

from typing import Any

from database.db import get_connection


def _load_job_row(job_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM pipeline_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"Pipeline job {job_id} not found")
    return dict(row)


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


def _do_pipeline_work(
    job_id: int,
    file_path: str,
    application_id: int,
    system_data: dict[str, Any],
    product_type: str,
    *,
    mapped_manifest: dict[str, Any] | None = None,
    package_id: str | None = None,
    generate_llm_summary: bool | None = None,
    resume: bool = False,
    refresh_cached_ocr: bool = False,
    run_fn: Any | None = None,
) -> dict[str, Any]:
    """Shared pipeline body used by both plain and mapped jobs.

    Transient crashes re-raise without touching ``applications.status``; the
    worker decides retry vs terminal failure in ``handle_job_exception`` and
    only the final failure marks the application ``failed``. A clean pipeline
    failure (``pipeline_status == 'failed'``) is terminal: the intake package
    is marked ``failed`` (never ``completed``) and a non-retryable
    ``PipelineFailedError`` is raised.
    """
    from services.job_control import PipelineFailedError

    if run_fn is None:
        from services.pipeline.orchestrator import run_pipeline as run_fn  # type: ignore[no-redef]
    from services.progress_tracker import (
        mark_failed,
        mark_job_completed,
        mark_job_failed,
        mark_job_started,
    )

    mark_job_started(job_id)
    source_docs = _load_package_source_documents(package_id)
    result = run_fn(
        file_path,
        application_id,
        system_data=system_data,
        product_type=product_type,
        generate_llm_summary=generate_llm_summary,
        mapped_manifest=mapped_manifest,
        source_documents=source_docs,
        job_id=job_id,
        resume=resume,
        refresh_cached_ocr=refresh_cached_ocr,
    )
    if result.get("pipeline_status") == "failed":
        mark_job_failed(job_id, "Pipeline completed with failed outcome")
        mark_failed(application_id, "Pipeline completed with failed outcome")
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET status = ? WHERE id = ?",
                ("failed", application_id),
            )
            connection.execute(
                """
                INSERT INTO audit_log (application_id, action, details)
                VALUES (?, ?, ?)
                """,
                (application_id, "pipeline_failed", "Pipeline completed with failed outcome"),
            )
            if package_id:
                connection.execute(
                    """
                    UPDATE intake_packages SET status = 'failed'
                    WHERE package_id = ? AND application_id = ?
                    """,
                    (package_id, application_id),
                )
        raise PipelineFailedError("Pipeline completed with failed outcome")
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
    return result


def _resolve_worker_source(
    application_id: int, job_id: int, payload: dict[str, Any]
) -> str:
    """Stage the durable store bytes and return a real file path.

    ``load_job_input`` already re-stages from the store before its checksum,
    but the worker entry points resolve explicitly via ``resolve_job_source``
    so the pipeline never hashes a deleted upload work dir.
    """
    from pathlib import Path

    from services.pipeline.input_preparation import resolve_job_source

    hint = str(payload.get("source_path") or "") or None
    package_id = payload.get("package_id")
    package_str = str(package_id) if package_id else None
    try:
        resolved = resolve_job_source(application_id, hint, job_id, package_id=package_str)
    except FileNotFoundError:
        if hint and Path(hint).is_file():
            return hint
        raise
    return str(resolved)


def run_pipeline_job(job_id: int) -> dict[str, Any]:
    """Run a plain (unmapped) pipeline job loaded from its persisted inputs."""
    from services.job_control import load_job_input
    from services.pipeline.input_preparation import cleanup_job_source, job_source_dir

    job = _load_job_row(job_id)
    application_id = int(job["application_id"])
    payload = load_job_input(application_id, job_id)
    source_path = _resolve_worker_source(application_id, job_id, payload)
    system_data = dict(payload.get("system_data") or {})
    product_type = str(payload.get("product_type") or "LAP")
    try:
        return _do_pipeline_work(
            job_id,
            source_path,
            application_id,
            system_data,
            product_type,
            mapped_manifest=None,
            package_id=(str(payload.get("package_id")) if payload.get("package_id") else None),
            generate_llm_summary=payload.get("generate_llm_summary"),
            resume=bool(payload.get("resume", False)),
            refresh_cached_ocr=bool(payload.get("refresh_cached_ocr", False)),
        )
    finally:
        cleanup_job_source(job_source_dir(job_id))


def run_mapped_job(job_id: int) -> dict[str, Any]:
    """Run a mapped-verification job loaded from its persisted inputs."""
    from services.job_control import load_job_input
    from services.pipeline.input_preparation import cleanup_job_source, job_source_dir

    job = _load_job_row(job_id)
    application_id = int(job["application_id"])
    payload = load_job_input(application_id, job_id)
    manifest = payload.get("mapped_manifest")
    if not isinstance(manifest, dict):
        raise RuntimeError("Mapped job is missing its persisted manifest")
    source_path = _resolve_worker_source(application_id, job_id, payload)
    try:
        return _do_pipeline_work(
            job_id,
            source_path,
            application_id,
            dict(payload.get("system_data") or {}),
            str(payload.get("product_type") or "LAP"),
            mapped_manifest=manifest,
            package_id=(str(payload.get("package_id")) if payload.get("package_id") else None),
            generate_llm_summary=payload.get("generate_llm_summary"),
            resume=bool(payload.get("resume", False)),
            refresh_cached_ocr=bool(payload.get("refresh_cached_ocr", False)),
        )
    finally:
        cleanup_job_source(job_source_dir(job_id))
