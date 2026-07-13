"""Streamlit results page with ops-efficiency reviewer UI."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

from database.db import get_connection
from services.checklist_service import get_ai_checkable_items, get_all_checklist_items, get_human_review_items
from services.checklist_status import build_checklist_status
from services.ocr_json_export import build_ocr_document_json
from services.report_generator import generate_excel_report
from services.reviewer_exceptions import collapse_for_reviewer, summarize_for_display
from services.reviewer_summary_store import load_reviewer_summary
from views.status_helpers import render_page_processing_table

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
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
    st.dataframe(exceptions or [], width="stretch")


def render_application_results(application_id: int) -> None:
    data = _load_application_result(application_id)
    if not data:
        st.error("Application not found.")
        return

    application = data["application"]
    application.setdefault("id", application_id)
    product_type = application.get("product_type") or "LAP"
    ground_truth = data["ground_truth"]
    raw_anomalies = data["anomalies"]
    summary = summarize_for_display(raw_anomalies)
    anomalies = summary["reviewer_anomalies"]
    pages = data["pages"]
    page_images = _page_image_map(pages)

    st.markdown(
        f"""
        <div class="dmef-page-title">
            <h1>Loan File Review - {application['loan_id']}</h1>
            <div class="dmef-caption">
                Application {application.get('id', application_id)} | {application.get('product_type') or 'LAP'} | {application.get('branch') or '-'}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_queue_header()
    _render_verdict_banner(application, summary)
    _render_deterministic_reviewer_summary(application_id)
    _render_summary(application, data, summary, pages, product_type)
    _render_ground_truth(ground_truth, application)
    _render_result_explanation(data)
    _render_final_page_processing(data)

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
    _render_download(application_id, data)
    _render_keyboard_shortcuts_note()
    _render_reviewer_decision(application_id, application.get("status"), manual_confirmed, summary)


def _render_queue_header() -> None:
    queue = st.session_state.get("queue")
    if not queue:
        return
    index = st.session_state.get("queue_index", 0)
    st.caption(f"Review queue: file {index + 1} of {len(queue)}")


def _render_deterministic_reviewer_summary(application_id: int) -> None:
    summary = load_reviewer_summary(application_id)
    if not summary:
        return
    st.subheader("Reviewer Action Summary")
    status = str(summary.get("overall_status") or "LIMITED_REVIEW")
    message = str(summary.get("message") or "")
    recommendation = str(summary.get("recommendation") or "")
    pages = summary.get("pages_to_review") or []
    if status == "CLEAN":
        st.success(f"{status}: {message}")
    elif status in {"HIGH_RISK", "FULL_MANUAL_REVIEW"}:
        st.error(f"{status.replace('_', ' ')}: {message}")
    else:
        st.warning(f"{status.replace('_', ' ')}: {message}")
    st.info(recommendation)
    if pages:
        st.warning(f"Pages to check manually: {', '.join(map(str, pages))}")
    people = summary.get("people_verification") or {}
    if people:
        st.markdown("#### Person-wise identity verification")
        rows = []
        for person_id, person in people.items():
            documents = person.get("documents") or {}
            for document_type, document in documents.items():
                rows.append({
                    "Person": person.get("person_name") or person_id,
                    "Role ID": person_id,
                    "Document": document_type,
                    "Status": document.get("status"),
                    "Pages": ", ".join(map(str, document.get("pages") or [])),
                    "Fields observed": ", ".join(document.get("fields") or []),
                    "Issues": document.get("anomaly_count", 0),
                })
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)


def _render_verdict_banner(application: dict, summary: dict) -> None:
    status = application.get("status") or "NEEDS_REVIEW"
    high_count = summary["high_count"]
    reviewer_count = summary["reviewer_count"]

    if status == "CLEAN" or reviewer_count == 0:
        _status_banner("CLEAN", "No checklist issues found", "clean")
        if st.button("Approve & Next", type="primary", key=f"quick_accept_{application['id']}"):
            _submit_decision(
                application_id=int(application["id"]),
                decision="ACCEPT",
                reviewer_note="Auto-approved from CLEAN banner - no checklist issues detected.",
                advance_queue=True,
            )
        return

    if status == "CRITICAL" or high_count > 0:
        _status_banner("CRITICAL", f"{high_count or reviewer_count} high-severity issue(s)", "critical")
        return

    _status_banner("NEEDS REVIEW", f"{reviewer_count} issue(s) to check", "review")


