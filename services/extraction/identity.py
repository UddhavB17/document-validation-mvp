"""Identity-document extractors: PAN, Aadhaar, voter ID, driving licence."""

from __future__ import annotations

import re
from typing import Any

from services.extraction._shared import (
    _clean_name_like_value,
    _digits_only,
    _extract_date_after_label,
    _extract_date_below_label,
    _extract_date_near,
    _is_past_date,
    _line_after_label,
    _lines_after_label,
    _parse_date,
    _xml_cleaner,
)
from services.identifiers import plausible_aadhaar_digits
from services.validation_gates import is_aadhaar_verification_appendix


def _extract_pan(text: str) -> dict[str, Any]:
    """Extract fields from a PAN card."""
    text = _xml_cleaner(text)
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper())
    if not pan_match and not re.search(
        r"\b(?:permanent\s+account\s+number|income\s+tax|govt\.?\s+of\s+india|pan\s+card)\b",
        text,
        re.IGNORECASE,
    ):
        return {}
    inline_name = None
    if pan_match:
        after_pan = text[pan_match.end() : pan_match.end() + 160]
        name_match = re.search(
            r"\bH?Name\s+([A-Za-z][A-Za-z ]{2,60}?)"
            r"(?=\s+(?:[A-Za-z]?\d|[\u0900-\u097f]|Date\b|Father\b))",
            after_pan,
            re.IGNORECASE,
        ) or re.search(
            r"(?:Account\s+Number\s+)?(?:नाम\s*)?(?:[A-Z]?\s*Name\s+)?"
            r"([A-Za-z][A-Za-z ]{2,60}?)(?=\s+(?:[\u0900-\u097f]|Date\b|Father\b))",
            after_pan,
            re.IGNORECASE,
        )
        inline_name = _clean_name_like_value(name_match.group(1)) if name_match else None
    dob = _extract_date_near(text.lower(), "date of birth", "dob")
    if dob is None:
        damaged_date = re.search(
            r"(?:date|fafuDate)\s+(\d{2})7(\d{2})/(\d{4})", text, re.IGNORECASE
        )
        if damaged_date:
            dob = _parse_date("/".join(damaged_date.groups()))
    return {
        "applicant_name": _line_after_label(
            text,
            "name",
            "applicant name",
            "card holder name",
        )
        or inline_name,
        "pan_number": pan_match.group(1) if pan_match else None,
        "dob": dob,
    }


