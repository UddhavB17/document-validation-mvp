"""Database-archive tests: DB rows -> object store JSON, never pruned."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import database.db as db
from database.db import get_connection, init_db
from services.db_archive import (
    ARCHIVE_PURPOSE,
    build_application_archive,
    export_application_archive,
    load_application_archive,
)
from services.retention import SOURCE_PURPOSES, run_retention
from services.storage import get_store

OLD = "2026-01-01 10:00:00"


def _fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    init_db()


def _seed_app(created_at: str = OLD) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO applications (loan_id, applicant_name, product_type, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("ARCH-1", "Asha Verma", "LAP", "completed", created_at),
        ).fetchone()
        app_id = int(row["id"])
        connection.execute(
            "INSERT INTO pages (application_id, page_number, document_type, ocr_text)"
            " VALUES (?, ?, ?, ?)",
            (app_id, 1, "PAN", "PAN number ABCDE1234F"),
        )
        connection.execute(
            "INSERT INTO validation_results (application_id, rule_id, reason) VALUES (?, ?, ?)",
            (app_id, "STATUS_CHECK_S7", "ok"),
        )
        connection.execute(
            "INSERT INTO reviewer_decisions (application_id, decision, reviewer_note)"
            " VALUES (?, ?, ?)",
            (app_id, "ACCEPT", "looks good"),
        )
    return app_id


def _seed_ref(app_id: int, purpose: str, key: str) -> None:
    get_store().put(key, b"payload-bytes", "application/pdf")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO object_refs
                (owner_table, owner_id, purpose, storage_key, content_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("applications", str(app_id), purpose, key, "application/pdf", 13, OLD),
        )


def _ref_exists(key: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS c FROM object_refs WHERE storage_key = ?", (key,)
        ).fetchone()
        return int(row["c"]) > 0


def test_build_archive_collects_rows_without_blob_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_db(tmp_path, monkeypatch)
    app_id = _seed_app()
    _seed_ref(app_id, "source", f"applications/{app_id}/source/file.pdf")

    envelope = build_application_archive(app_id)

    assert envelope["format"] == "dmef-db-archive/v1"
    assert envelope["application_id"] == app_id
    assert envelope["tables"]["applications"][0]["loan_id"] == "ARCH-1"
    assert envelope["tables"]["pages"][0]["ocr_text"] == "PAN number ABCDE1234F"
    assert envelope["tables"]["reviewer_decisions"][0]["decision"] == "ACCEPT"
    # object_refs travel as metadata (keys + purposes), never blob bytes.
    refs = envelope["tables"]["object_refs"]
    assert [ref["purpose"] for ref in refs] == ["source"]
    assert all("payload-bytes" not in json.dumps(ref) for ref in refs)
    json.dumps(envelope)  # fully JSON-serializable


def test_export_is_idempotent_and_reloadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_db(tmp_path, monkeypatch)
    app_id = _seed_app()

    first = export_application_archive(app_id)
    assert first["reused"] is False
    assert first["size_bytes"] and first["size_bytes"] > 0

    second = export_application_archive(app_id)
    assert second["reused"] is True
    assert second["storage_key"] == first["storage_key"]

    reloaded = load_application_archive(first["storage_key"])
    assert reloaded["format"] == "dmef-db-archive/v1"
    assert reloaded["tables"]["applications"][0]["loan_id"] == "ARCH-1"

    forced = export_application_archive(app_id, force=True)
    assert forced["reused"] is False


def test_retention_archives_db_before_pruning_and_never_deletes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_db(tmp_path, monkeypatch)
    app_id = _seed_app()
    _seed_ref(app_id, "source", f"applications/{app_id}/source/file.pdf")
    _seed_ref(app_id, "report", f"applications/{app_id}/report/report.xlsx")

    assert ARCHIVE_PURPOSE not in SOURCE_PURPOSES
    result = run_retention(now="2026-09-04T12:00:00+00:00", dry_run=False)

    assert result["applications_db_archived"] == 1
    assert result["db_archive_bytes"] > 0
    with get_connection() as connection:
        archive_keys = [
            row["storage_key"]
            for row in connection.execute(
                "SELECT storage_key FROM object_refs WHERE purpose = ?",
                (ARCHIVE_PURPOSE,),
            ).fetchall()
        ]
    assert len(archive_keys) == 1
    assert get_store().exists(archive_keys[0])
    # Source blob pruned, report and db_archive survive.
    assert not _ref_exists(f"applications/{app_id}/source/file.pdf")
    assert _ref_exists(f"applications/{app_id}/report/report.xlsx")
    assert _ref_exists(archive_keys[0])

    # Second run backfills nothing and prunes nothing new.
    rerun = run_retention(now="2026-09-04T12:00:00+00:00", dry_run=False)
    assert rerun["applications_db_archived"] == 0
