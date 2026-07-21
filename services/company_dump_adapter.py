"""Convert a raw company database dump into the trusted verification manifest."""

from __future__ import annotations

import json
import re
from typing import Any


SMART_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})
MISSING_VALUES = {"", "-", "na", "n/a", "none", "null", "not provided"}


class CompanyDumpConversionError(ValueError):
    """Raised when pasted text does not contain enough recognizable company data."""


def is_company_database_dump(value: str | dict[str, Any]) -> bool:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        return bool(keys & {"applicantdetails", "camdetails", "coapplicantdetails", "applicantkyc"})
    text = str(value or "")
    return bool(
        re.search(r"Loan Application:\s*RJ\d+", text, re.IGNORECASE)
        or re.search(r'"(?:applicantdetails|camdetails|coapplicantdetails)"\s*:', text, re.IGNORECASE)
    )


def convert_company_database_dump(value: str | dict[str, Any]) -> dict[str, Any]:
    """Return a canonical manifest from valid JSON or a tolerant pasted dump.

    The tolerant path intentionally extracts only known trusted fields. Masked,
    malformed, placeholder, and invalid exact identifiers are omitted so they
    do not become false mismatches.
    """
    if isinstance(value, dict):
        raw_text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        raw_text = str(value or "")
    text = raw_text.translate(SMART_QUOTES)
    if not is_company_database_dump(text):
        raise CompanyDumpConversionError("The pasted content is not a recognized company database dump.")

    applicant = _first_object(text, "applicantdetails")
    cam = _first_object(text, "camdetails")
    applicant_kyc = _first_object(text, "applicantkyc")
    applicant_address = _first_object(text, "applicantaddressdetails")
    coapplicants = _array_objects(text, "coapplicantdetails")
    coapplicant_kyc = _array_objects(text, "coapplicantkyc")
    entity_addresses = _array_objects(text, "entityaddressdetails")
    dbmaker = _first_object(text, "dbmaker")

    primary_name = _value(applicant, "entityName") or _value(cam, "applicantname")
    if not primary_name:
        raise CompanyDumpConversionError(
            "Could not find applicantdetails.entityName or camdetails.applicantname in the dump."
        )

    warnings: list[str] = []
    primary = _person(
        role="primary",
        details=applicant,
        kyc=applicant_kyc,
        address=_best_address(entity_addresses, primary_name, "applicant") or applicant_address,
        warnings=warnings,
    )
    primary["applicant_name"] = primary_name

    loan_amount = _valid_amount(
        _value(cam, "sanctionamount")
        or _value(cam, "loanamount")
        or _value(dbmaker, "approvedPrincipalAmount")
        or _value(dbmaker, "principalAmount")
    )
    if loan_amount:
        primary["loan_amount"] = loan_amount
    _copy_if_present(primary, "tenure", _valid_integer(_value(cam, "tenure") or _value(dbmaker, "noOfRepayment")))
    _copy_if_present(primary, "emi", _valid_amount(_value(cam, "emiamount") or _value(dbmaker, "emi")))
    _copy_if_present(primary, "roi", _valid_amount(_value(dbmaker, "interestRate")))

    people: dict[str, dict[str, Any]] = {"primary": primary}
    kyc_by_name = {
        _name_key(_value(item, "entityName")): item
        for item in coapplicant_kyc
        if _value(item, "entityName")
    }
    for index, details in enumerate(coapplicants, start=1):
        name = _value(details, "entityName")
        if not name:
            continue
        person_id = f"coapplicant_{index}"
        person = _person(
            role="coapplicant",
            details=details,
            kyc=kyc_by_name.get(_name_key(name), ""),
            address=_best_address(entity_addresses, name, "co-applicant"),
            warnings=warnings,
        )
        person["applicant_name"] = name
        people[person_id] = person

    loan_id = _loan_id(text, applicant, cam)
    manifest = {
        "schema_version": "1.0",
        "loan_id": loan_id,
        "product_type": "LAP",
        "branch": _clean_text(_value(cam, "branch")) or None,
        "source": "raw_company_database_dump",
        "people": people,
        "document_index": [],
    }
    if warnings:
        manifest["conversion_warnings"] = sorted(set(warnings))
    return manifest


