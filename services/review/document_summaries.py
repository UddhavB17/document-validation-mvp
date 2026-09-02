"""Document summary rows for the application review overview."""

from __future__ import annotations

from services.review.types import DocumentSummary


def build_document_summaries(
    document_pages: dict[str, list[int]],
    anomalies: list[dict[str, object]],
) -> list[DocumentSummary]:
    documents: list[DocumentSummary] = []
    for doc_type, pages_arr in document_pages.items():
        if not pages_arr:
            continue
        sorted_pages = sorted(int(page) for page in pages_arr)
        first_page = sorted_pages[0]
        if len(sorted_pages) > 1:
            page_range = f"{sorted_pages[0]}–{sorted_pages[-1]}"
        else:
            page_range = str(sorted_pages[0])

        doc_status: str = "Extracted"
        for anomaly in anomalies:
            vr_page = anomaly.get("page_number")
            if vr_page is not None and int(vr_page) in sorted_pages:
                doc_status = "Flagged"
                break

        filename = f"{doc_type.lower().replace(' ', '_')}.pdf"
        documents.append(
            {
                "name": filename,
                "type": doc_type,
                "pages": page_range,
                "status": doc_status,  # type: ignore[typeddict-item]
                "firstPage": first_page,
            }
        )
    documents.sort(key=lambda document: document["firstPage"])
    return documents
