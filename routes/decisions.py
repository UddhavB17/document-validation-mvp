"""Reviewer decision API routes."""

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.db import dialect, get_connection, init_db
from services.auth.dependencies import CurrentUser, get_current_user
from services.progress_tracker import operational_progress_status
from services.reviewer import compute_final_status

router = APIRouter(
    prefix="/decision", tags=["decision"], dependencies=[Depends(get_current_user)]
)

VALID_DECISIONS = {"ACCEPT", "OVERRIDE", "REQUEST_DOCS"}
GATED_DECISIONS = {"ACCEPT", "OVERRIDE"}
COMPLETED_PROGRESS_STATUSES = frozenset({"completed", "completed_with_warnings"})
STATUS_BY_DECISION = {
    "ACCEPT": "verified",
    "OVERRIDE": "verified_with_override",
    "REQUEST_DOCS": "incomplete",
}
UNDO_WINDOW_MINUTES = 10


def _begin_immediate(connection) -> None:
    """Acquire the SQLite write lock before any reads in a decision write path.

    ``BEGIN IMMEDIATE`` as the first statement serializes decision/undo
    writers (a second writer blocks on the busy timeout instead of reading
    stale rows). No-op on PostgreSQL, where row locks are used instead.
    """
    if dialect() == "sqlite":
        connection.execute("BEGIN IMMEDIATE")


def _lock_application(connection, application_id: int) -> None:
    """Serialize decision/undo writes on the application row where practical.

    On PostgreSQL this takes a row lock (``FOR UPDATE``); on SQLite the
    surrounding transaction still serializes writers. Uses the dialect
    wrapper (``?`` placeholders) in both cases.
    """
    if dialect() == "postgresql":
        connection.execute(
            "SELECT id FROM applications WHERE id = ? FOR UPDATE",
            (application_id,),
        )
    else:
        connection.execute(
            "SELECT id FROM applications WHERE id = ?",
            (application_id,),
        )


def _is_pipeline_complete(connection, application_id: int) -> bool:
    """Return True only with positive evidence that processing completed.

    Requires ``pipeline_progress`` to report an operational status of
    ``completed`` (or ``completed_with_warnings``, including the legacy
    ``partial_failed`` mapping) via existing staleness semantics. When any
    ``pipeline_jobs`` row exists, the latest job must also report
    ``completed``. Absent progress (with no completed job), or any
    queued/running/retrying/paused/cancelled/stale/failed signal, fails
    closed. Business status (``applications.status`` / validation findings)
    is never consulted here.
    """
    progress = connection.execute(
        "SELECT status, updated_at FROM pipeline_progress WHERE application_id = ?",
        (application_id,),
    ).fetchone()
    latest_job = connection.execute(
        "SELECT status FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
        (application_id,),
    ).fetchone()

    if progress is not None:
        operational = operational_progress_status(dict(progress))
        if operational not in COMPLETED_PROGRESS_STATUSES:
            return False
        if latest_job is not None and str(latest_job["status"] or "").lower() != "completed":
            return False
        return True
    if latest_job is not None and str(latest_job["status"] or "").lower() == "completed":
        return True
    return False


class DecisionRequest(BaseModel):
    application_id: int
    decision: str
    reviewer_note: str


@router.get("/{application_id}", summary="Get latest decision for an application")
def get_decision(application_id: int) -> dict[str, object]:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, application_id, decision, reviewer_note, decided_at
            FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()

    if row is None:
        return {"application_id": application_id, "decision": "pending"}
    return dict(row)