def _person(
    *,
    role: str,
    details: str,
    kyc: str,
    address: str,
    warnings: list[str],
) -> dict[str, Any]:
    person: dict[str, Any] = {"role": role}
    _copy_if_present(person, "date_of_birth", _valid_date(_value(details, "dob")))
    _copy_if_present(person, "phone_number", _valid_digits(_value(details, "mobileNo"), 10))
    _copy_if_present(person, "pan_number", _valid_pan(_value(kyc, "panNumber")))
    aadhaar = _value(kyc, "aadhaarNumber")
    valid_aadhaar = _valid_digits(aadhaar, 12)
    if valid_aadhaar:
        person["aadhaar_number"] = valid_aadhaar
    elif aadhaar and _masked_last4(aadhaar):
        person["aadhaar_last4"] = _masked_last4(aadhaar)
        warnings.append("Masked Aadhaar values were retained as last-four evidence and excluded from exact matching.")

    address_value = _value(address, "address") or _value(details, "communicationAddress")
    _copy_if_present(person, "address", _clean_text(address_value))
    _copy_if_present(person, "pin_code", _valid_digits(_value(address, "pincode"), 6))
    return person


def _loan_id(text: str, applicant: str, cam: str) -> str:
    header = re.search(r"Loan Application:\s*([A-Z]{2}\d+)", text, re.IGNORECASE)
    if header:
        return header.group(1).upper()
    application_id = _clean_text(_value(cam, "applicationid"))
    if application_id:
        return application_id
    numeric = _clean_text(_value(applicant, "loanId") or _value(cam, "loanId"))
    if numeric:
        return numeric
    raise CompanyDumpConversionError("Could not determine the loan ID from the database dump.")


def _first_object(text: str, key: str) -> str:
    section = _balanced_section(text, key, "{", "}")
    return section or ""


def _array_objects(text: str, key: str) -> list[str]:
    section = _balanced_section(text, key, "[", "]")
    if not section:
        return []
    return _balanced_children(section, "{", "}")


def _balanced_section(text: str, key: str, opening: str, closing: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{opening}', text, re.IGNORECASE)
    if not match:
        return None
    start = text.find(opening, match.start())
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def _balanced_children(text: str, opening: str, closing: str) -> list[str]:
    children: list[str] = []
    depth = 0
    start: int | None = None
    for index, char in enumerate(text):
        if char == opening:
            if depth == 0:
                start = index
            depth += 1
        elif char == closing and depth:
            depth -= 1
            if depth == 0 and start is not None:
                children.append(text[start : index + 1])
                start = None
    return children


def _value(section: str, key: str) -> str | None:
    if not section:
        return None
    quoted = re.search(
        rf'"{re.escape(key)}"\s*:\s*"([^"\r\n]*)"',
        section,
        re.IGNORECASE,
    )
    if quoted:
        return _clean_scalar(quoted.group(1))
    scalar = re.search(
        rf'"{re.escape(key)}"\s*:\s*([^,}}\]\r\n]+)',
        section,
        re.IGNORECASE,
    )
    if scalar:
        return _clean_scalar(scalar.group(1))
    match = re.search(
        rf'(?im)^\s*"{re.escape(key)}"\s*:\s*(.*?)(?:,\s*$|\s*$)',
        section,
    )
    return _clean_scalar(match.group(1)) if match else None


def _clean_scalar(value: str | None) -> str | None:
    text = str(value or "").strip().translate(SMART_QUOTES)
    if not text:
        return None
    text = re.sub(r"[,}\]]\s*$", "", text).strip()
    text = text.strip('"\'').strip()
    return None if text.lower() in MISSING_VALUES else text


def _clean_text(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,\"'")
    return None if not text or text.lower() in MISSING_VALUES else text


def _valid_digits(value: str | None, length: int) -> str | None:
    if not value or re.search(r"[xX*]", value):
        return None
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) == length else None


def _masked_last4(value: str | None) -> str | None:
    if not value or not re.search(r"[xX*]", value):
        return None
    match = re.search(r"(\d{4})\D*$", value)
    return match.group(1) if match else None


def _valid_pan(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", str(value or "")).upper()
    return normalized if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", normalized) else None


def _valid_date(value: str | None) -> str | None:
    text = _clean_text(value)
    return text if text and re.search(r"\d{4}", text) else None


def _valid_amount(value: str | None) -> str | None:
    text = str(value or "").replace(",", "").strip()
    match = re.fullmatch(r"\d+(?:\.\d+)?", text)
    return text if match else None


def _valid_integer(value: str | None) -> int | None:
    text = str(value or "").strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def _best_address(addresses: list[str], name: str, entity_type: str) -> str:
    candidates = [
        item
        for item in addresses
        if _name_key(_value(item, "entityName")) == _name_key(name)
        and entity_type in str(_value(item, "entityType") or "").lower()
    ]
    permanent = next(
        (item for item in candidates if str(_value(item, "addressSubType") or "").lower() == "permanent"),
        None,
    )
    return permanent or (candidates[0] if candidates else "")


def _name_key(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _copy_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, "", [], {}):
        target[key] = value
