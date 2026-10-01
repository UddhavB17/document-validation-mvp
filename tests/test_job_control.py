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


def test_job_control_endpoint_requires_configured_token(tmp_path, monkeypatch, auth_headers) -> None:
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_CONTROL_TOKEN", "control-secret")
    application_id, job_id, _ = _seed_job(tmp_path)
    with get_connection() as connection:
        connection.execute("UPDATE pipeline_jobs SET status = 'running' WHERE id = ?", (job_id,))
    client = TestClient(app)

    assert client.post(f"/review/applications/{application_id}/pause").status_code == 401
    assert (
        client.post(
            f"/review/applications/{application_id}/pause", headers=auth_headers
        ).status_code
        == 403
    )
    response = client.post(
        f"/review/applications/{application_id}/pause",
        headers={**auth_headers, "X-Job-Control-Token": "control-secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pause_requested"


def test_load_job_input_restores_store_bytes_after_source_deleted(
    tmp_path, monkeypatch
) -> None:
    """Deleted upload work dir still loads via the object store (BLOCK 1)."""
    import hashlib

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("DMEF_STORAGE_BACKEND", raising=False)
    application_id, job_id, source = _seed_job(tmp_path)
    pdf_bytes = source.read_bytes()

    from services.storage import get_store
    from services.storage.refs import record_ref

    store_key = f"applications/{application_id}/source/source.pdf"
    get_store().put(store_key, pdf_bytes, "application/pdf")
    record_ref(
        "applications",
        application_id,
        "source",
        store_key,
        content_type="application/pdf",
        size_bytes=len(pdf_bytes),
    )
    persist_job_input(
        job_id, application_id, source_path=source, system_data={}, product_type="LAP"
    )
    source.unlink()
    assert not source.exists()

    recovered = load_job_input(application_id, job_id)
    restored = Path(str(recovered["source_path"]))
    assert restored.is_file()
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == hashlib.sha256(
        pdf_bytes
    ).hexdigest()


@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("delete_source", [False, True])
def test_pipeline_task_preserves_source_integrity_and_cleans_failed_staging(
    tmp_path, monkeypatch, mapped, delete_source
) -> None:
    from services.pipeline import tasks
    from services.pipeline.input_preparation import job_source_dir
    from services.storage import get_store
    from services.storage.refs import record_ref

    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "dmef.db")
    monkeypatch.setenv("DMEF_JOB_INPUT_KEY_FILE", str(tmp_path / "recovery.key"))
    monkeypatch.setenv("DMEF_LOCAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "local")
    application_id, job_id, source = _seed_job(tmp_path)
    verified_bytes = source.read_bytes()
    persist_job_input(
        job_id,
        application_id,
        source_path=source,
        system_data={},
        product_type="LAP",
        mapped_manifest={} if mapped else None,
    )
    store_key = f"applications/{application_id}/source/a.pdf"
    get_store().put(store_key, b"changed after enqueue", "application/pdf")
    record_ref(
        "applications", application_id, "source", store_key, content_type="application/pdf"
    )
    observed = []

    def capture_input(_job_id, file_path, *_args, **_kwargs):
        observed.append(Path(file_path).read_bytes())
        return {"pipeline_status": "completed"}

    monkeypatch.setattr(tasks, "_do_pipeline_work", capture_input)
    run = tasks.run_mapped_job if mapped else tasks.run_pipeline_job
    if delete_source:
        source.unlink()
        with pytest.raises(JobInputUnavailableError, match="integrity"):
            run(job_id)
        assert observed == []
    else:
        assert run(job_id)["pipeline_status"] == "completed"
        assert observed == [verified_bytes]
        assert source.read_bytes() == verified_bytes
    assert not job_source_dir(job_id).exists()


def test_cleanup_job_source_is_idempotent_and_preserves_other_jobs(tmp_path, monkeypatch) -> None:
    from services.pipeline.input_preparation import cleanup_job_source

    work_root = tmp_path / "jobs"
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(work_root))
    first = work_root / "job-1" / "source.pdf"
    sibling = work_root / "job-2" / "source.pdf"
    for source in (first, sibling):
        source.parent.mkdir(parents=True)
        source.write_bytes(b"staged source")

    cleanup_job_source(first)
    assert not first.parent.exists()
    assert sibling.read_bytes() == b"staged source"

    # Task and worker finalizers may both clean the same job directory.
    cleanup_job_source(first.parent)
    assert sibling.read_bytes() == b"staged source"


@pytest.mark.parametrize("relative_path", [".", "source.pdf", "missing-job", "missing-job/source.pdf"])
def test_cleanup_job_source_never_removes_shared_work_root(
    tmp_path, monkeypatch, relative_path
) -> None:
    from services.pipeline.input_preparation import cleanup_job_source

    work_root = tmp_path / "jobs"
    monkeypatch.setenv("DMEF_JOB_WORK_DIR", str(work_root))
    sibling = work_root / "job-2" / "source.pdf"
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b"another job")
    (work_root / "source.pdf").write_bytes(b"unscoped source")

    cleanup_job_source(work_root / relative_path)

    assert sibling.read_bytes() == b"another job"
    assert (work_root / "source.pdf").read_bytes() == b"unscoped source"


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
