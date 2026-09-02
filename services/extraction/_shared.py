"""Shared extraction helpers — no imports from high-level services."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from services.person_names import canonicalize_person_name, is_name_field

try:
    from dateutil import parser as _dateutil_parser

    _DATEUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DATEUTIL_AVAILABLE = False

_ADDRESS_FIELD_NAMES = {
    "address",
    "current_address",
    "permanent_address",
    "communication_address",
}
_PAGE_COUNTER_RE = re.compile(
    r"\bpage\s*(?:no\.?\s*)?\d+\s*(?:of|/)\s*\d+\b",
    re.IGNORECASE,
)


def _strip_trailing_page_footer(value: Any) -> str:
    """Remove a page counter and anything appended after it from an address."""
    raw = str(value or "")
    match = _PAGE_COUNTER_RE.search(raw)
    return raw[: match.start()].rstrip(" ,.;:|-\n\r\t") if match else raw


def _sanitize_address_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Sanitize addresses at both page level and inside person rows."""
    cleaned = dict(fields)
    for field_name, value in list(cleaned.items()):
        if str(field_name).startswith("_"):
            continue
        if field_name in _ADDRESS_FIELD_NAMES:
            cleaned[field_name] = _sanitize_address_value(value)
        elif field_name == "person_records" and isinstance(value, list):
            cleaned[field_name] = [
                _sanitize_address_fields(record) if isinstance(record, dict) else record
                for record in value
            ]
    return cleaned


def _sanitize_address_value(value: Any) -> str | None:
    compact = re.sub(r"\s+", " ", _strip_trailing_page_footer(value)).strip()
    if not compact:
        return None
    if _address_value_is_contaminated(compact):
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", compact.casefold()).strip()
    if re.fullmatch(
        r"(?:guarantor|co applicant|applicant)?\s*"
        r"(?:employment|employement|business|kyc|personal)?\s*details",
        normalized,
    ) or re.fullmatch(
        r"(?:guarantor|co applicant|applicant)\s+(?:address|details)",
        normalized,
    ):
        return None
    placeholder_tokens = {
        "address",
        "landmark",
        "locality",
        "city",
        "district",
        "pin",
        "code",
        "state",
        "country",
        "village",
        "tehsil",
    }
    latin_tokens = re.findall(r"[A-Za-z0-9]+", compact)
    if latin_tokens and not any(token.isdigit() for token in latin_tokens):
        if {token.casefold() for token in latin_tokens} <= placeholder_tokens:
            return None
    if not re.search(r"\b\d{6}\b", compact) and len(latin_tokens) < 3:
        return None
    return compact


_ADDRESS_FORM_NOISE_PATTERNS = (
    r"\baadhaar\s+no\b",
    r"\bdriving\s+licen[cs]e\b",
    r"\bpan\s*/?\s*gir\b",
    r"\bprofessionally\s+qualified\b",
    r"\bbusiness\s+constitution\b",
    r"\b(?:undergraduate|graduate|postgraduate|post\s+graduate)\b",
    r"\b(?:mobile|telephone|whatsapp)(?:\s+(?:number|no|contact))?\b",
    r"\b(?:nature|industry|sector)\s+of\s+business\b",
)

_ADDRESS_FORM_NOISE_PATTERNS = (
    r"\baadhaar\s+no\b",
    r"\bdriving\s+licen[cs]e\b",
    r"\bpan\s*/?\s*gir\b",
    r"\bprofessionally\s+qualified\b",
    r"\bbusiness\s+constitution\b",
    r"\b(?:undergraduate|graduate|postgraduate|post\s+graduate)\b",
    r"\b(?:mobile|telephone|whatsapp)(?:\s+(?:number|no|contact))?\b",
    r"\b(?:nature|industry|sector)\s+of\s+business\b",
)


def _address_value_is_contaminated(value: str) -> bool:
    """Reject form-label soup produced by flattened multi-column OCR."""
    normalized = re.sub(r"\s+", " ", str(value or "")).casefold()
    noise_hits = sum(
        bool(re.search(pattern, normalized)) for pattern in _ADDRESS_FORM_NOISE_PATTERNS
    )
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    return noise_hits >= 2 or (noise_hits >= 1 and len(tokens) > 28) or len(tokens) > 55


def _xml_cleaner(text: str) -> str:
    """Strip XML/digital-signature content from page text before field extraction."""
    try:
        from services.text_extractor import clean_xml_and_metadata  # noqa: PLC0415

        return clean_xml_and_metadata(text)
    except ImportError:  # pragma: no cover
        return text


