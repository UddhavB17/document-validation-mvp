from pathlib import Path
import os

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.pipeline import run_pipeline
from services.pipeline import _build_page_records, _build_unsupported_page_records
from services.ocr_router import OCRRouter


@pytest.fixture(autouse=True)
def _default_to_local_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "local")
    import services.config as config_mod
    import services.ocr_router as ocr_router_mod

    real_get_setting = config_mod.get_setting

    def _get_setting(key: str, default=None):
        if key == "ocr.provider":
            return os.getenv("OCR_PROVIDER") or default or "local"
        return real_get_setting(key, default)

    monkeypatch.setattr(config_mod, "get_setting", _get_setting)
    monkeypatch.setattr(ocr_router_mod, "get_setting", _get_setting)


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


def _create_blank_scanned_pdf(path: Path, pages: int) -> None:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()


@pytest.mark.parametrize(
    "source_documents",
    [
        None,
        [{
            "source_document_id": "zip-doc-1",
            "original_filename": "Applicant/KYC/page.png",
            "internal_page_start": 1,
            "internal_page_end": 1,
        }],
    ],
    ids=["pdf", "normalized-zip"],
)
def test_google_provider_uses_one_api_ocr_and_no_local_ocr(
    monkeypatch: pytest.MonkeyPatch,
    source_documents,
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "google_vision")
    google_calls: list[str] = []
    local_calls: list[str] = []
    router = OCRRouter(
        fast_processor=lambda path: local_calls.append(str(path)) or {},
        structured_processor=lambda path: local_calls.append(str(path)) or {},
        google_vision_processor=lambda path: google_calls.append(str(path)) or {
            "ocr_text": "Loan Application Form\nApplicant Name: Ramesh Kumar\nLoan Amount: 500000",
            "confidence": 0.94,
            "char_count": 79,
            "word_count": 10,
            "line_count": 3,
            "image_width": 1000,
            "image_height": 1400,
            "text_density": 56.4,
        },
        event_recorder=lambda **_event: None,
    )
    monkeypatch.setattr("services.pipeline.get_ocr_router", lambda: router)
    monkeypatch.setattr(
        "services.pipeline.classify_page_text",
        lambda *_args, **_kwargs: (
            {"document_type": "Application Form", "confidence": 0.95},
            {"source": "rules", "rule_document_type": "Application Form", "rule_confidence": 0.95},
        ),
    )
    monkeypatch.setattr("services.pipeline.classify_with_structured_llm", lambda **_kwargs: None)

    pages = _build_page_records(
        [{"page_number": 1, "page_type": "scanned", "image_path": "page.png"}],
        {},
        application_id=None,
        source_documents=source_documents,
    )

    assert google_calls == ["page.png"]
    assert local_calls == []
    assert pages[0]["ocr_route"] == "google_vision"


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

    assert result["pipeline_status"] == "partial_failed"
    assert result["partial_failure_count"] == 1
    assert "\"_processing_error\": \"boom\"" in page["extracted_fields"]
    assert progress["stage"] == "completed"
    assert progress["status"] == "partial_failed"
    assert progress["processed_pages"] == progress["total_pages"] == 1


