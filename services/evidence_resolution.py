"""Resolve document type and person ownership without replacing OCR evidence.

This module performs a second, deterministic pass after every page has text.
It is shared by normalized ZIP packages and merged PDFs.  Trusted JSON is used
only to resolve *who* a document belongs to; values read from the document stay
separate and are never replaced by the trusted value.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from services.bureau_anchors import classify_credit_bureau_by_anchors
from services.cersai import starts_new_report as cersai_starts_new_report
from services.document_classifier import is_kyc_checklist_context
from services.field_extractor import extract_fields
from services.identifiers import plausible_aadhaar_digits
from services.person_ownership import MULTI_PERSON_DOCUMENT_TYPES, resolve_person_owner
from services.validation_gates import attach_field_provenance

UNKNOWN_TYPES = {"", "none", "unknown", "ocr skipped"}
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR_RE = re.compile(r"(?<!\d)(\d{4}[ \t]?\d{4}[ \t]?\d{4})(?!\d)")
_PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")
# Group-level promotions below this confidence would stamp near-arbitrary
# types (for example ZIP filename guesses) onto unrelated pages.
_GROUP_PROMOTION_MIN_CONFIDENCE = 0.55


def resolve_trusted_evidence(
    pages: list[dict[str, Any]],
    reference_data: dict[str, Any],
    *,
    source_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve low-confidence pages and document groups using auditable evidence.

    The function mutates ``pages`` in place and returns a compact summary.  It
    may promote an Unknown/low-confidence type when intrinsic document anchors
    are strong, aggregate fields across a document, and stamp a resolved owner.
    It never copies a trusted field value into a public extracted field.
    """
    trusted_people = {
        str(person_id): person
        for person_id, person in (reference_data or {}).items()
        if isinstance(person, dict)
    }
    for page in pages:
        _attach_generic_evidence(page)
        candidate = infer_document_type_from_evidence(str(page.get("ocr_text") or ""))
        if candidate:
            _promote_page_type(page, candidate)

    groups = _build_groups(pages, source_documents or [])
    summaries: list[dict[str, Any]] = []
    for group in groups:
        summary = _resolve_group(group, trusted_people)
        summaries.append(summary)

    return {
        "mode": "zip" if source_documents else "merged_pdf",
        "groups": summaries,
        "resolved_groups": sum(1 for item in summaries if item.get("resolved_document_type")),
        "resolved_owners": sum(1 for item in summaries if item.get("resolved_person_id")),
    }


