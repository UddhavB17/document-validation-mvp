"""Local worker supervision: launch a detached worker with file logs.

The pipeline only advances while a worker process is alive. On laptops and
the pilot box the worker is an ordinary background process that can die
with a reboot, a killed terminal, or a crash — leaving jobs `queued` and
`/health` reporting `worker: stale`. This module is the single place that
(1) checks liveness via the heartbeat, (2) asks whether any work is
pending, and (3) starts a detached worker whose stdout/stderr go to
``data/logs/worker-out.log`` / ``worker-err.log`` so the next crash leaves
a traceback instead of silence.

Used by the lifespan watchdog (``services/worker_watchdog.py``), the admin
``POST /admin/worker/start`` endpoint, and ``run_worker.ps1`` documents the
same layout for manual starts. Never raises: every helper returns a status
dict or False on failure.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Job states that mean "there is work for a worker to do".
ACTIVE_JOB_STATUSES = ("queued", "running", "retrying")

#: Log files for supervisor-spawned workers (also used by run_worker.ps1).
WORKER_OUT_LOG = "worker-out.log"
WORKER_ERR_LOG = "worker-err.log"


def repo_root() -> Path:
    """Return the repository root (parent of ``services/``)."""
    return Path(__file__).resolve().parents[1]


def worker_log_dir() -> Path:
    """Return (creating) the directory for worker log files."""
    log_dir = repo_root() / "data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - caller falls back to console output
        pass
    return log_dir


def is_worker_alive() -> bool:
    """True when the worker heartbeat is fresh (see ``/health``)."""
    try:
        from database.worker_heartbeat import get_heartbeat

        return bool(get_heartbeat().get("status") == "ok")
    except Exception:  # noqa: BLE001 - fail closed: treat as not alive
        logger.warning("Worker liveness check failed; assuming not alive", exc_info=True)
        return False


def has_active_work() -> bool:
    """True when any job is queued/running/retrying and could advance."""
    try:
        from database.db import get_connection

        placeholders = ",".join("?" for _ in ACTIVE_JOB_STATUSES)
        with get_connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM pipeline_jobs WHERE status IN ({placeholders})",
                ACTIVE_JOB_STATUSES,
            ).fetchone()
        return int(row["total"]) > 0
    except Exception:  # noqa: BLE001 - fail closed: assume nothing to do
        logger.warning("Active-work check failed; assuming idle", exc_info=True)
        return False


def ensure_worker_running(reason: str) -> dict[str, Any]:
    """Start a detached worker when none is alive; otherwise no-op.

    Returns ``{"started": bool, ...}`` and never raises. ``reason`` is
    logged (admin panel, watchdog) for auditability.
    """
    if is_worker_alive():
        return {"started": False, "detail": "worker heartbeat is fresh"}
    try:
        log_dir = worker_log_dir()
        out_path = log_dir / WORKER_OUT_LOG
        err_path = log_dir / WORKER_ERR_LOG
        out_file = open(out_path, "ab")  # noqa: PTH123 - intentional append
        try:
            err_file = open(err_path, "ab")  # noqa: PTH123 - intentional append
        except Exception:
            out_file.close()
            raise
        popen_kwargs: dict[str, Any] = {
            "cwd": str(repo_root()),
            "stdout": out_file,
            "stderr": err_file,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "services.worker"],
                **popen_kwargs,
            )
        finally:
            # The child keeps its own inherited handles; close the parent's.
            out_file.close()
            err_file.close()
        logger.info(
            "Worker supervisor started worker pid=%s reason=%s logs=%s",
            proc.pid,
            reason,
            out_path,
        )
        return {
            "started": True,
            "pid": int(proc.pid),
            "reason": reason,
            "out_log": str(out_path),
            "err_log": str(err_path),
        }
    except Exception as exc:  # noqa: BLE001 - report, never crash the caller
        logger.warning("Worker supervisor failed to start worker: %s", exc, exc_info=True)
        return {"started": False, "detail": f"spawn failed: {exc}"}
