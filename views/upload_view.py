"""Streamlit upload view."""

import json
import os
import time

import requests
import streamlit as st

from services.file_validator import validate_package_upload, validate_upload
from views.results_view import render_application_results
from views.reviewer_view import render_result_status_guard, render_zip_preparation_progress

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
    tab_upload, tab_mapped, tab_json = st.tabs(
        ["PDF Upload", "Mapped Verification", "Partner JSON Intake"]
    )

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

    with tab_mapped:
        st.subheader("Trusted JSON + Page Mapping")
        st.caption(
            "Use this path when the company supplies trusted reference values and tells the system "
            "which documents belong to each person. A combined PDF can be mapped directly, or an "
            "unordered ZIP can first be normalized into stable internal page numbers."
        )
        mapped_source = st.radio(
            "Document source",
            ["Combined PDF", "Unordered ZIP"],
            horizontal=True,
            key="mapped_document_source",
        )
        if mapped_source == "Combined PDF":
            _render_combined_pdf_mapping()
        else:
            _render_zip_package_mapping()

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

    _render_uploaded_application_result()


def _render_combined_pdf_mapping() -> None:
    mapped_pdf = st.file_uploader("Mapped loan PDF", type=["pdf"], key="mapped_pdf")
    mapped_json = st.text_area(
        "Trusted manifest JSON",
        height=330,
        key="mapped_pdf_manifest_json",
        placeholder=_manifest_placeholder(),
    )
    if st.button("Run Deterministic Verification", type="primary", key="verify_mapped_pdf"):
        if mapped_pdf is None or not mapped_json.strip():
            st.warning("Select the PDF and paste the trusted manifest JSON.")
            return
        manifest_payload = _parse_manifest_text(mapped_json)
        if manifest_payload is not None:
            _submit_mapped_verification(mapped_pdf, manifest_payload)


def _render_zip_package_mapping() -> None:
    st.caption(
        "Upload the original ZIP. PDF, PNG, JPG and JPEG files are preserved as separate sources "
        "and assigned stable internal page ranges before OCR starts. XLSX worksheets are rendered "
        "into readable internal PDF pages."
    )
    zip_file = st.file_uploader("Loan document ZIP", type=["zip"], key="mapped_zip")
    if st.button("Prepare ZIP and Build Page Inventory", type="primary", key="prepare_mapped_zip"):
        if zip_file is None:
            st.warning("Select the ZIP package first.")
        else:
            _prepare_zip_package(zip_file)

    if st.session_state.get("preparing_zip_package_id"):
        package = _render_zip_preparation_status()
    else:
        package = st.session_state.get("prepared_zip_package")
    if not package:
        return

    metrics = st.columns(3)
    metrics[0].metric("Package", str(package["package_id"])[:8])
    metrics[1].metric("Source files", int(package["total_files"]))
    metrics[2].metric("Internal pages", int(package["total_pages"]))
    inventory = [
        {
            "source_document_id": item["source_document_id"],
            "original_filename": item["original_filename"],
            "type": item["file_type"],
            "worksheets": ", ".join(item.get("worksheets") or []),
            "pages": _page_range_label(item),
        }
        for item in package.get("documents") or []
    ]
    st.dataframe(inventory, width="stretch", hide_index=True)
    st.caption(
        "Use each source_document_id and its internal pages in document_index. A mapped page must "
        "remain inside that source file's displayed page range."
    )

    if "zip_manifest_json" not in st.session_state:
        st.session_state["zip_manifest_json"] = json.dumps(
            _package_manifest_template(package), indent=2
        )
    mapped_json = st.text_area(
        "Trusted manifest JSON for this ZIP",
        height=420,
        key="zip_manifest_json",
    )
    if st.button("Run ZIP Comparison Pipeline", type="primary", key="verify_mapped_zip"):
        manifest_payload = _parse_manifest_text(mapped_json)
        if manifest_payload is not None:
            _submit_zip_package_verification(str(package["package_id"]), manifest_payload)


def _manifest_placeholder() -> str:
    return (
        '{\n  "schema_version": "1.0",\n  "loan_id": "LN-001",\n'
        '  "people": {\n    "primary": {"applicant_name": "Ramesh Kumar", '
        '"aadhaar_number": "123456789012", "pan_number": "ABCDE1234F"}\n  },\n'
        '  "document_index": [\n'
        '    {"source_document_id": "file-0001", "person_id": "primary", '
        '"document_type": "Aadhaar", "pages": [1, 2]}\n  ]\n}'
    )


def _parse_manifest_text(raw_json: str) -> dict | None:
    if not raw_json.strip():
        st.warning("Paste the trusted manifest JSON first.")
        return None
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
        return None


def _page_range_label(document: dict) -> str:
    start = int(document["internal_page_start"])
    end = int(document["internal_page_end"])
    return str(start) if start == end else f"{start}-{end}"


def _package_manifest_template(package: dict) -> dict:
    return {
        "schema_version": "1.0",
        "loan_id": "REPLACE-WITH-LOAN-ID",
        "product_type": "LAP",
        "source": "manual_zip_mapping",
        "people": {
            "primary": {
                "role": "primary",
                "applicant_name": "REPLACE WITH APPLICANT NAME",
            }
        },
        "document_index": [
            {
                "source_document_id": document["source_document_id"],
                "document_type": "REPLACE WITH DOCUMENT TYPE",
                "person_id": "primary",
                "pages": document["pages"],
                "required": True,
            }
            for document in package.get("documents") or []
        ],
    }