def test_run_pipeline_marks_partial_scan_and_preserves_skipped_readability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "dmef.db"
    pdf_path = tmp_path / "large_scanned.pdf"
    output_dir = tmp_path / "processed"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    monkeypatch.setenv("DMEF_FULL_SCAN_OCR", "false")
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "2")
    _create_blank_scanned_pdf(pdf_path, pages=5)

    monkeypatch.setattr(
        "services.pipeline.run_ocr_on_page",
        lambda *_args, **_kwargs: {
            "ocr_text": "Permanent Account Number ABCDE1234F",
            "is_readable": True,
            "confidence": 0.95,
        },
    )

    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            """,
            ("LAP-PARTIAL-001", "Ramesh Kumar", "LAP", "Delhi"),
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
            (application_id, str(pdf_path), "large_scanned.pdf", 1.0, 0, 0, 0),
        )

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={"loan_id": "LAP-PARTIAL-001", "applicant_name": "Ramesh Kumar"},
        product_type="LAP",
        generate_llm_summary=False,
    )

    assert any(anomaly["rule_id"] == "OCR_BUDGET_PARTIAL_SCAN" for anomaly in result["anomalies"])
    assert "OCR Skipped" not in result["documents_found"]

    with get_connection() as connection:
        skipped_rows = connection.execute(
            """
            SELECT is_readable, document_type
            FROM pages
            WHERE application_id = ? AND document_type = 'OCR Skipped'
            """,
            (application_id,),
        ).fetchall()

    assert len(skipped_rows) == 3
    assert all(row["is_readable"] is None for row in skipped_rows)


def test_run_pipeline_records_ocr_error_as_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "dmef.db"
    pdf_path = tmp_path / "ocr_error.pdf"
    output_dir = tmp_path / "processed"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    monkeypatch.setenv("DMEF_MAX_SCANNED_OCR_PAGES", "1")
    _create_blank_scanned_pdf(pdf_path, pages=1)

    monkeypatch.setattr(
        "services.pipeline.run_ocr_on_page",
        lambda *_args, **_kwargs: {
            "ocr_text": "",
            "is_readable": False,
            "confidence": 0.0,
            "error": "OCR exceeded hard timeout of 1s",
        },
    )

    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES (?, ?, ?, ?)
            """,
            ("LAP-OCR-ERR-001", "Ramesh Kumar", "LAP", "Delhi"),
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
            (application_id, str(pdf_path), "ocr_error.pdf", 1.0, 0, 0, 0),
        )

    result = run_pipeline(
        pdf_path,
        application_id,
        output_dir=output_dir,
        system_data={"loan_id": "LAP-OCR-ERR-001", "applicant_name": "Ramesh Kumar"},
        product_type="LAP",
        generate_llm_summary=False,
    )

    assert result["pipeline_status"] == "partial_failed"
    assert result["partial_failure_count"] == 1
    assert any(anomaly["rule_id"] == "PAGE_PROCESSING_ERROR" for anomaly in result["anomalies"])

    with get_connection() as connection:
        page = connection.execute(
            "SELECT extracted_fields FROM pages WHERE application_id = ?",
            (application_id,),
        ).fetchone()

    assert "OCR exceeded hard timeout" in page["extracted_fields"]


def test_build_page_records_routes_photo_without_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.pipeline.run_ocr_on_page",
        lambda *_args, **_kwargs: {
            "ocr_text": "",
            "is_readable": False,
            "confidence": 0.10,
            "char_count": 0,
            "word_count": 0,
            "line_count": 0,
            "image_width": 1600,
            "image_height": 1200,
            "text_density": 0.0,
        },
    )
    monkeypatch.setattr(
        "services.pipeline.classify_page_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("classification should be skipped")),
    )

    pages = _build_page_records(
        [{"page_number": 1, "page_type": "scanned", "image_path": "property_photo.png"}],
        {},
        application_id=None,
    )

    assert pages[0]["document_type"] == "Property Image"
    assert pages[0]["extracted_fields"]["content_category"] == "property_image"


def test_build_page_records_flags_low_confidence_handwritten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.pipeline.run_ocr_on_page",
        lambda *_args, **_kwargs: {
            "ocr_text": "rent paid 4500",
            "is_readable": True,
            "confidence": 0.45,
            "char_count": 14,
            "word_count": 3,
            "line_count": 1,
            "image_width": 1000,
            "image_height": 1400,
            "text_density": 10.0,
        },
    )

    pages = _build_page_records(
        [{"page_number": 1, "page_type": "scanned", "image_path": "bill.png"}],
        {},
        application_id=None,
    )

    assert pages[0]["document_type"] == "Unknown"
    assert pages[0]["extracted_fields"]["review_flag"] == "low_confidence_needs_review"


def test_build_page_records_marks_only_starting_json_as_db_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.pipeline.classify_with_structured_llm",
        lambda **_kwargs: None,
    )

    pages = _build_page_records(
        [{"page_number": 1, "page_type": "digital", "image_path": None}],
        {1: '{"application_id": 31, "applicant_name": "Radha Bai"}'},
        application_id=None,
    )

    assert pages[0]["document_type"] == "DB Data"
    assert pages[0]["extracted_fields"]["db_data_json"]["application_id"] == 31


