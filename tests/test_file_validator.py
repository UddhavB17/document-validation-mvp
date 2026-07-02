from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import database.db as db
import routes.upload as upload_route
from main import app
from services.file_validator import MAX_FILE_SIZE_BYTES, max_file_size_bytes, validate_file, validate_upload


def _create_pdf(path: Path, text_pages: int = 1, blank_pages: int = 0) -> None:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()

    for index in range(text_pages):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            f"Digital loan application page {index + 1}. "
            "Applicant details, PAN, loan amount, branch, and address are present.",
        )

    for _ in range(blank_pages):
        doc.new_page()

    doc.save(path)
    doc.close()


def test_validate_upload_accepts_pdf() -> None:
    result = validate_upload("loan-file.pdf")
    assert result["is_valid"] is True
    assert result["errors"] == []


def test_validate_upload_accepts_pdf_uppercase() -> None:
    result = validate_upload("LOAN-FILE.PDF")
    assert result["is_valid"] is True


def test_validate_upload_rejects_docx() -> None:
    result = validate_upload("loan-file.docx")
    assert result["is_valid"] is False
    assert any("PDF" in err for err in result["errors"])


def test_validate_upload_rejects_empty_filename() -> None:
    result = validate_upload("")
    assert result["is_valid"] is False


def test_validate_upload_rejects_no_extension() -> None:
    result = validate_upload("loanfile")
    assert result["is_valid"] is False


def test_validate_upload_accepts_file_within_size_limit() -> None:
    result = validate_upload("loan.pdf", file_size_bytes=1024)
    assert result["is_valid"] is True


def test_validate_upload_rejects_oversized_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_UPLOAD_SIZE_MB", raising=False)
    result = validate_upload("loan.pdf", file_size_bytes=MAX_FILE_SIZE_BYTES + 1)
    assert result["is_valid"] is False
    assert any("100MB" in err for err in result["errors"])


def test_validate_upload_uses_configurable_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "300")

    assert max_file_size_bytes() == 300 * 1024 * 1024
    result = validate_upload("loan.pdf", file_size_bytes=200 * 1024 * 1024)

    assert result["is_valid"] is True


def test_valid_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "valid.pdf"
    _create_pdf(pdf_path)

    result = validate_file(pdf_path, pdf_path.stat().st_size)

    assert result["valid"] is True


def test_wrong_file_type(tmp_path: Path) -> None:
    file_path = tmp_path / "loan.xlsx"
    file_path.write_text("not a pdf", encoding="utf-8")

    result = validate_file(file_path, file_path.stat().st_size)

    assert result == {"valid": False, "error": "Only PDF files accepted"}


def test_empty_file(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.pdf"
    file_path.write_bytes(b"")

    result = validate_file(file_path, file_path.stat().st_size)

    assert result == {"valid": False, "error": "File is empty"}


def test_file_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_UPLOAD_SIZE_MB", raising=False)
    file_path = tmp_path / "large.pdf"
    file_path.write_bytes(b"%PDF")

    result = validate_file(file_path, 200 * 1024 * 1024)

    assert result == {"valid": False, "error": "File too large, max 100MB"}


def test_corrupted_pdf(tmp_path: Path) -> None:
    file_path = tmp_path / "corrupted.pdf"
    file_path.write_text("garbage content", encoding="utf-8")

    result = validate_file(file_path, file_path.stat().st_size)

    assert result == {"valid": False, "error": "File is corrupted or unreadable"}


def test_page_count_detection(tmp_path: Path) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    _create_pdf(pdf_path, text_pages=3, blank_pages=2)

    result = validate_file(pdf_path, pdf_path.stat().st_size)

    assert result["valid"] is True
    assert result["total_pages"] == 5
    assert result["digital_pages"] == 3
    assert result["scanned_pages"] == 2


def test_database_application_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "dmef.db"
    uploads_path = tmp_path / "uploads"
    pdf_path = tmp_path / "upload.pdf"
    _create_pdf(pdf_path)

    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    monkeypatch.setattr(upload_route, "UPLOAD_DIR", uploads_path)

    client = TestClient(app)
    response = client.post(
        "/upload",
        data={
            "loan_id": "LAP-001",
            "applicant_name": "Ramesh Kumar",
            "coapplicant_name": "",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        files={"file": ("upload.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    application_id = response.json()["application_id"]

    with db.get_connection() as connection:
        application = connection.execute(
            "SELECT loan_id FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    assert application["loan_id"] == "LAP-001"
