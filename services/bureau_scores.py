"""Deterministic handling for credit-bureau no-score reports."""

from __future__ import annotations

import re


def has_explicit_no_score_evidence(text: str) -> bool:
    """Return True when a bureau report explicitly represents "no score".

    CIBIL renders insufficient credit history as score ``-1``. Some CRIF
    reports leave the score row empty when the account summary confirms that
    the subject has zero credit accounts. Both forms are canonicalized to the
    application's score value ``0``.
    """
    normalized = str(text or "").casefold()
    if not normalized:
        return False

    if re.search(
        r"\bscore\b[\s\S]{0,180}?(?<!\d)-1(?!\d)"
        r"[\s\S]{0,120}?\binsufficient\s+history\s+to\s+score\b",
        normalized,
    ):
        return True

    score_section_match = re.search(
        r"\bcrif\s+hm\s+score(?:\(s\))?\s*:?(.*?)\baccount\s+summary\b",
        normalized,
        re.DOTALL,
    )
    if score_section_match is None:
        return False

    score_section = score_section_match.group(1)
    if re.search(r"(?<!\d)0(?!\d)", score_section):
        return True
    if re.search(r"(?<![\d\-–])(?:[3-8]\d{2}|900)(?![\d\-–])", score_section):
        return False

    summary_match = re.search(
        r"\baccount\s+summary\b(.*?)(?:\bgroup\s+account\s+summary\b|\Z)",
        normalized,
        re.DOTALL,
    )
    if summary_match is None:
        return False
    account_count_match = re.search(
        r"\bnumber\s+of\s+accounts\b(.*)",
        summary_match.group(1),
        re.DOTALL,
    )
    if account_count_match is None:
        return False

    # In CRIF's flattened table, column headings occur between "Number of
    # Accounts" and the first data-row value. The first standalone number is
    # therefore the total account count.
    first_value = re.search(r"(?<!\d)(\d+)(?!\d)", account_count_match.group(1))
    return first_value is not None and int(first_value.group(1)) == 0
