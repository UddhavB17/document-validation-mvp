"""Shared validation for government identifier formats."""

from __future__ import annotations

import re
from typing import Any

# An Indian mobile number written with the 91 country code is 12 digits long
# and therefore matches naive 12-digit Aadhaar regexes.  Audited runs showed
# phone numbers such as ``919374200200`` being stored as Aadhaar numbers and
# then promoting form pages to the "Aadhaar" document type.
_PHONE_WITH_COUNTRY_CODE_RE = re.compile(r"^91[6-9]\d{9}$")


def plausible_aadhaar_digits(value: Any) -> str | None:
    """Return the 12-digit Aadhaar string, or None when clearly not an Aadhaar.

    Rejects values that are not 12 digits after cleanup and 12-digit values
    that are actually a mobile number with the 91 country prefix.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 12:
        return None
    if _PHONE_WITH_COUNTRY_CODE_RE.match(digits):
        return None
    return digits
