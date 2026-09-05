from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import database.db as db
from database.db import get_connection, init_db
from main import app
from services.job_control import (
    JobInputUnavailableError,
    PipelineCancelled,
    cooperate,
    load_job_input,
    persist_job_input,
    persist_job_input_or_fail,
    request_control,
)
from services.pipeline import _build_page_records
from services.progress_tracker import create_pipeline_job, start_tracking


def _seed_job(tmp_path: Path) -> tuple[int, int, Path]:
    init_db()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"stable source bytes")
    with get_connection() as connection:
        application_id = int(
            connection.execute(
                "INSERT INTO applications (loan_id, status) VALUES ('SECURE-001', 'processing') RETURNING id"
            ).fetchone()["id"]
        )
    start_tracking(application_id, total_pages=2)
    return application_id, create_pipeline_job(application_id), source


def test_recovery_payload_is_encrypted_and_secret_settings_are_excluded(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    application_id, job_id, source = _seed_job(tmp_path)
    with get_connection() as connection:
        connection.execute(
            "UPDATE system_settings SET config_value = 'do-not-persist' WHERE config_key = 'google.vision.api_key'"
        )

    persist_job_input(
        job_id,
        application_id,
        source_path=source,
        system_data={"pan_number": "ABCDE1234F"},
        product_type="LAP",
    )

    with get_connection() as connection:
        encrypted = connection.execute(
            "SELECT encrypted_payload FROM pipeline_job_inputs WHERE job_id = ?", (job_id,)
        ).fetchone()["encrypted_payload"]
    assert "ABCDE1234F" not in encrypted
    assert "do-not-persist" not in encrypted
    recovered = load_job_input(application_id, job_id)
    assert recovered["system_data"]["pan_number"] == "ABCDE1234F"
    assert "google.vision.api_key" not in recovered["settings_snapshot"]["system_settings"]
    import os

    if os.name != "nt":
        assert (tmp_path / "recovery.key").stat().st_mode & 0o777 == 0o600


def test_recovery_rejects_modified_source_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    application_id, job_id, source = _seed_job(tmp_path)
    persist_job_input(
        job_id,
        application_id,
        source_path=source,
        system_data={},
        product_type="LAP",
    )
    source.write_bytes(b"tampered")

    with pytest.raises(JobInputUnavailableError, match="integrity"):
        load_job_input(application_id, job_id)


def test_pause_resume_and_cancel_transitions_are_audited(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    application_id, job_id, _ = _seed_job(tmp_path)
    with get_connection() as connection:
        connection.execute("UPDATE pipeline_jobs SET status = 'running' WHERE id = ?", (job_id,))

    assert request_control(application_id, "pause")["status"] == "pause_requested"
    assert request_control(application_id, "resume")["status"] == "running"
    assert request_control(application_id, "cancel")["status"] == "cancel_requested"

    with pytest.raises(PipelineCancelled):
        cooperate(job_id, application_id)
    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, control_state FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        actions = {
            row["action"]
            for row in connection.execute(
                "SELECT action FROM audit_log WHERE application_id = ?", (application_id,)
            ).fetchall()
        }
    assert dict(job) == {"status": "cancelled", "control_state": "cancelled"}
    assert {
        "pipeline_pause_requested",
        "pipeline_resume_requested",
        "pipeline_cancel_requested",
    }.issubset(actions)


def test_persist_job_input_failure_marks_job_and_application_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    application_id, job_id, source = _seed_job(tmp_path)
    source.unlink()

    with pytest.raises(FileNotFoundError):
        persist_job_input_or_fail(
            job_id,
            application_id,
            source_path=source,
            system_data={"loan_id": "SECURE-001"},
            product_type="LAP",
        )

    with get_connection() as connection:
        job = connection.execute(
            "SELECT status, control_state FROM pipeline_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        application = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        progress = connection.execute(
            "SELECT status FROM pipeline_progress WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    assert dict(job) == {"status": "failed", "control_state": "failed"}
    assert application["status"] == "failed"
    assert progress["status"] == "failed"


def test_job_control_endpoint_requires_configured_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_CONTROL_TOKEN", "control-secret")
    application_id, job_id, _ = _seed_job(tmp_path)
    with get_connection() as connection:
        connection.execute("UPDATE pipeline_jobs SET status = 'running' WHERE id = ?", (job_id,))
    client = TestClient(app)

    assert client.post(f"/review/applications/{application_id}/pause").status_code == 403
    response = client.post(
        f"/review/applications/{application_id}/pause",
        headers={"X-Job-Control-Token": "control-secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pause_requested"


def test_page_builder_skips_completed_checkpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "local")
    monkeypatch.setenv("DMEF_LOCAL_OCR_TEST_MODE", "true")
    import services.config as config_mod
    import services.ocr_router as ocr_router_mod

    real_get_setting = config_mod.get_setting

    def _get_setting(key: str, default=None):
        if key == "ocr.provider":
            return "local"
        return real_get_setting(key, default)

    monkeypatch.setattr(config_mod, "get_setting", _get_setting)
    monkeypatch.setattr(ocr_router_mod, "get_setting", _get_setting)
    calls: list[str] = []

    def fake_ocr(image_path: str) -> dict:
        calls.append(image_path)
        return {
            "ocr_text": "Permanent Account Number ABCDE1234F",
            "is_readable": True,
            "confidence": 0.95,
        }

    monkeypatch.setattr("services.pipeline.page_processing.run_ocr_on_page", fake_ocr)
    structure = [
        {"page_number": 1, "page_type": "scanned", "image_path": "page_1.png"},
        {"page_number": 2, "page_type": "scanned", "image_path": "page_2.png"},
    ]
    checkpoint = {
        "page_number": 1,
        "page_type": "scanned",
        "image_path": "page_1.png",
        "ocr_text": "already processed",
        "document_type": "PAN",
        "classification_confidence": 0.99,
        "detected_page_number": 1,
        "extracted_fields": {},
    }

    pages = _build_page_records(structure, {}, checkpoint_pages=[checkpoint])

    assert calls == ["page_2.png"]
    assert pages[0]["ocr_text"] == "already processed"
