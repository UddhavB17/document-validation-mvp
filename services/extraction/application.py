"""Application-form extraction and layout-based address parsing."""

from __future__ import annotations

import re
from typing import Any

from services.extraction._shared import (
    _ADDRESS_FORM_NOISE_PATTERNS,
    _PAGE_COUNTER_RE,
    _address_value_is_contaminated,
    _clean_name_like_value,
    _extract_date_near,
    _line_after_label,
    _lines_after_label_until_stop,
    _looks_like_postal_address,
    _normalize_amount,
    _numeric_line_after_label,
    _ocr_normalized_pin,
    _parse_date,
    _raw_value_after_label,
)
from services.identifiers import plausible_aadhaar_digits
from services.person_names import canonicalize_person_name
from services.validation_gates import has_labeled_aadhaar_value

_APPLICATION_LAYOUT_ADDRESS_LABELS = {
    "current_address": (
        "current res address",
        "current resi address",
        "current residential address",
    ),
    "permanent_address": (
        "permanent res address",
        "permanent resi address",
        "permanent residential address",
    ),
    "communication_address": ("communication address",),
}

_LAYOUT_ADDRESS_REJECT_PREFIXES = (
    "aadhaar no",
    "business constitution",
    "city",
    "driving license",
    "driving licence",
    "email",
    "e mail",
    "mobile",
    "name",
    "owned rented",
    "professionally qualified",
    "telephone",
    "whatsapp",
    "years at",
    "years in",
)


def _extract_application_coapplicant_records(text: str) -> list[dict[str, Any]]:
    """Extract co-applicant rows whose values are stacked below table headers."""
    if "CO-APPLICANT DETAILS" not in text.upper():
        return []
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*(\d{1,2}-[A-Za-z]+-(?:\s*\n\s*)?\d{4})\s*\n"
        r"\s*([A-Za-z][A-Za-z ]{1,60}?)\s*\n"
        r"\s*([6-9]\d{9})\s*\n"
        r"\s*(FATHER|MOTHER|WIFE|HUSBAND|SON|DAUGHTER)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        records.append(
            {
                "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
                "date_of_birth": _parse_date(re.sub(r"\s+", "", match.group(2))),
                "father_name": re.sub(r"\s+", " ", match.group(3)).strip(),
                "phone_number": match.group(4),
                "relationship": match.group(5).title(),
            }
        )
    return records


