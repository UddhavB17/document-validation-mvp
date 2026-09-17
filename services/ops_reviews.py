"""Human review state for individual operations findings.

This is the smallest persisted reviewer workflow: one validation result is one
review item, and a review action never changes the source validation result or
the separate LLM dismissal status.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from database.db import get_connection
from services.ops_presentation import (
    _finding_from_group,
    rule_to_code,
)

ReviewDisposition = Literal["correct", "reopen"]


class StaleReviewItemError(ValueError):
    """The client is trying to update a finding revision that changed."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_evidence(value: Any) -> Any:
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def finding_revision(row: dict[str, Any]) -> str:
    """Return the revision fingerprint for the user-facing finding fields."""
    material = {
        key: row.get(key)
        for key in (
            "rule_id",
            "s_no",
            "severity",
            "document_type",
            "expected_value",
            "found_value",
            "page_number",
            "reason",
            "evidence_json",
            "status",
        )
    }
    material["evidence_json"] = _parse_evidence(material["evidence_json"])
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def review_item_id(application_id: int, validation_result_id: int, revision: str) -> str:
    """Create a stable opaque id for one application/finding revision."""
    raw = f"{application_id}:{validation_result_id}:{revision}".encode()
    return f"ri_{hashlib.sha256(raw).hexdigest()[:32]}"


def _load_active_findings(connection: Any, application_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM validation_results WHERE application_id = ? "
        "AND COALESCE(status, '') != 'dismissed_by_llm' ORDER BY id",
        (application_id,),
    ).fetchall()
    findings: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["evidence_json"] = _parse_evidence(item.get("evidence_json"))
        if rule_to_code(item.get("rule_id")) is not None:
            findings.append(item)
    return findings


def _reviewer_names(connection: Any, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    placeholders = ", ".join("?" for _ in user_ids)
    rows = connection.execute(
        f"SELECT id, display_name, email FROM users WHERE id IN ({placeholders})",
        tuple(user_ids),
    ).fetchall()
    return {
        int(row["id"]): str(row["display_name"] or row["email"] or f"user {row['id']}")
        for row in rows
    }


def _ensure_review_rows(
    connection: Any,
    application_id: int,
    findings: list[dict[str, Any]],
    now: str,
) -> dict[str, dict[str, Any]]:
    item_ids: list[str] = []
    for finding in findings:
        revision = finding_revision(finding)
        item_id = review_item_id(application_id, int(finding["id"]), revision)
        item_ids.append(item_id)
        connection.execute(
            """
            INSERT INTO ops_review_items (
                item_id, application_id, validation_result_id, finding_revision,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(item_id) DO NOTHING
            """,
            (item_id, application_id, int(finding["id"]), revision, now, now),
        )
    if not item_ids:
        return {}
    placeholders = ", ".join("?" for _ in item_ids)
    rows = connection.execute(
        f"SELECT * FROM ops_review_items WHERE application_id = ? AND item_id IN ({placeholders})",
        (application_id, *item_ids),
    ).fetchall()
    return {str(row["item_id"]): dict(row) for row in rows}


def _serialize_item(
    finding: dict[str, Any], state: dict[str, Any], reviewer_name: str | None
) -> dict[str, Any]:
    code = rule_to_code(finding.get("rule_id"))
    if code is None:
        raise ValueError("Finding is not operations-reviewable")
    finding_view = _finding_from_group(code, [finding])
    reviewer = None
    if state.get("reviewer_id") is not None:
        reviewer = {
            "id": int(state["reviewer_id"]),
            "name": reviewer_name or f"user {int(state['reviewer_id'])}",
        }
    return {
        "item_id": str(state["item_id"]),
        "application_id": int(state["application_id"]),
        "validation_result_id": int(state["validation_result_id"]),
        "revision": str(state["finding_revision"]),
        "code": finding_view["code"],
        "severity": finding_view["severity"],
        "title": finding_view["title"],
        "detail": finding_view["detail"],
        "pages": finding_view["pages"],
        "evidence": finding_view["evidence"],
        "status": str(state["status"]),
        "disposition": state.get("disposition"),
        "reviewer": reviewer,
        "reviewed_at": state.get("reviewed_at"),
        "note": state.get("note"),
    }


def _find_current_item(
    connection: Any, application_id: int, item_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    state_row = connection.execute(
        "SELECT * FROM ops_review_items WHERE application_id = ? AND item_id = ?",
        (application_id, item_id),
    ).fetchone()
    if state_row is None:
        raise KeyError(item_id)
    finding_row = connection.execute(
        "SELECT * FROM validation_results WHERE application_id = ? AND id = ?",
        (application_id, state_row["validation_result_id"]),
    ).fetchone()
    if finding_row is None:
        raise StaleReviewItemError("Finding no longer exists")
    finding = dict(finding_row)
    finding["evidence_json"] = _parse_evidence(finding.get("evidence_json"))
    if finding.get("status") == "dismissed_by_llm":
        raise StaleReviewItemError("Finding is no longer active")
    if finding_revision(finding) != str(state_row["finding_revision"]):
        raise StaleReviewItemError("Finding changed; reload the review item")
    return dict(state_row), finding


def get_review_items(application_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        app_row = connection.execute(
            "SELECT id FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if app_row is None:
            raise KeyError(application_id)
        findings = _load_active_findings(connection, application_id)
        states = _ensure_review_rows(connection, application_id, findings, _now())
        user_ids = {
            int(state["reviewer_id"])
            for state in states.values()
            if state.get("reviewer_id") is not None
        }
        names = _reviewer_names(connection, user_ids)
        items = []
        for finding in findings:
            revision = finding_revision(finding)
            item_id = review_item_id(application_id, int(finding["id"]), revision)
            state = states[item_id]
            items.append(_serialize_item(finding, state, names.get(int(state["reviewer_id"])) if state.get("reviewer_id") is not None else None))
    reviewed = [item for item in items if item["status"] == "reviewed"]
    return {
        "application_id": application_id,
        "items": items,
        "counts": {
            "total": len(items),
            "pending": len(items) - len(reviewed),
            "reviewed": len(reviewed),
        },
    }


def update_review_item(
    application_id: int,
    item_id: str,
    expected_revision: str,
    disposition: ReviewDisposition,
    reviewer_id: int,
    note: str | None,
) -> dict[str, Any]:
    now = _now()
    clean_note = (note or "").strip() or None
    with get_connection() as connection:
        state, finding = _find_current_item(connection, application_id, item_id)
        if expected_revision != state["finding_revision"]:
            raise StaleReviewItemError("Finding revision is stale; reload before saving")
        status = "reviewed" if disposition == "correct" else "pending"
        connection.execute(
            """
            UPDATE ops_review_items
            SET status = ?, disposition = ?, reviewer_id = ?, reviewed_at = ?, note = ?, updated_at = ?
            WHERE application_id = ? AND item_id = ? AND finding_revision = ?
            """,
            (
                status,
                disposition,
                reviewer_id,
                now,
                clean_note,
                now,
                application_id,
                item_id,
                expected_revision,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (
                application_id,
                "ops_exception_review_updated",
                json.dumps(
                    {
                        "item_id": item_id,
                        "validation_result_id": int(state["validation_result_id"]),
                        "revision": expected_revision,
                        "disposition": disposition,
                        "reviewer_id": reviewer_id,
                        "note": clean_note,
                    }
                ),
            ),
        )
        updated, current_finding = _find_current_item(connection, application_id, item_id)
        names = _reviewer_names(connection, {reviewer_id})
        return _serialize_item(current_finding, updated, names.get(reviewer_id))
