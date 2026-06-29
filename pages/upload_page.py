"""Streamlit upload page."""

import json
import os

import requests
import streamlit as st

from services.file_validator import validate_upload

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def render_upload_page() -> None:
    st.title("DMEF - Document Matching Early Finder")
    tab_upload, tab_json = st.tabs(["PDF Upload", "Partner JSON Intake"])

    with tab_upload:
        with st.form("upload_form"):
            loan_id = st.text_input("Loan ID")
            applicant_name = st.text_input("Applicant Name")
            coapplicant_name = st.text_input("Co-applicant Name")
            product_type = st.selectbox("Product Type", ["LAP", "MSME", "Personal Loan"])
            branch = st.text_input("Branch")
            uploaded_file = st.file_uploader("PDF file", type=["pdf"])
            submitted = st.form_submit_button("Submit")

        if submitted:
            _submit_upload_form(
                loan_id,
                applicant_name,
                coapplicant_name,
                product_type,
                branch,
                uploaded_file,
            )

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


def _submit_upload_form(
    loan_id: str,
    applicant_name: str,
    coapplicant_name: str,
    product_type: str,
    branch: str,
    uploaded_file,
) -> None:
    if not loan_id.strip() or not applicant_name.strip() or not branch.strip():
        st.error("Loan ID, Applicant Name, and Branch are required.")
        return

    if uploaded_file is None:
        st.error("PDF file is required.")
        return

    validation = validate_upload(uploaded_file.name, file_size_bytes=uploaded_file.size)
    if not validation["is_valid"]:
        for error in validation["errors"]:
            st.error(error)
        return

    with st.spinner("Uploading and processing file..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/upload",
                data={
                    "loan_id": loan_id,
                    "applicant_name": applicant_name,
                    "coapplicant_name": coapplicant_name,
                    "product_type": product_type,
                    "branch": branch,
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
    st.success(
        "Application ID: "
        f"{result['application_id']} | "
        f"Status: {result['status']} | "
        f"Processed: {result['total_pages']} pages "
        f"({result['digital_pages']} digital pages + "
        f"{result['scanned_pages']} scanned pages) | "
        f"Issues found: {result.get('anomaly_count', 0)}"
    )
