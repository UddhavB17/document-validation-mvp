"""Person-ownership submodule."""

from __future__ import annotations

import re
from typing import Any

from services.identifiers import plausible_aadhaar_digits
from services.ownership._helpers import _digits, _relation_name_matches, first_value
from services.ownership.constants import _MASKED_AADHAAR_LAST4_RE, FIELD_ALIASES
from services.person_names import is_person_name_candidate
from services.validation_gates import field_reliable_for_validation, has_labeled_aadhaar_value


def _source_override_evidence(
    pages: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Collect exact identifiers permitted to override a source-folder role."""
    evidence: dict[str, set[str]] = {person_id: set() for person_id in people}
    for page in pages:
        if not isinstance(page, dict):
            continue
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            fields = page if any(key in page for key in ("pan_number", "aadhaar_number")) else {}
        candidates = [fields]
        mapped = fields.get("_mapped_extraction")
        if isinstance(mapped, dict):
            candidates.append(mapped)
        generic = fields.get("_generic_evidence")
        ocr_text = str(page.get("ocr_text") or fields.get("ocr_text") or "")
        account_identity_document = str(page.get("document_type") or "").strip().casefold() in {
            "bank statement",
            "passbook",
            "cheque",
        }

        pan_values: list[Any] = []
        aadhaar_values: list[Any] = []
        account_values: list[Any] = []
        for candidate in candidates:
            pan_values.extend(
                candidate.get(alias)
                for alias in FIELD_ALIASES["pan_number"]
                if candidate.get(alias) not in (None, "", [], {})
            )
            aadhaar_values.extend(
                candidate.get(alias)
                for alias in FIELD_ALIASES["aadhaar_number"]
                if candidate.get(alias) not in (None, "", [], {})
            )
            account_values.extend(
                candidate.get(alias)
                for alias in FIELD_ALIASES["account_number"]
                if candidate.get(alias) not in (None, "", [], {})
            )
        if isinstance(generic, dict):
            pan_values.extend(generic.get("pan_numbers") or [])
            aadhaar_values.extend(generic.get("aadhaar_numbers") or [])
        pan_values.extend(
            match.group(0) for match in re.finditer(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", ocr_text.upper())
        )
        aadhaar_values.extend(
            match.group(1)
            for match in re.finditer(
                r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)",
                ocr_text,
            )
        )
        account_values.extend(
            _explicit_bank_account_observations(
                ocr_text,
                str(page.get("document_type") or ""),
            )
        )

        valid_pans = {
            re.sub(r"\s+", "", str(value)).upper()
            for value in pan_values
            if re.fullmatch(
                r"[A-Z]{5}\d{4}[A-Z]",
                re.sub(r"\s+", "", str(value)).upper(),
            )
            and field_reliable_for_validation(
                page,
                "pan_number",
                value,
                expected_document_type=str(page.get("document_type") or "Unknown"),
            )
        }
        valid_aadhaars = {
            digits
            for value in aadhaar_values
            if (digits := plausible_aadhaar_digits(value))
            and has_labeled_aadhaar_value(ocr_text, value)
            and field_reliable_for_validation(
                page,
                "aadhaar_number",
                value,
                expected_document_type=str(page.get("document_type") or "Unknown"),
            )
        }
        valid_accounts = (
            {
                digits
                for value in account_values
                if 8 <= len(digits := _digits(str(value))) <= 20
                and field_reliable_for_validation(
                    page,
                    "account_number",
                    value,
                    expected_document_type=str(page.get("document_type") or "Unknown"),
                )
            }
            if account_identity_document
            else set()
        )

        trusted_account_owners: dict[str, list[str]] = {}
        for candidate_id, trusted in people.items():
            trusted_digits = _digits(
                str(first_value(trusted, FIELD_ALIASES["account_number"]) or "")
            )
            if len(trusted_digits) >= 8:
                trusted_account_owners.setdefault(trusted_digits, []).append(candidate_id)

        for person_id, trusted in people.items():
            expected_pan = re.sub(
                r"\s+", "", str(first_value(trusted, FIELD_ALIASES["pan_number"]) or "")
            ).upper()
            if expected_pan and expected_pan in valid_pans:
                evidence[person_id].add("full_pan_number")
            expected_aadhaar = plausible_aadhaar_digits(
                first_value(trusted, FIELD_ALIASES["aadhaar_number"])
            )
            if expected_aadhaar and expected_aadhaar in valid_aadhaars:
                evidence[person_id].add("full_labeled_aadhaar_number")
            expected_account = _digits(
                str(first_value(trusted, FIELD_ALIASES["account_number"]) or "")
            )
            if expected_account in valid_accounts and trusted_account_owners.get(
                expected_account
            ) == [person_id]:
                evidence[person_id].add("full_account_number")
    return {person_id: sorted(values) for person_id, values in evidence.items()}


def relationship_observations(
    pages: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Extract W/O, S/O, D/O and C/O relation text without naming the owner."""
    observations: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        fields = page.get("extracted_fields") if isinstance(page, dict) else None
        fields = fields if isinstance(fields, dict) else {}
        qualifier = str(fields.get("relationship_qualifier") or "").upper().replace(" ", "")
        related = str(fields.get("related_person_name") or "").strip()
        if qualifier in {"W/O", "S/O", "D/O", "C/O"} and related:
            key = (qualifier, related.casefold())
            if key not in seen:
                seen.add(key)
                observations.append((qualifier, related))

        sources = [
            fields.get("address"),
            fields.get("current_address"),
            fields.get("permanent_address"),
            fields.get("communication_address"),
            page.get("ocr_text") if isinstance(page, dict) else None,
        ]
        for source in sources:
            for match in re.finditer(
                r"\b([WSDC])\s*/\s*O\b\s*[:\-]?\s*([^\n\r,;]{3,90})",
                str(source or ""),
                re.IGNORECASE,
            ):
                item = (f"{match.group(1).upper()}/O", match.group(2).strip())
                key = (item[0], item[1].casefold())
                if key in seen:
                    continue
                seen.add(key)
                observations.append(item)
    return observations


def _relationship_owner_candidates(
    qualifier: str,
    related_text: str,
    people: dict[str, dict[str, Any]],
) -> list[tuple[str, str | None]]:
    referenced_id = next(
        (
            person_id
            for person_id, person in people.items()
            if _relation_name_matches(related_text, person.get("applicant_name"))
        ),
        None,
    )
    candidates: list[tuple[str, str | None]] = []
    relation_fields = {
        "W/O": ("husband_name", "spouse_name", "related_person_name"),
        "S/O": ("father_name", "parent_name", "related_person_name"),
        "D/O": ("father_name", "parent_name", "related_person_name"),
        "C/O": ("related_person_name", "father_name", "husband_name", "spouse_name"),
    }.get(qualifier, ("related_person_name",))

    for person_id, person in people.items():
        trusted_qualifier = str(person.get("relationship_qualifier") or "").upper().replace(" ", "")
        if trusted_qualifier and trusted_qualifier != qualifier:
            continue
        relation_values = [person.get(field) for field in relation_fields]
        relation_values.extend(
            _relationship_tails(
                (
                    person.get(field)
                    for field in (
                        "address",
                        "current_address",
                        "permanent_address",
                        "communication_address",
                    )
                ),
                qualifier,
            )
        )
        if any(_relation_name_matches(related_text, value) for value in relation_values if value):
            candidates.append((person_id, referenced_id))
    return candidates


def _relationship_tails(values: Any, qualifier: str) -> list[str]:
    tails: list[str] = []
    letter = qualifier[0]
    for value in values:
        match = re.search(
            rf"\b{re.escape(letter)}\s*/\s*O\b\s*[:\-]?\s*([^\n\r,;]{{3,90}})",
            str(value or ""),
            re.IGNORECASE,
        )
        if match:
            tails.append(match.group(1).strip())
    return tails


def identity_observations(pages: list[dict[str, Any]]) -> dict[str, list[Any]]:
    observations: dict[str, list[Any]] = {field: [] for field in FIELD_ALIASES}
    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            # Allow passing a bare fields dict as a synthetic page.
            if isinstance(page, dict) and any(
                key in page for key in ("applicant_name", "pan_number", "dob")
            ):
                fields = page
            else:
                continue
        ocr_text = str(page.get("ocr_text") or fields.get("ocr_text") or "")
        candidates = [fields]
        mapped = fields.get("_mapped_extraction")
        if isinstance(mapped, dict):
            candidates.append(mapped)
        for candidate in candidates:
            for canonical, aliases in FIELD_ALIASES.items():
                for alias in aliases:
                    value = candidate.get(alias)
                    if value in (None, "", [], {}):
                        continue
                    if canonical == "applicant_name" and not is_person_name_candidate(value):
                        continue
                    if not field_reliable_for_validation(
                        page,
                        canonical,
                        value,
                        expected_document_type=str(page.get("document_type") or "Unknown"),
                    ):
                        continue
                    observations[canonical].append(value)
        generic = fields.get("_generic_evidence")
        if isinstance(generic, dict):
            for value in generic.get("pan_numbers") or []:
                observations["pan_number"].append(value)
            for value in generic.get("aadhaar_numbers") or []:
                if plausible_aadhaar_digits(value) and has_labeled_aadhaar_value(ocr_text, value):
                    observations["aadhaar_number"].append(value)
            for value in generic.get("phone_numbers") or []:
                observations["phone_number"].append(value)

        # Fall back to raw OCR for exact identifiers. Banking names are limited
        # to holder/header candidates; on all documents, W/O or S/O names are
        # relations and must not be treated as the cardholder.
        if ocr_text:
            observations["applicant_name"].extend(
                _explicit_name_observations(
                    ocr_text,
                    str(page.get("document_type") or ""),
                )
            )
            observations["account_number"].extend(
                _explicit_bank_account_observations(
                    ocr_text,
                    str(page.get("document_type") or ""),
                )
            )
            for match in re.finditer(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", ocr_text.upper()):
                observations["pan_number"].append(match.group(0))
            for match in re.finditer(r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)", ocr_text):
                if plausible_aadhaar_digits(match.group(1)) and has_labeled_aadhaar_value(
                    ocr_text, match.group(1)
                ):
                    observations["aadhaar_number"].append(match.group(1))
            for match in _MASKED_AADHAAR_LAST4_RE.finditer(ocr_text):
                observations["aadhaar_number"].append(match.group(1))
            for match in re.finditer(r"\b[6-9]\d{9}\b", ocr_text):
                observations["phone_number"].append(match.group(0))
    return observations


def _explicit_name_observations(text: str, document_type: str) -> list[str]:
    """Return subject-name evidence while excluding relationship-only names."""
    type_key = str(document_type or "").strip().casefold()
    if type_key == "cheque":
        return _cheque_signature_name_observations(text)
    if type_key in {"bank statement", "passbook"}:
        return _banking_holder_name_observations(text)

    candidates: list[str] = []
    patterns = (
        r"(?:^|\n)\s*(?:applicant|consumer|customer|card\s+holder|account\s+holder)\s+name\s*[:\-–]?\s*(?:\n\s*)?([^\n\r]{3,70})",
        r"(?:^|\n)\s*name\s*:\s*([^\n\r]{3,70})",
    )
    if type_key in {"cibil report", "crif report"}:
        patterns += (r"(?:^|\n)\s*for\s+([^\n\r]{3,70})",)
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = match.group(1).strip(" :\t")
            if re.match(
                r"^(?:[wsdcf]\s*/?\s*o|wife\s+of|son\s+of|daughter\s+of|care\s+of)\b",
                candidate,
                re.I,
            ):
                continue
            candidates.append(candidate)
    return candidates


def _banking_holder_name_observations(text: str) -> list[str]:
    """Return holder candidates from a banking header, never relation rows.

    Whole-page name matching is unsafe because transaction descriptions,
    nominees and ``S/O``/``W/O`` relatives can all contain trusted names.  This
    parser is layout-tolerant but deliberately bounded to subject-bearing header
    patterns and short standalone name rows before transaction data begins.
    """
    raw_header = re.split(
        r"(?:^|\n)\s*(?:transactions?|transaction\s+details|date\s+particulars|"
        r"opening\s+balance)\s*(?:\n|$)",
        str(text or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    lines = [re.sub(r"\s+", " ", line).strip(" ,.;") for line in raw_header.splitlines()]
    candidates: list[str] = []

    label_pattern = re.compile(
        r"^(?:welcome|account\s+holder(?:\s+name)?|customer(?:'s)?\s+name|"
        r"name\s+of\s+(?:the\s+)?(?:account\s+holder|customer)|name)"
        r"\s*[:\-–]?\s*(.*)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines[:50]):
        match = label_pattern.match(line)
        if not match:
            continue
        for candidate in [match.group(1), *lines[index + 1 : index + 4]]:
            if _banking_name_candidate(candidate):
                candidates.append(candidate)
                break

    for match in re.finditer(
        r"\b(?:account\s+holder(?:\s+name)?|customer(?:'s)?\s+name|"
        r"name\s+of\s+(?:the\s+)?(?:account\s+holder|customer))"
        r"\s*[:\-–]?\s+([^\n\r]{3,100})",
        raw_header,
        re.IGNORECASE,
    ):
        candidate = match.group(1).strip(" ,.;")
        # Inline passbook headers sometimes append a locality after the holder
        # ("Account Holder PEERU LAL SEMLI BAKHTA").  Preserve the short tail
        # as a bounded haystack; matching still requires a trusted full name.
        if (
            any(character.isalpha() for character in candidate)
            and not re.search(r"\d", candidate)
            and len(candidate.split()) <= 12
        ):
            candidates.append(candidate)

    for match in re.finditer(
        r"\bof\s+(?:mr|mrs|ms|miss|shri|smt|sri|dr)\.?\s+"
        r"([A-Za-z][A-Za-z .'-]{2,60}?)\s+(?=at\b|a/?c\b|account\b|$)",
        raw_header,
        re.IGNORECASE,
    ):
        if _banking_name_candidate(match.group(1)):
            candidates.append(match.group(1))

    for line in lines[:35]:
        if _banking_name_candidate(line):
            candidates.append(line)
    return list(dict.fromkeys(candidates))


def _banking_name_candidate(value: Any) -> bool:
    candidate = str(value or "").strip()
    if not candidate or re.match(
        r"^(?:[wsdcf]\s*/?\s*o|wife\s+of|son\s+of|daughter\s+of|"
        r"husband\s+of|father\s+of|care\s+of)\b",
        candidate,
        re.IGNORECASE,
    ):
        return False
    if not is_person_name_candidate(candidate):
        return False
    tokens = re.findall(r"[A-Za-z]+", candidate)
    return 1 <= len(tokens) <= 6


def _cheque_signature_name_observations(text: str) -> list[str]:
    """Read the printed holder beside a cheque's signature instruction."""
    candidates: list[str] = []
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
        candidate = match.group(1).strip(" .'-\t")
        if is_person_name_candidate(candidate):
            candidates.append(candidate)
    return candidates


def _explicit_bank_account_observations(text: str, document_type: str) -> list[str]:
    """Return full, labelled bank-account values from person-scoped bank docs."""
    type_key = str(document_type or "").strip().casefold()
    if type_key not in {"bank statement", "passbook", "cheque"}:
        return []

    values: list[str] = []
    pattern = re.compile(
        r"(?:account\s*(?:number|no\.?|#)|"
        r"a\s*[/\\lI|]?\s*c\s*(?:number|no\.)?|"
        r"a[lI]?[ct]\s*(?:number|no\.?))"
        r"\s*[:\-\u2013]?\s*(?:\r?\n\s*)?([0-9][0-9 \t]{7,24})(?!\d)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(str(text or "")):
        digits = _digits(match.group(1))
        if 8 <= len(digits) <= 20:
            values.append(digits)
    return list(dict.fromkeys(values))
