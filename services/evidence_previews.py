"""Versioned page-preview assets derived from canonical source PDFs.

NEEDS-COORDINATION: the user explicitly authorized durable page previews to
solve slow evidence loading. This supersedes the current no-durable-images
constraint for these derived, retention-managed assets only.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import fitz

from services.storage import get_store
from services.storage.refs import get_ref, record_ref

LOGGER = logging.getLogger(__name__)
PAGE_PREVIEW_PURPOSE = "page_preview"
PAGE_PREVIEW_DPI = 150


def preview_version(source_version: str) -> str:
    """Return a filesystem-safe stable token for a source-reference version."""
    return hashlib.sha256(source_version.encode("utf-8")).hexdigest()[:16]


def preview_key(application_id: int, source_version: str, page_number: int) -> str:
    return (
        f"applications/{application_id}/previews/{preview_version(source_version)}"
        f"/page-{page_number:04d}.png"
    )


def source_version(application_id: int) -> str | None:
    ref = get_ref("applications", application_id, "source") or get_ref(
        "applications", application_id, "normalized_pdf"
    )
    if ref is None:
        return None
    return str(ref.get("created_at") or ref.get("storage_key") or "")


def generate_application_page_previews(
    pdf_path: str | Path,
    application_id: int,
) -> int:
    """Render and persist every page for one application."""
    version = source_version(application_id)
    if version is None:
        return 0

    document = fitz.open(str(pdf_path))
    rendered = 0
    try:
        store = get_store()
        for index in range(document.page_count):
            page_number = index + 1
            pixmap = document.load_page(index).get_pixmap(
                matrix=fitz.Matrix(PAGE_PREVIEW_DPI / 72.0, PAGE_PREVIEW_DPI / 72.0),
                alpha=False,
            )
            payload = bytes(pixmap.tobytes("png"))
            key = preview_key(application_id, version, page_number)
            store.put(key, payload, "image/png")
            record_ref(
                "applications",
                application_id,
                PAGE_PREVIEW_PURPOSE,
                key,
                content_type="image/png",
                size_bytes=len(payload),
            )
            rendered += 1
    finally:
        document.close()
    LOGGER.info(
        "Generated %d page previews for application %s at version %s",
        rendered,
        application_id,
        preview_version(version),
    )
    return rendered
