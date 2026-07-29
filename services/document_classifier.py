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
    candidates.sort(key=lambda item: (-item["confidence"], item["priority"]))

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
    heading_area = _normalize_text("\n".join((text or "").splitlines()[:8])) or normalized[:1200]
    matched: list[dict[str, Any]] = []
    score = 0.0

    negative_hits = [term for term in rule.get("negative_keywords", []) if _contains(normalized, term)]
    if negative_hits:
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
    ratio = len(hits) / max(len(keywords), 1)
    # Do not require every synonym.  Two strong keyword hits are usually enough.
    capped_ratio = min(1.0, ratio * 2.0)
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
    lowered = str(value or "").lower()
    lowered = lowered.replace("\u2013", "-").replace("\u2014", "-")
    lowered = re.sub(r"[^0-9a-z\u0900-\u097f]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _contains(text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    if len(normalized_term.replace(" ", "")) <= 5:
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
