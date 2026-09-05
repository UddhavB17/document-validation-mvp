"""Secure, cooperative control and recovery metadata for pipeline jobs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken

from database import db
from database.db import get_connection

logger = logging.getLogger(__name__)

# Secret settings in ``system_settings`` are stored with this prefix followed
# by the Fernet token, so reads can tell ciphertext apart from legacy
# plaintext rows left behind before encryption at rest landed.
SECRET_VALUE_PREFIX = "enc:fernet:"

# Primary env var for the Fernet key that encrypts both pipeline recovery
# payloads and secret settings. ``DMEF_JOB_INPUT_KEY`` is the deprecated
# alias and is only honoured with a warning.
SECRETS_KEY_ENV = "DMEF_SECRETS_KEY"
DEPRECATED_SECRETS_KEY_ENV = "DMEF_JOB_INPUT_KEY"

_in_memory_fernet_key: bytes | None = None

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
    return datetime.now(UTC).isoformat()


def _configured_key_material() -> tuple[bytes | None, str]:
    """Return ``(key_bytes, source)`` from env or an existing key file.

    ``source`` names where the key came from for error messages. Returns
    ``(None, "")`` when nothing is configured.
    """
    configured = os.getenv(SECRETS_KEY_ENV, "").strip()
    if configured:
        try:
            Fernet(configured.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise JobInputUnavailableError(
                f"{SECRETS_KEY_ENV} must be a valid Fernet key"
            ) from exc
        return configured.encode("ascii"), SECRETS_KEY_ENV
    legacy = os.getenv(DEPRECATED_SECRETS_KEY_ENV, "").strip()
    if legacy:
        logger.warning(
            "%s is deprecated; set %s instead",
            DEPRECATED_SECRETS_KEY_ENV,
            SECRETS_KEY_ENV,
        )
        try:
            Fernet(legacy.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise JobInputUnavailableError(
                f"{DEPRECATED_SECRETS_KEY_ENV} must be a valid Fernet key"
            ) from exc
        return legacy.encode("ascii"), DEPRECATED_SECRETS_KEY_ENV

    explicit_file = os.getenv("DMEF_JOB_INPUT_KEY_FILE", "").strip()
    if explicit_file:
        key_path = Path(explicit_file)
        if key_path.exists():
            try:
                os.chmod(key_path, 0o600)
                return key_path.read_bytes().strip(), "DMEF_JOB_INPUT_KEY_FILE"
            except (OSError, ValueError) as exc:
                raise JobInputUnavailableError(
                    "Secure pipeline recovery key is unavailable"
                ) from exc
        if not _is_production():
            key = Fernet.generate_key()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as key_file:
                    key_file.write(key)
            return key, "DMEF_JOB_INPUT_KEY_FILE"
        return None, ""

    # Never auto-generate under the default data/ location. An existing legacy
    # key file is still honoured so older checkouts keep decrypting.
    default_path = Path(db.DATABASE_PATH.parent / ".job_input.key")
    if default_path.exists():
        try:
            os.chmod(default_path, 0o600)
            return default_path.read_bytes().strip(), "default key file"
        except (OSError, ValueError) as exc:
            raise JobInputUnavailableError(
                "Secure pipeline recovery key is unavailable"
            ) from exc
    return None, ""


def _is_production() -> bool:
    return os.getenv("DMEF_ENV", "").strip().lower() == "production"


def ensure_secrets_key() -> bytes:
    """Validate secrets-key configuration; fail fast in production.

    Returns the raw Fernet key bytes. When no key is configured and
    ``DMEF_ENV=production``, raises ``RuntimeError`` with a clear message so
    startup fails instead of silently running unencrypted. Outside production
    an ephemeral in-memory key is generated once per process and a warning is
    logged (in-memory means recovery payloads and secrets do not survive a
    restart — set ``DMEF_SECRETS_KEY`` for anything durable).
    """
    configured, _source = _configured_key_material()
    if configured:
        return configured
    if _is_production():
        raise RuntimeError(
            "DMEF_ENV=production requires DMEF_SECRETS_KEY to be set to a valid "
            "Fernet key (generate one with "
            "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`). "
            "Refusing to start without encrypted secrets at rest."
        )
    global _in_memory_fernet_key
    if _in_memory_fernet_key is None:
        _in_memory_fernet_key = Fernet.generate_key()
        logger.warning(
            "No DMEF_SECRETS_KEY configured; using an ephemeral in-memory key. "
            "Set DMEF_SECRETS_KEY for durable encryption."
        )
    return _in_memory_fernet_key


def secrets_fernet() -> Fernet:
    """Return a Fernet instance backed by :func:`ensure_secrets_key`."""
    try:
        return Fernet(ensure_secrets_key())
    except (ValueError, UnicodeEncodeError) as exc:
        raise JobInputUnavailableError("Configured secrets key is not a valid Fernet key") from exc


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret setting value for storage."""
    return SECRET_VALUE_PREFIX + secrets_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(stored: str) -> str:
    """Decrypt a stored secret setting value (raises ``InvalidToken`` if bad)."""
    token = stored[len(SECRET_VALUE_PREFIX):] if stored.startswith(SECRET_VALUE_PREFIX) else stored
    return secrets_fernet().decrypt(token.encode("ascii")).decode("utf-8")


