"""Person ownership resolution — compatibility facade."""

from services.ownership.constants import (
    FIELD_ALIASES,
    FIELD_WEIGHTS,
    LOAN_LEVEL_DOCUMENT_TYPES,
    MULTI_PERSON_DOCUMENT_TYPES,
    PERSON_SCOPED_DOCUMENT_TYPES,
    RELATIONSHIP_OWNER_WEIGHT,
    STRONG_ID_FIELDS,
)
from services.ownership.document_policy import (
    bank_statement_has_holder_evidence,
    document_is_loan_level,
    document_requires_person_owner,
    people_from_trusted,
)
from services.ownership.assignment import assign_page_owners, ownership_anomalies_for_unassigned, source_role_from_filename
from services.ownership._helpers import first_value
from services.ownership.matching import identity_matches, name_matches_trusted_person
from services.ownership.observations import identity_observations, relationship_observations
from services.ownership.resolution import resolve_person_owner

__all__ = [
    "FIELD_ALIASES",
    "FIELD_WEIGHTS",
    "LOAN_LEVEL_DOCUMENT_TYPES",
    "MULTI_PERSON_DOCUMENT_TYPES",
    "PERSON_SCOPED_DOCUMENT_TYPES",
    "RELATIONSHIP_OWNER_WEIGHT",
    "STRONG_ID_FIELDS",
    "assign_page_owners",
    "bank_statement_has_holder_evidence",
    "document_is_loan_level",
    "document_requires_person_owner",
    "first_value",
    "identity_matches",
    "identity_observations",
    "name_matches_trusted_person",
    "ownership_anomalies_for_unassigned",
    "people_from_trusted",
    "relationship_observations",
    "resolve_person_owner",
    "source_role_from_filename",
]
