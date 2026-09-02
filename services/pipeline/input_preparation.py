"""PDF input preparation and unsupported-input handling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from services.text_extractor import extract_digital_text
from services.pipeline.page_details import _build_db_data_fields, _is_starting_json_db_page

def _mapped_ground_truth(
    manifest: dict[str, Any],
    system_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten primary trusted data for checklist/report compatibility."""
    reference_data = manifest.get("reference_data") or {}
    primary = reference_data.get("primary") if isinstance(reference_data, dict) else {}
    primary = primary if isinstance(primary, dict) else {}
    return {
        **{key: value for key, value in manifest.items() if key not in {"documents", "reference_data"}},
        **(system_data or {}),
        **primary,
        "loan_id": manifest.get("loan_id") or (system_data or {}).get("loan_id"),
        "product_type": manifest.get("product_type") or (system_data or {}).get("product_type") or "LAP",
        "reference_data": reference_data,
    }

def _extract_digital_text_by_page(pdf_path: Path) -> dict[int, str]:
    doc = fitz.open(pdf_path)
    try:
        return {
            page_number: text
            for page_number, page in enumerate(doc, start=1)
            if (text := extract_digital_text(page))
        }
    finally:
        doc.close()

def _checklist_processing_metadata(progress_snapshot: dict[str, Any]) -> dict[str, int]:
    completed_pages = progress_snapshot.get("completed_pages") or []
    ocr_time_ms = int(
        sum(float(page.get("elapsed_seconds") or 0) for page in completed_pages) * 1000
    )
    return {
        "ocr_time_ms": ocr_time_ms,
        "classification_time_ms": 0,
        "narration_time_ms": 0,
    }

def _build_unsupported_page_records(
    page_structure: list[dict[str, Any]],
    digital_text_by_page: dict[int, str],
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_info in page_structure:
        page_number = int(page_info["page_number"])
        page_type = page_info["page_type"]
        text = digital_text_by_page.get(page_number, "")
        is_db_data = page_type == "digital" and _is_starting_json_db_page(page_number=page_number, text=text)
        document_type = "DB Data" if is_db_data else "Unknown"
        pages.append(
            {
                "page_number": page_number,
                "page_type": page_type,
                "image_path": page_info.get("image_path"),
                "is_readable": bool(text),
                "ocr_text": text,
                "ocr_confidence": None,
                "document_type": document_type,
                "classification_confidence": 1.0 if is_db_data else 0.0,
                "detection_method": "db_data" if is_db_data else "unknown",
                "detected_page_number": page_number if is_db_data else None,
                "extracted_fields": _build_db_data_fields(page_number=page_number, text=text) if is_db_data else {},
            }
        )
    return pages
