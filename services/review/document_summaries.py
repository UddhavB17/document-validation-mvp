"""Document summary rows for the application review overview."""

from __future__ import annotations

from typing import Any

from services.review.types import DocumentStatus, DocumentSummary


def build_document_summaries(
    document_pages: dict[str, list[int]],
    anomalies: list[dict[str, Any]],
) -> list[DocumentSummary]:
    """Build sorted document summary rows and flag documents with anomalies."""
    summaries: list[DocumentSummary] = []
    for document_type, page_numbers in document_pages.items():
        if not page_numbers:
            continue
        sorted_page_numbers = sorted(int(page) for page in page_numbers)
        first_page = sorted_page_numbers[0]
        if len(sorted_page_numbers) > 1:
            page_range = f"{sorted_page_numbers[0]}–{sorted_page_numbers[-1]}"
        else:
            page_range = str(sorted_page_numbers[0])

        # A document is flagged when any validation anomaly points to one of its pages.
        document_status: DocumentStatus = "Extracted"
        for anomaly in anomalies:
            anomaly_page_number = anomaly.get("page_number")
            if anomaly_page_number is not None and int(anomaly_page_number) in sorted_page_numbers:
                document_status = "Flagged"
                break

        document_filename = f"{document_type.lower().replace(' ', '_')}.pdf"
        summaries.append(
            {
                "name": document_filename,
                "type": document_type,
                "pages": page_range,
                "status": document_status,
                "firstPage": first_page,
            }
        )
    summaries.sort(key=lambda summary: summary["firstPage"])
    return summaries
