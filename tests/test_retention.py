"""Retention coverage for ws-a (each action, dry-run True and False)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.retention import RETAINED_AUDIT_ACTIONS, run_retention
from services.storage import get_store

NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)
OLD = "2026-01-01 10:00:00"
NEW = "2026-09-01 10:00:00"
# Ten days before NOW: older than the default 7-day export window but younger
# than a 30-day window, so it distinguishes the two settings.
MID = "2026-08-25 12:00:00"


def _fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / name)
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    init_db()


def _insert_ref(
    owner_table: str,
    owner_id: int | str,
    purpose: str,
    storage_key: str,
    created_at: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO object_refs
                (owner_table, owner_id, purpose, storage_key, content_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_table, str(owner_id), purpose, storage_key, "application/pdf", 4, created_at),
        )


def _ref_count(storage_key: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS c FROM object_refs WHERE storage_key = ?",
            (storage_key,),
        ).fetchone()
        return int(row["c"])


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


def test_retention_preserves_account_and_pipeline_control_history(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch, "audit-history.db")
    actions = [
        "pipeline_pause_requested", "pipeline_cancel_requested", "pipeline_resume_requested",
        "pipeline_paused", "pipeline_resumed", "user_created", "password_changed",
        "user_deactivated", "user_deleted", "pipeline_reprocess_queued",
    ]
    with get_connection() as connection:
        for action in [*actions, "llm_summary_generated"]:
            connection.execute(
                "INSERT INTO audit_log (action, details, timestamp) VALUES (?, ?, ?)",
                (action, "{}", OLD),
            )

    assert run_retention(now=NOW, dry_run=True)["audit_log_deleted"] == 1
    assert run_retention(now=NOW, dry_run=False)["audit_log_deleted"] == 1
    with get_connection() as connection:
        remaining = {
            row["action"] for row in connection.execute("SELECT action FROM audit_log").fetchall()
        }
    assert remaining == set(actions)


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


def test_retention_expires_ocr_exports_after_seven_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expired ocr_export refs are deleted even for young applications."""
    _fresh_db(tmp_path, monkeypatch, "exports.db")
    app_id = _insert_application("EXP-1", NEW)
    old_key = f"applications/{app_id}/ocr-export.json"
    fresh_key = f"applications/{app_id}/ocr-export-fresh.json"
    _insert_ref("applications", app_id, "ocr_export", old_key, OLD)
    _insert_ref("applications", app_id, "ocr_export", fresh_key, NEW)
    store = get_store()
    store.put(old_key, b"{}", "application/json")
    store.put(fresh_key, b"{}", "application/json")

    dry = run_retention(now=NOW, dry_run=True)
    assert dry["ocr_exports_deleted"] == 1
    assert dry["applications_archived"] == 0  # young app is not archived
    assert store.exists(old_key)  # dry-run writes nothing
    assert _ref_count(old_key) == 1

    real = run_retention(now=NOW, dry_run=False)
    assert real["ocr_exports_deleted"] == 1
    assert not store.exists(old_key)
    assert _ref_count(old_key) == 0
    # The fresh export survives with its row intact.
    assert store.exists(fresh_key)
    assert _ref_count(fresh_key) == 1


def test_retention_export_window_env_is_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DMEF_RETENTION_EXPORT_DAYS controls the ocr_export expiry age."""
    _fresh_db(tmp_path, monkeypatch, "export-days.db")
    app_id = _insert_application("EXPDAYS-1", NEW)
    key = f"applications/{app_id}/ocr-export.json"
    _insert_ref("applications", app_id, "ocr_export", key, MID)
    store = get_store()
    store.put(key, b"{}", "application/json")

    assert run_retention(now=NOW, dry_run=True)["ocr_exports_deleted"] == 1
    monkeypatch.setenv("DMEF_RETENTION_EXPORT_DAYS", "30")
    assert run_retention(now=NOW, dry_run=True)["ocr_exports_deleted"] == 0
    assert store.exists(key)


def test_retention_regenerated_export_refreshes_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-recording an export restarts its expiry window (clock independent)."""
    _fresh_db(tmp_path, monkeypatch, "refresh.db")
    app_id = _insert_application("REFRESH-1", NEW)
    key = f"applications/{app_id}/ocr-export.json"
    _insert_ref("applications", app_id, "ocr_export", key, OLD)

    from services.retention import _parse_ts
    from services.storage.refs import record_ref

    record_ref("applications", app_id, "ocr_export", key,
               content_type="application/json", size_bytes=2)
    store = get_store()
    store.put(key, b"{}", "application/json")
    with get_connection() as connection:
        created_raw = connection.execute(
            "SELECT created_at FROM object_refs WHERE storage_key = ?",
            (key,),
        ).fetchone()["created_at"]
    refreshed = _parse_ts(created_raw)
    assert refreshed is not None and refreshed > _parse_ts(OLD)

    # Three days after regeneration the export is kept...
    assert (
        run_retention(now=refreshed + timedelta(days=3), dry_run=False)[
            "ocr_exports_deleted"
        ]
        == 0
    )
    assert store.exists(key)
    # ...and eight days after regeneration it expires.
    assert (
        run_retention(now=refreshed + timedelta(days=8), dry_run=False)[
            "ocr_exports_deleted"
        ]
        == 1
    )
    assert not store.exists(key)