def infer_document_type_from_evidence(text: str) -> dict[str, Any] | None:
    """Return a strong intrinsic document-type candidate, or abstain.

    Exact trusted values are deliberately not accepted here: a PAN printed in
    an application form identifies a person but does not turn the form into a
    PAN card.
    """
    raw = str(text or "")
    lowered = raw.casefold()
    candidates: list[dict[str, Any]] = []
    # KYC tables in application forms/CAMs enumerate several card names; a
    # page that mentions Aadhaar AND PAN AND Voter ID is not any single card.
    kyc_checklist = is_kyc_checklist_context(raw)

    from services.document_classifier import is_insurance_application_context

    if is_insurance_application_context(raw):
        candidates.append(
            {
                "document_type": "Insurance Form",
                "confidence": 0.99,
                "evidence": ["insurer_anchor", "insurance_proposal_fields"],
                "authoritative_override": True,
            }
        )

    if re.search(r"\b(?:request\s+for\s+disburs(?:al|ement)|drawdown\s+request)\b", lowered):
        candidates.append(
            {
                "document_type": "Disbursement Request",
                "confidence": 0.98,
                "evidence": ["disbursement_request_heading"],
                "authoritative_override": True,
            }
        )

    bureau = classify_credit_bureau_by_anchors(raw)
    if bureau.get("document_type") and float(bureau.get("confidence") or 0.0) >= 0.75:
        candidates.append(
            {
                "document_type": str(bureau["document_type"]),
                "confidence": float(bureau["confidence"]),
                "evidence": ["bureau_header_and_score_anchors"],
            }
        )

    pan_numbers = _PAN_RE.findall(raw.upper())
    pan_heading = bool(
        re.search(
            r"\b(?:permanent\s+account\s+number|income\s+tax\s+department|pan\s+card)\b",
            lowered,
        )
    )
    pan_card_context = bool(re.search(r"\b(?:father(?:'s)?\s+name|date\s+of\s+birth)\b", lowered))
    if kyc_checklist:
        pan_heading = False
    if pan_numbers and pan_heading:
        confidence = 0.92 if pan_card_context else 0.82
        candidates.append(
            {
                "document_type": "PAN",
                "confidence": confidence,
                "evidence": ["pan_format", "pan_card_heading"]
                + (["pan_card_identity_fields"] if pan_card_context else []),
            }
        )

    aadhaar_numbers = [
        digits for item in _AADHAAR_RE.findall(raw) if (digits := plausible_aadhaar_digits(item))
    ]
    aadhaar_authority = bool(
        re.search(
            r"\b(?:uidai|aadhaar|aadhar|unique\s+identification\s+authority)\b|"
            r"भारतीय\s+विशिष्ट\s+पहचान|मेरा\s+आधार",
            lowered,
            re.IGNORECASE,
        )
    )
    if (
        not kyc_checklist
        and aadhaar_authority
        and (aadhaar_numbers or re.search(r"\b(?:vid|virtual\s+id)\b", lowered))
    ):
        candidates.append(
            {
                "document_type": "Aadhaar",
                "confidence": 0.93 if aadhaar_numbers else 0.80,
                "evidence": ["aadhaar_authority_anchor", "aadhaar_identifier"],
            }
        )

    if re.search(r"\b(?:loan\s+application\s+form|application\s+form)\b", lowered) or (
        "applicant details" in lowered and "co-applicant" in lowered
    ):
        candidates.append(
            {
                "document_type": "Application Form",
                "confidence": 0.90,
                "evidence": ["application_form_heading"],
            }
        )

    if not kyc_checklist and re.search(
        r"\b(?:election\s+commission|elector(?:'s)?\s+photo\s+identity|epic\s+no)\b", lowered
    ):
        candidates.append(
            {
                "document_type": "Voter ID",
                "confidence": 0.86,
                "evidence": ["voter_identity_anchor"],
            }
        )

    if (
        not kyc_checklist
        and re.search(r"\b(?:driving\s+licen[cs]e|transport\s+department)\b", lowered)
        and re.search(r"\b[A-Z]{2}[ -]?\d{2}[ -]?\d{4}[ -]?\d{7}\b", raw.upper())
    ):
        candidates.append(
            {
                "document_type": "Driving License",
                "confidence": 0.88,
                "evidence": ["driving_licence_heading", "driving_licence_number"],
            }
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: float(item["confidence"]))


def _attach_generic_evidence(page: dict[str, Any]) -> None:
    text = str(page.get("ocr_text") or "")
    fields = page.get("extracted_fields")
    if not isinstance(fields, dict):
        fields = {}
    generic = {
        "pan_numbers": list(dict.fromkeys(_PAN_RE.findall(text.upper()))),
        "aadhaar_numbers": list(
            dict.fromkeys(
                digits
                for item in _AADHAAR_RE.findall(text)
                if (digits := plausible_aadhaar_digits(item))
            )
        ),
        "phone_numbers": list(dict.fromkeys(_PHONE_RE.findall(text))),
    }
    generic = {key: value for key, value in generic.items() if value}
    if generic:
        fields = dict(fields)
        fields["_generic_evidence"] = generic
        page["extracted_fields"] = fields


