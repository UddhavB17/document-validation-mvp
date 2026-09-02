"""Document verification against Graviton reference data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database.models import DocumentVerificationReport, GravitonRecord
from services.audit_service import log_action
from services.field_verification import verify_all_fields
from services.ocr_json_export import merge_public_extracted_fields
from services.verification_pdf_parser import VerificationPdfParseError, parse_verification_pdf

def _stamp_pages_from_document_index(
    pages: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> None:
    """Copy automatic/ZIP document ownership onto the matching page records."""
    by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if page.get("page_number") is not None
    }
    for document in documents:
        person_id = str(document.get("applicant_role") or document.get("person_id") or "").strip()
        if not person_id or person_id in {"unassigned", "unknown"}:
            continue
        multi_person = bool((document.get("auto_mapping") or {}).get("multi_person_document"))
        for page_number in document.get("pages") or []:
            page = by_number.get(int(page_number))
            if page is None:
                continue
            # Application forms and CAMs contain several people.  Keep any
            # page/record-level ownership already resolved instead of stamping
            # every page as the primary applicant merely because the document
            # container is indexed under primary.
            if not multi_person:
                page["person_id"] = person_id
                page["applicant_role"] = person_id
            fields = page.get("extracted_fields")
            if isinstance(fields, dict):
                fields = dict(fields)
                ownership = dict(fields.get("_ownership") or {})
                if not multi_person:
                    ownership["person_id"] = person_id
                ownership.update({
                    "document_scope": "multi_person" if multi_person else "single_person",
                    "evidence": list(ownership.get("evidence") or []) + ["document_index"],
                })
                fields["_ownership"] = ownership
                page["extracted_fields"] = fields

def _run_document_verification(
    pdf_path: Path,
    application_id: int,
    pages: list[dict[str, Any]],
    ground_truth: dict[str, Any],
) -> tuple[DocumentVerificationReport | None, set[int] | None]:
    used_fallback = False
    try:
        graviton_record, document_pages = parse_verification_pdf(str(pdf_path))
        document_page_numbers = {int(page["page_number"]) for page in document_pages}
    except VerificationPdfParseError as exc:
        try:
            graviton_record = GravitonRecord.model_validate(ground_truth)
        except ValueError as fallback_exc:
            log_action(
                application_id,
                "verification_skipped",
                {
                    "reason": str(exc),
                    "fallback_reason": str(fallback_exc),
                    "pdf_path": str(pdf_path),
                },
            )
            return None, None
        used_fallback = True
        document_page_numbers = {
            int(page.get("page_number") or 0)
            for page in pages
            if str(page.get("document_type") or "") != "DB Data"
        }

    document_only_pages = [
        page
        for page in pages
        if int(page.get("page_number") or 0) in document_page_numbers
    ]
    extracted_fields = merge_public_extracted_fields(document_only_pages)
    report = verify_all_fields(extracted_fields, graviton_record)
    log_action(
        application_id,
        "verification_completed",
        {
            "graviton_application_id": graviton_record.application_id,
            "document_page_count": len(document_page_numbers),
            "overall_match": report.overall_match,
            "match_percentage": report.match_percentage,
            "needs_manual_review": report.needs_manual_review,
            "db_data_source": "digital_pages" if used_fallback else "verification_pdf_parser",
        },
    )
    return report, document_page_numbers
