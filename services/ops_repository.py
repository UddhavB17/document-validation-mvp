"""Persistence boundary for the operations presentation service."""

from __future__ import annotations

import json
from typing import Any

from database.db import get_connection


def load_ops_snapshot(application_id: int, *, include_pages: bool = True) -> dict[str, Any] | None:
    """Load the complete ops view input in one connection and bounded queries."""
    with get_connection() as connection:
        app_row = connection.execute(
            "SELECT id, loan_id, applicant_name, product_type, status, "
            "ops_summary_en, ops_summary_hi FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if app_row is None:
            return None
        application = dict(app_row)
        try:
            anomaly_rows = connection.execute(
                "SELECT id, application_id, rule_id, severity, status, page_number, "
                "reason, evidence_json, s_no, document_type, expected_value, found_value "
                "FROM validation_results WHERE application_id = ? "
                "AND COALESCE(status, '') != 'dismissed_by_llm' ORDER BY id",
                (application_id,),
            ).fetchall()
        except Exception:  # noqa: BLE001 - legacy database may lack the table
            anomaly_rows = []
        try:
            job_row = connection.execute(
                "SELECT status, failure_reason, error, attempt FROM pipeline_jobs "
                "WHERE application_id = ? ORDER BY id DESC LIMIT 1",
                (application_id,),
            ).fetchone()
        except Exception:  # noqa: BLE001 - legacy database may lack the table
            job_row = None
        try:
            progress_row = connection.execute(
                "SELECT status, percentage FROM pipeline_progress WHERE application_id = ?",
                (application_id,),
            ).fetchone()
        except Exception:  # noqa: BLE001 - legacy database may lack the table
            progress_row = None
        try:
            page_rows = (
                connection.execute(
                    "SELECT p.id, p.application_id, p.page_number, p.document_type, "
                    "p.page_type, p.classification_confidence, p.ocr_status, "
                    "p.extracted_fields, m.meta_json FROM pages p LEFT JOIN pages_meta m "
                    "ON m.application_id = p.application_id AND m.page_number = p.page_number "
                    "WHERE p.application_id = ? ORDER BY p.page_number",
                    (application_id,),
                ).fetchall()
                if include_pages
                else []
            )
        except Exception:  # noqa: BLE001 - legacy database may lack the table
            page_rows = []
        try:
            ground_truth = connection.execute(
                "SELECT raw_json FROM ground_truth WHERE application_id = ? "
                "ORDER BY extracted_at DESC LIMIT 1",
                (application_id,),
            ).fetchone()
        except Exception:  # noqa: BLE001 - legacy database may lack the table
            ground_truth = None

    anomalies = []
    for row in anomaly_rows:
        item = dict(row)
        evidence = item.get("evidence_json")
        if isinstance(evidence, str) and evidence:
            try:
                item["evidence_json"] = json.loads(evidence)
            except (TypeError, ValueError):
                item["evidence_json"] = None
        anomalies.append(item)

    pages = []
    for row in page_rows:
        page = dict(row)
        try:
            fields = json.loads(page.get("extracted_fields") or "{}")
        except (TypeError, ValueError):
            fields = {}
        fields = fields if isinstance(fields, dict) else {}
        try:
            meta = json.loads(page.pop("meta_json", None) or "{}")
        except (TypeError, ValueError):
            meta = {}
        if isinstance(meta, dict):
            fields.update({key: value for key, value in meta.items() if key.startswith("_")})
        page["extracted_fields"] = fields
        owner = fields.get("_ownership")
        if isinstance(owner, dict) and owner.get("person_id"):
            page["person_id"] = owner["person_id"]
        pages.append(page)

    try:
        checklist_context = json.loads(ground_truth["raw_json"] or "{}") if ground_truth else {}
    except (TypeError, ValueError):
        checklist_context = {}

    return {
        "application": application,
        "anomalies": anomalies,
        "job": dict(job_row) if job_row is not None else {},
        "progress": dict(progress_row) if progress_row is not None else {},
        "pages": pages,
        "checklist_context": checklist_context if isinstance(checklist_context, dict) else {},
    }
