"""Ground-truth text and field extraction from DIGITAL PDF pages.

Only pages whose selectable-text length exceeds 50 characters are considered
*digital* and processed here.  Scanned pages are skipped – they are handled
by the OCR pipeline instead.

Public API
----------
extract_digital_text(fitz_page)
    Return the stripped text of a single digital page, or an empty string for
    scanned pages.

extract_ground_truth(pdf_path)
    Open a PDF, concatenate text from all digital pages, and return a dict of
    structured fields extracted with regex and safe fallbacks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIGITAL_THRESHOLD = 50  # characters; mirrors pdf_processor.detect_page_type

# PAN: 5 uppercase letters, 4 digits, 1 uppercase letter
_PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b")

# Indian mobile numbers: start with 6-9, followed by 9 more digits
_PHONE_RE = re.compile(r"\b([6-9]\d{9})\b")


# ---------------------------------------------------------------------------
# Internal TypedDict
# ---------------------------------------------------------------------------


class _GroundTruth(TypedDict):
    applicant_name: str | None
    pan_number: str | None
    loan_amount: str | None
    phone: str | None
    address: str | None
    product_type: str | None
    raw_text: str


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def extract_digital_text(fitz_page: fitz.Page) -> str:
    """Return the stripped text of *fitz_page* if it is a digital page.

    Parameters
    ----------
    fitz_page:
        A :class:`fitz.Page` obtained from an open :class:`fitz.Document`.

    Returns
    -------
    str
        Stripped page text when the page is digital (``len(text) > 50``),
        or an empty string when the page is scanned / blank.
    """
    text = fitz_page.get_text().strip()
    return text if len(text) > _DIGITAL_THRESHOLD else ""


def extract_ground_truth(pdf_path: str | Path) -> _GroundTruth:
    """Extract structured ground-truth fields from a PDF's digital pages.

    Parameters
    ----------
    pdf_path:
        Filesystem path to the PDF.

    Returns
    -------
    dict
        Keys:

        ``applicant_name`` – name found after "applicant name", "borrower
        name", or "name of applicant" labels.

        ``pan_number`` – first PAN matching ``[A-Z]{5}[0-9]{4}[A-Z]``.

        ``loan_amount`` – digits after "loan amount" or "amount requested"
        (commas removed, returned as a string).

        ``phone`` – first 10-digit mobile number starting with 6–9.

        ``address`` – up to 3 lines following an "address" keyword.

        ``product_type`` – line containing LAP, MSME, or "Personal Loan".

        ``raw_text`` – full concatenated digital text from the document.

    Notes
    -----
    Every individual field extraction is wrapped in ``try/except`` so that
    messy, malformed, or empty text never raises.
    """
    path = Path(pdf_path)
    doc = fitz.open(path)

    digital_parts: list[str] = []
    try:
        for page in doc:
            chunk = extract_digital_text(page)
            if chunk:
                digital_parts.append(chunk)
    finally:
        doc.close()

    raw_text = "\n".join(digital_parts)

    return {
        "applicant_name": _safe_extract(_extract_applicant_name, raw_text),
        "pan_number":     _safe_extract(_extract_pan_number,     raw_text),
        "loan_amount":    _safe_extract(_extract_loan_amount,    raw_text),
        "phone":          _safe_extract(_extract_phone,          raw_text),
        "address":        _safe_extract(_extract_address,        raw_text),
        "product_type":   _safe_extract(_extract_product_type,   raw_text),
        "raw_text":       raw_text,
    }


# ---------------------------------------------------------------------------
# Internal extraction helpers
# ---------------------------------------------------------------------------


def _safe_extract(fn, text: str) -> str | None:
    """Call *fn(text)* and return ``None`` on any exception."""
    try:
        return fn(text)
    except Exception:  # noqa: BLE001
        return None


def _extract_applicant_name(text: str) -> str | None:
    """Return the value following an applicant-name label."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:20]):
        if not line.lower().startswith("for "):
            continue
        header_window = " ".join(lines[max(0, i - 3):i]).lower()
        if "credit information" not in header_window:
            continue
        candidate = _clean_name_candidate(line[4:])
        if candidate:
            return candidate

    labels = (
        "applicant name",
        "borrower name",
        "name of applicant",
        "consumer name",
        "name",
    )
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(label in line_lower for label in labels):
            # Value may appear after a colon on the same line
            colon_parts = re.split(r"[:\-–]", line, maxsplit=1)
            if len(colon_parts) == 2 and colon_parts[1].strip():
                candidate = _clean_name_candidate(colon_parts[1])
                if candidate:
                    return candidate
            # Otherwise take the next non-empty line
            for j in range(i + 1, len(lines)):
                candidate = _clean_name_candidate(lines[j])
                if candidate:
                    return candidate
    return None


def _clean_name_candidate(value: str) -> str | None:
    candidate = value.strip(" :\t\r\n")
    if not candidate:
        return None

    labels = {
        "applicant name",
        "borrower name",
        "name of applicant",
        "consumer name",
        "name",
        "आवेदक का नाम",
        "नाम",
    }
    if candidate.lower() in labels or candidate in labels:
        return None
    if re.search(r"(?:mobile|phone|pan|aadhaar|loan|amount|date|address)", candidate, re.IGNORECASE):
        return None
    if len(candidate) > 80:
        return None
    return candidate


def _extract_pan_number(text: str) -> str | None:
    """Return the first PAN number found in *text*."""
    match = _PAN_RE.search(text)
    return match.group(1) if match else None


def _extract_loan_amount(text: str) -> str | None:
    """Return digits-only loan amount following a loan-amount label."""
    pattern = re.compile(
        r"(?:loan\s+amount|amount\s+requested)\s*[:\-–]?\s*"
        r"(?:rs\.?|₹|inr)?\s*([\d,]+)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        return re.sub(r"[^\d]", "", match.group(1))
    return None


def _extract_phone(text: str) -> str | None:
    """Return the first valid 10-digit Indian mobile number."""
    match = _PHONE_RE.search(text)
    return match.group(1) if match else None


def _extract_address(text: str, max_lines: int = 3) -> str | None:
    """Return up to *max_lines* lines following an "address" keyword."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "address" in line.lower():
            # Value may be on the same line after a colon
            colon_parts = re.split(r"[:\-–]", line, maxsplit=1)
            collected: list[str] = []
            if len(colon_parts) == 2 and colon_parts[1].strip():
                collected.append(colon_parts[1].strip())
            # Gather subsequent non-empty lines up to max_lines total
            for j in range(i + 1, len(lines)):
                if len(collected) >= max_lines:
                    break
                part = lines[j].strip()
                if part:
                    collected.append(part)
            return " ".join(collected) if collected else None
    return None


def _extract_product_type(text: str) -> str | None:
    """Return the first line that mentions LAP, MSME, or Personal Loan."""
    pattern = re.compile(r"\b(LAP|MSME|Personal\s+Loan)\b", re.IGNORECASE)
    for line in text.splitlines():
        if pattern.search(line):
            return line.strip()
    return None
