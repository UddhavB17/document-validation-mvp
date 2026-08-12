"""Verification pipeline for trusted JSON plus explicit PDF page mappings."""

from __future__ import annotations

from collections import Counter
from functools import partial
from pathlib import Path
from typing import Any, Callable

from services.exception_aggregator import aggregate
from services.field_extractor import extract_fields
from services.field_verification import (
    verify_aadhaar,
    verify_address,
    verify_amount,
    verify_date,
    verify_name,
    verify_pan,
    verify_phone,
    verify_pincode,
)
from services.ocr_router import OCRRouter, run_fast_ocr_on_page
from services.pdf_processor import convert_page_to_image, open_pdf
from services.person_names import is_person_name_candidate
from services.reviewer import build_reviewer_summary, save_reviewer_summary
from services.progress_tracker import update_page_progress, update_stage
from services.text_extractor import extract_digital_text
from services.validation_gates import attach_field_provenance, canonical_field, field_reliable_for_validation
from database.models import FieldVerificationResult


# Backward-compatible seam used by existing mapped-verification integrations.
run_ocr_on_page = run_fast_ocr_on_page
_DEFAULT_FAST_OCR_PROCESSOR = run_fast_ocr_on_page


def _verify_supported_field(field: str, extracted: str, expected: str) -> FieldVerificationResult:
    from services.consistency_checks import _matches

    matched = _matches(field, expected, extracted)
    return FieldVerificationResult(
        field_name=field,
        extracted_value=extracted,
        db_value=expected,
        match=matched,
        confidence=1.0 if matched else 0.0,
        method="exact" if field in {"account_number", "application_number", "ifsc"} else "fuzzy",
        mismatch_reason=None if matched else "Value does not match the trusted JSON/database dump",
    )


VERIFY: dict[str, Callable[[str, str], Any]] = {
    "aadhaar_number": verify_aadhaar,
    "pan_number": verify_pan,
    "phone_number": verify_phone,
    "date_of_birth": verify_date,
    "loan_amount": verify_amount,
    "applicant_name": verify_name,
    "address": verify_address,
    "pin_code": verify_pincode,
    "account_number": partial(_verify_supported_field, "account_number"),
    "application_number": partial(_verify_supported_field, "application_number"),
    "ifsc": partial(_verify_supported_field, "ifsc"),
    "tenure": partial(_verify_supported_field, "tenure"),
    "installment_count": partial(_verify_supported_field, "installment_count"),
    "emi": partial(_verify_supported_field, "emi"),
    "roi": partial(_verify_supported_field, "roi"),
    "apr": partial(_verify_supported_field, "apr"),
    "sanction_amount": partial(_verify_supported_field, "sanction_amount"),
    "total_interest": partial(_verify_supported_field, "total_interest"),
    "total_repayment": partial(_verify_supported_field, "total_repayment"),
    "processing_fee": partial(_verify_supported_field, "processing_fee"),
    "insurance_amount": partial(_verify_supported_field, "insurance_amount"),
    "net_disbursement": partial(_verify_supported_field, "net_disbursement"),
    "foir": partial(_verify_supported_field, "foir"),
    "ltv": partial(_verify_supported_field, "ltv"),
}

ALIASES = {
    "aadhaar": "aadhaar_number",
    "aadhar": "aadhaar_number",
    "pan": "pan_number",
    "phone": "phone_number",
    "dob": "date_of_birth",
    "name": "applicant_name",
    "borrower_name": "applicant_name",
    "account_holder_name": "applicant_name",
    "pincode": "pin_code",
    "current_address": "address",
    "permanent_address": "address",
    "communication_address": "address",
}

DOCUMENT_FIELDS = {
    "cam": {
        "application_number", "applicant_name", "phone_number", "loan_amount",
        "sanction_amount", "tenure", "emi", "roi", "account_number", "ifsc",
    },
    "aadhaar": {"aadhaar_number", "applicant_name", "date_of_birth", "address", "pin_code"},
    "pan": {"pan_number", "applicant_name", "date_of_birth"},
    "pan card": {"pan_number", "applicant_name", "date_of_birth"},
    "sanction letter": {"applicant_name", "loan_amount"},
    "kfs": {"loan_amount"},
    "loan agreement": {"applicant_name", "loan_amount"},
    "facility agreement": {"applicant_name", "loan_amount"},
    "application form": {
        "applicant_name", "aadhaar_number", "pan_number", "date_of_birth",
        "phone_number", "address", "pin_code", "loan_amount",
    },
    # Utility bills are presence/classification evidence only. Provider fields,
    # service addresses, dates and account holders are not cross-checked.
    "utility bill": set(),
    "voter id": {"applicant_name", "date_of_birth", "address"},
    "cibil report": {"applicant_name"},
    "crif report": {"applicant_name"},
    "cersai report": {"applicant_name", "pan_number"},
    "bank statement": {"applicant_name", "account_number", "ifsc"},
    "passbook": {"applicant_name", "account_number", "ifsc"},
    "cheque": {"applicant_name", "account_number", "ifsc"},
    "nach form": {"applicant_name", "account_number", "ifsc"},
}

# These types are often split across many ZIP members / page groups. Verify
# fields once per (person, document type), not once per fragment.
_AGGREGATED_FIELD_DOC_TYPES = frozenset(
    {
        "sanction letter",
        "cam",
        "kfs",
        "loan agreement",
        "facility agreement",
        "application form",
        "aadhaar",
        "pan",
        "pan card",
        "voter id",
        "driving license",
        "bank statement",
        "passbook",
        "utility bill",
        "cibil report",
        "crif report",
        "stamp duty",
        "insurance consent",
        "nach form",
        # Multi-page statement/financial documents: name appears on first page only
        "bank statement",
        "passbook",
        "cheque",
        "cibil report",
        "crif report",
    }
)

# Below this OCR confidence on a scanned page we cannot trust field extraction.
_LOW_OCR_CONFIDENCE_THRESHOLD = 0.55

