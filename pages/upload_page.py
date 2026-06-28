"""Streamlit upload page.

Lets a reviewer:
  1. Upload a PDF for file-level validation.
  2. Paste / upload the partner OCR JSON payload for processing.
"""

import json

import streamlit as st

from services.file_validator import validate_upload


def render_upload_page() -> None:
    st.title("📤 Upload Loan File")
    st.caption(
        "Upload the loan-file PDF for file-level validation, "
        "or paste the partner OCR JSON to trigger checklist evaluation."
    )

    st.divider()

    # ── Tab 1: PDF file-level validation ──────
    tab_pdf, tab_json = st.tabs(["PDF Validation", "Partner JSON Intake"])

    with tab_pdf:
        st.subheader("PDF File Validation")
        uploaded_file = st.file_uploader(
            "Upload loan-file PDF",
            type=["pdf"],
            help="Maximum file size: 50 MB. Only PDF accepted.",
        )

        if uploaded_file is not None:
            result = validate_upload(
                uploaded_file.name,
                file_size_bytes=uploaded_file.size,
            )
            if result["is_valid"]:
                st.success(f"✅ **{uploaded_file.name}** passed file validation.")
            else:
                for err in result["errors"]:
                    st.error(f"❌ {err}")

    # ── Tab 2: Partner JSON intake ────────────
    with tab_json:
        st.subheader("Partner OCR JSON Payload")
        st.info(
            "Paste the JSON produced by your partner's OCR pipeline. "
            "It should contain `loan_id`, `digital_text`, and `scanned_docs`."
        )

        raw_json = st.text_area(
            "Paste JSON here",
            height=300,
            placeholder='{\n  "loan_id": "LN-001",\n  "digital_text": {},\n  "scanned_docs": {}\n}',
        )

        if st.button("▶ Run Checklist Evaluation", type="primary"):
            if not raw_json.strip():
                st.warning("Please paste the partner JSON first.")
            else:
                try:
                    payload = json.loads(raw_json)
                    st.success("JSON parsed successfully.")
                    st.json(payload)
                    st.info("TODO: wire up to checklist_engine and persist to DB.")
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