def test_build_page_records_does_not_mark_normal_digital_document_as_db_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.pipeline.classify_page_text",
        lambda *_args, **_kwargs: (
            {"document_type": "Application Form", "confidence": 0.95},
            {"source": "test_classifier"},
        ),
    )
    monkeypatch.setattr(
        "services.pipeline.extract_fields",
        lambda document_type, _text: {"applicant_name": "Ramesh Kumar"} if document_type == "Application Form" else {},
    )
    monkeypatch.setattr(
        "services.pipeline.classify_with_structured_llm",
        lambda **_kwargs: None,
    )

    pages = _build_page_records(
        [{"page_number": 1, "page_type": "digital", "image_path": None}],
        {
            1: (
                "Loan Application Form\n"
                "Applicant Name: Ramesh Kumar\n"
                "Loan Amount: Rs. 500000\n"
                "This is selectable text from a normal document, not JSON."
            )
        },
        application_id=None,
    )

    assert pages[0]["document_type"] == "Application Form"
    assert pages[0]["detection_method"] == "detected"
    assert pages[0]["extracted_fields"]["applicant_name"] == "Ramesh Kumar"
    assert "db_data_json" not in pages[0]["extracted_fields"]


def test_build_page_records_does_not_mark_later_json_page_as_db_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.pipeline.classify_page_text",
        lambda *_args, **_kwargs: (
            {"document_type": "Unknown", "confidence": 0.0},
            {"source": "test_classifier"},
        ),
    )
    monkeypatch.setattr("services.pipeline.extract_fields", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "services.pipeline.classify_with_structured_llm",
        lambda **_kwargs: None,
    )

    pages = _build_page_records(
        [{"page_number": 4, "page_type": "digital", "image_path": None}],
        {4: '{"application_id": 31, "applicant_name": "Late JSON"}'},
        application_id=None,
    )

    assert pages[0]["document_type"] == "Unknown"
    assert pages[0]["detection_method"] != "db_data"


def test_unsupported_page_records_do_not_mark_normal_digital_text_as_db_data() -> None:
    pages = _build_unsupported_page_records(
        [{"page_number": 1, "page_type": "digital", "image_path": None}],
        {1: "Normal selectable digital document text without a JSON object."},
    )

    assert pages[0]["document_type"] == "Unknown"
    assert pages[0]["detection_method"] == "unknown"


def test_filename_identity_type_contradicted_by_email_thread() -> None:
    from services.pipeline import _filename_type_contradicted_by_text

    email_text = (
        "Gmail - Aadhaar update request\n"
        "From: branch.ops@lender.example.com\nTo: support@lender.example.com\n"
        "Please find attached the customer's updated documents for approval. "
    ) + "Further correspondence follows. " * 20

    assert _filename_type_contradicted_by_text("Driving License", email_text) is True
    assert _filename_type_contradicted_by_text("Aadhaar Card", email_text) is True


def test_filename_identity_type_not_contradicted_by_card_ocr() -> None:
    from services.pipeline import _filename_type_contradicted_by_text

    # Short/noisy OCR from a card photo cannot contradict the filename.
    short_ocr = "RJ-14 20110012345 DOB 01-01-1980"
    assert _filename_type_contradicted_by_text("Driving License", short_ocr) is False

    # Long text that carries the document's own anchors is consistent.
    dl_text = (
        "Driving Licence\nTransport Department, Government of Rajasthan\n"
        "Licence No RJ-14 20110012345\nValid till 2030\n"
    ) + "Vehicle classes: LMV MCWG. " * 20
    assert _filename_type_contradicted_by_text("Driving License", dl_text) is False


def test_filename_contradiction_only_applies_to_identity_types() -> None:
    from services.pipeline import _filename_type_contradicted_by_text

    long_unrelated = "Some property valuation narrative. " * 30
    assert _filename_type_contradicted_by_text("Property Image", long_unrelated) is False


def test_gps_overlay_photo_is_property_image_evidence() -> None:
    from services.pipeline import _image_evidence_type_from_text

    text = "GPS Map Camera\nJodhpur, Rajasthan, India\nLat 26.28 Long 73.02\n27/07/2026 07:14 AM"
    assert _image_evidence_type_from_text(text) == "Property Image"