def _promote_page_type(page: dict[str, Any], candidate: dict[str, Any]) -> None:
    current_type = str(page.get("document_type") or "Unknown")
    current_confidence = float(page.get("classification_confidence") or 0.0)
    candidate_type = str(candidate["document_type"])
    candidate_confidence = float(candidate["confidence"])
    fields = page.get("extracted_fields")
    if not isinstance(fields, dict):
        fields = {}
    resolution = dict(fields.get("_evidence_resolution") or {})
    resolution.update(
        {
            "original_document_type": current_type,
            "candidate_document_type": candidate_type,
            "candidate_confidence": round(candidate_confidence, 3),
            "type_evidence": list(candidate.get("evidence") or []),
        }
    )

    can_promote = (
        bool(candidate.get("authoritative_override"))
        or current_type.strip().casefold() in UNKNOWN_TYPES
        or current_confidence < 0.65
        or (current_type != candidate_type and current_confidence < candidate_confidence - 0.20)
    )
    if can_promote:
        page["document_type"] = candidate_type
        page["classification_confidence"] = max(current_confidence, candidate_confidence)
        page["detection_method"] = "intrinsic_evidence_resolution"
        classification = dict(fields.get("_classification") or {})
        classification.update(
            {
                "assigned_type": candidate_type,
                "detection_method": "intrinsic_evidence_resolution",
                "pre_resolution_document_type": current_type,
                "resolution_evidence": list(candidate.get("evidence") or []),
            }
        )
        fields["_classification"] = classification
        resolution["document_type_changed"] = current_type != candidate_type
        resolution["resolved_document_type"] = candidate_type
    elif current_type != candidate_type:
        resolution["document_type_changed"] = False
        resolution["type_conflict"] = True
        resolution["resolved_document_type"] = current_type
    else:
        resolution["document_type_changed"] = False
        resolution["resolved_document_type"] = current_type
    fields["_evidence_resolution"] = resolution
    page["extracted_fields"] = fields
    attach_field_provenance(page)


def _build_groups(
    pages: list[dict[str, Any]], source_documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if int(page.get("page_number") or 0) > 0
    }
    source_by_page: dict[int, dict[str, Any]] = {}
    for source in source_documents:
        start = int(source.get("internal_page_start") or 0)
        end = int(source.get("internal_page_end") or 0)
        for page_number in range(start, end + 1):
            source_by_page[page_number] = source

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page in sorted(by_number.values(), key=lambda item: int(item.get("page_number") or 0)):
        page_number = int(page.get("page_number") or 0)
        page_type = str(page.get("document_type") or "Unknown")
        type_key = page_type.strip().casefold()
        source = source_by_page.get(page_number)
        source_id = str((source or {}).get("source_document_id") or "") or None
        if type_key in {"db data", "property image", "photo evidence", "ocr skipped"}:
            current = None
            continue
        detected_start = page.get("detected_page_number") == page.get("page_number")
        if type_key in UNKNOWN_TYPES:
            if (
                current is not None
                and current.get("zip_source_id") == source_id
                and _looks_like_continuation(page, str(current["document_type"]))
            ):
                current["pages"].append(page)
            else:
                current = None
            continue
        same_type = current is not None and str(current["document_type"]) == page_type
        same_source = current is not None and current.get("zip_source_id") == source_id
        keep_detected_page_in_group = bool(
            same_type
            and same_source
            and (
                type_key in MULTI_PERSON_DOCUMENT_TYPES
                or (
                    type_key == "cersai report"
                    and not cersai_starts_new_report(list(current.get("pages") or []), page)
                )
                or (
                    type_key == "aadhaar"
                    and _aadhaar_pages_belong_together(list(current.get("pages") or []), page)
                )
            )
        )
        starts_new = (
            current is None
            or not same_type
            or not same_source
            or (
                detected_start
                and not keep_detected_page_in_group
                and int(page.get("page_number") or 0) not in current["page_numbers"]
            )
        )
        if starts_new:
            number = int(page.get("page_number") or 0)
            if source_id:
                document_id = f"{source_id}#{number:04d}-{_slug(page_type)}"
                mode = "zip"
            else:
                document_id = f"merged-{number:04d}-{_slug(page_type)}"
                mode = "merged_pdf"
            current = {
                "document_id": document_id,
                "document_type": page_type,
                "pages": [],
                "page_numbers": [],
                "mode": mode,
                "zip_source_id": source_id,
                "source_document": source,
            }
            groups.append(current)
        current["pages"].append(page)
        current["page_numbers"].append(int(page.get("page_number") or 0))
    for group in groups:
        group.pop("page_numbers", None)
    return groups


def _looks_like_continuation(page: dict[str, Any], document_type: str) -> bool:
    text = str(page.get("ocr_text") or "").casefold()
    if not text.strip():
        return False
    if document_type.casefold() == "aadhaar":
        return bool(
            re.search(r"\b(?:address|pin\s*code|vid|w\s*/\s*o|s\s*/\s*o|d\s*/\s*o)\b", text)
        )
    if document_type.casefold() == "application form":
        return bool(
            re.search(r"\b(?:applicant|co-applicant|kyc\s+details|declaration|signature)\b", text)
        )
    if document_type.casefold() == "cersai report":
        return bool(
            re.search(
                r"\b(?:cersai|security\s+interest|search\s+output|end\s+of\s+report)\b",
                text,
            )
        )
    return False


