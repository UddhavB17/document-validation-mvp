"""Large finalization writes remain atomic and retain private evidence."""

import json

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event

import database.db as db
from services.exception_aggregator import save_aggregation
from services.pipeline.persistence import _load_page_checkpoints, _save_pages
from services.review.repository import load_application_review_bundle


@pytest.fixture
def application(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "bulk.db")
    db.init_db()
    with db.get_connection() as connection:
        row = connection.execute(
            "INSERT INTO applications (loan_id, applicant_name) VALUES (?, ?) RETURNING id",
            ("SYNTHETIC-BULK", "Synthetic Applicant"),
        ).fetchone()
    return int(row["id"])


def test_large_page_and_finding_batches_preserve_evidence(application):
    pages = [
        {
            "page_number": number,
            "page_type": "digital",
            "document_type": "Sanction Letter",
            "ocr_text": "synthetic OCR evidence",
            "extracted_fields": {
                "loan_amount": 100000 + number,
                "_field_provenance": {"loan_amount": {"field_confidence": 0.9}},
            },
        }
        for number in range(1, 892)
    ]
    inserts = []
    engine = db._get_engine()

    def count_inserts(_conn, _cursor, statement, _parameters, _context, executemany):
        if statement.lstrip().upper().startswith("INSERT"):
            inserts.append(executemany)

    event.listen(engine, "before_cursor_execute", count_inserts)
    try:
        _save_pages(application, pages)
        save_aggregation(
            application,
            [
                {
                    "rule_id": "SYNTHETIC_MISMATCH",
                    "severity": "MEDIUM",
                    "page_number": number,
                    "reason": "Synthetic regression finding",
                }
                for number in range(1, 892)
            ],
            "MEDIUM",
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_inserts)
    assert inserts == [True, True, True]
    saved = _load_page_checkpoints(application)
    assert len(saved) == 891
    assert saved[-1]["extracted_fields"] == pages[-1]["extracted_fields"]
    data, evidence = load_application_review_bundle(application)
    assert len(data["anomalies"]) == 891
    assert len(evidence) == 891
    assert evidence[0]["ocr_text"] == pages[0]["ocr_text"]
    assert evidence[0]["extracted_fields"]["_field_provenance"]
    public = json.dumps(jsonable_encoder(data))
    assert "synthetic OCR evidence" not in public
    assert "meta_json" not in public
    assert "_field_provenance" not in public


def test_failed_batch_rolls_back_without_losing_saved_pages(application, monkeypatch):
    _save_pages(application, [{"page_number": 1, "ocr_text": "retained checkpoint"}])
    original = db._Connection.executemany

    def fail_metadata(self, sql, params):
        if "INSERT INTO pages_meta" in sql:
            raise RuntimeError("simulated metadata write failure")
        return original(self, sql, params)

    monkeypatch.setattr(db._Connection, "executemany", fail_metadata)
    with pytest.raises(RuntimeError, match="simulated"):
        _save_pages(application, [{"page_number": 2, "ocr_text": "new page"}])
    saved = _load_page_checkpoints(application)
    assert [(p["page_number"], p["ocr_text"]) for p in saved] == [(1, "retained checkpoint")]


def test_review_bundle_reads_private_evidence_once_without_overriding_public_fields(application):
    _save_pages(application, [{
        "page_number": 1,
        "ocr_text": "synthetic evidence",
        "extracted_fields": {"loan_amount": 500000},
        "meta": {
            "_identity_extraction_reliable": False,
            "loan_amount": "must not override",
        },
    }])
    page_reads = []
    engine = db._get_engine()

    def count_page_reads(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM pages " in statement:
            page_reads.append(statement)

    event.listen(engine, "before_cursor_execute", count_page_reads)
    try:
        data, evidence = load_application_review_bundle(application)
    finally:
        event.remove(engine, "before_cursor_execute", count_page_reads)

    assert len(page_reads) == 1
    assert data["pages"][0]["extracted_fields"] == {"loan_amount": 500000}
    assert "ocr_text" not in data["pages"][0]
    assert "meta_json" not in data["pages"][0]
    assert evidence[0]["ocr_text"] == "synthetic evidence"
    assert evidence[0]["extracted_fields"] == {
        "loan_amount": 500000,
        "_identity_extraction_reliable": False,
    }
