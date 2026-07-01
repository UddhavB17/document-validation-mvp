"""Shared Streamlit status helpers for application result rendering."""

from __future__ import annotations

import os
import time

import streamlit as st

from database.db import get_connection

PROCESSING_STATUSES = frozenset({"uploaded", "processing", "ocr_completed"})
FAILED_STATUSES = frozenset({"pipeline_failed"})
FINAL_STATUSES = frozenset({"CLEAN", "NEEDS_REVIEW", "CRITICAL", "verified", "verified_with_override", "incomplete"})
POLL_INTERVAL_SECONDS = int(os.getenv("DMEF_POLL_INTERVAL_SECONDS", "2"))
POLL_TIMEOUT_SECONDS = int(os.getenv("DMEF_PROCESSING_TIMEOUT_SECONDS", "900"))


def load_application_status(application_id: int) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
    return row["status"] if row else None


def get_result_state(status: str | None) -> str:
    if status is None:
        return "missing"
    if status in PROCESSING_STATUSES:
        return "processing"
    if status in FAILED_STATUSES:
        return "failed"
    if status in FINAL_STATUSES:
        return "ready"
    return "unknown"


def render_result_status_guard(
    application_id: int,
    *,
    session_key_prefix: str,
    processing_message: str,
    failed_message: str = "PDF processing failed. Open the Worklist or check logs for details.",
) -> bool:
    """Return True when result details can be safely rendered."""
    status = load_application_status(application_id)
    state = get_result_state(status)

    if state == "missing":
        return False

    if state == "processing":
        start_key = f"{session_key_prefix}_poll_started_at"
        start_time = st.session_state.setdefault(start_key, time.monotonic())
        elapsed_seconds = int(time.monotonic() - start_time)

        if elapsed_seconds >= POLL_TIMEOUT_SECONDS:
            st.warning("Processing is taking longer than expected. Please check Worklist again later.")
            return False

        st.info(f"{processing_message} Elapsed: {elapsed_seconds}s.")
        time.sleep(POLL_INTERVAL_SECONDS)
        st.rerun()
        return False

    st.session_state.pop(f"{session_key_prefix}_poll_started_at", None)

    if state == "failed":
        st.error(failed_message)
        return False

    if state == "unknown":
        st.info(f"Current status: {status}")
        return False

    return True
