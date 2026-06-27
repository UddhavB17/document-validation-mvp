"""Streamlit reviewer worklist page."""

import pandas as pd
import streamlit as st

from database.db import get_connection


def render_worklist_page(items: list[dict] | None = None) -> None:
    st.subheader("Reviewer Worklist")
    applications = items or _load_worklist()
    status_filter = st.radio(
        "Filter",
        ["All", "Pending", "Needs Review", "Verified"],
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
            "Issues": item["issues"],
            "Uploaded": item["created_at"],
            "application_id": item["id"],
        }
        for item in filtered
    ]
    st.dataframe(pd.DataFrame(table_rows).drop(columns=["application_id"]), hide_index=True, use_container_width=True)

    selected_loan = st.selectbox("Open application", [row["Loan ID"] for row in table_rows])
    if st.button("Open Results"):
        selected = next(row for row in table_rows if row["Loan ID"] == selected_loan)
        st.session_state["application_id"] = selected["application_id"]
        st.session_state["page"] = "results"


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
                applications.created_at,
                COUNT(validation_results.id) AS issues
            FROM applications
            LEFT JOIN validation_results ON validation_results.application_id = applications.id
            GROUP BY applications.id
            ORDER BY applications.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _filter_applications(applications: list[dict], status_filter: str) -> list[dict]:
    if status_filter == "All":
        return applications
    if status_filter == "Pending":
        return [item for item in applications if item["status"] in {"uploaded", "ocr_completed"}]
    if status_filter == "Needs Review":
        return [item for item in applications if item["status"] in {"NEEDS_REVIEW", "CRITICAL"}]
    if status_filter == "Verified":
        return [item for item in applications if item["status"] in {"verified", "verified_with_override", "CLEAN"}]
    return applications
