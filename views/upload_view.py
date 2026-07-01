"""Streamlit upload view."""

import json
import os

import requests
import streamlit as st

from services.file_validator import validate_upload
from views.results_view import render_application_results
from views.status_helpers import render_result_status_guard

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
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
                else:
                    _submit_partner_json(payload)


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

    with st.spinner("Uploading file..."):
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
        st.error(_response_error_detail(response, "Upload failed"))
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


def _submit_partner_json(payload: dict) -> None:
    with st.spinner("Running checklist evaluation..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/upload/json",
                json=payload,
                timeout=180,
            )
        except requests.RequestException as exc:
            st.error(f"Partner JSON upload failed: {exc}")
            return

    if response.status_code >= 400:
        st.error(_response_error_detail(response, "Partner JSON upload failed"))
        return

    result = response.json()
    application_id = result["application_id"]
    st.session_state["last_uploaded_application_id"] = application_id
    st.session_state["application_id"] = application_id
    st.success(
        "Application ID: "
        f"{application_id} | "
        f"Status: {result['status']} | "
        f"Issues found: {result.get('anomaly_count', 0)}"
    )
    st.write(f"Documents found: {', '.join(result.get('documents_found') or []) or 'None'}")
    render_application_results(int(application_id))


def _response_error_detail(response: requests.Response, fallback: str) -> str:
    try:
        detail = response.json().get("detail", fallback)
    except ValueError:
        detail = response.text or fallback
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    return str(detail)


def _render_uploaded_application_result() -> None:
    application_id = st.session_state.get("last_uploaded_application_id")
    if application_id is None:
        return

    st.divider()
    is_ready = render_result_status_guard(
        int(application_id),
        session_key_prefix=f"upload_{application_id}",
        processing_message="PDF uploaded. Processing is still running...",
    )
    if not is_ready:
        return

    st.success("PDF has been processed.")
    render_application_results(int(application_id))
