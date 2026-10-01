"""Database access for review routes and services."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from database.db import get_connection
from services.paths import processed_output_dir
from services.progress_tracker import RETRYABLE_PROGRESS_STATES, operational_progress_status
from services.review.types import ApplicationReviewData

LOGGER = logging.getLogger(__name__)

JsonRow = dict[str, object]


def _required_int(value: object) -> int:
    """Convert a database scalar known to represent an integer."""
    if isinstance(value, (int, str)):
        return int(value)
    raise ValueError(f"Expected an integer-compatible database value, got {value!r}")


def coerce_json_row(row: Any) -> JsonRow:
    """Convert a SQLite row into a mapping with decoded extracted fields."""
    row_payload = dict(row)
    raw_extracted_fields = row_payload.get("extracted_fields")
    try:
        decoded_fields = json.loads(raw_extracted_fields) if raw_extracted_fields else {}
    except (TypeError, json.JSONDecodeError):
        decoded_fields = {}
    row_payload["extracted_fields"] = decoded_fields if isinstance(decoded_fields, dict) else {}
    # Payload diet: OCR text and layout blobs never leave the repository inside
    # summary rows. Single-page text uses load_page_text explicitly.
    row_payload.pop("ocr_text", None)
    row_payload.pop("structured_content", None)
    row_payload.pop("meta_json", None)
    return {str(key): value for key, value in row_payload.items()}


#: Explicit page-summary columns: no ``ocr_text``, no layout blobs, no meta.
PAGE_SUMMARY_COLUMNS = (
    "application_id, page_number, page_type, is_readable, ocr_confidence, "
    "ocr_route, ocr_escalated, ocr_processing_time_ms, document_type, "
    "classification_confidence, detection_method, detected_page_number, "
    "extracted_fields"
)


def load_pages_summary(application_id: int) -> list[JsonRow]:
    """Load compact page summaries (no ``ocr_text``, no meta)."""
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT {PAGE_SUMMARY_COLUMNS}
            FROM pages
            WHERE application_id = ?
            ORDER BY page_number
            """,
            (application_id,),
        ).fetchall()
    return [coerce_json_row(row) for row in rows]


def load_page_text(application_id: int, page_number: int) -> JsonRow | None:
    """Load one page's OCR text with its confidence and document type."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT page_number, ocr_text, ocr_confidence, document_type
            FROM pages
            WHERE application_id = ? AND page_number = ?
            """,
            (application_id, page_number),
        ).fetchone()
    if row is None:
        return None
    payload = dict(row)
    return {
        "page_number": payload.get("page_number"),
        "ocr_text": payload.get("ocr_text") or "",
        "ocr_confidence": payload.get("ocr_confidence"),
        "document_type": payload.get("document_type"),
    }


def load_application_review_data(application_id: int) -> ApplicationReviewData | None:
    """Load public review data without private evidence."""
    data, _ = _load_application_review(application_id, include_evidence=False)
    return data


def load_application_review_bundle(
    application_id: int,
    *,
    sparse_evidence: bool = False,
) -> tuple[ApplicationReviewData | None, list[dict]]:
    """Read review summaries and private comparison evidence together.

    Keep the evidence separate so OCR/private metadata cannot enter the public
    response, and avoid fetching every page row a second time.  The application
    review route uses ``sparse_evidence``: it only reads OCR/meta blobs for
    pages that contain fields expected by the saved ground truth.  The legacy
    full-evidence mode remains available to callers that explicitly need the
    complete private bundle (for example, OCR export/backfill tooling).
    """
    return _load_application_review(
        application_id,
        include_evidence=True,
        sparse_evidence=sparse_evidence,
    )


