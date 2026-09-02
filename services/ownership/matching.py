"""Person-ownership submodule."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from services.ownership._fuzzy import fuzz
from services.ownership._helpers import _date_key, _digits, _words, first_value
from services.ownership.constants import (
    FIELD_ALIASES,
    FIELD_WEIGHTS,
    RELATIONSHIP_OWNER_WEIGHT,
    STRONG_ID_FIELDS,
)
from services.person_names import is_person_name_candidate, name_similarity


def _lazy_identity_observations(pages):
    from services.ownership.observations import identity_observations

    return identity_observations(pages)


def _lazy_relationship_observations(pages):
    from services.ownership.observations import relationship_observations

    return relationship_observations(pages)


def _lazy_source_override_evidence(pages, people):
    from services.ownership.observations import _source_override_evidence

    return _source_override_evidence(pages, people)


def _lazy_relationship_owner_candidates(*args, **kwargs):
    from services.ownership.observations import _relationship_owner_candidates

    return _relationship_owner_candidates(*args, **kwargs)


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
    return bool(identity.get("source_override_evidence_by_person", {}).get(person_id))


def _strong_observed_identity_conflicts(
    pages: list[dict[str, Any]], person: dict[str, Any]
) -> bool:
    """Abstain when a nameless KYC page carries a different strong ID.

    A positively matching name still wins earlier and preserves genuine typo
    detection on an owned primary document.
    """
    observations = _lazy_identity_observations(pages)
    for field in ("pan_number", "aadhaar_number"):
        expected = first_value(person, FIELD_ALIASES[field])
        found = observations.get(field) or []
        if (
            expected not in (None, "")
            and found
            and not any(identity_matches(field, value, expected) for value in found)
        ):
            return True
    return False


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
    observed = _lazy_identity_observations(pages).get("applicant_name") or []
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
    observed = _lazy_identity_observations(pages).get("applicant_name") or []
    clean = [value for value in observed if is_person_name_candidate(value)]
    return bool(clean) and all(
        not name_matches_trusted_person(value, person) and name_similarity(value, expected) < 0.60
        for value in clean
    )


def _score_people(
    pages: list[dict[str, Any]],
    people: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    observations = _lazy_identity_observations(pages)
    source_override_evidence = _lazy_source_override_evidence(pages, people)
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
                matched = any(identity_matches(field, found, expected) for found in found_values)
            if matched:
                scores[person_id] += FIELD_WEIGHTS[field]
                evidence[person_id].append(field)

    # Relationship prefixes identify the holder only through an explicit
    # inverse relationship in trusted data.  For example, W/O <known person>
    # may resolve the unique person whose trusted address/husband metadata says
    # the same thing.  The referenced spouse is never treated as the holder.
    for qualifier, related_text in _lazy_relationship_observations(pages):
        candidates = _lazy_relationship_owner_candidates(
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


def identity_matches(field: str, found: Any, expected: Any) -> bool:
    left = str(found or "").strip()
    right = str(expected or "").strip()
    if not left or not right:
        return False
    if field == "applicant_name":
        left_tokens = re.findall(r"[a-z0-9]+", left.lower())
        right_tokens = re.findall(r"[a-z0-9]+", right.lower())
        is_haystack = len(left_tokens) >= max(4, len(right_tokens) + 2)
        if not is_haystack and (
            not is_person_name_candidate(left) or not is_person_name_candidate(right)
        ):
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
        return len(left_digits) >= 8 and len(right_digits) >= 8 and left_digits == right_digits
    return _words(left) == _words(right)
