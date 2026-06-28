from fastapi.testclient import TestClient

import database.db as db
from database.db import init_db
from main import app


def _seed_application() -> int:
    init_db()
    with db.get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("LAP-DECISION-1", "Ramesh Kumar", "LAP", "Delhi", "NEEDS_REVIEW"),
        )
    return cursor.lastrowid


def test_decision_requires_note(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    response = client.post(
        "/decision",
        json={"application_id": application_id, "decision": "ACCEPT", "reviewer_note": ""},
    )

    assert response.status_code == 400


def test_decision_updates_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    response = client.post(
        "/decision",
        json={
            "application_id": application_id,
            "decision": "ACCEPT",
            "reviewer_note": "All manual checks are complete.",
        },
    )

    assert response.status_code == 200
    with db.get_connection() as connection:
        application = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
    assert application["status"] == "verified"


def test_audit_log_written(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    client.post(
        "/decision",
        json={
            "application_id": application_id,
            "decision": "ACCEPT",
            "reviewer_note": "All manual checks are complete.",
        },
    )

    with db.get_connection() as connection:
        audit = connection.execute(
            "SELECT action FROM audit_log WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    assert audit["action"] == "reviewer_decision_made"
