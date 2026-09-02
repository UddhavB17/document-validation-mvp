"""Document-type and scoring constants for ownership resolution."""

from __future__ import annotations

import re

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

STRONG_ID_FIELDS = frozenset({"pan_number", "aadhaar_number", "account_number", "phone_number"})

_MASKED_AADHAAR_LAST4_RE = re.compile(
    r"\b(?:aadhaar|aadhar)(?:\s+(?:number|no\.?))?\s*[:#\-]?\s*"
    r"(?:[x*\u2022\u25cf]{2,4}[\s\-]*){1,3}(\d{4})\b",
    re.IGNORECASE,
)