def is_encrypted_secret(stored: str) -> bool:
    """Return True when a stored value carries the Fernet envelope prefix."""
    return stored.startswith(SECRET_VALUE_PREFIX)


def _fernet() -> Fernet:
    return secrets_fernet()


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
            key: os.environ[key] for key in _SAFE_ENVIRONMENT_KEYS if key in os.environ
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
    resume: bool = False,
    refresh_cached_ocr: bool = False,
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
        "resume": resume,
        "refresh_cached_ocr": refresh_cached_ocr,
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


def persist_job_input_or_fail(
    job_id: int,
    application_id: int,
    *,
    source_path: str | Path,
    system_data: dict[str, Any] | None,
    product_type: str,
    mapped_manifest: dict[str, Any] | None = None,
    package_id: str | None = None,
    generate_llm_summary: bool | None = None,
    resume: bool = False,
    refresh_cached_ocr: bool = False,
) -> None:
    """Persist recovery input, or mark the queued job/application failed and re-raise."""
    try:
        persist_job_input(
            job_id,
            application_id,
            source_path=source_path,
            system_data=system_data,
            product_type=product_type,
            mapped_manifest=mapped_manifest,
            package_id=package_id,
            generate_llm_summary=generate_llm_summary,
            resume=resume,
            refresh_cached_ocr=refresh_cached_ocr,
        )
    except Exception as exc:
        from services.progress_tracker import mark_failed, mark_job_failed

        error = f"Failed to persist recovery input: {exc}"
        mark_job_failed(job_id, error)
        mark_failed(application_id, error)
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET status = ? WHERE id = ?",
                ("failed", application_id),
            )
        raise


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


def restart_job(application_id: int) -> dict[str, Any]:
    """Reset the latest job for a fresh run: attempt=0, queued, no failure reason."""
    now = _utc_now_iso()
    with get_connection() as connection:
        job = connection.execute(
            "SELECT * FROM pipeline_jobs WHERE application_id = ? ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        if job is None:
            raise JobControlError("No pipeline job exists for this application")
        connection.execute(
            """
            UPDATE pipeline_jobs
            SET status = 'queued', control_state = 'running', attempt = 0,
                failure_reason = NULL, error = NULL, next_run_at = NULL,
                control_requested_at = ?, heartbeat_at = ?
            WHERE id = ?
            """,
            (now, now, job["id"]),
        )
    return {"application_id": application_id, "job_id": int(job["id"]), "status": "queued"}


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
            SET last_completed_page = CASE
                    WHEN last_completed_page > ? THEN last_completed_page
                    ELSE ?
                END,
                heartbeat_at = ?
            WHERE id = ?
            """,
            (page_number, page_number, _utc_now_iso(), job_id),
        )
