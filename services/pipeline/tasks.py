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
    """Shared pipeline body used by both plain and mapped jobs."""
    from services.job_control import PipelineCancelled

    if run_fn is None:
        from services.pipeline.orchestrator import run_pipeline as run_fn  # type: ignore[no-redef]
    from services.progress_tracker import (
        mark_failed,
        mark_job_completed,
        mark_job_failed,
        mark_job_started,
    )

    try:
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
            raise RuntimeError("Pipeline completed with failed outcome")
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
    except PipelineCancelled:
        raise
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        from services.progress_tracker import mark_failed as _mark_failed
        from services.progress_tracker import mark_job_failed as _mark_job_failed

        _mark_job_failed(job_id, str(exc))
        _mark_failed(application_id, str(exc))
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
        raise


def run_pipeline_job(job_id: int) -> dict[str, Any]:
    """Run a plain (unmapped) pipeline job loaded from its persisted inputs."""
    from services.job_control import load_job_input

    job = _load_job_row(job_id)
    application_id = int(job["application_id"])
    payload = load_job_input(application_id, job_id)
    system_data = dict(payload.get("system_data") or {})
    product_type = str(payload.get("product_type") or "LAP")
    return _do_pipeline_work(
        job_id,
        str(payload["source_path"]),
        application_id,
        system_data,
        product_type,
        mapped_manifest=None,
        package_id=(str(payload.get("package_id")) if payload.get("package_id") else None),
        generate_llm_summary=payload.get("generate_llm_summary"),
        resume=bool(payload.get("resume", False)),
        refresh_cached_ocr=bool(payload.get("refresh_cached_ocr", False)),
    )


def run_mapped_job(job_id: int) -> dict[str, Any]:
    """Run a mapped-verification job loaded from its persisted inputs."""
    from services.job_control import load_job_input

    job = _load_job_row(job_id)
    application_id = int(job["application_id"])
    payload = load_job_input(application_id, job_id)
    manifest = payload.get("mapped_manifest")
    if not isinstance(manifest, dict):
        raise RuntimeError("Mapped job is missing its persisted manifest")
    return _do_pipeline_work(
        job_id,
        str(payload["source_path"]),
        application_id,
        dict(payload.get("system_data") or {}),
        str(payload.get("product_type") or "LAP"),
        mapped_manifest=manifest,
        package_id=(str(payload.get("package_id")) if payload.get("package_id") else None),
        generate_llm_summary=payload.get("generate_llm_summary"),
        resume=bool(payload.get("resume", False)),
        refresh_cached_ocr=bool(payload.get("refresh_cached_ocr", False)),
    )
