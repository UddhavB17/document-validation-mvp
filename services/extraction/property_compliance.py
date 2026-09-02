"""Property, compliance, and ancillary document extractors."""

from __future__ import annotations

import re
from typing import Any

from services.cersai import DEBTOR_BASED, search_criteria_text, search_type
from services.extraction._shared import (
    _clean_name_like_value,
    _extract_amount,
    _extract_date_after_label,
    _extract_date_near,
    _inline_identifier_after_label,
    _inline_text_after_label,
    _line_after_label,
    _lines_after_label,
    _lines_after_label_until_stop,
    _normalize_amount,
    _parse_date,
    _value_after_label,
)


def _extract_utility_bill(text: str) -> dict[str, Any]:
    """Extract address-proof fields from electricity/water/gas/phone bills."""
    consumer_match = re.search(
        r"(?:consumer|customer|account)\s*(?:name|holder)?\s*[:\-–]?\s*([^\n\r]{3,80})",
        text,
        re.IGNORECASE,
    )
    address_stop_labels = {
        "bill date",
        "billing date",
        "due date",
        "amount",
        "total amount",
        "consumer number",
        "consumer no",
        "account number",
        "meter number",
    }
    address = (
        _lines_after_label_until_stop(text, "service address", stop_labels=address_stop_labels)
        or _lines_after_label_until_stop(text, "billing address", stop_labels=address_stop_labels)
        or _lines_after_label_until_stop(text, "supply address", stop_labels=address_stop_labels)
        or _utility_service_block_after_bill_heading(text)
        or _lines_after_label_until_stop(text, "address", stop_labels=address_stop_labels)
    )
    if not address:
        # Some OCR engines flatten the entire bill into one line. Preserve the
        # relationship/address segment printed after the consumer name, while
        # stopping before the YYYYMM billing month so it cannot become a PIN.
        inline_address = re.search(
            r"\b(?:S\s*/\s*O|D\s*/\s*O|W\s*/\s*O|C\s*/\s*O)\s*[:\-]?\s*"
            r"([A-Z][A-Z ]{5,100}?)(?=\s+20\d{4}\b)",
            text,
            re.IGNORECASE,
        )
        if inline_address:
            relation_start = re.search(
                r"\b(?:S\s*/\s*O|D\s*/\s*O|W\s*/\s*O|C\s*/\s*O)\b",
                inline_address.group(0),
                re.IGNORECASE,
            )
            address = (
                inline_address.group(0)[relation_start.start() :].strip()
                if relation_start
                else None
            )
    pin_match = re.search(r"(?<!\d)([1-8]\d{5})(?!\d)", address or "")
    if pin_match is None:
        pin_match = re.search(
            r"(?:pin\s*code|pincode|postal\s*code)\s*[:\-\u2013]?\s*([1-8]\d{5})",
            text,
            re.IGNORECASE,
        )
    holder_name = _clean_name_like_value(consumer_match.group(1)) if consumer_match else None
    if not holder_name:
        relation_name = re.search(
            r"\b([A-Z][A-Z ]{2,50})\s+(?:S/O|D/O|W/O|C/O)\b",
            text,
        )
        holder_name = _clean_name_like_value(relation_name.group(1)) if relation_name else None
    return {
        "applicant_name": holder_name,
        "address": address,
        "pin_code": pin_match.group(1) if pin_match else None,
        "bill_date": (
            _parse_date(date_match.group(0))
            if (date_match := re.search(r"\b\d{2}[-/]\d{2}[-/]\d{4}\b", text))
            else None
        ),
    }


def _utility_service_block_after_bill_heading(text: str) -> str | None:
    """Read the consumer/service block and avoid the utility's own header.

    Some electricity bills print ``ADDRESS`` only in the provider letterhead,
    while the actual premises follows ``E-ELECTRICITY BILL`` without a label.
    """
    lines = [line.strip() for line in str(text or "").splitlines()]
    start = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if re.search(r"\b(?:e[- ]?electricity|electricity|water|gas)\s+bill\b", line, re.I)
        ),
        None,
    )
    if start is None:
        return None
    collected: list[str] = []
    for line in lines[start : start + 12]:
        if not line:
            continue
        if re.search(
            r"\b(?:sub[- ]?division\s+office|bill\s+date|due\s+date|consumer\s+(?:no|number)|meter\s+(?:no|number))\b",
            line,
            re.I,
        ):
            break
        if re.search(r"\b(?:website|helpline|gst\s*(?:no|number))\b|www\.|\S+@\S+", line, re.I):
            continue
        collected.append(line)
    if (
        len(collected) >= 2
        and re.search(r"\d", collected[1])
        and (
            not re.search(r"\d", collected[0])
            or re.search(r"\b(?:exe|engineer|engr)\b", collected[0], re.I)
        )
    ):
        # The first row is often the consumer name; verification treats it as
        # separate from the premises address.
        collected = collected[1:]
    value = re.sub(r"\s+", " ", " ".join(collected)).strip(" ,.;")
    return value if len(re.findall(r"[A-Za-z\u0900-\u097f]", value)) >= 6 else None


