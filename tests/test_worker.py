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


@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
def test_failure_runs_pipeline_only_once_per_claim(
    isolated_db, tmp_path, monkeypatch, mapped, terminal
) -> None:
    import services.job_control as control
    import services.pipeline.tasks as pipeline_tasks
    import services.worker as worker_mod

    _, job_id = _enqueue(tmp_path, "single-run")
    monkeypatch.setattr(
        control, "load_job_input", lambda *_: {"mapped_manifest": {}} if mapped else {}
    )
    calls = []

    def run_plain(_job_id):
        calls.append("plain")
        raise error_type("processing interrupted")

    def run_mapped(_job_id):
        calls.append("mapped")
        raise error_type("processing interrupted")

    error_type = control.PipelineFailedError if terminal else RuntimeError
    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", run_plain)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", run_mapped)
    assert worker_mod.process_once() is True
    assert calls == ["mapped" if mapped else "plain"]
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, attempt, next_run_at FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    assert job["attempt"] == 1
    assert job["status"] == ("failed" if terminal else "retrying")
    assert (job["next_run_at"] is None) is terminal


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


def test_inline_disabled_runs_no_pipeline_code_in_api(tmp_path, monkeypatch, auth_headers) -> None:
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
        headers=auth_headers,
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


def test_worker_reloads_store_bytes_after_api_workdir_deleted(tmp_path, monkeypatch, auth_headers) -> None:
    """DMEF_INLINE_WORKER=0 upload → worker opens the PDF from the store.

    The API deletes the upload work dir in ``finally`` after enqueue; the
    worker must re-stage the durable bytes from the object store into
    ``DMEF_JOB_WORK_DIR`` before checksum/load. The heavy pipeline is stubbed
    with a function that asserts a real file exists and matches the stored
    bytes.
    """

    import hashlib
    import shutil

    import database.db as db_module
    from database.db import get_connection, init_db

    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("DMEF_STORAGE_BACKEND", raising=False)
    init_db()

    import services.pipeline.orchestrator as orchestrator
    import services.worker as worker_mod
    from services.storage import get_store
    from services.storage.refs import get_ref

    seen: dict[str, object] = {}

    def fake_heavy_pipeline(pdf_path, application_id, **kwargs):
        candidate = Path(str(pdf_path))
        assert candidate.is_file(), f"worker staged source is missing: {pdf_path}"
        data = candidate.read_bytes()
        seen["path"] = str(candidate)
        seen["sha"] = hashlib.sha256(data).hexdigest()
        seen["application_id"] = int(application_id)
        # Staged file must live under the job work dir, not the deleted upload dir.
        assert str(tmp_path / "jobs") in str(candidate)
        return {"pipeline_status": "completed", "final_status": "CLEAN"}

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_heavy_pipeline)

    import fitz
    from fastapi.testclient import TestClient

    from main import app

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Applicant Name: Ramesh Kumar\nPAN: ABCDE1234F")
    pdf_bytes = doc.tobytes()
    doc.close()
    expected_sha = hashlib.sha256(pdf_bytes).hexdigest()

    response = TestClient(app).post(
        "/upload",
        headers=auth_headers,
        data={
            "loan_id": "LAP-STORE-RELOAD-001",
            "applicant_name": "Ramesh Kumar",
            "coapplicant_name": "",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        files={"file": ("reload.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    job_id = int(body["job_id"])
    application_id = int(body["application_id"])

    # Durable bytes are in the store.
    ref = get_ref("applications", application_id, "source")
    assert ref is not None
    assert get_store().get(str(ref["storage_key"])) == pdf_bytes

    # Simulate the API process going away: delete any leftover job work dir
    # content that is not the durable store. The worker must still succeed.
    jobs_root = tmp_path / "jobs"
    if jobs_root.is_dir():
        for child in list(jobs_root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    assert worker_mod.process_once() is True
    assert seen.get("application_id") == application_id
    assert seen.get("sha") == expected_sha
    # The staged job file is cleaned after the run, so only assert a path
    # was staged (existence during the run is asserted inside the fake).
    assert seen.get("path")
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    assert job["status"] == "completed"


@pytest.mark.parametrize("scoped", [False, True])
def test_concurrent_claimers_single_winner(tmp_path, monkeypatch, scoped) -> None:
    """Two SQLite claimers cannot both claim the same queued row (BEGIN IMMEDIATE)."""
    import threading

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    init_db()

    _, job_id = _enqueue(tmp_path, "concurrent")

    import services.worker as worker_mod

    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def _claim(slot: int) -> None:
        try:
            barrier.wait(timeout=5)
        except Exception:
            pass
        try:
            results[slot] = worker_mod.claim_next_job(job_id if scoped else None)
        except Exception as exc:  # noqa: BLE001
            results[slot] = exc

    threads = [threading.Thread(target=_claim, args=(slot,)) for slot in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    claimed_ids = [
        int(result["id"]) for result in results if isinstance(result, dict) and result.get("id")
    ]
    # Exactly one thread wins the single queued row.
    assert len(claimed_ids) == 1
    assert claimed_ids[0] == job_id


def test_claim_sql_dialect_branching(monkeypatch) -> None:
    """Postgres dequeue uses FOR UPDATE SKIP LOCKED; SQLite does not."""
    import database.db as db_module
    import services.worker as worker_mod

    monkeypatch.setattr(db_module, "dialect", lambda: "postgresql")
    assert "FOR UPDATE SKIP LOCKED" in worker_mod._claim_select_sql()
    monkeypatch.setattr(db_module, "dialect", lambda: "sqlite")
    assert "FOR UPDATE SKIP LOCKED" not in worker_mod._claim_select_sql()


def test_scoped_worker_leaves_other_jobs_untouched(isolated_db, tmp_path, monkeypatch):
    import services.worker as worker

    _, older = _enqueue(tmp_path, "older")
    _, stale = _enqueue(tmp_path, "stale-other")
    _, target = _enqueue(tmp_path, "target")
    with get_connection() as connection:
        connection.execute(
            "UPDATE pipeline_jobs SET status = 'running', heartbeat_at = NULL WHERE id = ?",
            (stale,),
        )
    seen = []

    def finish(job):
        seen.append(job["id"])
        mark_job_completed(job["id"])

    monkeypatch.setattr(worker, "run_job_by_id", finish)
    worker.run_worker(job_id=target, poll_seconds=0.001)
    assert seen == [target]
    with get_connection() as connection:
        states = {
            row["id"]: (row["status"], row["attempt"])
            for row in connection.execute("SELECT id, status, attempt FROM pipeline_jobs").fetchall()
        }
    assert states == {older: ("queued", 0), stale: ("running", 0), target: ("completed", 1)}


def test_scoped_worker_obeys_retry_schedule(isolated_db, tmp_path, monkeypatch):
    import services.worker as worker

    _, target = _enqueue(tmp_path, "scoped-retry")
    seen = []

    def run(job):
        seen.append(job["attempt"])
        if len(seen) == 1:
            worker.handle_job_exception(target, RuntimeError("transient"))
        else:
            mark_job_completed(target)

    def advance(_seconds):
        assert worker.claim_next_job(target) is None
        with get_connection() as connection:
            connection.execute("UPDATE pipeline_jobs SET next_run_at = NULL WHERE id = ?", (target,))

    monkeypatch.setattr(worker, "run_job_by_id", run)
    monkeypatch.setattr(worker.time, "sleep", advance)
    worker.run_worker(job_id=target)
    assert seen == [1, 2]


@pytest.mark.parametrize("status,control", [("running", "running"), ("queued", "paused"), ("completed", "completed")])
def test_scoped_worker_does_not_reclaim_ineligible_job(isolated_db, tmp_path, monkeypatch, status, control):
    import services.worker as worker

    _, target = _enqueue(tmp_path, "ineligible")
    with get_connection() as connection:
        connection.execute("UPDATE pipeline_jobs SET status = ?, control_state = ? WHERE id = ?", (status, control, target))
    seen = []
    monkeypatch.setattr(worker, "run_job_by_id", lambda job: seen.append(job))
    worker.run_worker(job_id=target)
    assert seen == []


def test_transient_failure_keeps_application_processing_until_exhausted(
    isolated_db, tmp_path, monkeypatch
) -> None:
    """First crash → retrying without app failed; third crash → both failed."""
    import services.pipeline.tasks as pipeline_tasks
    import services.worker as worker_mod

    application_id, job_id = _enqueue(tmp_path, "retry-app-status")

    def always_raise(job_id: int):
        raise RuntimeError("transient boom")

    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", always_raise)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", always_raise)

    def clear_next_run() -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET next_run_at = NULL WHERE id = ?", (job_id,)
            )

    def states():
        with get_connection() as connection:
            job = connection.execute(
                "SELECT status, attempt FROM pipeline_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            app = connection.execute(
                "SELECT status FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
        return str(job["status"]), int(job["attempt"]), str(app["status"])

    worker_mod.run_worker(once=True)
    status, attempt, app_status = states()
    assert status == "retrying"
    assert attempt == 1
    assert app_status != "failed"

    clear_next_run()
    worker_mod.run_worker(once=True)
    status, attempt, app_status = states()
    assert status == "retrying"
    assert attempt == 2
    assert app_status != "failed"

    clear_next_run()
    worker_mod.run_worker(once=True)
    status, attempt, app_status = states()
    assert status == "failed"
    assert attempt == 3
    assert app_status == "failed"


def test_clean_pipeline_failure_is_terminal_without_retry(
    isolated_db, tmp_path, monkeypatch
) -> None:
    """pipeline_status=='failed' must not be retried as a transient crash."""
    import services.pipeline.tasks as pipeline_tasks
    import services.worker as worker_mod
    from services.job_control import PipelineFailedError

    application_id, job_id = _enqueue(tmp_path, "clean-failure")

    def clean_failure(job_id: int):
        raise PipelineFailedError("Pipeline completed with failed outcome")

    monkeypatch.setattr(pipeline_tasks, "run_pipeline_job", clean_failure)
    monkeypatch.setattr(pipeline_tasks, "run_mapped_job", clean_failure)

    worker_mod.run_worker(once=True)
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, attempt FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        app = connection.execute(
            "SELECT status FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
    assert str(job["status"]) == "failed"
    assert int(job["attempt"]) == 1
    assert str(app["status"]) == "failed"
    # No retry scheduled even though attempts remain.
    with get_connection() as connection:
        next_run = connection.execute(
            "SELECT next_run_at FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()["next_run_at"]
    # Terminal failure clears next_run_at (stays failed, not retrying).
    assert next_run is None
    assert worker_mod.process_once() is False
