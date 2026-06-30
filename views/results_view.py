"""Streamlit results page."""

import os

import pandas as pd
import requests
import streamlit as st

from database.db import get_connection
from services.checklist_service import get_ai_checkable_items, get_human_review_items
from services.report_generator import generate_excel_report

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def render_results_page(exceptions: list[dict] | None = None, llm_summary: str = "", loan_id: str = "") -> None:
    st.subheader("Validation Results")
    if loan_id:
        st.caption(f"Loan ID: {loan_id}")
    if llm_summary:
        st.info(llm_summary)
    st.dataframe(exceptions or [], use_container_width=True)


def render_application_results(application_id: int) -> None:
    data = _load_application_result(application_id)
    if not data:
        st.error("Application not found.")
        return

    application = data["application"]
    product_type = application.get("product_type") or "LAP"
    ground_truth = data["ground_truth"]
    anomalies = _sort_anomalies(data["anomalies"])
    pages = data["pages"]

    st.title(f"Loan File Review - {application['loan_id']}")
    _render_ground_truth(ground_truth, application)
    _render_summary(application, data, anomalies, pages, product_type)

    if application.get("llm_summary"):
        st.subheader("AI Analysis")
        st.info(application["llm_summary"])

    st.subheader("Anomalies")
    if anomalies:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Severity": anomaly.get("severity"),
                        "Document": anomaly.get("document_type"),
                        "Expected": anomaly.get("expected_value"),
                        "Found": anomaly.get("found_value"),
                        "Page": anomaly.get("page_number"),
                        "Reason": anomaly.get("reason"),
                    }
                    for anomaly in anomalies
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("No issues detected")

    manual_confirmed = _render_manual_review(product_type)
    _render_document_checklist(data)
    _render_pages_requiring_review(anomalies)
    _render_download(application_id)
    _render_reviewer_decision(application_id, application.get("status"), manual_confirmed)


def _render_ground_truth(ground_truth: dict, application: dict) -> None:
    st.subheader("Ground Truth")
    columns = st.columns(5)
    values = [
        ("Applicant Name", ground_truth.get("applicant_name") or application.get("applicant_name")),
        ("PAN", ground_truth.get("pan_number")),
        ("Loan Amount", ground_truth.get("loan_amount")),
        ("Branch", application.get("branch")),
        ("Product", application.get("product_type")),
    ]
    for column, (label, value) in zip(columns, values):
        column.metric(label, value or "-")


def _render_summary(application: dict, data: dict, anomalies: list[dict], pages: list[dict], product_type: str) -> None:
    uploaded_file = data["uploaded_file"]
    ai_items = get_ai_checkable_items(product_type)
    manual_items = get_human_review_items(product_type)
    failed_ai_snos = {anomaly.get("s_no") for anomaly in anomalies if anomaly.get("s_no") is not None}
    ai_passed = len([item for item in ai_items if item.get("s_no") not in failed_ai_snos])

    st.subheader("Summary")
    columns = st.columns(4)
    columns[0].metric("Total Pages", uploaded_file.get("total_pages") or len(pages))
    columns[1].metric("Digital Pages", uploaded_file.get("digital_pages") or "-")
    columns[2].metric("Scanned Pages", uploaded_file.get("scanned_pages") or "-")
    columns[3].metric("Issues Found", len(anomalies))

    st.write(f"Documents found: {len(data['documents_found'])} of {len(ai_items)} AI-checkable items")
    st.write(f"AI checked items: {ai_passed} of {len(ai_items)} passed")
    st.write(f"Manual review items: {len(manual_items)} items need human check")

    status = application.get("status")
    if status == "CLEAN":
        st.success("Final status: CLEAN")
    elif status == "CRITICAL":
        st.error("Final status: CRITICAL")
    elif status == "NEEDS_REVIEW":
        st.warning("Final status: NEEDS_REVIEW")
    else:
        st.info(f"Current status: {status}")


def _render_document_checklist(data: dict) -> None:
    st.subheader("Documents Checklist")
    found_col, missing_col = st.columns(2)
    found_rows = [
        {"Document": document, "Pages": ", ".join(map(str, data["document_pages"].get(document, [])))}
        for document in data["documents_found"]
    ]
    missing = sorted(set(data["documents_missing"]))

    with found_col:
        st.write("Found documents")
        st.dataframe(pd.DataFrame(found_rows), hide_index=True, use_container_width=True)
    with missing_col:
        st.write("Missing documents")
        if missing:
            st.error(", ".join(missing))
        else:
            st.success("None")


