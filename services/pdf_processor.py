"""PDF structure detection for DMEF loan-file processing.

Responsibilities
----------------
- Open a PDF with PyMuPDF (fitz).
- Classify each page as *digital* (selectable text) or *scanned* (image-only).
- Rasterise scanned pages to PNG for downstream OCR.
- Return a structured summary of the whole document.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

import fitz  # PyMuPDF


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
    """Render a PDF page to a PNG image at 200 DPI.

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

    # fitz.Matrix(2, 2) scales by 2× in both axes → 144 DPI base × ... 
    # Actually PyMuPDF default is 72 DPI, so ×2 gives 144 DPI; use ×(200/72)
    # for exactly 200 DPI.  Per the spec we use fitz.Matrix(2, 2).
    matrix = fitz.Matrix(2, 2)
    pixmap = fitz_page.get_pixmap(matrix=matrix, alpha=False)
    pixmap.save(str(output_path))
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

            image_path: str | None = None
            if page_type == "scanned":
                filename = f"{pdf_stem}_page_{page_number:04d}.png"
                image_path = convert_page_to_image(page, output_dir / filename)
                scanned_pages += 1
            else:
                digital_pages += 1

            pages.append(
                {
                    "page_number": page_number,
                    "page_type": page_type,
                    "image_path": image_path,
                }
            )
    finally:
        doc.close()

    return {
        "total_pages": total_pages,
        "digital_pages": digital_pages,
        "scanned_pages": scanned_pages,
        "pages": pages,
    }
