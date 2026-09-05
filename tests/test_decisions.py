from fastapi.testclient import TestClient

import database.db as db
from database.db import init_db
from main import app


def _seed_application() -> int:
    init_db()
    with db.get_connection() as connection:
        created = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("LAP-DECISION-1", "Ramesh Kumar", "LAP", "Delhi", "NEEDS_REVIEW"),
        ).fetchone()
        application_id = int(created["id"])
        connection.execute(
            """
            INSERT INTO validation_results (application_id, rule_id, severity, reason)
            VALUES (?, ?, ?, ?)
            """,
            (application_id, "MISSING_DOC_S1", "HIGH", "Application form missing"),
        )
    return application_id


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
    payload = response.json()
    assert payload["decision_id"] is not None
    with db.get_connection() as connection:
        application = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
    assert application["status"] == "verified"


def test_undo_decision_within_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id = _seed_application()
    client = TestClient(app)

    create_response = client.post(
        "/decision",
        json={
            "application_id": application_id,
            "decision": "ACCEPT",
            "reviewer_note": "All manual checks are complete.",
        },
    )
    decision_id = create_response.json()["decision_id"]

    undo_response = client.post(f"/decision/{decision_id}/undo")
    assert undo_response.status_code == 200
    assert undo_response.json()["restored_status"] == "CRITICAL"

    with db.get_connection() as connection:
        application = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        remaining = connection.execute(
            "SELECT COUNT(*) AS count FROM reviewer_decisions WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    assert application["status"] == "CRITICAL"
    assert remaining["count"] == 0


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
