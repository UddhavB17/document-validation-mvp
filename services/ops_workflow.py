"""Ops ownership, audit history, review progress, and document follow-up."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import UTC, datetime
from typing import Any

from database.db import dialect, get_connection


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _begin_write(connection: Any) -> None:
    if dialect() == "sqlite":
        connection.execute("BEGIN IMMEDIATE")


def _for_update() -> str:
    return " FOR UPDATE" if dialect() == "postgresql" else ""


def _event(
    connection: Any,
    application_id: int,
    actor_id: int | None,
    action: str,
    now: str,
    *,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        "INSERT INTO ops_case_events (application_id, actor_user_id, action, reason, details_json, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (application_id, actor_id, action, reason, json.dumps(details or {}), now),
    )


def ensure_case(application_id: int, actor_id: int | None = None) -> dict[str, Any]:
    """Create a prospective TAT record on first eligible Ops observation."""
    now = utc_now()
    with get_connection() as connection:
        app = connection.execute(
            "SELECT id, status FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if app is None:
            raise KeyError(application_id)
        app_status = str(app["status"] or "").lower()
        initial_state = (
            "completed"
            if app_status in {"verified", "verified_with_override", "accepted"}
            else "waiting_documents"
            if app_status == "incomplete"
            else "ready"
        )
        connection.execute(
            "INSERT INTO ops_cases (application_id, workflow_state, ready_at, updated_at, waiting_reason) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (application_id) DO NOTHING",
            (
                application_id,
                initial_state,
                now if initial_state == "ready" else None,
                now,
                "Documents requested" if initial_state == "waiting_documents" else None,
            ),
        )
        created = connection.execute(
            "SELECT application_id, owner_user_id, workflow_state, waiting_reason, ready_at, returned_at, "
            "first_started_at, first_outcome_at, completed_at, updated_at "
            "FROM ops_cases WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        if created is None:
            raise RuntimeError("Ops workflow state could not be created")
        return dict(created)


def workflow_detail(application_id: int, user_id: int) -> dict[str, Any]:
    ensure_case(application_id, user_id)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT c.application_id, c.owner_user_id, u.display_name AS owner_name, "
            "c.workflow_state, c.waiting_reason, c.ready_at, c.returned_at, c.first_started_at, "
            "c.first_outcome_at, c.completed_at, c.updated_at FROM ops_cases c "
            "LEFT JOIN users u ON u.id = c.owner_user_id WHERE c.application_id = ?",
            (application_id,),
        ).fetchone()
        events = connection.execute(
            "SELECT e.id, e.actor_user_id, u.display_name AS actor_name, e.action, e.reason, "
            "e.details_json, e.occurred_at FROM ops_case_events e LEFT JOIN users u "
            "ON u.id = e.actor_user_id WHERE e.application_id = ? ORDER BY e.id DESC LIMIT 100",
            (application_id,),
        ).fetchall()
        requests = connection.execute(
            "SELECT id, message, status, follow_up_at, opened_at, resolved_at "
            "FROM ops_document_requests WHERE application_id = ? ORDER BY id DESC",
            (application_id,),
        ).fetchall()
        request_items = connection.execute(
            "SELECT i.id, i.request_id, i.item, i.status, i.uploaded_file_id, i.updated_at "
            "FROM ops_document_request_items i JOIN ops_document_requests r ON r.id = i.request_id "
            "WHERE r.application_id = ? ORDER BY i.id",
            (application_id,),
        ).fetchall()
        checks = connection.execute(
            "SELECT check_key, evidence_revision, status, note, actor_user_id, updated_at "
            "FROM ops_review_checks WHERE application_id = ?",
            (application_id,),
        ).fetchall()
        decision = connection.execute(
            "SELECT decision, decided_at FROM reviewer_decisions WHERE application_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
    return {
        "case": dict(row),
        "events": [
            {**dict(event), "details": json.loads(event["details_json"] or "{}")}
            for event in events
        ],
        "document_requests": [dict(item) for item in requests],
        "document_request_items": [dict(item) for item in request_items],
        "checks": [dict(item) for item in checks],
        "latest_decision": dict(decision) if decision is not None else None,
    }


def worklist(
    application_id: int | None, user_id: int, view: str, limit: int, offset: int
) -> dict[str, Any]:
    now = utc_now()
    active_progress = "('queued','processing','retrying','paused')"
    active_jobs = "('queued','running','retrying','paused')"
    with get_connection() as connection:
        # Record the first server-observed ready moment prospectively. Cases
        # still processing are excluded so their queue age starts on completion.
        connection.execute(
            "INSERT INTO ops_cases (application_id, workflow_state, ready_at, updated_at) "
            "SELECT a.id, 'ready', ?, ? FROM applications a "
            "WHERE LOWER(COALESCE(a.status, '')) IN ('needs_review','clean','failed') "
            f"AND NOT EXISTS (SELECT 1 FROM pipeline_progress p WHERE p.application_id = a.id AND p.status IN {active_progress}) "
            f"AND NOT EXISTS (SELECT 1 FROM pipeline_jobs j WHERE j.application_id = a.id AND j.id = (SELECT MAX(j2.id) FROM pipeline_jobs j2 WHERE j2.application_id = a.id) AND j.status IN {active_jobs}) "
            "ON CONFLICT (application_id) DO NOTHING",
            (now, now),
        )
        view_where = {
            "all": "1 = 1",
            "ready": "c.workflow_state = 'ready' AND c.owner_user_id IS NULL AND COALESCE(p.status,'') NOT IN "
            f"{active_progress} AND COALESCE(j.status,'') NOT IN {active_jobs}",
            "mine": "c.workflow_state = 'ready' AND c.owner_user_id = ? "
            f"AND COALESCE(p.status,'') NOT IN {active_progress} AND COALESCE(j.status,'') NOT IN {active_jobs}",
            "waiting": "(c.workflow_state = 'waiting_documents' OR (c.application_id IS NULL AND LOWER(COALESCE(a.status,'')) = 'incomplete'))",
            "completed": "(c.workflow_state = 'completed' OR (c.application_id IS NULL AND LOWER(COALESCE(a.status,'')) IN ('verified','verified_with_override','accepted'))) ",
            "processing": f"(p.status IN {active_progress} OR j.status IN {active_jobs})",
        }
        if view not in view_where:
            raise ValueError("Unknown Ops worklist view")
        where = view_where[view]
        parameters: list[Any] = []
        if view == "mine":
            parameters.append(user_id)
        if application_id is not None:
            where = f"({where}) AND a.id = ?"
            parameters.append(application_id)
        joins = (
            " FROM applications a LEFT JOIN ops_cases c ON c.application_id = a.id "
            "LEFT JOIN pipeline_progress p ON p.application_id = a.id "
            "LEFT JOIN pipeline_jobs j ON j.id = (SELECT MAX(j2.id) FROM pipeline_jobs j2 WHERE j2.application_id = a.id) "
        )
        total_row = connection.execute(
            "SELECT COUNT(*) AS total" + joins + " WHERE " + where,
            tuple(parameters),
        ).fetchone()
        rows = connection.execute(
            "SELECT a.id, a.loan_id, a.applicant_name, a.status, a.updated_at, "
            "c.owner_user_id, c.workflow_state, c.waiting_reason, c.ready_at, c.returned_at, "
            "c.first_started_at, c.first_outcome_at, c.completed_at, u.display_name AS owner_name, "
            f"(p.status IN {active_progress} OR j.status IN {active_jobs}) AS processing, "
            "(SELECT COUNT(*) FROM validation_results v WHERE v.application_id = a.id AND COALESCE(v.status, '') != 'dismissed_by_llm') AS findings_count"
            + joins
            + " LEFT JOIN users u ON u.id = c.owner_user_id WHERE "
            + where
            + " ORDER BY COALESCE(c.returned_at, c.ready_at, a.updated_at) ASC, a.id ASC LIMIT ? OFFSET ?",
            tuple(parameters + [limit, offset]),
        ).fetchall()

    items: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        app_id = int(item["id"])
        state = item.get("workflow_state")
        processing = bool(item.get("processing"))
        app_status = str(item.get("status") or "").lower()
        if processing:
            state = "processing"
        elif state is None and app_status in {"verified", "verified_with_override", "accepted"}:
            state = "completed"
        elif state is None and app_status == "incomplete":
            state = "waiting_documents"
        elif state is None and app_status in {"needs_review", "clean", "failed"}:
            state = "ready"
        elif state is None:
            state = "not_ready"
        owner = item.get("owner_user_id")
        if view == "ready" and state != "ready":
            continue
        if view == "mine" and (state != "ready" or owner != user_id):
            continue
        if view == "waiting" and state != "waiting_documents":
            continue
        if view == "completed" and state != "completed":
            continue
        if view == "processing" and state != "processing":
            continue
        if application_id is not None and app_id != application_id:
            continue
        items.append(
            {
                "application_id": app_id,
                "loan_id": item.get("loan_id"),
                "applicant_name": item.get("applicant_name"),
                "status": "processing" if state == "processing" else app_status,
                "workflow_state": state,
                "findings_count": int(item.get("findings_count") or 0),
                "updated_at": item.get("updated_at"),
                "ready_at": item.get("ready_at"),
                "queue_entered_at": item.get("returned_at") or item.get("ready_at"),
                "owner_user_id": owner,
                "owner_name": item.get("owner_name"),
                "waiting_reason": item.get("waiting_reason"),
                "next_action": "Wait for processing"
                if state == "processing"
                else "Review documents"
                if state == "waiting_documents"
                else "Resume review"
                if owner == user_id
                else "Claim and review"
                if state == "ready"
                else "Outcome recorded"
                if state == "completed"
                else "Waiting for processing",
            }
        )
    total = int(total_row["total"] or 0)
    return {
        "applications": items[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
        "view": view,
    }


def claim(
    application_id: int, user_id: int, *, admin_reassign: bool = False, reason: str | None = None
) -> dict[str, Any]:
    # Seed a prospective case only when its current application state is
    # eligible for the actionable queue. The locked write below resolves races.
    worklist(application_id, user_id, "ready", 1, 0)
    now = utc_now()
    with get_connection() as connection:
        _begin_write(connection)
        row = connection.execute(
            "SELECT owner_user_id, workflow_state FROM ops_cases WHERE application_id = ?"
            + _for_update(),
            (application_id,),
        ).fetchone()
        if row is None:
            raise KeyError(application_id)
        owner = row["owner_user_id"]
        if row["workflow_state"] != "ready":
            raise ValueError("Only ready cases can be claimed")
        if owner is not None and int(owner) != user_id and not admin_reassign:
            raise PermissionError("Case is already claimed by another reviewer")
        action = (
            "case_reassigned" if owner is not None and int(owner) != user_id else "case_claimed"
        )
        if action == "case_reassigned" and not (reason or "").strip():
            raise ValueError("A reason is required when reassigning a case")
        connection.execute(
            "UPDATE ops_cases SET owner_user_id = ?, first_started_at = COALESCE(first_started_at, ?), updated_at = ? "
            "WHERE application_id = ?",
            (user_id, now, now, application_id),
        )
        _event(connection, application_id, user_id, action, now, reason=reason)
    return workflow_detail(application_id, user_id)["case"]


def release(
    application_id: int, user_id: int, *, admin: bool = False, reason: str | None = None
) -> dict[str, Any]:
    now = utc_now()
    with get_connection() as connection:
        _begin_write(connection)
        row = connection.execute(
            "SELECT owner_user_id, workflow_state FROM ops_cases WHERE application_id = ?"
            + _for_update(),
            (application_id,),
        ).fetchone()
        if row is None:
            raise KeyError(application_id)
        if row["workflow_state"] != "ready":
            raise ValueError("Only ready cases can be released")
        if row["owner_user_id"] is not None and int(row["owner_user_id"]) != user_id and not admin:
            raise PermissionError("Only the case owner or an admin may release this case")
        connection.execute(
            "UPDATE ops_cases SET owner_user_id = NULL, updated_at = ? WHERE application_id = ?",
            (now, application_id),
        )
        _event(connection, application_id, user_id, "case_released", now, reason=reason)
    return workflow_detail(application_id, user_id)["case"]


def reassign(
    application_id: int, target_user_id: int, actor_user_id: int, reason: str
) -> dict[str, Any]:
    now = utc_now()
    with get_connection() as connection:
        _begin_write(connection)
        target = connection.execute(
            "SELECT id FROM users WHERE id = ? AND is_active = TRUE", (target_user_id,)
        ).fetchone()
        case = connection.execute(
            "SELECT workflow_state FROM ops_cases WHERE application_id = ?" + _for_update(),
            (application_id,),
        ).fetchone()
        if target is None or case is None:
            raise KeyError(application_id)
        if case["workflow_state"] != "ready":
            raise ValueError("Only ready cases can be reassigned")
        connection.execute(
            "UPDATE ops_cases SET owner_user_id = ?, updated_at = ? WHERE application_id = ?",
            (target_user_id, now, application_id),
        )
        _event(
            connection,
            application_id,
            actor_user_id,
            "case_reassigned",
            now,
            reason=reason,
            details={"new_owner_user_id": target_user_id},
        )
    return workflow_detail(application_id, actor_user_id)["case"]


def review_next(user_id: int) -> int | None:
    with get_connection() as connection:
        candidates = connection.execute(
            "SELECT a.id, c.owner_user_id FROM applications a JOIN ops_cases c ON c.application_id = a.id "
            "LEFT JOIN pipeline_progress p ON p.application_id = a.id "
            "LEFT JOIN pipeline_jobs j ON j.id = (SELECT MAX(j2.id) FROM pipeline_jobs j2 WHERE j2.application_id = a.id) "
            "WHERE c.workflow_state = 'ready' AND (c.owner_user_id IS NULL OR c.owner_user_id = ?) "
            "AND COALESCE(p.status, '') NOT IN ('queued','processing','retrying','paused') "
            "AND COALESCE(j.status, '') NOT IN ('queued','running','retrying','paused') "
            "ORDER BY COALESCE(c.returned_at, c.ready_at) ASC, a.id ASC LIMIT 1",
            (user_id,),
        ).fetchone()
    if candidates is None:
        return None
    claim(int(candidates["id"]), user_id)
    return int(candidates["id"])


def check_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for finding in payload.get("top_findings", []):
        content = {
            "code": finding.get("code"),
            "severity": finding.get("severity"),
            "title": finding.get("title"),
            "detail": finding.get("detail"),
            "pages": finding.get("pages", []),
            "evidence": finding.get("evidence"),
        }
        revision = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        key = hashlib.sha256(f"finding:{revision}".encode()).hexdigest()[:32]
        items.append(
            {
                "check_key": key,
                "evidence_revision": revision,
                "kind": "finding",
                "title": finding.get("title"),
                "pages": finding.get("pages", []),
                "status": None,
                "note": None,
            }
        )
    for row in payload.get("checklist", {}).get("rows", []):
        content = {
            "s_no": row.get("s_no"),
            "description": row.get("description"),
            "status": row.get("status"),
            "pages": row.get("pages", []),
        }
        revision = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        key = hashlib.sha256(f"checklist:{revision}".encode()).hexdigest()[:32]
        items.append(
            {
                "check_key": key,
                "evidence_revision": revision,
                "kind": "checklist",
                "title": row.get("description"),
                "pages": row.get("pages", []),
                "status": None,
                "note": None,
            }
        )
    return items


def save_check(
    application_id: int,
    user_id: int,
    check_key: str,
    revision: str,
    status: str,
    note: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if status not in {"checked", "exception_confirmed", "needs_help"}:
        raise ValueError("Invalid review check status")
    current = next((item for item in check_items(payload) if item["check_key"] == check_key), None)
    if current is None or current["evidence_revision"] != revision:
        raise RuntimeError("Evidence changed; refresh the case before saving this check")
    now = utc_now()
    with get_connection() as connection:
        _begin_write(connection)
        case = connection.execute(
            "SELECT owner_user_id FROM ops_cases WHERE application_id = ?" + _for_update(),
            (application_id,),
        ).fetchone()
        if case is None:
            raise KeyError(application_id)
        if case["owner_user_id"] is None or int(case["owner_user_id"]) != user_id:
            raise PermissionError("Claim this case before saving review progress")
        connection.execute(
            "INSERT INTO ops_review_checks (application_id, check_key, evidence_revision, status, note, actor_user_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (application_id, check_key) DO UPDATE SET "
            "evidence_revision = excluded.evidence_revision, status = excluded.status, note = excluded.note, "
            "actor_user_id = excluded.actor_user_id, updated_at = excluded.updated_at",
            (
                application_id,
                check_key,
                revision,
                status,
                (note or "").strip() or None,
                user_id,
                now,
            ),
        )
        connection.execute(
            "UPDATE ops_cases SET first_started_at = COALESCE(first_started_at, ?), updated_at = ? WHERE application_id = ?",
            (now, now, application_id),
        )
        _event(
            connection,
            application_id,
            user_id,
            "review_check_saved",
            now,
            details={"check_key": check_key, "status": status},
        )
    return {
        "check_key": check_key,
        "evidence_revision": revision,
        "status": status,
        "note": (note or "").strip() or None,
        "updated_at": now,
    }


def create_document_request(
    application_id: int, user_id: int, message: str, items: list[str], follow_up_at: str | None
) -> dict[str, Any]:
    normalized = list(dict.fromkeys(item.strip() for item in items if item.strip()))
    if not normalized or len(normalized) > 30:
        raise ValueError("Add between 1 and 30 requested document items")
    if not message.strip() or len(message) > 4000:
        raise ValueError("A message of at most 4,000 characters is required")
    now = utc_now()
    with get_connection() as connection:
        _begin_write(connection)
        case = connection.execute(
            "SELECT owner_user_id, workflow_state FROM ops_cases WHERE application_id = ?"
            + _for_update(),
            (application_id,),
        ).fetchone()
        if case is None:
            raise KeyError(application_id)
        if case["owner_user_id"] is not None and int(case["owner_user_id"]) != user_id:
            raise PermissionError("Only the owner may request documents")
        if case["owner_user_id"] is None:
            raise PermissionError("Claim this case before requesting documents")
        created = connection.execute(
            "INSERT INTO ops_document_requests (application_id, owner_user_id, message, status, follow_up_at, created_by, opened_at) "
            "VALUES (?, ?, ?, 'open', ?, ?, ?) RETURNING id",
            (application_id, user_id, message.strip(), follow_up_at, user_id, now),
        ).fetchone()
        request_id = int(created["id"])
        for item in normalized:
            connection.execute(
                "INSERT INTO ops_document_request_items (request_id, item, status, updated_at) VALUES (?, ?, 'requested', ?)",
                (request_id, item, now),
            )
        connection.execute(
            "UPDATE ops_cases SET workflow_state = 'waiting_documents', waiting_reason = ?, updated_at = ? WHERE application_id = ?",
            (f"Waiting for {len(normalized)} requested item(s)", now, application_id),
        )
        _event(
            connection,
            application_id,
            user_id,
            "documents_requested",
            now,
            details={"request_id": request_id, "items": normalized, "follow_up_at": follow_up_at},
        )
    return {
        "request_id": request_id,
        "application_id": application_id,
        "status": "open",
        "items": normalized,
        "message": message.strip(),
        "follow_up_at": follow_up_at,
        "opened_at": now,
    }


def update_request_item(
    application_id: int,
    request_id: int,
    item_id: int,
    status: str,
    uploaded_file_id: int | None,
    user_id: int,
) -> dict[str, Any]:
    if status not in {"received", "outstanding"}:
        raise ValueError("Status must be received or outstanding")
    now = utc_now()
    with get_connection() as connection:
        _begin_write(connection)
        item = connection.execute(
            "SELECT i.id, i.request_id, i.item, i.status, r.application_id, r.status AS request_status "
            "FROM ops_document_request_items i JOIN ops_document_requests r ON r.id = i.request_id "
            "WHERE i.id = ? AND i.request_id = ? AND r.application_id = ?" + _for_update(),
            (item_id, request_id, application_id),
        ).fetchone()
        if item is None:
            raise KeyError(item_id)
        owner = connection.execute(
            "SELECT owner_user_id FROM ops_cases WHERE application_id = ?" + _for_update(),
            (application_id,),
        ).fetchone()
        if (
            owner is None
            or owner["owner_user_id"] is None
            or int(owner["owner_user_id"]) != user_id
        ):
            raise PermissionError("Claim this case before updating requested documents")
        if item["request_status"] != "open":
            raise ValueError("This document request is already closed")
        if uploaded_file_id is not None:
            linked = connection.execute(
                "SELECT id FROM uploaded_files WHERE id = ? AND application_id = ?",
                (uploaded_file_id, application_id),
            ).fetchone()
            if linked is None:
                raise ValueError("The linked file does not belong to this application")
        connection.execute(
            "UPDATE ops_document_request_items SET status = ?, uploaded_file_id = ?, updated_at = ? WHERE id = ?",
            (status, uploaded_file_id, now, item_id),
        )
        remaining = connection.execute(
            "SELECT COUNT(*) AS n FROM ops_document_request_items WHERE request_id = ? AND status NOT IN ('received')",
            (request_id,),
        ).fetchone()
        resolved = int(remaining["n"] or 0) == 0
        if resolved:
            connection.execute(
                "UPDATE ops_document_requests SET status = 'resolved', resolved_at = ? WHERE id = ?",
                (now, request_id),
            )
            open_count = connection.execute(
                "SELECT COUNT(*) AS n FROM ops_document_requests WHERE application_id = ? AND status = 'open'",
                (application_id,),
            ).fetchone()
            if int(open_count["n"] or 0) == 0:
                connection.execute(
                    "UPDATE ops_cases SET workflow_state = 'ready', waiting_reason = NULL, returned_at = ?, updated_at = ? WHERE application_id = ?",
                    (now, now, application_id),
                )
        _event(
            connection,
            application_id,
            user_id,
            "document_item_updated",
            now,
            details={
                "request_id": request_id,
                "item_id": item_id,
                "status": status,
                "uploaded_file_id": uploaded_file_id,
                "request_resolved": resolved,
            },
        )
    return {
        "item_id": item_id,
        "request_id": request_id,
        "status": status,
        "uploaded_file_id": uploaded_file_id,
        "updated_at": now,
        "request_resolved": resolved,
    }


def record_decision(
    connection: Any, application_id: int, user_id: int, decision: str, now: str, note: str
) -> None:
    case = connection.execute(
        "SELECT application_id FROM ops_cases WHERE application_id = ?", (application_id,)
    ).fetchone()
    if case is None:
        connection.execute(
            "INSERT INTO ops_cases (application_id, workflow_state, ready_at, updated_at) VALUES (?, 'ready', NULL, ?)",
            (application_id, now),
        )
    next_state = "waiting_documents" if decision == "REQUEST_DOCS" else "completed"
    connection.execute(
        "UPDATE ops_cases SET workflow_state = ?, waiting_reason = ?, owner_user_id = CASE WHEN ? = 'waiting_documents' THEN ? ELSE owner_user_id END, "
        "first_outcome_at = COALESCE(first_outcome_at, ?), "
        "completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END, updated_at = ? WHERE application_id = ?",
        (
            next_state,
            "Documents requested" if decision == "REQUEST_DOCS" else None,
            next_state,
            user_id,
            now,
            next_state,
            now,
            now,
            application_id,
        ),
    )
    _event(
        connection,
        application_id,
        user_id,
        "decision_recorded",
        now,
        details={"decision": decision},
    )
    if decision == "REQUEST_DOCS":
        created = connection.execute(
            "INSERT INTO ops_document_requests (application_id, owner_user_id, message, status, created_by, opened_at) "
            "VALUES (?, ?, ?, 'open', ?, ?) RETURNING id",
            (application_id, user_id, note.strip(), user_id, now),
        ).fetchone()
        connection.execute(
            "INSERT INTO ops_document_request_items (request_id, item, status, updated_at) "
            "VALUES (?, ?, 'requested', ?)",
            (int(created["id"]), "Requested documents (see review note)", now),
        )
        _event(
            connection,
            application_id,
            user_id,
            "documents_requested",
            now,
            details={"request_id": int(created["id"]), "source": "review_decision"},
        )


def record_undo(
    connection: Any, application_id: int, user_id: int, restored_status: str, now: str
) -> None:
    connection.execute(
        "SELECT application_id FROM ops_cases WHERE application_id = ?" + _for_update(),
        (application_id,),
    ).fetchone()
    open_request = connection.execute(
        "SELECT id FROM ops_document_requests WHERE application_id = ? AND status = 'open' LIMIT 1",
        (application_id,),
    ).fetchone()
    next_state = (
        "completed"
        if restored_status in {"verified", "verified_with_override", "accepted"}
        else "waiting_documents"
        if restored_status == "incomplete" or open_request is not None
        else "ready"
    )
    connection.execute(
        "UPDATE ops_cases SET workflow_state = ?, owner_user_id = CASE WHEN ? = 'ready' THEN NULL ELSE owner_user_id END, "
        "waiting_reason = CASE WHEN ? = 'waiting_documents' THEN COALESCE(waiting_reason, 'Documents requested') ELSE NULL END, "
        "ready_at = CASE WHEN ? = 'ready' THEN ? ELSE ready_at END, returned_at = NULL, "
        "completed_at = CASE WHEN ? = 'completed' THEN completed_at ELSE NULL END, updated_at = ? "
        "WHERE application_id = ?",
        (next_state, next_state, next_state, next_state, now, next_state, now, application_id),
    )
    _event(
        connection,
        application_id,
        user_id,
        "decision_undone",
        now,
        details={"restored_status": restored_status, "workflow_state": next_state},
    )


def tat_metrics() -> dict[str, Any]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT application_id, workflow_state, ready_at, returned_at, first_started_at, first_outcome_at, completed_at FROM ops_cases"
        ).fetchall()
        wait_rows = connection.execute(
            "SELECT application_id, opened_at, resolved_at FROM ops_document_requests"
        ).fetchall()
        undo_row = connection.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = 'decision_undone'"
        ).fetchone()
    now = datetime.now(UTC)

    def minutes(start: Any, end: Any) -> float | None:
        if not start or not end:
            return None
        try:
            a, b = datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end))
            if a.tzinfo is None:
                a = a.replace(tzinfo=UTC)
            if b.tzinfo is None:
                b = b.replace(tzinfo=UTC)
            return max(0.0, (b - a).total_seconds() / 60)
        except ValueError:
            return None

    wait_by_app: dict[int, float] = {}
    request_rounds_by_app: dict[int, int] = {}
    for item in wait_rows:
        app_id = int(item["application_id"])
        wait_by_app[app_id] = wait_by_app.get(app_id, 0.0) + (
            minutes(item["opened_at"], item["resolved_at"] or now.isoformat()) or 0.0
        )
        request_rounds_by_app[app_id] = request_rounds_by_app.get(app_id, 0) + 1

    def summary(values: list[float]) -> dict[str, Any]:
        ordered = sorted(values)
        if not ordered:
            return {"sample_count": 0, "p50_minutes": None, "p90_minutes": None}
        import math

        return {
            "sample_count": len(ordered),
            "p50_minutes": round(statistics.median(ordered), 1),
            "p90_minutes": round(ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)], 1),
        }

    first_touch, first_outcome, completion_total, completion_without_wait = [], [], [], []
    for row in rows:
        ready = row["ready_at"]
        start = row["first_started_at"]
        outcome = row["first_outcome_at"]
        complete = row["completed_at"]
        if ready and start and (value := minutes(ready, start)) is not None:
            first_touch.append(value)
        if start and outcome and (value := minutes(start, outcome)) is not None:
            first_outcome.append(value)
        if ready and complete and (value := minutes(ready, complete)) is not None:
            completion_total.append(value)
            completion_without_wait.append(
                max(0.0, value - wait_by_app.get(int(row["application_id"]), 0.0))
            )
    return {
        "baseline_type": "prospective",
        "sample_count": len(rows),
        "first_touch": summary(first_touch),
        "first_outcome_after_start": summary(first_outcome),
        "ready_to_completion": summary(completion_total),
        "ready_to_completion_excluding_document_wait": summary(completion_without_wait),
        "document_wait": summary(
            [
                minutes(item["opened_at"], item["resolved_at"] or now.isoformat()) or 0.0
                for item in wait_rows
            ]
        ),
        "document_request_rounds": {
            "total": len(wait_rows),
            "cases_with_requests": len(request_rounds_by_app),
            "cases_with_multiple_requests": sum(
                1 for count in request_rounds_by_app.values() if count > 1
            ),
        },
        "cases_reopened_after_documents": sum(1 for row in rows if row["returned_at"]),
        "decision_undo_count": int(undo_row["n"] or 0),
        "note": "Times begin when Ops workflow tracking first observes a case. Missing historical workflow dates are not inferred.",
    }
