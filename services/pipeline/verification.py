"""Document verification stage helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from database.models import DocumentVerificationReport, GravitonRecord
from services.audit_service import log_action
from services.field_verification import verify_all_fields
from services.ocr_json_export import merge_public_extracted_fields
from services.progress_tracker import update_stage
from services.verification_pdf_parser import VerificationPdfParseError, parse_verification_pdf


def _verify_pipeline_documents(
    *,
    pdf_path: Path,
    application_id: int,
    pages: list[dict[str, Any]],
    ground_truth: dict[str, Any],
    mapped_manifest: dict[str, Any] | None,
    source_documents: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, DocumentVerificationReport | None, set[int] | None]:
    """Run either trusted-page comparison or the standard document verification."""
    if mapped_manifest is None:
        update_stage(application_id, "verifying_documents", "Comparing OCR fields with Graviton data")
        verification_report, document_page_numbers = _run_document_verification(
            pdf_path, application_id, pages, ground_truth
        )
        return None, verification_report, document_page_numbers

    automatic_index: dict[str, Any] | None = None
    if not (mapped_manifest.get("documents") or []):
        from services.automatic_document_index import build_automatic_document_index

        automatic_index = build_automatic_document_index(
            pages,
            mapped_manifest.get("reference_data") or {},
            source_documents=source_documents,
        )
        mapped_manifest = {**mapped_manifest, "documents": automatic_index["documents"]}

    update_stage(
        application_id,
        "verifying_mapped_documents",
        "Comparing automatically identified documents with trusted JSON",
    )
    from services.mapped_verification import compare_processed_pages

    mapped_result = compare_processed_pages(
        pages,
        mapped_manifest,
        source_documents=source_documents,
    )
    if automatic_index is not None:
        mapped_result["anomalies"] = [
            *automatic_index["anomalies"],
            *mapped_result["anomalies"],
        ]
        mapped_result["automatic_document_index"] = automatic_index["documents"]
        mapped_result["unclassified_pages"] = automatic_index["unclassified_pages"]

    document_page_numbers = {
        int(number)
        for document in mapped_manifest.get("documents") or []
        for number in document.get("pages") or []
    }
    return mapped_result, None, document_page_numbers


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
