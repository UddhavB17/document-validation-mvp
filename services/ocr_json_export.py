"""Build and persist OCR document JSON exports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.field_assignment_refiner import is_suspicious_assignment


def build_ocr_document_json(
    application_id: int,
    pages: list[dict[str, Any]],
    *,
    document_page_numbers: set[int] | None = None,
    page_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert OCR-processed document pages into comparison-ready JSON."""
    selected_pages = _select_document_pages(pages, document_page_numbers)
    page_events_by_number = _page_events_by_number(page_events or [])
    documents = [
        _page_to_document_json(page, page_events_by_number.get(int(page.get("page_number") or 0)))
        for page in selected_pages
    ]
    return {
        "application_id": application_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "document_page_count": len(documents),
        "combined_extracted_fields": merge_public_extracted_fields(selected_pages),
        "documents": documents,
    }


def save_ocr_document_json(
    application_id: int,
    pages: list[dict[str, Any]],
    output_dir: str | Path = "data/processed",
    *,
    document_page_numbers: set[int] | None = None,
    page_events: list[dict[str, Any]] | None = None,
) -> Path:
    """Save OCR document-page JSON for later review or download."""
    export_payload = build_ocr_document_json(
        application_id,
        pages,
        document_page_numbers=document_page_numbers,
        page_events=page_events,
    )
    target_dir = Path(output_dir) / f"application_{application_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "document_ocr_data.json"
    with target_path.open("w", encoding="utf-8") as file:
        json.dump(export_payload, file, indent=2, ensure_ascii=False)
    return target_path


def merge_public_extracted_fields(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge non-private extracted OCR fields in page order."""
    merged: dict[str, Any] = {}
    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        fields = page.get("extracted_fields") or {}
        if not isinstance(fields, dict):
            continue
        for field_name, value in fields.items():
            if str(field_name).startswith("_") or value in (None, ""):
                continue
            if is_suspicious_assignment(str(field_name), value):
                continue
            merged.setdefault(str(field_name), value)
    return merged


def _select_document_pages(
    pages: list[dict[str, Any]],
    document_page_numbers: set[int] | None,
) -> list[dict[str, Any]]:
    sorted_pages = sorted(pages, key=lambda item: int(item.get("page_number") or 0))
    if document_page_numbers is None:
        return sorted_pages
    return [
        page
        for page in sorted_pages
        if int(page.get("page_number") or 0) in document_page_numbers
    ]


def _page_events_by_number(page_events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(event["page_number"]): event
        for event in page_events
        if event.get("page_number") is not None
    }


def _page_to_document_json(page: dict[str, Any], event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = event or {}
    fields = page.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    fields = _json_safe(fields)
    page_details = _json_safe(page)
    processing_event = _json_safe(event)
    return {
        "page_number": page.get("page_number"),
        "page_type": page.get("page_type"),
        "total_pages": event.get("total_pages"),
        "status": event.get("status") or page.get("status") or "completed",
        "document_type": page.get("document_type") or "Unknown",
        "llm_document_type": _llm_document_type(fields),
        "image_path": page.get("image_path"),
        "is_readable": page.get("is_readable"),
        "ocr_confidence": page.get("ocr_confidence"),
        "classification_confidence": page.get("classification_confidence"),
        "detection_method": page.get("detection_method"),
        "detected_page_number": page.get("detected_page_number"),
        "elapsed_seconds": event.get("elapsed_seconds") or page.get("elapsed_seconds"),
        "completed_at": event.get("completed_at") or page.get("completed_at"),
        "error": event.get("error") or page.get("error"),
        "ocr_text": page.get("ocr_text") or "",
        "extracted_fields": fields,
        "page_details": page_details,
        "processing_event": processing_event,
    }


def _llm_document_type(fields: dict[str, Any]) -> str | None:
    result = fields.get("_structured_llm_classification")
    if not isinstance(result, dict):
        return None
    document_type = str(result.get("document_type") or "").strip()
    return document_type or None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