@router.post("")
def create_decision(
    payload: DecisionRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    init_db()
    decision = payload.decision.upper()
    reviewer_note = payload.reviewer_note.strip()

    if decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=400, detail="Decision must be ACCEPT, OVERRIDE, or REQUEST_DOCS"
        )

    if len(reviewer_note) <= 10:
        raise HTTPException(status_code=400, detail="Reviewer note must be more than 10 characters")

    decided_at = datetime.now(UTC).isoformat()
    new_status = STATUS_BY_DECISION[decision]

    with get_connection() as connection:
        _begin_immediate(connection)
        _lock_application(connection, payload.application_id)
        existing = connection.execute(
            "SELECT id, status FROM applications WHERE id = ?",
            (payload.application_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Application not found")

        if decision in GATED_DECISIONS and not _is_pipeline_complete(
            connection, payload.application_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Pipeline processing has not completed for this application",
            )

        previous_status = existing["status"]
        # ws-b storage+db: RETURNING instead of cursor.lastrowid (None on Postgres).
        created = connection.execute(
            """
            INSERT INTO reviewer_decisions (application_id, decision, reviewer_note, decided_at)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (payload.application_id, decision, reviewer_note, decided_at),
        ).fetchone()
        if created is None:
            raise HTTPException(status_code=500, detail="Failed to record decision")
        decision_id = int(created["id"])
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (new_status, payload.application_id),
        )
        # Atomic with the decision: a verified decision must never lose its
        # reviewer trail because a follow-up audit write failed.
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (
                payload.application_id,
                "reviewer_decision_made",
                json.dumps(
                    {
                        "decision": decision,
                        "reviewer_note": reviewer_note,
                        "new_status": new_status,
                        "previous_status": previous_status,
                        "decision_id": decision_id,
                        "user_id": user.id,
                        "user_email": user.email,
                    }
                ),
            ),
        )

    return {
        "decision_id": decision_id,
        "application_id": payload.application_id,
        "decision": decision,
        "new_status": new_status,
        "decided_at": decided_at,
        "previous_status": previous_status,
    }


@router.post("/{decision_id}/undo", summary="Undo a recent reviewer decision")
def undo_decision(
    decision_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    init_db()
    with get_connection() as connection:
        # Write lock before any reads so concurrent undos serialize.
        _begin_immediate(connection)
        row = connection.execute(
            """
            SELECT id, application_id, decision, decided_at
            FROM reviewer_decisions
            WHERE id = ?
            """,
            (decision_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Decision not found")

        raw_decided_at = row["decided_at"]
        if isinstance(raw_decided_at, datetime):
            decided_at = raw_decided_at
        else:
            decided_at = datetime.fromisoformat(str(raw_decided_at))
        if decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - decided_at > timedelta(minutes=UNDO_WINDOW_MINUTES):
            raise HTTPException(status_code=400, detail="Undo window expired, contact supervisor")

        application_id = int(row["application_id"])
        _lock_application(connection, application_id)

        latest = connection.execute(
            """
            SELECT id FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        if latest is None or int(latest["id"]) != int(row["id"]):
            raise HTTPException(
                status_code=409, detail="Only the latest decision may be undone"
            )

        preceding = connection.execute(
            """
            SELECT decision FROM reviewer_decisions
            WHERE application_id = ? AND id < ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id, decision_id),
        ).fetchone()
        if preceding is not None and str(preceding["decision"] or "").upper() in STATUS_BY_DECISION:
            restored_status = STATUS_BY_DECISION[str(preceding["decision"]).upper()]
        else:
            anomalies = connection.execute(
                "SELECT severity, rule_id FROM validation_results WHERE application_id = ?",
                (application_id,),
            ).fetchall()
            restored_status = compute_final_status([dict(item) for item in anomalies])

        connection.execute("DELETE FROM reviewer_decisions WHERE id = ?", (decision_id,))
        connection.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (restored_status, application_id),
        )
        # Atomic with the undo for the same reason as creation.
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details)
            VALUES (?, ?, ?)
            """,
            (
                application_id,
                "decision_undone",
                json.dumps(
                    {
                        "decision_id": decision_id,
                        "restored_status": restored_status,
                        "user_id": user.id,
                        "user_email": user.email,
                    }
                ),
            ),
        )
    return {
        "decision_id": decision_id,
        "application_id": application_id,
        "restored_status": restored_status,
    }
