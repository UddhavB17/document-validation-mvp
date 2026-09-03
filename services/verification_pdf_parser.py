"""Parser for Graviton-backed document verification PDFs.

Expected format:
- first 1-3 pages contain Graviton JSON ground-truth data;
- remaining pages contain scanned verification document images.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import fitz
from pydantic import ValidationError

from database.models import GravitonRecord
from services.pdf_processor import open_pdf

_MAX_GRAVITON_JSON_PAGES = 3
_RENDER_DPI = 200


class VerificationPdfParseError(ValueError):
    """Base exception for verification PDF parsing failures."""


class GravitonJsonNotFoundError(VerificationPdfParseError):
    """Raised when no parseable Graviton JSON block is found in the PDF."""


class GravitonJsonMalformedError(VerificationPdfParseError):
    """Raised when the Graviton JSON text is present but malformed."""


class GravitonJsonValidationError(VerificationPdfParseError):
    """Raised when parsed Graviton JSON does not satisfy GravitonRecord."""


class DocumentPageExtractionError(VerificationPdfParseError):
    """Raised when scanned document pages cannot be rendered."""


def extract_graviton_json(pdf_path: str) -> GravitonRecord:
    """Extract and validate Graviton ground-truth JSON from the first pages.

    The parser reads up to the first three PDF pages, supports JSON spanning
    multiple pages, and returns a validated :class:`GravitonRecord`.
    """
    record, _end_page = _extract_graviton_record_and_end_page(pdf_path)
    return record


def extract_document_pages(pdf_path: str, start_page: int) -> list[dict]:
    """Render PDF pages from ``start_page`` onward as base64 PNG images.

    Args:
        pdf_path: Path to the verification PDF.
        start_page: One-based page number where scanned documents begin.

    Returns:
        A list of dictionaries shaped as
        ``{"page_number": int, "image_base64": str, "page_type": "unknown"}``.
    """
    if start_page < 1:
        raise DocumentPageExtractionError("start_page must be a 1-based page number")

    doc = open_pdf(pdf_path)
    try:
        if start_page > doc.page_count + 1:
            raise DocumentPageExtractionError(
                f"start_page {start_page} is beyond PDF page count {doc.page_count}"
            )

        document_pages: list[dict] = []
        matrix = fitz.Matrix(_RENDER_DPI / 72, _RENDER_DPI / 72)
        for page_index in range(start_page - 1, doc.page_count):
            page_number = page_index + 1
            try:
                pixmap = doc[page_index].get_pixmap(matrix=matrix, alpha=False)
                image_base64 = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
            except RuntimeError as exc:
                raise DocumentPageExtractionError(
                    f"Could not render document page {page_number}: {exc}"
                ) from exc

            document_pages.append(
                {
                    "page_number": page_number,
                    "image_base64": image_base64,
                    "page_type": "unknown",
                }
            )
        return document_pages
    finally:
        doc.close()


def parse_verification_pdf(pdf_path: str) -> tuple[GravitonRecord, list[dict]]:
    """Parse a complete document verification PDF.

    This function auto-detects where Graviton JSON ends by accumulating text
    from the first pages until a valid ``GravitonRecord`` can be built.  Pages
    after that valid JSON block are returned as base64-encoded images.
    """
    record, json_end_page = _extract_graviton_record_and_end_page(pdf_path)
    document_pages = extract_document_pages(pdf_path, start_page=json_end_page + 1)
    return record, document_pages


def _extract_graviton_record_and_end_page(pdf_path: str) -> tuple[GravitonRecord, int]:
    path = Path(pdf_path)
    if not path.exists():
        raise GravitonJsonNotFoundError(f"Verification PDF not found: {path}")

    doc = open_pdf(path)
    try:
        max_pages = min(_MAX_GRAVITON_JSON_PAGES, doc.page_count)
        if max_pages == 0:
            raise GravitonJsonNotFoundError("Verification PDF has no pages")

        collected_text: list[str] = []
        last_parse_error: Exception | None = None
        for page_index in range(max_pages):
            page_number = page_index + 1
            page_text = doc[page_index].get_text().strip()
            if not page_text:
                if collected_text:
                    break
                continue

            collected_text.append(page_text)
            candidate_text = "\n".join(collected_text)
            try:
                payload = _extract_json_payload(candidate_text)
                return _validate_graviton_payload(payload, page_number), page_number
            except GravitonJsonMalformedError as exc:
                last_parse_error = exc
                continue
            except GravitonJsonValidationError:
                raise

        if last_parse_error is not None:
            raise GravitonJsonMalformedError(
                f"Could not parse Graviton JSON from first {max_pages} page(s): {last_parse_error}"
            ) from last_parse_error
        raise GravitonJsonNotFoundError(f"No Graviton JSON text found in first {max_pages} page(s)")
    finally:
        doc.close()


def _extract_json_payload(text: str) -> dict[str, Any]:
    """Extract the first JSON object embedded in page text."""
    stripped = text.strip()
    if not stripped:
        raise GravitonJsonMalformedError("Graviton JSON text is empty")

    decoder = json.JSONDecoder()
    start_positions = [index for index, char in enumerate(stripped) if char == "{"]
    if not start_positions:
        raise GravitonJsonMalformedError("No JSON object start '{' found")

    errors: list[str] = []
    for start in start_positions:
        try:
            payload, _end = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError as exc:
            errors.append(f"position {start}: {exc.msg}")
            continue
        if not isinstance(payload, dict):
            raise GravitonJsonMalformedError("Graviton JSON root must be an object")
        return payload

    details = "; ".join(errors[-3:]) if errors else "unknown JSON parse error"
    raise GravitonJsonMalformedError(details)


def _validate_graviton_payload(payload: dict[str, Any], page_number: int) -> GravitonRecord:
    try:
        return GravitonRecord.model_validate(payload)
    except ValidationError as exc:
        raise GravitonJsonValidationError(
            f"Graviton JSON ending on page {page_number} failed validation: {exc}"
        ) from exc
