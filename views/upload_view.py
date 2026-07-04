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
    st.markdown(
        """
        <div class="dmef-page-title">
            <h1>Document Intake</h1>
            <div class="dmef-caption">Upload a loan-file packet, watch page results finish, then review the final checklist output.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    tab_upload, tab_json = st.tabs(["PDF Upload", "Partner JSON Intake"])

    with tab_upload:
        with st.form("upload_form"):
            left, right = st.columns([1.15, 0.85])
            with left:
                st.subheader("Application Details")
                id_col, product_col = st.columns([1, 1])
                loan_id = id_col.text_input("Loan ID")
                product_type = product_col.selectbox("Product Type", ["LAP", "MSME", "Personal Loan"])
                applicant_name = st.text_input("Applicant Name")
                coapplicant_name = st.text_input("Co-applicant Name")
                branch = st.text_input("Branch")
            with right:
                st.subheader("Document")
                uploaded_file = st.file_uploader("PDF file", type=["pdf"])
                if uploaded_file is not None:
                    size_kb = uploaded_file.size / 1024
                    st.metric("Selected file size", f"{size_kb:,.0f} KB")
                    st.caption(uploaded_file.name)
                else:
                    st.info("Select one PDF loan packet to begin.")
            submitted = st.form_submit_button("Submit for processing", type="primary", width="stretch")

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

        if st.button("Run Checklist Evaluation", type="primary"):
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
    queued_cols = st.columns(4)
    queued_cols[0].metric("Application", result["application_id"])
    queued_cols[1].metric("Total pages", result["total_pages"])
    queued_cols[2].metric("Digital", result["digital_pages"])
    queued_cols[3].metric("Scanned", result["scanned_pages"])
    st.success("Upload accepted. Page-level results will appear below as processing completes.")


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
    status_slot = st.empty()
    with status_slot.container():
        is_ready = render_result_status_guard(
            int(application_id),
            session_key_prefix=f"upload_{application_id}",
            processing_message="Processing your loan file",
        )
    if not is_ready:
        return

    st.success("PDF processing complete.")
    render_application_results(int(application_id))