def _extract_aadhaar(text: str) -> dict[str, Any]:
    """Extract fields from an Aadhaar card."""
    if is_aadhaar_verification_appendix(text):
        return {"_aadhaar_verification_appendix": True}
    heading = " ".join(line.strip() for line in str(text or "").splitlines()[:6] if line.strip())
    if re.search(
        r"\bself[\s-]*declaration\b[\s\S]{0,80}\bcurrent\s+address\b",
        heading,
        re.IGNORECASE,
    ):
        return {}
    xml_fields = _extract_aadhaar_xml(text)
    text = _xml_cleaner(text)
    digilocker_fields = _extract_digilocker_aadhaar_summary(text)
    aadhaar_match = re.search(r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)", text)
    authority_evidence = bool(
        re.search(
            r"unique\s+identification\s+authority|\buidai\b|e-?aadhaar|"
            r"भारतीय\s+विशिष्ट\s+पहचान|मेरा\s+आधार",
            text,
            re.IGNORECASE,
        )
    )
    form_kyc_section = bool(
        re.search(
            r"(?:applicant|co[\s-]*applicant|guarantor)\s+kyc\s+details",
            text,
            re.IGNORECASE,
        )
    )
    if form_kyc_section and not authority_evidence:
        return {}
    aadhaar_number = plausible_aadhaar_digits(aadhaar_match.group(1)) if aadhaar_match else None
    relation_match = re.search(
        r"\b(S\s*/\s*O|D\s*/\s*O|W\s*/\s*O|C\s*/\s*O|son\s+of|daughter\s+of|wife\s+of|care\s+of)\b\s*[:\-]?\s*([^\n\r,]{3,70})",
        text,
        re.IGNORECASE,
    )
    qualifier = re.sub(r"\s+", "", relation_match.group(1)).upper() if relation_match else None
    qualifier = {"SONOF": "S/O", "DAUGHTEROF": "D/O", "WIFEOF": "W/O", "CAREOF": "C/O"}.get(
        qualifier or "", qualifier
    )
    result = {
        "applicant_name": (
            xml_fields.get("applicant_name")
            or digilocker_fields.get("applicant_name")
            or _line_after_label(text, "name", "नाम")
        ),
        "aadhaar_number": aadhaar_number,
        "aadhaar_last4": xml_fields.get("aadhaar_last4") or digilocker_fields.get("aadhaar_last4"),
        "dob": (
            xml_fields.get("dob")
            or digilocker_fields.get("dob")
            or _extract_date_near(text.lower(), "date of birth", "dob", "year of birth", "yob")
        ),
        "address": (
            xml_fields.get("address")
            or digilocker_fields.get("address")
            or _extract_aadhaar_address(text)
        ),
        "pin_code": xml_fields.get("pin_code") or digilocker_fields.get("pin_code"),
        "gender": xml_fields.get("gender") or digilocker_fields.get("gender"),
        "relationship_qualifier": (
            xml_fields.get("relationship_qualifier")
            or digilocker_fields.get("relationship_qualifier")
            or qualifier
        ),
        "related_person_name": (
            xml_fields.get("related_person_name") or digilocker_fields.get("related_person_name")
        )
        or (_clean_name_like_value(relation_match.group(2)) if relation_match else None),
    }
    return result


def _extract_digilocker_aadhaar_summary(text: str) -> dict[str, Any]:
    """Parse DigiLocker label-first/value-second Aadhaar summary pages."""
    if not re.search(r"DigiLocker\s+verified\s+e-?Aadhaar", text or "", re.IGNORECASE):
        return {}

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    fields: dict[str, Any] = {}
    masked = re.search(r"(?i)\b[x*]{4,}(\d{4})\b", text or "")
    if masked:
        fields["aadhaar_last4"] = masked.group(1)

    for index, line in enumerate(lines):
        if not re.fullmatch(r"\d{2}[-/.]\d{2}[-/.]\d{4}", line):
            continue
        if index == 0 or index + 1 >= len(lines):
            continue
        gender = lines[index + 1].upper()
        if gender not in {"MALE", "FEMALE", "TRANSGENDER"}:
            continue
        name = _clean_name_like_value(lines[index - 1])
        if name:
            fields["applicant_name"] = name
            fields["dob"] = _parse_date(line)
            fields["gender"] = gender
            break

    relationship_pattern = re.compile(r"^(S/O|D/O|W/O|C/O)\s*:?\s*([^,\n]{2,70})", re.IGNORECASE)
    relationship_rows = [
        index for index, line in enumerate(lines) if relationship_pattern.match(line)
    ]
    for index in relationship_rows:
        line = lines[index]
        relationship = relationship_pattern.match(line)
        assert relationship is not None
        related_name = _clean_name_like_value(relationship.group(2))
        if related_name and not fields.get("related_person_name"):
            fields["relationship_qualifier"] = relationship.group(1).upper()
            fields["related_person_name"] = related_name

        # DigiLocker table extraction often repeats the relationship at the
        # start of the actual address, splitting both a name and PIN over lines
        # ("S/O: Nanga" + "Ram,Deoli..." and "30402" + "3").
        nearby = lines[index : index + 7]
        if not any("," in part for part in nearby[:3]):
            continue
        address = re.sub(r"\s+", " ", " ".join(nearby))
        address = re.sub(
            r"\b([1-8]\d{1,4})\s+(\d{1,4})\b",
            lambda match: (
                match.group(1) + match.group(2)
                if len(match.group(1) + match.group(2)) == 6
                else match.group(0)
            ),
            address,
        )
        pin = re.search(r"\b([1-8]\d{5})\b", address)
        if not pin:
            continue
        address = address[: pin.end()]
        combined_relationship = relationship_pattern.match(address)
        if combined_relationship:
            combined_name = _clean_name_like_value(combined_relationship.group(2))
            if combined_name and len(combined_name) > len(
                str(fields.get("related_person_name") or "")
            ):
                fields["related_person_name"] = combined_name
            address = address[combined_relationship.end() :].lstrip(" ,")
        fields["pin_code"] = pin.group(1)
        fields["address"] = address
        break

    if not fields.get("pin_code"):
        pin = re.search(r"(?m)^\s*([1-8]\d{5})\s*$", text or "")
        if pin:
            fields["pin_code"] = pin.group(1)
    return fields