def _status_banner(title: str, detail: str, kind: str) -> None:
    styles = {
        "clean": ("#0f241c", "#245a43", "#34d399", "#c8f7df"),
        "review": ("#2b2110", "#6f501f", "#fbbf24", "#ffe8a3"),
        "critical": ("#2a1218", "#713041", "#fb7185", "#ffd1d9"),
    }
    bg, border, accent, text = styles[kind]
    st.markdown(
        f"""
        <div style="background:{bg};border:1px solid {border};border-left:6px solid {accent};
        color:{text};padding:16px 18px;border-radius:6px;font-size:1.12rem;font-weight:700;margin-bottom:16px;">
        {title} - {detail}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_summary(application: dict, data: dict, summary: dict, pages: list[dict], product_type: str) -> None:
    uploaded_file = data["uploaded_file"]
    ai_items = get_ai_checkable_items(product_type)
    failed_ai_snos = {anomaly.get("s_no") for anomaly in data["anomalies"] if anomaly.get("s_no") is not None}
    ai_passed = len([item for item in ai_items if item.get("s_no") not in failed_ai_snos])
    page_events = data.get("page_events") or []
    avg_page_time = _average_page_time(page_events)

    st.subheader("Review Summary")
    columns = st.columns(6)
    columns[0].metric("Status", application.get("status") or "-")
    columns[1].metric("Total Pages", uploaded_file.get("total_pages") or len(pages))
    columns[2].metric("Digital", uploaded_file.get("digital_pages") or "-")
    columns[3].metric("Scanned", uploaded_file.get("scanned_pages") or "-")
    columns[4].metric("Checklist Passed", f"{ai_passed}/{len(ai_items) or '-'}")
    columns[5].metric("Avg Page Time", f"{avg_page_time:.2f}s" if avg_page_time else "-")
    st.caption(f"Reviewer-visible issues: {summary['reviewer_count']}")


def _render_ground_truth(ground_truth: dict, application: dict) -> None:
    st.subheader("Application Data")
    columns = st.columns(5)
    values = [
        ("Applicant", ground_truth.get("applicant_name") or application.get("applicant_name")),
        ("PAN", ground_truth.get("pan_number")),
        ("Loan Amount", ground_truth.get("loan_amount")),
        ("Branch", application.get("branch")),
        ("Product", application.get("product_type")),
    ]
    for column, (label, value) in zip(columns, values):
        column.metric(label, value or "-")


def _render_result_explanation(data: dict) -> None:
    anomalies = data["anomalies"]
    unsupported = next((item for item in anomalies if item.get("rule_id") == "UNSUPPORTED_DOCUMENT_TYPE"), None)
    page_failures = [item for item in anomalies if item.get("rule_id") == "PAGE_PROCESSING_ERROR"]
    missing = [item for item in anomalies if str(item.get("rule_id", "")).startswith("MISSING_DOC")]

    st.subheader("Result Explanation")
    if unsupported:
        st.error("Unsupported input: the file does not contain enough confident loan-document matches.")
        st.caption(str(unsupported.get("found_value") or unsupported.get("reason") or "Checklist evaluation skipped."))
        return
    if page_failures:
        st.warning(f"Partial failure: {len(page_failures)} page(s) had processing errors and need manual review.")
    if missing:
        st.info(f"{len(missing)} checklist item(s) are missing because no confident matching page was found.")
    if not unsupported and not page_failures and not missing:
        st.success("The result is based on confident page classifications and completed processing.")


def _render_final_page_processing(data: dict) -> None:
    completed_pages = data.get("page_events") or []
    if not completed_pages:
        return
    st.subheader("Page Processing Output")
    render_page_processing_table(completed_pages)


def _render_anomaly_expanders(anomalies: list[dict], page_images: dict[int, str]) -> None:
    if not anomalies:
        st.success("No issues detected")
        return

    for index, anomaly in enumerate(anomalies):
        severity = str(anomaly.get("severity", "LOW")).upper()
        page_number = anomaly.get("page_number")
        reason = anomaly.get("reason") or anomaly.get("rule_id") or "Issue"
        label = f"{severity} | Page {page_number or '?'} | {reason}"
        with st.expander(label, expanded=index == 0 and severity == "HIGH"):
            left, right = st.columns([1, 1])
            with left:
                image_path = page_images.get(page_number) if page_number is not None else None
                if image_path and Path(image_path).exists():
                    st.image(image_path, caption=f"Page {page_number}", width="stretch")
                else:
                    st.caption("Page image not available")
            with right:
                st.write(f"**Expected:** {anomaly.get('expected_value') or '-'}")
                st.write(f"**Found:** {anomaly.get('found_value') or '-'}")
                st.write(f"**Rule:** {anomaly.get('rule_id') or '-'}")
                if anomaly.get("collapsed_page_numbers"):
                    st.write(f"**Pages affected:** {', '.join(map(str, anomaly['collapsed_page_numbers']))}")


def _render_document_checklist(data: dict, product_type: str) -> None:
    if any(str(anomaly.get("rule_id", "")).upper() == "UNSUPPORTED_DOCUMENT_TYPE" for anomaly in data["anomalies"]):
        st.subheader("MSFC Checklist")
        st.error(
            "This uploaded file does not look like an MSFC loan file. "
            "Checklist matching is skipped to avoid false positives."
        )
        st.info("Upload a loan-file packet to run the 44-item checklist.")
        return

    checklist_items = get_all_checklist_items(product_type)
    item_count = len(checklist_items)
    st.subheader(f"MSFC Checklist ({item_count} items)")
    rows = build_checklist_status(checklist_items, data["pages"], data["anomalies"])
    missing_rows = [row for row in rows if row["status"] == "MISSING"]
    found_rows = [row for row in rows if row["status"] == "FOUND"]
    not_checked_rows = [row for row in rows if row["status"] == "NOT_CHECKED"]

    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("Found", len(found_rows))
    summary_col2.metric("Missing", len(missing_rows))
    summary_col3.metric("Not checked", len(not_checked_rows))

    display_rows = [
        {
            "S.No": row["s_no"],
            "Status": _checklist_status_label(row["status"]),
            "Description": row["description"],
            "Looked for": row["document_types"],
            "Pages": row["pages"],
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")

    if missing_rows:
        st.error(
            "Missing documents: "
            + "; ".join(f"S{row['s_no']} - {row['description']}" for row in missing_rows)
        )
    elif not_checked_rows:
        st.info("Checklist evaluation was skipped for items with no matching document pages.")
    else:
        st.success(f"All {item_count} checklist documents were found in the uploaded file.")


def _render_manual_review(product_type: str) -> bool:
    manual_items = get_human_review_items(product_type)
    st.subheader("Manual Review Required")
    st.warning("Items requiring manual verification cannot be checked automatically.")
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
            width="stretch",
        )
    return st.checkbox("I confirm I have manually verified all items in the above list")


def _render_pages_requiring_review(anomalies: list[dict]) -> None:
    page_numbers = sorted({anomaly.get("page_number") for anomaly in anomalies if anomaly.get("page_number")})
    st.subheader("Pages Requiring Review")
    if page_numbers:
        st.warning(f"Review these pages: {', '.join(map(str, page_numbers))}")
    else:
        st.success("All pages clean")


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
    if decision_cols[0].button("Accept", disabled=not manual_confirmed, key=f"accept_{application_id}"):
        if _submit_decision(application_id, "ACCEPT", st.session_state[note_key] or "Accepted after manual review.", advance_queue=True):
            return
    if decision_cols[1].button("Override", disabled=not manual_confirmed, key=f"override_{application_id}"):
        if _submit_decision(application_id, "OVERRIDE", st.session_state[note_key] or "Override approved after review.", advance_queue=True):
            return
    if decision_cols[2].button("Request Docs", disabled=not manual_confirmed, key=f"request_{application_id}"):
        st.session_state[f"show_request_docs_{application_id}"] = True
    if decision_cols[3].button("Skip / Next", key=f"skip_{application_id}"):
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


def _render_rejection_chips(note_key: str) -> None:
    st.caption("Quick-select rejection reason")
    columns = st.columns(3)
    labels = list(REJECTION_REASONS.keys())
    for idx, label in enumerate(labels):
        if columns[idx % 3].button(label, key=f"{note_key}_chip_{label}"):
            st.session_state[note_key] = REJECTION_REASONS[label]


def _render_keyboard_shortcuts_note() -> None:
    st.caption("Use queue Skip/Next buttons for faster throughput.")


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


def _checklist_status_label(status: str) -> str:
    if status == "FOUND":
        return "Found"
    if status == "MISSING":
        return "Missing"
    return "Not checked"


def _render_download(application_id: int, data: dict) -> None:
    st.subheader("Downloads")
    report_col, json_col = st.columns(2)
    with report_col:
        if st.button("Prepare Anomaly Report (Excel)", key=f"excel_report_{application_id}"):
            try:
                report_path = generate_excel_report(application_id)
                with open(report_path, "rb") as report_file:
                    st.download_button(
                        "Download Anomaly Report (Excel)",
                        data=report_file,
                        file_name=report_path.split("/")[-1],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"excel_report_download_{application_id}",
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                st.error(f"Report generation failed: {exc}")

    with json_col:
        document_json = _build_document_ocr_download_payload(application_id, data)
        st.download_button(
            "Download Document OCR JSON",
            data=json.dumps(document_json, indent=2, ensure_ascii=False),
            file_name=f"application_{application_id}_document_ocr_data.json",
            mime="application/json",
            key=f"document_ocr_json_{application_id}",
        )


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
        page_events = connection.execute(
            """
            SELECT page_number, total_pages, page_type, document_type, status,
                   elapsed_seconds, error, extracted_fields, completed_at
            FROM pipeline_page_events
            WHERE application_id = ?
            ORDER BY page_number
            """,
            (application_id,),
        ).fetchall()

    page_dicts = [_coerce_page_row(row) for row in pages]
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
        "page_events": [_coerce_page_event(row) for row in page_events],
        "documents_found": sorted(document_pages),
        "document_pages": document_pages,
        "documents_missing": [
            anomaly.get("document_type")
            for anomaly in anomaly_dicts
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC") and anomaly.get("document_type")
        ],
    }


def _coerce_page_event(row: Any) -> dict:
    payload = dict(row)
    raw_fields = payload.get("extracted_fields")
    try:
        decoded = json.loads(raw_fields) if raw_fields else {}
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    payload["extracted_fields"] = decoded if isinstance(decoded, dict) else {}
    return payload


def _coerce_page_row(row: Any) -> dict:
    payload = dict(row)
    raw_fields = payload.get("extracted_fields")
    try:
        decoded = json.loads(raw_fields) if raw_fields else {}
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    payload["extracted_fields"] = decoded if isinstance(decoded, dict) else {}
    return payload


def _build_document_ocr_download_payload(application_id: int, data: dict) -> dict:
    saved_payload = _load_saved_document_ocr_json(application_id)
    if saved_payload is not None:
        return saved_payload

    return build_ocr_document_json(
        application_id,
        data.get("pages") or [],
        page_events=data.get("page_events") or [],
    )


def _load_saved_document_ocr_json(application_id: int) -> dict | None:
    path = Path("data/processed") / f"application_{application_id}" / "document_ocr_data.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _page_image_map(pages: list[dict]) -> dict[int, str]:
    return {
        int(page["page_number"]): page["image_path"]
        for page in pages
        if page.get("page_number") is not None and page.get("image_path")
    }


def _average_page_time(page_events: list[dict]) -> float:
    values = [
        float(page.get("elapsed_seconds") or 0)
        for page in page_events
        if page.get("elapsed_seconds") not in (None, "")
    ]
    return sum(values) / len(values) if values else 0.0


def _sort_anomalies(anomalies: list[dict]) -> list[dict]:
    return collapse_for_reviewer(anomalies)
