import json
import zipfile
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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


def _zip_bytes(files: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for filename, content in files:
            archive.writestr(filename, content)
    return buffer.getvalue()


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
    monkeypatch.setattr(
        upload_route, "run_pipeline", lambda *_args, **_kwargs: {"pipeline_status": "completed"}
    )
    monkeypatch.setattr(upload_route, "submit_job", lambda fn, *args, **kwargs: fn(*args, **kwargs))

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


def test_progress_poll_does_not_reinitialize_database(monkeypatch) -> None:
    monkeypatch.setattr(
        upload_route,
        "init_db",
        lambda: (_ for _ in ()).throw(
            AssertionError("progress polling must not initialize the database")
        ),
    )
    monkeypatch.setattr(
        upload_route,
        "get_progress",
        lambda application_id: {"application_id": application_id, "status": "processing"},
    )

    assert upload_route.upload_progress(80) == {"application_id": 80, "status": "processing"}


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


def test_trusted_json_upload_queues_automatic_page_identification(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "submit_job", lambda *_args, **_kwargs: None)
    pdf_path = tmp_path / "automatic.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)

    response = client.post(
        "/upload/mapped",
        data={
            "manifest": json.dumps(
                {
                    "loan_id": "AUTO-001",
                    "people": {
                        "primary": {
                            "applicant_name": "Ramesh Kumar",
                            "pan_number": "ABCDE1234F",
                        }
                    },
                    "document_index": [],
                }
            )
        },
        files={"file": ("automatic.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["automatic_mapping"] is True
    assert body["mapped_pages"] == []
    progress = client.get(body["progress_url"]).json()
    assert progress["total_pages"] == 1


def test_upload_route_accepts_raw_company_database_dump() -> None:
    parsed = upload_route._parse_manifest(
        """
        Loan Application: RJ000000042
        {"applicantdetails": {
          "loanId": 42,
          "entityName": "Ramesh Kumar",
          "dob": "01-January-1990"
        },
        "camdetails": {
          "loanId": 42,
          "loanamount": "500000"
        }}
        """
    )

    assert parsed.loan_id == "RJ000000042"
    assert parsed.people["primary"].applicant_name == "Ramesh Kumar"
    assert parsed.people["primary"].model_extra["loan_amount"] == "500000"
    assert parsed.document_index == []


def test_mapped_background_job_uses_shared_pdf_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    db.init_db()
    with db.get_connection() as connection:
        application_id = int(
            connection.execute(
                "INSERT INTO applications (loan_id, status) VALUES (?, 'processing')",
                ("MAP-SHARED-001",),
            ).lastrowid
        )
    job_id = upload_route.create_pipeline_job(application_id)
    captured = {}

    def fake_run_pipeline(file_path, passed_application_id, **kwargs):
        captured.update(
            {
                "file_path": file_path,
                "application_id": passed_application_id,
                **kwargs,
            }
        )
        return {"pipeline_status": "completed", "final_status": "CLEAN"}

    monkeypatch.setattr(upload_route, "run_pipeline", fake_run_pipeline)
    manifest = {
        "loan_id": "MAP-SHARED-001",
        "product_type": "LAP",
        "reference_data": {
            "primary": {"applicant_name": "Ramesh Kumar"},
        },
        "documents": [
            {
                "source_document_id": "file-0001",
                "applicant_role": "primary",
                "document_type": "PAN",
                "pages": [1],
            }
        ],
    }

    upload_route._run_mapped_pipeline_task(
        job_id,
        str(tmp_path / "normalized.pdf"),
        application_id,
        manifest,
    )

    assert captured["application_id"] == application_id
    assert captured["mapped_manifest"] == manifest
    assert captured["generate_llm_summary"] is True
    assert captured["system_data"]["applicant_name"] == "Ramesh Kumar"
    with db.get_connection() as connection:
        job = connection.execute(
            "SELECT status FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    assert job["status"] == "completed"


def test_zip_package_upload_returns_stable_inventory_and_persists_sources(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    pdf_path = tmp_path / "source.pdf"
    _create_pdf(pdf_path)
    package = _zip_bytes(
        [
            ("Applicant/PAN.pdf", pdf_path.read_bytes()),
            ("CoApplicant/PAN.pdf", pdf_path.read_bytes()),
        ]
    )

    response = TestClient(app).post(
        "/upload/package",
        files={"file": ("loan-documents.zip", package, "application/zip")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "prepared"
    assert body["total_files"] == 2
    assert body["total_pages"] == 2
    assert [item["pages"] for item in body["documents"]] == [[1], [2]]
    with db.get_connection() as connection:
        package_row = connection.execute(
            "SELECT status, total_files, total_pages FROM intake_packages WHERE package_id = ?",
            (body["package_id"],),
        ).fetchone()
        document_count = connection.execute(
            "SELECT COUNT(*) AS total FROM intake_documents WHERE package_id = ?",
            (body["package_id"],),
        ).fetchone()["total"]
    assert dict(package_row) == {"status": "prepared", "total_files": 2, "total_pages": 2}
    assert document_count == 2


def test_background_zip_preparation_exposes_frontend_logs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(
        upload_route,
        "submit_job",
        lambda function, *args, **kwargs: function(*args, **kwargs),
    )
    pdf_path = tmp_path / "source.pdf"
    _create_pdf(pdf_path)

    response = TestClient(app).post(
        "/upload/package?background=true",
        files={
            "file": (
                "loan.zip",
                _zip_bytes([("Applicant/PAN.pdf", pdf_path.read_bytes())]),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    queued = response.json()
    assert queued["status"] == "queued"
    progress = TestClient(app).get(queued["progress_url"])
    assert progress.status_code == 200
    body = progress.json()
    assert body["status"] == "prepared"
    assert body["total_files"] == 1
    assert body["documents"][0]["original_filename"] == "Applicant/PAN.pdf"
    assert any(event["stage"] == "file_completed" for event in body["events"])


def test_zip_progress_writer_retries_windows_replace_lock(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    original_replace = Path.replace
    attempts = 0

    def intermittently_locked(path: Path, target: Path):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "Access is denied", str(target))
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", intermittently_locked)

    upload_route._write_package_preparation_progress(
        package_dir,
        {
            "package_id": "a" * 32,
            "status": "preparing",
            "message": "Loading PAN.pdf",
        },
        append_event=True,
    )

    progress = json.loads((package_dir / "preparation_progress.json").read_text(encoding="utf-8"))
    assert attempts == 3
    assert progress["status"] == "preparing"
    assert progress["events"][0]["message"] == "Loading PAN.pdf"
    assert not list(package_dir.glob("*.tmp"))


def test_zip_progress_lock_does_not_fail_package_task(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    def always_locked(_path: Path, target: Path):
        raise PermissionError(5, "Access is denied", str(target))

    monkeypatch.setattr(Path, "replace", always_locked)

    upload_route._write_package_preparation_progress(
        package_dir,
        {"package_id": "b" * 32, "status": "preparing"},
    )

    assert not list(package_dir.glob("*.tmp"))


def test_zip_package_verification_reuses_mapped_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_route, "submit_job", lambda *_args, **_kwargs: None)
    pdf_path = tmp_path / "source.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)
    prepared = client.post(
        "/upload/package",
        files={
            "file": (
                "loan.zip",
                _zip_bytes([("Applicant/PAN.pdf", pdf_path.read_bytes())]),
                "application/zip",
            )
        },
    ).json()
    source = prepared["documents"][0]
    manifest = {
        "loan_id": "ZIP-MAPPED-001",
        "people": {"primary": {"applicant_name": "Ramesh Kumar", "pan_number": "ABCDE1234F"}},
        "document_index": [
            {
                "source_document_id": source["source_document_id"],
                "document_type": "PAN",
                "person_id": "primary",
                "pages": source["pages"],
            }
        ],
    }

    response = client.post(
        prepared["verify_url"],
        data={"manifest": json.dumps(manifest)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_status"] == "queued"
    assert body["mapped_pages"] == [1]
    assert body["source_documents"] == 1
    with db.get_connection() as connection:
        package_row = connection.execute(
            "SELECT status, application_id FROM intake_packages WHERE package_id = ?",
            (prepared["package_id"],),
        ).fetchone()
        audit = connection.execute(
            "SELECT action FROM audit_log WHERE application_id = ?",
            (body["application_id"],),
        ).fetchone()
    assert package_row["status"] == "processing"
    assert package_row["application_id"] == body["application_id"]
    assert audit["action"] == "mapped_package_verification_queued"

    duplicate = client.post(
        prepared["verify_url"],
        data={"manifest": json.dumps(manifest)},
    )
    assert duplicate.status_code == 409
    with db.get_connection() as connection:
        connection.execute(
            "UPDATE intake_packages SET status = 'completed' WHERE package_id = ?",
            (prepared["package_id"],),
        )
    retry = client.post(
        prepared["verify_url"],
        data={"manifest": json.dumps(manifest)},
    )
    assert retry.status_code == 200
    assert retry.json()["application_id"] != body["application_id"]


def test_zip_package_rejects_mapping_to_page_owned_by_another_source(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", tmp_path / "uploads")
    pdf_path = tmp_path / "source.pdf"
    _create_pdf(pdf_path)
    client = TestClient(app)
    prepared = client.post(
        "/upload/package",
        files={
            "file": (
                "loan.zip",
                _zip_bytes(
                    [
                        ("first.pdf", pdf_path.read_bytes()),
                        ("second.pdf", pdf_path.read_bytes()),
                    ]
                ),
                "application/zip",
            )
        },
    ).json()
    manifest = {
        "loan_id": "ZIP-BAD-MAP-001",
        "people": {"primary": {"applicant_name": "Ramesh Kumar"}},
        "document_index": [
            {
                "source_document_id": prepared["documents"][0]["source_document_id"],
                "document_type": "PAN",
                "person_id": "primary",
                "pages": [2],
            }
        ],
    }

    response = client.post(
        prepared["verify_url"],
        data={"manifest": json.dumps(manifest)},
    )

    assert response.status_code == 422
    assert "do not belong" in response.json()["detail"]
    inventory = client.get(f"/upload/package/{prepared['package_id']}").json()
    assert inventory["status"] == "prepared"

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
