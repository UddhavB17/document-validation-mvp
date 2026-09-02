"""Consistency-check submodule."""

from __future__ import annotations

import re
from collections import defaultdict

from services.consistency.constants import (
    ADDRESS_FIELDS,
    EXACT_FIELDS,
    HOLDER_NAME_FIELDS,
    LOAN_FIELDS,
    NAME_FIELDS,
    PERSON_FIELDS,
)
from services.consistency.matching import (
    _anomaly,
    _compact,
    _matches,
    _names_equivalent,
    _relationship_name_matches,
    _trusted_address_variants,
)
from services.consistency.observations import _observation_anchor_rank
from services.consistency.trusted import _name_matches_with_relatives
from services.person_names import (
    canonicalize_person_name,
    is_person_name_candidate,
)


def _cross_document_matches(
    observations: list[dict], people: dict[str, dict] | None = None
) -> list[dict]:
    anomalies: list[dict] = []
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    consistency_fields = PERSON_FIELDS | LOAN_FIELDS | NAME_FIELDS | ADDRESS_FIELDS
    for obs in observations:
        if obs["field"] in consistency_fields and not (
            obs["person_id"] == "unassigned" and obs["field"] in PERSON_FIELDS
        ):
            grouped[(obs["person_id"], obs["field"])].append(obs)
    for (person_id, field), values in grouped.items():
        person = (people or {}).get(person_id, {})
        values = sorted(
            values,
            key=lambda item: _observation_anchor_rank(item, field, person),
            reverse=True,
        )
        anchor = values[0]
        for other in values[1:]:
            if anchor["document_type"] == other["document_type"] or _matches(
                field, anchor["value"], other["value"]
            ):
                continue
            if (
                field in HOLDER_NAME_FIELDS
                and person
                and (
                    _name_matches_with_relatives(anchor["value"], person)
                    and _name_matches_with_relatives(other["value"], person)
                )
            ):
                continue
            address_variants = _trusted_address_variants(person)
            if (
                field in ADDRESS_FIELDS
                and address_variants
                and all(
                    any(_matches("address", variant, item["value"]) for variant in address_variants)
                    for item in (anchor, other)
                )
            ):
                continue
            anomalies.append(
                _anomaly(
                    f"CROSS_DOCUMENT_{field.upper()}_MISMATCH",
                    "HIGH" if field in NAME_FIELDS | EXACT_FIELDS else "MEDIUM",
                    f"{anchor['value']} ({anchor['document_type']})",
                    f"{other['value']} ({other['document_type']})",
                    other,
                    f"{field.replace('_', ' ').title()} is inconsistent across documents for {person_id}.",
                )
            )
            break
    return anomalies


def _aadhaar_address_checks(
    observations: list[dict], people: dict[str, dict] | None = None
) -> list[dict]:
    anomalies: list[dict] = []
    by_person: dict[str, list[dict]] = defaultdict(list)
    for obs in observations:
        if obs["field"] in ADDRESS_FIELDS:
            by_person[obs["person_id"]].append(obs)
    for person_id, values in by_person.items():
        if person_id == "unassigned":
            continue
        address_variants = _trusted_address_variants((people or {}).get(person_id, {}))
        aadhaar_values = [item for item in values if item["document_type"] == "Aadhaar"]
        aadhaar = max(
            aadhaar_values,
            key=lambda item: (
                int(
                    any(_matches("address", variant, item["value"]) for variant in address_variants)
                ),
                -int(
                    bool(
                        re.search(
                            r"unique\s+identification\s+authority|"
                            r"भारतीय\s+विशिष्ट\s+पहचान\s+प्राधिकरण",
                            str(item.get("value") or ""),
                            re.I,
                        )
                    )
                ),
                len(str(item.get("value") or "")),
            ),
            default=None,
        )
        if not aadhaar:
            continue
        for other in values:
            if other is aadhaar or _matches("address", aadhaar["value"], other["value"]):
                continue
            if address_variants and all(
                any(_matches("address", variant, item["value"]) for variant in address_variants)
                for item in (aadhaar, other)
            ):
                continue
            anomalies.append(
                _anomaly(
                    "AADHAAR_ADDRESS_MISMATCH",
                    "HIGH",
                    aadhaar["value"],
                    other["value"],
                    other,
                    f"Address does not match the Aadhaar address for {person_id}.",
                )
            )
    return anomalies


