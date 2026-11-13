"""Durable Ops ownership, review, request and TAT tracking."""

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.ops_workflow import (
    check_items,
    claim,
    create_document_request,
    reassign,
    record_decision,
    release,
    save_check,
    update_request_item,
    workflow_detail,
    worklist,
)


@pytest.fixture
def ops_case(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "ops-workflow.db")
    init_db()
    with get_connection() as connection:
        app_id = int(
            connection.execute(
                "INSERT INTO applications (loan_id, applicant_name, product_type, status) "
                "VALUES (?, ?, ?, ?) RETURNING id",
                ("LN-OPS-1", "Ops Applicant", "LAP", "needs_review"),
            ).fetchone()["id"]
        )
        users = []
        for email in ("ops-one@example.test", "ops-two@example.test"):
            users.append(
                int(
                    connection.execute(
                        "INSERT INTO users (email, display_name, role, is_active, created_at) "
                        "VALUES (?, ?, 'user', TRUE, ?) RETURNING id",
                        (email, email.split("@")[0], "2026-11-13T00:00:00+00:00"),
                    ).fetchone()["id"]
                )
            )
    return app_id, users


def test_case_claim_is_atomic_and_handoffs_are_audited(ops_case):
    app_id, (first, second) = ops_case
    assert worklist(None, first, "ready", 10, 0)["total"] == 1
    claim(app_id, first)
    assert worklist(None, first, "ready", 10, 0)["total"] == 0
    assert worklist(None, first, "mine", 10, 0)["total"] == 1
    with pytest.raises(PermissionError, match="already claimed"):
        claim(app_id, second)
    release(app_id, first, reason="Shift handoff")
    case = claim(app_id, second)
    assert case["owner_user_id"] == second
    events = workflow_detail(app_id, second)["events"]
    assert [event["action"] for event in events[:3]] == [
        "case_claimed",
        "case_released",
        "case_claimed",
    ]
    assert events[1]["reason"] == "Shift handoff"


def test_admin_reassignment_records_actor_and_reason(ops_case):
    app_id, (first, second) = ops_case
    claim(app_id, first)
    case = reassign(app_id, second, first, "Balance queue before shift change")
    assert case["owner_user_id"] == second
    event = workflow_detail(app_id, second)["events"][0]
    assert event["action"] == "case_reassigned"
    assert event["actor_user_id"] == first
    assert event["reason"] == "Balance queue before shift change"


def test_review_progress_is_persisted_and_stale_evidence_is_rejected(ops_case):
    app_id, (owner, _) = ops_case
    claim(app_id, owner)
    payload = {
        "top_findings": [
            {
                "code": "NAME_MISMATCH",
                "severity": "HIGH",
                "title": {"en": "Name mismatch"},
                "detail": {"en": "Check the source"},
                "pages": [2],
                "evidence": {"page": 2, "bbox": None, "text": "A. Example"},
            }
        ],
        "checklist": {"rows": []},
    }
    item = check_items(payload)[0]
    saved = save_check(
        app_id,
        owner,
        item["check_key"],
        item["evidence_revision"],
        "checked",
        "Compared to PAN",
        payload,
    )
    assert saved["status"] == "checked"
    changed = {**payload, "top_findings": [{**payload["top_findings"][0], "pages": [3]}]}
    with pytest.raises(RuntimeError, match="Evidence changed"):
        save_check(
            app_id, owner, item["check_key"], item["evidence_revision"], "checked", None, changed
        )


def test_partial_document_response_keeps_case_waiting_until_all_items_arrive(ops_case):
    app_id, (owner, _) = ops_case
    claim(app_id, owner)
    request = create_document_request(
        app_id, owner, "Please upload both items.", ["PAN copy", "Latest bank statement"], None
    )
    detail = workflow_detail(app_id, owner)
    request_items = [
        item
        for item in detail["document_request_items"]
        if item["request_id"] == request["request_id"]
    ]
    first, second = request_items
    update_request_item(app_id, request["request_id"], first["id"], "received", None, owner)
    assert workflow_detail(app_id, owner)["case"]["workflow_state"] == "waiting_documents"
    update_request_item(app_id, request["request_id"], second["id"], "outstanding", None, owner)
    assert workflow_detail(app_id, owner)["case"]["workflow_state"] == "waiting_documents"
    update_request_item(app_id, request["request_id"], second["id"], "received", None, owner)
    case = workflow_detail(app_id, owner)["case"]
    assert case["workflow_state"] == "ready"
    assert case["returned_at"] is not None
    assert detail["document_requests"][0]["status"] == "open"


def test_request_docs_decision_creates_ops_follow_up_record(ops_case):
    app_id, (owner, _) = ops_case
    from services.ops_workflow import utc_now

    with get_connection() as connection:
        record_decision(
            connection,
            app_id,
            owner,
            "REQUEST_DOCS",
            utc_now(),
            "Please provide the missing bank statement.",
        )
    detail = workflow_detail(app_id, owner)
    assert detail["case"]["workflow_state"] == "waiting_documents"
    assert detail["case"]["owner_user_id"] == owner
    assert detail["case"]["ready_at"] is None
    assert detail["document_requests"][0]["status"] == "open"
    assert detail["document_request_items"][0]["item"] == "Requested documents (see review note)"
