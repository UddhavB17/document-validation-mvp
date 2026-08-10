"""Deterministic, registry-driven document page classifier.

The classifier intentionally stays rule/heuristic based.  It loads document
type signal rules from ``data/document_type_registry.json`` and scores each
candidate using the same mechanism: heading phrases, keyword groups, regex
field patterns, and optional required signals.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

try:  # pragma: no cover - exercised when rapidfuzz is installed
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - tiny fallback for lean test envs
    fuzz = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "data" / "document_type_registry.json"
UNKNOWN_TYPE = "None"
DEFAULT_MIN_CONFIDENCE = 0.50
HIGH_CONFIDENCE = 0.75

OCRRoute = Literal["fast", "structured"]

# Application forms and CAMs contain bilingual KYC tables that enumerate every
# accepted identity document ("AADHAAR / PAN / VOTER ID / DRIVING LICENCE /
# RATION CARD").  A real identity card never lists several other card types,
# so those pages must not be classified as the cards they merely mention.
IDENTITY_CARD_TYPES = frozenset({
    "Aadhaar", "PAN", "PAN Card", "Voter ID", "Driving License", "Passport",
    "Ration Card",
})
_ID_DOC_MENTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baadhaa?r\b|आधार", re.IGNORECASE),
    re.compile(r"\bpan\b|पैन", re.IGNORECASE),
    re.compile(r"\bvoter\b|मतदाता", re.IGNORECASE),
    re.compile(r"driving\s*licen[cs]e|ड्राइविंग", re.IGNORECASE),
    re.compile(r"ration\s*card|राशन", re.IGNORECASE),
    re.compile(r"\bpassport\b|पासपोर्ट", re.IGNORECASE),
)

_INSURANCE_APPLICATION_FIELD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bproposer(?:'s)?\b", re.IGNORECASE),
    re.compile(r"\bnominee\b", re.IGNORECASE),
    re.compile(r"\bpolicy\b", re.IGNORECASE),
    re.compile(r"\bsum\s+(?:insured|assured)\b", re.IGNORECASE),
    re.compile(r"\bpremium\b", re.IGNORECASE),
)

_INSURER_LEGAL_MARKER = re.compile(
    r"(?:\bunderwri(?:tt?en|sen)\s+by\b[\s\S]{0,100}?\binsurance\b|"
    r"\b[A-Z][A-Za-z0-9&.,'() /-]{1,80}\s+insurance\s+"
    r"(?:(?:company|co\.?)\s+)?(?:limited|ltd\.?)\b|"
    r"\birdai\s+(?:registration|reg\.?)\s*(?:number|no\.?)\b|"
    r"\binsurance\s+regulatory\s+and\s+development\s+authority\b)",
    re.IGNORECASE,
)

_INSURANCE_FORM_BOUNDARY = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(?:health|life|general|property|group|credit|personal\s+accident)\s+insurance\s+"
    r"(?:proposal|application)\s+form|"
    r"insurance\s+(?:proposal|application)\s+form|"
    r"proposal\s+form(?:\s+for\s+(?:insurance|policy|cover))?|"
    r"application\s+form[^\n]{0,100}\b(?:scheme|insurance|policy|cover|group\s+care)\b|"
    r"(?:group\s+care|insurance|policy|cover)[^\n]{0,100}\bapplication\s+form\b"
    r")",
    re.IGNORECASE,
)

_INSURANCE_IDENTIFIER_VALUE = r"([A-Z0-9][A-Z0-9./_-]{2,40})"


def is_kyc_checklist_context(text: str) -> bool:
    """True when a page enumerates three or more identity-document names."""
    raw = str(text or "")
    mentions = sum(1 for pattern in _ID_DOC_MENTION_PATTERNS if pattern.search(raw))
    return mentions >= 3


def is_insurance_application_context(text: str) -> bool:
    """Return True for an insurer's proposal/application form.

    Insurance proposal forms legitimately use the generic heading
    ``Application Form`` and an insurer-local application number.  Requiring
    both an insurer/regulator marker and several insurance-specific fields
    keeps ordinary loan applications out of this semantic override.
    """
    raw = str(text or "")
    # ``insurance``, ``premium`` and ``nominee`` also occur in ordinary loan
    # applications that merely offer an optional add-on.  An override therefore
    # needs both a legal insurer anchor and an insurance-form heading near the
    # beginning of the page/document, not just a cluster of insurance words.
    heading_area = "\n".join(raw.splitlines()[:30])[:2500]
    if re.search(
        r"(?:^|\n)\s*(?:loan|housing|mortgage|business)\s+application\s+form\b",
        heading_area,
        re.IGNORECASE,
    ):
        return False
    has_insurer_marker = bool(_INSURER_LEGAL_MARKER.search(raw))
    has_form_boundary = bool(_INSURANCE_FORM_BOUNDARY.search(heading_area))
    if not (has_insurer_marker and has_form_boundary):
        return False
    field_families = sum(
        1 for pattern in _INSURANCE_APPLICATION_FIELD_PATTERNS if pattern.search(raw)
    )
    return field_families >= 3


def is_insurer_local_application_identifier(text: str, value: Any) -> bool:
    """True only when *value* is labelled as the insurer's own form ID.

    Health-insurance forms embedded in loan packets often print both an
    insurer-local ``Application No``/``Proposal No`` and the originating
    lender's ``Loan Application No`` or ``Loan Account No``.  The latter is
    useful loan evidence and must not be discarded merely because the page is
    an insurance form.
    """
    expected = _identifier_key(value)
    if not expected or not _INSURER_LEGAL_MARKER.search(str(text or "")):
        return False

    raw = str(text or "")
    loan_values = _insurance_identifier_values(
        raw,
        rf"\bloan\s+(?:application|account|a\s*/\s*c)\s*"
        rf"(?:number|no\.?|#)?\s*[:\-–#]?\s*{_INSURANCE_IDENTIFIER_VALUE}",
    )
    # An explicit loan label wins even if an OCR layout also makes the value
    # appear close to a generic Application No label.
    if expected in loan_values:
        return False

    local_values = _insurance_identifier_values(
        raw,
        rf"\bproposal\s*(?:number|no\.?|#)\s*[:\-–#]?\s*"
        rf"{_INSURANCE_IDENTIFIER_VALUE}",
    )
    local_values.update(
        _insurance_identifier_values(
            raw,
            rf"(?<!loan\s)(?<!customer\s)\b(?:insurance\s+)?application\s*"
            rf"(?:number|no\.?|#)\s*[:\-–#]?\s*{_INSURANCE_IDENTIFIER_VALUE}",
        )
    )
    return expected in local_values


def is_bank_statement_profile_context(text: str) -> bool:
    """Recognize account-aggregator statement cover pages before transactions."""
    raw = str(text or "")
    return bool(
        re.search(r"\bStatement\s+From\s*:", raw, re.IGNORECASE)
        and re.search(r"\bStatement\s+To\s*:", raw, re.IGNORECASE)
        and re.search(r"\bAccount\s+Number\b", raw, re.IGNORECASE)
        and re.search(r"(?:^|\n)\s*PROFILE\s*(?:\n|$)", raw, re.IGNORECASE)
        and re.search(r"(?:^|\n)\s*TRANSACTIONS\s*(?:\n|$)", raw, re.IGNORECASE)
    )


def _insurance_identifier_values(text: str, pattern: str) -> set[str]:
    return {
        key
        for match in re.finditer(pattern, text, re.IGNORECASE)
        if (key := _identifier_key(match.group(1)))
    }


def _identifier_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


class DocumentTypeConfig(BaseModel):
    """Validated registry schema for fields shared outside classification."""

    model_config = ConfigDict(extra="allow")

    type: str
    ocr_route: OCRRoute = "structured"
    has_tabular_data: bool = False
    multi_column: bool = False


def classify_page(text: str) -> dict[str, Any]:
    """Classify a page of text into a configured document type.

    Returns a backward-compatible payload containing at least
    ``document_type`` and ``confidence``.  Additional score metadata is
    included for callers that want to inspect how the decision was made.
    """
    result = classify_page_with_candidates(text)
    return {
        "document_type": result["document_type"],
        "confidence": result["confidence"],
        "matched_signals": result.get("matched_signals", []),
        "candidate_scores": result.get("candidate_scores", []),
    }


def classify_page_with_candidates(text: str) -> dict[str, Any]:
    registry = load_document_type_registry()
    candidates = [_score_rule(text or "", rule) for rule in registry["document_types"]]
    if is_kyc_checklist_context(text or ""):
        for candidate in candidates:
            if candidate["document_type"] in IDENTITY_CARD_TYPES and candidate["confidence"]:
                candidate["confidence"] = 0.0
                candidate["matched_signals"] = [
                    {"kind": "suppressed", "value": "kyc_checklist_context"}
                ]
    if is_insurance_application_context(text or ""):
        for candidate in candidates:
            if candidate["document_type"] == "Application Form":
                candidate["confidence"] = 0.0
                candidate["matched_signals"] = [
                    {"kind": "suppressed", "value": "insurance_application_context"}
                ]
            elif candidate["document_type"] == "Insurance Form":
                candidate["confidence"] = max(0.95, candidate["confidence"])
                candidate["matched_signals"] = [
                    *candidate["matched_signals"],
                    {"kind": "semantic", "value": "insurance_application_context"},
                ]
    if is_bank_statement_profile_context(text or ""):
        for candidate in candidates:
            if candidate["document_type"] == "Bank Statement":
                candidate["confidence"] = max(0.98, candidate["confidence"])
                candidate["matched_signals"] = [
                    *candidate["matched_signals"],
                    {"kind": "semantic", "value": "statement_profile_and_transactions"},
                ]
                break
    candidates.sort(
        key=lambda item: (
            -item["confidence"],
            -int(any(signal.get("kind") == "opening_heading" for signal in item["matched_signals"])),
            item["priority"],
        )
    )

    best = candidates[0] if candidates else _unknown_result([])
    threshold = float(registry.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
    if best["confidence"] < threshold:
        return _unknown_result(candidates)

    return {
        "document_type": best["document_type"],
        "confidence": best["confidence"],
        "matched_signals": best["matched_signals"],
        "candidate_scores": _public_candidates(candidates),
    }


@lru_cache(maxsize=4)
def load_document_type_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load the JSON registry.  The env var is useful for tests/local tuning."""
    registry_path = Path(path or os.getenv("DOCUMENT_TYPE_REGISTRY_PATH") or DEFAULT_REGISTRY_PATH)
    with registry_path.open("r", encoding="utf-8") as file:
        registry = json.load(file)

    document_types = registry.get("document_types")
    if not isinstance(document_types, list) or not document_types:
        raise ValueError(f"Document type registry {registry_path} has no document_types list")

    for index, rule in enumerate(document_types):
        if not rule.get("type"):
            raise ValueError(f"Document type registry rule at index {index} has no type")
        normalized_rule = DocumentTypeConfig.model_validate(rule).model_dump()
        rule.clear()
        rule.update(normalized_rule)
        rule.setdefault("priority", index)
        rule.setdefault("min_confidence", registry.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
        rule.setdefault("headings", [])
        rule.setdefault("keywords", [])
        rule.setdefault("required_any", [])
        rule.setdefault("required_regex", [])
        rule.setdefault("field_patterns", [])
        rule.setdefault("negative_keywords", [])

    return registry


def document_type_config(document_type: str) -> DocumentTypeConfig:
    """Return OCR/layout metadata for a type, using structured as the safe default."""
    normalized = str(document_type or "").strip().casefold()
    normalized = {"pan": "pan card", "aadhar": "aadhaar"}.get(normalized, normalized)
    for rule in load_document_type_registry()["document_types"]:
        if str(rule.get("type") or "").strip().casefold() == normalized:
            return DocumentTypeConfig.model_validate(rule)
    return DocumentTypeConfig(type=str(document_type or UNKNOWN_TYPE))


def registry_document_types(include_unknown: bool = True) -> list[str]:
    types = [str(rule["type"]) for rule in load_document_type_registry()["document_types"]]
    if include_unknown:
        types.append(UNKNOWN_TYPE)
    return types


def _score_rule(text: str, rule: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_text(text)
    # Combined loan packets can end one short letter and begin the next logical
    # document halfway down a page. Twenty-four lines remains header-biased but
    # still catches those embedded document boundaries.
    heading_area = _normalize_text("\n".join((text or "").splitlines()[:24])) or normalized[:2000]
    matched: list[dict[str, Any]] = []
    score = 0.0

    explicit_opening_heading = _has_explicit_opening_heading(
        text,
        rule.get("headings", []),
        max_lines=int(rule.get("opening_heading_lines") or 4),
    )
    if rule.get("boundary_evidence_required"):
        # Some words name both a document and an obligation mentioned inside
        # another document ("submit an affidavit", "execute a declaration").
        # Such types need either a title near the beginning or at least two
        # independent document-form signals. A single body reference must not
        # split the surrounding multi-page document.
        boundary_keyword_hits = {
            _normalize_text(term)
            for term in rule.get("keywords", [])
            if _contains(normalized, term)
        }
        if not explicit_opening_heading and len(boundary_keyword_hits) < 2:
            return _candidate(
                rule,
                0.0,
                [{"kind": "suppressed", "value": "missing_document_boundary_evidence"}],
            )
    negative_hits = [term for term in rule.get("negative_keywords", []) if _contains(normalized, term)]
    if negative_hits and not explicit_opening_heading:
        return _candidate(rule, 0.0, [{"kind": "negative_keyword", "value": term} for term in negative_hits])

    required_any = rule.get("required_any", [])
    if required_any and not any(_contains(normalized, term) for term in required_any):
        return _candidate(rule, 0.0, [])

    required_regex = rule.get("required_regex", [])
    if required_regex and not any(re.search(pattern, text or "", re.IGNORECASE | re.MULTILINE) for pattern in required_regex):
        return _candidate(rule, 0.0, [])

    heading_score, heading_matches = _heading_score(heading_area, rule.get("headings", []))
    score += heading_score
    matched.extend(heading_matches)
    if explicit_opening_heading:
        matched.append({"kind": "opening_heading", "value": "explicit document title"})

    keyword_score, keyword_matches = _keyword_score(normalized, rule.get("keywords", []))
    score += keyword_score
    matched.extend(keyword_matches)

    field_score, field_matches = _regex_score(text or "", rule.get("field_patterns", []), "field_pattern", 0.25)
    score += field_score
    matched.extend(field_matches)

    required_score, required_matches = _keyword_score(normalized, required_any, max_score=0.10, kind="required_keyword")
    score += required_score
    matched.extend(required_matches)

    required_regex_score, required_regex_matches = _regex_score(text or "", required_regex, "required_regex", 0.10)
    score += required_regex_score
    matched.extend(required_regex_matches)

    # Multiple independent signal families deserve high confidence.  Exact
    # legacy-style matches should remain 1.0 for compatibility.
    signal_kinds = {item["kind"] for item in matched}
    if {"heading", "keyword"} <= signal_kinds or {"heading", "field_pattern"} <= signal_kinds:
        score = max(1.0, score + 0.15)
    if len(signal_kinds) >= 3:
        score += 0.10

    confidence = round(min(1.0, score), 3)
    min_confidence = float(rule.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
    if confidence < min_confidence:
        confidence = 0.0

    return _candidate(rule, confidence, matched)


def _has_explicit_opening_heading(
    text: str,
    headings: list[str],
    *,
    max_lines: int = 4,
) -> bool:
    """Return True when a configured title opens the first few non-empty lines.

    Negative terms are useful for clause references, but legal documents often
    mention the underlying loan agreement immediately after their own title.
    An explicit opening title is stronger evidence than such body references.
    """
    opening_lines = [
        _normalize_text(line)
        for line in str(text or "").splitlines()
        if _normalize_text(line)
    ][:max(1, max_lines)]
    for line in opening_lines:
        for heading in headings:
            normalized_heading = _normalize_text(heading)
            if not normalized_heading:
                continue
            if line == normalized_heading:
                return True
            if line.startswith(f"{normalized_heading} "):
                remainder = line[len(normalized_heading):].strip(" -:|")
                if remainder.startswith(
                    ("this ", "made ", "executed ", "dated ", "between ", "by ", "at ")
                ):
                    return True
    return False


def _heading_score(text: str, headings: list[str]) -> tuple[float, list[dict[str, Any]]]:
    matches: list[dict[str, Any]] = []
    best = 0.0
    for heading in headings:
        normalized_heading = _normalize_text(heading)
        if not normalized_heading:
            continue
        if _contains(text, normalized_heading):
            best = max(best, 0.60)
            matches.append({"kind": "heading", "value": heading, "score": 1.0})
            continue
        # Fuzzy matching very short acronyms (for example NACH) against a long,
        # noisy OCR line produces accidental near-matches.  Acronyms must be
        # present as complete tokens; longer headings may still use fuzzy OCR
        # recovery.
        if len(normalized_heading.replace(" ", "")) <= 5:
            continue
        ratio = _partial_ratio(normalized_heading, text)
        if ratio >= 0.86:
            contribution = 0.52
        elif ratio >= 0.76:
            contribution = 0.42
        else:
            contribution = 0.0
        if contribution:
            best = max(best, contribution)
            matches.append({"kind": "heading_fuzzy", "value": heading, "score": round(ratio, 3)})
    return best, matches[:3]


def _keyword_score(
    text: str,
    keywords: list[str],
    *,
    max_score: float = 0.30,
    kind: str = "keyword",
) -> tuple[float, list[dict[str, Any]]]:
    if not keywords:
        return 0.0, []
    hits = [{"kind": kind, "value": term} for term in keywords if _contains(text, term)]
    if not hits:
        return 0.0, []
    # Keywords are synonyms and translations, not a checklist. Adding support
    # for another language must not dilute the score of existing languages.
    # One hit contributes half and two independent hits saturate the family.
    capped_ratio = min(1.0, len(hits) / 2.0)
    return max_score * capped_ratio, hits[:5]


def _regex_score(
    text: str,
    patterns: list[str],
    kind: str,
    max_score: float,
) -> tuple[float, list[dict[str, Any]]]:
    if not patterns:
        return 0.0, []
    hits = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            hits.append({"kind": kind, "value": pattern})
    if not hits:
        return 0.0, []
    return max_score * min(1.0, len(hits) / max(len(patterns), 1) * 2.0), hits[:4]


def _candidate(rule: dict[str, Any], confidence: float, matched: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "document_type": str(rule["type"]),
        "confidence": confidence,
        "priority": int(rule.get("priority", 9999)),
        "matched_signals": matched,
    }


def _unknown_result(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "document_type": UNKNOWN_TYPE,
        "confidence": 0.0,
        "matched_signals": [],
        "candidate_scores": _public_candidates(candidates),
    }


def _public_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_type": item["document_type"],
            "confidence": item["confidence"],
            "matched_signals": item.get("matched_signals", []),
        }
        for item in candidates[:5]
    ]


def _normalize_text(value: str) -> str:
    lowered = unicodedata.normalize("NFKC", str(value or "")).casefold()
    lowered = lowered.replace("\u2013", "-").replace("\u2014", "-")
    normalized = "".join(
        character
        if character.isalnum() or unicodedata.category(character).startswith("M")
        else " "
        for character in lowered
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _contains(text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    if normalized_term.isascii() and len(normalized_term.replace(" ", "")) <= 5:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", text))
    return normalized_term in text


def _partial_ratio(needle: str, haystack: str) -> float:
    if not needle or not haystack:
        return 0.0
    if fuzz is not None:
        return float(fuzz.partial_ratio(needle, haystack)) / 100.0

    window_size = max(len(needle), 1)
    if len(haystack) <= window_size:
        return SequenceMatcher(None, needle, haystack).ratio()
    best = 0.0
    step = max(1, window_size // 4)
    for start in range(0, len(haystack) - window_size + 1, step):
        window = haystack[start : start + window_size]
        best = max(best, SequenceMatcher(None, needle, window).ratio())
    return best
