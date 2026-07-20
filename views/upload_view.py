"""Streamlit upload view."""

import json
import os
import time

import requests
import streamlit as st

from services.file_validator import validate_package_upload, validate_upload
from services.company_dump_adapter import (
    CompanyDumpConversionError,
    convert_company_database_dump,
    is_company_database_dump,
)
from views.results_view import render_application_results
from views.reviewer_view import render_result_status_guard, render_zip_preparation_progress

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def render_upload_page() -> None:
    st.markdown(
        """
        <div class="dmef-page-title">
            <h1>Document Intake</h1>
            <div class="dmef-caption">Upload a loan-file packet with trusted reference data, then review the automatic verification output.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Automatic Verification")
    st.caption(
        "Supply trusted reference values only. The system identifies the document type on every "
        "PDF page, groups continuation pages, infers the applicant or co-applicant from extracted "
        "identity fields, and then performs the comparison."
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

    _render_uploaded_application_result()


def _render_combined_pdf_mapping() -> None:
    mapped_pdf = st.file_uploader("Loan PDF", type=["pdf"], key="mapped_pdf")
    mapped_json = st.text_area(
        "Trusted JSON or raw company database dump",
        height=330,
        key="mapped_pdf_manifest_json",
        placeholder=_manifest_placeholder(),
        help=(
            "Paste either the canonical manifest or the complete company dump beginning with "
            "'Loan Application:'. Malformed smart quotes and masked identifiers are handled automatically."
        ),
    )
    if st.button("Identify and Verify Documents", type="primary", key="verify_mapped_pdf"):
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
        "The source ranges preserve ZIP file boundaries. Document type, continuation pages, and "
        "person ownership are identified automatically during OCR processing."
    )

    if "zip_manifest_json" not in st.session_state:
        st.session_state["zip_manifest_json"] = json.dumps(
            _package_manifest_template(package), indent=2
        )
    mapped_json = st.text_area(
        "Trusted JSON or raw company database dump for this ZIP",
        height=420,
        key="zip_manifest_json",
        help=(
            "You may replace the template with the complete company database dump; it will be "
            "converted into applicant and co-applicant reference data automatically."
        ),
    )
    if st.button("Identify and Verify ZIP Documents", type="primary", key="verify_mapped_zip"):
        manifest_payload = _parse_manifest_text(mapped_json)
        if manifest_payload is not None:
            _submit_zip_package_verification(str(package["package_id"]), manifest_payload)


def _manifest_placeholder() -> str:
    return (
        '{\n  "schema_version": "1.0",\n  "loan_id": "LN-001",\n'
        '  "people": {\n    "primary": {"applicant_name": "Ramesh Kumar", '
        '"aadhaar_number": "123456789012", "pan_number": "ABCDE1234F"}\n  },\n'
        '  "document_index": []\n}'
    )


def _parse_manifest_text(raw_json: str) -> dict | None:
    if not raw_json.strip():
        st.warning("Paste the trusted manifest JSON first.")
        return None
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        try:
            payload = convert_company_database_dump(raw_json)
        except CompanyDumpConversionError as conversion_exc:
            st.error(
                f"The pasted content is neither valid manifest JSON nor a recognized company dump. "
                f"JSON error: {exc}. Conversion error: {conversion_exc}"
            )
            return None
        st.success(
            f"Company database dump converted automatically for {len(payload.get('people') or {})} person(s)."
        )
    else:
        if is_company_database_dump(payload):
            try:
                payload = convert_company_database_dump(payload)
            except CompanyDumpConversionError as exc:
                st.error(f"Could not convert company database JSON: {exc}")
                return None
            st.success(
                f"Company database JSON converted automatically for {len(payload.get('people') or {})} person(s)."
            )
    for warning in payload.get("conversion_warnings") or []:
        st.warning(str(warning))
    return payload


def _page_range_label(document: dict) -> str:
    start = int(document["internal_page_start"])
    end = int(document["internal_page_end"])
    return str(start) if start == end else f"{start}-{end}"


def _package_manifest_template(package: dict) -> dict:
    return {
        "schema_version": "1.0",
        "loan_id": "REPLACE-WITH-LOAN-ID",
        "product_type": "LAP",
        "source": "automatic_zip_identification",
        "people": {
            "primary": {
                "role": "primary",
                "applicant_name": "REPLACE WITH APPLICANT NAME",
            }
        },
        "document_index": [],
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
        "Every page will be classified and assigned to the most likely person automatically."
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

    with st.spinner("Uploading pages for automatic identification and verification..."):
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
        "Every page will be classified and assigned to the most likely person automatically."
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
        st.subheader("Automatic Identification and Verification Output")
        st.caption(
            "Shared PDF pipeline: native text for digital pages, OCR only for scanned pages, "
            "LLM document classification, trusted JSON comparison, and the standard final report."
        )
        processing_message = "Identifying documents and comparing the loan file"
        completion_message = "Automatic identification and verification complete."
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