# Account statements and similar banking documents commonly print the holder
# name only on the cover/first page.  The document-level comparison should
# still validate a name when one is observed, but must not report a missing
# name merely because a multi-page statement has no name-bearing page in the
# mapped fragment.
_OPTIONAL_ON_MULTIPAGE_BANKING_DOC_TYPES = frozenset(
    {"bank statement", "passbook", "cheque"}
)


def _name_optional_for_multipage_document(
    field: str, document_type: str, readable_pages: list[int]
) -> bool:
    return (
        field == "applicant_name"
        and document_type.strip().casefold() in _OPTIONAL_ON_MULTIPAGE_BANKING_DOC_TYPES
        and len(set(readable_pages)) > 1
    )


def _mapped_ocr_router() -> OCRRouter:
    """Build a router while retaining the historical monkeypatch seam."""
    kwargs: dict[str, Any] = {}
    if run_ocr_on_page is not _DEFAULT_FAST_OCR_PROCESSOR:
        kwargs["google_vision_processor"] = run_ocr_on_page
    return OCRRouter(
        fast_processor=run_ocr_on_page,
        structured_processor=run_ocr_on_page,
        **kwargs,
    )

def run_mapped_verification(
    pdf_path: str | Path,
    application_id: int,
    manifest: dict[str, Any],
    *,
    output_dir: str | Path = "data/processed",
) -> dict[str, Any]:
    """Extract mapped pages and compare their fields with trusted reference JSON."""
    pdf_path = Path(pdf_path)
    target = Path(output_dir) / f"application_{application_id}" / "mapped_pages"
    document = open_pdf(pdf_path)
    total_pages = len(document)
    reference_data = _verification_reference_data(manifest)
    pages: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    checked_fields = 0
    matched_fields = 0
    total_mapped_pages = len(
        {int(number) for item in manifest.get("documents") or [] for number in item.get("pages") or []}
    )
    processed_page_numbers: set[int] = set()
    digital_page_numbers: set[int] = set()
    ocr_page_numbers: set[int] = set()
    ocr_router = _mapped_ocr_router()

    try:
        update_stage(
            application_id,
            "processing_mapped_pages",
            "Extracting digital text and OCR-verifying scanned mapped pages",
        )
        for mapping in manifest.get("documents") or []:
            document_type = str(mapping.get("document_type") or "Unknown")
            provided_person_id = str(
                mapping.get("applicant_role") or mapping.get("person_id") or "primary"
            )
            person_id = provided_person_id
            expected = _expected_fields(reference_data, mapping, document_type)
            mapped_pages = [int(number) for number in mapping.get("pages") or []]
            if not mapped_pages:
                if mapping.get("required", True):
                    anomalies.append(_anomaly("DOCUMENT_MISSING", "HIGH", None, document_type, None, None,
                                              "No page was mapped for this required document.",
                                              person_id=person_id))
                continue

            document_observations: dict[str, list[dict[str, Any]]] = {}
            unreliable_fields: dict[str, list[dict[str, Any]]] = {}
            readable_pages: list[int] = []
            inherited_ocr_route = None
            mapping_page_start = len(pages)
            for page_number in mapped_pages:
                if page_number < 1 or page_number > total_pages:
                    anomalies.append(_anomaly("PAGE_OUT_OF_RANGE", "HIGH", page_number, document_type, None,
                                              total_pages, "Mapped page does not exist in the PDF.",
                                              person_id=person_id))
                    continue
                pdf_page = document[page_number - 1]
                text = _safe_digital_text(pdf_page)
                if text:
                    page_type = "digital"
                    image_path = None
                    is_readable = True
                    confidence = 1.0
                    text_source = "embedded_text"
                    digital_page_numbers.add(page_number)
                else:
                    page_type = "scanned"
                    image_path = convert_page_to_image(
                        pdf_page,
                        target / f"page_{page_number}.png",
                    )
                    routed_ocr = ocr_router.process_page(
                        str(image_path or ""),
                        document_type,
                        page_number,
                        doc_id=(
                            mapping.get("source_document_id")
                            or f"{application_id}:{document_type}:{mapped_pages[0]}"
                        ),
                        inherited_route=inherited_ocr_route,
                    )
                    inherited_ocr_route = routed_ocr.requested_route or routed_ocr.route_used
                    ocr = routed_ocr.to_legacy_dict()
                    text = routed_ocr.text
                    confidence = routed_ocr.confidence
                    is_readable = bool(text)
                    text_source = f"ocr_{routed_ocr.route_used}"
                    ocr_page_numbers.add(page_number)
                extracted = extract_fields(document_type, text)
                page_record = {
                    "page_number": page_number,
                    "page_type": page_type,
                    "image_path": image_path,
                    "is_readable": is_readable,
                    "ocr_text": text,
                    "ocr_confidence": confidence,
                    "document_type": document_type,
                    "person_id": person_id,
                    "classification_confidence": 1.0,
                    "detection_method": f"provided_mapping_{text_source}",
                    "detected_page_number": page_number,
                    "extracted_fields": extracted,
                }
                for key, value in extracted.items():
                    if (
                        not str(key).startswith("_")
                        and key != "repayment_schedule_rows"
                        and value not in (None, "")
                    ):
                        field = _canonical(key)
                        if not field_reliable_for_validation(
                            page_record,
                            field,
                            value,
                            expected_document_type=document_type,
                        ):
                            if field != "applicant_name":
                                unreliable_fields.setdefault(field, []).append(
                                    {"page_number": page_number, "value": value}
                                )
                            continue
                        observation = {
                            "person_id": person_id,
                            "document_type": document_type,
                            "source_document_id": mapping.get("source_document_id"),
                            "page_number": page_number,
                            "field_name": field,
                            "value": value,
                            "ocr_confidence": confidence,
                            "text_source": text_source,
                        }
                        observations.append(observation)
                        document_observations.setdefault(field, []).append(observation)
                if is_readable:
                    readable_pages.append(page_number)
                if page_type == "scanned":
                    page_record.update({
                        "ocr_structure": ocr,
                        "structured_content": routed_ocr.structured_content,
                        "ocr_route": routed_ocr.route_used,
                        "ocr_escalated": routed_ocr.escalated,
                        "ocr_processing_time_ms": routed_ocr.processing_time_ms,
                    })
                else:
                    page_record.update({
                        "ocr_structure": {},
                        "structured_content": None,
                        "ocr_route": None,
                        "ocr_escalated": False,
                        "ocr_processing_time_ms": 0,
                    })
                attach_field_provenance(page_record)
                pages.append(page_record)
                processed_page_numbers.add(page_number)
                update_page_progress(
                    application_id,
                    processed_pages=len(processed_page_numbers),
                    total_pages=total_mapped_pages,
                    current_page=page_number,
                    message=(
                        f"Verified mapped page {page_number} "
                        f"via {text_source} "
                        f"({len(processed_page_numbers)}/{total_mapped_pages})"
                    ),
                )

            mapping_page_records = pages[mapping_page_start:]
            person_id, debtor_scoped, owner = _resolved_mapping_person(
                document_type,
                mapping_page_records,
                reference_data,
                provided_person_id,
            )
            expected = _resolved_mapping_expected_fields(
                reference_data,
                mapping,
                document_type,
                person_id,
                debtor_scoped=debtor_scoped,
            )
            if debtor_scoped:
                for page_record in mapping_page_records:
                    page_record["person_id"] = person_id
                    page_record["applicant_role"] = person_id
                    fields = page_record.get("extracted_fields")
                    if isinstance(fields, dict):
                        fields["_ownership"] = {
                            "person_id": person_id,
                            "confidence": owner.get("confidence", 0.0),
                            "evidence": owner.get("evidence", []),
                            "cersai_search_type": "debtor_based",
                        }
                for field_observations in document_observations.values():
                    for observation in field_observations:
                        observation["person_id"] = person_id
                if person_id == "unassigned" and mapped_pages:
                    anomalies.append(_anomaly(
                        "AUTO_OWNER_UNRESOLVED", "LOW", mapped_pages[0], document_type,
                        "Debtor PAN matching a trusted applicant/co-applicant", None,
                        "CERSAI debtor identity did not match any trusted person.",
                        person_id=None,
                    ))

            if not readable_pages:
                anomalies.append(_anomaly("DOCUMENT_NOT_READABLE", "HIGH", mapped_pages[0], document_type,
                                          None, None, "Text extraction could not read the mapped document pages.",
                                          person_id=person_id))
                continue

            for raw_field, expected_value in expected.items():
                field = _canonical(raw_field)
                if field not in VERIFY or expected_value in (None, ""):
                    continue
                field_observations = document_observations.get(field) or []
                page_number = readable_pages[0]
                if not field_observations:
                    if field == "applicant_name" and unreliable_fields.get(field):
                        continue
                    if _name_optional_for_multipage_document(
                        field, document_type, readable_pages
                    ):
                        continue
                    if unreliable_fields.get(field):
                        anomalies.append(_anomaly(
                            f"{field.upper()}_EXTRACTION_UNRELIABLE", "LOW",
                            unreliable_fields[field][0].get("page_number") or page_number,
                            document_type, expected_value, None,
                            "Extracted evidence for this field was not reliable enough for trusted JSON comparison.",
                            field, "MANUAL_REVIEW_REQUIRED", person_id,
                        ))
                        continue
                    checked_fields += 1
                    anomalies.append(_anomaly(
                        f"{field.upper()}_NOT_FOUND", "MEDIUM", page_number, document_type,
                        expected_value, None, "Expected field was not found with sufficient confidence.", field,
                        "FIELD_NOT_FOUND", person_id,
                    ))
                    continue
                seen_values: set[str] = set()
                for observation in field_observations:
                    normalized_key = _comparison_key(field, observation["value"])
                    if normalized_key in seen_values:
                        continue
                    seen_values.add(normalized_key)
                    checked_fields += 1
                    result = VERIFY[field](str(observation["value"]), str(expected_value))
                    observation["expected_value"] = expected_value
                    observation["status"] = "MATCH" if result.match else "MISMATCH"
                    if result.match:
                        matched_fields += 1
                        continue
                    wrong_owner = _find_other_owner(
                        reference_data, person_id, field, observation["value"]
                    )
                    if wrong_owner:
                        anomalies.append(_anomaly(
                            "INDEX_MAPPING_SUSPECTED", "HIGH", observation["page_number"], document_type,
                            expected_value, observation["value"],
                            f"Value matches {wrong_owner}, not {person_id}; verify the page/person index.",
                            field, "MISMATCH", person_id, wrong_owner,
                        ))
                        continue
                    severity = "HIGH" if field in {"aadhaar_number", "pan_number", "date_of_birth"} else "MEDIUM"
                    anomalies.append(_anomaly(
                        f"{field.upper()}_MISMATCH", severity, observation["page_number"], document_type,
                        expected_value, observation["value"], result.mismatch_reason or "Values do not match.", field,
                        "MISMATCH", person_id,
                    ))
    finally:
        document.close()

    from services.pipeline import _save_ground_truth, _save_pages

    update_stage(application_id, "persisting_outputs", "Saving deterministic verification results")
    _save_ground_truth(application_id, reference_data)
    _save_pages(application_id, pages)
    result = aggregate(pages, anomalies, reference_data, application_id=application_id)
    result["reviewer_summary"] = build_reviewer_summary(
        total_pages=total_pages,
        anomalies=result["anomalies"],
        checked_fields=checked_fields,
        matched_fields=matched_fields,
    )
    result["checked_fields"] = checked_fields
    result["matched_fields"] = matched_fields
    result["mapped_pages_processed"] = len(pages)
    result["digital_pages_processed"] = len(digital_page_numbers)
    result["ocr_pages_processed"] = len(ocr_page_numbers)
    result["observations"] = observations
    result["people_verification"] = _build_people_verification(
        reference_data, manifest.get("documents") or [], observations, result["anomalies"]
    )
    result["reviewer_summary"]["people_verification"] = result["people_verification"]
    save_reviewer_summary(application_id, result["reviewer_summary"])
    return result


