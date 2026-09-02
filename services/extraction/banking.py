"""Banking-document extractors: statements, passbook, cheque, NACH, PDC."""

from __future__ import annotations

import re
from typing import Any

from services.extraction._shared import (
    _clean_name_like_value,
    _digits_only,
    _extract_amount,
    _extract_date_near,
    _line_after_label,
    _parse_date,
)
from services.person_names import canonicalize_person_name
from services.validation_gates import is_amortization_schedule


def _extract_pdc(text: str) -> dict[str, Any]:
    """Extract individual cheque leaves from a scanned PDC sheet.

    MICR lines normally contain the six-digit cheque number followed by nine
    routing digits. OCR may repeat the same leaf, so return unique numbers.
    """
    cheque_numbers = list(
        dict.fromkeys(
            match.group(1)
            for match in re.finditer(r"(?<!\d)(\d{6})[\s'\"*]*(\d{9})(?!\d)", text or "")
        )
    )
    return {
        "cheque_numbers": cheque_numbers,
        "cheque_count": len(cheque_numbers) or None,
    }


def _extract_bank_statement(text: str) -> dict[str, Any]:
    """Extract fields from a bank statement."""
    if is_amortization_schedule(text):
        return {
            "_validation_blocked_reason": "amortization_schedule_not_bank_statement",
        }
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?)\s*[:\-–]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    stacked_account_number = (
        _stacked_bank_statement_account_number(text) if account_match is None else None
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    branch_match = re.search(r"\bbranch[ \t]*[:\-–][ \t]*([^\n\r]{2,70})", text, re.IGNORECASE)
    bank_match = re.search(
        r"(?:^|\n)\s*(?:bank(?:\s+name)?|name\s+of\s+bank)\s*(?:\n\s*)?[:\-–]\s*([^\n\r]{2,70})",
        text,
        re.IGNORECASE,
    )
    type_match = re.search(r"\baccount\s+type\s*[:\-–]?\s*([^\n\r]{2,30})", text, re.IGNORECASE)
    period_start, period_end = _extract_statement_period(text)
    transaction_dates = _extract_bank_transaction_dates(text)
    period_source = "statement_period" if period_start and period_end else None
    if not period_source and transaction_dates:
        period_start, period_end = transaction_dates[0], transaction_dates[-1]
        period_source = "transaction_dates"
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper())
    is_internal_approval = bool(
        re.search(
            r"request\s+for\s+approval|designation\s*:\s*|department\s*:\s*",
            text,
            re.IGNORECASE,
        )
    )
    phone_match = (
        None
        if is_internal_approval
        else re.search(
            r"(?:registered\s+mobile|customer\s+mobile|mobile\s+(?:number|no\.?))"
            r"\s*[:\-–]?\s*([6-9]\d{9})(?!\d)",
            text,
            re.IGNORECASE,
        )
    )
    # CAMS profile pages often present field labels in one column and their
    # values in another.  Prefer the value immediately following CKYC and a
    # date of birth, including title-case names (for example ``Kala Singh``).
    # The former all-caps-only pattern missed those pages, causing the generic
    # ``Name`` fallback to mistake a later profile label such as "Holding
    # Nature" for the account holder.
    profile_name = re.search(
        r"\bCKYC\s*\n\s*([A-Za-z][A-Za-z .]{2,70}(?:\n\s*[A-Za-z][A-Za-z .]{2,70})?)"
        r"\s*\n\s*\d{4}-\d{2}-\d{2}",
        text,
    )
    header_name = _bank_statement_header_holder_name(text)
    statement_title_name = _statement_holder_after_title(text)
    fallback_name = _line_after_label(text, "account holder", "customer name", "name")
    if fallback_name and fallback_name.casefold() in {
        "holding nature",
        "dob",
        "mobile",
        "landline",
        "email",
        "pan",
        "address",
        "nominee",
        "ckyc",
        "profile",
    }:
        fallback_name = None
    return {
        "account_holder_name": (
            _clean_name_like_value(re.sub(r"\s+", " ", profile_name.group(1))).title()
            if profile_name
            else header_name or statement_title_name or fallback_name
        ),
        "account_number": (
            _digits_only(account_match.group(1)) if account_match else stacked_account_number
        ),
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "bank_name": bank_match.group(1).strip() if bank_match else None,
        "branch": branch_match.group(1).strip() if branch_match else None,
        "account_type": type_match.group(1).strip() if type_match else None,
        "pan_number": pan_match.group(1) if pan_match else None,
        "phone_number": phone_match.group(1) if phone_match else None,
        "nach_status": (
            "done"
            if re.search(r"\be\s*-?\s*nach\s+(?:status\s*[-–:]*)?done\b", text, re.IGNORECASE)
            else None
        ),
        "statement_period_start": period_start,
        "statement_period_end": period_end,
        "_statement_date_evidence": (
            {
                "source": period_source,
                "transaction_dates": transaction_dates,
            }
            if period_source or transaction_dates
            else {}
        ),
    }


