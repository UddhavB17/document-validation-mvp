"""Deterministic bureau anchors for CIBIL vs CRIF report pages."""

from __future__ import annotations

import re
from typing import Any


def classify_credit_bureau_by_anchors(text: str, layout_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic CIBIL/CRIF classification when anchors are clear."""
    normalized = _normalize(text)
    header = _normalize(_header_region(text, layout_metadata))
    matches: dict[str, list[str]] = {"cibil": [], "crif": []}
    cibil_score = 0.0
    crif_score = 0.0

    cibil_score += _add_if(matches, "cibil", "exact:TransUnion CIBIL", "transunion cibil" in normalized, 0.65)
    cibil_score += _add_if(matches, "cibil", "header:CIBIL", "cibil" in header, 0.30)
    cibil_score += _add_if(matches, "cibil", "term:CIBIL", _word_present(normalized, "cibil"), 0.30)
    cibil_score += _add_if(matches, "cibil", "field:control number", "control number" in normalized, 0.20)
    cibil_score += _add_if(matches, "cibil", "field:member id", "member id" in normalized, 0.15)
    cibil_score += _add_if(matches, "cibil", "score:cibil score", "cibil score" in normalized, 0.20)

    crif_score += _add_if(matches, "crif", "exact:CRIF High Mark", "crif high mark" in normalized, 0.65)
    crif_score += _add_if(matches, "crif", "header:CRIF", "crif" in header, 0.30)
    crif_score += _add_if(matches, "crif", "header:High Mark", "high mark" in header, 0.30)
    crif_score += _add_if(matches, "crif", "term:CRIF", _word_present(normalized, "crif"), 0.30)
    crif_score += _add_if(matches, "crif", "term:High Mark", "high mark" in normalized, 0.30)
    crif_score += _add_if(matches, "crif", "score:crif score", "crif score" in normalized, 0.20)

    cibil_score += _score_range_bonus(normalized, "cibil", matches)
    crif_score += _score_range_bonus(normalized, "crif", matches)

    if cibil_score >= 0.75 and cibil_score >= crif_score + 0.30:
        return _result("CIBIL Report", min(cibil_score, 1.0), cibil_score, crif_score, matches)
    if crif_score >= 0.75 and crif_score >= cibil_score + 0.30:
        return _result("CRIF Report", min(crif_score, 1.0), cibil_score, crif_score, matches)

    return {
        "document_type": None,
        "confidence": round(max(cibil_score, crif_score), 3),
        "cibil_score": round(cibil_score, 3),
        "crif_score": round(crif_score, 3),
        "matches": {key: value for key, value in matches.items() if value},
    }


def _header_region(text: str, layout_metadata: dict[str, Any] | None) -> str:
    if layout_metadata:
        header_text = layout_metadata.get("header_text")
        if header_text:
            return str(header_text)
    return "\n".join((text or "").splitlines()[:8])


def _add_if(matches: dict[str, list[str]], key: str, label: str, condition: bool, weight: float) -> float:
    if condition:
        matches[key].append(label)
        return weight
    return 0.0


def _score_range_bonus(normalized: str, bureau: str, matches: dict[str, list[str]]) -> float:
    if bureau not in normalized:
        return 0.0
    if re.search(r"\b(?:score|bureau score|credit score)\D{0,20}([3-8]\d{2}|900)\b", normalized):
        matches[bureau].append("score_range:300-900")
        return 0.10
    return 0.0


def _result(
    document_type: str,
    confidence: float,
    cibil_score: float,
    crif_score: float,
    matches: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "document_type": document_type,
        "confidence": round(confidence, 3),
        "cibil_score": round(cibil_score, 3),
        "crif_score": round(crif_score, 3),
        "matches": {key: value for key, value in matches.items() if value},
    }


def _normalize(value: str) -> str:
    lowered = str(value or "").lower()
    lowered = re.sub(r"[^0-9a-z]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _word_present(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text))