def compare_processed_pages(
    pages: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    source_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare shared-pipeline page output with trusted mapped JSON.

    Page rendering, digital-text extraction, OCR, deterministic classification,
    LLM classification, and field assignment have already happened in the normal
    PDF pipeline. This function adds trusted ownership/mapping evidence without
    re-running OCR.
    """
    reference_data = _verification_reference_data(manifest)
    documents = manifest.get("documents") or []
    source_lookup = _source_lookup(source_documents or [])
    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if page.get("page_number") is not None
    }
    anomalies: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    checked_fields = 0
    matched_fields = 0
    # For loan-level / multi-fragment types: collect once, verify once.
    aggregated: dict[tuple[str, str], dict[str, Any]] = {}

    for mapping in documents:
        provided_type = str(mapping.get("document_type") or "Unknown")
        provided_person_id = str(
            mapping.get("applicant_role") or mapping.get("person_id") or "primary"
        )
        source_document_id = mapping.get("source_document_id")
        mapped_numbers = [int(number) for number in mapping.get("pages") or []]
        mapped_page_records = [
            pages_by_number[number]
            for number in mapped_numbers
            if number in pages_by_number
        ]
        person_id, debtor_scoped, owner = _resolved_mapping_person(
            provided_type,
            mapped_page_records,
            reference_data,
            provided_person_id,
        )
        expected = _resolved_mapping_expected_fields(
            reference_data,
            mapping,
            provided_type,
            person_id,
            debtor_scoped=debtor_scoped,
        )
        document_observations: dict[str, list[dict[str, Any]]] = {}
        document_unreliable_fields: dict[str, list[dict[str, Any]]] = {}
        readable_pages: list[int] = []
        aggregate_key = (person_id, provided_type.strip().lower())
        should_aggregate = provided_type.strip().lower() in _AGGREGATED_FIELD_DOC_TYPES

        if not mapped_numbers:
            if mapping.get("required", True):
                anomalies.append(_anomaly(
                    "DOCUMENT_MISSING", "HIGH", None, provided_type, None, None,
                    "No page was mapped for this required document.", person_id=person_id,
                ))
            continue
        if debtor_scoped and person_id == "unassigned":
            anomalies.append(_anomaly(
                "AUTO_OWNER_UNRESOLVED", "LOW", mapped_numbers[0], provided_type,
                "Debtor PAN matching a trusted applicant/co-applicant", None,
                "CERSAI debtor identity did not match any trusted person.",
                person_id=None,
            ))

        for page_number in mapped_numbers:
            page = pages_by_number.get(page_number)
            if page is None:
                anomalies.append(_anomaly(
                    "PAGE_OUT_OF_RANGE", "HIGH", page_number, provided_type,
                    "Mapped page available in processed PDF", None,
                    "Mapped page was not produced by the shared PDF pipeline.",
                    person_id=person_id,
                ))
                continue

            fields = page.get("extracted_fields")
            if not isinstance(fields, dict):
                fields = {}
                page["extracted_fields"] = fields
            _suppress_invalid_name_fields(fields)
            mapping_metadata = {
                "person_id": person_id,
                "provided_person_id": provided_person_id,
                "provided_document_type": provided_type,
                "source_document_id": source_document_id,
                "pages": mapped_numbers,
            }
            fields["_provided_mapping"] = mapping_metadata
            page["person_id"] = person_id
            page["applicant_role"] = person_id
            if debtor_scoped:
                fields["_ownership"] = {
                    "person_id": person_id,
                    "confidence": owner.get("confidence", 0.0),
                    "evidence": owner.get("evidence", []),
                    "cersai_search_type": "debtor_based",
                }
            page["source_document_id"] = source_document_id
            page["provided_document_type"] = provided_type

            text = str(page.get("ocr_text") or "")
            mapped_fields = extract_fields(provided_type, text) if text else {}
            fields["_mapped_extraction"] = mapped_fields
            comparison_fields = {
                **{key: value for key, value in fields.items() if not str(key).startswith("_")},
                **{
                    key: value for key, value in mapped_fields.items()
                    if not str(key).startswith("_") and value not in (None, "", [], {})
                },
            }
            if page.get("is_readable") is not False and text.strip():
                readable_pages.append(page_number)

            for key, value in comparison_fields.items():
                if (
                    value in (None, "", [], {})
                    or str(key).startswith("_")
                    or key == "repayment_schedule_rows"
                ):
                    continue
                field = _canonical(key)
                if not field_reliable_for_validation(
                    page,
                    field,
                    value,
                    expected_document_type=provided_type,
                ):
                    if field != "applicant_name":
                        document_unreliable_fields.setdefault(field, []).append(
                            {"page_number": page_number, "value": value}
                        )
                    continue
                observation = {
                    "person_id": person_id,
                    "document_type": provided_type,
                    "classified_document_type": page.get("document_type"),
                    "source_document_id": source_document_id,
                    "source_filename": source_lookup.get(str(source_document_id), {}).get("original_filename"),
                    "source_segment": _source_segment(source_lookup.get(str(source_document_id), {})),
                    "page_number": page_number,
                    "field_name": field,
                    "value": value,
                    "document_confidence": mapping.get("auto_mapping", {}).get("document_confidence"),
                    "ocr_confidence": page.get("ocr_confidence"),
                    "text_source": (
                        "embedded_text"
                        if page.get("page_type") == "digital"
                        else f"ocr_{page.get('ocr_route') or 'api'}"
                    ),
                    "field_confidence": _observation_field_confidence(page, key),
                }
                observations.append(observation)
                document_observations.setdefault(field, []).append(observation)

        if not readable_pages:
            anomalies.append(_anomaly(
                "DOCUMENT_NOT_READABLE", "HIGH", mapped_numbers[0], provided_type,
                None, None,
                "The shared PDF pipeline could not extract text from the mapped document pages.",
                person_id=person_id,
            ))
            continue

        if should_aggregate:
            bucket = aggregated.setdefault(
                aggregate_key,
                {
                    "person_id": person_id,
                    "document_type": provided_type,
                    "expected": expected,
                    "observations": {},
                    "unreliable_fields": {},
                    "readable_pages": [],
                },
            )
            bucket["expected"].update(expected)
            bucket["readable_pages"].extend(readable_pages)
            for field, field_observations in document_observations.items():
                bucket["observations"].setdefault(field, []).extend(field_observations)
            for field, unreliable in document_unreliable_fields.items():
                bucket["unreliable_fields"].setdefault(field, []).extend(unreliable)
            continue

        field_stats = _verify_document_fields(
            expected=expected,
            document_observations=document_observations,
            readable_pages=readable_pages,
            provided_type=provided_type,
            person_id=person_id,
            reference_data=reference_data,
            anomalies=anomalies,
            unreliable_fields=document_unreliable_fields,
        )
        checked_fields += field_stats["checked"]
        matched_fields += field_stats["matched"]

    for bucket in aggregated.values():
        field_stats = _verify_document_fields(
            expected=bucket["expected"],
            document_observations=bucket["observations"],
            readable_pages=sorted(set(bucket["readable_pages"])),
            provided_type=bucket["document_type"],
            person_id=bucket["person_id"],
            reference_data=reference_data,
            anomalies=anomalies,
            prefer_any_match=True,
            unreliable_fields=bucket.get("unreliable_fields") or {},
        )
        checked_fields += field_stats["checked"]
        matched_fields += field_stats["matched"]

    source_classifications = _classify_source_documents(
        pages,
        documents,
        reference_data,
        source_documents or [],
    )
    _attach_source_provenance(anomalies, source_documents or [])
    people_verification = _build_people_verification(
        reference_data, documents, observations, anomalies
    )
    return {
        "anomalies": anomalies,
        "observations": observations,
        "checked_fields": checked_fields,
        "matched_fields": matched_fields,
        "people_verification": people_verification,
        "source_classifications": source_classifications,
    }


def _verify_document_fields(
    *,
    expected: dict[str, Any],
    document_observations: dict[str, list[dict[str, Any]]],
    readable_pages: list[int],
    provided_type: str,
    person_id: str,
    reference_data: dict[str, Any],
    anomalies: list[dict[str, Any]],
    prefer_any_match: bool = False,
    unreliable_fields: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, int]:
    """Compare extracted observations against expected values for one document unit."""
    checked = 0
    matched = 0

    # Determine which readable pages have low OCR confidence so we can suppress
    # spurious NOT_FOUND / MISMATCH anomalies for genuinely unreadable pages.
    low_confidence_pages_emitted: set[int] = set()

    for raw_field, expected_value in expected.items():
        field = _canonical(raw_field)
        if field not in VERIFY or expected_value in (None, ""):
            continue
        if field == "applicant_name" and not is_person_name_candidate(expected_value):
            continue
        field_observations = document_observations.get(field) or []
        if not field_observations:
            if field == "applicant_name" and (unreliable_fields or {}).get(field):
                continue
            if _name_optional_for_multipage_document(
                field, provided_type, readable_pages
            ):
                continue
            if (unreliable_fields or {}).get(field):
                page_number = ((unreliable_fields or {}).get(field) or [{}])[0].get("page_number")
                anomalies.append(_anomaly(
                    f"{field.upper()}_EXTRACTION_UNRELIABLE", "LOW", page_number,
                    provided_type, expected_value, None,
                    "Extracted evidence for this field was not reliable enough for trusted JSON comparison.",
                    field, "MANUAL_REVIEW_REQUIRED", person_id,
                ))
                continue
            page_number = readable_pages[0] if readable_pages else None
            # If the first readable page has low OCR confidence, suppress the
            # NOT_FOUND anomaly and emit a LOW_CONFIDENCE_PAGE once per page.
            first_page_conf = _page_ocr_confidence(document_observations, readable_pages)
            if first_page_conf is not None and first_page_conf < _LOW_OCR_CONFIDENCE_THRESHOLD:
                if page_number is not None and page_number not in low_confidence_pages_emitted:
                    low_confidence_pages_emitted.add(page_number)
                    anomalies.append(_anomaly(
                        "LOW_CONFIDENCE_PAGE", "LOW", page_number, provided_type,
                        "Readable OCR text", f"OCR confidence {first_page_conf:.0%} — field extraction unreliable",
                        "ocr_confidence", "MANUAL_REVIEW_REQUIRED", person_id,
                    ))
                continue  # Skip individual field anomalies for low-confidence pages
            checked += 1
            anomalies.append(_anomaly(
                f"{field.upper()}_NOT_FOUND", "MEDIUM", page_number if readable_pages else None,
                provided_type, expected_value, None,
                "Expected field was not found with sufficient confidence.",
                field, "FIELD_NOT_FOUND", person_id,
            ))
            continue

        if prefer_any_match:
            # One success across any fragment is enough for loan-level packets.
            matching = [
                observation for observation in field_observations
                if _mapped_field_matches(
                    field,
                    observation["value"],
                    expected_value,
                    reference_data.get(person_id, {}),
                )
            ]
            checked += 1
            if matching:
                matched += 1
                for observation in matching:
                    observation["expected_value"] = expected_value
                    observation["status"] = "MATCH"
                continue
            # Fall through to report the first distinct mismatch only.

        seen_values: set[str] = set()
        emitted_mismatch = False
        for observation in field_observations:
            normalized_key = _comparison_key(field, observation["value"])
            if normalized_key in seen_values:
                continue
            seen_values.add(normalized_key)
            if not prefer_any_match:
                checked += 1
            result = VERIFY[field](str(observation["value"]), str(expected_value))
            trusted_match = _mapped_field_matches(
                field,
                observation["value"],
                expected_value,
                reference_data.get(person_id, {}),
            )
            observation["expected_value"] = expected_value
            observation["status"] = "MATCH" if trusted_match else "MISMATCH"
            if trusted_match:
                if not prefer_any_match:
                    matched += 1
                continue
            if prefer_any_match and emitted_mismatch:
                continue

            # Gate mismatch anomalies on OCR confidence
            page_conf = float(observation.get("ocr_confidence") or 1.0)
            if page_conf < _LOW_OCR_CONFIDENCE_THRESHOLD:
                # Don't escalate low-confidence mismatches; emit one page-level warning
                page_number = observation.get("page_number")
                if page_number is not None and page_number not in low_confidence_pages_emitted:
                    low_confidence_pages_emitted.add(page_number)
                    anomalies.append(_anomaly(
                        "LOW_CONFIDENCE_PAGE", "LOW", page_number, provided_type,
                        "Reliable OCR text", f"OCR confidence {page_conf:.0%} — field comparison unreliable",
                        "ocr_confidence", "MANUAL_REVIEW_REQUIRED", person_id,
                    ))
                emitted_mismatch = True
                continue

            wrong_owner = _find_other_owner(reference_data, person_id, field, observation["value"])
            if wrong_owner:
                anomalies.append(_anomaly(
                    "INDEX_MAPPING_SUSPECTED", "HIGH", observation["page_number"], provided_type,
                    expected_value, observation["value"],
                    f"Value matches {wrong_owner}, not {person_id}; verify the page/person index.",
                    field, "MISMATCH", person_id, wrong_owner,
                ))
                emitted_mismatch = True
                continue
            severity = "HIGH" if field in {"aadhaar_number", "pan_number"} else "MEDIUM"
            anomalies.append(_anomaly(
                f"{field.upper()}_MISMATCH", severity, observation["page_number"], provided_type,
                expected_value, observation["value"], result.mismatch_reason or "Values do not match.",
                field, "MISMATCH", person_id,
            ))
            emitted_mismatch = True
    return {"checked": checked, "matched": matched}


def _mapped_field_matches(
    field: str,
    observed: Any,
    expected: Any,
    person: dict[str, Any] | None,
) -> bool:
    person = person if isinstance(person, dict) else {}
    if field == "applicant_name" and person:
        try:
            from services.person_ownership import name_matches_trusted_person

            if name_matches_trusted_person(observed, person):
                return True
        except Exception:
            pass
    if field == "address" and person:
        candidates = [
            value
            for key, value in person.items()
            if _canonical(key) == "address" and value not in (None, "")
        ]
        if any(VERIFY["address"](str(observed), str(value)).match for value in candidates):
            return True
    return VERIFY[field](str(observed), str(expected)).match


def _classify_source_documents(
    pages: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    reference_data: dict[str, Any],
    source_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate page/LLM classifications and extracted identity per ZIP member."""
    page_lookup = {int(page.get("page_number") or 0): page for page in pages}
    inventory = {str(item.get("source_document_id")): item for item in source_documents}
    grouped: dict[str, dict[str, Any]] = {}
    for source_id, item in inventory.items():
        start = int(item.get("internal_page_start") or 0)
        end = int(item.get("internal_page_end") or 0)
        grouped[source_id] = {
            "mappings": [],
            "pages": set(range(start, end + 1)) if start > 0 and end >= start else set(),
        }
    for mapping in mappings:
        source_id = str(mapping.get("source_document_id") or "unassigned")
        group = grouped.setdefault(source_id, {"mappings": [], "pages": set()})
        group["mappings"].append(mapping)
        group["pages"].update(int(number) for number in mapping.get("pages") or [])

    results: list[dict[str, Any]] = []
    for source_id, group in grouped.items():
        source_pages = [page_lookup[number] for number in sorted(group["pages"]) if number in page_lookup]
        type_votes: Counter[str] = Counter()
        owner_votes: Counter[str] = Counter()
        for page in source_pages:
            fields = page.get("extracted_fields") or {}
            from services.automatic_document_index import _effective_document_type

            predicted_type = _effective_document_type(page)
            if predicted_type not in {"Unknown", "None", "OCR Skipped"}:
                type_votes[predicted_type] += 1
            if isinstance(fields, dict):
                candidate_names = [
                    fields.get("applicant_name"),
                    fields.get("account_holder_name"),
                    fields.get("customer_name"),
                ]
                mapped_fields = fields.get("_mapped_extraction")
                if isinstance(mapped_fields, dict):
                    candidate_names.append(mapped_fields.get("applicant_name"))
                for candidate in candidate_names:
                    if not is_person_name_candidate(candidate):
                        continue
                    candidate_key = _comparison_key("applicant_name", candidate)
                    if not candidate_key:
                        continue
                    for person_id, trusted in reference_data.items():
                        if not isinstance(trusted, dict):
                            continue
                        trusted_name = trusted.get("applicant_name")
                        if not is_person_name_candidate(trusted_name):
                            continue
                        if candidate_key == _comparison_key("applicant_name", trusted_name):
                            owner_votes[str(person_id)] += 1

        provided_owners = sorted({
            str(item.get("applicant_role") or item.get("person_id") or "primary")
            for item in group["mappings"]
        })
        predicted_owner = owner_votes.most_common(1)[0][0] if owner_votes else (
            provided_owners[0] if len(provided_owners) == 1 else None
        )
        predicted_type = type_votes.most_common(1)[0][0] if type_votes else "Unknown"
        item = inventory.get(source_id, {})
        classification = {
            "source_document_id": source_id,
            "original_filename": item.get("original_filename"),
            "pages": sorted(group["pages"]),
            "provided_person_ids": provided_owners,
            "predicted_person_id": predicted_owner,
            "owner_detection_method": "extracted_identity" if owner_votes else "provided_mapping",
            "provided_document_types": sorted({str(entry.get("document_type") or "Unknown") for entry in group["mappings"]}),
            "predicted_document_type": predicted_type,
            "document_type_votes": dict(type_votes),
        }
        results.append(classification)
        for page in source_pages:
            fields = page.get("extracted_fields")
            if isinstance(fields, dict):
                fields["_zip_source_classification"] = classification
    return results


def _source_lookup(source_documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("source_document_id") or ""): item for item in source_documents}