def _stacked_bank_statement_account_number(text: str) -> str | None:
    """Map an account value when OCR emits bank labels before their values.

    SBI statement headers commonly flatten as CIF, account, type and address
    labels followed by the corresponding values. Requiring that complete label
    sequence keeps unrelated long numbers out of account extraction.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    for cif_index, line in enumerate(lines):
        if not re.fullmatch(r"CIF\s+(?:Number|No\.?)\s*:?\s*", line, re.I):
            continue
        window = lines[cif_index : cif_index + 10]
        account_offsets = [
            offset
            for offset, candidate in enumerate(window[1:], start=1)
            if re.fullmatch(
                r"(?:Account|A/C)\s+(?:Number|No\.?)\s*:?\s*",
                candidate,
                re.I,
            )
        ]
        if not account_offsets:
            continue
        account_offset = account_offsets[0]
        remaining_labels = " ".join(window[account_offset + 1 :])
        if not re.search(r"\bA/C\s+Type\b", remaining_labels, re.I) or not re.search(
            r"\bAddress\b", remaining_labels, re.I
        ):
            continue
        values: list[str] = []
        for candidate in lines[cif_index + account_offset + 1 : cif_index + 24]:
            if re.match(
                r"^(?:Code|MICR|CKYCR|Statement\s+From|Date\s+of\s+Statement)\b",
                candidate,
                re.I,
            ):
                break
            if re.fullmatch(r"\d{9,18}", candidate):
                values.append(candidate)
        if len(values) >= 2:
            # The flattened value order mirrors the CIF/account label order.
            return values[1]
    return None


def _bank_statement_header_holder_name(text: str) -> str | None:
    """Extract the statement subject without confusing relatives or transactions.

    Bank layouts commonly print the holder after ``Welcome`` or as a standalone
    honorific line.  Relationship rows such as ``S/O: Kala Singh`` identify a
    relative, while transaction descriptions such as ``WDL TFR`` are not names.
    Keep this scan inside the statement header so neither can become the holder.
    """
    header = re.split(
        r"(?:^|\n)\s*(?:transactions?|transaction\s+details|date\s+particulars|"
        r"opening\s+balance|statement\s+of\s+account)\s*(?:\n|$)",
        str(text or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    lines = [re.sub(r"\s+", " ", line).strip(" ,.;") for line in header.splitlines()]

    label_pattern = re.compile(
        r"^(?:welcome|account\s+holder(?:\s+name)?|customer(?:'s)?\s+name|"
        r"name\s+of\s+(?:the\s+)?(?:account\s+holder|customer))\s*[:\-–]?\s*(.*)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines[:40]):
        match = label_pattern.match(line)
        if not match:
            continue
        candidates = [match.group(1), *lines[index + 1 : index + 4]]
        for raw_candidate in candidates:
            candidate = _clean_name_like_value(raw_candidate)
            if candidate:
                return candidate

    titled = re.search(
        r"\bof\s+(?:mr|mrs|ms|miss|shri|smt|sri|dr)\.?\s+"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)\s+(?=at\b|a/?c\b|account\b|$)",
        header,
        re.IGNORECASE,
    )
    if titled:
        candidate = _clean_name_like_value(titled.group(1))
        if candidate:
            return candidate

    for line in lines[:30]:
        if re.match(
            r"^(?:[wsdcf]\s*/?\s*o|wife\s+of|son\s+of|daughter\s+of|"
            r"care\s+of)\b",
            line,
            re.IGNORECASE,
        ):
            continue
        if not re.match(
            r"^(?:mr|mrs|ms|miss|shri|smt|sri|dr)\.?[\s:\-–]+",
            line,
            re.IGNORECASE,
        ):
            continue
        candidate = _clean_name_like_value(line)
        if candidate:
            return candidate
    return None


def _statement_holder_after_title(text: str) -> str | None:
    """Recover holder names from lender statement cover-page column order.

    OCR may emit the visual labels and lender logo before the statement title,
    so a generic ``Name`` lookup lands on a logo token. The subject printed
    immediately after an explicit statement-of-account title is stronger.
    """
    lines = [re.sub(r"\s+", " ", line).strip(" ,.;") for line in str(text or "").splitlines()]
    title_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(
                r"\b(?:customer(?:'s)?\s+)?statement\s+of\s+account\b|"
                r"\baccount\s+statement\b|\bbank\s+statement\b",
                line,
                re.IGNORECASE,
            )
        ),
        None,
    )
    if title_index is None:
        return None
    for line in lines[title_index + 1 : title_index + 6]:
        if re.search(
            r"\b(?:balance|transactions?|particulars|withdrawal|deposit|debit|credit)\b",
            line,
            re.IGNORECASE,
        ):
            break
        candidate = canonicalize_person_name(line)
        if not candidate.valid:
            continue
        latin_tokens = re.findall(r"[A-Za-z]+", str(candidate.value or ""))
        if len(latin_tokens) >= 2:
            return candidate.value
    return None


def _extract_passbook(text: str) -> dict[str, Any]:
    """Extract fields from a bank passbook page."""
    stacked_name_branch = re.search(
        r"(?:name|नाम)\s*:\s*\n\s*([0-9Xx* ]{6,24})\s*\n"
        r"[^\n]*(?:branch|शाखा)\s*:\s*([A-Z][A-Z .'-]{3,70})\s*\n"
        r"\s*([A-Z][A-Z .'-]{2,70})\s*\n\s*IFSC",
        text,
        re.IGNORECASE,
    )
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?|खाता\s*संख्या)\s*[:\-\u2013]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    branch_match = re.search(r"\bbranch[ \t]*[:\-–]?[ \t]*([^\n\r]{2,70})", text, re.IGNORECASE)
    bank_match = re.search(
        r"\b(?:bank\s+name|name\s+of\s+bank)\s*[:\-–]?\s*([^\n\r]{2,70})", text, re.IGNORECASE
    )
    type_match = re.search(r"\baccount\s+type\s*[:\-–]?\s*([^\n\r]{2,30})", text, re.IGNORECASE)
    passbook_name = re.search(
        r"\b(?:SHRI|SMT|SRI|MR|MRS)\.?[^A-Za-z\n]{0,6}([A-Z][A-Z ]{2,60})\b",
        text,
        re.IGNORECASE,
    )
    return {
        "account_holder_name": (
            _clean_name_like_value(passbook_name.group(1)) if passbook_name else None
        )
        or (_clean_name_like_value(stacked_name_branch.group(2)) if stacked_name_branch else None)
        or _line_after_label(text, "account holder", "customer name", "name", "नाम"),
        "account_number": (
            _digits_only(stacked_name_branch.group(1))
            if stacked_name_branch
            else (_digits_only(account_match.group(1)) if account_match else None)
        ),
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "bank_name": bank_match.group(1).strip() if bank_match else None,
        "branch": (
            stacked_name_branch.group(3).strip()
            if stacked_name_branch
            else (branch_match.group(1).strip() if branch_match else None)
        ),
        "account_type": type_match.group(1).strip() if type_match else None,
    }


def _extract_cheque(text: str) -> dict[str, Any]:
    """Extract fields from a cheque or cancelled cheque page."""
    cheque_number = _extract_cheque_number(text)
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|"
        r"a\s*[/\\lI|]?\s*c\s*(?:number|no\.)?|"
        r"a[lI]?[ct]\s*(?:number|no\.?))"
        r"\s*[:\-\u2013]?\s*(?:\r?\n\s*)?([0-9Xx*][0-9Xx* \t]{5,23})",
        text,
        re.IGNORECASE,
    )
    ifsc_match = re.search(r"\b([A-Z]{4}0[A-Z0-9]{6})\b", text.upper())
    amount = _extract_amount(text.lower(), "rupees", "amount")
    return {
        "account_holder_name": (
            _extract_cheque_signature_holder(text)
            or _line_after_label(text, "account holder", "name")
        ),
        "account_number": _digits_only(account_match.group(1)) if account_match else None,
        "cheque_number": cheque_number,
        "ifsc": ifsc_match.group(1) if ifsc_match else None,
        "cheque_date": _extract_date_near(text.lower(), "date"),
        "amount": amount,
        "is_cancelled": "cancelled" in text.lower() or "canceled" in text.lower(),
    }


def _extract_cheque_signature_holder(text: str) -> str | None:
    """Extract the printed holder name associated with the signature box."""
    for match in re.finditer(
        r"\b(?:mr|mrs|ms|miss|shri|smt|sri)\.?\s+"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)(?=\s*(?:\r?\n|$))",
        str(text or ""),
        re.IGNORECASE,
    ):
        signature_window = str(text or "")[match.end() : match.end() + 240]
        if not re.search(
            r"\b(?:please\s+sign\s+abov[es]|authori[sz]ed\s+signatory)\b",
            signature_window,
            re.IGNORECASE,
        ):
            continue
        candidate = _clean_name_like_value(match.group(1))
        if canonicalize_person_name(candidate).valid:
            return candidate
    return None


def _extract_cheque_number(text: str) -> str | None:
    labeled = re.search(
        r"(?:cheque\s*(?:number|no\.?)|chq\s*(?:number|no\.?))\s*[:\-\u2013]?\s*(\d{6})",
        text,
        re.IGNORECASE,
    )
    if labeled:
        return labeled.group(1)
    candidates = re.findall(r"\b\d{6}\b", text)
    return candidates[0] if candidates else None


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
        start = re.search(rf"statement\s+from\s*[:\-–]?\s*({date_pattern})", text, re.IGNORECASE)
        end = re.search(rf"statement\s+to\s*[:\-–]?\s*({date_pattern})", text, re.IGNORECASE)
        if start and end:
            return _parse_date(start.group(1)), _parse_date(end.group(1))
        return None, None
    return _parse_date(match.group(1)), _parse_date(match.group(2))


def _extract_bank_transaction_dates(text: str) -> list[str]:
    """Extract transaction-table dates without treating header identity dates as activity."""
    table_anchor = re.search(
        r"\b(?:txn|transaction|value)\s*date\b|"
        r"\bdate\s+(?:narration|particulars|description|withdrawal|deposit|debit|credit)\b|"
        r"\bdate\s*\n\s*(?:narration|particulars|description)\b",
        str(text or ""),
        re.IGNORECASE,
    )
    if not table_anchor:
        return []

    date_pattern = re.compile(
        r"\b(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
        r"|\d{4}[/\-.]\d{2}[/\-.]\d{2}"
        r"|\d{1,2}[-\s]+[A-Za-z]+[-\s]+\d{4})\b"
    )
    observed: list[str] = []
    for match in date_pattern.finditer(str(text or "")[table_anchor.end() :]):
        parsed = _parse_date(match.group(0))
        if parsed:
            observed.append(parsed)
    return sorted(set(observed))


def _extract_nach_form(text: str) -> dict[str, Any]:
    lower = text.lower()
    account_match = re.search(
        r"(?:account\s*(?:number|no\.?|#)|a/c\s*(?:no\.?|number)?)\s*[:\-–]?\s*([0-9Xx* ]{6,24})",
        text,
        re.IGNORECASE,
    )
    if "not registered" in lower or "registration pending" in lower:
        registration_status = "not registered"
    elif (
        "registered" in lower
        or "registration successful" in lower
        or re.search(r"\bregister[_\s-]*success(?:ful)?\b", lower)
        or "active" in lower
    ):
        registration_status = "registered"
    else:
        registration_status = None
    status_screen_name = re.search(
        r"\b[6-9]\d{9}\s*\n\s*([A-Z][A-Z .'-]{5,70})\s*\n\s*CRN\s*:",
        text,
        re.IGNORECASE,
    )
    return {
        "registration_status": registration_status,
        "account_holder_name": (
            _clean_name_like_value(status_screen_name.group(1))
            if status_screen_name
            else _line_after_label(text, "account holder", "customer name", "name")
        ),
        "account_number": _digits_only(account_match.group(1)) if account_match else None,
    }
