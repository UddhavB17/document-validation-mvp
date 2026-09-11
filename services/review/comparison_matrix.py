"""Comparison matrix and relationship graph construction for application review."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from services.consistency_checks import _matches
from services.review.comparison_evidence import comparison_observations, observed_field
from services.review.types import (
    ApplicantComparisonSection,
    ApplicantRole,
    ApplicationReviewData,
    ComparisonAndRelationships,
    ComparisonMatrix,
    FieldStatus,
    RelationshipNode,
)

LOGGER = logging.getLogger(__name__)


def _mapped_role(role: object, person_id: str) -> ApplicantRole:
    """Normalize persisted applicant roles to the review API's role values."""
    normalized_role = str(role or ("primary" if person_id == "primary" else "coapplicant"))
    if normalized_role == "primary":
        return "primary"
    if normalized_role == "guarantor":
        return "guarantor"
    return "co_applicant"


def resolve_field_status(
    person_id: str,
    field_name: str,
    expected_value: str | None,
    actual_value: str | None,
    anomalies: list[dict[str, Any]],
    page_to_person: dict[int, str],
) -> FieldStatus:
    """Resolve one applicant field's status from values and related anomalies."""
    if not expected_value or expected_value == "None":
        return "match"
    if not actual_value or actual_value == "None":
        return "attention"
    if not _matches(field_name, expected_value, actual_value):
        return "mismatch"

    has_mismatch = False
    has_attention = False

    for anomaly in anomalies:
        rule_id = str(anomaly.get("rule_id", "")).upper()
        page_number = anomaly.get("page_number")

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
            if page_number is not None:
                if page_to_person.get(page_number) == person_id:
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
    evidence_pages: list[dict[str, Any]] | None = None,
) -> ComparisonAndRelationships:
    """Build comparison rows and relationship nodes for an application review."""
    # Initialize the stable empty response used for missing or invalid ground truth.
    ground_truth = data.get("ground_truth") or {}
    raw_ground_truth_json = ground_truth.get("raw_json")

    comparison_matrix: ComparisonMatrix = {
        "core_parameters": [],
        "applicants": [],
    }
    relationships: list[RelationshipNode] = []

    if not raw_ground_truth_json:
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}

    try:
        decoded_ground_truth = json.loads(str(raw_ground_truth_json))
    except (TypeError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "Application %s has invalid ground-truth JSON; comparison matrix is empty",
            application_id,
            exc_info=exc,
        )
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}
    if not isinstance(decoded_ground_truth, dict):
        LOGGER.warning(
            "Application %s ground-truth JSON is not an object; comparison matrix is empty",
            application_id,
        )
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}
    ground_truth_json = decoded_ground_truth

    # Support both the multi-person and legacy single-applicant ground-truth shapes.
    people = ground_truth_json.get("people") or ground_truth_json.get("reference_data") or {}
    if not people and ground_truth_json.get("applicant_name"):
        people = {
            "primary": {
                "person_id": "primary",
                "role": "primary",
                "applicant_name": ground_truth_json.get("applicant_name"),
                "pan_number": ground_truth_json.get("pan_number"),
                "date_of_birth": ground_truth_json.get("date_of_birth"),
                "phone_number": ground_truth_json.get("phone_number"),
                "address": ground_truth_json.get("address"),
                "pin_code": ground_truth_json.get("pin_code"),
                "aadhaar_last4": ground_truth_json.get("aadhaar_last4"),
                "gender": ground_truth_json.get("gender"),
                "father_name": ground_truth_json.get("father_name"),
                "mother_name": ground_truth_json.get("mother_name"),
                "relationship": "Self",
            }
        }

    raw_pages = data.get("pages") or []
    anomalies = data.get("anomalies") or []

    # The optional export can be absent or stale. Persisted page evidence is
    # authoritative; expected/application metadata is never extracted evidence.
    observations = comparison_observations(
        evidence_pages if evidence_pages is not None else raw_pages, people
    )
    page_to_person: dict[int, str] = {}
    owners_by_page: dict[int, set[str]] = {}
    for observation in observations:
        owners_by_page.setdefault(observation["page_number"], set()).add(observation["person_id"])
    for page_number, owners in owners_by_page.items():
        if len(owners) == 1:
            page_to_person[page_number] = next(iter(owners))

    # Build application-level comparison rows.
    core_field_definitions = [
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

    for field_name, label in core_field_definitions:
        expected = ground_truth_json.get(field_name)
        if expected is None:
            continue
        expected = str(expected)

        extracted, source_pages, status = observed_field(observations, field_name, expected)
        has_mismatch = False
        has_attention = False
        for anomaly in anomalies:
            rule_id = str(anomaly.get("rule_id", "")).upper()
            if field_name.upper() in rule_id or (
                field_name == "loan_id" and "APPLICATION_NUMBER" in rule_id
            ):
                if "MISMATCH" in rule_id or "FAIL" in rule_id or "ERROR" in rule_id:
                    has_mismatch = True
                else:
                    has_attention = True

        if has_mismatch:
            status = "mismatch"
        elif has_attention and status == "match":
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

    # Build applicant-level comparison rows before constructing relationship nodes.
    applicant_field_definitions = [
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

    for person_id, person_profile in sorted_people:
        person_name = person_profile.get("applicant_name")
        if not person_name:
            continue

        mapped_role = _mapped_role(person_profile.get("role"), person_id)

        if mapped_role == "primary":
            applicant_label = "Primary Applicant"
        elif mapped_role == "guarantor":
            applicant_label = "Guarantor"
        else:
            coapplicant_count += 1
            applicant_label = f"Co-applicant {coapplicant_count}"

        applicant_section: ApplicantComparisonSection = {
            "applicant_role": mapped_role,
            "applicant_label": applicant_label,
            "person_name": person_name,
            "fields": [],
        }

        has_any_mismatch = False
        has_any_attention = False

        for field_name, field_label in applicant_field_definitions:
            expected = person_profile.get(field_name)
            if expected is not None:
                expected = str(expected)
            else:
                if field_name == "father_name":
                    expected = person_profile.get("related_person_name")
                if expected is not None:
                    expected = str(expected)

            if expected is None or expected == "None":
                continue

            extracted, source_pages, field_status = observed_field(
                observations, field_name, expected, person_id
            )
            anomaly_status = resolve_field_status(
                person_id, field_name, expected, extracted, anomalies, page_to_person
            )
            if field_status == "match":
                field_status = anomaly_status

            if field_status == "mismatch":
                has_any_mismatch = True
            elif field_status == "attention":
                has_any_attention = True

            applicant_section["fields"].append(
                {
                    "field_name": field_name,
                    "label": field_label,
                    "expected_value": expected,
                    "extracted_value": extracted,
                    "status": field_status,
                    "source_pages": source_pages,
                }
            )

        person_profile["_computed_status"] = (
            "mismatch" if has_any_mismatch else ("attention" if has_any_attention else "match")
        )
        comparison_matrix["applicants"].append(applicant_section)

    # Deduplicate applicant and family members into relationship graph nodes.
    node_lookup: dict[str, RelationshipNode] = {}
    primary_person_profile = people.get("primary")
    if primary_person_profile:
        primary_name = primary_person_profile.get("applicant_name")
        primary_status = primary_person_profile.get("_computed_status", "match")
        node_lookup[primary_name.lower().strip()] = {
            "id": "p1",
            "name": primary_name,
            "role": "primary",
            "relation_to_primary": None,
            "status": primary_status,
        }

    coapplicant_index = 0
    family_member_index = 0
    for person_id, person_profile in sorted_people:
        person_name = person_profile.get("applicant_name")
        if not person_name:
            continue
        name_key = person_name.lower().strip()
        mapped_role = _mapped_role(person_profile.get("role"), person_id)
        relation = person_profile.get("relationship") or (
            None if mapped_role == "primary" else "co-applicant"
        )
        person_status = person_profile.get("_computed_status", "match")

        if name_key not in node_lookup:
            if mapped_role in ("co_applicant", "guarantor"):
                coapplicant_index += 1
                node_id = f"c{coapplicant_index}"
            else:
                family_member_index += 1
                node_id = f"f{family_member_index}"

            node_lookup[name_key] = {
                "id": node_id,
                "name": person_name,
                "role": mapped_role,
                "relation_to_primary": relation
                if relation and relation.lower() != "self"
                else None,
                "status": person_status,
            }
        else:
            if relation and relation.lower() != "self":
                node_lookup[name_key]["relation_to_primary"] = relation
            if person_status != "match":
                node_lookup[name_key]["status"] = person_status

        father = person_profile.get("father_name")
        if father and father.lower() != "none" and father.strip():
            father_key = father.lower().strip()
            if father_key not in node_lookup:
                family_member_index += 1
                node_lookup[father_key] = {
                    "id": f"f{family_member_index}",
                    "name": father,
                    "role": "family_member",
                    "relation_to_primary": (
                        "father"
                        if mapped_role == "primary"
                        else ("father-in-law" if relation == "WIFE" else "father")
                    ),
                    "status": "n/a",
                }
            elif mapped_role == "primary":
                node_lookup[father_key]["relation_to_primary"] = "father"

        mother = person_profile.get("mother_name")
        if mother and mother.lower() != "none" and mother.strip():
            mother_key = mother.lower().strip()
            if mother_key not in node_lookup:
                family_member_index += 1
                node_lookup[mother_key] = {
                    "id": f"f{family_member_index}",
                    "name": mother,
                    "role": "family_member",
                    "relation_to_primary": "mother" if mapped_role == "primary" else "mother",
                    "status": "n/a",
                }
            elif mapped_role == "primary":
                node_lookup[mother_key]["relation_to_primary"] = "mother"

    relationships = list(node_lookup.values())

    return {
        "comparison_matrix": comparison_matrix,
        "relationships": relationships,
    }
