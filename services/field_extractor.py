"""Field extractor for DMEF.

Extracts structured fields from OCR-extracted text for each document type.
Called after classify_page() identifies the document type.

Public API
----------
extract_fields(document_type: str, text: str) -> dict
    Dispatches to the correct per-type extractor and returns a flat dict
    of field_name → value.

Cross-match contract (Sanction Letter & Loan Agreement)
-------------------------------------------------------
These fields are consumed by checklist_engine for Graviton cross-matching.
Field names and types MUST NOT change without updating the engine:

    loan_amount  → str   (digits only, no commas, no currency symbols)
    tenure       → int   (always normalised to number of months)
    emi          → str   (digits only, no commas, no currency symbols)
    roi          → float (percentage as a float, e.g. 8.5 for 8.5%)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# python-dateutil – graceful import with informative error
try:
    from dateutil import parser as _dateutil_parser
    _DATEUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DATEUTIL_AVAILABLE = False


# ── Public dispatcher ─────────────────────────────────────────────────────────

def extract_fields(document_type: str, text: str) -> dict[str, Any]:
    """Extract structured fields from *text* for *document_type*.

    Args:
        document_type: Classifier output (e.g. "Sanction Letter").
        text:          Raw OCR text of the page / document.

    Returns:
        Dict of field_name → extracted value (str | int | float | None).
        Unknown document types return an empty dict.
    """
    _EXTRACTORS = {
        "Sanction Letter":  _extract_sanction_letter,
        "Loan Agreement":   _extract_loan_agreement,
        "PAN":              _extract_pan,
        "PAN Card":         _extract_pan,
        "Aadhaar":          _extract_aadhaar,
        "Voter ID":         _extract_voter_id,
        "Driving License":  _extract_driving_license,
        "CRIF Report":      _extract_crif_report,
        "Bank Statement":   _extract_bank_statement,
        "Salary Slip":      _extract_salary_slip,
    }
    extractor = _EXTRACTORS.get(document_type)
    if extractor is None:
        return {}
    return extractor(text)


# ── Shared extraction helpers ─────────────────────────────────────────────────

def _digits_only(value: str) -> str:
    """Strip everything except digits and return as string."""
    return re.sub(r"[^\d]", "", value)


def _extract_amount(text_lower: str, *label_patterns: str) -> str | None:
    """Extract a numeric amount following any of the label phrases.

    Handles Indian comma-separated formats like 5,00,000.
    Returns digits-only string (no commas, no ₹/Rs.).
    """
    for pattern in label_patterns:
        match = re.search(
            rf"{re.escape(pattern)}\s*[:\-–]?\s*(?:rs\.?|₹|inr)?\s*([\d,]+)",
            text_lower,
        )
        if match:
            return _digits_only(match.group(1))
    return None


def _extract_tenure_months(text_lower: str) -> int | None:
    """Extract tenure and normalise to integer number of months.

    Recognises:
      - "60 months" / "60 month"
      - "5 years"  / "5 year"
      - bare digits after "tenure" when no unit is present
    """
    # Explicit months
    match = re.search(
        r"(?:loan\s+)?tenure\s*[:\-–]?\s*(\d+)\s*months?",
        text_lower,
    )
    if match:
        return int(match.group(1))

    # Explicit years → convert
    match = re.search(
        r"(?:loan\s+)?tenure\s*[:\-–]?\s*(\d+)\s*years?",
        text_lower,
    )
    if match:
        return int(match.group(1)) * 12

    # Fallback: bare number after "tenure"
    match = re.search(
        r"(?:loan\s+)?tenure\s*[:\-–]?\s*(\d+)",
        text_lower,
    )
    if match:
        return int(match.group(1))

    return None


def _extract_roi(text_lower: str) -> float | None:
    """Extract rate of interest as a float (e.g. 8.5)."""
    # Look for percentage near roi / rate of interest
    match = re.search(
        r"(?:rate of interest|roi)\s*[:\-–]?\s*(\d+\.?\d*)\s*%",
        text_lower,
    )
    if match:
        return float(match.group(1))

    # Fallback: any percentage in the text
    match = re.search(r"(\d+\.?\d*)\s*%", text_lower)
    if match:
        return float(match.group(1))

    return None


def _extract_emi(text_lower: str) -> str | None:
    """Extract EMI amount (digits only).

    Handles labels:
      - "emi amount"  (spec: "EMI Amount: Rs. 10,500")
      - "emi"
      - "equated monthly instalment"
    """
    match = re.search(
        r"(?:emi(?:\s+amount)?|equated\s+monthly\s*instalment?)\s*[:\-–]?\s*(?:rs\.?|₹|inr)?\s*([\d,]+)",
        text_lower,
    )
    if match:
        return _digits_only(match.group(1))
    return None


def _line_after_label(text: str, *labels: str) -> str | None:
    """Return the first non-empty line that follows any of *labels*."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(label in line_lower for label in labels):
            # Try the remainder of the same line first
            parts = re.split(r"[:\-–]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                candidate = _clean_name_like_value(parts[1])
                if candidate:
                    return candidate
            # Else next non-empty line
            for j in range(i + 1, len(lines)):
                candidate = _clean_name_like_value(lines[j])
                if candidate:
                    return candidate
    return None


def _clean_name_like_value(value: str) -> str | None:
    candidate = value.strip(" :\t\r\n")
    if not candidate:
        return None
    labels = {
        "applicant name",
        "borrower name",
        "name of applicant",
        "consumer name",
        "card holder name",
        "father's name",
        "fathers name",
        "name",
        "s/o",
        "d/o",
        "w/o",
        "आवेदक का नाम",
        "नाम",
    }
    if candidate.lower() in labels or candidate in labels:
        return None
    if len(candidate) > 100:
        return None
    return candidate


def _lines_after_label(text: str, label: str, max_lines: int = 3) -> str | None:
    """Return up to *max_lines* lines following *label*, joined by spaces."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if label in line.lower():
            collected: list[str] = []
            for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
                part = lines[j].strip()
                if part:
                    collected.append(part)
            return " ".join(collected) if collected else None
    return None


def _parse_date(text: str) -> str | None:
    """Parse *text* as a date and return ISO-8601 string, or None on failure."""
    if not _DATEUTIL_AVAILABLE:
        # Fallback: return the raw string stripped of noise
        return text.strip() or None
    try:
        dt = _dateutil_parser.parse(text, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def _extract_date_near(text_lower: str, *anchors: str) -> str | None:
    """Find a date-like pattern near any of the anchor keywords."""
    date_pattern = re.compile(
        r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"   # DD/MM/YYYY or DD-MM-YY
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"            # YYYY-MM-DD
        r"|\d{1,2}\s+\w+\s+\d{4})\b"                 # 01 January 2025
    )
    for anchor in anchors:
        idx = text_lower.find(anchor)
        if idx == -1:
            continue
        # Search in a 120-character window around the anchor
        window = text_lower[max(0, idx - 20): idx + 100]
        match = date_pattern.search(window)
        if match:
            return _parse_date(match.group(0))
    return None


def _is_past_date(iso_date: str | None) -> bool:
    """Return True if *iso_date* is before today."""
    if iso_date is None:
        return False
    try:
        return date.fromisoformat(iso_date) < date.today()
    except ValueError:
        return False


# ── Per-document-type extractors ──────────────────────────────────────────────

def _extract_sanction_letter(text: str) -> dict[str, Any]:
    """Extract fields from a Sanction Letter.

    Cross-match fields (exact names required by checklist_engine):
        loan_amount  → str   digits only
        tenure       → int   months
        emi          → str   digits only
        roi          → float percentage
    """
    t = text.lower()
    return {
        "loan_amount": _extract_amount(
            t, "sanctioned amount", "loan amount", "amount sanctioned"
        ),
        "tenure": _extract_tenure_months(t),
        "emi": _extract_emi(t),
        "roi": _extract_roi(t),
        "applicant_name": _line_after_label(text, "borrower", "applicant name"),
    }


def _extract_loan_agreement(text: str) -> dict[str, Any]:
    """Extract fields from a Loan Agreement.

    Cross-match fields match Sanction Letter naming exactly.
    """
    t = text.lower()
    return {
        "loan_amount": _extract_amount(
            t, "loan amount", "sanctioned amount", "amount sanctioned"
        ),
        "tenure": _extract_tenure_months(t),
        "emi": _extract_emi(t),
        "roi": _extract_roi(t),
        "borrower_name": _line_after_label(text, "borrower"),
        "agreement_date": _extract_date_near(t, "date of agreement", "agreement date", "date"),
    }


def _extract_pan(text: str) -> dict[str, Any]:
    """Extract fields from a PAN card."""
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper())
    return {
        "applicant_name": _line_after_label(
            text,
            "name",
            "applicant name",
            "card holder name",
            "father's name",
            "fathers name",
        ),
        "pan_number": pan_match.group(1) if pan_match else None,
        "dob": _extract_date_near(text.lower(), "date of birth", "dob"),
    }


def _extract_aadhaar(text: str) -> dict[str, Any]:
    """Extract fields from an Aadhaar card."""
    aadhaar_match = re.search(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", text)
    aadhaar_number = aadhaar_match.group(1).replace(" ", "") if aadhaar_match else None
    return {
        "applicant_name": _line_after_label(text, "name", "s/o", "d/o", "w/o"),
        "aadhaar_number": aadhaar_number,
        "dob": _extract_date_near(text.lower(), "date of birth", "dob", "year of birth", "yob"),
        "address": _lines_after_label(text, "address", max_lines=4),
    }


def _extract_voter_id(text: str) -> dict[str, Any]:
    """Extract fields from a Voter ID / EPIC card."""
    t = text.lower()

    # Voter ID number: 3 uppercase letters + 7 digits  e.g. ABC1234567
    vid_match = re.search(r'\b([A-Z]{3}[0-9]{7})\b', text)

    # DOB
    dob_raw = _extract_date_near(t, "dob", "date of birth")

    return {
        "applicant_name": _line_after_label(text, "name", "elector's name", "electors name"),
        "voter_id_number": vid_match.group(1) if vid_match else None,
        "address": _lines_after_label(text, "address", max_lines=3),
        "dob": dob_raw,
    }


def _extract_driving_license(text: str) -> dict[str, Any]:
    """Extract fields from a Driving License.

    Also flags expired licences via 'is_expired' key.
    """
    t = text.lower()

    # DL number: 2 uppercase letters + 2 digits + optional space + 11 digits
    # (\b does not work between \d and \D reliably, so we anchor with lookahead/lookbehind)
    dl_match = re.search(r'(?<![A-Z0-9])([A-Z]{2}\d{2}\s?\d{11})(?![A-Z0-9])', text)

    validity_date = _extract_date_near(t, "valid till", "valid upto", "validity")
    is_expired = _is_past_date(validity_date)

    dob_raw = _extract_date_near(t, "dob", "date of birth")

    return {
        "applicant_name": _line_after_label(text, "name"),
        "dl_number": dl_match.group(1).replace(" ", "") if dl_match else None,
        "dob": dob_raw,
        "validity_date": validity_date,
        "is_expired": is_expired,
    }


def _extract_crif_report(text: str) -> dict[str, Any]:
    """Extract fields from a CRIF / CIBIL credit report."""
    t = text.lower()

    # Credit score: 3-digit number near the word "score"
    score: str | None = None
    score_match = re.search(
        r'(?:credit\s+)?score\s*[:\-–]?\s*\b([3-9]\d{2})\b',
        t,
    )
    if score_match:
        score = score_match.group(1)
    else:
        # Broader fallback: any 3-digit number 300-900 near "score" in a 60-char window
        idx = t.find("score")
        if idx != -1:
            window = t[max(0, idx - 10): idx + 50]
            fb = re.search(r'\b([3-9]\d{2})\b', window)
            if fb:
                score = fb.group(1)

    # Report date
    report_date = _extract_date_near(t, "report generated", "as on", "date of report")

    # Applicant name: first substantive non-header line
    applicant_name: str | None = _line_after_label(
        text, "applicant name", "name of applicant", "consumer name", "name"
    )

    return {
        "applicant_name": applicant_name,
        "credit_score": score,
        "report_date": report_date,
    }


def _extract_bank_statement(text: str) -> dict[str, Any]:
    """Extract fields from a bank statement."""
    t = text.lower()
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?)\s*[:\-–]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    period_start, period_end = _extract_statement_period(text)
    return {
        "account_holder_name": _line_after_label(text, "account holder", "customer name", "name"),
        "account_number": _digits_only(account_match.group(1)) if account_match else None,
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "statement_period_start": period_start,
        "statement_period_end": period_end or _extract_date_near(t, "statement date", "as on", "period ending"),
    }


def _extract_statement_period(text: str) -> tuple[str | None, str | None]:
    date_pattern = (
        r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"
        r"|\d{1,2}\s+\w+\s+\d{4}"
    )
    match = re.search(
        rf"(?:period|statement\s+period|from)\s*[:\-–]?\s*({date_pattern})\s*(?:to|\-|\u2013|\u2014)\s*({date_pattern})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    return _parse_date(match.group(1)), _parse_date(match.group(2))


def _extract_salary_slip(text: str) -> dict[str, Any]:
    """Extract fields from a salary slip."""
    t = text.lower()
    return {
        "employee_name": _line_after_label(text, "employee name", "name"),
        "employer_name": _line_after_label(text, "employer", "company", "organization", "organisation"),
        "gross_salary": _extract_amount(t, "gross salary", "gross pay", "gross earnings"),
        "net_salary": _extract_amount(t, "net salary", "net pay", "take home"),
        "salary_month": _extract_salary_month(text),
    }


def _extract_salary_month(text: str) -> str | None:
    match = re.search(
        r"(?:salary\s+month|pay\s+period|month)\s*[:\-–]?\s*([A-Za-z]+\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None