def _aadhaar_pages_belong_together(
    current_pages: list[dict[str, Any]],
    next_page: dict[str, Any],
) -> bool:
    """Join adjacent Aadhaar front/back evidence without merging two cards."""
    if not current_pages:
        return False
    current_numbers = {number for page in current_pages for number in _page_aadhaar_numbers(page)}
    next_numbers = _page_aadhaar_numbers(next_page)
    if current_numbers and next_numbers:
        return bool(current_numbers & next_numbers)

    next_fields = next_page.get("extracted_fields")
    next_fields = next_fields if isinstance(next_fields, dict) else {}
    next_text = str(next_page.get("ocr_text") or "")
    has_address_side = bool(
        next_fields.get("address")
        or re.search(r"\b(?:address|pin\s*code|[WSDC]\s*/\s*O)\b", next_text, re.IGNORECASE)
    )
    has_holder_identity = bool(
        next_numbers
        or next_fields.get("applicant_name")
        or next_fields.get("date_of_birth")
        or next_fields.get("dob")
    )
    current_has_identity = any(
        _page_aadhaar_numbers(page)
        or (
            isinstance(page.get("extracted_fields"), dict)
            and (
                page["extracted_fields"].get("applicant_name")
                or page["extracted_fields"].get("date_of_birth")
                or page["extracted_fields"].get("dob")
            )
        )
        for page in current_pages
    )
    return bool(current_has_identity and has_address_side and not has_holder_identity)


def _page_aadhaar_numbers(page: dict[str, Any]) -> set[str]:
    fields = page.get("extracted_fields")
    fields = fields if isinstance(fields, dict) else {}
    values = [fields.get("aadhaar_number")]
    generic = fields.get("_generic_evidence")
    if isinstance(generic, dict):
        values.extend(generic.get("aadhaar_numbers") or [])
    return {digits for value in values if (digits := plausible_aadhaar_digits(value))}


