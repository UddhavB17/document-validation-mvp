"""Bounded safety tests for reviewer decisions (PR26, codex/main-cleanup scope).

Covers: state gating of ACCEPT/OVERRIDE on pipeline completion (fail closed),
REQUEST_DOCS remaining available, authenticated reviewer in audit details,
latest-only undo with preceding-decision restore, and successive undo.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import database.db as db
import routes.decisions as routes_decisions
from database.db import init_db
from main import app
from services.auth.dependencies import CurrentUser

NOTE = "All manual checks are complete and verified by reviewer."


def _isolate(monkeypatch, tmp_path) -> None:
    # Mirror existing tests: point SQLite at a temp file and rely on the
    # shared truncate fixture on PostgreSQL. Never override DATABASE_URL
    # here: auth_headers may have bootstrapped PostgreSQL, and switching to
    # SQLite mid-test would leave an unseeded database.
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    init_db()


def _seed_application(
    *,
    app_status: str = "processing",
    with_high_finding: bool = True,
) -> int:
    init_db()
    with db.get_connection() as connection:
        created = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("LAP-SAFETY", "Safety Case", "LAP", "Delhi", app_status),
        ).fetchone()
        application_id = int(created["id"])
        if with_high_finding:
            connection.execute(
                """
                INSERT INTO validation_results (application_id, rule_id, severity, reason)
                VALUES (?, ?, ?, ?)
                """,
                (application_id, "MISSING_DOC_S1", "HIGH", "Application form missing"),
            )
    return application_id


def _seed_progress(
    application_id: int,
    *,
    status: str = "completed",
    updated_at: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_progress (
                application_id, stage, total_pages, processed_pages,
                percentage, status, started_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(application_id) DO UPDATE SET
                stage = excluded.stage,
                status = excluded.status,
                updated_at = excluded.updated_at,
                completed_at = excluded.completed_at
            """,
            (
                application_id,
                "completed" if status in {"completed", "completed_with_warnings"} else "processing_pages",
                2,
                2,
                100.0,
                status,
                now,
                updated_at or now,
                now if status in {"completed", "completed_with_warnings"} else None,
            ),
        )


def _seed_job(application_id: int, *, status: str = "completed") -> None:
    now = datetime.now(UTC).isoformat()
    with db.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_jobs (
                application_id, job_type, status, control_state,
                attempt, max_attempts, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                "pdf_pipeline",
                status,
                "completed" if status == "completed" else "running",
                1,
                3,
                now,
                now if status == "completed" else None,
            ),
        )


def _seed_completed(application_id: int, *, progress_status: str = "completed") -> None:
    _seed_progress(application_id, status=progress_status)
    _seed_job(application_id, status="completed")


def _post_decision(client, headers, application_id: int, decision: str):
    return client.post(
        "/decision",
        headers=headers,
        json={
            "application_id": application_id,
            "decision": decision,
            "reviewer_note": NOTE,
        },
    )


def _app_status(application_id: int) -> str | None:
    with db.get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
    return str(row["status"]) if row else None


def _decision_count(application_id: int) -> int:
    with db.get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM reviewer_decisions WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    return int(row["count"])


def _latest_audit_details(application_id: int, action: str) -> dict:
    with db.get_connection() as connection:
        row = connection.execute(
            """
            SELECT details FROM audit_log
            WHERE application_id = ? AND action = ?
            ORDER BY id DESC LIMIT 1
            """,
            (application_id, action),
        ).fetchone()
    assert row is not None, f"missing audit entry {action}"
    return json.loads(str(row["details"]))


def _bootstrap_admin_id() -> tuple[int, str]:
    with db.get_connection() as connection:
        row = connection.execute(
            "SELECT id, email FROM users WHERE email = ?",
            ("admin@example.com",),
        ).fetchone()
    assert row is not None
    return int(row["id"]), str(row["email"])


def test_accept_blocked_on_processing_without_evidence(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing", with_high_finding=False)
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "ACCEPT")

    assert response.status_code == 409
    assert _decision_count(application_id) == 0
    assert _app_status(application_id) == "processing"


def test_clean_business_state_does_not_imply_completion(tmp_path, monkeypatch, auth_headers) -> None:
    # No findings at all (pipeline-derived status would be CLEAN) but the
    # pipeline never completed: ACCEPT must still fail closed.
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing", with_high_finding=False)
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "ACCEPT")

    assert response.status_code == 409
    assert _app_status(application_id) == "processing"


