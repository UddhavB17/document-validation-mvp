from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.pipeline import run_pipeline


def _create_application_pdf(path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Loan Application Form\n"
        "Applicant Name: Ramesh Kumar\n"
        "Loan Amount: Rs. 500000\n"
        "Product Type: LAP\n"
        "Address: 12 Market Road Delhi\n"
        "This digital page contains enough selectable text for processing.",
    )
    doc.save(path)
    doc.close()


def test_run_pipeline_persists_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "dmef.db"
    pdf_path = tmp_path / "application.pdf"
    output_dir = tmp_path / "processed"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    _create_application_pdf(pdf_path)

    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            """,
            ("LAP-PIPE-001", "Ramesh Kumar", "LAP", "Delhi"),
        )
        application_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, file_size_kb,
                total_pages, digital_pages, scanned_pages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (application_id, str(pdf_path), "application.pdf", 1.0, 0, 0, 0),
        )

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={
            "loan_id": "LAP-PIPE-001",
            "applicant_name": "Ramesh Kumar",
            "product_type": "LAP",
            "branch": "Delhi",
        },
        product_type="LAP",
        generate_llm_summary=False,
    )

    assert result["pipeline_status"] == "completed"
    assert result["total_pages"] == 1
    assert result["digital_pages"] == 1
    assert result["final_status"] in {"CLEAN", "NEEDS_REVIEW", "CRITICAL"}

    with get_connection() as connection:
        application = connection.execute(
            "SELECT status, llm_summary FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        progress = connection.execute(
            "SELECT stage, status, percentage, processed_pages, total_pages FROM pipeline_progress WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        ground_truth = connection.execute(
            "SELECT applicant_name, loan_amount FROM ground_truth WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        page_count = connection.execute(
            "SELECT COUNT(*) AS total FROM pages WHERE application_id = ?",
            (application_id,),
        ).fetchone()["total"]
        anomaly_count = connection.execute(
            "SELECT COUNT(*) AS total FROM validation_results WHERE application_id = ?",
            (application_id,),
        ).fetchone()["total"]

    assert application["status"] == result["final_status"]
    assert application["llm_summary"]
    assert ground_truth["applicant_name"] == "Ramesh Kumar"
    assert ground_truth["loan_amount"] == "500000"
    assert page_count == 1
    assert anomaly_count == len(result["anomalies"])
    assert progress["stage"] == "completed"
    assert progress["status"] == "completed"
    assert progress["percentage"] == 100.0
    assert progress["processed_pages"] == progress["total_pages"] == 1


def test_run_pipeline_saves_rule_summary_when_llm_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "dmef.db"
    pdf_path = tmp_path / "application.pdf"
    output_dir = tmp_path / "processed"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    monkeypatch.setattr("services.pipeline.generate_explanation", lambda *args, **kwargs: None)
    _create_application_pdf(pdf_path)

    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            """,
            ("LAP-PIPE-002", "Ramesh Kumar", "LAP", "Delhi"),
        )
        application_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, file_size_kb,
                total_pages, digital_pages, scanned_pages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (application_id, str(pdf_path), "application.pdf", 1.0, 0, 0, 0),
        )

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={"loan_id": "LAP-PIPE-002", "applicant_name": "Ramesh Kumar"},
        product_type="LAP",
        generate_llm_summary=True,
    )

    with get_connection() as connection:
        application = connection.execute(
            "SELECT llm_summary FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    assert result["llm_summary"]
    assert application["llm_summary"] == result["llm_summary"]
    assert "exception(s) require review" in application["llm_summary"]


def test_run_pipeline_continues_when_page_processing_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "dmef.db"
    pdf_path = tmp_path / "application.pdf"
    output_dir = tmp_path / "processed"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    _create_application_pdf(pdf_path)
    monkeypatch.setattr("services.pipeline.extract_fields", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            """,
            ("LAP-PIPE-003", "Ramesh Kumar", "LAP", "Delhi"),
        )
        application_id = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO uploaded_files (
                application_id, file_path, original_filename, file_size_kb,
                total_pages, digital_pages, scanned_pages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (application_id, str(pdf_path), "application.pdf", 1.0, 0, 0, 0),
        )

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={"loan_id": "LAP-PIPE-003", "applicant_name": "Ramesh Kumar"},
        product_type="LAP",
        generate_llm_summary=False,
    )

    with get_connection() as connection:
        page = connection.execute(
            "SELECT extracted_fields FROM pages WHERE application_id = ? ORDER BY page_number ASC LIMIT 1",
            (application_id,),
        ).fetchone()
        progress = connection.execute(
            "SELECT stage, status, processed_pages, total_pages FROM pipeline_progress WHERE application_id = ?",
            (application_id,),
        ).fetchone()

    assert result["pipeline_status"] == "completed"
    assert "\"_processing_error\": \"boom\"" in page["extracted_fields"]
    assert progress["stage"] == "completed"
    assert progress["status"] == "completed"
    assert progress["processed_pages"] == progress["total_pages"] == 1