def _resolve_group(
    group: dict[str, Any], reference_data: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    pages = list(group.get("pages") or [])
    text = "\n".join(
        cleaned for page in pages if (cleaned := _document_page_text(page.get("ocr_text")))
    )
    document_type, type_confidence, type_evidence = _group_document_type(pages, text)
    document_id = str(group.get("document_id") or "document")

    if (
        document_type
        and document_type.casefold() not in UNKNOWN_TYPES
        and type_confidence >= _GROUP_PROMOTION_MIN_CONFIDENCE
    ):
        for page in pages:
            current = str(page.get("document_type") or "Unknown")
            confidence = float(page.get("classification_confidence") or 0.0)
            if current.casefold() in UNKNOWN_TYPES or confidence < 0.50:
                _promote_page_type(
                    page,
                    {
                        "document_type": document_type,
                        "confidence": type_confidence,
                        "evidence": [*type_evidence, "document_group_continuity"],
                    },
                )

    document_fields = extract_fields(document_type, text) if document_type and text else {}
    if document_type.casefold() in MULTI_PERSON_DOCUMENT_TYPES:
        records = _merge_person_records(
            document_fields.get("person_records"),
            _trusted_person_records_from_observed_text(text, reference_data),
        )
        if records:
            document_fields["person_records"] = records
    _attach_document_extraction(pages, document_id, document_type, document_fields)

    multi_person = document_type.casefold() in MULTI_PERSON_DOCUMENT_TYPES
    source_document = group.get("source_document")
    source_filename = (
        str(source_document.get("original_filename") or "")
        if isinstance(source_document, dict)
        else ""
    )
    owner = (
        {"person_id": None, "confidence": 0.0, "evidence": ["multi_person_document"]}
        if multi_person
        else resolve_person_owner(
            pages,
            reference_data,
            document_type,
            source_filename=source_filename or None,
        )
    )
    resolved_person_id = owner.get("person_id")
    if resolved_person_id and not multi_person:
        for page in pages:
            page["person_id"] = resolved_person_id
            page["applicant_role"] = resolved_person_id

    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            fields = {}
        resolution = dict(fields.get("_evidence_resolution") or {})
        resolution.update(
            {
                "document_id": document_id,
                "resolved_document_type": document_type,
                "document_type_confidence": round(type_confidence, 3),
                "type_evidence": type_evidence,
                "resolved_person_id": resolved_person_id,
                "owner_confidence": round(float(owner.get("confidence") or 0.0), 3),
                "owner_evidence": list(owner.get("evidence") or []),
                "multi_person_document": multi_person,
                "trusted_values_replaced": False,
            }
        )
        fields["_evidence_resolution"] = resolution
        page["extracted_fields"] = fields
        attach_field_provenance(
            page,
            source_document=source_document if isinstance(source_document, dict) else None,
        )

    return {
        "document_id": document_id,
        "pages": [int(page.get("page_number") or 0) for page in pages],
        "resolved_document_type": document_type,
        "document_type_confidence": round(type_confidence, 3),
        "type_evidence": type_evidence,
        "resolved_person_id": resolved_person_id,
        "owner_confidence": round(float(owner.get("confidence") or 0.0), 3),
        "owner_evidence": list(owner.get("evidence") or []),
        "multi_person_document": multi_person,
        "person_record_count": len(document_fields.get("person_records") or []),
    }


_PAGE_COUNTER_LINE_RE = re.compile(
    r"^\s*page\s*(?:no\.?\s*)?\d+\s*(?:of|/)\s*\d+\s*[.;:]?\s*$",
    re.IGNORECASE,
)
_DIGITAL_SIGNATURE_FOOTER_RE = re.compile(
    r"^\s*(?:signed\s+by|reason\s*:|e-?signed\s+using|date\s*:)",
    re.IGNORECASE,
)


def _document_page_text(value: Any) -> str:
    """Remove pagination/signature footers before document-level extraction."""
    lines = str(value or "").splitlines()
    for index, line in enumerate(lines):
        if not _PAGE_COUNTER_LINE_RE.fullmatch(line):
            continue
        leading = [item for item in lines[:index] if item.strip()]
        trailing = [item for item in lines[index + 1 :] if item.strip()]
        if not trailing or (
            len(leading) >= 3
            and any(_DIGITAL_SIGNATURE_FOOTER_RE.match(item) for item in trailing[:8])
        ):
            return "\n".join(lines[:index]).rstrip()
        return "\n".join([*lines[:index], *lines[index + 1 :]]).strip()
    return "\n".join(lines).strip()


def _group_document_type(pages: list[dict[str, Any]], text: str) -> tuple[str, float, list[str]]:
    votes: Counter[str] = Counter()
    confidence_by_type: dict[str, list[float]] = {}
    for page in pages:
        document_type = str(page.get("document_type") or "Unknown")
        if document_type.casefold() in UNKNOWN_TYPES:
            continue
        confidence = float(page.get("classification_confidence") or 0.0)
        votes[document_type] += max(confidence, 0.01)
        confidence_by_type.setdefault(document_type, []).append(confidence)
    intrinsic = infer_document_type_from_evidence(text)
    if intrinsic:
        votes[str(intrinsic["document_type"])] += float(intrinsic["confidence"]) * 1.5
        confidence_by_type.setdefault(str(intrinsic["document_type"]), []).append(
            float(intrinsic["confidence"])
        )
    if not votes:
        return "Unknown", 0.0, []
    document_type = votes.most_common(1)[0][0]
    confidences = confidence_by_type.get(document_type) or [0.0]
    confidence = sum(confidences) / max(len(confidences), 1)
    evidence = ["page_type_votes"]
    if intrinsic and intrinsic["document_type"] == document_type:
        evidence.extend(list(intrinsic.get("evidence") or []))
    return document_type, round(min(1.0, confidence), 3), list(dict.fromkeys(evidence))


def _attach_document_extraction(
    pages: list[dict[str, Any]],
    document_id: str,
    document_type: str,
    document_fields: dict[str, Any],
) -> None:
    if not pages or not document_fields:
        return
    anchor = pages[0]
    fields = anchor.get("extracted_fields")
    if not isinstance(fields, dict):
        fields = {}
    fields = dict(fields)
    public = {
        key: value
        for key, value in document_fields.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    conflicts: dict[str, dict[str, Any]] = {}
    for key, value in public.items():
        current = fields.get(key)
        if current in (None, "", [], {}):
            fields[key] = value
        elif current != value:
            conflicts[key] = {"page_value": current, "document_value": value}
    fields["_document_extraction"] = {
        "document_id": document_id,
        "document_type": document_type,
        "observed_fields": public,
        "conflicts": conflicts,
        "trusted_values_replaced": False,
    }
    anchor["extracted_fields"] = fields


def _trusted_person_records_from_observed_text(
    text: str,
    reference_data: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build person rows only when trusted values are literally present in OCR.

    Trusted data locates evidence but is never copied as if OCR produced it.
    Every public value below is the exact substring found in ``text``.
    """
    records: list[dict[str, Any]] = []
    compact_digits = re.sub(r"\D", "", text)
    for person_id, trusted in reference_data.items():
        record: dict[str, Any] = {}
        evidence: list[str] = []

        pan = str(trusted.get("pan_number") or trusted.get("pan") or "").strip().upper()
        if pan and re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan):
            match = re.search(rf"\b{re.escape(pan)}\b", text.upper())
            if match:
                record["pan_number"] = text[match.start() : match.end()]
                evidence.append("exact_pan_match")

        aadhaar = re.sub(r"\D", "", str(trusted.get("aadhaar_number") or ""))
        aadhaar_last4 = re.sub(r"\D", "", str(trusted.get("aadhaar_last4") or ""))[-4:]
        if aadhaar and len(aadhaar) == 12 and aadhaar in compact_digits:
            observed = next(
                (item for item in _AADHAAR_RE.findall(text) if re.sub(r"\D", "", item) == aadhaar),
                None,
            )
            if observed:
                record["aadhaar_number"] = re.sub(r"\D", "", observed)
                evidence.append("exact_aadhaar_match")
        elif aadhaar_last4 and any(
            re.sub(r"\D", "", item).endswith(aadhaar_last4) for item in _AADHAAR_RE.findall(text)
        ):
            record["aadhaar_last4"] = aadhaar_last4
            evidence.append("aadhaar_last4_match")

        phone = re.sub(r"\D", "", str(trusted.get("phone_number") or trusted.get("phone") or ""))
        if len(phone) == 10:
            phone_match = re.search(rf"(?<!\d){re.escape(phone)}(?!\d)", text)
            if phone_match:
                record["phone_number"] = phone_match.group(0)
                evidence.append("exact_phone_match")

        trusted_name = str(trusted.get("applicant_name") or "").strip()
        if trusted_name:
            name_match = re.search(rf"(?<!\w){re.escape(trusted_name)}(?!\w)", text, re.IGNORECASE)
            if name_match:
                record["applicant_name"] = name_match.group(0)
                evidence.append("exact_name_text_match")

        strong = {
            "exact_pan_match",
            "exact_aadhaar_match",
            "aadhaar_last4_match",
            "exact_phone_match",
        }
        if strong.intersection(evidence):
            record["_resolved_person_id"] = person_id
            record["_resolution_evidence"] = evidence
            records.append(record)
    return records


def _merge_person_records(*record_sets: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}
    for record_set in record_sets:
        if not isinstance(record_set, list):
            continue
        for record in record_set:
            if not isinstance(record, dict):
                continue
            pan = str(record.get("pan_number") or "").upper()
            aadhaar = re.sub(
                r"\D", "", str(record.get("aadhaar_number") or record.get("aadhaar_last4") or "")
            )
            phone = re.sub(r"\D", "", str(record.get("phone_number") or ""))
            person_id = str(record.get("_resolved_person_id") or "")
            name = str(record.get("applicant_name") or "").casefold()
            if pan:
                key = ("pan", pan)
            elif aadhaar:
                key = ("aadhaar", aadhaar)
            elif phone:
                key = ("phone", phone)
            elif person_id:
                key = ("person", person_id)
            else:
                key = ("name", name)
            if key in positions:
                existing = merged[positions[key]]
                for field, value in record.items():
                    if existing.get(field) in (None, "", [], {}) and value not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        existing[field] = value
                continue
            positions[key] = len(merged)
            merged.append(dict(record))
    return merged


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-") or "document"
