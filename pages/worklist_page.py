"""Streamlit reviewer worklist page."""

import pandas as pd
import streamlit as st

from database.db import get_connection
from services.reviewer_exceptions import summarize_for_display
from views.results_view import render_application_results
from views.status_helpers import render_result_status_guard


def render_worklist_page(items: list[dict] | None = None) -> None:
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
    st.dataframe(pd.DataFrame(table_rows).drop(columns=["application_id"]), hide_index=True, use_container_width=True)

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
    pending = [item for item in applications if item["status"] in {"NEEDS_REVIEW", "CRITICAL", "ocr_completed", "checklist_run"}]
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


if __name__ == "__main__":
    render_worklist_page()