def _source_segment(source: dict[str, Any]) -> str | None:
    if not source:
        return None
    start = source.get("internal_page_start")
    end = source.get("internal_page_end")
    if start in (None, "") or end in (None, ""):
        return None
    return f"{start}-{end}" if start != end else str(start)


def _attach_source_provenance(
    anomalies: list[dict[str, Any]], source_documents: list[dict[str, Any]]
) -> None:
    by_source = _source_lookup(source_documents)
    by_page: dict[int, dict[str, Any]] = {}
    for source in source_documents:
        start = int(source.get("internal_page_start") or 0)
        end = int(source.get("internal_page_end") or 0)
        for page_number in range(start, end + 1):
            by_page[page_number] = source
    for anomaly in anomalies:
        source = by_source.get(str(anomaly.get("source_document_id") or ""))
        if not source:
            page_number = anomaly.get("page_number")
            if page_number is not None:
                source = by_page.get(int(page_number))
        if not source:
            continue
        anomaly["source_document_id"] = source.get("source_document_id")
        anomaly["source_filename"] = source.get("original_filename")
        anomaly["source_segment"] = _source_segment(source)


def _safe_digital_text(page: Any) -> str:
    """Use embedded text when available; page failures safely fall back to OCR."""
    try:
        return extract_digital_text(page)
    except Exception:
        return ""