def _load_application_review(
    application_id: int, *, include_evidence: bool, sparse_evidence: bool = False
) -> tuple[ApplicationReviewData | None, list[dict]]:
    columns = ", ".join(f"p.{column.strip()}" for column in PAGE_SUMMARY_COLUMNS.split(","))
    if include_evidence and not sparse_evidence:
        columns += ", p.ocr_text, m.meta_json"
    join = (
        "LEFT JOIN pages_meta m ON m.application_id = p.application_id "
        "AND m.page_number = p.page_number"
        if include_evidence and not sparse_evidence
        else ""
    )
    evidence_rows: list[Any] = []
    with get_connection() as connection:
        application_row = connection.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if application_row is None:
            return None, []
        uploaded_file_row = connection.execute(
            "SELECT * FROM uploaded_files WHERE application_id = ? ORDER BY uploaded_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        ground_truth_row = connection.execute(
            "SELECT * FROM ground_truth WHERE application_id = ? ORDER BY extracted_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        anomaly_rows = connection.execute(
            "SELECT * FROM validation_results WHERE application_id = ?",
            (application_id,),
        ).fetchall()
        page_rows = connection.execute(
            f"""
            SELECT {columns}
            FROM pages p {join}
            WHERE p.application_id = ?
            ORDER BY p.page_number
            """,
            (application_id,),
        ).fetchall()
        page_event_rows = connection.execute(
            """
            SELECT page_number, total_pages, page_type, document_type, status,
                    elapsed_seconds, error, completed_at
            FROM pipeline_page_events
            WHERE application_id = ?
            ORDER BY page_number
            """,
            (application_id,),
        ).fetchall()

        # OCR and private metadata are needed only while constructing the
        # comparison matrix.  A full-page join makes a large review (for
        # example application 11) read megabytes of text and metadata even
        # though most pages carry no ground-truth comparison fields.  First
        # load compact page summaries, then fetch blobs only for candidate
        # pages selected from their business fields.
        if include_evidence and sparse_evidence:
            candidate_pages = _comparison_evidence_page_numbers(
                page_rows,
                ground_truth_row,
            )
            if candidate_pages:
                placeholders = ",".join("?" for _ in candidate_pages)
                evidence_rows = connection.execute(
                    f"""
                    SELECT p.page_number, p.ocr_text, m.meta_json
                    FROM pages p
                    LEFT JOIN pages_meta m
                      ON m.application_id = p.application_id
                     AND m.page_number = p.page_number
                    WHERE p.application_id = ?
                      AND p.page_number IN ({placeholders})
                    ORDER BY p.page_number
                    """,
                    (application_id, *candidate_pages),
                ).fetchall()

    # Normalize database rows before deriving the document index and response payload.
    normalized_page_rows: list[JsonRow] = [coerce_json_row(row) for row in page_rows]
    normalized_anomaly_rows: list[JsonRow] = [dict(row) for row in anomaly_rows]
    document_pages: dict[str, list[int]] = {}
    for page_row in normalized_page_rows:
        document_type = page_row.get("document_type")
        page_number = page_row.get("page_number")
        if document_type and document_type != "Unknown" and page_number is not None:
            document_pages.setdefault(str(document_type), []).append(_required_int(page_number))

    if not include_evidence:
        evidence = []
    elif sparse_evidence:
        evidence = _hydrate_sparse_comparison_evidence(normalized_page_rows, evidence_rows)
    else:
        evidence = _hydrate_comparison_evidence(normalized_page_rows, page_rows)
    return {
        "application": dict(application_row),
        "uploaded_file": dict(uploaded_file_row) if uploaded_file_row else {},
        "ground_truth": dict(ground_truth_row) if ground_truth_row else {},
        "anomalies": normalized_anomaly_rows,
        "pages": normalized_page_rows,
        "page_events": [coerce_json_row(row) for row in page_event_rows],
        "documents_found": sorted(document_pages),
        "document_pages": document_pages,
        "documents_missing": [
            anomaly.get("document_type")
            for anomaly in normalized_anomaly_rows
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC")
            and anomaly.get("document_type")
        ],
    }, evidence


