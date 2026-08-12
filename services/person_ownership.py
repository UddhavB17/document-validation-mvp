"""Assign each loan-file page to the correct trusted person before comparisons.

Cross-person TRUSTED_* anomalies happen when co-applicant OCR (Unkar / Radha)
is compared against primary.  Ownership is resolved from identity evidence
(PAN, Aadhaar, bank account, phone, DOB, name) — not from a family tree.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from services.cersai import (
    ASSET_BASED as CERSAI_ASSET_BASED,
    DEBTOR_BASED as CERSAI_DEBTOR_BASED,
    UNKNOWN as CERSAI_UNKNOWN,
    report_search_type as detect_cersai_report_search_type,
    search_type as detect_cersai_search_type,
)
from services.identifiers import plausible_aadhaar_digits
from services.person_names import is_person_name_candidate, name_similarity
from services.validation_gates import (
    field_reliable_for_validation,
    has_labeled_aadhaar_value,
)

try:  # pragma: no cover - rapidfuzz is the preferred scorer
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    class fuzz:  # type: ignore[no-redef]
        @staticmethod
        def token_sort_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100

        @staticmethod
        def token_set_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100


LOAN_LEVEL_DOCUMENT_TYPES = frozenset(
    {
        "loan agreement",
        "facility agreement",
        "sanction letter",
        "stamp duty",
        "insurance consent",
        "insurance consent letter",
        "nach form",
        "cersai report",
        "legal report",
        "legal clearance report",
        "technical report",
        "technical clearance report",
        "valuation report",
        "property document",
        "property image",
        "no objection certificate",
        "noc",
        "divorce decree",
        "death certificate",
        "affidavit",
        "cam",
        "kfs",
        "key fact statement",
    }
)

# Must never silently default to primary when identity does not match.
PERSON_SCOPED_DOCUMENT_TYPES = frozenset(
    {
        "aadhaar",
        "pan",
        "pan card",
        "voter id",
        "driving license",
        "passport",
        "application form",
        "cibil report",
        "crif report",
        "bank statement",
        "passbook",
        "cheque",
        "salary slip",
        "income tax return",
        "form 97",
        "mnrega job card",
        "npr letter",
        "kyc card photo",
        "ration card photo",
        "insurance form",
        "life insurance form",
        "property insurance form",
    }
)

# These documents are containers for several people.  Their internal person
# rows must be resolved independently instead of assigning the whole document
# to whichever name happens to appear most often.
MULTI_PERSON_DOCUMENT_TYPES = frozenset({"application form", "cam"})

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "applicant_name": ("applicant_name", "borrower_name", "account_holder_name", "customer_name"),
    "date_of_birth": ("date_of_birth", "dob"),
    "pan_number": ("pan_number", "pan"),
    "aadhaar_number": ("aadhaar_number", "aadhaar_last4", "aadhaar", "aadhar"),
    "account_number": ("account_number", "bank_account_number", "bank_account_no", "account_no"),
    "phone_number": ("phone_number", "phone", "mobile_number"),
    "pin_code": ("pin_code", "pincode"),
    "address": ("address",),
}

FIELD_WEIGHTS = {
    "aadhaar_number": 8.0,
    "pan_number": 8.0,
    "account_number": 8.0,
    "phone_number": 5.0,
    "date_of_birth": 5.0,
    "applicant_name": 6.0,
    "pin_code": 2.0,
    "address": 1.0,
}

RELATIONSHIP_OWNER_WEIGHT = 4.0

STRONG_ID_FIELDS = frozenset(
    {"pan_number", "aadhaar_number", "account_number", "phone_number"}
)

_MASKED_AADHAAR_LAST4_RE = re.compile(
    r"\b(?:aadhaar|aadhar)(?:\s+(?:number|no\.?))?\s*[:#\-]?\s*"
    r"(?:[x*\u2022\u25cf]{2,4}[\s\-]*){1,3}(\d{4})\b",
    re.IGNORECASE,
)


def people_from_trusted(trusted: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = (trusted or {}).get("people") or (trusted or {}).get("reference_data") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def document_requires_person_owner(
    document_type: str,
    pages: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> bool:
    """Return whether this document must resolve to a trusted person."""
    type_key = str(document_type or "").strip().casefold()
    if type_key == "cersai report":
        return _cersai_search_type(_as_page_list(pages)) == CERSAI_DEBTOR_BASED
    return type_key in PERSON_SCOPED_DOCUMENT_TYPES


def document_is_loan_level(
    document_type: str,
    pages: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> bool:
    """Return whether ownership is loan/property-level rather than person-level."""
    type_key = str(document_type or "").strip().casefold()
    if type_key == "cersai report":
        return _cersai_search_type(_as_page_list(pages)) != CERSAI_DEBTOR_BASED
    return type_key in LOAN_LEVEL_DOCUMENT_TYPES


def _as_page_list(
    pages: list[dict[str, Any]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(pages, dict):
        return [pages]
    return [page for page in (pages or []) if isinstance(page, dict)]


def _cersai_search_type(pages: list[dict[str, Any]]) -> str:
    """Read subtype from extraction metadata first, then intrinsic OCR text."""
    return detect_cersai_report_search_type(pages)


def _cersai_debtor_identity_page(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one identity record containing only CERSAI search-subject fields."""
    combined_text = "\n".join(str(page.get("ocr_text") or "") for page in pages)
    extracted: dict[str, Any] = {}
    if combined_text.strip():
        # Lazy import avoids making the general extractor depend on ownership.
        from services.field_extractor import extract_fields

        extracted = extract_fields("CERSAI Report", combined_text)

    debtor_name = extracted.get("debtor_name")
    debtor_pan = extracted.get("debtor_pan_number")
    debtor_dob = extracted.get("debtor_date_of_birth")
    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            continue
        if detect_cersai_search_type(page.get("ocr_text"), fields) != CERSAI_DEBTOR_BASED:
            continue
        debtor_name = debtor_name or fields.get("debtor_name") or fields.get("applicant_name")
        debtor_pan = debtor_pan or fields.get("debtor_pan_number") or fields.get("pan_number")
        debtor_dob = (
            debtor_dob
            or fields.get("debtor_date_of_birth")
            or fields.get("date_of_birth")
            or fields.get("dob")
        )

    subject_fields = {
        "cersai_search_type": CERSAI_DEBTOR_BASED,
        "debtor_name": debtor_name,
        "debtor_pan_number": debtor_pan,
        "debtor_date_of_birth": debtor_dob,
        "applicant_name": debtor_name,
        "pan_number": debtor_pan,
        "date_of_birth": debtor_dob,
    }
    return {
        "document_type": "CERSAI Report",
        "ocr_text": "",
        "extracted_fields": subject_fields,
    }