def _prepare_zip_package(uploaded_file) -> None:
    validation = validate_package_upload(uploaded_file.name, file_size_bytes=uploaded_file.size)
    if not validation["is_valid"]:
        for error in validation["errors"]:
            st.error(error)
        return
    with st.spinner("Uploading ZIP package..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/upload/package",
                params={"background": "true"},
                files={
                    "file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        "application/zip",
                    )
                },
                timeout=300,
            )
        except requests.RequestException as exc:
            st.error(f"ZIP preparation failed: {exc}")
            return
    if response.status_code >= 400:
        st.error(_response_error_detail(response, "ZIP preparation failed"))
        return
    queued = response.json()
    st.session_state.pop("prepared_zip_package", None)
    st.session_state.pop("zip_manifest_json", None)
    st.session_state["preparing_zip_package_id"] = str(queued["package_id"])
    st.session_state["zip_preparation_started_at"] = time.monotonic()


def _render_zip_preparation_status() -> dict | None:
    """Poll once and rerun, matching the PDF upload live-processing UX."""
    package_id = str(st.session_state["preparing_zip_package_id"])
    try:
        response = requests.get(
            f"{API_BASE_URL}/upload/package/{package_id}/preparation",
            timeout=30,
        )
    except requests.RequestException as exc:
        st.warning(f"Waiting for ZIP preparation status: {exc}")
        time.sleep(2)
        st.rerun()
        return None

    if response.status_code == 503:
        st.info("ZIP preparation status is being updated...")
        time.sleep(1)
        st.rerun()
        return None
    if response.status_code >= 400:
        st.error(_response_error_detail(response, "Could not load ZIP preparation logs"))
        st.session_state.pop("preparing_zip_package_id", None)
        return None

    progress = response.json()
    render_zip_preparation_progress(progress)
    status = progress.get("status")
    if status == "prepared":
        st.session_state.pop("preparing_zip_package_id", None)
        st.session_state.pop("zip_preparation_started_at", None)
        st.session_state["prepared_zip_package"] = progress
        st.session_state["zip_manifest_json"] = json.dumps(
            _package_manifest_template(progress), indent=2
        )
        st.success(
            f"ZIP prepared: {progress['total_files']} source files became "
            f"{progress['total_pages']} stable internal pages."
        )
        return progress
    if status == "failed":
        st.error(str(progress.get("error") or "ZIP preparation failed"))
        st.session_state.pop("preparing_zip_package_id", None)
        return None

    started_at = float(st.session_state.get("zip_preparation_started_at") or time.monotonic())
    if time.monotonic() - started_at >= 900:
        st.warning("ZIP preparation is taking longer than expected; completed file logs remain visible.")
    time.sleep(2)
    st.rerun()
    return None


def _submit_zip_package_verification(package_id: str, manifest: dict) -> None:
    with st.spinner("Queueing ZIP documents through the shared PDF comparison pipeline..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/upload/package/{package_id}/verify",
                data={"manifest": json.dumps(manifest)},
                timeout=180,
            )
        except requests.RequestException as exc:
            st.error(f"ZIP verification failed: {exc}")
            return
    if response.status_code >= 400:
        st.error(_response_error_detail(response, "ZIP verification failed"))
        return
    result = response.json()
    application_id = int(result["application_id"])
    st.session_state["last_uploaded_application_id"] = application_id
    st.session_state["application_id"] = application_id
    st.session_state["last_upload_mode"] = "mapped_zip"
    st.success(
        f"Application {application_id} queued from {result.get('source_documents', 0)} ZIP files. "
        "Digital pages use native text, scanned pages use OCR, and every page is classified. "
        f"JSON comparison pages: {result.get('mapped_pages') or []}."
    )


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
    st.session_state["last_upload_mode"] = "pdf"
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


def _submit_mapped_verification(uploaded_file, manifest: dict) -> None:
    validation = validate_upload(uploaded_file.name, file_size_bytes=uploaded_file.size)
    if not validation["is_valid"]:
        for error in validation["errors"]:
            st.error(error)
        return

    with st.spinner("Uploading mapped pages for deterministic verification..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/upload/mapped",
                data={"manifest": json.dumps(manifest)},
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
            st.error(f"Mapped verification upload failed: {exc}")
            return

    if response.status_code >= 400:
        st.error(_response_error_detail(response, "Mapped verification upload failed"))
        return
    result = response.json()
    application_id = int(result["application_id"])
    st.session_state["last_uploaded_application_id"] = application_id
    st.session_state["application_id"] = application_id
    st.session_state["last_upload_mode"] = "mapped_pdf"
    st.success(
        f"Application {application_id} queued. "
        "Digital pages use native text, scanned pages use OCR, and every page is classified. "
        f"JSON comparison pages: {result.get('mapped_pages') or []}."
    )


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
    upload_mode = st.session_state.get("last_upload_mode")
    if upload_mode in {"mapped_zip", "mapped_pdf"}:
        st.subheader("Mapped Verification Output")
        st.caption(
            "Shared PDF pipeline: native text for digital pages, OCR only for scanned pages, "
            "LLM document classification, trusted JSON comparison, and the standard final report."
        )
        processing_message = "Processing and comparing your mapped loan file"
        completion_message = "Mapped verification and output generation complete."
    else:
        processing_message = "Processing your loan file"
        completion_message = "PDF processing complete."
    status_slot = st.empty()
    with status_slot.container():
        is_ready = render_result_status_guard(
            int(application_id),
            session_key_prefix=f"upload_{application_id}",
            processing_message=processing_message,
        )
    if not is_ready:
        return

    st.success(completion_message)
    render_application_results(int(application_id))
