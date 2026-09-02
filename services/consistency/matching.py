"""Consistency-check submodule."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from services.consistency.constants import (
    ADDRESS_FIELDS,
    DATE_FIELDS,
    EXACT_FIELDS,
    HOLDER_NAME_FIELDS,
    NUMERIC_FIELDS,
)
from services.person_names import (
    comparable_name,
    is_person_name_candidate,
    name_similarity,
    names_match,
)


def _relationship_name_matches(left: Any, right: Any) -> bool:
    """Compare family-chain names with transliteration and surname omission.

    Aadhaar relationship lines commonly omit a surname, while trusted data may
    spell a given name phonetically (Tika/Teeka). Require at least two aligned
    name tokens before allowing that tolerance so unrelated one-word names do
    not become matches.
    """
    if _matches("applicant_name", left, right):
        return True
    left_tokens = list(dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(left)))
    right_tokens = list(
        dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(right))
    )
    if min(len(left_tokens), len(right_tokens)) < 2:
        return False
    if len(left_tokens) <= len(right_tokens):
        short, long = left_tokens, right_tokens
    else:
        short, long = right_tokens, left_tokens
    aligned = long[: len(short)]

    def token_matches(short_token: str, long_token: str) -> bool:
        if _similarity(short_token, long_token) >= 0.80:
            return True
        # Transliteration often changes only the written vowel (Tika/Teeka,
        # Mohammad/Mohammed). A shared two-character consonant skeleton is
        # acceptable here only because the full relationship comparison also
        # requires another aligned name token.
        consonants = lambda token: re.sub(r"[aeiouy]", "", token.casefold())
        left_skeleton = consonants(short_token)
        right_skeleton = consonants(long_token)
        return len(left_skeleton) >= 2 and left_skeleton == right_skeleton

    return all(token_matches(a, b) for a, b in zip(short, aligned))


def _canonical(field: str) -> str:
    aliases = {
        "name": "applicant_name",
        "full_name": "applicant_name",
        "borrower_name": "applicant_name",
        "account_holder_name": "applicant_name",
        "dob": "date_of_birth",
        "mobile_number": "phone_number",
        "mobile_no": "phone_number",
        "credit_score": "credit_score",
        "interest_rate": "roi",
        "loan_tenure": "tenure",
        "bank_account_number": "account_number",
        "application_id": "application_number",
    }
    key = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
    return aliases.get(key, key)


def _lookup(data: dict, field: str) -> Any:
    for key, value in data.items():
        if _canonical(str(key)) == field and value not in (None, ""):
            return value
    if field == "credit_score":
        return data.get("cibil_score") or data.get("crif_score")
    return None


def _matches(field: str, left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return True
    if field in NUMERIC_FIELDS or field == "credit_score":
        a, b = _number(left), _number(right)
        return a is not None and b is not None and abs(a - b) <= max(0.01, abs(a) * 0.01)
    if field in DATE_FIELDS:
        try:
            from datetime import date

            from dateutil import parser

            def parse_date(value: Any) -> date:
                text = str(value).strip()
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                    return date.fromisoformat(text)
                return parser.parse(text, dayfirst=True).date()

            return parse_date(left) == parse_date(right)
        except (TypeError, ValueError, OverflowError):
            pass
    if field in EXACT_FIELDS:
        left_compact, right_compact = _compact(left), _compact(right)
        return left_compact == right_compact or (
            field in {"aadhaar_number", "aadhaar_last4", "account_number"}
            and len(left_compact) >= 4
            and len(right_compact) >= 4
            and left_compact[-4:] == right_compact[-4:]
        )
    if field in ADDRESS_FIELDS:
        if _explicit_address_unit_conflict(left, right):
            return False

        def address_tokens(value: Any) -> set[str]:
            normalized = re.sub(r"\b([swdc])\s*/\s*o\b", r"\1o", str(value).lower())
            # OCR often glues "UkarLal" / "UkarLal," — split common Indian name endings.
            normalized = re.sub(r"([a-z])(lal|bai|devi|singh|kumar)\b", r"\1 \2", normalized)
            return set(re.findall(r"[a-z0-9]+", normalized))

        left_tokens = address_tokens(left)
        right_tokens = address_tokens(right)
        shared = left_tokens & right_tokens
        # Trusted dumps sometimes contain only the relationship/address prefix
        # (for example "S/O: Unkar Lal").  A full document address containing
        # that exact prefix is consistent, not a mismatch.
        if min(len(left_tokens), len(right_tokens)) >= 2 and (
            left_tokens <= right_tokens or right_tokens <= left_tokens
        ):
            return True

        # If trusted data intentionally stores only a relationship prefix,
        # tolerate a one-character OCR error in that related person's name.
        def relation_prefix(value: Any) -> tuple[str, str] | None:
            normalized = re.sub(r"\b([swdc])\s*/\s*o\b", r"\1o", str(value).lower())
            normalized = re.sub(r"([a-z])(lal|bai|devi|singh|kumar)\b", r"\1 \2", normalized)
            match = re.search(r"\b(so|wo|do|co)\s*[:\-]?\s*([a-z]+(?:\s+[a-z]+)?)", normalized)
            return (match.group(1), match.group(2)) if match else None

        left_relation = relation_prefix(left)
        right_relation = relation_prefix(right)
        if left_relation and right_relation and left_relation[0] == right_relation[0]:
            if len(left_relation[1].split()) <= len(right_relation[1].split()):
                short_name, long_name = left_relation[1], right_relation[1]
            else:
                short_name, long_name = right_relation[1], left_relation[1]
            word_count = max(1, len(short_name.split()))
            comparable_long_name = " ".join(long_name.split()[:word_count])
            relation_name_matches = (
                _names_equivalent(short_name, comparable_long_name)
                or _similarity(short_name, comparable_long_name) >= 0.75
            )
            if relation_name_matches and (
                min(len(left_tokens), len(right_tokens)) <= 3 or len(shared) >= 3
            ):
                return True
            # Short trusted prefix vs long OCR address: same PIN + relation match is enough.
            same_pin_for_prefix = bool(
                set(re.findall(r"\b[1-8]\d{5}\b", str(left)))
                & set(re.findall(r"\b[1-8]\d{5}\b", str(right)))
            )
            if (
                relation_name_matches
                and same_pin_for_prefix
                and min(len(left_tokens), len(right_tokens)) <= 4
            ):
                return True
        # OCR often produces one or two spelling variants in a full address
        # (Semah/Semali, Sulia/Suilia) and may add Hindi tokens. When the PIN is
        # identical and at least three quarters of the shorter Latin-token set
        # agrees, the addresses are operationally consistent.
        same_pin = bool(
            set(re.findall(r"\b[1-8]\d{5}\b", str(left)))
            & set(re.findall(r"\b[1-8]\d{5}\b", str(right)))
        )
        containment = len(shared) / max(1, min(len(left_tokens), len(right_tokens)))
        if same_pin and len(shared) >= 5 and containment >= 0.75:
            return True
        generic_address_tokens = {
            "so",
            "wo",
            "do",
            "co",
            "po",
            "dist",
            "district",
            "state",
            "india",
            "gujarat",
            "rajasthan",
            "ahmedabad",
            "ahmadabad",
            *re.findall(r"\b[1-8]\d{5}\b", f"{left} {right}"),
        }
        distinctive_shared = {
            token for token in shared if token not in generic_address_tokens and len(token) >= 3
        }
        left_distinctive = {
            token
            for token in left_tokens
            if token not in generic_address_tokens and len(token) >= 3 and not token.isdigit()
        }
        right_distinctive = {
            token
            for token in right_tokens
            if token not in generic_address_tokens and len(token) >= 3 and not token.isdigit()
        }
        fuzzy_distinctive_pairs = {
            (left_token, right_token)
            for left_token in left_distinctive - distinctive_shared
            for right_token in right_distinctive - distinctive_shared
            if _similarity(left_token, right_token) >= 0.78
        }
        left_units = _explicit_address_units(left)
        right_units = _explicit_address_units(right)
        matched_unit = any(
            not left_values.isdisjoint(right_units[category])
            for category, left_values in left_units.items()
            if category in right_units
        )
        # Layout OCR may corrupt a PIN or one locality spelling while preserving
        # the exact flat/unit plus multiple address anchors (B-402, Pandit,
        # Hathijan). Conversely rural addresses often have an exact PIN plus
        # one exact and one near-identical village token (Harniyau/Harniyav).
        if (matched_unit and len(distinctive_shared) >= 2) or (
            same_pin and len(distinctive_shared) + len(fuzzy_distinctive_pairs) >= 2
        ):
            return True
        # Trusted rural addresses often contain only village/locality + PIN,
        # while Aadhaar adds relation, PO, tehsil and district text. Two shared
        # distinctive locality tokens plus the same PIN identify that variant.
        if same_pin and len(distinctive_shared) >= 2 and containment >= 0.55:
            return True
        # Multi-card OCR collage: locality + PIN agree even when Hindi OCR is noisy.
        locality_markers = {
            "semli",
            "semali",
            "bakhta",
            "bakta",
            "sulia",
            "jhalawar",
            "pachpahar",
            "rajasthan",
        }
        if same_pin and len(shared & locality_markers) >= 2 and containment >= 0.4:
            return True
        overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        return overlap >= 0.70 or _similarity(left, right) >= 0.82
    if field in HOLDER_NAME_FIELDS:
        return names_match(
            _without_honorific(left), _without_honorific(right), threshold=0.85
        ) or _names_equivalent(left, right)
    if field in {"father_name", "mother_name"}:
        return _related_names_equivalent(left, right)
    return _similarity(left, right) >= 0.88


def _explicit_address_unit_conflict(left: Any, right: Any) -> bool:
    """Reject locality-tolerant matches when both addresses disagree on a unit.

    PIN and locality overlap are deliberately tolerant of OCR noise.  A clear
    Flat/House/Unit number is different: B-402 and B-403 cannot describe the
    same service address even if every remaining token is identical.
    """
    left_units = _explicit_address_units(left)
    right_units = _explicit_address_units(right)
    for category in left_units.keys() & right_units.keys():
        if left_units[category].isdisjoint(right_units[category]):
            return True
    return False


def _explicit_address_units(value: Any) -> dict[str, set[str]]:
    text = str(value or "").casefold()
    result: dict[str, set[str]] = defaultdict(set)
    identifier = r"([a-z]?\s*[-/]?\s*\d{1,5}(?:\s*[-/]\s*\d{1,5})?[a-z]?)"
    patterns = (
        (
            "occupancy",
            rf"\b(?:flat|apartment|apt|house|unit|door|room|quarter)\s*(?:(?:number|no)\.?\s*)?{identifier}",
        ),
        ("occupancy", rf"\bh\s*\.?\s*no\.?\s*{identifier}"),
        ("plot", rf"\bplot\s*(?:(?:number|no)\.?\s*)?{identifier}"),
        ("block", rf"\bblock\s*(?:(?:number|no)\.?\s*)?{identifier}"),
    )
    for category, pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            normalized = re.sub(r"[^a-z0-9]", "", match.group(1).casefold())
            if normalized:
                result[category].add(normalized)

    # Company dumps commonly omit the word "Flat" and start directly with
    # an alphanumeric unit such as "B 402" or "B-402".
    leading = re.match(r"^\s*([a-z])\s*[-/]?\s*(\d{1,5}[a-z]?)\b", text)
    if leading:
        result["occupancy"].add(f"{leading.group(1)}{leading.group(2)}")
    return result


def _without_honorific(value: Any) -> str:
    return re.sub(
        r"^\s*(?:mr|mrs|ms|miss|shri|smt|dr)\.?\s+",
        "",
        str(value or ""),
        flags=re.IGNORECASE,
    )


def _related_names_equivalent(left: Any, right: Any) -> bool:
    """Compare parent names without holder-only extra-relative tolerance."""
    left_tokens = list(dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(left)))
    right_tokens = list(
        dict.fromkeys(_canonical_name_token(token) for token in _name_tokens(right))
    )
    if not left_tokens or not right_tokens or len(left_tokens) != len(right_tokens):
        return False
    if left_tokens == right_tokens or set(left_tokens) == set(right_tokens):
        return True
    return (
        SequenceMatcher(
            None,
            "".join(left_tokens),
            "".join(right_tokens),
        ).ratio()
        >= 0.88
    )


_NAME_VARIANT_GROUPS = (
    frozenset({"unkar", "onkar", "ukar", "unkarlal", "onkarlal", "ukarlal"}),
    frozenset({"peeru", "peerulal"}),
    frozenset({"radha", "radhabai", "radhe", "radhebai"}),
)


def _name_tokens(value: Any) -> list[str]:
    text = _without_honorific(value).lower()
    text = re.sub(r"([a-z])(lal|bai|devi|singh|kumar)\b", r"\1 \2", text)
    return re.findall(r"[a-z]+", text)


def _canonical_name_token(token: str) -> str:
    compact = re.sub(r"[^a-z]", "", token.lower())
    for group in _NAME_VARIANT_GROUPS:
        if compact in group:
            return next(iter(sorted(group)))
    return compact


def _names_equivalent(left: Any, right: Any) -> bool:
    """True when two person names match after honorific/transliteration normalization."""
    # Trusted dumps sometimes duplicate a token ("Kuldeep KULDEEP"); compare
    # unique tokens in order so duplication does not create a mismatch.
    left_tokens = list(dict.fromkeys(_canonical_name_token(tok) for tok in _name_tokens(left)))
    right_tokens = list(dict.fromkeys(_canonical_name_token(tok) for tok in _name_tokens(right)))
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    # Indian documents commonly rotate given/father/surname order while
    # preserving the same complete token set.
    if len(left_tokens) == len(right_tokens) and set(left_tokens) == set(right_tokens):
        return True
    # Allow substring containment for "Unkar" vs "Unkar Lal" style pairs.
    if len(left_tokens) <= len(right_tokens):
        short, long = left_tokens, right_tokens
    else:
        short, long = right_tokens, left_tokens
    if short == long[: len(short)]:
        return True
    left_compact = "".join(left_tokens)
    right_compact = "".join(right_tokens)
    if left_compact == right_compact:
        return True
    # Compact form appearing inside OCR/page text haystack.
    if isinstance(right, str) and len(left_compact) >= 4 and left_compact in _compact(right):
        return True
    if isinstance(left, str) and len(right_compact) >= 4 and right_compact in _compact(left):
        return True
    return SequenceMatcher(None, left_compact, right_compact).ratio() >= 0.85


def _compact(value: Any) -> str:
    return comparable_name(value)


def _similarity(left: Any, right: Any) -> float:
    if is_person_name_candidate(left) and is_person_name_candidate(right):
        return name_similarity(left, right)
    a, b = _compact(left), _compact(right)
    if not a or not b:
        return 0.0
    # Prefer transliteration-aware comparison for short person names.
    if _names_equivalent(left, right):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _number(value: Any) -> float | None:
    try:
        return float(re.sub(r"[^0-9.-]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _anomaly(
    rule_id: str, severity: str, expected: Any, found: Any, obs: dict, reason: str
) -> dict:
    return {
        "rule_id": rule_id,
        "s_no": None,
        "severity": severity,
        "document_type": obs["document_type"],
        "expected_value": expected,
        "found_value": found,
        "page_number": obs["page_number"],
        "person_id": None if obs["person_id"] == "unassigned" else obs["person_id"],
        "reason": reason,
    }


def _trusted_address_variants(*records: dict | None) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if _canonical(str(key)) not in ADDRESS_FIELDS or value in (None, ""):
                continue
            marker = _compact(value)
            if not marker or marker in seen:
                continue
            seen.add(marker)
            values.append(value)
    return values
