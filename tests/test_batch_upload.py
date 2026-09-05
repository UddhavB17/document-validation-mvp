"""Batch upload endpoint tests: one batch_id, per-file jobs, rejected items."""

import pytest
from fastapi.testclient import TestClient

import database.db as db
import routes.upload as upload_route
from database.db import get_connection
from main import app


@pytest.fixture()
def batch_client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    return TestClient(app)


def _pdf_bytes(tag: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"Applicant Name: {tag}\nPAN: ABCDE1234F\nLoan Amount: 500000")
    data = doc.tobytes()
    doc.close()
    return data


def _post_batch(client: TestClient, files: list[tuple[str, bytes, str]]):
    return client.post(
        "/upload/batch",
        files=[("files", (name, content, content_type)) for name, content, content_type in files],
    )


def test_three_pdfs_share_one_batch_id(batch_client) -> None:
    response = _post_batch(
        batch_client,
        [
            ("loan-a.pdf", _pdf_bytes("Ramesh A"), "application/pdf"),
            ("loan-b.pdf", _pdf_bytes("Ramesh B"), "application/pdf"),
            ("loan-c.pdf", _pdf_bytes("Ramesh C"), "application/pdf"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"]
    assert len(body["items"]) == 3
    for item in body["items"]:
        assert item["status"] == "queued"
        assert item["application_id"]
        assert item["job_id"]

    with get_connection() as connection:
        app_count = connection.execute("SELECT COUNT(*) AS total FROM applications").fetchone()[
            "total"
        ]
        jobs = connection.execute(
            "SELECT id, application_id, status, attempt, batch_id FROM pipeline_jobs"
        ).fetchall()
    assert app_count == 3
    assert len(jobs) == 3
    assert {row["batch_id"] for row in jobs} == {body["batch_id"]}
    assert {row["status"] for row in jobs} == {"queued"}


def test_invalid_file_is_rejected_without_failing_batch(batch_client) -> None:
    response = _post_batch(
        batch_client,
        [
            ("good-1.pdf", _pdf_bytes("Ramesh Good"), "application/pdf"),
            ("notes.txt", b"not a pdf", "text/plain"),
            ("good-2.pdf", _pdf_bytes("Ramesh Better"), "application/pdf"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    by_name = {item["filename"]: item for item in body["items"]}
    assert by_name["notes.txt"]["status"] == "rejected"
    assert by_name["notes.txt"]["reason"]
    assert by_name["notes.txt"]["application_id"] is None
    assert by_name["good-1.pdf"]["status"] == "queued"
    assert by_name["good-2.pdf"]["status"] == "queued"

    with get_connection() as connection:
        job_count = connection.execute("SELECT COUNT(*) AS total FROM pipeline_jobs").fetchone()[
            "total"
        ]
    assert job_count == 2


def test_batch_status_endpoint_shape(batch_client) -> None:
    posted = _post_batch(
        batch_client,
        [
            ("status-1.pdf", _pdf_bytes("Ramesh One"), "application/pdf"),
            ("status-2.pdf", _pdf_bytes("Ramesh Two"), "application/pdf"),
        ],
    ).json()

    response = batch_client.get(f"/upload/batch/{posted['batch_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"] == posted["batch_id"]
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["application_id"]
        assert item["filename"] in {"status-1.pdf", "status-2.pdf"}
        assert item["status"] == "queued"
        assert item["attempt"] == 0
        assert item["failure_reason"] is None
        assert item["progress_percentage"] == 0.0
        assert item["review_ready"] is False

    assert batch_client.get("/upload/batch/0" * 1 + "f" * 31).status_code == 404