def _extract_aadhaar_xml(text: str) -> dict[str, Any]:
    """Read identity and PoA attributes from digitally signed e-Aadhaar XML.

    The certificate following ``Poa`` contains a second postal address for the
    signing authority.  Regexing the word "address" therefore captured the
    certificate subject instead of the holder's Aadhaar address.
    """
    # Aadhaar XML back pages can omit ``Poi`` while still carrying the holder
    # name in ``LData`` and the authoritative address/relationship in ``Poa``.
    # Requiring ``Poi`` made those pages fall through to generic/LLM extraction,
    # which could mistake the signing certificate's postal code for the
    # holder's PIN and the holder's own name for their related person's name.
    if "<UidData" not in text or "<Poa" not in text:
        return {}
    try:
        uid_fragment = re.search(r"<UidData\b[^>]*", text, re.IGNORECASE)
        poi_fragment = re.search(r"<Poi\b[^>]*/?>", text, re.IGNORECASE)
        ldata_fragment = re.search(r"<LData\b[^>]*/?>", text, re.IGNORECASE)
        poa_fragment = re.search(r"<Poa\b[^>]*/?>", text, re.IGNORECASE)
        if not (uid_fragment and poa_fragment):
            return {}

        def attributes(fragment: str) -> dict[str, str]:
            return {
                key.lower(): value
                for key, value in re.findall(r'([A-Za-z][A-Za-z0-9]*)="([^"]*)"', fragment)
            }

        uid = attributes(uid_fragment.group(0)).get("uid", "")
        poi = attributes(poi_fragment.group(0)) if poi_fragment else {}
        ldata = attributes(ldata_fragment.group(0)) if ldata_fragment else {}
        poa = attributes(poa_fragment.group(0))
        co_value = poa.get("co", "").strip()
        relation_match = re.match(r"\s*(S/O|D/O|W/O|C/O)\s*:\s*(.+)", co_value, re.IGNORECASE)
        address_parts = [
            poa.get("house"),
            poa.get("street"),
            poa.get("lm"),
            poa.get("loc"),
            poa.get("vtc"),
            poa.get("po"),
            poa.get("subdist"),
            poa.get("dist"),
            poa.get("state"),
            poa.get("country"),
            poa.get("pc"),
        ]
        address = ", ".join(
            dict.fromkeys(part.strip() for part in address_parts if part and part.strip())
        )
        return {
            "applicant_name": poi.get("name") or ldata.get("name") or None,
            "aadhaar_last4": _digits_only(uid)[-4:] if len(_digits_only(uid)) >= 4 else None,
            "dob": _parse_date(poi.get("dob")) if poi.get("dob") else None,
            "gender": {"M": "MALE", "F": "FEMALE", "T": "TRANSGENDER"}.get(
                poi.get("gender", "").upper()
            ),
            "address": address or None,
            "pin_code": poa.get("pc") or None,
            "relationship_qualifier": relation_match.group(1).upper() if relation_match else None,
            "related_person_name": _clean_name_like_value(relation_match.group(2))
            if relation_match
            else None,
            "_aadhaar_xml_demographic_fields": sorted(set(poi) | set(ldata) | set(poa)),
        }
    except (AttributeError, ValueError):
        return {}