def _relationship_checks(observations: list[dict], people: dict[str, dict]) -> list[dict]:
    anomalies: list[dict] = []
    relations = [obs for obs in observations if obs["field"] == "relationship_qualifier"]
    related_names = {
        (obs["person_id"], obs["page_number"]): obs
        for obs in observations
        if obs["field"] == "related_person_name"
    }
    known_names = {person_id: person.get("applicant_name") for person_id, person in people.items()}
    primary_rel = next((item for item in relations if item["person_id"] == "primary"), None)
    primary_related = (
        related_names.get(("primary", primary_rel["page_number"])) if primary_rel else None
    )
    for relation in relations:
        related = related_names.get((relation["person_id"], relation["page_number"]))
        if not related:
            continue
        declared = str(people.get(relation["person_id"], {}).get("relationship") or "").lower()
        qualifier = str(relation["value"]).lower()
        person_name = known_names.get(relation["person_id"])
        consistent = True
        if declared == "father" and primary_related:
            consistent = _relationship_name_matches(primary_related["value"], person_name)
        elif declared == "mother" and primary_related:
            if qualifier in {"w/o", "wife of"}:
                consistent = _relationship_name_matches(primary_related["value"], related["value"])
            else:
                consistent = _relationship_name_matches(primary_related["value"], person_name)
        elif declared in {"son", "daughter"}:
            consistent = qualifier in {
                "s/o",
                "d/o",
                "son of",
                "daughter of",
            } and _relationship_name_matches(related["value"], known_names.get("primary"))
        elif declared == "wife":
            consistent = qualifier in {"w/o", "wife of"} and _relationship_name_matches(
                related["value"], known_names.get("primary")
            )
        if not consistent:
            anomalies.append(
                _anomaly(
                    "RELATIONSHIP_QUALIFIER_MISMATCH",
                    "HIGH",
                    declared,
                    relation["value"],
                    relation,
                    f"S/O, D/O, W/O or C/O evidence conflicts with the declared relationship for {relation['person_id']}.",
                )
            )
        if known_names and not any(
            _matches("applicant_name", name, related["value"])
            for name in known_names.values()
            if name
        ):
            # A parent/spouse need not be a borrower, so report this softly for review.
            # Do not flag the parent named on a father/mother co-applicant's own
            # Aadhaar: that person is a grandparent and need not be on the loan.
            if declared in {"wife", "husband", "son", "daughter"}:
                anomalies.append(
                    _anomaly(
                        "RELATIONSHIP_NAME_REVIEW",
                        "LOW",
                        "Declared family relationship",
                        related["value"],
                        related,
                        "Related person's name could not be linked to a named applicant/co-applicant; review the family chain.",
                    )
                )
    return anomalies


def _application_name_checks(pages: list[dict], people: dict[str, dict]) -> list[dict]:
    if not people:
        return []
    found: list[tuple[str, dict]] = []
    app_pages = [page for page in pages if page.get("document_type") == "Application Form"]
    if not app_pages:
        return []
    # Co-applicant names often appear on later form pages that sandwich-smoothing
    # has not yet retyped, so also scan nearby KYC/application-looking pages.
    search_pages = list(app_pages)
    app_nums = {int(p.get("page_number") or 0) for p in app_pages}
    for page in pages:
        pn = int(page.get("page_number") or 0)
        if pn and any(abs(pn - other) <= 8 for other in app_nums):
            search_pages.append(page)
    extraction_noise = False
    for page in app_pages:
        fields = page.get("extracted_fields") or {}
        if isinstance(fields, dict) and fields.get("_identity_extraction_reliable") is False:
            extraction_noise = True
            continue
        values = fields.get("applicant_names") or [fields.get("applicant_name")]
        for value in values:
            if not value:
                continue
            candidate = canonicalize_person_name(value)
            if candidate.valid and candidate.value:
                found.append((candidate.value, page))
            else:
                # A rejected candidate (label/address noise) means extraction
                # failed on this form, not that the name is absent from it.
                extraction_noise = True
    anomalies: list[dict] = []
    for person_id, person in people.items():
        expected = person.get("applicant_name")
        name_visible_in_text = (
            any(
                _compact(expected) in _compact(page.get("ocr_text"))
                or _names_equivalent(expected, page.get("ocr_text"))
                for page in search_pages
            )
            if expected
            else False
        )
        if (
            not expected
            or not is_person_name_candidate(expected)
            or name_visible_in_text
            or any(_matches("applicant_name", expected, value) for value, _ in found)
        ):
            continue
        if not found and extraction_noise:
            # Name candidates existed but were rejected as noise (or extraction
            # was marked unreliable): an extraction gap, not a mismatch.
            continue
        page = found[0][1] if found else app_pages[0]
        anomalies.append(
            {
                "rule_id": "APPLICATION_NAME_MISMATCH",
                "s_no": 1,
                "severity": "HIGH",
                "document_type": "Application Form",
                "expected_value": expected,
                "found_value": ", ".join(value for value, _ in found) or "Name not extracted",
                "page_number": page.get("page_number"),
                "person_id": person_id,
                "reason": "Applicant/co-applicant name or spelling is missing or inconsistent in the application form.",
            }
        )
    return anomalies
