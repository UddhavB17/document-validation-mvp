from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

import database.db as db
import services.reprocessing as reprocessing
from database.db import get_connection, init_db
from main import app
from services.progress_tracker import get_progress, start_tracking


def _seed_pdf_application(tmp_path: Path, *, progress_status: str = "failed") -> tuple[int, Path]:
    init_db()
    pdf_path = tmp_path / "source.pdf"
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Evidence page for operational review")
    document.save(pdf_path)
    document.close()
    with get_connection() as connection:
        application_id = int(
            connection.execute(
                """
                INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("OPS-001", "Ramesh Kumar", "LAP", "Delhi", "pipeline_failed"),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, total_pages, digital_pages, scanned_pages
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (application_id, str(pdf_path), "source.pdf", 1, 1, 0),
        )
    start_tracking(application_id, total_pages=1, digital_pages=1)
    with get_connection() as connection:
        connection.execute(
            "UPDATE pipeline_progress SET status = ?, stage = ? WHERE application_id = ?",
            (progress_status, progress_status, application_id),
        )
    return application_id, pdf_path


def test_progress_marks_old_processing_job_stale(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id, _ = _seed_pdf_application(tmp_path, progress_status="processing")
    old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with get_connection() as connection:
        connection.execute(
            "UPDATE pipeline_progress SET updated_at = ? WHERE application_id = ?",
            (old_time, application_id),
        )

    progress = get_progress(application_id)

    assert progress is not None
    assert progress["operational_status"] == "stale"
    assert progress["is_stale"] is True
    assert progress["retryable"] is True


def test_source_pdf_endpoint_returns_inline_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id, pdf_path = _seed_pdf_application(tmp_path)
    client = TestClient(app)

    response = client.get(f"/review/applications/{application_id}/source-pdf")

    assert response.status_code == 200
    assert response.content == pdf_path.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")


def test_source_page_endpoint_renders_exact_page_image(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id, _ = _seed_pdf_application(tmp_path)
    client = TestClient(app)

    response = client.get(f"/review/applications/{application_id}/source-page/1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert client.get(f"/review/applications/{application_id}/source-page/2").status_code == 404


def test_failed_application_can_be_queued_for_reprocess(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id, _ = _seed_pdf_application(tmp_path)
    submitted = []
    monkeypatch.setattr(reprocessing, "submit_job", lambda *args: submitted.append(args))

    result = reprocessing.queue_application_reprocess(application_id)

    assert result["pipeline_status"] == "queued"
    assert result["previous_pipeline_status"] == "failed"
    assert submitted
    with get_connection() as connection:
        job = connection.execute(
            "SELECT job_type, status FROM pipeline_jobs WHERE id = ?", (result["job_id"],)
        ).fetchone()
        audit = connection.execute(
            "SELECT action FROM audit_log WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
    assert dict(job) == {"job_type": "pdf_reprocess", "status": "queued"}
    assert audit["action"] == "pipeline_reprocess_queued"


def test_explicit_restart_can_reprocess_a_completed_application(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id, _ = _seed_pdf_application(tmp_path, progress_status="completed")
    submitted = []
    monkeypatch.setattr(reprocessing, "submit_job", lambda *args: submitted.append(args))

    result = reprocessing.restart_application(
        application_id,
        from_checkpoint=True,
        refresh_cached_ocr=True,
    )

    assert result["previous_pipeline_status"] == "completed"
    assert result["resume_from_checkpoint"] is True
    assert result["refresh_cached_ocr"] is True
    assert submitted