@pytest.mark.parametrize(
    ("progress_status", "job_status"),
    [
        ("processing", "running"),
        ("processing", "completed"),
        ("completed", "running"),
        ("completed", "queued"),
        ("completed", "retrying"),
        ("completed", "failed"),
        ("paused", "paused"),
        ("cancelled", "cancelled"),
        ("failed", "failed"),
    ],
)
def test_accept_and_override_fail_closed_for_incomplete_states(
    tmp_path, monkeypatch, auth_headers, progress_status, job_status
) -> None:
    _isolate(monkeypatch, tmp_path)
    client = TestClient(app)
    for decision in ("ACCEPT", "OVERRIDE"):
        application_id = _seed_application(app_status="processing")
        _seed_progress(application_id, status=progress_status)
        _seed_job(application_id, status=job_status)

        response = _post_decision(client, auth_headers, application_id, decision)

        assert response.status_code == 409, (decision, progress_status, job_status)
        assert _decision_count(application_id) == 0
        assert _app_status(application_id) == "processing"


def test_accept_blocked_when_progress_stale(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    stale_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    _seed_progress(application_id, status="processing", updated_at=stale_at)
    _seed_job(application_id, status="running")
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "ACCEPT")

    assert response.status_code == 409
    assert _app_status(application_id) == "processing"


def test_accept_succeeds_when_pipeline_completed(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "ACCEPT")

    assert response.status_code == 200, response.text
    assert response.json()["new_status"] == "verified"
    assert _app_status(application_id) == "verified"


def test_accept_succeeds_with_completed_with_warnings(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id, progress_status="completed_with_warnings")
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "OVERRIDE")

    assert response.status_code == 200, response.text
    assert _app_status(application_id) == "verified_with_override"


def test_request_docs_allowed_without_completion(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "REQUEST_DOCS")

    assert response.status_code == 200, response.text
    assert response.json()["new_status"] == "incomplete"
    assert _app_status(application_id) == "incomplete"


