from pathlib import Path
import zipfile

from fastapi.testclient import TestClient

import database.db as db
import routes.upload as upload_route
from main import app


def _create_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Applicant Name: Ramesh Kumar\nPAN: ABCDE1234F\nLoan Amount: 500000")
    doc.save(path)
    doc.close()


def test_partner_json_runs_validation_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    client = TestClient(app)

    response = client.post(
        "/upload/json",
        json={
            "loan_id": "LAP-JSON-001",
            "applicant_name": "Ramesh Kumar",
            "product_type": "LAP",
            "branch": "Delhi",
            "digital_text": {
                "applicant_name": "Ramesh Kumar",
                "pan_number": "ABCDE1234F",
                "loan_amount": "500000",
            },
            "scanned_docs": {
                "pan_card": "INCOME TAX DEPARTMENT\nName: Ramesh Kumar\nABCDE1234F",
                "bank_statement": "Account Number: 123456789012\nStatement Date: 30/04/2026",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"]
    assert body["pipeline_status"] == "completed"
    assert body["status"] in {"CLEAN", "NEEDS_REVIEW", "CRITICAL"}
    assert "PAN" in body["documents_found"]

    with db.get_connection() as connection:
        page_count = connection.execute(
            "SELECT COUNT(*) AS total FROM pages WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()["total"]
        ground_truth = connection.execute(
            "SELECT pan_number FROM ground_truth WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()

    assert page_count == 2
    assert ground_truth["pan_number"] == "ABCDE1234F"


def test_pdf_upload_route_returns_processing_queued(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "run_pipeline", lambda *_args, **_kwargs: {"pipeline_status": "completed"})

    pdf_path = tmp_path / "upload.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)

    response = client.post(
        "/upload",
        data={
            "loan_id": "LAP-UPLOAD-001",
            "applicant_name": "Ramesh Kumar",
            "coapplicant_name": "",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        files={"file": ("upload.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["pipeline_status"] == "queued"
    assert body["loan_id"] == "LAP-UPLOAD-001"
    assert body["progress_url"] == f"/upload/{body['application_id']}/progress"

    progress_response = client.get(body["progress_url"])
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["application_id"] == body["application_id"]
    assert progress["stage"] in {"queued", "processing_pages"}
    assert progress["status"] in {"processing", "completed"}

    with db.get_connection() as connection:
        job = connection.execute(
            "SELECT status FROM pipeline_jobs WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()

    assert job["status"] == "completed"


def test_pdf_upload_rejects_oversized_stream_before_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    client = TestClient(app)

    response = client.post(
        "/upload",
        data={
            "loan_id": "LAP-LARGE-001",
            "applicant_name": "Ramesh Kumar",
            "coapplicant_name": "",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        files={"file": ("huge.pdf", b"0" * ((1024 * 1024) + 1), "application/pdf")},
    )

    assert response.status_code == 400
    assert "File too large" in response.json()["detail"]
    assert not list((tmp_path / "uploads").glob("*.pdf"))


def test_mapped_upload_rejects_page_outside_pdf(tmp_path, monkeypatch) -> None:
    import json

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    pdf_path = tmp_path / "mapped.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)

    response = client.post(
        "/upload/mapped",
        data={
            "manifest": json.dumps(
                {
                    "loan_id": "MAP-OUTSIDE-001",
                    "reference_data": {"pan_number": "ABCDE1234F"},
                    "documents": [{"document_type": "PAN", "pages": [2]}],
                }
            )
        },
        files={"file": ("mapped.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 422
    assert "exceeds PDF page count 1" in response.json()["detail"]
    assert not list((tmp_path / "uploads").glob("*.pdf"))


def test_mapped_upload_queues_valid_manifest(tmp_path, monkeypatch) -> None:
    import json

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "submit_job", lambda *_args, **_kwargs: None)
    pdf_path = tmp_path / "mapped.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)

    response = client.post(
        "/upload/mapped",
        data={
            "manifest": json.dumps(
                {
                    "loan_id": "MAP-VALID-001",
                    "applicant_name": "Ramesh Kumar",
                    "reference_data": {"pan_number": "ABCDE1234F"},
                    "documents": [{"document_type": "PAN", "pages": [1]}],
                }
            )
        },
        files={"file": ("mapped.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_status"] == "queued"
    assert body["mapped_pages"] == [1]
    assert body["summary_url"] == f"/verification/summary/{body['application_id']}"
    with db.get_connection() as connection:
        audit = connection.execute(
            "SELECT action FROM audit_log WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()
    assert audit["action"] == "mapped_file_uploaded"


def test_mapped_zip_upload_uses_manifest_from_package(tmp_path, monkeypatch) -> None:
    import json

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "submit_job", lambda *_args, **_kwargs: None)
    pdf_path = tmp_path / "mapped.pdf"
    zip_path = tmp_path / "mapped.zip"
    _create_pdf(pdf_path)
    manifest = {
        "loan_id": "MAP-ZIP-001",
        "applicant_name": "Ramesh Kumar",
        "reference_data": {"pan_number": "ABCDE1234F"},
        "documents": [{"document_type": "PAN", "pages": [1]}],
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(pdf_path, "loan_file.pdf")
        archive.writestr("manifest.json", json.dumps(manifest))

    client = TestClient(app)
    response = client.post(
        "/upload/mapped",
        files={"file": ("mapped.zip", zip_path.read_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["loan_id"] == "MAP-ZIP-001"
    assert body["mapped_pages"] == [1]

    with db.get_connection() as connection:
        uploaded = connection.execute(
            "SELECT original_filename FROM uploaded_files WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()
    assert uploaded["original_filename"] == "loan_file.pdf"


def test_mapped_zip_upload_requires_manifest_when_not_pasted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    pdf_path = tmp_path / "mapped.pdf"
    zip_path = tmp_path / "mapped.zip"
    _create_pdf(pdf_path)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(pdf_path, "loan_file.pdf")

    client = TestClient(app)
    response = client.post(
        "/upload/mapped",
        files={"file": ("mapped.zip", zip_path.read_bytes(), "application/zip")},
    )

    assert response.status_code == 422
    assert "JSON manifest" in response.json()["detail"]


def test_mapped_zip_upload_selects_pdf_named_in_manifest(tmp_path, monkeypatch) -> None:
    import json

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "submit_job", lambda *_args, **_kwargs: None)
    selected_pdf = tmp_path / "selected.pdf"
    other_pdf = tmp_path / "other.pdf"
    zip_path = tmp_path / "mapped.zip"
    _create_pdf(selected_pdf)
    _create_pdf(other_pdf)
    manifest = {
        "loan_id": "MAP-ZIP-SELECTED-001",
        "pdf_file": "selected.pdf",
        "applicant_name": "Ramesh Kumar",
        "reference_data": {"pan_number": "ABCDE1234F"},
        "documents": [{"document_type": "PAN", "pages": [1]}],
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(selected_pdf, "selected.pdf")
        archive.write(other_pdf, "other.pdf")
        archive.writestr("manifest.json", json.dumps(manifest))

    client = TestClient(app)
    response = client.post(
        "/upload/mapped",
        files={"file": ("mapped.zip", zip_path.read_bytes(), "application/zip")},
    )

    assert response.status_code == 200
    body = response.json()
    with db.get_connection() as connection:
        uploaded = connection.execute(
            "SELECT original_filename FROM uploaded_files WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()
    assert uploaded["original_filename"] == "selected.pdf"


