"""Credit-bureau report extractors."""

from __future__ import annotations

import re
from typing import Any

from services.bureau_scores import has_explicit_no_score_evidence
from services.extraction._shared import (
    _clean_name_like_value,
    _extract_date_near,
    _line_after_label,
)


def _extract_crif_report(text: str) -> dict[str, Any]:
    """Extract fields from a CRIF / CIBIL credit report."""
    t = text.lower()

    # Credit score: 3-digit number near the word "score"
    score: str | None = None
    score_match = re.search(
        r"(?:credit\s+)?score\s*[:\-–]?\s*\b(0|[3-9]\d{2})\b",
        t,
    )
    if score_match:
        score = score_match.group(1)
    else:
        table_score = re.search(r"\b300\s*[-–]\s*900\s+(0|[3-9]\d{2})\b", t)
        if table_score:
            score = table_score.group(1)
    if score is None:
        # Broader fallback: any 3-digit number 300-900 near "score" in a 60-char window
        idx = t.find("score")
        if idx != -1:
            window = t[max(0, idx - 10) : idx + 50]
            fb = re.search(r"\b(0|[3-9]\d{2})\b", window)
            if fb:
                score = fb.group(1)
    if score is None and has_explicit_no_score_evidence(text):
        score = "0"

    # Report date
    report_date = _extract_date_near(t, "report generated", "as on", "date of report")

    # Applicant name: first substantive non-header line
    applicant_name: str | None = _extract_bureau_applicant_name(text)

    account_count = re.search(r"(?:total|number\s+of)\s+accounts?\s*[:\-–]?\s*(\d+)", t)
    overdue_count = re.search(r"(?:overdue|past\s+due)\s+accounts?\s*[:\-–]?\s*(\d+)", t)
    report_id = re.search(
        r"(?:report|reference|document)\s*(?:id|no\.?|number)\s*[:\-–]?\s*([A-Z0-9\-/]+)",
        text,
        re.IGNORECASE,
    )
    return {
        "applicant_name": applicant_name,
        "credit_score": score,
        "cibil_score" if "cibil" in t else "crif_score": score,
        "report_date": report_date,
        "bureau_account_count": account_count.group(1) if account_count else None,
        "overdue_account_count": overdue_count.group(1) if overdue_count else None,
        "dpd_status": _line_after_label(text, "dpd status", "days past due"),
        "credit_report_id": report_id.group(1) if report_id else None,
    }


def _extract_bureau_applicant_name(text: str) -> str | None:
    """Extract only the report subject, never variation/address-section rows."""
    header_window = text[:2500]
    for pattern in (
        r"(?:^|\n)\s*Consumer\s+Name\s*:?\s*(?:\n\s*)?"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)(?=\s*(?:\n|Date\b|DOB\b))",
        r"(?:^|\n)\s*Applicant\s+Name\s*[:\-–]?\s*(?:\n\s*)?"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)(?=\s*(?:\n|DOB\b|Gender\b))",
        r"(?:^|\n)\s*Name\s*:\s*([A-Za-z][A-Za-z .'-]{2,60}?)"
        r"(?=\s+(?:DOB|Gender|Father|Phone|ID|Current Address|$))",
        r"(?:^|\n)\s*For\s+([A-Za-z][A-Za-z .'-]{2,60}?)\s*(?=\n|$)",
    ):
        match = re.search(pattern, header_window, re.IGNORECASE | re.MULTILINE)
        if match:
            return _clean_name_like_value(match.group(1))
    return None
