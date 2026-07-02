from pathlib import Path

import pytest

import database.db as db
import services.report_generator as report_generator
from database.db import init_db
from services.report_generator import build_report, generate_excel_report, save_report_json


def _seed_application() -> int:
    init_db()
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("LAP-REPORT-1", "Ramesh Kumar", "LAP", "Delhi", "CRITICAL"),
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
            (application_id, "data/uploads/sample.pdf", "sample.pdf", 12.0, 5, 2, 3),
        )
        connection.execute(
            """
            INSERT INTO validation_results (
                application_id, rule_id, severity, document_type,
                expected_value, found_value, page_number, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                "MISSING_DOC_S7",
                "HIGH",
                "PAN",
                "Document present",
                "Not found",
                None,
                "PAN card mandatory",
            ),
        )
    return application_id


@pytest.mark.skipif(pytest.importorskip("openpyxl") is None, reason="openpyxl required")
def test_excel_file_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(report_generator, "REPORT_DIR", tmp_path)
    application_id = _seed_application()

    report_path = generate_excel_report(application_id)

    assert Path(report_path).exists()


def test_excel_has_two_sheets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(report_generator, "REPORT_DIR", tmp_path)
    application_id = _seed_application()

    workbook = openpyxl.load_workbook(generate_excel_report(application_id))

    assert workbook.sheetnames == ["Summary", "Anomalies"]


def test_excel_anomaly_colors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(report_generator, "REPORT_DIR", tmp_path)
    application_id = _seed_application()

    workbook = openpyxl.load_workbook(generate_excel_report(application_id))

    assert workbook["Anomalies"]["B2"].fill.fgColor.rgb in {"00FF4444", "FFFF4444"}


def test_excel_empty_anomalies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setattr(report_generator, "REPORT_DIR", tmp_path)
    init_db()
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("LAP-CLEAN-1", "Ramesh Kumar", "LAP", "Delhi", "CLEAN"),
        )
        application_id = cursor.lastrowid

    workbook = openpyxl.load_workbook(generate_excel_report(application_id))

    assert workbook["Anomalies"].max_row == 1


def test_report_json_sanitizes_loan_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_generator, "REPORTS_DIR", tmp_path)

    report_path = save_report_json(build_report(1, loan_id="../bad/loan id"))

    assert report_path.parent == tmp_path
    assert report_path.name == "report_1_bad_loan_id.json"
