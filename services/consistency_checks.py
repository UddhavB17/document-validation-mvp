"""Cross-document and trusted-data consistency checks — compatibility facade."""

from services.consistency.constants import (
    ADDRESS_FIELDS,
    DATE_FIELDS,
    EXACT_FIELDS,
    HOLDER_NAME_FIELDS,
    LOAN_FIELDS,
    NAME_FIELDS,
    NUMERIC_FIELDS,
    PERSON_FIELDS,
)
from services.consistency.matching import _canonical, _matches, _names_equivalent
from services.consistency.observations import _observations, _people
from services.consistency.runner import run_consistency_checks

__all__ = [
    "ADDRESS_FIELDS",
    "DATE_FIELDS",
    "EXACT_FIELDS",
    "HOLDER_NAME_FIELDS",
    "LOAN_FIELDS",
    "NAME_FIELDS",
    "NUMERIC_FIELDS",
    "PERSON_FIELDS",
    "run_consistency_checks",
    "_canonical",
    "_matches",
    "_names_equivalent",
    "_observations",
    "_people",
]