def _extract_cersai_report(text: str) -> dict[str, Any]:
    """Extract CERSAI metadata and only the entered debtor identity.

    The CERSAI corporate PAN and identities listed in search results are not the
    report subject.  Keeping extraction inside ``Search Criteria Entered`` is
    what makes applicant/co-applicant ownership deterministic.
    """
    t = text.lower()
    criteria_text = search_criteria_text(text)
    cersai_search_type = search_type(text)
    debtor_based = cersai_search_type == DEBTOR_BASED
    debtor_pan = _value_after_label(criteria_text, "pan") if debtor_based else None
    if debtor_pan and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", debtor_pan.upper()):
        debtor_pan = None
    transaction_id = _value_after_label(
        text, "transaction id", "transaction id / qrf", "transaction id / qrf no"
    )
    search_reference = _value_after_label(text, "search reference number")
    debtor_name = _value_after_label(criteria_text, "name of the debtor") if debtor_based else None
    debtor_dob = _extract_date_after_label(criteria_text, "date of birth") if debtor_based else None
    search_result = None
    if "no match found" in t:
        search_result = "No Match Found"
    elif "match found" in t:
        search_result = "Match Found"

    return {
        "cersai_search_type": cersai_search_type,
        "debtor_name": debtor_name,
        "debtor_pan_number": debtor_pan.upper() if debtor_pan else None,
        "debtor_date_of_birth": debtor_dob,
        # Backward-compatible person-field aliases. They always refer to the
        # entered debtor, never to a party found in the result section.
        "applicant_name": debtor_name,
        "pan_number": debtor_pan.upper() if debtor_pan else None,
        "date_of_birth": debtor_dob,
        "search_reference_number": search_reference,
        "transaction_id": transaction_id,
        "search_result": search_result,
        "report_date": _extract_date_near(
            t, "report download date", "report downloaded on", "downloaded on", "report date"
        ),
    }


