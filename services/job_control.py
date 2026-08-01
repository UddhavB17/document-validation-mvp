"""Secure, cooperative control and recovery metadata for pipeline jobs."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken

from database import db
from database.db import get_connection


ControlAction = Literal["pause", "resume", "cancel"]
_ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "pause_requested", "paused"})
_SAFE_ENVIRONMENT_KEYS = (
    "OCR_PROVIDER",
    "DMEF_FULL_SCAN_OCR",
    "DMEF_MAX_SCANNED_OCR_PAGES",
    "ENABLE_LLM_SUMMARY",
    "LLM_PROVIDER",
    "LLM_MODEL",
)


class JobControlError(RuntimeError):
    """Raised when a requested job transition is invalid or unsafe."""


class JobInputUnavailableError(RuntimeError):
    """Raised when encrypted recovery inputs cannot be loaded safely."""


class PipelineCancelled(RuntimeError):
    """Cooperative signal used to stop a pipeline at a safe boundary."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet() -> Fernet:
    configured = os.getenv("DMEF_JOB_INPUT_KEY", "").strip()
    if configured:
        try:
            return Fernet(configured.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise JobInputUnavailableError(
                "DMEF_JOB_INPUT_KEY must be a valid Fernet key"
            ) from exc

    key_path = Path(
        os.getenv("DMEF_JOB_INPUT_KEY_FILE", str(db.DATABASE_PATH.parent / ".job_input.key"))
    )
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key = Fernet.generate_key()
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as key_file:
                key_file.write(key)
    try:
        os.chmod(key_path, 0o600)
        return Fernet(key_path.read_bytes().strip())
    except (OSError, ValueError) as exc:
        raise JobInputUnavailableError("Secure pipeline recovery key is unavailable") from exc


def _source_checksum(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_settings_snapshot() -> dict[str, Any]:
    """Capture reproducibility settings while excluding all secret values."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT config_key, config_value
            FROM system_settings
            WHERE value_type != 'secret'
            ORDER BY config_key
            """
        ).fetchall()
    return {
        "system_settings": {str(row["config_key"]): row["config_value"] for row in rows},
        "environment": {
            key: os.environ[key]
            for key in _SAFE_ENVIRONMENT_KEYS
            if key in os.environ
        },
    }


def persist_job_input(
    job_id: int,
    application_id: int,
    *,
    source_path: str | Path,
    system_data: dict[str, Any] | None,
    product_type: str,
    mapped_manifest: dict[str, Any] | None = None,
    package_id: str | None = None,
    generate_llm_summary: bool | None = None,
) -> None:
    """Encrypt the minimum complete payload required for an exact recovery run."""
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("Pipeline source file is unavailable")
    payload = {
        "source_path": str(source),
        "system_data": system_data or {},
        "product_type": product_type,
        "mapped_manifest": mapped_manifest,
        "package_id": package_id,
        "generate_llm_summary": generate_llm_summary,
        "settings_snapshot": safe_settings_snapshot(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = _fernet().encrypt(encoded).decode("ascii")
    checksum = _source_checksum(source)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO pipeline_job_inputs (
                job_id, application_id, encrypted_payload, source_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                encrypted_payload = excluded.encrypted_payload,
                source_sha256 = excluded.source_sha256,
                created_at = excluded.created_at
            """,
            (job_id, application_id, encrypted, checksum, _utc_now_iso()),
        )


def load_job_input(application_id: int, job_id: int | None = None) -> dict[str, Any]:
    """Decrypt and integrity-check the latest persisted recovery payload."""
    with get_connection() as connection:
        if job_id is None:
            row = connection.execute(
                """
                SELECT inputs.*
                FROM pipeline_job_inputs AS inputs
                JOIN pipeline_jobs AS jobs ON jobs.id = inputs.job_id
                WHERE inputs.application_id = ?
                ORDER BY jobs.attempt DESC, jobs.id DESC
                LIMIT 1
                """,
                (application_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM pipeline_job_inputs WHERE application_id = ? AND job_id = ?",
                (application_id, job_id),
            ).fetchone()
    if row is None:
        raise JobInputUnavailableError("No secure recovery payload is available")
    try:
        plaintext = _fernet().decrypt(str(row["encrypted_payload"]).encode("ascii"))
        payload = json.loads(plaintext)
    except (InvalidToken, UnicodeEncodeError, json.JSONDecodeError) as exc:
        raise JobInputUnavailableError("Recovery payload failed decryption") from exc
    source = Path(str(payload.get("source_path") or ""))
    if not source.is_file() or not secrets.compare_digest(
        _source_checksum(source), str(row["source_sha256"])
    ):
        raise JobInputUnavailableError("Recovery source file failed its integrity check")
    return payload


def request_control(application_id: int, action: ControlAction) -> dict[str, Any]:
    """Apply one validated control transition to the latest job."""
    now = _utc_now_iso()
    with get_connection() as connection:
        job = connection.execute(
            "SELECT * FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        if job is None:
            raise JobControlError("No pipeline job exists for this application")
        status = str(job["status"])
        control_state = str(job["control_state"] or "running")
        if action == "pause":
            if status not in {"queued", "running"} or control_state != "running":
                raise JobControlError(f"Cannot pause a job in state {status}/{control_state}")
            next_control, next_status = "pause_requested", "pause_requested"
        elif action == "resume":
            if status not in {"paused", "pause_requested"}:
                raise JobControlError(f"Cannot resume a job in state {status}")
            next_control, next_status = "running", "running"
        else:
            if status not in _ACTIVE_JOB_STATUSES:
                raise JobControlError(f"Cannot cancel a job in state {status}")
            next_control, next_status = "cancel_requested", "cancel_requested"
        progress_status = "processing" if action == "resume" else next_status
        progress_stage = "processing_pages" if action == "resume" else next_status
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET control_state = ?, status = ?, control_requested_at = ?
            WHERE id = ?
            """,
            (next_control, next_status, now, job["id"]),
        )
        connection.execute(
            """
            UPDATE pipeline_progress
            SET status = ?, stage = ?, message = ?, updated_at = ?
            WHERE application_id = ?
            """,
            (
                progress_status,
                progress_stage,
                f"Pipeline {action} requested",
                now,
                application_id,
            ),
        )
        connection.execute(
            "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
            (
                application_id,
                f"pipeline_{action}_requested",
                json.dumps({"job_id": int(job["id"]), "previous_status": status}),
            ),
        )
    return {"application_id": application_id, "job_id": int(job["id"]), "status": next_status}


def cooperate(job_id: int | None, application_id: int) -> None:
    """Heartbeat and honor pause/cancel requests between expensive operations."""
    if job_id is None:
        return
    paused_recorded = False
    while True:
        now = _utc_now_iso()
        cancelled = False
        with get_connection() as connection:
            job = connection.execute(
                "SELECT status, control_state FROM pipeline_jobs WHERE id = ? AND application_id = ?",
                (job_id, application_id),
            ).fetchone()
            if job is None:
                raise PipelineCancelled("Pipeline job no longer exists")
            control_state = str(job["control_state"] or "running")
            connection.execute(
                "UPDATE pipeline_jobs SET heartbeat_at = ? WHERE id = ?",
                (now, job_id),
            )
            if control_state == "cancel_requested":
                connection.execute(
                    """
                    UPDATE pipeline_jobs
                    SET status = 'cancelled', control_state = 'cancelled', completed_at = ?
                    WHERE id = ?
                    """,
                    (now, job_id),
                )
                connection.execute(
                    """
                    UPDATE pipeline_progress
                    SET status = 'cancelled', stage = 'cancelled', message = 'Pipeline cancelled',
                        completed_at = ?, updated_at = ?
                    WHERE application_id = ?
                    """,
                    (now, now, application_id),
                )
                connection.execute(
                    "UPDATE applications SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (application_id,),
                )
                connection.execute(
                    "UPDATE intake_packages SET status = 'cancelled' WHERE application_id = ? AND status = 'processing'",
                    (application_id,),
                )
                cancelled = True
            elif control_state in {"pause_requested", "paused"}:
                connection.execute(
                    "UPDATE pipeline_jobs SET status = 'paused', control_state = 'paused' WHERE id = ?",
                    (job_id,),
                )
                connection.execute(
                    """
                    UPDATE pipeline_progress
                    SET status = 'paused', stage = 'paused', message = 'Pipeline paused safely', updated_at = ?
                    WHERE application_id = ?
                    """,
                    (now, application_id),
                )
                if not paused_recorded:
                    connection.execute(
                        "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
                        (application_id, "pipeline_paused", json.dumps({"job_id": job_id})),
                    )
                    paused_recorded = True
            elif not cancelled:
                if paused_recorded:
                    connection.execute(
                        "INSERT INTO audit_log (application_id, action, details) VALUES (?, ?, ?)",
                        (application_id, "pipeline_resumed", json.dumps({"job_id": job_id})),
                    )
                return
        if cancelled:
            raise PipelineCancelled("Pipeline cancelled by request")
        time.sleep(0.25)


def mark_checkpoint(job_id: int | None, page_number: int) -> None:
    if job_id is None:
        return
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET last_completed_page = MAX(last_completed_page, ?), heartbeat_at = ?
            WHERE id = ?
            """,
            (page_number, _utc_now_iso(), job_id),
        )