def _extract_application_form(text: str) -> dict[str, Any]:
    """Extract identity fields commonly repeated in a loan application form."""
    is_coapplicant_kyc_table = "CO-APPLICANT KYC DETAILS" in text.upper()
    pan_match = (
        None
        if is_coapplicant_kyc_table
        else re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text.upper())
    )
    aadhaar_match = next(
        (
            match
            for match in re.finditer(r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)", text)
            if has_labeled_aadhaar_value(text, match.group(1))
        ),
        None,
    )
    # Do not attribute co-applicant or corporate-header phones to the primary.
    phone_match = None
    if "CO-APPLICANT DETAILS" not in text.upper():
        phone_match = re.search(
            r"MOBILE\s+NUMBER[^\n\r]*\n(?:[^A-Za-z0-9\n\r]*\n){0,3}\s*([6-9]\d{9})(?!\d)",
            text,
            re.IGNORECASE,
        )
    pin_match = re.search(r"(?:pin\s*code|pincode)\s*[:\-–]?\s*(\d{6})", text, re.IGNORECASE)
    labeled_names = [
        _clean_name_like_value(value)
        for value in re.findall(
            r"(?:applicant|co[\s-]*applicant|borrower|guarantor)\s*(?:name)?\s*[:\-–]\s*([^\n\r]{3,70})",
            text,
            re.IGNORECASE,
        )
    ]
    language_match = re.search(
        r"(?:second|alternate|vernacular)\s+language\s*[:\-–]?\s*([A-Za-z\u0600-\u06FF\u0900-\u0D7F ]{3,30})",
        text,
        re.IGNORECASE,
    )
    applicant_section = (
        text[text.upper().find("APPLICANT DETAILS") :]
        if "APPLICANT DETAILS" in text.upper()
        else text
    )
    name_match = re.search(
        r"(?:^|\n)\s*NAME\s*\n(?:[^A-Za-z0-9\n]*\n){0,3}\s*([A-Za-z][A-Za-z .'-]{2,70})\s*\n"
        r"\s*DATE\s+OF\s+BIRTH",
        applicant_section,
        re.IGNORECASE,
    )
    current_address = _extract_application_address_block(
        text, "COMMUNICATION ADDRESS", ("PERMANENT ADDRESS", "OFFICE ADDRESS")
    ) or _extract_residential_address_alias(
        text,
        "current address",
        "current resi. address",
        "current resi address",
        "current residential address",
    )
    permanent_address = _extract_application_address_block(
        text, "PERMANENT ADDRESS", ("OFFICE ADDRESS", "APPLICANT EMPLOYEMENT")
    ) or _extract_residential_address_alias(
        text,
        "permanent address",
        "permanent resi. address",
        "permanent resi address",
        "permanent residential address",
    )
    communication_address = _extract_application_address_block(
        text, "COMMUNICATION ADDRESS", ("PERMANENT ADDRESS", "OFFICE ADDRESS")
    ) or _extract_residential_address_alias(text, "communication address")
    person_records = [
        *_extract_application_coapplicant_records(text),
        *_extract_application_kyc_records(text),
    ]
    coapplicant_address_record = _extract_coapplicant_address_record(
        text,
        current_address=current_address,
        permanent_address=permanent_address,
    )
    if coapplicant_address_record:
        address_name = str(coapplicant_address_record.get("applicant_name") or "").casefold()
        matching_record = next(
            (
                record
                for record in person_records
                if isinstance(record, dict)
                and str(record.get("applicant_name") or "").casefold() == address_name
            ),
            None,
        )
        if matching_record is None:
            person_records.append(coapplicant_address_record)
        else:
            for field_name, value in coapplicant_address_record.items():
                if value not in (None, "") and matching_record.get(field_name) in (None, ""):
                    matching_record[field_name] = value
        # Only clear container-level addresses if they were actually assigned to the co-applicant
        if coapplicant_address_record.get("current_address") == current_address:
            current_address = None
        if coapplicant_address_record.get("permanent_address") == permanent_address:
            permanent_address = None
        if coapplicant_address_record.get("communication_address") == communication_address:
            communication_address = None
    return {
        "applicant_name": (
            name_match.group(1).strip()
            if name_match
            else _line_after_label(text, "applicant name", "borrower name", "name of applicant")
        ),
        "pan_number": pan_match.group(1) if pan_match else None,
        "aadhaar_number": plausible_aadhaar_digits(aadhaar_match.group(1))
        if aadhaar_match
        else None,
        "date_of_birth": _extract_date_near(text.lower(), "date of birth", "dob"),
        "loan_amount": _normalize_amount(_numeric_line_after_label(text, "loan amount")),
        "phone_number": phone_match.group(1) if phone_match else None,
        "pin_code": pin_match.group(1) if pin_match else None,
        "current_address": current_address,
        "permanent_address": permanent_address,
        "communication_address": communication_address,
        "applicant_names": [name for name in labeled_names if name],
        "person_records": person_records,
        "second_language": language_match.group(1).strip() if language_match else None,
    }


