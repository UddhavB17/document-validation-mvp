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


def _insert_job(
    application_id: int,
    status: str,
    created_at: str,
    parent_job_id: int | None = None,
) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO pipeline_jobs (application_id, job_type, status, created_at)
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (application_id, "pdf_pipeline", status, created_at),
        ).fetchone()
        job_id = int(row["id"])
        if parent_job_id is not None:
            connection.execute(
                "UPDATE pipeline_jobs SET parent_job_id = ? WHERE id = ?",
                (parent_job_id, job_id),
            )
        return job_id


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
        # Realistic rows: single uploads store NULL file_path (keys live in
        # object_refs); intake path columns hold store keys (contracts §2).
        connection.execute(
            """
            INSERT INTO uploaded_files (application_id, file_path, original_filename)
            VALUES (?, ?, ?)
            """,
            (old_app, None, "a.pdf"),
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
        # --- fx-schema: real object_refs rows (retention reads these) ---
        connection.execute(
            """
            INSERT INTO object_refs
                (owner_table, owner_id, purpose, storage_key, content_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "applications", str(old_app), "source",
                "applications/old/source/a.pdf", "application/pdf", 9, OLD,
                "intake_packages", "pkg-old", "source",
                "applications/old/source/a.zip", "application/zip", 9, OLD,
                "intake_packages", "pkg-old", "normalized_pdf",
                "applications/old/normalized/a.pdf", "application/pdf", 9, OLD,
            ),
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
    # --- fx-schema: dry-run counts object_refs keys without deleting ---
    assert result["source_keys_deleted"] == 3
    assert _counts() == before
    with get_connection() as connection:
        row = connection.execute(
            "SELECT archived_at FROM applications WHERE id = ?", (ids["old_app"],)
        ).fetchone()
        assert row["archived_at"] is None
    assert "reviewer_decision_made" in RETAINED_AUDIT_ACTIONS
    # Dry-run must not delete store objects.
    store = get_store()
    assert store.exists("applications/old/source/a.pdf")
    assert store.exists("applications/old/source/a.zip")
    assert store.exists("applications/old/normalized/a.pdf")


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


def test_retention_parent_chain_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 4-job parent_job_id chain used to raise IntegrityError on delete."""
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "chain.db")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    init_db()

    app_id = _insert_application("CHAIN-1", OLD)
    job1 = _insert_job(app_id, "completed", OLD)
    job2 = _insert_job(app_id, "completed", OLD, parent_job_id=job1)
    job3 = _insert_job(app_id, "completed", OLD, parent_job_id=job2)
    job4 = _insert_job(app_id, "completed", OLD, parent_job_id=job3)

    # Sanity: chain is linked oldest -> newest.
    with get_connection() as connection:
        parents = {
            row["id"]: row["parent_job_id"]
            for row in connection.execute(
                "SELECT id, parent_job_id FROM pipeline_jobs WHERE application_id = ?",
                (app_id,),
            ).fetchall()
        }
    assert parents[job2] == job1
    assert parents[job3] == job2
    assert parents[job4] == job3

    result = run_retention(now=NOW, dry_run=False)

    assert result["pipeline_jobs_deleted"] == 1
    with get_connection() as connection:
        remaining = connection.execute(
            "SELECT id, parent_job_id FROM pipeline_jobs WHERE application_id = ? ORDER BY id",
            (app_id,),
        ).fetchall()
        remaining_ids = [int(row["id"]) for row in remaining]
        assert job1 not in remaining_ids
        assert remaining_ids == sorted(remaining_ids)
        assert len(remaining_ids) == 3
        # The child of the deleted parent was nulled instead of violating FK.
        by_id = {int(row["id"]): row["parent_job_id"] for row in remaining}
        assert by_id[job2] is None


def test_retention_counts_and_deletes_object_refs_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store objects recorded in object_refs are counted (dry-run) and deleted."""
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "refs.db")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    init_db()

    app_id = _insert_application("REFS-1", OLD)
    key = f"applications/{app_id}/source/doc.pdf"
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO object_refs
                (owner_table, owner_id, purpose, storage_key, content_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("applications", str(app_id), "source", key, "application/pdf", 4, OLD),
        )
    store = get_store()
    store.put(key, b"pdf-bytes", "application/pdf")
    assert store.exists(key)

    dry = run_retention(now=NOW, dry_run=True)
    assert dry["applications_archived"] == 1
    assert dry["source_keys_deleted"] == 1
    # Dry-run changes nothing.
    assert store.exists(key)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT archived_at FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["archived_at"] is None

    real = run_retention(now=NOW, dry_run=False)
    assert real["applications_archived"] == 1
    assert real["source_keys_deleted"] == 1
    assert not store.exists(key)


def test_retention_never_deletes_active_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queued/running/retrying jobs are never pruned even when over budget."""
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "active.db")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    init_db()

    app_id = _insert_application("ACTIVE-1", OLD)
    queued_oldest = _insert_job(app_id, "queued", OLD)
    _insert_job(app_id, "completed", OLD)
    _insert_job(app_id, "completed", OLD)
    _insert_job(app_id, "completed", OLD)

    result = run_retention(now=NOW, dry_run=False)

    # Only 3 terminal jobs exist; the queued job keeps the total at 4 but is
    # never a deletion candidate.
    assert result["pipeline_jobs_deleted"] == 0
    with get_connection() as connection:
        remaining = {
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM pipeline_jobs WHERE application_id = ?", (app_id,)
            ).fetchall()
        }
    assert queued_oldest in remaining
    assert len(remaining) == 4
