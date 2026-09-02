"""Person-ownership submodule."""

from __future__ import annotations

from typing import Any

from services.cersai import (
    ASSET_BASED as CERSAI_ASSET_BASED,
)
from services.cersai import (
    DEBTOR_BASED as CERSAI_DEBTOR_BASED,
)
from services.cersai import (
    UNKNOWN as CERSAI_UNKNOWN,
)
from services.ownership.cersai import _cersai_search_type, _resolve_cersai_debtor_owner
from services.ownership.constants import (
    LOAN_LEVEL_DOCUMENT_TYPES,
    PERSON_SCOPED_DOCUMENT_TYPES,
)
from services.ownership.matching import (
    _identity_is_decisive,
    _observed_names_clearly_contradict,
    _observed_names_contradict,
    _score_people,
    _strong_id_contradicts,
    _strong_observed_identity_conflicts,
    _trusted_role,
)


def _source_role_from_filename(*args, **kwargs):
    from services.ownership.assignment import source_role_from_filename

    return source_role_from_filename(*args, **kwargs)


def _lazy_filename_person_name_owner(*args, **kwargs):
    from services.ownership.assignment import _filename_person_name_owner

    return _filename_person_name_owner(*args, **kwargs)


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
        str(key): value for key, value in (reference_data or {}).items() if isinstance(value, dict)
    }
    type_key = str(document_type or "").strip().lower()
    if not type_key and page_list:
        type_key = str(page_list[0].get("document_type") or "").strip().lower()

    cersai_type = _cersai_search_type(page_list) if type_key == "cersai report" else CERSAI_UNKNOWN
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
    resolved_source_filename = source_filename or next(
        (
            str(page.get("source_filename") or "")
            for page in page_list
            if isinstance(page, dict) and page.get("source_filename")
        ),
        "",
    )
    source_role = _source_role_from_filename(resolved_source_filename)
    filename_owner = (
        _lazy_filename_person_name_owner(resolved_source_filename, people)
        if type_key in PERSON_SCOPED_DOCUMENT_TYPES
        else None
    )

    # A clean identity match is stronger than a folder/index hint. This also
    # makes a wrongly filed primary PAN recoverable without trusting the path.
    identity_winner = identity.get("best_id")
    if source_role and identity_winner and _identity_is_decisive(identity, str(identity_winner)):
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
                "evidence": sorted(
                    set([*(identity.get("evidence") or []), f"source_role:{source_role}"])
                ),
                "source_role": source_role,
            }
        if filename_owner in role_candidates:
            return {
                "person_id": filename_owner,
                "confidence": 0.9,
                "evidence": ["source_filename_name", f"source_role:{source_role}"],
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
            and not provided_person_is_document_scope
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

    if filename_owner:
        return {
            "person_id": filename_owner,
            "confidence": 0.9,
            "evidence": ["source_filename_name"],
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
