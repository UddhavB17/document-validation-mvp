"""Storage/payload budget tests for the ws-a data diet (contracts §8).

Runs the real pipeline over a small fixture PDF and asserts the persisted
rows and review payloads stay within budget: no ``native`` blobs, business
keys only in ``extracted_fields``, no OCR text in summary payloads, a tiny
``/status`` response, and no durable page images outside the job work dir.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import database.db as db
from database.db import get_connection, init_db
from services.pipeline import run_pipeline


@pytest.fixture(autouse=True)
def _default_to_local_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "local")
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("DMEF_LOCAL_OCR_TEST_MODE", "true")
    import services.config as config_mod
    import services.ocr_router as ocr_router_mod

    real_get_setting = config_mod.get_setting

    def _get_setting(key: str, default=None):
        if key == "ocr.provider":
            return "local"
        return real_get_setting(key, default)

    monkeypatch.setattr(config_mod, "get_setting", _get_setting)
    monkeypatch.setattr(ocr_router_mod, "get_setting", _get_setting)


def _create_mixed_pdf(path: Path) -> None:
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
        "PAN: ABCDE1234F\n"
        "This digital page contains enough selectable text for processing.",
    )
    doc.new_page()  # image-only scanned page
    doc.save(path)
    doc.close()


def _run_fixture_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    db_path = tmp_path / "dmef.db"
    pdf_path = tmp_path / "application.pdf"
    output_dir = tmp_path / "processed"
    job_work_dir = tmp_path / "jobs"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(job_work_dir))
    monkeypatch.setenv("PAGE_OUTPUT_DIR", str(tmp_path / "pagedir"))
    _create_mixed_pdf(pdf_path)
    monkeypatch.setattr(
        "services.pipeline.page_processing.run_ocr_on_page",
        lambda *_args, **_kwargs: {
            "ocr_text": "Permanent Account Number ABCDE1234F",
            "is_readable": True,
            "confidence": 0.95,
        },
    )
    monkeypatch.setattr(
        "services.pipeline.page_processing.classify_with_structured_llm",
        lambda **_kwargs: None,
    )

    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            ("LAP-DIET-001", "Ramesh Kumar", "LAP", "Delhi"),
        ).fetchone()
        application_id = int(row["id"])
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

    with get_connection() as connection:
        job_row = connection.execute(
            """
            INSERT INTO pipeline_jobs (application_id, job_type, status, created_at)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (application_id, "pdf_pipeline", "queued", "2026-09-04 12:00:00"),
        ).fetchone()
        job_id = int(job_row["id"])

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={"loan_id": "LAP-DIET-001", "applicant_name": "Ramesh Kumar"},
        product_type="LAP",
        generate_llm_summary=False,
        job_id=job_id,
    )
    assert result["application_id"] == application_id
    return application_id


def test_pages_rows_have_no_blobs_and_fit_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application_id = _run_fixture_pipeline(tmp_path, monkeypatch)

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM pages WHERE application_id = ? ORDER BY page_number",
            (application_id,),
        ).fetchall()
    assert rows, "fixture run should persist page rows"

    columns = set(rows[0].keys())
    assert "structured_content" not in columns
    assert "image_path" not in columns

    serialized = [json.dumps(dict(row), ensure_ascii=False) for row in rows]
    assert all('"native"' not in payload for payload in serialized)
    average_bytes = sum(len(payload) for payload in serialized) / len(serialized)
    assert average_bytes <= 4 * 1024, f"average pages row is {average_bytes:.0f} bytes"

    with get_connection() as connection:
        field_rows = connection.execute(
            "SELECT extracted_fields FROM pages WHERE application_id = ?",
            (application_id,),
        ).fetchall()
        meta_rows = connection.execute(
            "SELECT meta_json FROM pages_meta WHERE application_id = ?",
            (application_id,),
        ).fetchall()
    assert len(meta_rows) == len(field_rows)
    for row in field_rows:
        fields = json.loads(row["extracted_fields"])
        assert isinstance(fields, dict)
        assert all(not str(key).startswith("_") for key in fields)


def test_page_events_carry_no_field_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application_id = _run_fixture_pipeline(tmp_path, monkeypatch)

    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM pipeline_page_events WHERE application_id = ?",
            (application_id,),
        ).fetchall()
    assert rows, "fixture run should record page events"
    assert "extracted_fields" not in set(rows[0].keys())
    assert all('"native"' not in json.dumps(dict(row)) for row in rows)


def test_review_payloads_respect_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    application_id = _run_fixture_pipeline(tmp_path, monkeypatch)
    from main import app

    client = TestClient(app)

    review_response = client.get(
        f"/review/applications/{application_id}", headers=auth_headers
    )
    assert review_response.status_code == 200
    assert '"ocr_text"' not in review_response.text
    assert '"structured_content"' not in review_response.text

    status_response = client.get(
        f"/review/applications/{application_id}/status", headers=auth_headers
    )
    assert status_response.status_code == 200
    assert len(status_response.content) <= 5 * 1024
    payload = status_response.json()
    assert payload["application_id"] == application_id
    assert set(payload["progress"].keys()) == {
        "stage",
        "percentage",
        "completed_pages",
        "total_pages",
    }

    text_response = client.get(
        f"/review/applications/{application_id}/pages/1/text", headers=auth_headers
    )
    assert text_response.status_code == 200
    assert set(text_response.json().keys()) == {
        "page_number",
        "ocr_text",
        "ocr_confidence",
        "document_type",
    }


def test_no_png_written_outside_job_work_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Observe only files produced by this run, never a developer's uploads.
    checklist_source = Path("data/checklist.json").resolve()
    (tmp_path / "data").mkdir()
    shutil.copyfile(checklist_source, tmp_path / "data/checklist.json")
    monkeypatch.chdir(tmp_path)
    _run_fixture_pipeline(tmp_path, monkeypatch)

    repo_data = Path("data")
    page_output = Path(os.environ.get("PAGE_OUTPUT_DIR", "data/processed"))
    png_files: list[str] = []
    for root in (repo_data, page_output):
        if root.is_dir():
            png_files.extend(
                str(path)
                for path in root.rglob("*.png")
                if "node_modules" not in path.parts
            )
    assert png_files == []