def test_create_audit_contains_authenticated_reviewer(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    expected_id, expected_email = _bootstrap_admin_id()
    client = TestClient(app)

    response = _post_decision(client, auth_headers, application_id, "ACCEPT")
    assert response.status_code == 200

    details = _latest_audit_details(application_id, "reviewer_decision_made")
    assert details["user_id"] == expected_id
    assert details["user_email"] == expected_email
    assert details["decision"] == "ACCEPT"


def test_undo_audit_contains_authenticated_reviewer(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    expected_id, expected_email = _bootstrap_admin_id()
    client = TestClient(app)

    decision_id = _post_decision(client, auth_headers, application_id, "ACCEPT").json()["decision_id"]
    undo = client.post(f"/decision/{decision_id}/undo", headers=auth_headers)
    assert undo.status_code == 200

    details = _latest_audit_details(application_id, "decision_undone")
    assert details["user_id"] == expected_id
    assert details["user_email"] == expected_email
    assert details["decision_id"] == decision_id


def test_undo_older_decision_rejected_and_newer_status_untouched(
    tmp_path, monkeypatch, auth_headers
) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    client = TestClient(app)

    first_id = _post_decision(client, auth_headers, application_id, "REQUEST_DOCS").json()["decision_id"]
    second_id = _post_decision(client, auth_headers, application_id, "ACCEPT").json()["decision_id"]
    assert _app_status(application_id) == "verified"

    rejected = client.post(f"/decision/{first_id}/undo", headers=auth_headers)

    assert rejected.status_code == 409
    assert _app_status(application_id) == "verified"
    assert _decision_count(application_id) == 2
    # Newest decision is still intact.
    with db.get_connection() as connection:
        remaining = connection.execute(
            "SELECT id FROM reviewer_decisions WHERE application_id = ? ORDER BY id",
            (application_id,),
        ).fetchall()
    assert [int(row["id"]) for row in remaining] == [first_id, second_id]


def test_undo_restores_preceding_decision_status(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    client = TestClient(app)

    _post_decision(client, auth_headers, application_id, "REQUEST_DOCS")
    second_id = _post_decision(client, auth_headers, application_id, "ACCEPT").json()["decision_id"]

    undo = client.post(f"/decision/{second_id}/undo", headers=auth_headers)

    assert undo.status_code == 200
    # Preceding REQUEST_DOCS maps to incomplete, not pipeline-derived CRITICAL.
    assert undo.json()["restored_status"] == "incomplete"
    assert _app_status(application_id) == "incomplete"
    assert _decision_count(application_id) == 1


def test_successive_undo_falls_back_to_pipeline_status(tmp_path, monkeypatch, auth_headers) -> None:
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    client = TestClient(app)

    first_id = _post_decision(client, auth_headers, application_id, "REQUEST_DOCS").json()["decision_id"]
    second_id = _post_decision(client, auth_headers, application_id, "ACCEPT").json()["decision_id"]

    first_undo = client.post(f"/decision/{second_id}/undo", headers=auth_headers)
    assert first_undo.status_code == 200
    assert first_undo.json()["restored_status"] == "incomplete"

    second_undo = client.post(f"/decision/{first_id}/undo", headers=auth_headers)
    assert second_undo.status_code == 200
    # No preceding decision left: pipeline-derived status from HIGH finding.
    assert second_undo.json()["restored_status"] == "CRITICAL"
    assert _app_status(application_id) == "CRITICAL"
    assert _decision_count(application_id) == 0


def test_audit_failure_rolls_back_decision(tmp_path, monkeypatch, auth_headers) -> None:
    """A failed audit write must not leave a verified decision without a trail."""
    import contextlib

    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)

    real_get_connection = routes_decisions.get_connection

    @contextlib.contextmanager
    def failing_audit_connection():
        with real_get_connection() as connection:
            original_execute = connection.execute

            def execute(sql, params=()):
                if "audit_log" in sql:
                    raise RuntimeError("simulated audit write failure")
                return original_execute(sql, params)

            connection.execute = execute  # type: ignore[method-assign]
            yield connection

    monkeypatch.setattr(routes_decisions, "get_connection", failing_audit_connection)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/decision",
        headers=auth_headers,
        json={
            "application_id": application_id,
            "decision": "ACCEPT",
            "reviewer_note": NOTE,
        },
    )

    assert response.status_code == 500
    assert _decision_count(application_id) == 0
    assert _app_status(application_id) == "processing"


def test_concurrent_undo_same_decision_single_winner(tmp_path, monkeypatch, auth_headers) -> None:
    """Concurrent undos of one decision serialize: exactly one succeeds."""
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    client = TestClient(app)

    decision_id = _post_decision(client, auth_headers, application_id, "ACCEPT").json()["decision_id"]
    user_id, user_email = _bootstrap_admin_id()
    user = CurrentUser(
        id=user_id,
        email=user_email,
        display_name="admin",
        role="admin",
        is_active=True,
    )

    outcomes: list[tuple[str, object]] = []

    def attempt() -> None:
        try:
            result = routes_decisions.undo_decision(decision_id, user)
            outcomes.append(("ok", result["restored_status"]))
        except HTTPException as exc:
            outcomes.append(("error", exc.status_code))

    first = threading.Thread(target=attempt)
    second = threading.Thread(target=attempt)
    first.start()
    second.start()
    first.join(timeout=60)
    second.join(timeout=60)

    assert len(outcomes) == 2
    assert [kind for kind, _ in outcomes].count("ok") == 1
    error_codes = [code for kind, code in outcomes if kind == "error"]
    # SQLite reports the loser as missing (blocked until the winner commits);
    # PostgreSQL reports it as no-longer-latest. Either way it must not apply.
    assert error_codes == [404] or error_codes == [409]
    assert _decision_count(application_id) == 0
    assert _app_status(application_id) == "CRITICAL"


def test_undo_waits_for_sqlite_write_lock(tmp_path, monkeypatch, auth_headers) -> None:
    """Undo must block behind an open SQLite write txn, then apply exactly once."""
    if db.dialect() == "postgresql":
        pytest.skip("SQLite BEGIN IMMEDIATE serialization")
    _isolate(monkeypatch, tmp_path)
    application_id = _seed_application(app_status="processing")
    _seed_completed(application_id)
    client = TestClient(app)

    decision_id = _post_decision(client, auth_headers, application_id, "ACCEPT").json()["decision_id"]
    user_id, user_email = _bootstrap_admin_id()
    user = CurrentUser(
        id=user_id,
        email=user_email,
        display_name="admin",
        role="admin",
        is_active=True,
    )

    holder_ready = threading.Event()
    release = threading.Event()

    def hold_write_lock() -> None:
        with db.get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "SELECT id FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            holder_ready.set()
            assert release.wait(timeout=30)

    holder = threading.Thread(target=hold_write_lock)
    holder.start()
    assert holder_ready.wait(timeout=30)

    outcome: dict[str, tuple[str, object]] = {}

    def attempt() -> None:
        try:
            result = routes_decisions.undo_decision(decision_id, user)
            outcome["result"] = ("ok", result["restored_status"])
        except HTTPException as exc:
            outcome["result"] = ("error", exc.status_code)

    worker = threading.Thread(target=attempt)
    worker.start()
    time.sleep(1.0)
    # Still blocked: the writer holds RESERVED and the busy timeout exceeds this.
    assert "result" not in outcome
    release.set()
    worker.join(timeout=60)
    holder.join(timeout=60)

    assert outcome["result"][0] == "ok"
    assert _decision_count(application_id) == 0
    assert _app_status(application_id) == "CRITICAL"
