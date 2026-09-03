"""Pipeline logging and per-page phase timing helpers."""

from __future__ import annotations

import logging
import sys
import time

from services.progress_tracker import mark_page_started

logger = logging.getLogger("dmef.pipeline")

_LOGGING_CONFIGURED = False


def _ensure_pipeline_logging() -> None:
    global _LOGGING_CONFIGURED
    if not _LOGGING_CONFIGURED and not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
            force=False,
        )
        _LOGGING_CONFIGURED = True
    logger.setLevel(logging.INFO)


def _log_page_phase_start(page_number: int, total_pages: int, phase: str) -> float:
    _ensure_pipeline_logging()
    logger.info("[Page %s/%s] Phase: %-22s started", page_number, total_pages, phase)
    _flush_log_handlers()
    return time.perf_counter()


def _log_page_phase_done(page_number: int, total_pages: int, phase: str, started_at: float) -> None:
    elapsed = time.perf_counter() - started_at
    logger.info("[Page %s/%s] Phase: %-22s done in %.2fs", page_number, total_pages, phase, elapsed)
    _flush_log_handlers()


def _log_page_phase_failed(
    page_number: int, total_pages: int, phase: str, started_at: float, exc: Exception
) -> None:
    elapsed = time.perf_counter() - started_at
    logger.exception(
        "[Page %s/%s] Phase: %-22s failed in %.2fs: %s",
        page_number,
        total_pages,
        phase,
        elapsed,
        exc,
    )
    _flush_log_handlers()


def _log_total_page_time(page_number: int, total_pages: int, started_at: float) -> float:
    elapsed = time.perf_counter() - started_at
    logger.info("[Page %s/%s] Total page time: %.2fs", page_number, total_pages, elapsed)
    _flush_log_handlers()
    return elapsed


def _flush_log_handlers() -> None:
    for handler in logger.handlers + logging.getLogger().handlers:
        handler.flush()


def _mark_page_phase(
    application_id: int | None,
    page_number: int,
    total_pages: int,
    phase: str,
) -> None:
    if application_id is None:
        return
    mark_page_started(
        application_id,
        current_page=page_number,
        total_pages=total_pages,
        message=f"Working on page {page_number}/{total_pages}: {phase}",
    )
