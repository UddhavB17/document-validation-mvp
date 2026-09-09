"""Batch upload endpoint tests: one batch_id, per-file jobs, rejected items."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import database.db as db
import routes.upload as upload_route
from database.db import get_connection
from main import app


@pytest.fixture()
def batch_client(tmp_path, monkeypatch, auth_headers):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("DMEF_STORAGE_BACKEND", raising=False)
    client = TestClient(app)
    client.headers.update(auth_headers)
    return client


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


def test_batch_single_pdf_uses_object_store(tmp_path, monkeypatch, auth_headers) -> None:
    """POST /upload/batch with one PDF lives in the store, not data/uploads."""
    from pathlib import Path

    import database.db as db_module

    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("DMEF_STORAGE_BACKEND", raising=False)
    client = TestClient(app)
    client.headers.update(auth_headers)

    from services.storage import get_store
    from services.storage.refs import get_ref

    uploads_root = Path("data/uploads")
    before = (
        {p.relative_to(uploads_root).as_posix() for p in uploads_root.rglob("*") if p.is_file()}
        if uploads_root.is_dir()
        else set()
    )

    pdf = _pdf_bytes("Batch Store")
    response = _post_batch(client, [("store-one.pdf", pdf, "application/pdf")])
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "queued"
    application_id = int(item["application_id"])

    with get_connection() as connection:
        refs = connection.execute(
            "SELECT COUNT(*) AS total FROM object_refs WHERE owner_table = 'applications'"
            " AND owner_id = ?",
            (str(application_id),),
        ).fetchone()["total"]
        uploaded = connection.execute(
            "SELECT file_path FROM uploaded_files WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    assert int(refs) >= 1
    file_path = uploaded["file_path"] if uploaded else None
    assert file_path is None or not Path(str(file_path)).is_absolute(), (
        f"batch file_path must not be an absolute local path, got {file_path!r}"
    )

    ref = get_ref("applications", application_id, "source")
    assert ref is not None
    assert get_store().get(str(ref["storage_key"])) == pdf

    after = (
        {p.relative_to(uploads_root).as_posix() for p in uploads_root.rglob("*") if p.is_file()}
        if uploads_root.is_dir()
        else set()
    )
    assert after == before
    # No batch PDFs left under the legacy tree or the monkeypatched UPLOAD_DIR.
    assert not list((tmp_path / "uploads").rglob("*.pdf"))


def test_batch_status_includes_rejected_files(batch_client) -> None:
    """GET /upload/batch/{id} surfaces rejected files for the UI table."""
    response = _post_batch(
        batch_client,
        [
            ("good.pdf", _pdf_bytes("Ramesh Good"), "application/pdf"),
            ("notes.txt", b"not a pdf", "text/plain"),
        ],
    )
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]

    status = batch_client.get(f"/upload/batch/{batch_id}")
    assert status.status_code == 200
    items = status.json()["items"]
    by_name = {item["filename"]: item for item in items}
    assert "notes.txt" in by_name
    assert by_name["notes.txt"]["status"] == "rejected"
    assert by_name["notes.txt"]["reason"]
    assert "good.pdf" in by_name


def test_batch_worker_processes_store_bytes_without_shared_upload_dir(
    tmp_path, monkeypatch, auth_headers
) -> None:
    """Batch job runs with DMEF_INLINE_WORKER=0 after the API work dir is gone."""
    import hashlib

    import database.db as db_module
    from database.db import init_db

    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_INLINE_WORKER", "0")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("DMEF_STORAGE_BACKEND", raising=False)
    init_db()

    import services.pipeline.orchestrator as orchestrator
    import services.worker as worker_mod

    seen: dict[str, object] = {}

    def fake_pipeline(pdf_path, application_id, **kwargs):
        candidate = Path(str(pdf_path))
        assert candidate.is_file()
        seen["sha"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        seen["application_id"] = int(application_id)
        return {"pipeline_status": "completed", "final_status": "CLEAN"}

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_pipeline)
    client = TestClient(app)
    client.headers.update(auth_headers)
    pdf = _pdf_bytes("Batch Worker")
    posted = _post_batch(client, [("worker.pdf", pdf, "application/pdf")]).json()
    assert posted["items"][0]["status"] == "queued"

    assert worker_mod.process_once() is True
    assert seen.get("sha") == hashlib.sha256(pdf).hexdigest()
