"""Comparison matrix and relationship graph construction for application review."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from services.review.repository import load_saved_document_ocr_json
from services.review.types import (
    ApplicationReviewData,
    ComparisonAndRelationships,
    ComparisonMatrix,
    FieldStatus,
)


def find_source_pages_for_value(
    pages: list[dict[str, Any]],
    value: str,
    field_name: str,
    person_id: str | None = None,
    page_to_person: dict[int, str] | None = None,
) -> list[int]:
    if not value or len(value.strip()) < 3:
        return []
    val_clean = value.strip().replace(" ", "").lower()
    source_pages: list[int] = []

    for page in pages:
        page_no = page.get("page_number")
        if page_no is None:
            continue
        page_no = int(page_no)

        if person_id and page_to_person:
            mapped_person = page_to_person.get(page_no)
            if mapped_person and mapped_person != person_id:
                doc_type = str(page.get("document_type") or "").strip().lower()
                if doc_type not in {"application form", "cam"}:
                    continue

        is_match = False
        extracted = page.get("extracted_fields") or {}

        field_value = extracted.get(field_name) or (
            extracted.get("_mapped_extraction") and extracted.get("_mapped_extraction").get(field_name)
        )
        if field_value:
            if str(field_value).strip().replace(" ", "").lower() == val_clean:
                is_match = True

        if not is_match:
            for key, extracted_value in extracted.items():
                if key.startswith("_"):
                    continue
                if str(extracted_value).strip().replace(" ", "").lower() == val_clean:
                    is_match = True
                    break

        if not is_match and page.get("_ocr_clean"):
            if val_clean in page["_ocr_clean"]:
                is_match = True

        if is_match:
            source_pages.append(page_no)

    return sorted(list(set(source_pages)))


def resolve_field_status(
    person_id: str,
    field_name: str,
    expected_value: str | None,
    actual_value: str | None,
    anomalies: list[dict[str, Any]],
    page_to_person: dict[int, str],
) -> FieldStatus:
    if not expected_value or expected_value == "None":
        return "match"
    if not actual_value or actual_value == "None":
        return "attention"

    has_mismatch = False
    has_attention = False

    for anomaly in anomalies:
        rule_id = str(anomaly.get("rule_id", "")).upper()
        page_no = anomaly.get("page_number")

        is_field_related = False
        if field_name == "applicant_name" and "NAME" in rule_id:
            is_field_related = True
        elif field_name == "pan_number" and "PAN" in rule_id:
            is_field_related = True
        elif field_name == "date_of_birth" and ("DOB" in rule_id or "DATE" in rule_id):
            is_field_related = True
        elif field_name == "phone_number" and "PHONE" in rule_id:
            is_field_related = True
        elif field_name == "address" and "ADDRESS" in rule_id:
            is_field_related = True
        elif field_name == "pin_code" and "PIN" in rule_id:
            is_field_related = True
        elif field_name == "aadhaar_last4" and "AADHAAR" in rule_id:
            is_field_related = True

        if is_field_related:
            applies_to_person = False
            if page_no is not None:
                if page_to_person.get(page_no) == person_id:
                    applies_to_person = True
            else:
                reason = str(anomaly.get("reason", "")).lower()
                if person_id in reason or (person_id == "primary" and "coapplicant" not in reason):
                    applies_to_person = True

            if applies_to_person:
                if "MISMATCH" in rule_id or "FAIL" in rule_id or "ERROR" in rule_id:
                    has_mismatch = True
                else:
                    has_attention = True

    if has_mismatch:
        return "mismatch"
    if has_attention:
        return "attention"
    return "match"


def build_comparison_matrix_and_relationships(
    application_id: int,
    data: ApplicationReviewData,
    *,
    ocr_data: Mapping[str, object] | None = None,
) -> ComparisonAndRelationships:
    ground_truth = data.get("ground_truth") or {}
    raw_json_str = ground_truth.get("raw_json")

    comparison_matrix: ComparisonMatrix = {
        "core_parameters": [],
        "applicants": [],
    }
    relationships: list[dict[str, Any]] = []

    if not raw_json_str:
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}

    try:
        gt_json = json.loads(str(raw_json_str))
    except Exception:
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}

    people = gt_json.get("people") or gt_json.get("reference_data") or {}
    if not people and gt_json.get("applicant_name"):
        people = {
            "primary": {
                "person_id": "primary",
                "role": "primary",
                "applicant_name": gt_json.get("applicant_name"),
                "pan_number": gt_json.get("pan_number"),
                "date_of_birth": gt_json.get("date_of_birth"),
                "phone_number": gt_json.get("phone_number"),
                "address": gt_json.get("address"),
                "pin_code": gt_json.get("pin_code"),
                "aadhaar_last4": gt_json.get("aadhaar_last4"),
                "gender": gt_json.get("gender"),
                "father_name": gt_json.get("father_name"),
                "mother_name": gt_json.get("mother_name"),
                "relationship": "Self",
            }
        }

    raw_pages = data.get("pages") or []
    anomalies = data.get("anomalies") or []

    if ocr_data is None:
        ocr_data = load_saved_document_ocr_json(application_id) or {}
    combined_extracted = ocr_data.get("combined_extracted_fields") or {}

    page_to_person: dict[int, str] = {}
    for doc_mapping in ocr_data.get("documents", []):
        person_id = doc_mapping.get("applicant_role") or doc_mapping.get("person_id")
        if person_id:
            for page_num in doc_mapping.get("pages", []):
                page_to_person[int(page_num)] = str(person_id)

    pages: list[dict[str, Any]] = []
    for page in raw_pages:
        page_dict = dict(page)
        ocr_text = page_dict.get("ocr_text")
        page_dict["_ocr_clean"] = str(ocr_text).replace(" ", "").lower() if ocr_text else ""
        pages.append(page_dict)

    core_fields = [
        ("loan_id", "Loan ID / Application Number"),
        ("sanction_amount", "Sanction Amount"),
        ("loan_amount", "Loan Amount"),
        ("roi", "Rate of Interest (ROI)"),
        ("tenure", "Tenure (Months)"),
        ("emi", "EMI"),
        ("installment_count", "Installment Count"),
        ("branch", "Branch"),
        ("product_type", "Product Type"),
        ("case_type", "Case Type"),
    ]

    for field_name, label in core_fields:
        expected = gt_json.get(field_name)
        if expected is None:
            continue
        expected = str(expected)

        extracted = combined_extracted.get(field_name)
        if extracted is None:
            extracted = data.get("application", {}).get(field_name)

        if extracted is not None:
            extracted = str(extracted)
        else:
            extracted = None

        source_pages: list[int] = []
        if extracted is not None:
            source_pages = find_source_pages_for_value(pages, extracted, field_name)

        status: FieldStatus = "match"
        has_mismatch = False
        has_attention = False
        for anomaly in anomalies:
            rule_id = str(anomaly.get("rule_id", "")).upper()
            if field_name.upper() in rule_id or (field_name == "loan_id" and "APPLICATION_NUMBER" in rule_id):
                if "MISMATCH" in rule_id or "FAIL" in rule_id or "ERROR" in rule_id:
                    has_mismatch = True
                else:
                    has_attention = True

        if has_mismatch:
            status = "mismatch"
        elif has_attention:
            status = "attention"
        elif extracted is None:
            status = "attention"

        comparison_matrix["core_parameters"].append(
            {
                "field_name": field_name,
                "label": label,
                "expected_value": expected,
                "extracted_value": extracted,
                "status": status,
                "source_pages": source_pages,
            }
        )

    dem_fields = [
        ("applicant_name", "Applicant Name"),
        ("pan_number", "PAN Number"),
        ("date_of_birth", "Date of Birth"),
        ("phone_number", "Phone Number"),
        ("address", "Address (Permanent)"),
        ("pin_code", "Pin Code"),
        ("aadhaar_last4", "Aadhaar Last 4"),
        ("gender", "Gender"),
        ("father_name", "Father / Spouse Name"),
    ]

    sorted_people = sorted(
        people.items(),
        key=lambda item: 0 if item[0] == "primary" or item[1].get("role") == "primary" else 1,
    )

    comparison_matrix["applicants"] = []
    coapplicant_count = 0

    for person_id, profile in sorted_people:
        person_name = profile.get("applicant_name")
        if not person_name:
            continue

        role = profile.get("role") or ("primary" if person_id == "primary" else "coapplicant")
        role_mapped = "primary" if role == "primary" else ("guarantor" if role == "guarantor" else "co_applicant")

        if role_mapped == "primary":
            applicant_label = "Primary Applicant"
        elif role_mapped == "guarantor":
            applicant_label = "Guarantor"
        else:
            coapplicant_count += 1
            applicant_label = f"Co-applicant {coapplicant_count}"

        applicant_entry = {
            "applicant_role": role_mapped,
            "applicant_label": applicant_label,
            "person_name": person_name,
            "fields": [],
        }

        has_any_mismatch = False
        has_any_attention = False

        for field_name, label_field in dem_fields:
            expected = profile.get(field_name)
            if expected is not None:
                expected = str(expected)
            else:
                if field_name == "father_name":
                    expected = profile.get("related_person_name")
                if expected is not None:
                    expected = str(expected)

            if expected is None or expected == "None":
                continue

            extracted = None
            for page in pages:
                page_number = page.get("page_number")
                if page_number is not None and page_to_person.get(int(page_number)) == person_id:
                    extracted_fields = page.get("extracted_fields") or {}
                    value = extracted_fields.get(field_name)
                    if value is None:
                        if field_name == "applicant_name":
                            value = extracted_fields.get("name") or extracted_fields.get("borrower_name")
                        elif field_name == "date_of_birth":
                            value = extracted_fields.get("dob")
                        elif field_name == "phone_number":
                            value = extracted_fields.get("phone")
                        elif field_name == "pin_code":
                            value = extracted_fields.get("pincode")
                        elif field_name == "address":
                            value = extracted_fields.get("permanent_address") or extracted_fields.get(
                                "communication_address"
                            )
                    if value is not None:
                        extracted = str(value)
                        break

            if extracted is None and person_id == "primary":
                extracted = combined_extracted.get(field_name)
                if extracted is not None:
                    extracted = str(extracted)

            source_pages = []
            if extracted is not None:
                source_pages = find_source_pages_for_value(
                    pages, extracted, field_name, person_id, page_to_person
                )
            elif expected is not None:
                source_pages = find_source_pages_for_value(
                    pages, expected, field_name, person_id, page_to_person
                )

            field_status = resolve_field_status(
                person_id, field_name, expected, extracted, anomalies, page_to_person
            )

            if field_status == "mismatch":
                has_any_mismatch = True
            elif field_status == "attention":
                has_any_attention = True

            applicant_entry["fields"].append(
                {
                    "field_name": field_name,
                    "label": label_field,
                    "expected_value": expected,
                    "extracted_value": extracted,
                    "status": field_status,
                    "source_pages": source_pages,
                }
            )

        profile["_computed_status"] = (
            "mismatch" if has_any_mismatch else ("attention" if has_any_attention else "match")
        )
        comparison_matrix["applicants"].append(applicant_entry)

    node_lookup: dict[str, dict[str, Any]] = {}
    primary_profile = people.get("primary")
    if primary_profile:
        name = primary_profile.get("applicant_name")
        status = primary_profile.get("_computed_status", "match")
        node_lookup[name.lower().strip()] = {
            "id": "p1",
            "name": name,
            "role": "primary",
            "relation_to_primary": None,
            "status": status,
        }

    co_index = 0
    fam_index = 0
    for person_id, profile in sorted_people:
        name = profile.get("applicant_name")
        if not name:
            continue
        name_key = name.lower().strip()
        role = profile.get("role") or ("primary" if person_id == "primary" else "coapplicant")
        role_mapped = "primary" if role == "primary" else ("guarantor" if role == "guarantor" else "co_applicant")
        relation = profile.get("relationship") or (None if role_mapped == "primary" else "co-applicant")
        status = profile.get("_computed_status", "match")

        if name_key not in node_lookup:
            if role_mapped in ("co_applicant", "guarantor"):
                co_index += 1
                node_id = f"c{co_index}"
            else:
                fam_index += 1
                node_id = f"f{fam_index}"

            node_lookup[name_key] = {
                "id": node_id,
                "name": name,
                "role": role_mapped,
                "relation_to_primary": relation if relation and relation.lower() != "self" else None,
                "status": status,
            }
        else:
            if relation and relation.lower() != "self":
                node_lookup[name_key]["relation_to_primary"] = relation
            if status != "match":
                node_lookup[name_key]["status"] = status

        father = profile.get("father_name")
        if father and father.lower() != "none" and father.strip():
            father_key = father.lower().strip()
            if father_key not in node_lookup:
                fam_index += 1
                node_lookup[father_key] = {
                    "id": f"f{fam_index}",
                    "name": father,
                    "role": "family_member",
                    "relation_to_primary": (
                        "father"
                        if role_mapped == "primary"
                        else ("father-in-law" if relation == "WIFE" else "father")
                    ),
                    "status": "n/a",
                }
            elif role_mapped == "primary":
                node_lookup[father_key]["relation_to_primary"] = "father"

        mother = profile.get("mother_name")
        if mother and mother.lower() != "none" and mother.strip():
            mother_key = mother.lower().strip()
            if mother_key not in node_lookup:
                fam_index += 1
                node_lookup[mother_key] = {
                    "id": f"f{fam_index}",
                    "name": mother,
                    "role": "family_member",
                    "relation_to_primary": "mother" if role_mapped == "primary" else "mother",
                    "status": "n/a",
                }
            elif role_mapped == "primary":
                node_lookup[mother_key]["relation_to_primary"] = "mother"

    relationships = list(node_lookup.values())

    return {
        "comparison_matrix": comparison_matrix,
        "relationships": relationships,
    }
