"""Reviewer worklist, activity page, and shared result-status UI."""

from __future__ import annotations

import json
import time

import pandas as pd
import streamlit as st

from database.db import get_connection
from services.config import get_int
from services.progress_tracker import get_progress
from services.reviewer import summarize_for_display

PROCESSING_STATUSES = frozenset({"uploaded", "processing", "ocr_completed"})
FAILED_STATUSES = frozenset({"pipeline_failed"})
FINAL_STATUSES = frozenset({"CLEAN", "NEEDS_REVIEW", "CRITICAL", "verified", "verified_with_override", "incomplete"})
POLL_INTERVAL_SECONDS = get_int("DMEF_POLL_INTERVAL_SECONDS", 2, minimum=1)
POLL_TIMEOUT_SECONDS = get_int("DMEF_PROCESSING_TIMEOUT_SECONDS", 900, minimum=30)

_PROCESSING_BANNER_CSS = """
<style>
.dmef-processing-banner {
    background: #132033;
    border: 1px solid #28415f;
    border-left: 5px solid #60a5fa;
    border-radius: 6px;
    color: #dbeafe;
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
    progress_message = str(progress.get("message") or "").strip()
    status_line = f"{fallback_message}: {processed_pages}/{total_pages} pages processed"
    if current_page:
        status_line += f" | working on page {current_page}"
    if progress_message:
        status_line += f" | {progress_message}"

    completed_pages = progress.get("completed_pages") or []
    if not completed_pages:
        render_processing_loading(progress, status_line)
        return

    st.markdown("### Page Processing")
    st.caption(status_line)
    if progress.get("percentage") is not None:
        st.progress(min(float(progress.get("percentage") or 0) / 100.0, 1.0))
    _render_processing_metrics(progress, completed_pages)
    render_page_processing_table(completed_pages)


def render_processing_loading(progress: dict, status_line: str) -> None:
    st.markdown("### Page Processing")
    st.caption(status_line)
    if progress.get("percentage") is not None:
        st.progress(min(float(progress.get("percentage") or 0) / 100.0, 1.0))
    render_processing_banner(status_line)


def render_page_processing_table(completed_pages: list[dict]) -> None:
    rows = []
    for page in completed_pages:
        fields = page.get("extracted_fields") or {}
        status = str(page.get("status") or "completed")
        rows.append(
            {
                "Page": page.get("page_number"),
                "Status": _status_label(status),
                "Type": page.get("page_type"),
                "Document": page.get("document_type") or "Unknown",
                "LLM Document": _llm_document_label(fields),
                "Time (s)": _format_elapsed(page.get("elapsed_seconds")),
                "Data": page.get("error") or _summarize_fields(fields),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


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

        progress = load_progress_summary(application_id)
        if progress:
            render_live_page_results(progress, processing_message)
        else:
            st.info(processing_message)
        if elapsed_seconds >= POLL_TIMEOUT_SECONDS:
            st.warning("Processing is taking longer than expected. Already received page results remain visible here.")
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


def _llm_document_label(fields: dict) -> str:
    llm_result = fields.get("_structured_llm_classification") if isinstance(fields, dict) else None
    if not isinstance(llm_result, dict):
        return "-"
    document_type = str(llm_result.get("document_type") or "").strip()
    if not document_type:
        return "-"
    confidence = llm_result.get("confidence")
    try:
        return f"{document_type} ({float(confidence):.0%})"
    except (TypeError, ValueError):
        return document_type


def _summarize_fields(fields: dict) -> str:
    visible_markers = {
        key: fields.get(key)
        for key in ("review_flag", "content_category")
        if fields.get(key) not in (None, "", [], {})
    }
    if visible_markers:
        return json.dumps(visible_markers, ensure_ascii=False)

    public_fields = {
        key: value
        for key, value in fields.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return "-"
    compact = json.dumps(public_fields, ensure_ascii=False)
    return compact if len(compact) <= 180 else f"{compact[:177]}..."


def _render_processing_metrics(progress: dict, completed_pages: list[dict]) -> None:
    total_pages = int(progress.get("total_pages") or 0)
    completed_count = len(completed_pages)
    failed_count = len([page for page in completed_pages if str(page.get("status") or "").lower() == "error"])
    elapsed_values = [
        float(page.get("elapsed_seconds") or 0)
        for page in completed_pages
        if page.get("elapsed_seconds") not in (None, "")
    ]
    avg_seconds = sum(elapsed_values) / len(elapsed_values) if elapsed_values else 0
    columns = st.columns(4)
    columns[0].metric("Completed", f"{completed_count}/{total_pages or '-'}")
    columns[1].metric("Failed pages", failed_count)
    columns[2].metric("Avg page time", f"{avg_seconds:.2f}s" if elapsed_values else "-")
    columns[3].metric("ETA", _format_eta(progress.get("eta_seconds")))


def _format_eta(value: object) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0:
        return "Done"
    minutes, remaining = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {remaining}s"
    return f"{remaining}s"


def _status_label(status: str) -> str:
    normalized = status.lower()
    if normalized == "error":
        return "Error"
    if normalized == "skipped":
        return "Skipped"
    return "Completed"


def render_worklist_page(items: list[dict] | None = None) -> None:
    from views.results_view import render_application_results

    st.subheader("Reviewer Worklist")
    applications = items or _load_worklist()

    queue_col, _ = st.columns([1, 3])
    if queue_col.button("Start Review Queue", type="primary"):
        pending = _queue_candidates(applications)
        if not pending:
            st.warning("No files waiting for review.")
        else:
            st.session_state["queue"] = [item["id"] for item in pending]
            st.session_state["queue_index"] = 0
            st.session_state["worklist_application_id"] = pending[0]["id"]
            st.rerun()

    status_filter = st.radio(
        "Filter",
        ["All", "Pending", "Needs Review", "Auto Clean", "Verified"],
        horizontal=True,
    )
    filtered = _filter_applications(applications, status_filter)

    if not filtered:
        st.info("No applications found.")
        return

    table_rows = [
        {
            "Loan ID": item["loan_id"],
            "Applicant": item["applicant_name"],
            "Product": item["product_type"],
            "Status": item["status"],
            "Issues": item["reviewer_issues"],
            "Uploaded": item["created_at"],
            "application_id": item["id"],
        }
        for item in filtered
    ]
    st.dataframe(pd.DataFrame(table_rows).drop(columns=["application_id"]), hide_index=True, width="stretch")

    selected_loan = st.selectbox("Open application", [row["Loan ID"] for row in table_rows])
    if st.button("Show Results"):
        selected = next(row for row in table_rows if row["Loan ID"] == selected_loan)
        st.session_state["worklist_application_id"] = selected["application_id"]

    selected_application_id = st.session_state.get("worklist_application_id")
    if selected_application_id is not None:
        st.divider()
        is_ready = render_result_status_guard(
            int(selected_application_id),
            session_key_prefix=f"worklist_{selected_application_id}",
            processing_message="Processing your loan file",
        )
        if not is_ready:
            return
        render_application_results(int(selected_application_id))


def _queue_candidates(applications: list[dict]) -> list[dict]:
    pending = [
        item
        for item in applications
        if item["status"] in {"NEEDS_REVIEW", "CRITICAL", "ocr_completed", "checklist_run"}
    ]
    return sorted(pending, key=lambda item: item["created_at"])


def _load_worklist() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                applications.id,
                applications.loan_id,
                applications.applicant_name,
                applications.product_type,
                applications.status,
                applications.created_at
            FROM applications
            ORDER BY applications.created_at DESC
            """
        ).fetchall()

    applications = []
    for row in rows:
        item = dict(row)
        with get_connection() as connection:
            anomalies = connection.execute(
                "SELECT severity, rule_id, page_number, reason, document_type, expected_value, found_value FROM validation_results WHERE application_id = ?",
                (item["id"],),
            ).fetchall()
        summary = summarize_for_display([dict(anomaly) for anomaly in anomalies])
        item["issues"] = summary["raw_count"]
        item["reviewer_issues"] = summary["reviewer_count"]
        applications.append(item)
    return applications


