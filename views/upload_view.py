"""Streamlit upload view."""

import json
import os
import time

import requests
import streamlit as st

from database.db import get_connection
from services.file_validator import validate_upload
from views.results_view import render_application_results

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def render_upload_page() -> None:
    st.title("DMEF - Document Matching Early Finder")
    tab_upload, tab_json = st.tabs(["PDF Upload", "Partner JSON Intake"])

    with tab_upload:
        with st.form("upload_form"):
            loan_id = st.text_input("Loan ID")
            uploaded_file = st.file_uploader("PDF file", type=["pdf"])
            submitted = st.form_submit_button("Submit")

        if submitted:
            _submit_upload_form(loan_id, uploaded_file)

        _render_uploaded_application_result()

    with tab_json:
        st.subheader("Partner OCR JSON Payload")
        raw_json = st.text_area(
            "Paste JSON here",
            height=300,
            placeholder='{\n  "loan_id": "LN-001",\n  "digital_text": {},\n  "scanned_docs": {}\n}',
        )

        if st.button("Run Checklist Evaluation"):
            if not raw_json.strip():
                st.warning("Please paste the partner JSON first.")
            else:
                try:
                    payload = json.loads(raw_json)
                    st.success("JSON parsed successfully.")
                    st.json(payload)
                    st.info("Checklist evaluation will run after pipeline integration.")
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")


def _submit_upload_form(loan_id: str, uploaded_file) -> None:
    if not loan_id.strip():
        st.error("Loan ID is required.")
        return

    if uploaded_file is None:
        st.error("PDF file is required.")
        return

    validation = validate_upload(uploaded_file.name, file_size_bytes=uploaded_file.size)
    if not validation["is_valid"]:
        for error in validation["errors"]:
            st.error(error)
        return

    with st.spinner("Uploading file..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/upload",
                data={
                    "loan_id": loan_id,
                    "applicant_name": loan_id,
                    "coapplicant_name": "",
                    "product_type": "LAP",
                    "branch": "Default",
                },
                files={
                    "file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        "application/pdf",
                    )
                },
                timeout=180,
            )
        except requests.RequestException as exc:
            st.error(f"Upload failed: {exc}")
            return

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", "Upload failed")
        except ValueError:
            detail = response.text or "Upload failed"
        st.error(detail)
        return

    result = response.json()
    st.session_state["last_uploaded_application_id"] = result["application_id"]
    st.session_state["application_id"] = result["application_id"]
    st.success(
        "Application ID: "
        f"{result['application_id']} | "
        f"Status: {result['status']} | "
        f"Queued for processing: {result['total_pages']} pages "
        f"({result['digital_pages']} digital pages + "
        f"{result['scanned_pages']} scanned pages) | "
        "Results will appear below after processing completes."
    )


def _render_uploaded_application_result() -> None:
    application_id = st.session_state.get("last_uploaded_application_id")
    if application_id is None:
        return

    status = _load_application_status(int(application_id))
    if status is None:
        return

    st.divider()
    if status == "processing":
        st.info("PDF uploaded. Processing is still running...")
        time.sleep(2)
        st.rerun()
    if status == "pipeline_failed":
        st.error("PDF processing failed. Open the Worklist or check logs for details.")
        return

    st.success("PDF has been processed.")
    render_application_results(int(application_id))


def _load_application_status(application_id: int) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
    return row["status"] if row else None
