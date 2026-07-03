"""Shared Streamlit status helpers for application result rendering."""

from __future__ import annotations

import json
import time

import streamlit as st

from database.db import get_connection
from services.config import get_int
from services.progress_tracker import get_progress

PROCESSING_STATUSES = frozenset({"uploaded", "processing", "ocr_completed"})
FAILED_STATUSES = frozenset({"pipeline_failed"})
FINAL_STATUSES = frozenset({"CLEAN", "NEEDS_REVIEW", "CRITICAL", "verified", "verified_with_override", "incomplete"})
POLL_INTERVAL_SECONDS = get_int("DMEF_POLL_INTERVAL_SECONDS", 2, minimum=1)
POLL_TIMEOUT_SECONDS = get_int("DMEF_PROCESSING_TIMEOUT_SECONDS", 900, minimum=30)

_PROCESSING_BANNER_CSS = """
<style>
.dmef-processing-banner {
    background: #e8f4fd;
    border: 1px solid #b6dff5;
    border-left: 5px solid #0284c7;
    border-radius: 10px;
    color: #0c4a6e;
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0.75rem 0 1rem 0;
    padding: 18px 20px;
}
.dmef-processing-text {
    display: inline-block;
}
.dmef-processing-dots {
    display: inline-block;
    min-width: 1.5em;
    text-align: left;
}
.dmef-processing-dots::after {
    animation: dmef-processing-dots 1.4s steps(4, end) infinite;
    content: "";
}
@keyframes dmef-processing-dots {
    0% { content: ""; }
    25% { content: "."; }
    50% { content: ".."; }
    75% { content: "..."; }
    100% { content: ""; }
}
</style>
"""


def load_application_status(application_id: int) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
    return row["status"] if row else None


def load_progress_summary(application_id: int) -> dict | None:
    return get_progress(application_id)


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


def render_processing_banner(message: str) -> None:
    """Show one stable processing notice with animated dots (no elapsed timer)."""
    st.markdown(
        _PROCESSING_BANNER_CSS
        + (
            '<div class="dmef-processing-banner">'
            '<span class="dmef-processing-text">'
            f"{message}"
            "</span>"
            '<span class="dmef-processing-dots"></span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_live_page_results(progress: dict, fallback_message: str) -> None:
    processed_pages = progress.get("processed_pages") or 0
    total_pages = progress.get("total_pages") or 0
    current_page = progress.get("last_processed_page")
    status_line = f"{fallback_message}: {processed_pages}/{total_pages} pages processed"
    if current_page:
        status_line += f" | working on page {current_page}"
    st.caption(status_line)
    if progress.get("percentage") is not None:
        st.progress(min(float(progress.get("percentage") or 0) / 100.0, 1.0))

    completed_pages = progress.get("completed_pages") or []
    if not completed_pages:
        st.info("Waiting for the first page result...")
        return

    rows = []
    for page in completed_pages:
        fields = page.get("extracted_fields") or {}
        rows.append(
            {
                "Page": page.get("page_number"),
                "Status": page.get("status"),
                "Type": page.get("page_type"),
                "Document": page.get("document_type") or "Unknown",
                "Time (s)": _format_elapsed(page.get("elapsed_seconds")),
                "Data": page.get("error") or _summarize_fields(fields),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


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

        progress = load_progress_summary(application_id)
        if progress:
            render_live_page_results(progress, processing_message)
        else:
            st.info(processing_message)
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


def _format_elapsed(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def _summarize_fields(fields: dict) -> str:
    public_fields = {
        key: value
        for key, value in fields.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return "-"
    compact = json.dumps(public_fields, ensure_ascii=False)
    return compact if len(compact) <= 180 else f"{compact[:177]}..."
