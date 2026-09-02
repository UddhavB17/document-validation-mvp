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

import json
import re
from pathlib import Path
from typing import Any, TypedDict, cast

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


class _LayoutCell(TypedDict):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int


_NAME_LABELS_PRIORITY: tuple[str, ...] = (
    "applicant name",
    "borrower name",
    "name of applicant",
    "consumer name",
    "name",
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def clean_xml_and_metadata(text: str) -> str:
    """Filter out XML signature tags, certificate structures and base64 strings."""
    if not text:
        return ""
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip XML signature tags and signature metadata keywords
        if any(
            tag in stripped
            for tag in (
                "X509Certificate",
                "X509SubjectName",
                "X509Data",
                "SignatureValue",
                "DigestValue",
                "Signature",
                "SignedInfo",
                "KeyInfo",
                "CanonicalizationMethod",
                "SignatureMethod",
                "Transform",
                "DigestMethod",
            )
        ):
            continue
        # Strip standard XML tags
        line_no_xml = re.sub(r"<[^>]+>", "", line).strip()
        if not line_no_xml and line.strip():
            continue
        # Skip base64-encoded strings (often > 60 chars without whitespace, alphanumeric + / = )
        if len(line_no_xml) > 60 and " " not in line_no_xml:
            if re.match(r"^[A-Za-z0-9+/=]+$", line_no_xml):
                continue
        cleaned_lines.append(line_no_xml)
    return "\n".join(cleaned_lines).strip()


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
    cleaned = clean_xml_and_metadata(text)
    return cleaned if len(cleaned) > _DIGITAL_THRESHOLD else ""


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
    layout_cells: list[_LayoutCell] = []
    try:
        for page_index, page in enumerate(doc):
            chunk = extract_digital_text(page)
            if chunk:
                digital_parts.append(chunk)
                layout_cells.extend(_page_layout_cells(page, page_index))
    finally:
        doc.close()

    raw_text = "\n".join(digital_parts)
    json_payload = _extract_json_payload(raw_text)
    flattened_json = _flatten_json_payload(json_payload)

    result: dict[str, Any] = dict(flattened_json)
    result.update(
        {
            "applicant_name": _json_value(
                flattened_json, "applicant_name", "applicant.name", "borrower_name", "name"
            )
            or _extract_applicant_name_full(layout_cells, raw_text),
            "pan_number": _json_value(
                flattened_json, "pan_number", "pan", "applicant.pan_number", "applicant.pan"
            )
            or _safe_extract(_extract_pan_number, raw_text),
            "loan_amount": _json_value(
                flattened_json, "loan_amount", "amount", "requested_amount", "sanctioned_amount"
            )
            or _safe_extract(_extract_loan_amount, raw_text),
            "phone": _json_value(flattened_json, "phone", "phone_number", "mobile", "mobile_number")
            or _safe_extract(_extract_phone, raw_text),
            "address": _json_value(flattened_json, "address", "applicant.address")
            or _safe_extract(_extract_address, raw_text),
            "product_type": _json_value(flattened_json, "product_type", "loan_type", "product")
            or _safe_extract(_extract_product_type, raw_text),
            "raw_text": raw_text,
            "db_data_json": json_payload,
        }
    )
    return cast(_GroundTruth, result)


# ---------------------------------------------------------------------------
# Internal extraction helpers
# ---------------------------------------------------------------------------


def _safe_extract(fn, text: str) -> str | None:
    """Call *fn(text)* and return ``None`` on any exception."""
    try:
        return fn(text)
    except Exception:  # noqa: BLE001
        return None


def _extract_json_payload(text: str) -> dict[str, Any]:
    """Return the first JSON object found in digital DB-data text."""
    stripped = str(text or "").strip()
    if not stripped:
        return {}
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _flatten_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_key = f"{prefix}.{key}" if prefix else str(key)
                visit(child_key, item)
            return
        if isinstance(value, list):
            flattened[prefix] = value
            return
        flattened[prefix] = value

    visit("", payload or {})
    return flattened


def _json_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _extract_applicant_name_full(layout_cells: list[_LayoutCell], raw_text: str) -> str | None:
    try:
        name = _extract_applicant_name_by_layout(layout_cells)
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return _safe_extract(_extract_applicant_name, raw_text)


def _extract_applicant_name(text: str) -> str | None:
    """Return the value following an applicant-name label."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:20]):
        if not line.lower().startswith("for "):
            continue
        header_window = " ".join(lines[max(0, i - 3) : i]).lower()
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
        "gender",
        "sex",
        "date of birth",
        "c/o",
        "s/o",
        "d/o",
        "w/o",
        "c/o , s/o",
        "marital status",
        "landmark",
        "locality",
        "city / district",
        "pin code",
        "state",
        "nationality",
        "category",
        "occupation",
        "email",
        "masked aadhaar number",
    }
    if candidate.lower() in labels or candidate in labels:
        return None
    if re.search(
        r"(?:mobile|phone|pan|aadhaar|loan|amount|date|address|gender|"
        r"marital|landmark|locality|nationality|occupation|email|pin\s*code)",
        candidate,
        re.IGNORECASE,
    ):
        return None
    if len(candidate) > 80:
        return None
    return candidate


def _page_layout_cells(fitz_page: fitz.Page, page_index: int) -> list[_LayoutCell]:
    try:
        words = fitz_page.get_text("words")
    except Exception:  # noqa: BLE001
        return []
    grouped: dict[tuple[int, int], list[tuple]] = {}
    for word in words:
        x0, y0, x1, y1, text, block_no, line_no, word_no = word
        if not str(text).strip():
            continue
        grouped.setdefault((block_no, line_no), []).append((x0, y0, x1, y1, word_no, text))
    cells: list[_LayoutCell] = []
    for items in grouped.values():
        items.sort(key=lambda it: (it[4], it[0]))
        text = " ".join(str(it[5]) for it in items).strip()
        if not text:
            continue
        cells.append(
            {
                "text": text,
                "x0": min(it[0] for it in items),
                "y0": min(it[1] for it in items),
                "x1": max(it[2] for it in items),
                "y1": max(it[3] for it in items),
                "page": page_index,
            }
        )
    return cells


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip(":").lower())


def _extract_applicant_name_by_layout(cells: list[_LayoutCell]) -> str | None:
    if not cells:
        return None
    for variant in _NAME_LABELS_PRIORITY:
        for cell in cells:
            if _normalize_label(cell["text"]) != variant:
                continue
            value = _value_right_of(cells, cell)
            candidate = _clean_name_candidate(value) if value else None
            if candidate:
                return candidate
    return None


def _value_right_of(cells: list[_LayoutCell], label: _LayoutCell) -> str | None:
    label_mid_y = (label["y0"] + label["y1"]) / 2
    label_height = max(label["y1"] - label["y0"], 1.0)
    row_tolerance = max(label_height * 0.6, 4.0)
    same_row: list[_LayoutCell] = []
    for cell in cells:
        if cell is label or cell["page"] != label["page"]:
            continue
        cell_mid_y = (cell["y0"] + cell["y1"]) / 2
        if abs(cell_mid_y - label_mid_y) > row_tolerance:
            continue
        if cell["x0"] < label["x1"] - 2:
            continue
        same_row.append(cell)
    if not same_row:
        return None
    same_row.sort(key=lambda c: c["x0"])
    parts = [same_row[0]["text"]]
    prev_x1 = same_row[0]["x1"]
    for cell in same_row[1:]:
        if cell["x0"] - prev_x1 <= 40:
            parts.append(cell["text"])
            prev_x1 = cell["x1"]
        else:
            break
    return " ".join(parts).strip() or None


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