def _extract_application_layout_addresses(
    structured_content: dict[str, Any] | None,
) -> dict[str, str]:
    """Extract application-form address rows from OCR bounding boxes.

    Google Vision's flat text can interleave two form columns.  Region geometry
    keeps values on the same visual row as their address label and prevents a
    distant PAN, education, or contact field from entering the address.
    """
    if not isinstance(structured_content, dict):
        return {}
    raw_regions = structured_content.get("layout_regions")
    if not isinstance(raw_regions, list):
        return {}

    regions: list[dict[str, Any]] = []
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            continue
        text = re.sub(r"\s+", " ", str(raw_region.get("text") or "")).strip()
        geometry = _layout_region_geometry(raw_region)
        if not text or geometry is None:
            continue
        try:
            confidence = float(raw_region.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        x0, y0, x1, y1 = geometry
        regions.append(
            {
                "text": text,
                "normalized": _normalized_layout_text(text),
                "confidence": confidence,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
            }
        )

    extracted: dict[str, str] = {}
    for field_name, labels in _APPLICATION_LAYOUT_ADDRESS_LABELS.items():
        anchors = [
            region for region in regions if any(label in region["normalized"] for label in labels)
        ]
        for anchor in anchors:
            value = _layout_address_value(regions, anchor)
            if value:
                extracted[field_name] = value
                break
    return extracted


def _layout_region_geometry(region: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bounding_box = region.get("bounding_box") or region.get("boundingBox") or {}
    vertices = bounding_box.get("vertices") if isinstance(bounding_box, dict) else None
    if not isinstance(vertices, list) or not vertices:
        return None
    try:
        xs = [float(vertex.get("x") or 0.0) for vertex in vertices if isinstance(vertex, dict)]
        ys = [float(vertex.get("y") or 0.0) for vertex in vertices if isinstance(vertex, dict)]
    except (TypeError, ValueError):
        return None
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _normalized_layout_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _layout_address_value(regions: list[dict[str, Any]], anchor: dict[str, Any]) -> str | None:
    label_right = float(anchor["x1"])
    label_top = float(anchor["y0"])
    label_bottom = float(anchor["y1"])

    primary: list[dict[str, Any]] = []
    continuation: list[dict[str, Any]] = []
    pin_regions: list[dict[str, Any]] = []
    for region in regions:
        if region is anchor or float(region["x0"]) <= label_right + 4:
            continue
        if not _is_layout_address_piece(region["text"], region["normalized"]):
            continue
        y0 = float(region["y0"])
        y1 = float(region["y1"])
        if y0 <= label_bottom + 4 and y1 >= label_top - 8:
            primary.append(region)
            continue
        if label_bottom < y0 <= label_bottom + 32:
            continuation.append(region)
            continue
        if label_top - 4 <= y0 <= label_bottom + 55 and re.fullmatch(
            r"(?:pin\s*)?[1-8]\d{5}(?:\s+tele)?",
            region["normalized"],
        ):
            pin_regions.append(region)

    continuation.sort(key=lambda region: (float(region["y0"]), float(region["x0"])))
    pin_regions.sort(key=lambda region: (float(region["y0"]), float(region["x0"])))

    selected: list[dict[str, Any]] = [*primary, *continuation]
    if not any(re.search(r"\b[1-8]\d{5}\b", str(region["text"])) for region in selected):
        selected.extend(pin_regions[:1])
    if not selected:
        return None

    pieces: list[str] = []
    for region in selected:
        piece = re.sub(r"^PIN\s*", "", str(region["text"]), flags=re.IGNORECASE)
        piece = re.sub(r"\s+Tele(?:phone)?\b.*$", "", piece, flags=re.IGNORECASE)
        piece = piece.strip(" ,.;:-")
        if piece and piece not in pieces:
            pieces.append(piece)
    value = " ".join(pieces)
    if not _looks_like_postal_address(value) or _address_value_is_contaminated(value):
        return None

    confidences = [float(region["confidence"]) for region in selected if region["confidence"]]
    if confidences and sum(confidences) / len(confidences) < 0.60:
        return None
    core_confidences = [
        float(region["confidence"])
        for region in selected
        if region["confidence"]
        and not re.fullmatch(r"(?:pin\s*)?[1-8]\d{5}(?:\s+tele)?", region["normalized"])
    ]
    if core_confidences and min(core_confidences) < 0.60:
        return None
    return value


def _is_layout_address_piece(text: str, normalized: str) -> bool:
    if not normalized or any(
        normalized.startswith(prefix) for prefix in _LAYOUT_ADDRESS_REJECT_PREFIXES
    ):
        return False
    if any(re.search(pattern, normalized) for pattern in _ADDRESS_FORM_NOISE_PATTERNS):
        return False
    if normalized in {
        "address",
        "current",
        "permanent",
        "office",
        "others",
        "pin",
        "residence",
        "yes",
        "no",
    }:
        return False
    if len(text) > 120 or not re.search(r"[A-Za-z0-9]", text):
        return False
    return True


def _extract_application_address_block(
    text: str,
    heading: str,
    stop_headings: tuple[str, ...],
) -> str | None:
    """Extract address-table values split across bilingual application rows."""
    upper = str(text or "").upper()
    start = upper.find(heading.upper())
    if start < 0:
        return None
    section_boundaries = (
        *stop_headings,
        "GUARANTOR DETAILS",
        "GUARANTOR ADDRESS",
        "GUARANTOR EMPLOYEMENT/BUSINESS DETAILS",
        "GUARANTOR EMPLOYMENT/BUSINESS DETAILS",
        "GUARANTOR EMPLOYMENT DETAILS",
        "GUARANTOR BUSINESS DETAILS",
        "CO-APPLICANT DETAILS",
        "CO-APPLICANT KYC DETAILS",
        "APPLICANT DETAILS",
    )
    ends = [upper.find(stop.upper(), start + len(heading)) for stop in section_boundaries]
    end = min((value for value in ends if value >= 0), default=len(text))
    lines = [line.strip() for line in text[start:end].splitlines() if line.strip()]
    label_names = {
        "address",
        "type",
        "address type",
        "sub type",
        "address sub type",
        "years at current address",
        "landmark",
        "tehsil",
        "district",
        "pincode",
        "pin code",
        "state",
        "country",
    }

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z]+", " ", value.casefold()).strip()

    def value_after(
        label: str,
        *,
        allow_status: bool = False,
        prefer_address: bool = False,
    ) -> str | None:
        for index, line in enumerate(lines):
            if normalized(line) != label:
                continue
            fallback: str | None = None
            candidates = lines[index + 1 : index + 10]
            for candidate_index, candidate in enumerate(candidates):
                key = normalized(candidate)
                if key in label_names:
                    break
                if not re.search(r"[A-Za-z0-9]", candidate):
                    continue
                if not allow_status and key in {"current", "permanent", "office"}:
                    continue
                cleaned = candidate.strip(" ,.;")
                if _PAGE_COUNTER_RE.search(cleaned):
                    # A page counter marks the end of this page's table. Never
                    # walk into the digital-signature footer looking for a value.
                    break
                if not prefer_address:
                    return cleaned
                if _looks_like_postal_address(cleaned):
                    pieces = [cleaned]
                    for continuation in candidates[candidate_index + 1 : candidate_index + 4]:
                        continuation_key = normalized(continuation)
                        if continuation_key in label_names:
                            break
                        continuation_text = continuation.strip(" ,.;")
                        if _looks_like_postal_address(continuation_text) or re.search(
                            r"\b[1-8]\d{5}\b", continuation_text
                        ):
                            pieces.append(continuation_text)
                    return " ".join(dict.fromkeys(pieces))
                # OCR often stacks NAME and ADDRESS labels first, followed by
                # the person's name and then the actual postal address.  Keep a
                # plausible non-name fallback, but never return the name itself
                # as the address.
                if not canonicalize_person_name(cleaned).valid and fallback is None:
                    fallback = cleaned
            if fallback:
                return fallback
        return None

    base = value_after("address", prefer_address=True)
    pin = value_after("pincode") or value_after("pin code")
    parts = [
        base,
        value_after("landmark"),
        value_after("tehsil"),
        value_after("district"),
        value_after("state"),
        value_after("country"),
        pin,
    ]
    result = ", ".join(dict.fromkeys(value for value in parts if value))
    return result or None


def _extract_residential_address_alias(text: str, *labels: str) -> str | None:
    """Extract inline/stacked residential-address labels used in Indian forms."""
    for label in labels:
        inline = _raw_value_after_label(text, label)
        if inline and _looks_like_postal_address(inline):
            return inline
        layout_block = _extract_jumbled_residential_block(text, label)
        if layout_block:
            return layout_block
        stacked = _lines_after_label_until_stop(
            text,
            label,
            stop_labels={
                "current address",
                "current resi. address",
                "permanent address",
                "permanent resi. address",
                "office address",
                "mobile number",
                "date of birth",
                "pan",
                "aadhaar",
            },
            max_lines=4,
        )
        if stacked and _looks_like_postal_address(stacked):
            return stacked
    return None


def _extract_jumbled_residential_block(text: str, label: str) -> str | None:
    """Recover form addresses whose visual columns OCR into interleaved lines."""
    lines = [re.sub(r"\s+", " ", line).strip(" ,.;") for line in str(text or "").splitlines()]
    normalized_label = re.sub(r"[^a-z]+", " ", label.casefold()).strip()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.sub(r"[^a-z]+", " ", line.casefold()).strip() == normalized_label
        ),
        None,
    )
    if start is None:
        return None

    stop_prefixes = (
        "permanent resi",
        "current resi",
        "permanent residential",
        "current residential",
        "occupation details",
        "preferred mailing",
    )
    ignored_exact = {
        "city",
        "telephone",
        "email id",
        "e mail id",
        "residence",
        "post graduate",
        "graduate",
        "non graduate",
        "pin",
        "fax",
        "whatsapp available",
        "yes",
        "no",
    }
    ignored_prefixes = (
        "mobile ",
        "owned rented",
        "years at ",
        "years in ",
        "preferred contact",
        "current office address",
        "additional office address",
    )
    pieces: list[str] = []
    for index, line in enumerate(lines[start + 1 : start + 23], start=start + 1):
        if not line:
            continue
        normalized = re.sub(r"[^a-z]+", " ", line.casefold()).strip()
        if index > start + 1 and any(normalized.startswith(prefix) for prefix in stop_prefixes):
            break
        pin_match = re.search(r"\bPIN\s*([0-9A-Z]{6})\b", line, re.IGNORECASE)
        if pin_match:
            pin = _ocr_normalized_pin(pin_match.group(1))
            if pin:
                pieces.append(pin)
            continue
        if normalized in ignored_exact or any(
            normalized.startswith(prefix) for prefix in ignored_prefixes
        ):
            continue
        cleaned = re.sub(r"^if\s+different\s+from\s+above\)?\s*", "", line, flags=re.IGNORECASE)
        if cleaned and re.search(r"[A-Za-z0-9]", cleaned):
            pieces.append(cleaned)

    # Column-order OCR may print the labelled PIN just after an intervening
    # office-address heading.  Use it only as part of this address value.
    nearby = " ".join(lines[start + 1 : start + 18])
    for match in re.finditer(r"\bPIN\s*([0-9A-Z]{6})\b", nearby, re.IGNORECASE):
        pin = _ocr_normalized_pin(match.group(1))
        if pin and pin not in pieces:
            pieces.append(pin)
    result = " ".join(dict.fromkeys(pieces)).strip()
    return result if _looks_like_postal_address(result) else None