def _get_allowed_fields_for_type(document_type: str) -> set[str] | None:
    doc_lower = document_type.strip().lower()
    if doc_lower == "utility bill":
        # This explicit empty contract also overrides older persisted admin
        # settings that required utility address/name/PIN comparisons.
        return set()
    norm_key = doc_lower.replace(" ", "_")
    if norm_key == "pan_card":
        norm_key = "pan"
    elif norm_key == "cibil_report":
        norm_key = "cibil"
    elif norm_key == "crif_report":
        norm_key = "crif"

    from services.config import get_setting
    db_fields = get_setting(f"required_fields.{norm_key}")
    if isinstance(db_fields, list):
        # Admin configuration can add case-specific fields, while the core
        # identity/account/loan reconciliation contract remains mandatory.
        return set(db_fields) | set(DOCUMENT_FIELDS.get(doc_lower) or set())

    return DOCUMENT_FIELDS.get(doc_lower)


def _resolved_mapping_person(
    document_type: str,
    pages: list[dict[str, Any]],
    reference_data: dict[str, Any],
    provided_person_id: str,
) -> tuple[str, bool, dict[str, Any]]:
    """Override a CERSAI mapping only when its entered debtor establishes scope."""
    from services.person_ownership import (
        document_requires_person_owner,
        resolve_person_owner,
    )

    if str(document_type or "").strip().casefold() != "cersai report":
        return provided_person_id, False, {
            "person_id": provided_person_id,
            "confidence": 0.7,
            "evidence": ["provided_mapping"],
        }
    debtor_scoped = document_requires_person_owner(document_type, pages)
    if not debtor_scoped:
        return provided_person_id, False, {
            "person_id": provided_person_id,
            "confidence": 0.7,
            "evidence": ["provided_mapping"],
        }
    owner = resolve_person_owner(pages, reference_data, document_type)
    resolved = str(owner.get("person_id") or "unassigned")
    return resolved, True, owner


