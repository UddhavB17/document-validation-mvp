"""Consistency-check submodule."""

from __future__ import annotations

import logging

from services.consistency.affidavit import _identity_affidavit_checks
from services.consistency.bureau import _bureau_checks
from services.consistency.cross_document import (
    _aadhaar_address_checks,
    _application_name_checks,
    _cross_document_matches,
    _relationship_checks,
)
from services.consistency.language import _application_language_checks
from services.consistency.observations import _observations, _people
from services.consistency.trusted import _trusted_matches

logger = logging.getLogger(__name__)


def run_consistency_checks(pages: list[dict], trusted: dict) -> list[dict]:
    anomalies: list[dict] = []
    people = _people(trusted)
    # Ensure pages carry person_id even when callers skip checklist assign.
    try:
        from services.person_ownership import assign_page_owners

        assign_page_owners(pages, {"people": people, **(trusted or {})})
    except (ImportError, TypeError, ValueError, KeyError, AttributeError) as exc:
        # Ownership assignment is best-effort here so consistency checks still run.
        # Unexpected failures remain visible in logs instead of being silent.
        logger.warning(
            "assign_page_owners failed before consistency checks; continuing without person stamps: %s",
            exc,
        )
    observations = _observations(pages, people)

    anomalies.extend(_trusted_matches(observations, people, trusted))
    anomalies.extend(_application_name_checks(pages, people))
    anomalies.extend(_cross_document_matches(observations, people))
    anomalies.extend(_aadhaar_address_checks(observations, people))
    anomalies.extend(_relationship_checks(observations, people))
    anomalies.extend(_bureau_checks(pages, observations))
    anomalies.extend(_application_language_checks(pages, trusted))
    from services.repayment_schedule import validate_repayment_schedules

    anomalies.extend(validate_repayment_schedules(pages, trusted))
    anomalies.extend(_identity_affidavit_checks(pages, anomalies, people))
    return anomalies
