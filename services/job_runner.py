"""Durable enqueue for pipeline work plus the inline-execution switch.

New code enqueues durable ``pipeline_jobs`` rows via :func:`enqueue`. Request
paths then hand the persisted job to :func:`submit_job`, which runs the task
synchronously inside the request when ``DMEF_INLINE_WORKER=1`` (the setting
existing tests rely on) and never runs pipeline code when ``0`` — the worker
process (``services/worker.py``) claims those rows instead.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any, TypeVar

from database.db import get_connection
from services.config import get_bool

T = TypeVar("T")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _inline_enabled() -> bool:
    return get_bool("DMEF_INLINE_WORKER", False)


def enqueue(
    kind: str,
    application_id: int,
    payload: dict[str, Any],
    batch_id: str | None = None,
) -> int:
    """Insert a ``pipeline_jobs`` row, persist inputs, return the job id.

    ``payload`` keys: ``source_path``, ``system_data``, ``product_type``,
    ``mapped_manifest``, ``package_id``, ``generate_llm_summary``.
    """
    from services.job_control import persist_job_input_or_fail

    now = _utc_now_iso()
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO pipeline_jobs (
                application_id, job_type, status, control_state, attempt,
                max_attempts, next_run_at, failure_reason, batch_id,
                parent_job_id, heartbeat_at, created_at
            ) VALUES (?, ?, 'queued', 'running', 0, 3, NULL, NULL, ?, NULL, ?, ?)
            RETURNING id
            """,
            (application_id, kind, batch_id, now, now),
        ).fetchone()
        job_id = int(row["id"])
    persist_job_input_or_fail(
        job_id,
        application_id,
        source_path=payload["source_path"],
        system_data=payload.get("system_data"),
        product_type=str(payload.get("product_type") or "LAP"),
        mapped_manifest=payload.get("mapped_manifest"),
        package_id=payload.get("package_id"),
        generate_llm_summary=payload.get("generate_llm_summary"),
        resume=bool(payload.get("resume", False)),
        refresh_cached_ocr=bool(payload.get("refresh_cached_ocr", False)),
    )
    # Ensure the batch linkage survives even if the input persist path rewrote rows.
    if batch_id is not None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET batch_id = ? WHERE id = ?",
                (batch_id, job_id),
            )
    return job_id


def submit_job(fn: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
    """Deprecated shim kept so existing tests can monkeypatch it.

    New pipeline code must use :func:`enqueue`. Non-pipeline background work
    (ZIP preparation) still flows through here and runs on a daemon thread.
    """
    import concurrent.futures
    import threading

    if _inline_enabled():
        future: Future[T] = concurrent.futures.Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future
    future = concurrent.futures.Future()
    # Pipeline task functions live in services.pipeline.tasks; never run those
    # in the API process. Other background helpers (ZIP preparation) run on a
    # plain daemon thread.
    module = getattr(fn, "__module__", "") or ""
    name = getattr(fn, "__name__", "") or ""
    if module.startswith("services.pipeline.tasks") or name.startswith("_run_"):
        future.set_result(None)  # type: ignore[arg-type]
        return future

    def _target() -> None:
        try:
            result = fn(*args, **kwargs)
            if not future.done():
                future.set_result(result)
        except Exception as exc:  # noqa: BLE001
            if not future.done():
                future.set_exception(exc)

    threading.Thread(target=_target, daemon=True).start()
    return future
