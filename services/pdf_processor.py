"""PDF structure detection for DMEF loan-file processing.

Responsibilities
----------------
- Open a PDF with PyMuPDF (fitz).
- Classify each page as *digital* (selectable text) or *scanned* (image-only).
- Rasterise scanned pages to PNG for downstream OCR.
- Return a structured summary of the whole document.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import fitz  # PyMuPDF

from services.config import get_float, get_int
from services.image_limits import downscale_if_needed, max_image_side_px
from services.processing_policy import selected_scanned_page_numbers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_pdf(pdf_path: str | Path) -> fitz.Document:
    """Open a PDF file and return a :class:`fitz.Document`.

    Parameters
    ----------
    pdf_path:
        Filesystem path to the PDF.

    Returns
    -------
    fitz.Document
        The opened document.  The caller is responsible for closing it.

    Raises
    ------
    FileNotFoundError
        If *pdf_path* does not exist.
    ValueError
        If the file cannot be opened as a PDF (corrupted / wrong type).
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ValueError(f"Could not open PDF '{path}': {exc}") from exc
    return doc


def detect_page_type(fitz_page: fitz.Page) -> str:
    """Classify a single PDF page as *digital* or *scanned*.

    A page is considered *digital* when it contains more than 50 characters of
    selectable text; otherwise it is treated as *scanned* (image-only).

    Parameters
    ----------
    fitz_page:
        A :class:`fitz.Page` object obtained from an open document.

    Returns
    -------
    str
        ``"digital"`` or ``"scanned"``.
    """
    text = fitz_page.get_text().strip()
    return "digital" if len(text) > 50 else "scanned"


def convert_page_to_image(fitz_page: fitz.Page, output_path: str | Path) -> str:
    """Render a PDF page to a PNG image for downstream OCR.

    Parameters
    ----------
    fitz_page:
        The page to rasterise.
    output_path:
        Destination path for the PNG file (parent directories are created
        automatically if they do not exist).

    Returns
    -------
    str
        The absolute path of the saved PNG file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    scale = get_float("DMEF_RENDER_SCALE", 1.0, minimum=0.75, maximum=2.0)
    matrix = fitz.Matrix(scale, scale)
    pixmap = fitz_page.get_pixmap(matrix=matrix, alpha=False)

    import cv2
    import numpy as np

    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    if pixmap.n == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
    elif pixmap.n == 1:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    image = downscale_if_needed(image, max_side=max_image_side_px())
    cv2.imwrite(str(output_path), image)
    return str(output_path.resolve())


# ---------------------------------------------------------------------------
# Internal TypedDict helpers
# ---------------------------------------------------------------------------


class _PageInfo(TypedDict):
    page_number: int
    page_type: str
    image_path: str | None


class _PdfStructure(TypedDict):
    total_pages: int
    digital_pages: int
    scanned_pages: int
    pages: list[_PageInfo]


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def process_pdf_structure(
    pdf_path: str | Path,
    output_dir: str | Path,
) -> _PdfStructure:
    """Analyse a PDF and export scanned pages as PNG images.

    Parameters
    ----------
    pdf_path:
        Path to the source PDF file.
    output_dir:
        Directory where PNG images for scanned pages will be written.  The
        directory is created automatically when needed.

    Returns
    -------
    dict
        A mapping with the following keys:

        ``total_pages`` – total number of pages in the document.

        ``digital_pages`` – count of pages with selectable text.

        ``scanned_pages`` – count of image-only (scanned) pages.

        ``pages`` – list of per-page dicts, each with:

            ``page_number`` (1-based ``int``),
            ``page_type`` (``"digital"`` or ``"scanned"``),
            ``image_path`` (absolute ``str`` for scanned pages, ``None`` for
            digital pages).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_stem = Path(pdf_path).stem
    doc = open_pdf(pdf_path)

    pages: list[_PageInfo] = []
    digital_pages = 0
    scanned_pages = 0
    total_pages = doc.page_count  # capture before close

    try:
        for index in range(total_pages):
            page = doc[index]
            page_number = index + 1  # 1-based
            page_type = detect_page_type(page)

            if page_type == "scanned":
                scanned_pages += 1
            else:
                digital_pages += 1

            pages.append(
                {
                    "page_number": page_number,
                    "page_type": page_type,
                    "image_path": None,
                }
            )

        selected_scanned_pages = selected_scanned_page_numbers(pages)
        for page_info in pages:
            page_number = int(page_info["page_number"])
            if page_info["page_type"] != "scanned" or page_number not in selected_scanned_pages:
                continue
            page = doc[page_number - 1]
            filename = f"{pdf_stem}_page_{page_number:04d}.png"
            page_info["image_path"] = convert_page_to_image(page, output_dir / filename)
    finally:
        doc.close()

    return {
        "total_pages": total_pages,
        "digital_pages": digital_pages,
        "scanned_pages": scanned_pages,
        "pages": pages,
    }