def _filter_applications(applications: list[dict], status_filter: str) -> list[dict]:
    if status_filter == "All":
        return applications
    if status_filter == "Pending":
        return [item for item in applications if item["status"] in {"uploaded", "processing", "ocr_completed"}]
    if status_filter == "Needs Review":
        return [item for item in applications if item["status"] in {"NEEDS_REVIEW", "CRITICAL"}]
    if status_filter == "Auto Clean":
        return [item for item in applications if item["status"] == "CLEAN"]
    if status_filter == "Verified":
        return [item for item in applications if item["status"] in {"verified", "verified_with_override"}]
    return applications


def render_activity_page() -> None:
    st.subheader("My Activity")
    st.caption("Decisions recorded today")

    summary = _load_today_summary()
    if not summary["rows"]:
        st.info("No reviewer decisions recorded today.")
        return

    columns = st.columns(4)
    columns[0].metric("Files reviewed today", summary["total"])
    columns[1].metric("Accepted", summary["accepted"])
    columns[2].metric("Overridden", summary["overridden"])
    columns[3].metric("Sent back", summary["sent_back"])

    chart_data = pd.DataFrame(
        [
            {"Decision": "Accepted", "Count": summary["accepted"]},
            {"Decision": "Overridden", "Count": summary["overridden"]},
            {"Decision": "Sent back", "Count": summary["sent_back"]},
        ]
    )
    if summary["total"] > 0:
        st.bar_chart(chart_data.set_index("Decision"))

    st.dataframe(pd.DataFrame(summary["rows"]), hide_index=True, width="stretch")


def _load_today_summary() -> dict:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                reviewer_decisions.id,
                reviewer_decisions.application_id,
                applications.loan_id,
                reviewer_decisions.decision,
                reviewer_decisions.decided_at
            FROM reviewer_decisions
            JOIN applications ON applications.id = reviewer_decisions.application_id
            WHERE date(reviewer_decisions.decided_at) = date('now', 'localtime')
            ORDER BY reviewer_decisions.decided_at DESC
            """
        ).fetchall()

    decision_rows = [dict(row) for row in rows]
    accepted = sum(1 for row in decision_rows if row["decision"] == "ACCEPT")
    overridden = sum(1 for row in decision_rows if row["decision"] == "OVERRIDE")
    sent_back = sum(1 for row in decision_rows if row["decision"] == "REQUEST_DOCS")

    return {
        "total": len(decision_rows),
        "accepted": accepted,
        "overridden": overridden,
        "sent_back": sent_back,
        "rows": decision_rows,
    }
