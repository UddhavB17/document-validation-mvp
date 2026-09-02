"""Shared CERSAI report-type and search-criteria helpers.

CERSAI pages contain several identities: the registry's own PAN, the debtor
used as the search subject, and parties returned in the search output.  Only
the debtor entered in the search criteria can establish person ownership.
"""

from __future__ import annotations

import re
from typing import Any

DEBTOR_BASED = "debtor_based"
ASSET_BASED = "asset_based"
UNKNOWN = "unknown"


def search_criteria_text(text: Any) -> str:
    """Return only the CERSAI ``Search Criteria Entered`` block."""
    match = re.search(
        r"\bsearch\s+criteria\s+entered\b\s*:?\s*"
        r"(.*?)"
        r"(?="
        r"\bsearch\s+output(?:\s+details)?\b|"
        r"\bsearch\s+results?\b|"
        r"\bdetails\s+of\s+security\s+interest\b|"
        r"\Z"
        r")",
        str(text or ""),
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def search_type(text: Any, fields: dict[str, Any] | None = None) -> str:
    """Identify a CERSAI report as debtor-based, asset-based, or unknown."""
    explicit = str((fields or {}).get("cersai_search_type") or "").strip().casefold()
    normalized_explicit = re.sub(r"[^a-z]+", "_", explicit).strip("_")
    if normalized_explicit in {DEBTOR_BASED, ASSET_BASED}:
        return normalized_explicit

    raw = str(text or "")
    debtor_heading = re.search(r"\bdebtor\s+based\s+search\s+report\b", raw, re.IGNORECASE)
    asset_heading = re.search(r"\basset\s+based\s+search\s+report\b", raw, re.IGNORECASE)
    if debtor_heading and (not asset_heading or debtor_heading.start() < asset_heading.start()):
        return DEBTOR_BASED
    if asset_heading:
        return ASSET_BASED

    criteria = search_criteria_text(raw)
    if re.search(r"\bname\s+of\s+the\s+debtor\b", criteria, re.IGNORECASE):
        return DEBTOR_BASED
    if re.search(
        r"\b(?:asset\s+category|asset\s+id|survey\s+number|property\s+id)\b",
        criteria,
        re.IGNORECASE,
    ):
        return ASSET_BASED
    return UNKNOWN


def report_search_type(
    pages: list[dict[str, Any]] | dict[str, Any] | None,
) -> str:
    """Return the first intrinsic CERSAI subtype found across a report."""
    page_list = [pages] if isinstance(pages, dict) else list(pages or [])
    for page in page_list:
        if not isinstance(page, dict):
            continue
        fields = page.get("extracted_fields")
        fields = fields if isinstance(fields, dict) else {}
        ownership = fields.get("_ownership")
        if isinstance(ownership, dict) and ownership.get("cersai_search_type"):
            detected = search_type("", {"cersai_search_type": ownership["cersai_search_type"]})
            if detected != UNKNOWN:
                return detected
        detected = search_type(page.get("ocr_text"), fields)
        if detected != UNKNOWN:
            return detected
    return UNKNOWN


def page_starts_report(page: dict[str, Any]) -> bool:
    """Return whether a page contains an intrinsic CERSAI report start."""
    text = str(page.get("ocr_text") or "")
    return bool(
        re.search(r"\b(?:debtor|asset)\s+based\s+search\s+report\b", text, re.I)
        or re.search(r"\bsearch\s+criteria\s+entered\b", text, re.I)
    )


def starts_new_report(
    current_pages: list[dict[str, Any]],
    next_page: dict[str, Any],
) -> bool:
    """Split one source only when another real CERSAI search starts."""
    return bool(
        current_pages
        and page_starts_report(next_page)
        and any(page_starts_report(page) for page in current_pages)
    )


def is_debtor_based(text: Any, fields: dict[str, Any] | None = None) -> bool:
    return search_type(text, fields) == DEBTOR_BASED
