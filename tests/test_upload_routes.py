from fastapi.testclient import TestClient

import database.db as db
from main import app


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