def test_retention_failed_source_delete_is_retried_then_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed store deletion keeps its row (retry) and success removes it."""
    _fresh_db(tmp_path, monkeypatch, "retry.db")
    app_id = _insert_application("RETRY-1", OLD)
    key = f"applications/{app_id}/source/doc.pdf"
    _insert_ref("applications", app_id, "source", key, OLD)

    import services.retention as retention_mod

    real_store = get_store()
    real_store.put(key, b"pdf-bytes", "application/pdf")
    state = {"fail": True}
    original_delete = real_store.delete

    def flaky_delete(storage_key: str) -> None:
        if state["fail"]:
            state["fail"] = False
            raise OSError("simulated store outage")
        return original_delete(storage_key)

    monkeypatch.setattr(real_store, "delete", flaky_delete)
    monkeypatch.setattr(retention_mod, "get_store", lambda: real_store)

    first = run_retention(now=NOW, dry_run=False)
    assert first["source_keys_deleted"] == 0
    assert real_store.exists(key)
    assert _ref_count(key) == 1  # row retained for a future retry

    # Dry-run reports the retry candidate without writing anything.
    dry = run_retention(now=NOW, dry_run=True)
    assert dry["source_keys_deleted"] == 1
    assert dry["applications_archived"] == 0  # already archived above
    assert real_store.exists(key)
    assert _ref_count(key) == 1

    second = run_retention(now=NOW, dry_run=False)
    assert second["source_keys_deleted"] == 1
    assert not real_store.exists(key)
    assert _ref_count(key) == 0  # row removed: later runs are idempotent

    third = run_retention(now=NOW, dry_run=False)
    assert third["source_keys_deleted"] == 0
    assert third["ocr_exports_deleted"] == 0


@pytest.mark.parametrize(
    "status", ["queued", "running", "retrying", "paused", "stale", "cancelled"]
)
def test_retention_active_job_blocks_source_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """Old applications with resumable jobs keep source/normalized/manifest."""
    _fresh_db(tmp_path, monkeypatch, f"active-src-{status}.db")
    app_id = _insert_application("ACTSRC-1", OLD)
    _insert_job(app_id, status, OLD)
    source_key = f"applications/{app_id}/source/doc.pdf"
    normalized_key = f"applications/{app_id}/normalized/doc.pdf"
    export_key = f"applications/{app_id}/ocr-export.json"
    _insert_ref("applications", app_id, "source", source_key, OLD)
    _insert_ref("applications", app_id, "normalized_pdf", normalized_key, OLD)
    _insert_ref("applications", app_id, "ocr_export", export_key, OLD)
    store = get_store()
    for candidate in (source_key, normalized_key, export_key):
        store.put(candidate, b"x", "application/pdf")

    dry = run_retention(now=NOW, dry_run=True)
    assert dry["applications_archived"] == 1
    assert dry["source_keys_deleted"] == 0
    assert dry["ocr_exports_deleted"] == 1  # exports expire on their own age

    real = run_retention(now=NOW, dry_run=False)
    assert real["source_keys_deleted"] == 0
    assert real["ocr_exports_deleted"] == 1
    with get_connection() as connection:
        archived = connection.execute(
            "SELECT archived_at FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert archived["archived_at"]  # archiving itself still happens
    assert store.exists(source_key)
    assert store.exists(normalized_key)
    assert _ref_count(source_key) == 1
    assert _ref_count(normalized_key) == 1
    assert not store.exists(export_key)
