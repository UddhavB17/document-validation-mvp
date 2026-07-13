from pathlib import Path

import database.db as db
from database.db import get_connection, init_db
from services.mapped_verification import run_mapped_verification
from services.reviewer_summary import build_reviewer_summary
from services.reviewer_summary_store import load_reviewer_summary


class _FakeDocument:
    def __init__(self, pages: int) -> None:
        self.pages = [object() for _ in range(pages)]

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int):
        return self.pages[index]

    def close(self) -> None:
        return None


def _application() -> int:
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch)
            VALUES ('MAP-001', 'Ramesh Kumar', 'LAP', 'Delhi')
            """
        )
        return int(cursor.lastrowid)


def test_mapped_verification_uses_mapping_and_flags_pan_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "mapped.db")
    monkeypatch.setattr("services.mapped_verification.open_pdf", lambda _path: _FakeDocument(20))
    monkeypatch.setattr(
        "services.mapped_verification.convert_page_to_image",
        lambda _page, output: str(output),
    )
    monkeypatch.setattr(
        "services.mapped_verification.run_ocr_on_page",
        lambda path: {
            "ocr_text": (
                "Name: Ramesh Kumar\nPermanent Account Number ZZZZZ9999Z"
                if "page_14" in path
                else "Name: Ramesh Kumar\n1234 5678 9012"
            ),
            "is_readable": True,
            "confidence": 0.96,
        },
    )
    application_id = _application()

    result = run_mapped_verification(
        tmp_path / "loan.pdf",
        application_id,
        {
            "loan_id": "MAP-001",
            "reference_data": {
                "aadhaar_number": "123456789012",
                "pan_number": "ABCDE1234F",
            },
            "documents": [
                {
                    "document_type": "Aadhaar",
                    "pages": [12],
                    "expected_fields": {"aadhaar_number": "123456789012"},
                },
                {
                    "document_type": "PAN",
                    "pages": [14],
                    "expected_fields": {"pan_number": "ABCDE1234F"},
                },
            ],
        },
        output_dir=tmp_path / "processed",
    )

    assert result["mapped_pages_processed"] == 2
    assert result["checked_fields"] == 2
    assert result["matched_fields"] == 1
    assert [item["rule_id"] for item in result["anomalies"]] == ["PAN_NUMBER_MISMATCH"]
    assert result["reviewer_summary"]["overall_status"] == "HIGH_RISK"
    assert result["reviewer_summary"]["pages_to_review"] == [14]
    assert result["reviewer_summary"]["review_items"][0]["expected_masked"] == "******234F"
    assert load_reviewer_summary(application_id) == result["reviewer_summary"]


def test_reviewer_summary_escalates_many_high_risk_anomalies() -> None:
    anomalies = [
        {
            "rule_id": f"RULE_{number}",
            "severity": "HIGH",
            "page_number": number,
            "reason": "Critical difference",
        }
        for number in (2, 4, 6)
    ]
    summary = build_reviewer_summary(
        total_pages=30,
        anomalies=anomalies,
        checked_fields=5,
        matched_fields=2,
    )

    assert summary["overall_status"] == "FULL_MANUAL_REVIEW"
    assert summary["pages_to_review"] == [2, 4, 6]
    assert "Completely check" in summary["recommendation"]


def test_reviewer_summary_is_clean_without_anomalies() -> None:
    summary = build_reviewer_summary(
        total_pages=10,
        anomalies=[],
        checked_fields=4,
        matched_fields=4,
    )
    assert summary["overall_status"] == "CLEAN"
    assert summary["pages_to_review"] == []