def _render_manual_review(product_type: str) -> bool:
    manual_items = get_human_review_items(product_type)
    st.subheader("Manual Review Required")
    st.warning("Items requiring manual verification (cannot be checked automatically)")
    if manual_items:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "S.No": item.get("s_no"),
                        "Item Description": item.get("description"),
                        "Why manual review needed": item.get("reason"),
                    }
                    for item in manual_items
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    return st.checkbox("I confirm I have manually verified all items in the above list")


def _render_pages_requiring_review(anomalies: list[dict]) -> None:
    page_numbers = sorted({anomaly.get("page_number") for anomaly in anomalies if anomaly.get("page_number")})
    st.subheader("Pages Requiring Review")
    if page_numbers:
        st.warning(f"Review these pages: {', '.join(map(str, page_numbers))}")
    else:
        st.success("All pages clean")


def _render_download(application_id: int) -> None:
    if st.button("Download Anomaly Report (Excel)"):
        try:
            report_path = generate_excel_report(application_id)
            with open(report_path, "rb") as report_file:
                st.download_button(
                    "Download Anomaly Report (Excel)",
                    data=report_file,
                    file_name=report_path.split("/")[-1],
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        except Exception as exc:
            st.error(f"Report generation failed: {exc}")


def _render_reviewer_decision(application_id: int, status: str | None, manual_confirmed: bool) -> None:
    if status in {"verified", "verified_with_override", "incomplete"}:
        st.success("Reviewer decision already submitted.")
        return

    st.subheader("Reviewer Decision")
    decision = st.radio("Decision", ["ACCEPT", "OVERRIDE", "REQUEST_DOCS"], horizontal=True, disabled=not manual_confirmed)
    reviewer_note = st.text_area("Reviewer Note", disabled=not manual_confirmed)
    if st.button("Confirm Decision", disabled=not manual_confirmed):
        if len(reviewer_note.strip()) <= 10:
            st.error("Reviewer note must be more than 10 characters.")
            return
        response = requests.post(
            f"{API_BASE_URL}/decision",
            json={"application_id": application_id, "decision": decision, "reviewer_note": reviewer_note},
            timeout=30,
        )
        if response.status_code >= 400:
            st.error(response.json().get("detail", "Decision failed"))
        else:
            st.success("Reviewer decision saved.")


def _load_application_result(application_id: int) -> dict | None:
    with get_connection() as connection:
        application = connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if application is None:
            return None
        uploaded_file = connection.execute(
            "SELECT * FROM uploaded_files WHERE application_id = ? ORDER BY uploaded_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        ground_truth = connection.execute(
            "SELECT * FROM ground_truth WHERE application_id = ? ORDER BY extracted_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        anomalies = connection.execute("SELECT * FROM validation_results WHERE application_id = ?", (application_id,)).fetchall()
        pages = connection.execute("SELECT * FROM pages WHERE application_id = ? ORDER BY page_number", (application_id,)).fetchall()

    page_dicts = [dict(row) for row in pages]
    document_pages: dict[str, list[int]] = {}
    for page in page_dicts:
        doc_type = page.get("document_type")
        if doc_type and doc_type != "Unknown":
            document_pages.setdefault(doc_type, []).append(page.get("page_number"))

    anomaly_dicts = [dict(row) for row in anomalies]
    return {
        "application": dict(application),
        "uploaded_file": dict(uploaded_file) if uploaded_file else {},
        "ground_truth": dict(ground_truth) if ground_truth else {},
        "anomalies": anomaly_dicts,
        "pages": page_dicts,
        "documents_found": sorted(document_pages),
        "document_pages": document_pages,
        "documents_missing": [
            anomaly.get("document_type")
            for anomaly in anomaly_dicts
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC") and anomaly.get("document_type")
        ],
    }


def _sort_anomalies(anomalies: list[dict]) -> list[dict]:
    return sorted(
        anomalies,
        key=lambda anomaly: (
            SEVERITY_ORDER.get(str(anomaly.get("severity", "LOW")).upper(), 3),
            anomaly.get("page_number") or 10**9,
        ),
    )
