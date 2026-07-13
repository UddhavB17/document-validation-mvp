"""Verification pipeline for trusted JSON plus explicit PDF page mappings."""

from __future__ import annotations

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
from services.ocr_engine import run_ocr_on_page
from services.pdf_processor import convert_page_to_image, open_pdf
from services.reviewer_summary import build_reviewer_summary
from services.reviewer_summary_store import save_reviewer_summary
from services.progress_tracker import update_page_progress, update_stage


VERIFY: dict[str, Callable[[str, str], Any]] = {
    "aadhaar_number": verify_aadhaar,
    "pan_number": verify_pan,
    "phone_number": verify_phone,
    "date_of_birth": verify_date,
    "loan_amount": verify_amount,
    "applicant_name": verify_name,
    "address": verify_address,
    "pin_code": verify_pincode,
}

ALIASES = {
    "aadhaar": "aadhaar_number",
    "aadhar": "aadhaar_number",
    "pan": "pan_number",
    "phone": "phone_number",
    "dob": "date_of_birth",
    "name": "applicant_name",
    "pincode": "pin_code",
}

DOCUMENT_FIELDS = {
    "aadhaar": {"aadhaar_number", "applicant_name", "date_of_birth", "address", "pin_code"},
    "pan": {"pan_number", "applicant_name", "date_of_birth"},
    "pan card": {"pan_number", "applicant_name", "date_of_birth"},
    "sanction letter": {"applicant_name", "loan_amount"},
    "loan agreement": {"applicant_name", "loan_amount"},
    "application form": {
        "applicant_name", "aadhaar_number", "pan_number", "date_of_birth",
        "phone_number", "address", "pin_code", "loan_amount",
    },
}


def run_mapped_verification(
    pdf_path: str | Path,
    application_id: int,
    manifest: dict[str, Any],
    *,
    output_dir: str | Path = "data/processed",
) -> dict[str, Any]:
    """OCR only mapped pages and compare fields with trusted reference JSON."""
    pdf_path = Path(pdf_path)
    target = Path(output_dir) / f"application_{application_id}" / "mapped_pages"
    document = open_pdf(pdf_path)
    total_pages = len(document)
    reference_data = manifest.get("reference_data") or {}
    pages: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    checked_fields = 0
    matched_fields = 0
    total_mapped_pages = len(
        {int(number) for item in manifest.get("documents") or [] for number in item.get("pages") or []}
    )
    processed_page_numbers: set[int] = set()

    try:
        update_stage(application_id, "processing_mapped_pages", "OCR-verifying supplied document pages")
        for mapping in manifest.get("documents") or []:
            document_type = str(mapping.get("document_type") or "Unknown")
            person_id = str(mapping.get("applicant_role") or mapping.get("person_id") or "primary")
            expected = _expected_fields(reference_data, mapping, document_type)
            mapped_pages = [int(number) for number in mapping.get("pages") or []]
            if not mapped_pages:
                if mapping.get("required", True):
                    anomalies.append(_anomaly("DOCUMENT_MISSING", "HIGH", None, document_type, None, None,
                                              "No page was mapped for this required document.",
                                              person_id=person_id))
                continue

            document_observations: dict[str, list[dict[str, Any]]] = {}
            readable_pages: list[int] = []
            for page_number in mapped_pages:
                if page_number < 1 or page_number > total_pages:
                    anomalies.append(_anomaly("PAGE_OUT_OF_RANGE", "HIGH", page_number, document_type, None,
                                              total_pages, "Mapped page does not exist in the PDF.",
                                              person_id=person_id))
                    continue
                image_path = convert_page_to_image(
                    document[page_number - 1],
                    target / f"page_{page_number}.png",
                )
                ocr = run_ocr_on_page(str(image_path or ""))
                text = str(ocr.get("ocr_text") or "")
                confidence = float(ocr.get("confidence") or 0.0)
                extracted = extract_fields(document_type, text)
                for key, value in extracted.items():
                    if not str(key).startswith("_") and value not in (None, ""):
                        field = _canonical(key)
                        observation = {
                            "person_id": person_id,
                            "document_type": document_type,
                            "source_document_id": mapping.get("source_document_id"),
                            "page_number": page_number,
                            "field_name": field,
                            "value": value,
                            "ocr_confidence": confidence,
                        }
                        observations.append(observation)
                        document_observations.setdefault(field, []).append(observation)
                if text and ocr.get("is_readable", True):
                    readable_pages.append(page_number)
                pages.append({
                    "page_number": page_number,
                    "page_type": "scanned",
                    "image_path": image_path,
                    "is_readable": bool(text) and bool(ocr.get("is_readable", True)),
                    "ocr_text": text,
                    "ocr_confidence": confidence,
                    "document_type": document_type,
                    "person_id": person_id,
                    "classification_confidence": 1.0,
                    "detection_method": "provided_mapping",
                    "detected_page_number": page_number,
                    "extracted_fields": extracted,
                })
                processed_page_numbers.add(page_number)
                update_page_progress(
                    application_id,
                    processed_pages=len(processed_page_numbers),
                    total_pages=total_mapped_pages,
                    current_page=page_number,
                    message=(
                        f"Verified mapped page {page_number} "
                        f"({len(processed_page_numbers)}/{total_mapped_pages})"
                    ),
                )

            if not readable_pages:
                anomalies.append(_anomaly("DOCUMENT_NOT_READABLE", "HIGH", mapped_pages[0], document_type,
                                          None, None, "OCR could not read the mapped document pages.",
                                          person_id=person_id))
                continue

            for raw_field, expected_value in expected.items():
                field = _canonical(raw_field)
                if field not in VERIFY or expected_value in (None, ""):
                    continue
                field_observations = document_observations.get(field) or []
                page_number = readable_pages[0]
                if not field_observations:
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
    result["observations"] = observations
    result["people_verification"] = _build_people_verification(
        reference_data, manifest.get("documents") or [], observations, result["anomalies"]
    )
    result["reviewer_summary"]["people_verification"] = result["people_verification"]
    save_reviewer_summary(application_id, result["reviewer_summary"])
    return result


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
    allowed = DOCUMENT_FIELDS.get(document_type.strip().lower())
    if not allowed:
        return values
    return {key: value for key, value in values.items() if _canonical(key) in allowed}


def _canonical(field: Any) -> str:
    value = str(field or "").strip().lower()
    return ALIASES.get(value, value)


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
    for other_id, data in reference_data.items():
        if other_id == person_id or not isinstance(data, dict):
            continue
        expected = data.get(field)
        if expected not in (None, "") and _comparison_key(field, expected) == found:
            return str(other_id)
    return None


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