def load_latest_decision(application_id: int) -> JsonRow | None:
    """Load the most recent reviewer decision for an application."""
    with get_connection() as connection:
        decision_row = connection.execute(
            """
            SELECT id, application_id, decision, reviewer_note, decided_at
            FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    return dict(decision_row) if decision_row else None


def _hydrate_comparison_evidence(pages: list[dict], rows: list[Any]) -> list[dict]:
    evidence = []
    for page, row in zip(pages, rows, strict=True):
        detail = dict(row)
        try:
            meta = json.loads(detail.get("meta_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            meta = {}
        fields = dict(page.get("extracted_fields") or {})
        if isinstance(meta, dict):
            fields.update({key: value for key, value in meta.items() if key.startswith("_")})
        evidence.append(
            {**page, "ocr_text": detail.get("ocr_text") or "", "extracted_fields": fields}
        )
    return evidence


_COMPARISON_FIELD_ALIASES = {
    "phone": "phone_number",
    "mobile": "phone_number",
    "mobile_number": "phone_number",
    "pan": "pan_number",
    "pincode": "pin_code",
    "application_number": "loan_id",
}


def _comparison_field_name(value: object) -> str:
    key = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return _COMPARISON_FIELD_ALIASES.get(key, key)


def _ground_truth_comparison_fields(row: Any) -> set[str]:
    """Return expected comparison keys without loading any page blobs."""
    if row is None:
        return set()
    try:
        raw_json = json.loads(str(row["raw_json"] or "{}"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(raw_json, dict):
        return set()

    fields: set[str] = set()
    for key, value in raw_json.items():
        if key in {"people", "reference_data"}:
            continue
        if value not in (None, "", [], {}):
            fields.add(_comparison_field_name(key))
    people = raw_json.get("people") or raw_json.get("reference_data") or {}
    if isinstance(people, dict):
        for profile in people.values():
            if not isinstance(profile, dict):
                continue
            for key, value in profile.items():
                if value not in (None, "", [], {}):
                    fields.add(_comparison_field_name(key))
    return fields


def _comparison_evidence_page_numbers(page_rows: list[Any], ground_truth_row: Any) -> list[int]:
    """Select pages whose persisted fields can affect the comparison matrix.

    ``pages.extracted_fields`` contains only business fields, so it is safe to
    inspect those compact values first.  OCR text and ``pages_meta`` are then
    fetched for this small candidate set only.  ``person_records`` is included
    when any record carries an expected field, preserving multi-person forms.
    """
    expected = _ground_truth_comparison_fields(ground_truth_row)
    if not expected:
        return []
    numbers: list[int] = []
    for row in page_rows:
        try:
            page_number = int(row["page_number"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            fields = json.loads(row["extracted_fields"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            fields = {}
        if not isinstance(fields, dict):
            continue
        direct_fields = {
            _comparison_field_name(key)
            for key, value in fields.items()
            if not str(key).startswith("_") and value not in (None, "", [], {})
        }
        if direct_fields & expected:
            numbers.append(page_number)
            continue
        records = fields.get("person_records")
        if isinstance(records, list) and any(
            isinstance(record, dict)
            and any(
                _comparison_field_name(key) in expected
                and value not in (None, "", [], {})
                for key, value in record.items()
            )
            for record in records
        ):
            numbers.append(page_number)
    return numbers


def _hydrate_sparse_comparison_evidence(
    pages: list[dict], rows: list[Any]
) -> list[dict]:
    """Hydrate all summaries while attaching raw evidence only to candidates."""
    details_by_page = {}
    for row in rows:
        try:
            details_by_page[int(row["page_number"])] = dict(row)
        except (KeyError, TypeError, ValueError):
            continue
    evidence: list[dict] = []
    for page in pages:
        try:
            page_number = int(page.get("page_number"))
        except (TypeError, ValueError):
            page_number = 0
        detail = details_by_page.get(page_number, {})
        try:
            meta = json.loads(detail.get("meta_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            meta = {}
        fields = dict(page.get("extracted_fields") or {})
        if isinstance(meta, dict):
            fields.update({key: value for key, value in meta.items() if key.startswith("_")})
        evidence.append(
            {
                **page,
                "ocr_text": detail.get("ocr_text") or "",
                "extracted_fields": fields,
            }
        )
    return evidence


def load_saved_document_ocr_json(application_id: int) -> JsonRow | None:
    """Load the saved per-document OCR JSON, if it is readable and object-shaped."""
    path = processed_output_dir() / f"application_{application_id}" / "document_ocr_data.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as json_file:
            payload = json.load(json_file)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Saved OCR JSON could not be read from %s; rebuilding it", path, exc_info=exc
        )
        return None
    return payload if isinstance(payload, dict) else None


def load_worklist_data() -> tuple[
    list[JsonRow], dict[int, list[JsonRow]], dict[int, dict[str, object]], dict[int, dict[str, object]]
]:
    """Read the worklist in three queries sharing one connection.

    Join the one-to-one progress row, but fetch anomalies separately so an
    application with many findings does not repeat its metadata on the wire.
    A third batched query carries each application's latest pipeline job
    (status + heartbeat) for resume gating. Settings/stale detection run
    after releasing this read transaction.
    """
    with get_connection() as connection:
        application_rows = connection.execute(
            """
            SELECT a.id, a.loan_id, a.applicant_name, a.product_type, a.status, a.created_at,
                   p.application_id AS progress_application_id,
                   p.status AS progress_status, p.processed_pages, p.total_pages,
                   p.percentage, p.updated_at
            FROM applications a
            LEFT JOIN pipeline_progress p ON p.application_id = a.id
            ORDER BY a.created_at DESC
            """
        ).fetchall()
        if not application_rows:
            return [], {}, {}, {}
        application_ids = [_required_int(row["id"]) for row in application_rows]
        placeholders = ",".join("?" for _ in application_ids)
        validation_rows = connection.execute(
            f"""
            SELECT application_id, severity, rule_id, status, page_number, reason,
                   document_type, expected_value, found_value
            FROM validation_results
            WHERE application_id IN ({placeholders})
            """,
            application_ids,
        ).fetchall()
        job_rows = connection.execute(
            """
            SELECT application_id, status, heartbeat_at FROM pipeline_jobs
            WHERE id IN (SELECT MAX(id) FROM pipeline_jobs GROUP BY application_id)
            """
        ).fetchall()

    results_by_application: dict[int, list[JsonRow]] = defaultdict(list)
    for row in validation_rows:
        application_id = _required_int(row["application_id"])
        results_by_application[application_id].append(dict(row))

    jobs_by_application: dict[int, dict[str, object]] = {}
    for row in job_rows:
        jobs_by_application[_required_int(row["application_id"])] = dict(row)

    applications: list[JsonRow] = []
    progress_by_application: dict[int, dict[str, object]] = {}
    for row in application_rows:
        payload = dict(row)
        application_id = _required_int(payload["id"])
        progress_id = payload.pop("progress_application_id")
        progress = {"status": payload.pop("progress_status")}
        for key in ("processed_pages", "total_pages", "percentage", "updated_at"):
            progress[key] = payload.pop(key)
        applications.append(payload)
        if progress_id is None:
            continue
        operational_status = operational_progress_status(progress)
        progress_by_application[application_id] = {
            "operational_status": operational_status,
            "retryable": operational_status in RETRYABLE_PROGRESS_STATES,
            "processed_pages": progress.get("processed_pages"),
            "total_pages": progress.get("total_pages"),
            "percentage": progress.get("percentage"),
        }
    return applications, results_by_application, progress_by_application, jobs_by_application


def load_today_activity() -> list[JsonRow]:
    """Load today's reviewer decisions in the API's existing order."""
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = (
        now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    ).isoformat()
    with get_connection() as connection:
        activity_rows = connection.execute(
            """
            SELECT
                reviewer_decisions.id,
                reviewer_decisions.application_id,
                applications.loan_id,
                reviewer_decisions.decision,
                reviewer_decisions.decided_at
            FROM reviewer_decisions
            JOIN applications ON applications.id = reviewer_decisions.application_id
            WHERE reviewer_decisions.decided_at >= ?
              AND reviewer_decisions.decided_at < ?
            ORDER BY reviewer_decisions.decided_at DESC
            """,
            (day_start, day_end),
        ).fetchall()
    return [dict(row) for row in activity_rows]


def load_latest_uploaded_file(application_id: int) -> JsonRow | None:
    """Load the newest uploaded source file metadata for an application."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT file_path, original_filename
            FROM uploaded_files
            WHERE application_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    return dict(row) if row else None
