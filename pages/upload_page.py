"""Streamlit upload page."""

import os

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def render_upload_page() -> None:
    st.title("DMEF - Document Matching Early Finder")

    with st.form("upload_form"):
        loan_id = st.text_input("Loan ID")
        applicant_name = st.text_input("Applicant Name")
        coapplicant_name = st.text_input("Co-applicant Name")
        product_type = st.selectbox("Product Type", ["LAP", "MSME", "Personal Loan"])
        branch = st.text_input("Branch")
        uploaded_file = st.file_uploader("PDF file", type=["pdf"])
        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    if not loan_id.strip() or not applicant_name.strip() or not branch.strip():
        st.error("Loan ID, Applicant Name, and Branch are required.")
        return

    if uploaded_file is None:
        st.error("PDF file is required.")
        return

    with st.spinner("Validating file..."):
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
                timeout=60,
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
        f"File uploaded: {result['total_pages']} pages "
        f"({result['digital_pages']} digital pages + "
        f"{result['scanned_pages']} scanned pages)"
    )