def _resolved_mapping_expected_fields(
    reference_data: dict[str, Any],
    mapping: dict[str, Any],
    document_type: str,
    person_id: str,
    *,
    debtor_scoped: bool,
) -> dict[str, Any]:
    if debtor_scoped and person_id == "unassigned":
        return {}
    effective_mapping = dict(mapping)
    effective_mapping["applicant_role"] = person_id
    if debtor_scoped:
        # Explicit fields attached to the original page/person mapping can be
        # stale. Rebuild expectations from the debtor's trusted person record.
        effective_mapping.pop("expected_fields", None)
    return _expected_fields(reference_data, effective_mapping, document_type)


def _expected_fields(
    reference_data: dict[str, Any],
    document: dict[str, Any],
    document_type: str,
) -> dict[str, Any]:
    explicit = document.get("expected_fields")
    if isinstance(explicit, dict) and explicit:
        return explicit
    role = str(document.get("applicant_role") or "primary")
    role_data = reference_data.get(role)
    values = role_data if isinstance(role_data, dict) else reference_data
    allowed = _get_allowed_fields_for_type(document_type)
    if not allowed:
        # Do not demand identity fields from photos, screenshots, affidavits,
        # spreadsheets, or other document types that have no verification contract.
        return {}
    return {key: value for key, value in values.items() if _canonical(key) in allowed}


