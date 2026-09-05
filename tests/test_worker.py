"""Worker claim/retry/stale-recovery tests with a fake pipeline task."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.job_runner import enqueue
from services.progress_tracker import mark_job_completed, start_tracking


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    init_db()
    return tmp_path


def _seed_application(source: Path, loan_id: str = "LN-WORKER-001") -> tuple[int, str]:
    source.write_bytes(b"worker source bytes")
    with get_connection() as connection:
        row = connection.execute(
            "INSERT INTO applications (loan_id, status) VALUES (?, 'processing') RETURNING id",
            (loan_id,),
        ).fetchone()
        application_id = int(row["id"])
    start_tracking(application_id, total_pages=1)
    return application_id, str(source)


def _enqueue(tmp_path: Path, tag: str) -> tuple[int, int]:
    application_id, source_path = _seed_application(tmp_path / f"{tag}.pdf", f"LN-{tag}")
    job_id = enqueue(
        "pdf_pipeline",
        application_id,
        {
            "source_path": source_path,
            "system_data": {"loan_id": f"LN-{tag}"},
            "product_type": "LAP",
        },
    )
    return application_id, job_id


def test_worker_processes_jobs_in_id_order(isolated_db, tmp_path, monkeypatch) -> None:
    import services.pipeline.tasks as pipeline_tasks
    import services.worker as worker_mod

    _, first = _enqueue(tmp_path, "order-1")
    _, second = _enqueue(tmp_path, "order-2")
    _, third = _enqueue(tmp_path, "order-3")

    processed: list[int] = []

    def fake_run(job_id: int):
        processed.append(job_id)
        mark_job_completed(job_id)
        return {"ok": True}

    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", fake_run)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", fake_run)

    worker_mod.run_worker(once=True)
    worker_mod.run_worker(once=True)
    worker_mod.run_worker(once=True)

    assert processed == [first, second, third]
    with get_connection() as connection:
        statuses = {
            row["id"]: row["status"]
            for row in connection.execute("SELECT id, status FROM pipeline_jobs").fetchall()
        }
    assert statuses == {first: "completed", second: "completed", third: "completed"}


def test_failing_job_retries_then_fails_with_reason(isolated_db, tmp_path, monkeypatch) -> None:
    import services.pipeline.tasks as pipeline_tasks
    import services.worker as worker_mod

    application_id, job_id = _enqueue(tmp_path, "always-fails")

    def always_raise(job_id: int):
        raise RuntimeError("File is corrupted or unreadable")

    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", always_raise)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", always_raise)

    def clear_next_run() -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET next_run_at = NULL WHERE id = ?", (job_id,)
            )

    def job_state():
        with get_connection() as connection:
            return connection.execute(
                "SELECT status, attempt, next_run_at, failure_reason FROM pipeline_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()

    # Attempt 1 -> retrying with a future next_run_at.
    worker_mod.run_worker(once=True)
    state = job_state()
    assert state["status"] == "retrying"
    assert int(state["attempt"]) == 1
    assert state["next_run_at"] is not None
    assert state["failure_reason"] is None

    # Not due yet: a second pass processes nothing.
    assert worker_mod.process_once() is False
    assert int(job_state()["attempt"]) == 1

    # Attempt 2 -> retrying again.
    clear_next_run()
    worker_mod.run_worker(once=True)
    state = job_state()
    assert state["status"] == "retrying"
    assert int(state["attempt"]) == 2

    # Attempt 3 -> terminal failure with a readable reason.
    clear_next_run()
    worker_mod.run_worker(once=True)
    state = job_state()
    assert state["status"] == "failed"
    assert int(state["attempt"]) == 3
    assert state["failure_reason"] == "File is corrupted or unreadable."

    with get_connection() as connection:
        application = connection.execute(
            "SELECT status FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
    assert application["status"] == "failed"


def test_stale_running_job_is_recovered(isolated_db, tmp_path) -> None:
    import services.worker as worker_mod

    _, job_id = _enqueue(tmp_path, "stale")
    old_heartbeat = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    with get_connection() as connection:
        connection.execute(
            "UPDATE pipeline_jobs SET status = 'running', attempt = 2, heartbeat_at = ? WHERE id = ?",
            (old_heartbeat, job_id),
        )

    assert worker_mod.recover_stale_jobs() == 1
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status, attempt FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    assert row["status"] == "retrying"
    assert int(row["attempt"]) == 2


def test_sigterm_flag_finishes_current_job(isolated_db, tmp_path, monkeypatch) -> None:
    import services.pipeline.tasks as pipeline_tasks
    import services.worker as worker_mod

    _, job_id = _enqueue(tmp_path, "sigterm")

    def fake_run(job_id: int):
        mark_job_completed(job_id)
        return {"ok": True}

    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", fake_run)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", fake_run)
    try:
        worker_mod.request_shutdown()
        assert worker_mod._shutdown_requested is True
        # --once still finishes the current job before exiting.
        worker_mod.run_worker(once=True)
        with get_connection() as connection:
            status = connection.execute(
                "SELECT status FROM pipeline_jobs WHERE id = ?", (job_id,)
            ).fetchone()["status"]
        assert status == "completed"
        # The looping mode exits immediately once shutdown was requested.
        worker_mod.run_worker(poll_seconds=0.01)
    finally:
        worker_mod._shutdown_requested = False


def test_inline_disabled_runs_no_pipeline_code_in_api(tmp_path, monkeypatch) -> None:
    """With DMEF_INLINE_WORKER=0 the upload request only enqueues."""
    from fastapi.testclient import TestClient

    import routes.upload as upload_route
    from main import app

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")

    import services.pipeline.tasks as pipeline_tasks

    def explode(*args, **kwargs):
        raise AssertionError("pipeline must not run inside the API process")

    monkeypatch.setattr(pipeline_tasks, "_do_pipeline_work", explode)
    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", explode)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", explode)

    import fitz

    pdf_path = tmp_path / "inline.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Applicant Name: Ramesh Kumar\nPAN: ABCDE1234F")
    doc.save(pdf_path)
    doc.close()

    response = TestClient(app).post(
        "/upload",
        data={
            "loan_id": "LAP-INLINE-000",
            "applicant_name": "Ramesh Kumar",
            "coapplicant_name": "",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        files={"file": ("inline.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_status"] == "queued"
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, attempt FROM pipeline_jobs WHERE id = ?", (body["job_id"],)
        ).fetchone()
    assert job["status"] == "queued"
    assert int(job["attempt"]) == 0
