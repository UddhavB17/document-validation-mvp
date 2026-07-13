"""Provider boundary for manual indexes and the future index-PDF format."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from services.verification_manifest import IndexedDocument, VerificationManifest
from services.company_data_provider import CompanyReferenceData


class DocumentIndexProvider(Protocol):
    def get_document_index(self, pdf_path: str | Path) -> list[IndexedDocument]:
        ...


class ManualDocumentIndexProvider:
    """Current demo adapter for a manually supplied page index."""

    def __init__(self, items: list[dict[str, Any] | IndexedDocument]) -> None:
        self.items = items

    def get_document_index(self, pdf_path: str | Path) -> list[IndexedDocument]:
        del pdf_path
        return [
            item if isinstance(item, IndexedDocument) else IndexedDocument.model_validate(item)
            for item in self.items
        ]


class IndexedPdfDocumentIndexProvider:
    """Future adapter placeholder until the company's index-PDF format is known."""

    def get_document_index(self, pdf_path: str | Path) -> list[IndexedDocument]:
        raise RuntimeError(
            "Index-PDF parsing is not configured. Map the supplied index format to "
            f"IndexedDocument records for {Path(pdf_path).name}."
        )


def compose_verification_manifest(
    reference: CompanyReferenceData,
    document_index: list[IndexedDocument],
) -> VerificationManifest:
    """Combine independently supplied company truth and page index."""
    return VerificationManifest(
        loan_id=reference.loan_id,
        product_type=reference.product_type,
        branch=reference.branch,
        people=reference.people,
        document_index=document_index,
        source=reference.source,
    )