def _verification_reference_data(manifest: dict[str, Any]) -> dict[str, Any]:
    """Include trusted root loan terms in the primary verification record."""
    raw = manifest.get("reference_data") or {}
    reference_data = {
        str(person_id): dict(person)
        for person_id, person in raw.items()
        if isinstance(person, dict)
    } if isinstance(raw, dict) and any(isinstance(value, dict) for value in raw.values()) else {}
    if not reference_data:
        reference_data = {"primary": dict(raw)} if isinstance(raw, dict) else {"primary": {}}
    primary_id = "primary" if "primary" in reference_data else next(iter(reference_data))
    primary = reference_data[primary_id]
    loan_fields = {
        "application_number",
        "loan_amount",
        "sanction_amount",
        "tenure",
        "installment_count",
        "emi",
        "roi",
        "apr",
        "total_interest",
        "total_repayment",
        "processing_fee",
        "insurance_amount",
        "net_disbursement",
        "foir",
        "ltv",
    }
    for raw_field, value in manifest.items():
        field = _canonical(raw_field)
        if field in loan_fields and value not in (None, "", [], {}) and primary.get(field) in (None, ""):
            primary[field] = value
    return reference_data


def _canonical(field: Any) -> str:
    value = str(field or "").strip().lower()
    return canonical_field(ALIASES.get(value, value))