def _extract_aadhaar_address(text: str) -> str | None:
    """Extract the holder address without UIDAI footer/header boilerplate."""
    match = re.search(
        r"\baddress\s*:\s*(.{8,360}?\b[1-8]\d{5}\b)",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _clean_aadhaar_address_value(match.group(1))
    return _clean_aadhaar_address_value(_lines_after_label(text, "address", max_lines=4))


def _clean_aadhaar_address_value(value: Any) -> str | None:
    """Remove issuing-authority text accidentally interleaved after Address:."""
    if value in (None, ""):
        return None
    cleaned = str(value)
    authority_patterns = (
        r"भारतीय\s+विशिष्ट\s+पहचान\s+प्राधिकरण",
        r"\bUnique\s+Identification\s+Authority\s+of\s+India\b",
        r"\b(?:Government|Govt\.?)\s+of\s+India\b",
    )
    for pattern in authority_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:^|\s)(?:address|पता)\s*:\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")
    return cleaned or None


def _extract_voter_id(text: str) -> dict[str, Any]:
    """Extract fields from a Voter ID / EPIC card."""
    t = text.lower()

    # Voter ID number: 3 uppercase letters + 7 digits  e.g. ABC1234567
    vid_match = re.search(r"\b([A-Z]{3}[0-9]{7})\b", text)

    # DOB
    dob_raw = _extract_date_near(t, "dob", "date of birth")

    return {
        "applicant_name": _voter_cardholder_name(text),
        "voter_id_number": vid_match.group(1) if vid_match else None,
        "address": _lines_after_label(text, "address", max_lines=3),
        "dob": dob_raw,
    }


def _voter_cardholder_name(text: str) -> str | None:
    """Prefer the Latin cardholder value in bilingual EPIC label/value blocks."""
    lines = text.splitlines()
    label_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(r"elector'?s\s+name|निर्वाचक\s+का\s+नाम", line, re.IGNORECASE)
        ),
        None,
    )
    if label_index is None:
        return _line_after_label(text, "name")

    valid_candidates: list[str] = []
    for line in lines[label_index + 1 : label_index + 14]:
        candidate = _clean_name_like_value(line)
        if not candidate:
            continue
        valid_candidates.append(candidate)
        if re.search(r"[A-Za-z]", candidate):
            return candidate
    return valid_candidates[0] if valid_candidates else None


def _extract_driving_license(text: str) -> dict[str, Any]:
    """Extract fields from a Driving License.

    Also flags expired licences via 'is_expired' key.
    """

    # DL number: 2 uppercase letters + 2 digits + optional space + 11 digits
    # (\b does not work between \d and \D reliably, so we anchor with lookahead/lookbehind)
    dl_match = re.search(r"(?<![A-Z0-9])([A-Z]{2}\d{2}\s?\d{11})(?![A-Z0-9])", text)

    # Read dates only from their own labels.  A proximity window is unsafe on
    # DLs because Date of Issue, DOB and Valid Till are commonly printed beside
    # each other and flattened OCR loses the original columns.
    validity_date = _extract_date_after_label(
        text, "valid till", "valid upto", "valid up to", "validity date", "validity"
    )
    is_expired = _is_past_date(validity_date)

    dob_raw = _extract_date_after_label(
        text, "date of birth", "dob", "d.o.b"
    ) or _extract_date_below_label(
        text,
        "date of birth",
        "dob",
        "d.o.b",
        max_lines=6,
        stop_labels=(
            "name",
            "address",
            "permanent address",
            "date of issue",
            "validity",
            "valid till",
            "licence no",
            "license no",
            "dl no",
        ),
    )
    date_of_issue = _extract_date_after_label(
        text, "date of issue", "issue date", "issued on", "date issued"
    )

    return {
        "applicant_name": _line_after_label(text, "name"),
        "dl_number": dl_match.group(1).replace(" ", "") if dl_match else None,
        "dob": dob_raw,
        "date_of_issue": date_of_issue,
        "validity_date": validity_date,
        "is_expired": is_expired,
        "address": _lines_after_label(text, "address", max_lines=3),
    }