def _digits_only(value: str) -> str:
    """Strip everything except digits and return as string."""
    return re.sub(r"[^\d]", "", value)


def _normalize_amount(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return str(int(number)) if number.is_integer() else (f"{number:.2f}".rstrip("0").rstrip("."))


def _strip_trailing_page_footer(value: Any) -> str:
    """Remove a page counter and anything appended after it from an address."""
    raw = str(value or "")
    match = _PAGE_COUNTER_RE.search(raw)
    return raw[: match.start()].rstrip(" ,.;:|-\n\r\t") if match else raw


def _sanitize_address_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Sanitize addresses at both page level and inside person rows."""
    cleaned = dict(fields)
    for field_name, value in list(cleaned.items()):
        if str(field_name).startswith("_"):
            continue
        if field_name in _ADDRESS_FIELD_NAMES:
            cleaned[field_name] = _sanitize_address_value(value)
        elif field_name == "person_records" and isinstance(value, list):
            cleaned[field_name] = [
                _sanitize_address_fields(record) if isinstance(record, dict) else record
                for record in value
            ]
    return cleaned


def _sanitize_address_value(value: Any) -> str | None:
    compact = re.sub(r"\s+", " ", _strip_trailing_page_footer(value)).strip()
    if not compact:
        return None
    if _address_value_is_contaminated(compact):
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", compact.casefold()).strip()
    if re.fullmatch(
        r"(?:guarantor|co applicant|applicant)?\s*"
        r"(?:employment|employement|business|kyc|personal)?\s*details",
        normalized,
    ) or re.fullmatch(
        r"(?:guarantor|co applicant|applicant)\s+(?:address|details)",
        normalized,
    ):
        return None
    placeholder_tokens = {
        "address",
        "landmark",
        "locality",
        "city",
        "district",
        "pin",
        "code",
        "state",
        "country",
        "village",
        "tehsil",
    }
    latin_tokens = re.findall(r"[A-Za-z0-9]+", compact)
    if latin_tokens and not any(token.isdigit() for token in latin_tokens):
        if {token.casefold() for token in latin_tokens} <= placeholder_tokens:
            return None
    if not re.search(r"\b\d{6}\b", compact) and len(latin_tokens) < 3:
        return None
    return compact


def _address_value_is_contaminated(value: str) -> bool:
    """Reject form-label soup produced by flattened multi-column OCR."""
    normalized = re.sub(r"\s+", " ", str(value or "")).casefold()
    noise_hits = sum(
        bool(re.search(pattern, normalized)) for pattern in _ADDRESS_FORM_NOISE_PATTERNS
    )
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    return noise_hits >= 2 or (noise_hits >= 1 and len(tokens) > 28) or len(tokens) > 55


def _raw_value_after_label(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*[:\-–]\s*([^\n\r]{{1,160}})",
            text,
            re.IGNORECASE,
        )
        if match:
            value = match.group(1).strip(" :\t")
            if value:
                return value
    return None


def _extract_amount(text_lower: str, *label_patterns: str) -> str | None:
    """Extract a numeric amount following any of the label phrases.

    Handles Indian comma-separated formats like 5,00,000.
    Returns digits-only string (no commas, no ₹/Rs.).
    """
    for pattern in label_patterns:
        match = re.search(
            rf"{re.escape(pattern)}[ \t]*[:\-–]?[ \t]*(?:rs\.?|₹|inr)?[ \t]*([\d,]+(?:\.\d+)?)",
            text_lower,
        )
        if match:
            return _normalize_amount(match.group(1))
    return None


def _numeric_line_after_label(text: str, *labels: str, max_lines: int = 8) -> str | None:
    """Return the next value-like line after a bilingual table label."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        normalized = re.sub(r"\s+", " ", line.strip()).lower()
        if not any(normalized == label or normalized.startswith(f"{label} ") for label in labels):
            continue
        for candidate_line in lines[index + 1 : index + 1 + max_lines]:
            candidate = candidate_line.strip()
            match = re.fullmatch(
                r"(?:rs\.?\s*)?([\d,]+(?:\.\d+)?)\s*(?:%|fixed|months?|/-)?",
                candidate,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)
    return None


def _has_repayment_summary_evidence(text: str) -> bool:
    """Gate the broad KFS summary parser on real table structure.

    Loan boilerplate can mention a KFS and ``rate of interest`` before a
    numbered clause such as ``6. In case of digital loans``.  A loose
    cross-line regex previously turned that clause number into ROI=6.  Real KFS
    summaries expose at least two labelled rows (or the explicit APR
    illustration heading).
    """
    raw = str(text or "")
    if re.search(r"\billustration\s+for\s+computation\s+of\s+apr\b", raw, re.I):
        return True
    row_patterns = (
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?(?:sanctioned\s+)?loan\s+amount\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?loan\s+term\b",
        r"(?:^|\n)\s*(?:[A-Z][.)]\s*)?type\s+of\s+emi\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?rate\s+of\s+interest\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?total\s+interest\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?net\s+disburs(?:ed|ement)\b",
        r"(?:^|\n)\s*(?:\d+[.)]\s*)?total\s+amount\s+to\s+be\s+paid\b",
    )
    return sum(bool(re.search(pattern, raw, re.I)) for pattern in row_patterns) >= 2


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(float(str(value))) if value not in (None, "") else None
    except ValueError:
        return None


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(str(value)) if value not in (None, "") else None
    except ValueError:
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

    return None


def _extract_percentage_near(text_lower: str, *labels: str) -> float | None:
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\b\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*%?", text_lower)
        if match:
            return float(match.group(1))
    return None


def _extract_identifier(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*[:\-–#]?\s*([A-Z0-9][A-Z0-9\-/]{{3,40}})", text, re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
    return None


def _extract_emi(text_lower: str) -> str | None:
    """Extract EMI amount (digits only).

    Handles labels:
      - "emi amount"  (spec: "EMI Amount: Rs. 10,500")
      - "emi"
      - "equated monthly instalment"
    """
    # KFS APR illustrations commonly present the value as
    # ``Monthly 8234.00 & 60`` below a bilingual "Type of EMI" heading.
    # Read that row before the generic label matcher, which can otherwise
    # wander into the preceding sanctioned-loan-amount value.
    monthly_row = re.search(
        r"\bmonthly\s+(?:rs\.?\s*)?([\d,]+(?:\.\d+)?)\s*(?:&|and)\s*\d+\b",
        text_lower,
    )
    if monthly_row:
        return _normalize_amount(monthly_row.group(1))

    # On amortisation pages the first row can be a broken-period instalment
    # (for example 2582), while the recurring EMI is repeated in later rows.
    # Select the modal EMI column value rather than the serial number directly
    # below the table heading.
    if "repayment schedule" in text_lower and re.search(r"emi\s*\(\s*in\s+rs", text_lower):
        schedule_values = [
            _normalize_amount(value)
            for _, _, value, _, _, _ in re.findall(
                r"(?:^|\n)\s*(\d+)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)\s*\n"
                r"\s*([\d,]+(?:\.\d+)?)",
                text_lower,
            )
        ]
        if schedule_values:
            recurring = max(set(schedule_values), key=schedule_values.count)
            if schedule_values.count(recurring) >= 2:
                return recurring

    match = re.search(
        r"(?:^|\n)\s*(?:emi(?:\s+amount)?|equated\s+monthly\s*instalment?)"
        r"\s*\*?\s*(?:\(\s*in\s+rs\.?\s*\))?\s*[:\-–]?\s*(?:rs\.?|₹|inr)?\s*"
        r"(?:\n\s*)?([\d,]+)(?![A-Za-z-])",
        text_lower,
    )
    if match:
        return _digits_only(match.group(1))
    return None


def _line_after_label(text: str, *labels: str) -> str | None:
    """Return the first non-empty line that follows any of *labels*."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        matched_label = next(
            (
                label
                for label in labels
                if re.fullmatch(rf"{re.escape(label)}\s*[:\-–]?", line_stripped, re.IGNORECASE)
                or re.match(rf"^{re.escape(label)}\s*[:\-–]\s*\S", line_stripped, re.IGNORECASE)
            ),
            None,
        )
        if matched_label:
            # Try the remainder of the same line first
            parts = re.split(r"[:\-–]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                candidate = _clean_name_like_value(parts[1])
                if candidate:
                    return candidate
            # Else next non-empty line (bounded to 8 lines max)
            for j in range(i + 1, min(len(lines), i + 9)):
                if not any(character.isalpha() for character in lines[j]):
                    continue
                candidate = _clean_name_like_value(lines[j])
                if candidate:
                    return candidate
    return None


def _clean_name_like_value(value: str) -> str | None:
    candidate = canonicalize_person_name(value)
    return candidate.value if candidate.valid else None


def _sanitize_name_fields(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(fields)
    for field_name, value in list(cleaned.items()):
        if str(field_name).startswith("_"):
            continue
        if field_name == "person_records" and isinstance(value, list):
            cleaned[field_name] = [
                _sanitize_name_fields(record) if isinstance(record, dict) else record
                for record in value
            ]
            continue
        if isinstance(value, list):
            if is_name_field(field_name):
                names = [
                    candidate.value
                    for item in value
                    if (candidate := canonicalize_person_name(item)).valid
                ]
                cleaned[field_name] = names
            continue
        if is_name_field(field_name) and value not in (None, ""):
            candidate = canonicalize_person_name(value)
            cleaned[field_name] = candidate.value if candidate.valid else None
    return cleaned


def _lines_after_label(text: str, label: str, max_lines: int = 3) -> str | None:
    """Return up to *max_lines* lines following *label*, joined by spaces."""
    lines = text.splitlines()
    stop_labels = {
        "name",
        "applicant name",
        "father name",
        "date of birth",
        "dob",
        "date of issue",
        "issue date",
        "issued on",
        "valid till",
        "valid upto",
        "validity",
        "licence no",
        "license no",
        "dl no",
        "address",
        "pin code",
        "gender",
        "sex",
        "date",
        "mobile",
        "phone",
        "blood group",
    }
    for i, line in enumerate(lines):
        if not re.search(rf"\b{re.escape(label)}\b", line, re.IGNORECASE):
            continue
        collected: list[str] = []
        inline = re.split(r"[:\-–]", line, maxsplit=1)
        if len(inline) == 2 and inline[1].strip():
            return inline[1].strip()
        for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
            part = lines[j].strip()
            if not part:
                continue
            normalized = _normalize_label(part).split(":", 1)[0]
            if normalized in stop_labels or any(
                normalized.startswith(f"{stop} ") for stop in stop_labels
            ):
                break
            collected.append(part)
        return " ".join(collected) if collected else None
    return None


def _lines_after_label_until_stop(
    text: str,
    label: str,
    *,
    stop_labels: set[str],
    max_lines: int = 4,
) -> str | None:
    """Return lines after *label* until a known non-address label is reached."""
    lines = text.splitlines()
    normalized_stops = {_normalize_label(stop_label) for stop_label in stop_labels}
    for i, line in enumerate(lines):
        if label in line.lower():
            collected: list[str] = []
            for j in range(i + 1, min(i + 1 + max_lines, len(lines))):
                part = lines[j].strip()
                if not part:
                    continue
                if _normalize_label(part).split(":")[0] in normalized_stops:
                    break
                if any(_normalize_label(part).startswith(stop) for stop in normalized_stops):
                    break
                collected.append(part)
            return " ".join(collected) if collected else None
    return None


def _value_after_label(text: str, *labels: str) -> str | None:
    """Return the next useful value after an exact-ish OCR label."""
    lines = [line.strip() for line in text.splitlines()]
    normalized_labels = {_normalize_label(label) for label in labels}
    stop_labels = {
        "aadhaar",
        "address",
        "date of birth",
        "dob",
        "mobile number",
        "name of the debtor",
        "pan",
        "search criteria",
        "search reference number",
        "transaction id",
    }
    for index, line in enumerate(lines):
        for label in labels:
            inline_match = re.match(
                rf"^\s*{re.escape(label)}\s*[:\-–]\s*(.+?)\s*$",
                line,
                re.IGNORECASE,
            )
            if inline_match:
                return inline_match.group(1).strip(" :\t\r\n")
        normalized_line = _normalize_label(line)
        if normalized_line not in normalized_labels:
            continue
        for candidate in lines[index + 1 : index + 5]:
            normalized_candidate = _normalize_label(candidate)
            if not candidate or normalized_candidate in stop_labels:
                continue
            return candidate.strip(" :\t\r\n")
    return None


def _normalize_label(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-z]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_date(text: str) -> str | None:
    """Parse *text* as a date and return ISO-8601 string, or None on failure."""
    stripped = str(text or "").strip()
    # dateutil with dayfirst=True swaps the month and day of already-normalized
    # ISO dates (for example 1994-12-05 -> 1994-05-12). Preserve ISO semantics.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        try:
            return date.fromisoformat(stripped).isoformat()
        except ValueError:
            return None
    if not _DATEUTIL_AVAILABLE:
        # Fallback: return the raw string stripped of noise
        return stripped or None
    try:
        dt = _dateutil_parser.parse(stripped, dayfirst=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def _extract_date_near(text_lower: str, *anchors: str) -> str | None:
    """Find a date-like pattern near any of the anchor keywords."""
    date_pattern = re.compile(
        r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"  # DD/MM/YYYY or DD-MM-YY
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"  # YYYY-MM-DD
        r"|\d{1,2}[-\s]+\w+[-\s]+\d{4})\b"  # 01-January-2025
    )
    for anchor in anchors:
        idx = text_lower.find(anchor)
        if idx == -1:
            continue
        # Search in a 120-character window around the anchor
        window = text_lower[max(0, idx - 20) : idx + 100]
        match = date_pattern.search(window)
        if match:
            return _parse_date(match.group(0))
    return None


def _extract_date_after_label(text: str, *labels: str) -> str | None:
    """Extract a date immediately following one of the supplied labels."""
    date_pattern = (
        r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"
        r"|\d{1,2}[-\s]+\w+[-\s]+\d{4}"
    )
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*[:\-–]?\s*({date_pattern})",
            text,
            re.IGNORECASE,
        )
        if match:
            return _parse_date(match.group(1))
    return None


def _extract_date_below_label(
    text: str,
    *labels: str,
    max_lines: int = 6,
    stop_labels: tuple[str, ...] = (),
) -> str | None:
    """Extract a date from the short visual block below a field label.

    Structured cards often flatten adjacent columns into intervening OCR lines.
    For example, a driving licence may emit ``Date of Birth``, ``Blood Group``,
    ``Unknown``, then the DOB.  This bounded scan tolerates those non-date lines
    but stops before the next identity field so a different date is not used.
    """
    date_pattern = re.compile(
        r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
        r"|\d{4}[/\-\.]\d{2}[/\-\.]\d{2}"
        r"|\d{1,2}[-\s]+[A-Za-z]+[-\s]+\d{4})\b"
    )
    normalized_labels = {_normalize_label(label) for label in labels}
    normalized_stops = tuple(_normalize_label(label) for label in stop_labels)
    lines = [line.strip() for line in str(text or "").splitlines()]
    for index, line in enumerate(lines):
        normalized_line = _normalize_label(line)
        if not any(
            normalized_line == label or normalized_line.endswith(f" {label}")
            for label in normalized_labels
        ):
            continue
        for candidate in lines[index + 1 : index + 1 + max_lines]:
            normalized_candidate = _normalize_label(candidate)
            if normalized_candidate and any(
                normalized_candidate == stop
                or normalized_candidate.endswith(f" {stop}")
                or normalized_candidate.startswith(f"{stop} ")
                for stop in normalized_stops
            ):
                break
            match = date_pattern.search(candidate)
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


def _next_nonempty_line(text: str, label: str, *, max_lines: int = 3) -> str | None:
    """Return a short table value immediately below an exact label line."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.sub(r"\s+", " ", line.strip()).casefold() != label.casefold():
            continue
        for candidate_line in lines[index + 1 : index + 1 + max_lines]:
            candidate = re.sub(r"\s+", " ", candidate_line.strip())
            if candidate:
                return candidate[:160]
    return None


def _looks_like_postal_address(value: str) -> bool:
    text = re.sub(r"\s+", " ", _strip_trailing_page_footer(value)).strip()
    if not text:
        return False
    if re.search(r"\b[1-8]\d{5}\b", text):
        return True
    tokens = re.findall(r"[A-Za-z0-9]+", text)
    return bool(
        len(tokens) >= 4
        and (
            re.search(r"\d", text)
            or re.search(
                r"\b(?:road|street|nagar|vas|village|taluka|district|ahmedabad|"
                r"flat|house|plot|sector|colony|society)\b",
                text,
                re.IGNORECASE,
            )
        )
    )


def _ocr_normalized_pin(value: str) -> str | None:
    translated = (
        str(value or "")
        .upper()
        .translate(
            str.maketrans(
                {
                    "O": "0",
                    "Q": "0",
                    "D": "0",
                    "I": "1",
                    "L": "1",
                    "Z": "2",
                    "M": "4",
                    "S": "5",
                    "G": "6",
                    "B": "8",
                }
            )
        )
    )
    return translated if re.fullmatch(r"[1-8]\d{5}", translated) else None


def _inline_identifier_after_label(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)[ \t]*{re.escape(label)}[ \t]*[:\-–#]?[ \t]*"
            r"([A-Z0-9][A-Z0-9./_-]{2,40})[ \t]*(?:\r?$)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
    return None


def _inline_text_after_label(text: str, *labels: str) -> str | None:
    for label in labels:
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*[:\-–]\s*([^\n\r]{{2,80}})",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" ,.;")
    return None