def _observation_field_confidence(page: dict[str, Any], field: Any) -> float | None:
    fields = page.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        return None
    provenance = fields.get("_field_provenance")
    if not isinstance(provenance, dict):
        return None
    item = provenance.get(str(field))
    if not isinstance(item, dict):
        field_key = _canonical(field)
        item = next(
            (
                candidate
                for key, candidate in provenance.items()
                if _canonical(key) == field_key and isinstance(candidate, dict)
            ),
            None,
        )
    if not isinstance(item, dict):
        return None
    try:
        return float(item.get("field_confidence"))
    except (TypeError, ValueError):
        return None


def _page_ocr_confidence(
    document_observations: dict[str, list[dict[str, Any]]],
    readable_pages: list[int],
) -> float | None:
    """Return the OCR confidence for the first readable page, or None if unavailable.

    Looks for any observation on the first readable page that has an
    ``ocr_confidence`` key.  Digital (embedded-text) pages always have
    confidence 1.0 and are never below the threshold.
    """
    if not readable_pages:
        return None
    first_page = readable_pages[0]
    for obs_list in document_observations.values():
        for obs in obs_list:
            if obs.get("page_number") == first_page:
                conf = obs.get("ocr_confidence")
                if conf is not None:
                    return float(conf)
    return None



def _anomaly(
    rule_id: str,
    severity: str,
    page_number: int | None,
    document_type: str,
    expected: Any,
    found: Any,
    reason: str,
    field_name: str | None = None,
    status: str = "MANUAL_REVIEW_REQUIRED",
    person_id: str | None = None,
    matched_person_id: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "s_no": None,
        "severity": severity,
        "document_type": document_type,
        "person_id": person_id,
        "matched_person_id": matched_person_id,
        "field_name": field_name,
        "status": status,
        "expected_value": expected,
        "found_value": found,
        "page_number": page_number,
        "reason": reason,
    }


def _comparison_key(field: str, value: Any) -> str:
    text = str(value or "").strip().upper()
    if field in {"aadhaar_number", "phone_number", "pin_code"}:
        return "".join(character for character in text if character.isdigit())
    return " ".join(text.split())


def _find_other_owner(
    reference_data: dict[str, Any], person_id: str, field: str, found_value: Any
) -> str | None:
    found = _comparison_key(field, found_value)
    if field == "applicant_name" and not is_person_name_candidate(found_value):
        return None
    for other_id, data in reference_data.items():
        if other_id == person_id or not isinstance(data, dict):
            continue
        expected = None
        for k, v in data.items():
            if _canonical(k) == field:
                expected = v
                break
        if expected not in (None, ""):
            if field == "applicant_name" and not is_person_name_candidate(expected):
                continue
            if _comparison_key(field, expected) == found:
                return str(other_id)
            validator = VERIFY.get(field)
            if validator:
                try:
                    if validator(str(found_value), str(expected)).match:
                        return str(other_id)
                except Exception:
                    pass
    return None


def _name_observation_is_reliable(page: dict[str, Any], value: Any) -> bool:
    fields = page.get("extracted_fields") or {}
    if isinstance(fields, dict) and fields.get("_identity_extraction_reliable") is False:
        return False
    return is_person_name_candidate(value)


def _suppress_invalid_name_fields(fields: dict[str, Any]) -> None:
    for key, value in list(fields.items()):
        if str(key).startswith("_"):
            continue
        if key == "person_records" and isinstance(value, list):
            for record in value:
                if isinstance(record, dict):
                    _suppress_invalid_name_fields(record)
            continue
        if _canonical(key) != "applicant_name":
            continue
        if isinstance(value, list):
            names = [item for item in value if is_person_name_candidate(item)]
            fields[key] = names
        elif value not in (None, "") and not is_person_name_candidate(value):
            fields[key] = None


def _build_people_verification(
    reference_data: dict[str, Any],
    documents: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
) -> dict[str, Any]:
    matrix: dict[str, Any] = {}
    person_ids = set(reference_data)
    person_ids.update(str(item.get("applicant_role") or "primary") for item in documents)
    for person_id in sorted(person_ids):
        trusted = reference_data.get(person_id)
        person_name = trusted.get("applicant_name") if isinstance(trusted, dict) else None
        person_documents: dict[str, Any] = {}
        document_types = sorted({
            str(mapping.get("document_type") or "Unknown")
            for mapping in documents
            if str(mapping.get("applicant_role") or "primary") == person_id
        })
        for document_type in document_types:
            mappings = [
                mapping for mapping in documents
                if str(mapping.get("applicant_role") or "primary") == person_id
                and str(mapping.get("document_type") or "Unknown") == document_type
            ]
            relevant_observations = [
                item for item in observations
                if item["person_id"] == person_id and item["document_type"] == document_type
            ]
            relevant_anomalies = [
                item for item in anomalies
                if item.get("person_id") == person_id and item.get("document_type") == document_type
            ]
            status = "NEEDS_REVIEW" if relevant_anomalies else "MATCH"
            compared_observations = [item for item in relevant_observations if item.get("status")]
            if not compared_observations and not relevant_anomalies:
                status = "NOT_CHECKED"
            person_documents[document_type] = {
                "status": status,
                "pages": sorted({page for mapping in mappings for page in mapping.get("pages") or []}),
                "fields": sorted({item["field_name"] for item in relevant_observations}),
                "observation_count": len(relevant_observations),
                "anomaly_count": len(relevant_anomalies),
            }
        matrix[person_id] = {
            "person_id": person_id,
            "person_name": person_name,
            "status": (
                "NEEDS_REVIEW"
                if any(item["status"] == "NEEDS_REVIEW" for item in person_documents.values())
                else (
                    "MATCH"
                    if person_documents and all(
                        item["status"] == "MATCH" for item in person_documents.values()
                    )
                    else "NOT_CHECKED"
                )
            ),
            "documents": person_documents,
        }
    return matrix
