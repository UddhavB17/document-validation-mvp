"""Streamlit results page with ops-efficiency reviewer UI."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from database.db import get_connection
from services.checklist_service import get_ai_checkable_items, get_all_checklist_items, get_human_review_items
from services.checklist_status import build_checklist_status
from services.report_generator import generate_excel_report
from services.reviewer_exceptions import collapse_for_reviewer, summarize_for_display

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
UNDO_WINDOW_MINUTES = 10

REJECTION_REASONS = {
    "Document missing": "Please resubmit with the missing document(s) listed above.",
    "Name mismatch": "Name on submitted document does not match application records. Please verify and resubmit.",
    "Scan unclear": "Scan quality is too low to verify. Please rescan and resubmit.",
    "Statement outdated": "Bank statement is outside the allowed recency window. Please upload a recent statement.",
    "Wrong applicant": "Document appears to belong to a different applicant. Please verify and resubmit.",
    "Signature missing": "Required signature is missing. Please upload a signed copy.",
}


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
    raw_anomalies = data["anomalies"]
    summary = summarize_for_display(raw_anomalies)
    anomalies = summary["reviewer_anomalies"]
    pages = data["pages"]
    page_images = _page_image_map(pages)

    st.title(f"Loan File Review - {application['loan_id']}")
    _render_queue_header()
    _render_verdict_banner(application, summary)
    _render_ground_truth(ground_truth, application)
    _render_summary(application, data, summary, pages, product_type)

    if application.get("llm_summary"):
        st.subheader("AI Analysis")
        st.info(application["llm_summary"])

    st.subheader("Anomalies")
    if summary["raw_count"] > summary["reviewer_count"]:
        st.caption(
            f"Showing {summary['reviewer_count']} actionable item(s) "
            f"(collapsed from {summary['raw_count']} raw OCR/check flags)."
        )
    _render_anomaly_expanders(anomalies, page_images)

    manual_confirmed = _render_manual_review(product_type)
    _render_document_checklist(data, product_type)
    _render_pages_requiring_review(anomalies)
    _render_download(application_id)
    _render_keyboard_shortcuts_note()
    _render_reviewer_decision(application_id, application.get("status"), manual_confirmed, summary)


def _render_queue_header() -> None:
    queue = st.session_state.get("queue")
    if not queue:
        return
    index = st.session_state.get("queue_index", 0)
    st.markdown(f"**Review queue:** File {index + 1} of {len(queue)}")


def _render_verdict_banner(application: dict, summary: dict) -> None:
    status = application.get("status") or "NEEDS_REVIEW"
    high_count = summary["high_count"]
    reviewer_count = summary["reviewer_count"]

    if status == "CLEAN" or reviewer_count == 0:
        st.markdown(
            """
            <div style="background:#15803d;color:white;padding:24px;border-radius:12px;
            font-size:1.4rem;font-weight:700;text-align:center;margin-bottom:16px;">
            ✓ CLEAN — No issues found
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Approve & Next", type="primary", key=f"quick_accept_{application['id']}"):
            _submit_decision(
                application_id=int(application["id"]),
                decision="ACCEPT",
                reviewer_note="Auto-approved from CLEAN banner — no checklist issues detected.",
                advance_queue=True,
            )
        return

    if status == "CRITICAL" or high_count > 0:
        st.markdown(
            f"""
            <div style="background:#b91c1c;color:white;padding:24px;border-radius:12px;
            font-size:1.4rem;font-weight:700;text-align:center;margin-bottom:16px;">
            ✕ CRITICAL — {high_count or reviewer_count} high-severity issue(s)
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div style="background:#c2410c;color:white;padding:24px;border-radius:12px;
        font-size:1.4rem;font-weight:700;text-align:center;margin-bottom:16px;">
        ⚠ NEEDS REVIEW — {reviewer_count} issue(s) to check
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_anomaly_expanders(anomalies: list[dict], page_images: dict[int, str]) -> None:
    if not anomalies:
        st.success("No issues detected")
        return

    for index, anomaly in enumerate(anomalies):
        severity = str(anomaly.get("severity", "LOW")).upper()
        page_number = anomaly.get("page_number")
        reason = anomaly.get("reason") or anomaly.get("rule_id") or "Issue"
        label = f"{_severity_icon(severity)} Page {page_number or '?'} — {reason}"
        with st.expander(label, expanded=index == 0 and severity == "HIGH"):
            left, right = st.columns([1, 1])
            with left:
                image_path = page_images.get(page_number) if page_number is not None else None
                if image_path and Path(image_path).exists():
                    st.image(image_path, caption=f"Page {page_number}", use_container_width=True)
                else:
                    st.caption("Page image not available")
            with right:
                st.write(f"**Expected:** {anomaly.get('expected_value') or '-'}")
                st.write(f"**Found:** {anomaly.get('found_value') or '-'}")
                st.write(f"**Rule:** {anomaly.get('rule_id') or '-'}")
                if anomaly.get("collapsed_page_numbers"):
                    st.write(f"**Pages affected:** {', '.join(map(str, anomaly['collapsed_page_numbers']))}")


def _render_rejection_chips(note_key: str) -> None:
    st.caption("Quick-select rejection reason")
    columns = st.columns(3)
    labels = list(REJECTION_REASONS.keys())
    for idx, label in enumerate(labels):
        if columns[idx % 3].button(label, key=f"{note_key}_chip_{label}"):
            st.session_state[note_key] = REJECTION_REASONS[label]


def _render_keyboard_shortcuts_note() -> None:
    # Keyboard shortcuts via JS are brittle in Streamlit; use on-screen actions instead.
    st.caption("Tip: use queue Skip/Next buttons for faster throughput. Keyboard shortcuts are a known limitation.")


def _render_reviewer_decision(
    application_id: int,
    status: str | None,
    manual_confirmed: bool,
    summary: dict,
) -> None:
    latest = _load_latest_decision(application_id)
    if latest and status in {"verified", "verified_with_override", "incomplete"}:
        st.success(f"Reviewer decision already submitted: {latest.get('decision')}")
        _render_undo_button(latest)
        return

    st.subheader("Reviewer Decision")
    note_key = f"reviewer_note_{application_id}"
    if note_key not in st.session_state:
        st.session_state[note_key] = ""

    decision_cols = st.columns(4)
    if decision_cols[0].button("Accept (A)", disabled=not manual_confirmed, key=f"accept_{application_id}"):
        if _submit_decision(application_id, "ACCEPT", st.session_state[note_key] or "Accepted after manual review.", advance_queue=True):
            return
    if decision_cols[1].button("Override", disabled=not manual_confirmed, key=f"override_{application_id}"):
        if _submit_decision(application_id, "OVERRIDE", st.session_state[note_key] or "Override approved after review.", advance_queue=True):
            return
    if decision_cols[2].button("Request docs (R)", disabled=not manual_confirmed, key=f"request_{application_id}"):
        st.session_state[f"show_request_docs_{application_id}"] = True
    if decision_cols[3].button("Skip / Next (N)", key=f"skip_{application_id}"):
        _advance_queue()

    if st.session_state.get(f"show_request_docs_{application_id}"):
        _render_rejection_chips(note_key)
        reviewer_note = st.text_area(
            "Reviewer Note",
            key=note_key,
            disabled=not manual_confirmed,
        )
        if st.button("Submit request for documents", disabled=not manual_confirmed, key=f"submit_request_{application_id}"):
            if len(reviewer_note.strip()) <= 10:
                st.error("Reviewer note must be more than 10 characters.")
            elif _submit_decision(application_id, "REQUEST_DOCS", reviewer_note, advance_queue=True):
                st.session_state.pop(f"show_request_docs_{application_id}", None)


def _render_undo_button(latest: dict) -> None:
    decision_id = latest.get("id")
    decided_at_raw = latest.get("decided_at")
    if not decision_id or not decided_at_raw:
        return
    decided_at = datetime.fromisoformat(str(decided_at_raw))
    if datetime.now() - decided_at > timedelta(minutes=UNDO_WINDOW_MINUTES):
        return
    if st.button("Undo decision (available for 10 min)", key=f"undo_{decision_id}"):
        response = requests.post(f"{API_BASE_URL}/decision/{decision_id}/undo", timeout=30)
        if response.status_code >= 400:
            st.error(response.json().get("detail", "Undo failed"))
        else:
            st.success("Decision undone.")
            st.rerun()


def _submit_decision(application_id: int, decision: str, reviewer_note: str, *, advance_queue: bool) -> bool:
    if len(reviewer_note.strip()) <= 10:
        st.error("Reviewer note must be more than 10 characters.")
        return False
    response = requests.post(
        f"{API_BASE_URL}/decision",
        json={"application_id": application_id, "decision": decision, "reviewer_note": reviewer_note.strip()},
        timeout=30,
    )
    if response.status_code >= 400:
        st.error(response.json().get("detail", "Decision failed"))
        return False
    st.success("Reviewer decision saved.")
    if advance_queue:
        _advance_queue()
    else:
        st.rerun()
    return True


def _advance_queue() -> None:
    queue = st.session_state.get("queue")
    if not queue:
        st.rerun()
        return
    next_index = st.session_state.get("queue_index", 0) + 1
    if next_index >= len(queue):
        st.session_state.pop("queue", None)
        st.session_state.pop("queue_index", None)
        st.session_state.pop("worklist_application_id", None)
        st.success("Queue complete.")
        st.rerun()
        return
    st.session_state["queue_index"] = next_index
    st.session_state["worklist_application_id"] = queue[next_index]
    st.rerun()


def _severity_icon(severity: str) -> str:
    return {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}.get(severity.upper(), "⚪")


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


def _render_summary(application: dict, data: dict, summary: dict, pages: list[dict], product_type: str) -> None:
    uploaded_file = data["uploaded_file"]
    ai_items = get_ai_checkable_items(product_type)
    manual_items = get_human_review_items(product_type)
    failed_ai_snos = {anomaly.get("s_no") for anomaly in data["anomalies"] if anomaly.get("s_no") is not None}
    ai_passed = len([item for item in ai_items if item.get("s_no") not in failed_ai_snos])

    st.subheader("Summary")
    columns = st.columns(4)
    columns[0].metric("Total Pages", uploaded_file.get("total_pages") or len(pages))
    columns[1].metric("Digital Pages", uploaded_file.get("digital_pages") or "-")
    columns[2].metric("Scanned Pages", uploaded_file.get("scanned_pages") or "-")
    columns[3].metric("Issues (reviewer view)", summary["reviewer_count"])


def _render_document_checklist(data: dict, product_type: str) -> None:
    checklist_items = get_all_checklist_items(product_type)
    item_count = len(checklist_items)
    st.subheader(f"MSFC Checklist ({item_count} items)")
    rows = build_checklist_status(checklist_items, data["pages"], data["anomalies"])
    missing_rows = [row for row in rows if row["status"] == "MISSING"]
    found_count = len(rows) - len(missing_rows)

    summary_col1, summary_col2 = st.columns(2)
    summary_col1.metric("Checklist items found", found_count)
    summary_col2.metric("Checklist items missing", len(missing_rows))

    display_rows = [
        {
            "S.No": row["s_no"],
            "Status": "✅ Found" if row["status"] == "FOUND" else "❌ Missing",
            "Description": row["description"],
            "Looked for": row["document_types"],
            "Pages": row["pages"],
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, use_container_width=True)

    if missing_rows:
        st.error(
            "Missing documents: "
            + "; ".join(f"S{row['s_no']} — {row['description']}" for row in missing_rows)
        )
    else:
        st.success(f"All {item_count} checklist documents were found in the uploaded file.")


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


def _load_latest_decision(application_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, application_id, decision, reviewer_note, decided_at
            FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    return dict(row) if row else None


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


def _page_image_map(pages: list[dict]) -> dict[int, str]:
    return {
        int(page["page_number"]): page["image_path"]
        for page in pages
        if page.get("page_number") is not None and page.get("image_path")
    }


def _sort_anomalies(anomalies: list[dict]) -> list[dict]:
    return collapse_for_reviewer(anomalies)
