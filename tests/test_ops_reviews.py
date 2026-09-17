"""Persisted individual exception review workflow."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from database.db import get_connection, init_db
from main import app
from services.exception_aggregator import save_aggregation


def _seed_review_case() -> tuple[int, int]:
    init_db()
    with get_connection() as connection:
        app_row = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, status)
            VALUES (?, ?, ?, ?) RETURNING id
            """,
            ("LN-REVIEW-1", "Review Applicant", "LAP", "needs_review"),
        ).fetchone()
        application_id = int(app_row["id"])
        finding_row = connection.execute(
            """
            INSERT INTO validation_results (
                application_id, rule_id, s_no, severity, document_type,
                expected_value, found_value, page_number, reason, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (
                application_id,
                "PAN_NUMBER_MISMATCH",
                2,
                "HIGH",
                "PAN Card",
                "EXPECTED",
                "FOUND",
                3,
                "Names differ",
                json.dumps({"page": 3, "bbox": [0.1, 0.2, 0.4, 0.5], "text": "FOUND"}),
            ),
        ).fetchone()
        return application_id, int(finding_row["id"])


def test_review_item_persists_correct_reopen_and_audit(auth_headers) -> None:
    application_id, validation_result_id = _seed_review_case()
    client = TestClient(app)

    listed = client.get(f"/ops/applications/{application_id}/review-items", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    item = listed.json()["items"][0]
    assert item["status"] == "pending"
    assert item["item_id"].startswith("ri_")
    assert item["validation_result_id"] == validation_result_id
    assert listed.json()["counts"] == {"total": 1, "pending": 1, "reviewed": 0}

    saved = client.put(
        f"/ops/applications/{application_id}/review-items/{item['item_id']}",
        headers=auth_headers,
        json={"expected_revision": item["revision"], "disposition": "correct", "note": "Checked page 3."},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "reviewed"
    assert saved.json()["note"] == "Checked page 3."
    assert saved.json()["reviewer"]["name"] == "Administrator"

    reviewed = client.get(f"/ops/applications/{application_id}/review-items", headers=auth_headers).json()
    assert reviewed["counts"] == {"total": 1, "pending": 0, "reviewed": 1}

    reopened = client.put(
        f"/ops/applications/{application_id}/review-items/{item['item_id']}",
        headers=auth_headers,
        json={"expected_revision": item["revision"], "disposition": "reopen", "note": "Needs another look."},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "pending"
    assert reopened.json()["disposition"] == "reopen"

    with get_connection() as connection:
        source = connection.execute(
            "SELECT status FROM validation_results WHERE id = ?", (validation_result_id,)
        ).fetchone()
        audit = connection.execute(
            "SELECT action FROM audit_log WHERE application_id = ? ORDER BY id",
            (application_id,),
        ).fetchall()
    assert source["status"] == "open"
    assert [row["action"] for row in audit] == [
        "ops_exception_review_updated",
        "ops_exception_review_updated",
    ]


def test_review_item_rejects_wrong_application_and_stale_revision(auth_headers) -> None:
    application_id, validation_result_id = _seed_review_case()
    with get_connection() as connection:
        other = connection.execute(
            "INSERT INTO applications (loan_id, applicant_name, status) VALUES (?, ?, ?) RETURNING id",
            ("LN-OTHER", "Other Applicant", "needs_review"),
        ).fetchone()["id"]
    client = TestClient(app)
    item = client.get(f"/ops/applications/{application_id}/review-items", headers=auth_headers).json()["items"][0]

    wrong_owner = client.put(
        f"/ops/applications/{int(other)}/review-items/{item['item_id']}",
        headers=auth_headers,
        json={"expected_revision": item["revision"], "disposition": "correct"},
    )
    assert wrong_owner.status_code == 404

    with get_connection() as connection:
        connection.execute(
            "UPDATE validation_results SET reason = ? WHERE id = ?",
            ("Changed after reload", validation_result_id),
        )
    stale = client.put(
        f"/ops/applications/{application_id}/review-items/{item['item_id']}",
        headers=auth_headers,
        json={"expected_revision": item["revision"], "disposition": "correct"},
    )
    assert stale.status_code == 409


@pytest.mark.parametrize("reviewed", [False, True], ids=["pending", "reviewed"])
@pytest.mark.parametrize("replace_finding", [False, True], ids=["clean", "replacement"])
def test_reprocessing_clears_review_state_and_preserves_audit(
    auth_headers, reviewed, replace_finding,
) -> None:
    application_id, validation_result_id = _seed_review_case()
    other_application_id, _ = _seed_review_case()
    client = TestClient(app)
    path = f"/ops/applications/{application_id}/review-items"
    other_path = f"/ops/applications/{other_application_id}/review-items"
    item = client.get(path, headers=auth_headers).json()["items"][0]
    other_before = client.get(other_path, headers=auth_headers).json()
    if reviewed:
        saved = client.put(
            f"{path}/{item['item_id']}", headers=auth_headers,
            json={
                "expected_revision": item["revision"],
                "disposition": "correct",
                "note": "Confirmed against the original page.",
            },
        )
        assert saved.status_code == 200, saved.text

    with get_connection() as connection:
        source = dict(connection.execute(
            "SELECT * FROM validation_results WHERE id = ?", (validation_result_id,),
        ).fetchone())
        audit_before = [dict(row) for row in connection.execute(
            "SELECT * FROM audit_log WHERE application_id = ? ORDER BY id", (application_id,),
        ).fetchall()]

    # Even an identical replacement finding must require fresh human review.
    save_aggregation(application_id, [source] if replace_finding else [], "MEDIUM" if replace_finding else "CLEAN")

    with get_connection() as connection:
        assert connection.execute(
            "SELECT item_id FROM ops_review_items WHERE application_id = ?", (application_id,),
        ).fetchall() == []
        audit_after = [dict(row) for row in connection.execute(
            "SELECT * FROM audit_log WHERE application_id = ? ORDER BY id", (application_id,),
        ).fetchall()]
    assert audit_after == audit_before
    refreshed = client.get(path, headers=auth_headers)
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["counts"] == {
        "total": int(replace_finding), "pending": int(replace_finding), "reviewed": 0,
    }
    if replace_finding:
        replacement = refreshed.json()["items"][0]
        assert replacement["item_id"] != item["item_id"]
        assert replacement["reviewer"] is None
        assert replacement["reviewed_at"] is None
        assert replacement["note"] is None
        assert replacement["disposition"] is None
    stale = client.put(
        f"{path}/{item['item_id']}", headers=auth_headers,
        json={"expected_revision": item["revision"], "disposition": "correct"},
    )
    assert stale.status_code == 404
    assert client.get(other_path, headers=auth_headers).json() == other_before


def test_failed_reprocessing_restores_findings_and_saved_review(auth_headers) -> None:
    application_id, validation_result_id = _seed_review_case()
    client = TestClient(app)
    path = f"/ops/applications/{application_id}/review-items"
    item = client.get(path, headers=auth_headers).json()["items"][0]
    saved = client.put(
        f"{path}/{item['item_id']}", headers=auth_headers,
        json={"expected_revision": item["revision"], "disposition": "correct", "note": "Keep this review."},
    )
    assert saved.status_code == 200, saved.text
    before = client.get(path, headers=auth_headers).json()
    with get_connection() as connection:
        source_before = dict(connection.execute(
            "SELECT * FROM validation_results WHERE id = ?", (validation_result_id,),
        ).fetchone())
        audit_before = [dict(row) for row in connection.execute(
            "SELECT * FROM audit_log WHERE application_id = ? ORDER BY id", (application_id,),
        ).fetchall()]

    with pytest.raises(TypeError, match="not JSON serializable"):
        save_aggregation(application_id, [{"evidence_json": {"invalid": object()}}], "CLEAN")

    assert client.get(path, headers=auth_headers).json() == before
    with get_connection() as connection:
        assert dict(connection.execute(
            "SELECT * FROM validation_results WHERE id = ?", (validation_result_id,),
        ).fetchone()) == source_before
        assert connection.execute(
            "SELECT status FROM applications WHERE id = ?", (application_id,),
        ).fetchone()["status"] == "needs_review"
        assert [dict(row) for row in connection.execute(
            "SELECT * FROM audit_log WHERE application_id = ? ORDER BY id", (application_id,),
        ).fetchall()] == audit_before
