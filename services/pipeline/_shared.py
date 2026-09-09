"""Shared pipeline constants."""

from __future__ import annotations

import re

DOCUMENT_TYPE_ALIASES = {
    "PAN Card": "PAN",
    "None": "Unknown",
}

_NO_PAGE_INHERITANCE_TYPES = {
    "PAN",
    "PAN Card",
    "Driving License",
    "Cheque",
    "KYC OSV Mark",
}

_ONE_PAGE_INHERITANCE_TYPES = {"Aadhaar", "Voter ID"}

_NO_SANDWICH_SMOOTHING_TYPES = _NO_PAGE_INHERITANCE_TYPES | _ONE_PAGE_INHERITANCE_TYPES

_MID_CONFIDENCE_BOUNDARY = 0.55

_MULTI_PAGE_RUN_FILL_TYPES = {
    "Bank Statement",
    "CIBIL Report",
    "CRIF Report",
    "Application Form",
    "Loan Agreement",
    "Facility Agreement",
    "Passbook",
}

_INTRINSIC_IDENTITY_TYPES = frozenset(
    {
        "Aadhaar",
        "PAN",
        "PAN Card",
        "Voter ID",
        "Driving License",
        "Passport",
        "Ration Card",
    }
)

# Identity-document types inferred from ZIP member filenames must be supported
# by page content when the page carries substantial text.
_FILENAME_IDENTITY_TYPE_ANCHORS: dict[str, tuple[str, ...]] = {
    "PAN Card": ("permanent account number", "income tax", "पैन"),
    "Aadhaar": ("aadhaar", "aadhar", "uidai", "आधार"),
    "Driving License": (
        "driving licence",
        "driving license",
        "transport department",
        "motor vehicle",
        "ड्राइविंग",
    ),
    "Voter ID": ("election commission", "voter", "epic", "मतदाता"),
    "Passport": ("passport", "पासपोर्ट"),
}

_EMAIL_ADDRESS_RE = re.compile(r"[\w.+-]+@[\w-]+\.\w+")

_EMAIL_INFERRED_EVIDENCE_TYPES = frozenset(
    {
        "Cheque",
        "PDC",
        "Insurance Form",
        "Life Insurance Form",
        "Property Insurance Form",
        "Insurance Consent Letter",
    }
)
