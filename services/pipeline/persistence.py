"""Database persistence helpers for pipeline outputs."""

from __future__ import annotations

import json
import os
from typing import Any

from database.db import get_connection

def _save_ground_truth(application_id: int, ground_truth: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM ground_truth WHERE application_id = ?", (application_id,))
        connection.execute(
            """
            INSERT INTO ground_truth (
                application_id,
                applicant_name,
                pan_number,
                loan_amount,
                phone,
                address,
                product_type,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                ground_truth.get("applicant_name"),
                ground_truth.get("pan_number"),
                ground_truth.get("loan_amount"),
                ground_truth.get("phone"),
                ground_truth.get("address"),
                ground_truth.get("product_type"),
                json.dumps(ground_truth, ensure_ascii=False),
            ),
        )

def _save_pages(application_id: int, pages: list[dict[str, Any]]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM pages WHERE application_id = ?", (application_id,))
        for page in pages:
            _insert_page(connection, application_id, page)

def _save_page_checkpoint(application_id: int, page: dict[str, Any]) -> None:
    """Persist one completed page atomically so a crash can resume after it."""
    page_number = int(page.get("page_number") or 0)
    if page_number < 1:
        return
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM pages WHERE application_id = ? AND page_number = ?",
            (application_id, page_number),
        )
        _insert_page(connection, application_id, page)

def _insert_page(connection: Any, application_id: int, page: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO pages (
            application_id, page_number, page_type, image_path, is_readable,
            ocr_text, ocr_confidence, ocr_route, ocr_escalated,
            ocr_processing_time_ms, structured_content, document_type,
            classification_confidence, detection_method, detected_page_number,
            extracted_fields
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            page.get("page_number"),
            page.get("page_type"),
            page.get("image_path"),
            page.get("is_readable") if page.get("is_readable") is not None else None,
            page.get("ocr_text"),
            page.get("ocr_confidence"),
            page.get("ocr_route"),
            bool(page.get("ocr_escalated", False)),
            int(page.get("ocr_processing_time_ms") or 0),
            json.dumps(page.get("structured_content"), ensure_ascii=False)
            if page.get("structured_content") is not None
            else None,
            page.get("document_type"),
            page.get("classification_confidence"),
            page.get("detection_method"),
            page.get("detected_page_number"),
            json.dumps(page.get("extracted_fields") or {}, ensure_ascii=False),
        ),
    )

def _load_page_checkpoints(application_id: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM pages WHERE application_id = ? ORDER BY page_number",
            (application_id,),
        ).fetchall()
    checkpoints: list[dict[str, Any]] = []
    for row in rows:
        page = dict(row)
        page["extracted_fields"] = _decode_json_object(page.get("extracted_fields"))
        page["structured_content"] = _decode_json_object(page.get("structured_content"))
        page["ocr_structure"] = page.get("structured_content") or {}
        checkpoints.append(page)
    return checkpoints

def _decode_json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}

def _update_uploaded_file_counts(application_id: int, structure: dict[str, Any]) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE uploaded_files
            SET total_pages = ?, digital_pages = ?, scanned_pages = ?
            WHERE application_id = ?
            """,
            (
                structure.get("total_pages"),
                structure.get("digital_pages"),
                structure.get("scanned_pages"),
                application_id,
            ),
        )

def _should_call_llm(generate_llm_summary: bool | None) -> bool:
    if generate_llm_summary is not None:
        return generate_llm_summary
    return os.getenv("ENABLE_LLM_SUMMARY", "").lower() in {"1", "true", "yes", "on"}

def _save_llm_summary(application_id: int, summary: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE applications SET llm_summary = ? WHERE id = ?",
            (summary, application_id),
        )
