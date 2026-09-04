"""Retention coverage for ws-a (each action, dry-run True and False)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.retention import RETAINED_AUDIT_ACTIONS, run_retention
from services.storage import get_store

NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)
OLD = "2026-01-01 10:00:00"
NEW = "2026-09-01 10:00:00"


def _insert_application(loan_id: str, created_at: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, branch, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (loan_id, "Ramesh Kumar", "LAP", "Delhi", "processing", created_at),
        ).fetchone()
        return int(row["id"])


def _insert_job(application_id: int, status: str, created_at: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO pipeline_jobs (application_id, job_type, status, created_at)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (application_id, "pdf_pipeline", status, created_at),
        ).fetchone()
        return int(row["id"])


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    init_db()

    old_app = _insert_application("OLD-1", OLD)
    new_app = _insert_application("NEW-1", NEW)

    completed_a = _insert_job(old_app, "completed", OLD)
    completed_b = _insert_job(old_app, "completed", OLD)
    _insert_job(old_app, "completed", OLD)
    _insert_job(old_app, "failed", OLD)
    queued_new = _insert_job(new_app, "queued", NEW)

    with get_connection() as connection:
        for job_id in (completed_a, completed_b, queued_new):
            connection.execute(
                """
                INSERT INTO pipeline_job_inputs (job_id, application_id, encrypted_payload, source_sha256, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, old_app if job_id != queued_new else new_app, "x", "y", OLD),
            )
        connection.execute(
            """
            INSERT INTO ocr_route_events
                (document_id, page_number, event_type, requested_route, route_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)
            """,
            ("old-doc", 1, "processing", "fast", "fast", OLD,
             "new-doc", 1, "processing", "fast", "fast", NEW),
        )
        connection.execute(
            """
            INSERT INTO classification_review_log
                (application_id, page_number, reason, created_at)
            VALUES (?, ?, ?, ?), (?, ?, ?, ?)
            """,
            (old_app, 1, "low_confidence", OLD, new_app, 1, "low_confidence", NEW),
        )
        connection.execute(
            """
            INSERT INTO audit_log (application_id, action, details, timestamp)
            VALUES (?, ?, ?, ?), (?, ?, ?, ?), (?, ?, ?, ?)
            """,
            (old_app, "reviewer_decision_made", "{}", OLD,
             old_app, "llm_summary_generated", "{}", OLD,
             new_app, "llm_summary_generated", "{}", NEW),
        )
        connection.execute(
            """
            INSERT INTO uploaded_files (application_id, file_path, original_filename)
            VALUES (?, ?, ?)
            """,
            (old_app, "applications/old/source/a.pdf", "a.pdf"),
        )
        connection.execute(
            """
            INSERT INTO intake_packages
                (package_id, application_id, source_filename, source_zip_path,
                 normalized_pdf_path, total_files, total_pages, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("pkg-old", old_app, "a.zip", "applications/old/source/a.zip",
             "applications/old/normalized/a.pdf", 1, 2, OLD),
        )

    store = get_store()
    store.put("applications/old/source/a.pdf", b"pdf-bytes", "application/pdf")
    store.put("applications/old/source/a.zip", b"zip-bytes", "application/zip")
    store.put("applications/old/normalized/a.pdf", b"pdf-bytes", "application/pdf")
    return {"old_app": old_app, "new_app": new_app}


def _counts() -> dict[str, int]:
    with get_connection() as connection:
        return {
            "inputs": int(
                connection.execute("SELECT COUNT(*) AS c FROM pipeline_job_inputs").fetchone()["c"]
            ),
            "jobs": int(
                connection.execute("SELECT COUNT(*) AS c FROM pipeline_jobs").fetchone()["c"]
            ),
            "route_events": int(
                connection.execute("SELECT COUNT(*) AS c FROM ocr_route_events").fetchone()["c"]
            ),
            "review_log": int(
                connection.execute(
                    "SELECT COUNT(*) AS c FROM classification_review_log"
                ).fetchone()["c"]
            ),
            "audit": int(
                connection.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
            ),
        }


def test_retention_dry_run_reports_without_changing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed(tmp_path, monkeypatch)
    before = _counts()

    result = run_retention(now=NOW, dry_run=True)

    assert result["dry_run"] is True
    assert result["pipeline_job_inputs_deleted"] == 2
    assert result["pipeline_jobs_deleted"] == 1  # 4 jobs on old app, keep newest 3
    assert result["telemetry_deleted"] == {
        "ocr_route_events": 1,
        "classification_review_log": 1,
    }
    assert result["audit_log_deleted"] == 1  # only the old non-retained action
    assert result["applications_archived"] == 1
    assert result["source_keys_deleted"] == 0
    assert _counts() == before
    with get_connection() as connection:
        row = connection.execute(
            "SELECT archived_at FROM applications WHERE id = ?", (ids["old_app"],)
        ).fetchone()
        assert row["archived_at"] is None
    assert "reviewer_decision_made" in RETAINED_AUDIT_ACTIONS


def test_retention_real_run_deletes_and_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed(tmp_path, monkeypatch)

    result = run_retention(now=NOW, dry_run=False)

    assert result["pipeline_job_inputs_deleted"] == 2
    assert result["pipeline_jobs_deleted"] == 1
    assert result["telemetry_deleted"] == {
        "ocr_route_events": 1,
        "classification_review_log": 1,
    }
    assert result["audit_log_deleted"] == 1
    assert result["applications_archived"] == 1
    assert result["source_keys_deleted"] == 3

    after = _counts()
    assert after == {"inputs": 1, "jobs": 4, "route_events": 1, "review_log": 1, "audit": 2}

    with get_connection() as connection:
        archived = connection.execute(
            "SELECT archived_at FROM applications WHERE id = ?", (ids["old_app"],)
        ).fetchone()
        assert archived["archived_at"]
        fresh = connection.execute(
            "SELECT archived_at FROM applications WHERE id = ?", (ids["new_app"],)
        ).fetchone()
        assert fresh["archived_at"] is None
        remaining_jobs = connection.execute(
            "SELECT id FROM pipeline_jobs WHERE application_id = ? ORDER BY id",
            (ids["old_app"],),
        ).fetchall()
        assert len(remaining_jobs) == 3  # newest three kept
        audit_actions = [
            row["action"]
            for row in connection.execute("SELECT action FROM audit_log").fetchall()
        ]
        assert "reviewer_decision_made" in audit_actions  # user action retained
        assert "llm_summary_generated" in audit_actions  # recent telemetry retained

    store = get_store()
    assert not store.exists("applications/old/source/a.pdf")
    assert not store.exists("applications/old/source/a.zip")
    assert not store.exists("applications/old/normalized/a.pdf")