def _extract_coapplicant_address_record(
    text: str,
    *,
    current_address: str | None,
    permanent_address: str | None,
) -> dict[str, Any] | None:
    section_start = re.search(r"\bCO[\s-]*APPLICANT\s+ADDRESS\b", text, re.IGNORECASE)
    if not section_start:
        return None
    # Search only inside the co-applicant address section. Whole-document
    # extraction previously walked back to the lender's corporate header and
    # manufactured a company-as-person record.
    scoped_text = text[section_start.start() :]
    section_end = re.search(
        r"(?:^|\n)\s*(?:GUARANTOR\s+(?:DETAILS|ADDRESS)|"
        r"APPLICANT\s+DETAILS|DECLARATION|BANK\s+ACCOUNT\s+DETAILS)\b",
        scoped_text[len(section_start.group(0)) :],
        re.IGNORECASE,
    )
    if section_end:
        scoped_text = scoped_text[: len(section_start.group(0)) + section_end.start()]
    excluded = {
        "co applicant address",
        "communication address",
        "permanent address",
        "office address",
        "name",
        "address",
        "current",
    }
    person_name = None
    for line in scoped_text.splitlines():
        candidate_text = re.sub(r"\s+", " ", line).strip(" ,.;")
        normalized = re.sub(r"[^a-z]+", " ", candidate_text.casefold()).strip()
        if not candidate_text or normalized in excluded:
            continue
        candidate = canonicalize_person_name(candidate_text)
        if candidate.valid and len(re.findall(r"[A-Za-z]+", str(candidate.value or ""))) >= 2:
            person_name = candidate.value
            break
    if not person_name:
        return None
    co_current = (
        _extract_application_address_block(
            scoped_text, "COMMUNICATION ADDRESS", ("PERMANENT ADDRESS", "OFFICE ADDRESS")
        )
        or _extract_residential_address_alias(
            scoped_text, "current address", "communication address"
        )
        or current_address
    )
    co_permanent = (
        _extract_application_address_block(scoped_text, "PERMANENT ADDRESS", ("OFFICE ADDRESS",))
        or _extract_residential_address_alias(scoped_text, "permanent address")
        or permanent_address
    )
    return {
        "applicant_name": person_name,
        "current_address": co_current,
        "communication_address": co_current,
        "permanent_address": co_permanent,
    }


def _extract_application_kyc_records(text: str) -> list[dict[str, Any]]:
    """Keep each application-form KYC row attached to its named person."""
    if "KYC DETAILS" not in text.upper():
        return []
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*([A-Za-z][A-Za-z ]{2,60}?)\s*\n"
        r"\s*([X*]{8}\d{4})\s*\n"
        r"\s*([A-Z]{5}\d{4}[A-Z])\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        records.append(
            {
                "applicant_name": re.sub(r"\s+", " ", match.group(1)).strip(),
                "aadhaar_last4": match.group(2)[-4:],
                "pan_number": match.group(3).upper(),
            }
        )
    return records
