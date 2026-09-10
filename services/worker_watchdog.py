"""Lifespan watchdog: keep a worker alive while work is pending.

The API serves uploads and the UI, but only a worker process advances
jobs. If the worker dies (reboot, killed terminal, crash), jobs sit
`queued` and `/health` reports `worker: stale` — exactly the "processing
is stuck" state. This watchdog runs a daemon thread inside the API
process: every ``DMEF_WORKER_WATCHDOG_SECONDS`` (default 60) it checks for
active jobs with a stale heartbeat and, at most once per
``DMEF_WORKER_WATCHDOG_MIN_SPAWN_GAP_SECONDS`` (default 300), starts a
detached worker via ``services.worker_launcher`` (logs to
``data/logs/worker-*.log``).

Disabled automatically when ``DMEF_ENV=production`` (Cloud Run manages the
worker as its own service; a local spawn there would be wrong) unless
``DMEF_WORKER_WATCHDOG=1`` is set explicitly. Never raises.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_last_spawn_at: float = 0.0
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _watchdog_enabled() -> bool:
    from services.config import get_setting

    try:
        explicit = get_setting("DMEF_WORKER_WATCHDOG", "")
    except Exception:  # noqa: BLE001 - config unavailable; stay dormant
        return False
    if str(explicit or "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if str(explicit or "").strip().lower() in {"0", "false", "no", "off"}:
        return False
    try:
        env = str(get_setting("DMEF_ENV", "local") or "local").strip().lower()
    except Exception:  # noqa: BLE001 - config unavailable; stay dormant
        return False
    return env != "production"


def _watchdog_interval_seconds() -> float:
    from services.config import get_int

    try:
        return float(get_int("DMEF_WORKER_WATCHDOG_SECONDS", 60, minimum=15))
    except Exception:  # noqa: BLE001 - config unavailable; conservative pace
        return 60.0


def _min_spawn_gap_seconds() -> float:
    from services.config import get_int

    try:
        return float(get_int("DMEF_WORKER_WATCHDOG_MIN_SPAWN_GAP_SECONDS", 300, minimum=60))
    except Exception:  # noqa: BLE001 - config unavailable; conservative gap
        return 300.0


def _watchdog_once() -> None:
    """Single check-and-heal pass. Never raises."""
    global _last_spawn_at
    try:
        from services.worker_launcher import (
            ensure_worker_running,
            has_active_work,
            is_worker_alive,
        )

        if not has_active_work():
            return
        if is_worker_alive():
            return
        now = time.monotonic()
        if now - _last_spawn_at < _min_spawn_gap_seconds():
            return
        _last_spawn_at = now
        result = ensure_worker_running("watchdog: active jobs with stale heartbeat")
        logger.info("Worker watchdog pass: %s", result)
    except Exception:  # noqa: BLE001 - the watchdog must never break the API
        logger.warning("Worker watchdog pass failed", exc_info=True)


def _watchdog_loop(interval_seconds: float) -> None:
    while True:
        try:
            time.sleep(interval_seconds)
            if _watchdog_enabled():
                _watchdog_once()
        except Exception:  # noqa: BLE001 - daemon thread must not die
            logger.warning("Worker watchdog loop error", exc_info=True)


def start_worker_watchdog() -> bool:
    """Start the daemon watchdog thread once. Returns True when running."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        if not _watchdog_enabled():
            logger.info("Worker watchdog disabled (DMEF_ENV=production without opt-in)")
            return False
        _thread = threading.Thread(
            target=_watchdog_loop,
            args=(_watchdog_interval_seconds(),),
            name="dmef-worker-watchdog",
            daemon=True,
        )
        _thread.start()
        logger.info("Worker watchdog started")
        return True