def _resolve_cersai_debtor_owner(
    pages: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a debtor-based report by debtor PAN, then debtor identity."""
    subject_page = _cersai_debtor_identity_page(pages)
    observations = identity_observations([subject_page])
    observed_pans = {
        re.sub(r"\s+", "", str(value or "")).upper()
        for value in observations.get("pan_number") or []
        if re.fullmatch(
            r"[A-Z]{5}\d{4}[A-Z]",
            re.sub(r"\s+", "", str(value or "")).upper(),
        )
    }
    if observed_pans:
        pan_matches = {
            person_id
            for person_id, person in people.items()
            if re.sub(
                r"\s+",
                "",
                str(first_value(person, FIELD_ALIASES["pan_number"]) or ""),
            ).upper() in observed_pans
        }
        if len(pan_matches) == 1:
            return {
                "person_id": next(iter(pan_matches)),
                "confidence": 1.0,
                "evidence": ["cersai_debtor_pan_number", "pan_number"],
            }
        return {
            "person_id": None,
            "confidence": 0.0,
            "evidence": [
                "cersai_debtor_pan_ambiguous"
                if pan_matches
                else "cersai_debtor_pan_not_in_trusted_data"
            ],
        }

    identity = _score_people([subject_page], people)
    if identity.get("best_id"):
        return {
            "person_id": identity["best_id"],
            "confidence": identity["confidence"],
            "evidence": sorted(set([
                *(identity.get("evidence") or []),
                "cersai_debtor_identity",
            ])),
        }
    return {
        "person_id": None,
        "confidence": 0.0,
        "evidence": ["cersai_debtor_identity_unresolved"],
    }


def _cersai_document_groups(pages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group contiguous CERSAI pages so result pages inherit the debtor owner."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_source: str | None = None
    current_has_search = False

    for page in sorted(pages, key=lambda item: int(item.get("page_number") or 0)):
        if str(page.get("document_type") or "").strip().casefold() != "cersai report":
            if current:
                groups.append(current)
            current = []
            current_source = None
            current_has_search = False
            continue

        source = str(
            page.get("source_document_id")
            or page.get("document_instance_id")
            or page.get("report_id")
            or ""
        ).strip() or None
        fields = page.get("extracted_fields")
        fields = fields if isinstance(fields, dict) else {}
        page_has_search = bool(
            re.search(r"\bsearch\s+criteria\s+entered\b", str(page.get("ocr_text") or ""), re.I)
            or fields.get("debtor_name")
            or fields.get("debtor_pan_number")
        )
        source_changed = bool(current and current_source and source and current_source != source)
        starts_next_report = bool(current and current_has_search and page_has_search)
        if source_changed or starts_next_report:
            groups.append(current)
            current = []
            current_has_search = False

        current.append(page)
        current_source = source or current_source
        current_has_search = current_has_search or page_has_search

    if current:
        groups.append(current)
    return groups


def resolve_person_owner(
    pages: list[dict[str, Any]] | dict[str, Any],
    reference_data: dict[str, Any],
    document_type: str = "",
    *,
    provided_person_id: str | None = None,
    provided_person_is_document_scope: bool = False,
    source_filename: str | None = None,
) -> dict[str, Any]:
    """Score trusted people against extracted identity and pick a clear winner.

    Returns ``{"person_id", "confidence", "evidence"}``.  ``person_id`` is
    ``None`` when ownership cannot be established for a person-scoped doc.
    """
    page_list = [pages] if isinstance(pages, dict) else list(pages or [])
    people = {
        str(key): value
        for key, value in (reference_data or {}).items()
        if isinstance(value, dict)
    }
    type_key = str(document_type or "").strip().lower()
    if not type_key and page_list:
        type_key = str(page_list[0].get("document_type") or "").strip().lower()

    cersai_type = (
        _cersai_search_type(page_list)
        if type_key == "cersai report"
        else CERSAI_UNKNOWN
    )
    if cersai_type == CERSAI_ASSET_BASED:
        # An asset-based search is property-scoped. Any people printed in the
        # results are returned registry parties, not the report's applicant.
        return {
            "person_id": None,
            "confidence": 1.0,
            "evidence": ["cersai_asset_based"],
            "document_scope": "loan_level",
        }
    if not people:
        return {"person_id": None, "confidence": 0.0, "evidence": []}
    if cersai_type == CERSAI_DEBTOR_BASED:
        # A debtor-based result may list the other applicant/co-applicants in
        # its output. Ownership is determined only by the debtor entered in the
        # search criteria, with the debtor PAN taking precedence over names.
        return _resolve_cersai_debtor_owner(page_list, people)

    identity = _score_people(
        [] if type_key == "cersai report" else page_list,
        people,
    )
    provided = str(provided_person_id or "").strip() or None
    source_role = source_role_from_filename(
        source_filename
        or next(
            (
                str(page.get("source_filename") or "")
                for page in page_list
                if isinstance(page, dict) and page.get("source_filename")
            ),
            "",
        )
    )

    # A clean identity match is stronger than a folder/index hint. This also
    # makes a wrongly filed primary PAN recoverable without trusting the path.
    identity_winner = identity.get("best_id")
    if source_role and identity_winner and _identity_is_decisive(
        identity, str(identity_winner)
    ):
        evidence = list(identity.get("evidence") or [])
        if _trusted_role(str(identity_winner), people[str(identity_winner)]) != source_role:
            evidence.append(f"overrode_source_role:{source_role}")
        return {
            "person_id": identity_winner,
            "confidence": identity["confidence"],
            "evidence": sorted(set(evidence)),
            "source_role": source_role,
        }

    if source_role:
        role_candidates = [
            person_id
            for person_id, person in people.items()
            if _trusted_role(person_id, person) == source_role
        ]
        if not role_candidates:
            return {
                "person_id": None,
                "confidence": 0.0,
                "evidence": [
                    f"source_role:{source_role}",
                    "source_role_not_in_trusted_data",
                ],
                "source_role": source_role,
            }
        if len(role_candidates) == 1:
            role_person_id = role_candidates[0]
            return {
                "person_id": role_person_id,
                "confidence": 0.85,
                "evidence": [f"source_role:{source_role}"],
                "source_role": source_role,
            }
        if provided_person_is_document_scope and provided in role_candidates:
            # A continuation page commonly omits the subject name/ID.  The
            # surrounding physical document may already have been resolved
            # from its identity-bearing cover page.  Keep that group-level
            # owner instead of discarding it merely because several trusted
            # people share the same source-folder role.  A decisive full PAN
            # or labelled full Aadhaar still overrides above.
            return {
                "person_id": provided,
                "confidence": 0.9,
                "evidence": ["document_index", f"source_role:{source_role}"],
                "source_role": source_role,
            }
        if identity_winner in role_candidates:
            return {
                "person_id": identity_winner,
                "confidence": identity["confidence"],
                "evidence": sorted(set([*(identity.get("evidence") or []), f"source_role:{source_role}"])),
                "source_role": source_role,
            }
        return {
            "person_id": None,
            "confidence": 0.0,
            "evidence": [f"source_role:{source_role}", "source_role_ambiguous"],
            "source_role": source_role,
        }

    if provided and provided in people:
        if (
            type_key in PERSON_SCOPED_DOCUMENT_TYPES
            and not identity["scores"].get(provided)
            and not identity.get("best_id")
            and _observed_names_clearly_contradict(page_list, people[provided])
        ):
            # A manifest/index hint is not identity evidence.  Packets often
            # contain guarantors or relatives absent from the trusted people
            # list; a clean contradictory name must remain unassigned instead
            # of being compared with the hinted applicant.
            return {
                "person_id": None,
                "confidence": 0.0,
                "evidence": ["observed_name_contradicts_provided_mapping"],
            }
        if not _strong_id_contradicts(identity, provided, people):
            evidence = list(identity.get("evidence_by_person", {}).get(provided, []))
            evidence.append("provided_mapping")
            confidence = 0.7
            if identity["best_id"] == provided:
                confidence = max(confidence, float(identity["confidence"]))
            elif identity["scores"].get(provided, 0.0):
                confidence = max(confidence, 0.85)
            return {
                "person_id": provided,
                "confidence": round(min(1.0, confidence), 3),
                "evidence": sorted(set(evidence)),
            }
        # Strong ID points at someone else — prefer identity over bad mapping.
        if identity["best_id"]:
            return {
                "person_id": identity["best_id"],
                "confidence": identity["confidence"],
                "evidence": identity["evidence"] + ["overrode_provided_mapping"],
            }

    if identity["best_id"]:
        return {
            "person_id": identity["best_id"],
            "confidence": identity["confidence"],
            "evidence": identity["evidence"],
        }

    if len(people) == 1:
        only_id = next(iter(people))
        # A single-person manifest still contains other people's documents
        # (guarantors, family members).  When the page carries a clean name
        # that is clearly someone else and nothing else matched, refusing the
        # fallback keeps guarantor KYC out of the primary's comparisons.
        if (
            type_key in PERSON_SCOPED_DOCUMENT_TYPES
            and not identity["scores"].get(only_id)
            and (
                _observed_names_contradict(page_list, people[only_id])
                or _strong_observed_identity_conflicts(page_list, people[only_id])
            )
        ):
            return {
                "person_id": None,
                "confidence": 0.0,
                "evidence": ["observed_name_contradicts_manifest"],
            }
        return {"person_id": only_id, "confidence": 0.5, "evidence": ["single_person_manifest"]}

    # Person-scoped types must not silently fall back to primary.
    if type_key in PERSON_SCOPED_DOCUMENT_TYPES:
        return {"person_id": None, "confidence": 0.0, "evidence": []}

    if type_key in LOAN_LEVEL_DOCUMENT_TYPES and "primary" in people:
        return {"person_id": "primary", "confidence": 0.4, "evidence": ["loan_level_document"]}

    return {"person_id": None, "confidence": 0.0, "evidence": []}


def assign_page_owners(
    pages: list[dict[str, Any]],
    trusted: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Stamp ``person_id`` on each page using identity evidence.

    Mutates pages in place and returns them.  Person-scoped pages that cannot
    be owned become ``unassigned`` instead of defaulting to primary.
    """
    people = people_from_trusted(trusted)
    if not people:
        asset_pages = {
            id(page)
            for group in _cersai_document_groups(pages)
            if _cersai_search_type(group) == CERSAI_ASSET_BASED
            for page in group
        }
        for page in pages:
            if id(page) in asset_pages:
                page["person_id"] = None
                page["applicant_role"] = None
                fields = page.get("extracted_fields")
                fields = dict(fields) if isinstance(fields, dict) else {}
                fields["_ownership"] = {
                    "person_id": None,
                    "confidence": 1.0,
                    "evidence": ["cersai_asset_based"],
                    "cersai_search_type": CERSAI_ASSET_BASED,
                    "document_scope": "loan_level",
                }
                page["extracted_fields"] = fields
                continue
            if not page.get("person_id") and not page.get("applicant_role"):
                page["person_id"] = "unassigned"
        return pages

    cersai_group_owners: dict[int, dict[str, Any]] = {}
    cersai_group_types: dict[int, str] = {}
    for group in _cersai_document_groups(pages):
        group_type = _cersai_search_type(group)
        if group_type not in {CERSAI_DEBTOR_BASED, CERSAI_ASSET_BASED}:
            continue
        group_owner = resolve_person_owner(group, people, "CERSAI Report")
        for grouped_page in group:
            cersai_group_owners[id(grouped_page)] = group_owner
            cersai_group_types[id(grouped_page)] = group_type

    for page in pages:
        existing = str(page.get("person_id") or page.get("applicant_role") or "").strip()
        provided = existing if existing and existing not in {"unassigned", "unknown"} else None
        # Manifest/ZIP mapping may live on the page or in extraction metadata.
        fields = page.get("extracted_fields") if isinstance(page.get("extracted_fields"), dict) else {}
        ownership = fields.get("_ownership") if isinstance(fields, dict) else None
        provided_person_is_document_scope = bool(
            isinstance(ownership, dict)
            and str(ownership.get("person_id") or "").strip() == provided
            and ownership.get("document_scope") == "single_person"
            and "document_index" in set(ownership.get("evidence") or [])
        )
        mapped = fields.get("_mapped_extraction") if isinstance(fields, dict) else None
        if isinstance(mapped, dict) and mapped.get("person_id"):
            provided = str(mapped.get("person_id"))
        zip_cls = fields.get("_zip_source_classification") if isinstance(fields, dict) else None
        if isinstance(zip_cls, dict) and zip_cls.get("predicted_person_id"):
            provided = provided or str(zip_cls.get("predicted_person_id"))

        document_type = str(page.get("document_type") or "")
        if id(page) in cersai_group_owners:
            owner = dict(cersai_group_owners[id(page)])
        else:
            owner = resolve_person_owner(
                [page],
                people,
                document_type,
                provided_person_id=provided,
                provided_person_is_document_scope=provided_person_is_document_scope,
                source_filename=str(page.get("source_filename") or "") or None,
            )
        type_key = document_type.strip().lower()
        person_id = owner.get("person_id")
        cersai_group_type = cersai_group_types.get(id(page))
        is_asset_based_cersai = cersai_group_type == CERSAI_ASSET_BASED
        requires_person = (
            cersai_group_type == CERSAI_DEBTOR_BASED
            or document_requires_person_owner(document_type, [page])
        )

        if person_id is None and not is_asset_based_cersai:
            if requires_person or type_key in PERSON_SCOPED_DOCUMENT_TYPES or len(people) > 1:
                person_id = "unassigned"
            elif "primary" in people:
                person_id = "primary"
                owner = {
                    "person_id": person_id,
                    "confidence": 0.35,
                    "evidence": ["loan_level_document_default"],
                }
            else:
                person_id = "unassigned"

        page["person_id"] = person_id
        page["applicant_role"] = person_id
        ownership_meta = {
            "person_id": person_id,
            "confidence": owner.get("confidence", 0.0),
            "evidence": owner.get("evidence", []),
            "source_role": owner.get("source_role"),
        }
        if cersai_group_type:
            ownership_meta["cersai_search_type"] = cersai_group_type
        if owner.get("document_scope"):
            ownership_meta["document_scope"] = owner["document_scope"]
        if provided_person_is_document_scope:
            # Keep the provenance durable across the checklist's intentional
            # second ownership pass inside consistency checks.
            ownership_meta["document_scope"] = "single_person"
        if isinstance(fields, dict):
            fields = dict(fields)
            fields["_ownership"] = ownership_meta
            page["extracted_fields"] = fields
        else:
            page["extracted_fields"] = {"_ownership": ownership_meta}

    return pages


def source_role_from_filename(value: Any) -> str | None:
    """Return an applicant role from an explicit ZIP path segment.

    Segment matching is intentional: ``Co-Applicant`` must never be caught by
    a naive substring check for ``Applicant``.
    """
    segments = re.split(r"[/\\\\]+", str(value or ""))
    for segment in segments:
        key = re.sub(r"[^a-z0-9]+", "", segment.casefold())
        if key.startswith("coapplicant") or key.startswith("coborrower"):
            return "coapplicant"
        if key.startswith("guarantor"):
            return "guarantor"
        if key == "applicant" or key.startswith("primaryapplicant"):
            return "primary"
    return None


def _trusted_role(person_id: str, person: dict[str, Any]) -> str | None:
    raw = re.sub(
        r"[^a-z0-9]+",
        "",
        str(person.get("role") or person.get("applicant_role") or person_id).casefold(),
    )
    if person_id == "primary" or raw in {"primary", "applicant", "primaryapplicant"}:
        return "primary"
    if raw.startswith("coapplicant") or raw.startswith("coborrower"):
        return "coapplicant"
    if raw.startswith("guarantor"):
        return "guarantor"
    return None


def _identity_is_decisive(identity: dict[str, Any], person_id: str) -> bool:
    """Return True only for evidence strong enough to contradict a ZIP role.

    Folder roles are participant-level provenance.  Names, phones and Aadhaar
    last-four values are useful for choosing among candidates, but are too
    collision-prone to move a document from one participant role to another.
    A format-valid full PAN, a full Aadhaar printed next to an Aadhaar label,
    or a unique full bank-account number may override that source role.
    """
    return bool(
        identity.get("source_override_evidence_by_person", {}).get(person_id)
    )


def _strong_observed_identity_conflicts(
    pages: list[dict[str, Any]], person: dict[str, Any]
) -> bool:
    """Abstain when a nameless KYC page carries a different strong ID.

    A positively matching name still wins earlier and preserves genuine typo
    detection on an owned primary document.
    """
    observations = identity_observations(pages)
    for field in ("pan_number", "aadhaar_number"):
        expected = first_value(person, FIELD_ALIASES[field])
        found = observations.get(field) or []
        if expected not in (None, "") and found and not any(
            identity_matches(field, value, expected) for value in found
        ):
            return True
    return False


def ownership_anomalies_for_unassigned(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit LOW AUTO_OWNER_UNRESOLVED for person-scoped pages left unassigned."""
    anomalies: list[dict[str, Any]] = []
    for page in pages:
        person_id = str(page.get("person_id") or "")
        document_type = str(page.get("document_type") or "Unknown")
        if person_id != "unassigned":
            continue
        if not document_requires_person_owner(document_type, page):
            continue
        if (
            document_type.strip().casefold() == "bank statement"
            and not bank_statement_has_holder_evidence(page)
        ):
            # Checklist item 17 validates recent account history. A statement
            # that genuinely omits the holder name must not fail that rule via
            # an unrelated automatic-ownership warning.
            continue
        fields = page.get("extracted_fields") if isinstance(page.get("extracted_fields"), dict) else {}
        ownership = fields.get("_ownership") if isinstance(fields, dict) else {}
        if (
            isinstance(ownership, dict)
            and "source_role_not_in_trusted_data" in set(ownership.get("evidence") or [])
        ):
            # The automatic index emits a single role-level trusted-data scope
            # item; avoid an additional unresolved-owner warning per page.
            continue
        anomalies.append(
            {
                "rule_id": "AUTO_OWNER_UNRESOLVED",
                "s_no": None,
                "severity": "LOW",
                "document_type": document_type,
                "person_id": None,
                "matched_person_id": None,
                "field_name": None,
                "status": "MANUAL_REVIEW_REQUIRED",
                "expected_value": "Automatic person assignment",
                "found_value": None,
                "page_number": page.get("page_number"),
                "reason": (
                    "The document type was identified, but no applicant identity "
                    "matched trusted data."
                ),
            }
        )
    return anomalies


def bank_statement_has_holder_evidence(page: dict[str, Any]) -> bool:
    """Return whether a bank statement contains an actual holder-name candidate."""
    fields = page.get("extracted_fields")
    fields = fields if isinstance(fields, dict) else {}
    holder = first_value(fields, FIELD_ALIASES["applicant_name"])
    if holder not in (None, "") and is_person_name_candidate(holder):
        return True
    return any(
        is_person_name_candidate(candidate)
        for candidate in _banking_holder_name_observations(str(page.get("ocr_text") or ""))
    )


def name_matches_trusted_person(observed: Any, person: dict[str, Any]) -> bool:
    """True when an observed name identifies the trusted person.

    Tolerates duplicated tokens ("Kuldeep KULDEEP"), reordered tokens, and
    extra tokens that belong to the person's trusted father/mother name
    ("Anupkumar Chetanbhai Suthar" for applicant "Suthar Anupkumar" whose
    father is "Chetanbhai ... Suthar").
    """
    trusted_name = str(person.get("applicant_name") or "").strip()
    if not trusted_name or not observed:
        return False
    if name_similarity(observed, trusted_name) >= 0.85:
        return True
    observed_tokens = _unique_name_tokens(observed)
    trusted_tokens = _unique_name_tokens(trusted_name)
    if not observed_tokens or not trusted_tokens:
        return False
    if observed_tokens == trusted_tokens:
        return True
    if set(trusted_tokens) <= set(observed_tokens):
        relative_tokens = [
            token
            for field in ("father_name", "mother_name", "husband_name", "spouse_name")
            for token in _unique_name_tokens(person.get(field))
        ]
        extras = [token for token in observed_tokens if token not in set(trusted_tokens)]
        return bool(extras) and all(
            any(name_similarity(extra, relative) >= 0.75 for relative in relative_tokens)
            for extra in extras
        )
    return False


def _unique_name_tokens(value: Any) -> list[str]:
    tokens = re.findall(r"[a-z]+", str(value or "").casefold())
    honorifics = {"mr", "mrs", "ms", "miss", "shri", "smt", "sri", "dr"}
    return list(dict.fromkeys(token for token in tokens if token not in honorifics))


def _observed_names_contradict(
    pages: list[dict[str, Any]],
    person: dict[str, Any],
) -> bool:
    """True when every clean observed name points away from *person*."""
    observed = identity_observations(pages).get("applicant_name") or []
    clean = [
        value
        for value in observed
        if is_person_name_candidate(value) and len(str(value).split()) <= 6
    ]
    if not clean:
        return False
    return not any(name_matches_trusted_person(value, person) for value in clean)


def _observed_names_clearly_contradict(
    pages: list[dict[str, Any]],
    person: dict[str, Any],
) -> bool:
    """Require a wide name gap before rejecting an explicit mapping hint."""
    expected = first_value(person, FIELD_ALIASES["applicant_name"])
    if not expected:
        return False
    observed = identity_observations(pages).get("applicant_name") or []
    clean = [value for value in observed if is_person_name_candidate(value)]
    return bool(clean) and all(
        not name_matches_trusted_person(value, person)
        and name_similarity(value, expected) < 0.60
        for value in clean
    )


def _score_people(
    pages: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    observations = identity_observations(pages)
    source_override_evidence = _source_override_evidence(pages, people)
    scores: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {person_id: [] for person_id in people}
    for person_id, trusted in people.items():
        for field, found_values in observations.items():
            expected = first_value(trusted, FIELD_ALIASES[field])
            if expected in (None, ""):
                continue
            if field == "applicant_name":
                matched = any(
                    name_matches_trusted_person(found, trusted)
                    or identity_matches(field, found, expected)
                    for found in found_values
                )
            else:
                matched = any(
                    identity_matches(field, found, expected)
                    for found in found_values
                )
            if matched:
                scores[person_id] += FIELD_WEIGHTS[field]
                evidence[person_id].append(field)

    # Relationship prefixes identify the holder only through an explicit
    # inverse relationship in trusted data.  For example, W/O <known person>
    # may resolve the unique person whose trusted address/husband metadata says
    # the same thing.  The referenced spouse is never treated as the holder.
    for qualifier, related_text in relationship_observations(pages):
        candidates = _relationship_owner_candidates(
            qualifier,
            related_text,
            people,
        )
        if len(candidates) != 1:
            continue
        owner_id, referenced_id = candidates[0]
        scores[owner_id] += RELATIONSHIP_OWNER_WEIGHT
        evidence[owner_id].append(
            f"relationship:{qualifier.lower()}:{referenced_id or 'trusted_relation'}"
        )

    ranked = scores.most_common()
    if ranked:
        best_id, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score > second_score:
            confidence = min(1.0, 0.45 + (best_score / 12.0))
            return {
                "best_id": best_id,
                "confidence": round(confidence, 3),
                "evidence": sorted(set(evidence[best_id])),
                "scores": dict(scores),
                "evidence_by_person": evidence,
                "source_override_evidence_by_person": source_override_evidence,
            }
    return {
        "best_id": None,
        "confidence": 0.0,
        "evidence": [],
        "scores": dict(scores),
        "evidence_by_person": evidence,
        "source_override_evidence_by_person": source_override_evidence,
    }


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
        account_identity_document = (
            str(page.get("document_type") or "").strip().casefold()
            in {"bank statement", "passbook", "cheque"}
        )

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
            match.group(0)
            for match in re.finditer(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", ocr_text.upper())
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
            trusted_digits = _digits(str(
                first_value(trusted, FIELD_ALIASES["account_number"]) or ""
            ))
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
            expected_account = _digits(str(
                first_value(trusted, FIELD_ALIASES["account_number"]) or ""
            ))
            if (
                expected_account in valid_accounts
                and trusted_account_owners.get(expected_account) == [person_id]
            ):
                evidence[person_id].add("full_account_number")
    return {
        person_id: sorted(values)
        for person_id, values in evidence.items()
    }


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
                    for field in ("address", "current_address", "permanent_address", "communication_address")
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


def _relation_name_matches(observed: Any, expected: Any) -> bool:
    observed_tokens = re.findall(r"[a-z]+", str(observed or "").casefold())
    expected_tokens = re.findall(r"[a-z]+", str(expected or "").casefold())
    if not observed_tokens or not expected_tokens:
        return False
    width = len(expected_tokens)
    return any(
        name_similarity(" ".join(observed_tokens[index:index + width]), " ".join(expected_tokens)) >= 0.85
        for index in range(0, max(1, len(observed_tokens) - width + 1))
    )


def _strong_id_contradicts(
    identity: dict[str, Any],
    provided: str,
    people: dict[str, dict[str, Any]],
) -> bool:
    """True when exact PAN/Aadhaar/phone evidence belongs to a different person."""
    best_id = identity.get("best_id")
    if not best_id or best_id == provided:
        return False
    evidence = set(identity.get("evidence_by_person", {}).get(best_id, []))
    if not evidence.intersection(STRONG_ID_FIELDS):
        return False
    provided_score = float(identity.get("scores", {}).get(provided, 0.0))
    best_score = float(identity.get("scores", {}).get(best_id, 0.0))
    return best_score > provided_score


def identity_observations(pages: list[dict[str, Any]]) -> dict[str, list[Any]]:
    observations: dict[str, list[Any]] = {field: [] for field in FIELD_ALIASES}
    for page in pages:
        fields = page.get("extracted_fields")
        if not isinstance(fields, dict):
            # Allow passing a bare fields dict as a synthetic page.
            if isinstance(page, dict) and any(key in page for key in ("applicant_name", "pan_number", "dob")):
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
                if (
                    plausible_aadhaar_digits(value)
                    and has_labeled_aadhaar_value(ocr_text, value)
                ):
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
                if (
                    plausible_aadhaar_digits(match.group(1))
                    and has_labeled_aadhaar_value(ocr_text, match.group(1))
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
            if re.match(r"^(?:[wsdcf]\s*/?\s*o|wife\s+of|son\s+of|daughter\s+of|care\s+of)\b", candidate, re.I):
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
        for candidate in [match.group(1), *lines[index + 1:index + 4]]:
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


def first_value(values: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = values.get(alias)
        if value not in (None, ""):
            return value
    return None


def identity_matches(field: str, found: Any, expected: Any) -> bool:
    left = str(found or "").strip()
    right = str(expected or "").strip()
    if not left or not right:
        return False
    if field == "applicant_name":
        left_tokens = re.findall(r"[a-z0-9]+", left.lower())
        right_tokens = re.findall(r"[a-z0-9]+", right.lower())
        is_haystack = len(left_tokens) >= max(4, len(right_tokens) + 2)
        if not is_haystack and (not is_person_name_candidate(left) or not is_person_name_candidate(right)):
            return False
        if not is_haystack and name_similarity(left, right) >= 0.85:
            return True
        # OCR haystack (passbook/statement pages) — look for the trusted name inside.
        if len(left_tokens) >= max(4, len(right_tokens) + 2) and right_tokens:
            compact_right = "".join(right_tokens)
            compact_left = "".join(left_tokens)
            if len(compact_right) >= 4 and compact_right in compact_left:
                return True
            if len(right_tokens) >= 2:
                pattern = r"\b" + r"\s+".join(re.escape(tok) for tok in right_tokens) + r"\b"
                if re.search(pattern, left.lower()):
                    return True
        return False
    if field == "address":
        return fuzz.token_set_ratio(_words(left), _words(right)) >= 75
    if field == "date_of_birth":
        return _date_key(left) == _date_key(right)
    if field in {"aadhaar_number", "phone_number", "pin_code"}:
        left_digits = _digits(left)
        right_digits = _digits(right)
        if field == "aadhaar_number" and len(left_digits) >= 4 and len(right_digits) >= 4:
            return left_digits[-4:] == right_digits[-4:]
        return left_digits == right_digits and bool(left_digits)
    if field == "pan_number":
        return re.sub(r"\s+", "", left).upper() == re.sub(r"\s+", "", right).upper()
    if field == "account_number":
        left_digits = _digits(left)
        right_digits = _digits(right)
        # Masked suffixes are useful for field review but are not unique enough
        # to establish person ownership.
        return (
            len(left_digits) >= 8
            and len(right_digits) >= 8
            and left_digits == right_digits
        )
    return _words(left) == _words(right)


def _words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _date_key(value: str) -> str:
    normalized = str(value or "").strip()
    for format_string in (
        "%d-%B-%Y",
        "%d-%b-%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(normalized, format_string).date().isoformat()
        except ValueError:
            continue
    return _words(normalized).replace(" ", "")
