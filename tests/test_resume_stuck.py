"""Resume-from-checkpoint for crash-stuck jobs (tmp/user-portal-ux).

A worker killed mid-run (e.g. network outage) leaves the job ``running``
with a stale heartbeat while progress still reads ``processing``. The
worklist must offer Resume there, and the resume endpoint must reap the
stale job and requeue from the last checkpoint.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import database.db as db
from database.db import init_db
from main import app
from services.reprocessing import can_resume_application
from services.review.worklist import build_worklist


def _seed_application() -> int:
    init_db()
    with db.get_connection() as connection:
        created = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?) RETURNING id
            """,
            ("LAP-RESUME-1", "Sita Devi", "LAP", "Jaipur", "processing"),
        ).fetchone()
        return int(created["id"])


def _seed_progress(application_id: int, *, status: str = "processing", updated_ago_minutes: int = 0) -> None:
    now = datetime.now(UTC)
    updated = (now - timedelta(minutes=updated_ago_minutes)).isoformat()
    stamp = now.isoformat()
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_progress (
                application_id, stage, total_pages, processed_pages,
                percentage, status, started_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(application_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (application_id, "checks", 891, 58, 6.5, status, stamp, updated, None),
        )


def _seed_job(application_id: int, *, status: str, heartbeat_ago_minutes: int | None) -> int:
    now = datetime.now(UTC)
    heartbeat = (
        (now - timedelta(minutes=heartbeat_ago_minutes)).isoformat()
        if heartbeat_ago_minutes is not None
        else None
    )
    with db.get_connection() as connection:
        created = connection.execute(
            """
            INSERT INTO pipeline_jobs (
                application_id, job_type, status, control_state,
                attempt, max_attempts, heartbeat_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (application_id, "pdf_pipeline", status, "running", 1, 3, heartbeat, now.isoformat()),
        ).fetchone()
        return int(created["id"])


def _seed_upload(application_id: int, pdf_path) -> None:
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename,
                total_pages, digital_pages, scanned_pages
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (application_id, str(pdf_path), "source.pdf", 3, 3, 0),
        )


def test_can_resume_stale_running_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    _seed_application_id = _seed_application()
    _seed_progress(_seed_application_id)
    _seed_job(_seed_application_id, status="running", heartbeat_ago_minutes=60)

    assert can_resume_application(_seed_application_id) is True


def test_can_resume_live_running_job_is_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    _seed_application_id = _seed_application()
    _seed_progress(_seed_application_id)
    _seed_job(_seed_application_id, status="running", heartbeat_ago_minutes=0)

    assert can_resume_application(_seed_application_id) is False


def test_can_resume_failed_without_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    _seed_application_id = _seed_application()
    _seed_progress(_seed_application_id, status="failed", updated_ago_minutes=60)

    assert can_resume_application(_seed_application_id) is True


def test_can_resume_completed_is_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    _seed_application_id = _seed_application()
    now = datetime.now(UTC).isoformat()
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_progress (
                application_id, stage, total_pages, processed_pages,
                percentage, status, started_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_seed_application_id, "done", 3, 3, 100.0, "completed", now, now, now),
        )
    _seed_job(_seed_application_id, status="completed", heartbeat_ago_minutes=60)

    assert can_resume_application(_seed_application_id) is False


def test_worklist_flags_stuck_job_resumable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    _seed_progress(application_id)
    _seed_job(application_id, status="running", heartbeat_ago_minutes=60)

    items = build_worklist()["items"]
    item = next(entry for entry in items if entry["id"] == application_id)

    assert item["pipeline_status"] == "processing"
    assert item["pipeline_retryable"] is False
    assert item["pipeline_resumable"] is True


def test_resume_endpoint_requeues_stuck_job(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    import services.reprocessing as reprocessing

    submitted: list = []
    monkeypatch.setattr(
        reprocessing, "submit_job", lambda *args, **kwargs: submitted.append((args, kwargs))
    )
    application_id = _seed_application()
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake bytes for resume")
    _seed_upload(application_id, pdf_path)
    _seed_progress(application_id)
    _seed_job(application_id, status="running", heartbeat_ago_minutes=60)
    client = TestClient(app)

    response = client.post(
        f"/review/applications/{application_id}/resume", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert submitted, "resume must enqueue a new attempt"
    with db.get_connection() as connection:
        jobs = connection.execute(
            "SELECT status FROM pipeline_jobs WHERE application_id = ? ORDER BY id",
            (application_id,),
        ).fetchall()
    assert len(jobs) == 2
    assert str(jobs[1]["status"]) in {"queued", "retrying", "running"}


def test_resume_live_job_conflicts(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    _seed_progress(application_id)
    _seed_job(application_id, status="running", heartbeat_ago_minutes=0)
    client = TestClient(app)

    response = client.post(
        f"/review/applications/{application_id}/resume", headers=auth_headers
    )

    assert response.status_code == 409