def _extract_salary_slip(text: str) -> dict[str, Any]:
    """Extract fields from a salary slip."""
    t = text.lower()
    return {
        "applicant_name": _line_after_label(text, "employee name", "name"),
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


def _extract_stamp_duty(text: str) -> dict[str, Any]:
    lower = text.lower()
    state_match = re.search(
        r"government\s+of\s+([A-Za-z][A-Za-z &.-]{2,40})",
        text,
        re.IGNORECASE,
    )
    duty_amount_match = re.search(
        r"stamp\s+duty\s+amount\s*(?:\(\s*rs\.?\s*\))?\s*[:\-–]?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    consideration_match = re.search(
        r"consideration\s+(?:price|amount)\s*(?:\(\s*rs\.?\s*\))?\s*[:\-–]?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    instrument_description = _value_after_label(
        text, "description of document", "description of instrument", "instrument description"
    )
    article_match = re.search(
        r"\bArticle\s+([0-9]+(?:\([A-Za-z0-9]+\))?)",
        instrument_description or text,
        re.IGNORECASE,
    )
    return {
        "stamp_date": _extract_date_near(
            lower, "stamp date", "date of stamp", "certificate issued date", "issue date"
        ),
        "stamp_certificate_number": _value_after_label(
            text, "certificate no", "certificate number", "e-stamp number"
        ),
        "stamp_jurisdiction_state": state_match.group(1).strip(" .") if state_match else None,
        "stamp_duty_amount": _normalize_amount(duty_amount_match.group(1))
        if duty_amount_match
        else None,
        "stamp_consideration_amount": (
            _normalize_amount(consideration_match.group(1)) if consideration_match else None
        ),
        "stamp_instrument_description": instrument_description,
        "stamp_article": article_match.group(1) if article_match else None,
        "stamp_unique_document_reference": _value_after_label(
            text, "unique doc. reference", "unique document reference", "uin"
        ),
        "stamp_account_reference": _value_after_label(text, "account reference"),
        "stamp_purchased_by": _value_after_label(text, "purchased by"),
        "stamp_first_party": _value_after_label(text, "first party"),
        "stamp_second_party": _value_after_label(text, "second party"),
    }


def _extract_insurance_form(text: str) -> dict[str, Any]:
    """Extract insurance-form fields without collapsing IDs into loan IDs.

    A proposal form can carry three different namespaces: the insurer's
    application/proposal number, the lender's loan application number and the
    lender's loan account number.  Keeping them separate prevents a local
    proposal ID from being compared with the trusted loan application ID.
    """
    insurer_match = re.search(
        r"(?:^|\n)\s*((?:[A-Z][A-Za-z0-9&.'()-]*\s+){1,8}"
        r"Insurance\s+(?:Company|Co\.?|Limited|Ltd\.?))\b",
        text,
        re.IGNORECASE,
    )
    policy_tenure_match = re.search(
        r"(?:^|\n)\s*Policy\s+Tenure\s*[:\-–]?\s*"
        r"(\d{1,3})\s*(Years?|Months?)\b",
        text,
        re.IGNORECASE,
    )
    policy_tenure_months = None
    if policy_tenure_match:
        policy_tenure_months = int(policy_tenure_match.group(1))
        if policy_tenure_match.group(2).casefold().startswith("year"):
            policy_tenure_months *= 12

    return {
        "insurer_name": (
            re.sub(r"\s+", " ", insurer_match.group(1)).strip() if insurer_match else None
        ),
        "insurance_application_number": _inline_identifier_after_label(
            text,
            "insurance application number",
            "insurance application no",
            "application number",
            "application no",
        ),
        "insurance_proposal_number": _inline_identifier_after_label(
            text,
            "proposal number",
            "proposal no",
        ),
        "insurance_policy_number": _inline_identifier_after_label(
            text,
            "policy number",
            "policy no",
        ),
        "loan_application_number": _inline_identifier_after_label(
            text,
            "loan application number",
            "loan application no",
        ),
        "loan_account_number": _inline_identifier_after_label(
            text,
            "loan account number",
            "loan account no",
            "loan a/c no",
        ),
        "proposer_name": _inline_text_after_label(text, "proposer name"),
        "insured_person_name": _inline_text_after_label(
            text,
            "insured person name",
            "name of person to be insured",
        ),
        "nominee_name": _inline_text_after_label(text, "nominee name"),
        "policy_tenure_months": policy_tenure_months,
        "sum_insured": _extract_amount(text.casefold(), "sum insured"),
        "total_premium": _extract_amount(text.casefold(), "total premium", "premium amount"),
    }


def _extract_insurance_consent(text: str) -> dict[str, Any]:
    lower = text.lower()
    tenure_match = re.search(r"insurance\s+tenure\s*[:\-–]?\s*(\d+)\s*(months?|years?)?", lower)
    insurance_tenure: int | None = None
    if tenure_match:
        insurance_tenure = int(tenure_match.group(1))
        if str(tenure_match.group(2) or "").startswith("year"):
            insurance_tenure *= 12
    return {
        "insurance_tenure": insurance_tenure,
        "applicant_name": _line_after_label(text, "applicant name", "customer name", "name"),
    }


def _extract_clearance_report(text: str) -> dict[str, Any]:
    lower = text.lower()
    status_window = _clearance_status_window(text)
    status_lower = status_window.lower()
    rejected = next(
        (
            status
            for status in ("not cleared", "not clear", "negative", "rejected", "pending")
            if status in status_lower
        ),
        None,
    )
    accepted = next(
        (
            status
            for status in (
                "technically cleared",
                "title clear",
                "cleared",
                "clear",
                "positive",
                "approved",
                "recommended",
                "satisfactory",
            )
            if status in status_lower
        ),
        None,
    )
    return {
        "clearance_status": rejected or accepted,
        "report_status": rejected or accepted,
        "report_date": _extract_date_near(lower, "report date", "date of report", "as on"),
    }


def _clearance_status_window(text: str) -> str:
    for label in (
        "clearance status",
        "technical status",
        "report status",
        "recommendation",
        "remarks",
    ):
        value = _lines_after_label(text, label, max_lines=3)
        if value:
            return value
    return " ".join(str(text or "").splitlines()[:20])
